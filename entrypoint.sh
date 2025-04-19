#!/bin/bash
# entrypoint.sh

# Configuration with defaults
ENABLE_TLS=${ENABLE_TLS:-"false"}
TOKEN_SERVICE_PORT=${TOKEN_SERVICE_PORT:-8000}
ADMIN_KEY_FILE="/tokens/admin.key"
REGISTRY_HOST=${REGISTRY_HOST:-"127.0.0.1"}
REGISTRY_PORT=${REGISTRY_PORT:-5000}
GLUSTER_VOLUME_NAME=${GLUSTER_VOLUME_NAME:-"docker-volume"}
GLUSTER_BRICK_PATH=${GLUSTER_BRICK_PATH:-"/gluster/bricks"}
MONITOR_PORT=${MONITOR_PORT:-8001}
DB_PATH="/data/swarm_monitor.db"

echo "Starting Docker Swarm Management Node"

# Start Docker daemon
echo "Starting Docker daemon..."
dockerd-entrypoint.sh &
sleep 3

# Wait for Docker to be available
echo "Waiting for Docker daemon..."
until docker info >/dev/null 2>&1; do
    echo -n "."
    sleep 1
done
echo "Docker daemon is ready!"

# Initialize Swarm if not already done
if ! docker node ls &>/dev/null; then
    echo "Initializing new Swarm manager..."
    docker swarm init --advertise-addr $(hostname -i)
    echo "Swarm initialized successfully!"
else
    echo "Swarm already initialized."
fi

# Setup SQLite database
echo "Setting up SQLite database..."
if [ ! -f "$DB_PATH" ]; then
    echo "Creating new database at $DB_PATH"
    sqlite3 "$DB_PATH" < /app/db_schema.sql
    echo "Database created successfully!"
else
    echo "Database already exists at $DB_PATH"
fi

# Setup GlusterFS
echo "Setting up GlusterFS..."
/app/gluster-setup.sh

# Setup Docker Registry
echo "Setting up local Docker Registry..."
if ! docker ps | grep -q registry; then
    echo "Starting Docker Registry on port $REGISTRY_PORT..."
    docker run -d \
      -p ${REGISTRY_PORT}:5000 \
      --restart=always \
      --name registry \
      -v /var/lib/registry:/var/lib/registry \
      -v /app/registry-config.yml:/etc/docker/registry/config.yml \
      registry:2
    
    # Create a Docker config to use this registry
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["${REGISTRY_HOST}:${REGISTRY_PORT}"],
  "registry-mirrors": ["http://${REGISTRY_HOST}:${REGISTRY_PORT}"]
}
EOF
    
    echo "Docker Registry setup complete!"
else
    echo "Docker Registry already running."
fi

# Display admin API key
if [ -f "$ADMIN_KEY_FILE" ]; then
    ADMIN_KEY=$(cat "$ADMIN_KEY_FILE")
    echo "=========================================="
    echo "Admin API Key: $ADMIN_KEY"
    echo "Use this key to generate node join tokens."
    echo "=========================================="
else
    echo "Admin API key will be generated when the token service starts."
fi

# Start token service
echo "Starting token authentication service on port $TOKEN_SERVICE_PORT..."
python3 /app/token_service.py &

# Start monitoring service
echo "Starting container monitoring service on port $MONITOR_PORT..."
python3 /app/swarm_monitor.py &

# Display connection info
MANAGER_IP=$(hostname -i)
echo "=========================================="
echo "Swarm manager is ready at $MANAGER_IP"
echo "Token service running at http://$MANAGER_IP:$TOKEN_SERVICE_PORT"
echo "Monitor API running at http://$MANAGER_IP:$MONITOR_PORT"
echo "Docker Registry running at http://$MANAGER_IP:$REGISTRY_PORT"
echo "GlusterFS volume '$GLUSTER_VOLUME_NAME' ready for mounting"
echo "=========================================="

# If a command was provided, execute it, otherwise keep container running
if [ $# -gt 0 ]; then
    exec "$@"
else
    # Keep container running
    tail -f /dev/null
fi