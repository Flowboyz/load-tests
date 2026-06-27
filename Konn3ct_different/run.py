from gevent import monkey
monkey.patch_all()

from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    # Run development server using Socket.IO wrapper
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)
