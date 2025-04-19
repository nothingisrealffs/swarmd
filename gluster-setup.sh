#!/bin/bash
# gluster-setup.sh - Setup GlusterFS for Docker volume sharing

# Configuration
VOLUME_NAME=${GLUSTER_VOLUME_NAME:-"docker-volume"}
BRICK_PATH=${GLUSTER_BRICK_PATH:-"/gluster/bricks"}

# Make sure glusterd is running
echo "Starting GlusterFS daemon..."
if ! pgrep glusterd > /dev/null; then
    glusterd
    sleep 2
fi

# Check if glusterd is running
if ! pgrep glusterd > /dev/null; then
    echo "Failed to start GlusterFS daemon!"
    exit 1
fi

# Create brick directory if it doesn't exist
if [ ! -d "$BRICK_PATH" ]; then
    mkdir -p "$BRICK_PATH"
    chmod 777 "$BRICK_PATH"
    echo "Created GlusterFS brick directory: $BRICK_PATH"
fi

# Check if the volume already exists
if ! gluster volume info "$VOLUME_NAME" &>/dev/null; then
    echo "Creating GlusterFS volume: $VOLUME_NAME"
    # Create a single node volume
    gluster volume create "$VOLUME_NAME" $(hostname -i):$BRICK_PATH force
    
    # Start the volume
    gluster volume start "$VOLUME_NAME"
    
    # Enable necessary features
    gluster volume set "$VOLUME_NAME" auth.allow '*'
    gluster volume set "$VOLUME_NAME" performance.cache-size 256MB
    gluster volume set "$VOLUME_NAME" performance.io-thread-count 32
    
    echo "GlusterFS volume created and started!"
else
    echo "GlusterFS volume '$VOLUME_NAME' already exists."
    
    # Make sure the volume is started
    VOLUME_STATUS=$(gluster volume info "$VOLUME_NAME" | grep "Status:" | awk '{print $2}')
    if [ "$VOLUME_STATUS" != "Started" ]; then
        echo "Starting GlusterFS volume..."
        gluster volume start "$VOLUME_NAME"
    fi
fi

# Mount the volume locally for use
MOUNT_POINT="/gluster/mount"
if [ ! -d "$MOUNT_POINT" ]; then
    mkdir -p "$MOUNT_POINT"
fi

# Unmount if already mounted
if mount | grep -q "$MOUNT_POINT"; then
    umount "$MOUNT_POINT" || echo "Warning: Could not unmount $MOUNT_POINT"
fi

# Mount the gluster volume
mount -t glusterfs $(hostname -i):/$VOLUME_NAME $MOUNT_POINT
if [ $? -eq 0 ]; then
    echo "GlusterFS volume mounted at $MOUNT_POINT"
    
    # Create a docker volume that points to this location
    if ! docker volume ls | grep -q "gluster-volume"; then
        docker volume create --driver local \
            --opt type=none \
            --opt device=$MOUNT_POINT \
            --opt o=bind \
            gluster-volume
        echo "Docker volume 'gluster-volume' created, pointing to GlusterFS storage."
    fi
else
    echo "Failed to mount GlusterFS volume!"
fi

# Display GlusterFS status
echo "----- GlusterFS Status -----"
gluster volume status
echo "--------------------------"