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
            
    # Add a fallback mock device for testing UI when no emulators are connected
    if not devices:
        devices.append({
            "id": "mock_android_emulator",
            "name": "Demo Android Emulator (Mock)",
            "type": "android"
        })
        
    return devices

def execute_flow_generator(flow_path, device_id=None):
    """
    Generator yielding console log lines as Maestro executes the test.
    """
    cmd = ["maestro"]
    if device_id and device_id != "mock_android_emulator":
        cmd.extend(["--device", device_id])
    cmd.extend(["test", flow_path])
    
    # Handle mock run
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

    try:
        # Run process, redirecting stderr to stdout to catch all output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            yield line.rstrip()
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
