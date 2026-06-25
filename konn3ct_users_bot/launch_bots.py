import subprocess
import time
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Bot Launcher — runs single bots one after another")
    parser.add_argument("--url", required=True, help="Meeting URL")
    parser.add_argument("--bots", type=int, default=10, help="Number of bots to launch")
    parser.add_argument("--delay", type=float, default=5.0, help="Seconds to wait between launching bots")
    parser.add_argument("--leave", type=int, default=0, help="Auto-leave after N minutes")
    args = parser.parse_args()

    print(f"🚀 Launching {args.bots} bots one by one (delay: {args.delay}s)...")
    
    processes = []
    
    try:
        for i in range(1, args.bots + 1):
            print(f"[{i}/{args.bots}] Starting bot...")
            
            # Build the command
            cmd = [sys.executable, "py_guest_single.py", "--url", args.url]
            if args.leave > 0:
                cmd.extend(["--leave", str(args.leave)])
                
            # Launch as a background process
            p = subprocess.Popen(cmd)
            processes.append(p)
            
            # Wait before launching the next one
            if i < args.bots:
                time.sleep(args.delay)
                
        print(f"\n✅ All {args.bots} bots launched!")
        print("Press Ctrl+C to stop all bots and exit.")
        
        # Keep the main script alive while bots run
        for p in processes:
            p.wait()
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping all bots...")
        for p in processes:
            p.terminate()
        print("Done.")

if __name__ == "__main__":
    main()
