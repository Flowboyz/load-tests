import os
import datetime
import jwt
from flask import Blueprint, request, jsonify, make_response, current_app
from functools import wraps
from app.models import db, User

auth_bp = Blueprint('auth', __name__)

SECRET_KEY = os.environ.get("DASHBOARD_SECRET_KEY", "konn3ct-super-secret-key-12345")

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check Authorization header first
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        # Fallback to cookies
        if not token:
            token = request.cookies.get('token')
            
        # Check API Key header
        api_key = request.headers.get('X-API-Key')
        if api_key:
            user = User.query.filter_by(api_key=api_key).first()
            if user:
                request.current_user = user
                return f(*args, **kwargs)
        
        if not token:
            return jsonify({'message': 'Authentication token is missing!'}), 401
            
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user = User.query.filter_by(id=data['user_id']).first()
            if not user:
                return jsonify({'message': 'Invalid token, user not found!'}), 401
            request.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token!'}), 401
            
        return f(*args, **kwargs)
    return decorated

def roles_accepted(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = getattr(request, 'current_user', None)
            if not user:
                return jsonify({'message': 'Authentication required!'}), 401
            if user.role not in roles:
                return jsonify({'message': 'Access forbidden: Insufficient permissions!'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'message': 'Username and password are required!'}), 400
        
    user = User.query.filter_by(username=username).first()
    
    if not user or not user.check_password(password):
        return jsonify({'message': 'Invalid credentials!'}), 401
        
    # Generate JWT token valid for 24 hours
    token = jwt.encode({
        'user_id': user.id,
        'role': user.role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, SECRET_KEY, algorithm="HS256")
    
    response = make_response(jsonify({
        'message': 'Login successful!',
        'user': user.to_dict()
    }))
    
    # Set JWT in HttpOnly secure cookie
    response.set_cookie(
        'token',
        token,
        httponly=True,
        secure=request.is_secure,
        samesite='Lax',
        max_age=24 * 60 * 60  # 24 hours
    )
    return response

@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({'message': 'Logout successful!'}))
    response.delete_cookie('token')
    return response

@auth_bp.route('/me', methods=['GET'])
@token_required
def me():
    return jsonify(request.current_user.to_dict())
