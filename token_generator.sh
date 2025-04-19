# token_generator.sh

# Configuration
MANAGER_HOST=${SWARM_MANAGER:-"localhost"}
TOKEN_SERVICE_PORT=${TOKEN_SERVICE_PORT:-8000}

# Read admin key from file or environment
if [ -z "$ADMIN_API_KEY" ] && [ -f "./admin.key" ]; then
    ADMIN_API_KEY=$(cat ./admin.key)
fi

if [ -z "$ADMIN_API_KEY" ]; then
    echo "Error: Admin API key not found. Please provide it via ADMIN_API_KEY env variable or ./admin.key file."
    exit 1
fi

# Parse command line arguments
NODE_ID=""
NODE_ROLE="worker"

while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        --id|-i)
            NODE_ID="$2"
            shift
            shift
            ;;
        --role|-r)
            NODE_ROLE="$2"
            shift
            shift
            ;;
        --help|-h)
            echo "Usage: $0 --id <node-id> [--role <worker|manager>]"
            echo ""
            echo "Options:"
            echo "  --id, -i     Node identifier (required)"
            echo "  --role, -r   Node role: 'worker' or 'manager' (default: worker)"
            echo "  --help, -h   Show this help message"
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
if [ -z "$NODE_ID" ]; then
    echo "Error: Node ID is required. Use --id to specify."
    exit 1
fi

if [ "$NODE_ROLE" != "worker" ] && [ "$NODE_ROLE" != "manager" ]; then
    echo "Error: Invalid role. Use 'worker' or 'manager'."
    exit 1
fi

# Generate token via API
echo "Generating token for node '$NODE_ID' with role '$NODE_ROLE'..."

TOKEN_RESPONSE=$(curl -s -X POST \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $ADMIN_API_KEY" \
    -d "{\"node_id\": \"$NODE_ID\", \"role\": \"$NODE_ROLE\"}" \
    "http://$MANAGER_HOST:$TOKEN_SERVICE_PORT/token/generate")

# Check if request was successful
if [[ "$TOKEN_RESPONSE" == *"error"* ]]; then
    echo "Error generating token: $TOKEN_RESPONSE"
    exit 1
fi

# Extract token from response
TOKEN=$(echo $TOKEN_RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "Error: Failed to extract token from response."
    exit 1
fi

# Save token to file
echo "$TOKEN" > "${NODE_ID}.token"
echo "Token generated and saved to ${NODE_ID}.token"
echo ""
echo "===== JOIN COMMAND ====="
echo "Run this on the node you want to join to the swarm:"
echo "curl -s -o join_node.sh https://raw.githubusercontent.com/yourusername/swarm-manager/main/join_node.sh"
echo "chmod +x join_node.sh"
echo "./join_node.sh --manager $MANAGER_HOST:$TOKEN_SERVICE_PORT --token $TOKEN"
echo "======================="