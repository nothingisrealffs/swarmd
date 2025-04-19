from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import json
import subprocess
import threading
import time
import os
import uuid
import tempfile
import shutil
import datetime
import werkzeug.utils

# Configuration
DB_PATH = "/data/swarm_monitor.db"
UPLOAD_FOLDER = "/data/uploads"
REGISTRY_HOST = os.environ.get("REGISTRY_HOST", "127.0.0.1")
REGISTRY_PORT = os.environ.get("REGISTRY_PORT", "5000")
MONITOR_PORT = int(os.environ.get("MONITOR_PORT", "8001"))

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # Limit uploads to 500MB

# Database connection helper
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Execute Docker command and return JSON result
def execute_docker_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command error: {e}")
        print(f"Error output: {e.stderr}")
        return None

# Log event to database
def log_event(event_type, object_type, object_id, details=None):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO events (event_type, object_type, object_id, details) VALUES (?, ?, ?, ?)",
            (event_type, object_type, object_id, details)
        )
        conn.commit()
    finally:
        conn.close()

# Background worker to update database with current state
def update_data_worker():
    while True:
        try:
            update_nodes()
            update_services()
            update_containers()
            update_images()
        except Exception as e:
            print(f"Error in update worker: {e}")
        
        # Sleep for 30 seconds before next update
        time.sleep(30)

# Update nodes information
def update_nodes():
    nodes_json = execute_docker_cmd("docker node ls --format '{{json .}}'")
    if not nodes_json:
        return
    
    conn = get_db_connection()
    try:
        # Split multiple JSON objects if needed
        nodes = [json.loads(node) for node in nodes_json.strip().split('\n') if node]
        
        for node in nodes:
            node_id = node.get('ID', '')
            hostname = node.get('Hostname', '')
            role = 'manager' if 'Leader' in node.get('ManagerStatus', '') else 'worker'
            status = node.get('Status', '')
            availability = node.get('Availability', '')
            
            # Get IP address from node inspect
            ip_address = ""
            node_inspect = execute_docker_cmd(f"docker node inspect {node_id} --format '{{{{.Status.Addr}}}}'")
            if node_inspect:
                ip_address = node_inspect
            
            conn.execute(
                """INSERT OR REPLACE INTO nodes 
                   (id, hostname, ip_address, role, status, availability, last_updated) 
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (node_id, hostname, ip_address, role, status, availability)
            )
        
        conn.commit()
    finally:
        conn.close()

# Update services information
def update_services():
    services_json = execute_docker_cmd("docker service ls --format '{{json .}}'")
    if not services_json:
        return
    
    conn = get_db_connection()
    try:
        # Split multiple JSON objects if needed
        services = [json.loads(service) for service in services_json.strip().split('\n') if service]
        
        for service in services:
            service_id = service.get('ID', '')
            name = service.get('Name', '')
            image = service.get('Image', '')
            replicas_str = service.get('Replicas', '0/0')
            replicas = int(replicas_str.split('/')[0]) if '/' in replicas_str else 0
            status = 'active' if replicas > 0 else 'inactive'
            
            # Get timestamps from service inspect
            created_at = datetime.datetime.now().isoformat()
            updated_at = created_at
            
            service_inspect = execute_docker_cmd(f"docker service inspect {service_id}")
            if service_inspect:
                try:
                    inspect_data = json.loads(service_inspect)
                    if isinstance(inspect_data, list) and len(inspect_data) > 0:
                        created_at = inspect_data[0].get('CreatedAt', created_at)
                        updated_at = inspect_data[0].get('UpdatedAt', updated_at)
                except json.JSONDecodeError:
                    pass
            
            conn.execute(
                """INSERT OR REPLACE INTO services 
                   (id, name, image, replicas, status, created_at, updated_at, last_updated) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (service_id, name, image, replicas, status, created_at, updated_at)
            )
        
        conn.commit()
    finally:
        conn.close()

# Update containers information
def update_containers():
    containers_json = execute_docker_cmd("docker ps -a --format '{{json .}}'")
    if not containers_json:
        return
    
    conn = get_db_connection()
    try:
        # Split multiple JSON objects if needed
        containers = [json.loads(container) for container in containers_json.strip().split('\n') if container]
        
        for container in containers:
            container_id = container.get('ID', '')
            image = container.get('Image', '')
            command = container.get('Command', '')
            status = container.get('Status', '')
            state = 'running' if status.lower().startswith('up') else 'stopped'
            created_at = container.get('CreatedAt', datetime.datetime.now().isoformat())
            ports = container.get('Ports', '')
            
            # Get node ID from container info (for swarm containers)
            node_id = None
            service_id = None
            
            container_inspect = execute_docker_cmd(f"docker inspect {container_id}")
            if container_inspect:
                try:
                    inspect_data = json.loads(container_inspect)
                    if isinstance(inspect_data, list) and len(inspect_data) > 0:
                        # Extract data from inspect
                        node_id = inspect_data[0].get('Node', {}).get('ID', None)
                        service_id = inspect_data[0].get('Service', {}).get('ID', None)
                        
                        # Get timestamp info
                        state_data = inspect_data[0].get('State', {})
                        started_at = state_data.get('StartedAt', None)
                        finished_at = state_data.get('FinishedAt', None)
                        
                        conn.execute(
                            """INSERT OR REPLACE INTO containers 
                               (id, service_id, node_id, image, command, status, state, 
                                created_at, started_at, finished_at, ports, last_updated) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                            (container_id, service_id, node_id, image, command, status, 
                             state, created_at, started_at, finished_at, ports)
                        )
                except json.JSONDecodeError:
                    pass
        
        conn.commit()
    finally:
        conn.close()

# Update images information
def update_images():
    images_json = execute_docker_cmd("docker image ls --format '{{json .}}'")
    if not images_json:
        return
    
    conn = get_db_connection()
    try:
        # Split multiple JSON objects if needed
        images = [json.loads(image) for image in images_json.strip().split('\n') if image]
        
        for image in images:
            image_id = image.get('ID', '')
            repository = image.get('Repository', '')
            tag = image.get('Tag', '')
            size_bytes = 0
            
            # Convert size string to bytes
            size_str = image.get('Size', '0')
            size_parts = size_str.split()
            if len(size_parts) >= 2:
                try:
                    size_num = float(size_parts[0])
                    unit = size_parts[1].upper()
                    
                    # Convert to bytes based on unit
                    multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                    if unit in multipliers:
                        size_bytes = int(size_num * multipliers[unit])
                except ValueError:
                    pass
            
            created_at = image.get('CreatedAt', datetime.datetime.now().isoformat())
            digest = image.get('Digest', '')
            
            conn.execute(
                """INSERT OR REPLACE INTO images 
                   (id, repository, tag, digest, size_bytes, created_at, last_updated) 
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (image_id, repository, tag, digest, size_bytes, created_at)
            )
        
        conn.commit()
    finally:
        conn.close()

# API Routes

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get overall system status"""
    conn = get_db_connection()
    try:
        nodes = conn.execute('SELECT COUNT(*) as count FROM nodes').fetchone()
        services = conn.execute('SELECT COUNT(*) as count FROM services').fetchone()
        containers = conn.execute('SELECT COUNT(*) as count FROM containers').fetchone()
        running = conn.execute("SELECT COUNT(*) as count FROM containers WHERE state = 'running'").fetchone()
        
        return jsonify({
            'status': 'healthy',
            'nodes': nodes['count'],
            'services': services['count'],
            'containers': containers['count'],
            'running_containers': running['count'],
            'timestamp': datetime.datetime.now().isoformat()
        })
    finally:
        conn.close()

@app.route('/api/nodes', methods=['GET'])
def get_nodes():
    """Get all nodes in the swarm"""
    conn = get_db_connection()
    try:
        nodes = conn.execute('SELECT * FROM nodes').fetchall()
        return jsonify([dict(node) for node in nodes])
    finally:
        conn.close()

@app.route('/api/nodes/<node_id>', methods=['GET'])
def get_node(node_id):
    """Get detailed information about a specific node"""
    conn = get_db_connection()
    try:
        node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        # Get containers running on this node
        containers = conn.execute(
            'SELECT * FROM containers WHERE node_id = ?', (node_id,)
        ).fetchall()
        
        result = dict(node)
        result['containers'] = [dict(container) for container in containers]
        return jsonify(result)
    finally:
        conn.close()

@app.route('/api/services', methods=['GET'])
def get_services():
    """Get all services in the swarm"""
    conn = get_db_connection()
    try:
        services = conn.execute('SELECT * FROM services').fetchall()
        return jsonify([dict(service) for service in services])
    finally:
        conn.close()

@app.route('/api/services/<service_id>', methods=['GET'])
def get_service(service_id):
    """Get detailed information about a specific service"""
    conn = get_db_connection()
    try:
        service = conn.execute('SELECT * FROM services WHERE id = ?', (service_id,)).fetchone()
        if not service:
            return jsonify({'error': 'Service not found'}), 404
        
        # Get containers for this service
        containers = conn.execute(
            'SELECT * FROM containers WHERE service_id = ?', (service_id,)
        ).fetchall()
        
        result = dict(service)
        result['containers'] = [dict(container) for container in containers]
        return jsonify(result)
    finally:
        conn.close()

@app.route('/api/containers', methods=['GET'])
def get_containers():
    """Get all containers in the swarm"""
    conn = get_db_connection()
    try:
        containers = conn.execute('SELECT * FROM containers').fetchall()
        return jsonify([dict(container) for container in containers])
    finally:
        conn.close()

@app.route('/api/containers/<container_id>', methods=['GET'])
def get_container(container_id):
    """Get detailed information about a specific container"""
    conn = get_db_connection()
    try:
        container = conn.execute('SELECT * FROM containers WHERE id = ?', (container_id,)).fetchone()
        if not container:
            return jsonify({'error': 'Container not found'}), 404
        
        return jsonify(dict(container))
    finally:
        conn.close()

@app.route('/api/images', methods=['GET'])
def get_images():
    """Get all images in the registry"""
    conn = get_db_connection()
    try:
        images = conn.execute('SELECT * FROM images').fetchall()
        return jsonify([dict(image) for image in images])
    finally:
        conn.close()

@app.route('/api/events', methods=['GET'])
def get_events():
    """Get system events, with optional filtering"""
    event_type = request.args.get('type')
    object_type = request.args.get('object_type')
    limit = request.args.get('limit', 100, type=int)
    
    conn = get_db_connection()
    try:
        query = 'SELECT * FROM events'
        params = []
        
        # Apply filters
        filters = []
        if event_type:
            filters.append('event_type = ?')
            params.append(event_type)
        if object_type:
            filters.append('object_type = ?')
            params.append(object_type)
        
        if filters:
            query += ' WHERE ' + ' AND '.join(filters)
        
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        events = conn.execute(query, params).fetchall()
        return jsonify([dict(event) for event in events])
    finally:
        conn.close()

@app.route('/api/upload/image', methods=['POST'])
def upload_image():
    """Upload a docker image tar file and load it into the registry"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if not file.filename.endswith('.tar'):
        return jsonify({'error': 'Only .tar image files are supported'}), 400
    
    # Generate a unique filename
    filename = str(uuid.uuid4()) + '.tar'
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        # Save uploaded file
        file.save(filepath)
        
        # Load image into docker
        load_result = execute_docker_cmd(f"docker load -i {filepath}")
        if not load_result:
            return jsonify({'error': 'Failed to load Docker image'}), 500
        
        # Extract image name and tag
        image_info = None
        
        # Pattern could be "Loaded image: name:tag" or "Loaded image ID: sha256:..."
        if "Loaded image:" in load_result:
            image_info = load_result.split("Loaded image:")[1].strip()
        
        # If we can't determine the image name, list recent images
        if not image_info:
            images_json = execute_docker_cmd("docker image ls --format '{{json .}}' | head -n 1")
            if images_json:
                image = json.loads(images_json)
                image_info = f"{image.get('Repository')}:{image.get('Tag')}"
        
        # Tag and push to local registry
        if image_info:
            # Parse repository and tag
            image_parts = image_info.split(':')
            repo = image_parts[0]
            tag = image_parts[1] if len(image_parts) > 1 else 'latest'
            
            # Create registry tag
            registry_image = f"{REGISTRY_HOST}:{REGISTRY_PORT}/{repo}:{tag}"
            tag_result = execute_docker_cmd(f"docker tag {image_info} {registry_image}")
            
            # Push to registry
            push_result = execute_docker_cmd(f"docker push {registry_image}")
            if not push_result:
                return jsonify({'error': 'Failed to push image to registry'}), 500
            
            # Log event
            log_event('upload', 'image', image_info, 
                      f"Image uploaded and pushed to registry as {registry_image}")
            
            # Return success with image info
            return jsonify({
                'success': True,
                'message': 'Image uploaded and pushed to registry',
                'original_image': image_info,
                'registry_image': registry_image
            })
        
        return jsonify({
            'success': True,
            'message': 'Image loaded successfully',
            'details': load_result
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        # Clean up the uploaded file
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route('/api/upload/compose', methods=['POST'])
def upload_compose():
    """Upload a docker-compose.yml file and deploy it as a stack"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    stack_name = request.form.get('stack_name')
    if not stack_name:
        return jsonify({'error': 'Stack name is required'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    # Create temporary directory for the compose file
    temp_dir = tempfile.mkdtemp(prefix="compose_", dir=app.config['UPLOAD_FOLDER'])
    compose_path = os.path.join(temp_dir, "docker-compose.yml")
    
    try:
        # Save uploaded file
        file.save(compose_path)
        
        # Deploy the stack
        deploy_result = execute_docker_cmd(f"docker stack deploy -c {compose_path} {stack_name}")
        if not deploy_result and deploy_result is not None:
            deploy_result = "Stack deployed successfully"
        
        if deploy_result is None:
            return jsonify({'error': 'Failed to deploy stack'}), 500
        
        # Log event
        log_event('deploy', 'stack', stack_name, 
                  f"Stack deployed from uploaded compose file")
        
        return jsonify({
            'success': True,
            'message': 'Stack deployed successfully',
            'stack_name': stack_name,
            'details': deploy_result
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

@app.route('/api/stacks', methods=['GET'])
def get_stacks():
    """Get all deployed stacks"""
    stacks_output = execute_docker_cmd("docker stack ls --format '{{json .}}'")
    if not stacks_output:
        return jsonify([])
    
    # Parse output into list of stacks
    stacks = [json.loads(stack) for stack in stacks_output.strip().split('\n') if stack]
    return jsonify(stacks)

@app.route('/api/stacks/<stack_name>', methods=['GET'])
def get_stack(stack_name):
    """Get detailed information about a specific stack"""
    # Get stack services
    services_output = execute_docker_cmd(f"docker stack services {stack_name} --format '{{json .}}'")
    if not services_output:
        return jsonify({'error': 'Stack not found or has no services'}), 404
    
    # Parse services
    services = [json.loads(service) for service in services_output.strip().split('\n') if service]
    
    return jsonify({
        'name': stack_name,
        'services': services
    })

@app.route('/api/stacks/<stack_name>', methods=['DELETE'])
def remove_stack(stack_name):
    """Remove a deployed stack"""
    result = execute_docker_cmd(f"docker stack rm {stack_name}")
    if result is None:
        return jsonify({'error': 'Failed to remove stack'}), 500
    
    # Log event
    log_event('remove', 'stack', stack_name, 'Stack removed')
    
    return jsonify({
        'success': True,
        'message': f'Stack {stack_name} removed successfully'
    })

@app.route('/api/registry', methods=['GET'])
def get_registry_images():
    """Get list of images in the registry"""
    try:
        # Query the registry API for catalog
        registry_url = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}/v2/_catalog"
        catalog_cmd = f"curl -s {registry_url}"
        catalog_json = execute_docker_cmd(catalog_cmd)
        
        if not catalog_json:
            return jsonify({'repositories': []})
        
        catalog = json.loads(catalog_json)
        repositories = catalog.get('repositories', [])
        
        # Get tags for each repository
        result = []
        for repo in repositories:
            tags_url = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}/v2/{repo}/tags/list"
            tags_cmd = f"curl -s {tags_url}"
            tags_json = execute_docker_cmd(tags_cmd)
            
            if tags_json:
                tags_data = json.loads(tags_json)
                result.append({
                    'repository': repo,
                    'tags': tags_data.get('tags', [])
                })
            else:
                result.append({
                    'repository': repo,
                    'tags': []
                })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/registry/<path:repo>/tags/<tag>', methods=['DELETE'])
def delete_registry_image(repo, tag):
    """Delete an image from the registry"""
    try:
        # First, we need to get the digest
        manifest_url = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}/v2/{repo}/manifests/{tag}"
        digest_cmd = f"curl -s -I -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' {manifest_url} | grep Docker-Content-Digest | awk '{{print $2}}'"
        digest = execute_docker_cmd(digest_cmd).strip()
        
        if not digest:
            return jsonify({'error': 'Image digest not found'}), 404
        
        # Delete the image using the digest
        delete_url = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}/v2/{repo}/manifests/{digest}"
        delete_cmd = f"curl -s -X DELETE {delete_url}"
        result = execute_docker_cmd(delete_cmd)
        
        # Log event
        log_event('delete', 'registry_image', f"{repo}:{tag}", f"Image deleted from registry")
        
        return jsonify({
            'success': True,
            'message': f'Image {repo}:{tag} deleted from registry'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats', methods=['GET'])
def get_system_stats():
    """Get system-wide statistics"""
    # Get Docker info
    docker_info = execute_docker_cmd("docker info --format '{{json .}}'")
    if not docker_info:
        return jsonify({'error': 'Failed to get Docker info'}), 500
    
    try:
        info = json.loads(docker_info)
        
        # Get disk usage
        disk_usage_cmd = "df -h /var/lib/docker | tail -1 | awk '{print $2, $3, $4, $5}'"
        disk_usage = execute_docker_cmd(disk_usage_cmd).split()
        
        # Format the result
        stats = {
            'containers': info.get('Containers', 0),
            'running': info.get('ContainersRunning', 0),
            'paused': info.get('ContainersPaused', 0),
            'stopped': info.get('ContainersStopped', 0),
            'images': info.get('Images', 0),
            'swarm_nodes': info.get('Swarm', {}).get('Nodes', 0),
            'swarm_managers': info.get('Swarm', {}).get('Managers', 0),
            'memory': info.get('MemTotal', 0),
            'disk': {
                'total': disk_usage[0] if len(disk_usage) > 0 else 'unknown',
                'used': disk_usage[1] if len(disk_usage) > 1 else 'unknown',
                'available': disk_usage[2] if len(disk_usage) > 2 else 'unknown',
                'use_percent': disk_usage[3] if len(disk_usage) > 3 else 'unknown'
            }
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh', methods=['POST'])
def refresh_data():
    """Manually trigger a refresh of the database"""
    try:
        update_nodes()
        update_services()
        update_containers()
        update_images()
        
        return jsonify({
            'success': True,
            'message': 'Data refresh triggered successfully',
            'timestamp': datetime.datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Start the background worker
def start_worker():
    worker_thread = threading.Thread(target=update_data_worker)
    worker_thread.daemon = True
    worker_thread.start()

if __name__ == '__main__':
    # Initialize the database connection
    print("Initializing database connection...")
    conn = get_db_connection()
    conn.close()
    
    # Start the background worker
    print("Starting background data update worker...")
    start_worker()
    
    # Run the Flask app
    print(f"Starting Flask app on port {MONITOR_PORT}...")
    app.run(host='0.0.0.0', port=MONITOR_PORT)