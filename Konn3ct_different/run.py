from gevent import monkey
monkey.patch_all()

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
