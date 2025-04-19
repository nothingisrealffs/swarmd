# 🐳 Docker Swarm Manager with Token-Based Joining, Monitoring, and GlusterFS

A self-contained, containerized system to manage a Docker Swarm cluster with:

- Token-based node joining via JWT
- Centralized real-time monitoring of Swarm status
- Embedded local Docker Registry with GlusterFS-backed storage
- REST APIs for node status, image uploads, stack deployments
- SQLite backend for historical tracking
- Secure join & management operations via API keys

---

## 📌 Overview

This application provides:
- A central Swarm Manager node inside a container
- Token-based join process for secure node addition
- Internal registry for local image hosting and distribution
- Persistent shared volume storage via GlusterFS
- Monitoring and API-based control interfaces

---

## 📈 Architecture Flow

![Docker Swarm Manager Workflow](./A_flowchart_titled_"Docker_Swarm_Manager_Workflow".png)

---

## 🧭 Component Flow (Startup to Runtime)

1. **Container Startup**
   - Builds using `Dockerfile`
   - Runs `entrypoint.sh`

2. **Swarm Init**
   - Initializes Swarm (if not yet initialized)
   - Starts Docker daemon inside the container

3. **Database Setup**
   - SQLite schema is created using `db_schema.sql`

4. **Shared Storage**
   - Runs `gluster-setup.sh` to set up GlusterFS volume
   - Mounts GlusterFS and maps it to Docker volume

5. **Registry**
   - Starts internal registry with `registry-config.yml`
   - Exposes Docker Registry on port `5000`

6. **Token Service**
   - Flask app via `token_service.py`
   - JWT-based token issuing & validation

7. **Swarm Monitoring**
   - Flask app via `swarm_monitor.py`
   - Gathers container, node, image, and service data
   - Stores state in SQLite
   - Exposes REST API for external queries

---

## 📦 Files & Their Roles

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Defines the main container, volume mounts, ports |
| `Dockerfile` | Builds container image with Flask, Docker, GlusterFS |
| `entrypoint.sh` | Startup logic, init Swarm, DB, run services |
| `db_schema.sql` | Schema for the monitoring database |
| `gluster-setup.sh` | Starts GlusterFS and binds Docker volume |
| `registry-config.yml` | Config for embedded Docker Registry |
| `token_service.py` | Flask JWT join token API service |
| `swarm_monitor.py` | Monitors cluster and provides a REST API |
| `token_generator.sh` | Script to request join tokens (run outside container) |
| `join_node.sh` | Used on other hosts to join the Swarm using token |

---

## 🔧 System Breakdown: What Runs Where

### 🐳 Inside the Container (Swarm Manager)
- `entrypoint.sh`
- `swarm_monitor.py` (Port 8001)
- `token_service.py` (Port 8000)
- Docker Daemon
- GlusterFS Server
- Local Docker Registry (Port 5000)
- SQLite DB

### 💻 On the Host Machine (where container runs)
- `docker-compose up`
- `token_generator.sh` (Generates join tokens)
- (Optional) CLI tools to monitor container logs and registry

### 🌐 On External Nodes
- Install Docker
- Use `join_node.sh` to request a token and join
- Mount GlusterFS volume (optional, but recommended)
- Join Swarm with:
  ```bash
  docker swarm join --token <token> <manager-ip>:2377
