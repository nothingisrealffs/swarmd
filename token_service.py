from flask import Flask, request, jsonify
import jwt
import os
import time
import uuid
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64

app = Flask(__name__)

# Load or generate secret key for JWT signing
SECRET_KEY_FILE = '/tokens/secret.key'
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, 'rb') as f:
        SECRET_KEY = f.read()
else:
    # Generate a secure random key
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    SECRET_KEY = kdf.derive(os.urandom(32))
    with open(SECRET_KEY_FILE, 'wb') as f:
        f.write(SECRET_KEY)

# Store valid tokens (in production, use Redis or another persistent store)
VALID_TOKENS = {}
TOKEN_DIR = '/tokens'
os.makedirs(TOKEN_DIR, exist_ok=True)

# Load existing tokens
def load_tokens():
    for filename in os.listdir(TOKEN_DIR):
        if filename.endswith('.token'):
            token_file = os.path.join(TOKEN_DIR, filename)
            with open(token_file, 'r') as f:
                token_data = f.read().strip().split('|')
                if len(token_data) >= 3:
                    node_id, token, role = token_data[:3]
                    VALID_TOKENS[token] = {
                        'node_id': node_id,
                        'role': role,
                        'created': int(time.time())
                    }

load_tokens()

@app.route('/token/generate', methods=['POST'])
def generate_token():
    # Validate API key for token generation
    api_key = request.headers.get('X-API-Key')
    
    with open('/tokens/admin.key', 'r') as f:
        valid_api_key = f.read().strip()
    
    if api_key != valid_api_key:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    node_id = data.get('node_id')
    role = data.get('role', 'worker')
    
    if not node_id:
        return jsonify({'error': 'Missing node_id'}), 400
    
    # Generate a unique token
    token_uuid = str(uuid.uuid4())
    exp_time = int(time.time()) + 86400  # 24 hours
    
    payload = {
        'node_id': node_id,
        'role': role,
        'exp': exp_time
    }
    
    # Create JWT token
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    
    # Store token
    VALID_TOKENS[token] = {
        'node_id': node_id,
        'role': role,
        'created': int(time.time())
    }
    
    # Save token to file for persistence
    with open(f'/tokens/{node_id}.token', 'w') as f:
        f.write(f"{node_id}|{token}|{role}")
    
    return jsonify({
        'token': token,
        'expires': exp_time,
        'node_id': node_id,
        'role': role
    })

@app.route('/token/validate', methods=['POST'])
def validate_token():
    data = request.get_json()
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Missing token'}), 400
    
    # Check if token exists in our valid tokens
    if token not in VALID_TOKENS:
        return jsonify({'valid': False, 'error': 'Invalid token'}), 401
    
    try:
        # Decode and validate JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        
        # Check if token has expired
        if 'exp' in payload and payload['exp'] < time.time():
            return jsonify({'valid': False, 'error': 'Token expired'}), 401
        
        # Return token data
        return jsonify({
            'valid': True,
            'node_id': payload.get('node_id'),
            'role': payload.get('role', 'worker'),
            'swarm_join_token': get_swarm_token(payload.get('role', 'worker')),
            'manager_ip': get_manager_ip()
        })
        
    except jwt.PyJWTError as e:
        return jsonify({'valid': False, 'error': str(e)}), 401

def get_swarm_token(role):
    """Get the appropriate Swarm join token"""
    try:
        if role.lower() == 'manager':
            result = os.popen('docker swarm join-token manager -q').read().strip()
        else:
            result = os.popen('docker swarm join-token worker -q').read().strip()
        return result
    except Exception as e:
        return str(e)

def get_manager_ip():
    """Get the manager node IP address"""
    # This gets the container's IP, adjust if needed for your network setup
    try:
        result = os.popen("hostname -i | awk '{print $1}'").read().strip()
        return result
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    # Generate admin API key if it doesn't exist
    admin_key_file = '/tokens/admin.key'
    if not os.path.exists(admin_key_file):
        admin_key = base64.b64encode(os.urandom(32)).decode('utf-8')
        with open(admin_key_file, 'w') as f:
            f.write(admin_key)
        print(f"Generated admin API key: {admin_key}")
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=8000)