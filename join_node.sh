#!/bin/bash
# join_node.sh - Script to join a node to the Swarm

# Configuration defaults
MANAGER_HOST=""
TOKEN=""
TOKEN_SERVICE_PORT=8000
SETUP_GLUSTER=true
SETUP_REGISTRY=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        --manager|-m)
            MANAGER_HOST="$2"
            shift
            shift
            ;;
        --token|-t)
            TOKEN="$2"
            shift
            shift
            ;;
        --no-gluster)
            SETUP_GLUSTER=false
            shift
            ;;
        --no-registry)
            SETUP_REGISTRY=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 --manager <host:port> --token <token> [--no-gluster] [--no-registry]"
            echo ""
            echo "Options:"
            echo "  --manager, -m   Swarm manager host:port"
            echo "  --token, -t     Join token received from token generator"
            echo "  --no-gluster    Skip GlusterFS client setup"
            echo "  --no-registry   Skip Docker registry client setup"
            echo "  --help, -h      Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# Validate required arguments
if [ -z "$MANAGER_HOST" ]; then
    echo "Error: Manager host is required. Use --manager to specify."
    exit 1
fi

if [ -z "$TOKEN" ]; then
    echo "Error: Token is required. Use --token to specify."
    exit 1
fi

# Extract host and port
if [[ "$MANAGER_HOST" == *":"* ]]; then
    HOST_PART=$(echo $MANAGER_HOST | cut -d':' -f1)
    PORT_PART=$(echo $MANAGER_HOST | cut -d':' -f2)
    if [ ! -z "$PORT_PART" ]; then
        TOKEN_SERVICE_PORT=$PORT_PART
    fi
    MANAGER_HOST=$HOST_PART
fi

echo "Validating token with Swarm manager at $MANAGER_HOST:$TOKEN_SERVICE_PORT..."

# Validate token and get join details
JOIN_RESPONSE=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -d "{\"token\": \"$TOKEN\"}" \
    "http://$MANAGER_HOST:$TOKEN_SERVICE_PORT/token/validate")

# Check for errors
if [[ "$JOIN_RESPONSE" == *"\"valid\":false"* || "$JOIN_RESPONSE" == *"error"* ]]; then
    echo "Error: Invalid or expired token."
    echo "Response: $JOIN_RESPONSE"
    exit 1
fi

# Extract information from response
NODE_ROLE=$(echo $JOIN_RESPONSE | grep -o '"role":"[^"]*' | cut -d'"' -f4)
SWARM_TOKEN=$(echo $JOIN_RESPONSE | grep -o '"swarm_join_token":"[^"]*' | cut -d'"' -f4)
MANAGER_IP=$(echo $JOIN_RESPONSE | grep -o '"manager_ip":"[^"]*' | cut -d'"' -f4)

# Validate extracted data
if [ -z "$SWARM_TOKEN" ] || [ -z "$MANAGER_IP" ]; then
    echo "Error: Failed to extract join information from response."
    echo "Response: $JOIN_RESPONSE"
    exit 1
fi

echo "Token validated successfully!"
echo "Role: $NODE_ROLE"
echo "Manager IP: $MANAGER_IP"

# Setup Registry if requested
if [ "$SETUP_REGISTRY" = true ]; then
    echo "Setting up Docker Registry client configuration..."
    
    # Create Docker daemon configuration
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<EOF
{
  "insecure-registries": ["${MANAGER_IP}:5000"],
  "registry-mirrors": ["http://${MANAGER_IP}:5000"]
}
EOF

    # Restart Docker service to apply changes
    systemctl restart docker || service docker restart
    sleep 3
    echo "Docker Registry client setup complete!"
fi

# Setup GlusterFS client if requested
if [ "$SETUP_GLUSTER" = true ]; then
    echo "Setting up GlusterFS client..."
    
    # Install GlusterFS client if not present
    if ! command -v glusterfs >/dev/null; then
        if command -v apt-get >/dev/null; then
            apt-get update && apt-get install -y glusterfs-client
        elif command -v yum >/dev/null; then
            yum install -y glusterfs-client
        elif command -v apk >/dev/null; then
            apk add --no-cache glusterfs
        else
            echo "Warning: Could not install GlusterFS client. Please install it manually."
        fi
    fi
    
    # Create mount point
    mkdir -p /gluster/mount
    
    # Add fstab entry for persistent mount
    if ! grep -q "${MANAGER_IP}:/docker-volume" /etc/fstab; then
        echo "${MANAGER_IP}:/docker-volume /gluster/mount glusterfs defaults,_netdev 0 0" >> /etc/fstab
    fi
    
    # Mount immediately
    mount -t glusterfs ${MANAGER_IP}:/docker-volume /gluster/mount
    
    if [ $? -eq 0 ]; then
        echo "GlusterFS volume mounted successfully!"
    else
        echo "Warning: Failed to mount GlusterFS volume. Please check network connectivity."
    fi
fi

# Join the Swarm
echo "Joining Docker Swarm as $NODE_ROLE..."
JOIN_CMD="docker swarm join --token $SWARM_TOKEN $MANAGER_IP:2377"

echo "Executing: $JOIN_CMD"
eval $JOIN_CMD

# Check join status
if [ $? -eq 0 ]; then
    echo "Successfully joined the Swarm!"
else
    echo "Failed to join the Swarm. Please check Docker daemon status and network connectivity."
    exit 1
fi