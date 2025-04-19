FROM alpine:latest

# Install required packages
RUN apk add --no-cache \
    docker \
    openssl \
    bash \
    curl \
    jq \
    socat \
    python3 \
    py3-pip \
    glusterfs \
    glusterfs-client \
    nfs-utils \
    e2fsprogs \
    sqlite

# Install Python dependencies
RUN pip3 install flask pyjwt cryptography flask-cors werkzeug==2.2.3 sqlite3 requests

# Create necessary directories
RUN mkdir -p /app /certs /tokens /var/registry /gluster /var/lib/registry /data

# Copy application files
COPY entrypoint.sh /app/
COPY token_service.py /app/
COPY gluster-setup.sh /app/
COPY registry-config.yml /app/
COPY swarm_monitor.py /app/
COPY db_schema.sql /app/
RUN chmod +x /app/entrypoint.sh /app/gluster-setup.sh

WORKDIR /app

ENTRYPOINT ["/app/entrypoint.sh"]