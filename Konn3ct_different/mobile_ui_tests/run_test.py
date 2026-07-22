import subprocess
import os
import re

def list_emulators():
    """
    Returns list of connected Android devices via adb.
    On macOS, also queries simulator configurations for iOS (for future extensions).
    """
    devices = []
    
    # 1. Android ADB list
    try:
        # Run adb devices
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
        lines = res.stdout.strip().split("\n")
        for line in lines[1:]: # Skip the first "List of devices attached" line
            parts = re.split(r'\s+', line.strip())
            if len(parts) >= 2 and parts[1] == "device":
                devices.append({
                    "id": parts[0],
                    "name": f"Android Device ({parts[0]})",
                    "type": "android"
                })
    except Exception:
        pass # ADB not in PATH or not running
        
    # 2. iOS Simulator list (only if on macOS, but safe check)
    if os.name != "nt":
        try:
            res = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"], capture_output=True, text=True, timeout=5)
            lines = res.stdout.strip().split("\n")
            for line in lines:
                match = re.search(r'^\s*([^\(]+)\s*\(([A-F0-9\-]+)\)\s*\(Booted\)', line)
                if match:
                    devices.append({
                        "id": match.group(2),
                        "name": f"iOS Simulator ({match.group(1).strip()})",
                        "type": "ios"
                    })
        except Exception:
            pass
            
    # Always offer Maestro Cloud as an execution target
    devices.append({
        "id": "maestro_cloud",
        "name": "Maestro Cloud (SaaS Headless Run)",
        "type": "android"
    })
    
    # Add a fallback mock device for testing UI when no emulators are connected
    if len(devices) == 1:
        devices.append({
            "id": "mock_android_emulator",
            "name": "Demo Android Emulator (Mock)",
            "type": "android"
        })
        
    return devices

def execute_flow_generator(flow_path, device_id=None, apk_path=None, api_key=None, cloud_model=None, cloud_os=None, on_process_spawned=None):
    """
    Generator yielding console log lines as Maestro executes the test.
    Supports local device testing and cloud-based testing (Maestro Cloud).
    """
    # 1. Handle mock run
    if device_id == "mock_android_emulator":
        yield "ℹ️ [MOCK RUN] Starting Maestro Test Suite..."
        yield f"ℹ️ Selected Flow File: {os.path.basename(flow_path)}"
        yield "🚀 Step 1: launchApp -> [SUCCESS]"
        yield "🚀 Step 2: tapOn Room Code -> [SUCCESS]"
        yield "🚀 Step 3: inputText 1govtest -> [SUCCESS]"
        yield "🚀 Step 4: tapOn Join Meeting -> [SUCCESS]"
        yield "🚀 Step 5: assertVisible Mute Microphone -> [SUCCESS]"
        yield "🎉 [MOCK RUN] All Maestro steps completed successfully!"
        return

    # 2. Build command for Maestro Cloud or local test
    if device_id == "maestro_cloud":
        if not apk_path:
            yield "❌ ERROR: Maestro Cloud requires a path to your app APK."
            return
            
        # Resolve APK path relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_apk_path = os.path.abspath(os.path.join(project_root, apk_path))
        if not os.path.exists(abs_apk_path):
            abs_apk_path = os.path.abspath(apk_path)
            if not os.path.exists(abs_apk_path):
                yield f"❌ ERROR: APK file not found at path: {apk_path}"
                return
                
        cmd = ["maestro", "cloud"]
        if api_key:
            cmd.extend(["--apiKey", api_key])
        if cloud_model:
            cmd.extend(["--device-model", cloud_model])
        if cloud_os:
            cmd.extend(["--device-os", str(cloud_os)])
        cmd.extend([abs_apk_path, flow_path])
        yield "ℹ️ Initializing Maestro Cloud run..."
        yield f"🚀 Uploading APK: {os.path.basename(abs_apk_path)}"
        yield f"🚀 Uploading Flow: {os.path.basename(flow_path)}"
        if cloud_model:
            yield f"🚀 Cloud Device Model: {cloud_model}"
        if cloud_os:
            yield f"🚀 Cloud Android OS Version: API {cloud_os}"
    else:
        cmd = ["maestro"]
        if device_id:
            cmd.extend(["--device", device_id])
        cmd.extend(["test", flow_path])
        yield "ℹ️ Initializing Maestro execution environment..."
        yield f"🚀 Target Device: {device_id or 'Default'}"
        
    try:
        # Run process, redirecting stderr to stdout to catch all output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        if on_process_spawned:
            on_process_spawned(process)
        for line in process.stdout:
            line_str = line.rstrip()
            # If the output contains a run link, highlight it
            if "console.mobile.dev/runs/" in line_str or "cloud.mobile.dev/runs/" in line_str or "app.maestro.dev/" in line_str:
                match = re.search(r'(https://(console|cloud)\.mobile\.dev/runs/\S+|https://app\.maestro\.dev/\S+)', line_str)
                if match:
                    url = match.group(1)
                    yield f"🔗 LINK: {url}"
            yield line_str
        process.wait()
        if process.returncode == 0:
            yield "🎉 Maestro execution completed successfully!"
        else:
            yield f"❌ Maestro failed with exit code: {process.returncode}"
    except FileNotFoundError:
        yield "❌ ERROR: Maestro CLI is not installed or not in PATH."
        yield "💡 Please install it via: https://maestro.mobile.dev"
    except Exception as e:
        yield f"❌ Unexpected execution error: {e}"
