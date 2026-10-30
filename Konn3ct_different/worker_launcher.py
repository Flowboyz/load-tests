import sys
import os
import subprocess
import signal
import time
import argparse
import datetime
import glob
import json

# Ensure stdout uses UTF-8 encoding
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def main():
    parser = argparse.ArgumentParser(description="Multi-process orchestrator for high-scale load testing")
    
    # Orchestrator parameters
    parser.add_argument('--bots', type=int, default=20000, help="Total number of bots")
    parser.add_argument('--workers', type=int, default=10, help="Number of worker processes to spawn")
    parser.add_argument('--worker-stagger', type=float, default=5.0, help="Seconds between launching each worker process")
    
    # Target environment
    parser.add_argument('--room', type=str, default='testinggg', help="Room ID")
    parser.add_argument('--frontend', type=str, default='https://edge.konn3ct.net', help="Frontend URL")
    parser.add_argument('--signal', type=str, default='konn3ctedge.konn3ct.net', help="Signal domain")
    parser.add_argument('--jwt-secret', type=str, default=None, help="JWT secret for local auth")
    parser.add_argument('--webrtc-enabled', action='store_true', help="Enable WebRTC")
    
    # Test duration
    parser.add_argument('--leave', type=int, default=0, help="Duration in minutes (0 = infinite)")
    
    # Worker batch settings
    parser.add_argument('--batch', type=int, default=20, help="Bots per batch in each worker")
    parser.add_argument('--stagger', type=float, default=0.3, help="Stagger between batches in each worker")
    parser.add_argument('--concurrency', type=int, default=2500, help="Concurrency per worker")
    
    # Bot behaviors and roles
    parser.add_argument('--lightweight', action='store_true', help="Enable lightweight viewer mode")
    parser.add_argument('--large-room-mode', action='store_true', help="Enable tiered large room mode")
    parser.add_argument('--speaker-promotion-storm', action='store_true', help="Enable dynamic viewer hand-raise storms and host promotion/demotion lifecycle")
    parser.add_argument('--conversational-audio', action='store_true', default=True, help="Simulate natural conversational speech bursts")
    parser.add_argument('--test-scenarios', type=str, default='camera_toggle,mic_toggle,hand_raise,chat', help="Test scenarios comma-separated list")
    parser.add_argument('--host-bot-id', type=int, default=1, help="Bot ID assigned as host")
    parser.add_argument('--presenter-bot-id', type=int, default=2, help="Bot ID assigned as presenter")
    parser.add_argument('--camera-publishers', type=str, default='1,2,3,4,5', help="Camera publisher bot IDs")
    parser.add_argument('--mic-publishers', type=str, default='1,2,3,4,5', help="Mic publisher bot IDs")
    parser.add_argument('--screen-share-publishers', type=str, default='2', help="Screen share publisher bot IDs")
    parser.add_argument('--viewer-bots', type=str, default='11-100000', help="Viewer bot ID range")
    
    # Network and reliability
    parser.add_argument('--no-cross-confirm', action='store_true', help="Disable cross confirmation")
    parser.add_argument('--cross-confirm-limit', type=int, default=3, help="Cross confirm limit")
    parser.add_argument('--max-retries', type=int, default=10, help="Max reconnection retries")
    parser.add_argument('--media-quality', type=str, default='low', help="Media quality")
    parser.add_argument('--network-conditions', type=str, default='ethernet:20,wi-fi:50,4g:20,3g:10', help="Network conditions distribution")
    
    # Intervals for actions
    parser.add_argument('--action-interval', type=float, default=120, help="Action interval")
    parser.add_argument('--chat-interval', type=float, default=180, help="Chat interval")
    
    # Disabled features
    parser.add_argument('--no-chat', action='store_true', help="Disable chat")
    parser.add_argument('--no-camera', action='store_true', help="Disable camera")
    parser.add_argument('--no-mic', action='store_true', help="Disable mic")
    parser.add_argument('--no-handraise', action='store_true', help="Disable handraise")
    parser.add_argument('--no-screen-share', action='store_true', help="Disable screen share")

    # Reporting
    parser.add_argument('--report-output', type=str, default='load_test_20k_report.docx', help="Final merged report output")

    args = parser.parse_args()
    args.jwt_secret = args.jwt_secret or os.environ.get("JWT_SECRET") or None

    total_bots = args.bots
    workers = args.workers
    
    # Calculate bots per worker
    bots_per_worker = total_bots // workers
    remainder = total_bots % workers

    base_dir = os.path.dirname(os.path.abspath(__file__))
    py_guest_path = os.path.join(base_dir, 'py_guest.py')
    generate_report_path = os.path.join(base_dir, 'generate_report.py')

    print("=========================================")
    print(f" Multi-Process Load Test Orchestrator")
    print(f" Total Bots: {total_bots}")
    print(f" Workers: {workers}")
    print(f" Bots/Worker: {bots_per_worker} (Remainder: {remainder} for last worker)")
    print("=========================================")

    processes = []
    current_start_id = 1

    # Clean up old chunk logs before starting
    for old_log in glob.glob(os.path.join(base_dir, "report_log_chunk_*.jsonl")):
        try:
            os.remove(old_log)
        except OSError:
            pass
    combined_log_path = os.path.join(base_dir, "report_log_combined.jsonl")
    if os.path.exists(combined_log_path):
        try:
            os.remove(combined_log_path)
        except OSError:
            pass

    # Launch worker processes
    for i in range(workers):
        # The last worker handles any remaining bots
        chunk_size = bots_per_worker + (1 if i < remainder else 0)
        report_log_file = f"report_log_chunk_{i}.jsonl"
        startup_delay = i * args.worker_stagger

        cmd = [
            sys.executable, py_guest_path,
            '--room', args.room,
            '--frontend', args.frontend,
            '--signal', args.signal,
            '--bots', str(chunk_size),
            '--start-id', str(current_start_id),
            '--leave', str(args.leave),
            '--batch', str(args.batch),
            '--stagger', str(args.stagger),
            '--report-log', report_log_file,
            '--camera-publishers', args.camera_publishers,
            '--mic-publishers', args.mic_publishers,
            '--screen-share-publishers', args.screen_share_publishers,
            '--viewer-bots', args.viewer_bots,
            '--cross-confirm-limit', str(args.cross_confirm_limit),
            '--max-retries', str(args.max_retries),
            '--media-quality', args.media_quality,
            '--network-conditions', args.network_conditions,
            '--action-interval', str(args.action_interval),
            '--chat-interval', str(args.chat_interval),
            '--concurrency', str(args.concurrency),
            '--test-scenarios', args.test_scenarios,
            '--host-bot-id', str(args.host_bot_id),
            '--presenter-bot-id', str(args.presenter_bot_id),
            '--startup-delay', str(startup_delay)
        ]
        
        # Add optional boolean flags and arguments
        if args.jwt_secret:
            cmd.extend(['--jwt-secret', args.jwt_secret])
        if args.webrtc_enabled:
            cmd.append('--webrtc-enabled')
        if args.lightweight:
            cmd.append('--lightweight')
        if args.large_room_mode:
            cmd.append('--large-room-mode')
        if args.speaker_promotion_storm:
            cmd.append('--speaker-promotion-storm')
        if args.conversational_audio:
            cmd.append('--conversational-audio')
        if args.no_cross_confirm:
            cmd.append('--no-cross-confirm')
        if args.no_chat:
            cmd.append('--no-chat')
        if args.no_camera:
            cmd.append('--no-camera')
        if args.no_mic:
            cmd.append('--no-mic')
        if args.no_handraise:
            cmd.append('--no-handraise')
        if args.no_screen_share:
            cmd.append('--no-screen-share')

        time_str = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"[{time_str}] Launching Worker {i}: {chunk_size} bots starting at ID {current_start_id}")
        
        p = subprocess.Popen(cmd, cwd=base_dir)
        processes.append((i, p))
        
        current_start_id += chunk_size
        
        # Sleep slightly before launching next to avoid thundering herd on OS resources, 
        # though the actual bot stagger is handled by py_guest.py and the --startup-delay
        time.sleep(0.5)

    stop_requested = False

    def terminate_all(signum=None, frame=None):
        nonlocal stop_requested
        stop_requested = True
        time_str = datetime.datetime.now().strftime('%H:%M:%S')
        print(f"\n[{time_str}] Received signal {signum}, terminating all workers...")
        for i, p in processes:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception as e:
                    print(f"Failed to terminate worker {i}: {e}")
                    
        print("Waiting 5 seconds for processes to exit...")
        time.sleep(5)
        
        for i, p in processes:
            if p.poll() is None:
                try:
                    print(f"Worker {i} still running, sending SIGKILL...")
                    p.kill()
                except Exception as e:
                    print(f"Failed to kill worker {i}: {e}")

    # Register signal handlers
    signal.signal(signal.SIGINT, terminate_all)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, terminate_all)

    # Monitor loop
    try:
        while not stop_requested:
            alive_count = 0
            for i, p in processes:
                if p.poll() is None:
                    alive_count += 1
                else:
                    if p.returncode != 0:
                        time_str = datetime.datetime.now().strftime('%H:%M:%S')
                        print(f"[{time_str}] Worker {i} exited unexpectedly with code {p.returncode}")
            
            time_str = datetime.datetime.now().strftime('%H:%M:%S')
            print(f"[{time_str}] Workers alive: {alive_count}/{workers}")
            
            if alive_count == 0:
                print(f"[{time_str}] All workers finished.")
                break
                
            time.sleep(10)
    except KeyboardInterrupt:
        # KeyboardInterrupt is also caught by the signal handler, but we pass here to allow exit flow
        pass
    
    # Merge logs and generate report after all workers exit (streamed to prevent OOM on 20K+ runs)
    time_str = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"\n[{time_str}] Merging worker logs into {combined_log_path}...")
    
    merged_count = 0
    wrote_header = False
    with open(combined_log_path, 'w', encoding='utf-8') as out_f:
        for i in range(workers):
            chunk_log = os.path.join(base_dir, f"report_log_chunk_{i}.jsonl")
            if os.path.exists(chunk_log):
                try:
                    with open(chunk_log, 'r', encoding='utf-8') as in_f:
                        for line in in_f:
                            stripped = line.strip()
                            if not stripped:
                                continue
                            if '"test_started"' in stripped:
                                if wrote_header:
                                    continue
                                wrote_header = True
                            out_f.write(stripped + '\n')
                            merged_count += 1
                    os.remove(chunk_log)
                except Exception as e:
                    print(f"Error merging chunk {chunk_log}: {e}")
            
    time_str = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"[{time_str}] Successfully merged {merged_count} log events.")
    
    # Run report generator
    if os.path.exists(generate_report_path):
        print(f"[{time_str}] Generating final report...")
        report_cmd = [
            sys.executable, generate_report_path,
            combined_log_path,
            '--output', args.report_output
        ]
        
        try:
            subprocess.run(report_cmd, check=True, cwd=base_dir)
            time_str = datetime.datetime.now().strftime('%H:%M:%S')
            print(f"[{time_str}] Final report successfully generated: {args.report_output}")
        except subprocess.CalledProcessError as e:
            print(f"Error generating report: {e}")
    else:
        print(f"[{time_str}] Report generator not found at {generate_report_path}, skipping report generation.")

if __name__ == "__main__":
    main()
