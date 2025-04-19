-- Database schema for Swarm monitoring

-- Nodes table to track swarm nodes
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    availability TEXT NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Containers table to track running containers
CREATE TABLE IF NOT EXISTS containers (
    id TEXT PRIMARY KEY,
    service_id TEXT,
    node_id TEXT,
    image TEXT NOT NULL,
    command TEXT,
    status TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    ports TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (node_id) REFERENCES nodes(id)
);

-- Services table to track swarm services
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    image TEXT NOT NULL,
    replicas INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Images table to track available images
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    tag TEXT NOT NULL,
    digest TEXT,
    size_bytes INTEGER,
    created_at TIMESTAMP NOT NULL,
    uploaded_by TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Events table to track important events
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_containers_node ON containers(node_id);
CREATE INDEX IF NOT EXISTS idx_containers_service ON containers(service_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_object ON events(object_type, object_id);