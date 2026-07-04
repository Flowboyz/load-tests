import time
import sys
import json
import urllib.request
import urllib.error

# Attempt to import psutil, print helpful error if missing
try:
    import psutil
except ImportError:
    print("❌ Error: psutil is not installed.")
    print("💡 Please install it via: pip install psutil")
    sys.exit(1)

def get_telemetry():
    """Queries CPU and RAM utilization metrics."""
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return {
        "cpu_usage": cpu,
        "ram_usage": ram
    }

def post_telemetry(url, data):
    """Sends telemetry data to the Master dashboard controller."""
    req_url = f"{url.rstrip('/')}/api/server/telemetry"
    body = json.dumps(data).encode("utf-8")
    
    req = urllib.request.Request(
        req_url,
        data=body,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            if res.status == 200:
                return True
    except urllib.error.URLError as e:
        print(f"⚠️ Connection error posting to {req_url}: {e.reason}")
    except Exception as e:
        print(f"⚠️ Unexpected error posting telemetry: {e}")
    return False

def main():
    if len(sys.argv) < 2:
        print("💡 Usage: python server_telemetry_agent.py <Master_Dashboard_URL>")
        print("Example: python server_telemetry_agent.py http://localhost:8000")
        sys.exit(1)
        
    master_url = sys.argv[1]
    print(f"🚀 Konn3ct Target Server Telemetry Agent Started.")
    print(f"🔗 Target Master Dashboard: {master_url}")
    print("📈 Press Ctrl+C to terminate...")
    
    # First CPU query can return 0.0, so query once to initialize
    psutil.cpu_percent(interval=None)
    time.sleep(0.5)

    try:
        while True:
            stats = get_telemetry()
            success = post_telemetry(master_url, stats)
            if success:
                print(f"📊 Telemetry Sent -> CPU: {stats['cpu_usage']:.1f}% | RAM: {stats['ram_usage']:.1f}%")
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n👋 Telemetry agent stopped gracefully.")

if __name__ == "__main__":
    main()
