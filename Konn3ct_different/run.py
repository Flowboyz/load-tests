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
    print("==================================================")
    print("🚀 Konn3ct Dashboard Server is starting up...")
    print("🔗 URL: http://206.189.202.80:8000/ or http://localhost:8000/")
    print("📢 Note: Ensure port 8000 is allowed in your server's firewall.")
    print("==================================================")
    # Run development server using Socket.IO wrapper
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)
