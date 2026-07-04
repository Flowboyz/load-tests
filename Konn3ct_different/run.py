from gevent import monkey
monkey.patch_all()

# Patch gevent fork hooks to prevent Python 3.12 threading assert warning on child forks
try:
    import gevent.threading
    if hasattr(gevent.threading, '_ForkHooks'):
        original_after = gevent.threading._ForkHooks.after_fork_in_child
        def patched_after(self):
            try:
                original_after(self)
            except AssertionError:
                pass
        gevent.threading._ForkHooks.after_fork_in_child = patched_after
except Exception:
    pass

from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    import sys
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"⚠️ Invalid port '{sys.argv[1]}', using default 8000.")
            
    print("==================================================")
    print("🚀 Konn3ct Dashboard Server is starting up...")
    print(f"🔗 URL: http://localhost:{port}/")
    print(f"📢 Note: Ensure port {port} is allowed in your server's firewall.")
    print("==================================================")
    # Run development server using Socket.IO wrapper
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
