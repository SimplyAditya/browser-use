# Browser-Use Docker Backend - Technical Documentation

## Overview

This document explains how browser-use is deployed as a backend service using Docker, covering the architecture, code changes, and how all components work together.

**Goal:** Enable an API backend to trigger browser-use tasks via Docker containers that spin up fresh for each task, execute the scraping/data extraction, return results, and auto-cleanup while persisting logs.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          API Backend Server                                  │
│                              (Your Server)                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   API Request: "Navigate to amazon.com and extract product price"            │
│       │                                                                       │
│       ▼                                                                       │
│   ┌────────────────────────────────────────────────────────────────────┐     │
│   │  docker run --rm                                                      │     │
│   │    -v ./logs:/root/.config/browseruse/logs                         │     │
│   │    -e OPENAI_API_KEY                                                 │     │
│   │    -e ANTHROPIC_API_KEY                                              │     │
│   │    browseruse                                                        │     │
│   │    browser --task "Navigate to amazon.com and extract..."           │     │
│   └────────────────────────────────────────────────────────────────────┘     │
│       │                                                                       │
│       │     Container Lifecycle                                             │
│       │     ┌───────────────────────────────────────────────────────────┐     │
│       │     │ 1. Container starts (fresh OS, no previous state)      │     │
│       │     │ 2. browser-use CLI executes --task argument            │     │
│       │     │ 3. Agent runs LLM-driven browser automation            │     │
│       │     │ 4. Result returned as JSON                            │     │
│       │     │ 5. Container exits → auto-deleted (--rm flag)          │     │
│       │     └───────────────────────────────────────────────────────────┘     │
│       │                                                                       │
│       ▼                                                                       │
│   Logs written to: ./logs/invocations.jsonl  (persists after container dies)│
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Why Ephemeral Containers?

### Problem: State/Cache Pollution

Traditional long-running services accumulate state:
- Browser cookies and session data
- Cached pages and assets
- Browser profile changes
- DNS cache

This state can **interfere with scraping tasks** (e.g., personalized content, cached prices).

### Solution: Fresh Container Per Task

Each `docker run --rm` starts a **completely fresh container**:
- No cookies from previous requests
- No cached pages or prices
- No DNS cache pollution
- No browser profile changes
- Intentionally isolated

**Tradeoff:** Slower (container startup ~2-5 sec) but **correct** for scraping.

---

## Files Created/Modified

### New Files

| File | Purpose |
|------|---------|
| `browser_use/server/__init__.py` | Package marker |
| `browser_use/server/models.py` | Pydantic API models |
| `browser_use/server/invocation_logger.py` | Structured JSONL logging |
| `browser_use/server/session_manager.py` | Browser session pool |
| `browser_use/server/app.py` | FastAPI REST server |
| `scripts/deploy.sh` | Server deployment script |
| `browser_use/logging_config.py` | Runtime log level control (modified) |

### Modified Files

| File | Change |
|------|--------|
| `pyproject.toml` | Added `fastapi`, `uvicorn` dependencies + `browser-use-server` script |
| `browser_use/logging_config.py` | Added `set_log_level_runtime()` and `get_log_level_runtime()` |

---

## Component Details

### 1. Invocation Logger (`browser_use/server/invocation_logger.py`)

**Purpose:** Log every task invocation to a JSONL file that persists after container cleanup.

**How it works:**
```python
# Each invocation writes a JSON line:
{
  "timestamp": "2026-05-15T10:30:45.123456Z",
  "invocation_id": "inv_20260515_103045",
  "task_id": "uuid",
  "task": "Navigate to amazon.com and extract price",
  "status": "completed",  # or "running", "failed"
  "llm_provider": "openai",
  "llm_model": "gpt-4o",
  "steps": 12,
  "result": "Product price: $29.99",
  "duration_seconds": 45.2,
  "error": null
}
```

**File rotation:**
- Keeps last 10,000 lines in `invocations.jsonl`
- Rotates to `invocations_YYYY-MM-DD.jsonl` when full

**Why JSONL?** Append-only, easy to parse, no locking issues.

### 2. Runtime Log Level Control (`browser_use/logging_config.py`)

**Purpose:** Change log level without restarting the service.

**Added functions:**
```python
def set_log_level_runtime(level: str) -> None:
    """Change log level at runtime without restart."""
    global _runtime_log_level
    valid_levels = ('debug', 'info', 'result', 'critical')
    if level not in valid_levels:
        raise ValueError(f'Invalid log level: {level}')
    _runtime_log_level = level
    # Updates all browser_use loggers immediately

def get_log_level_runtime() -> str:
    """Get current runtime log level."""
    return _runtime_log_level or CONFIG.BROWSER_USE_LOGGING_LEVEL
```

**How it works:**
- Module-level global variable stores current level
- When log level changes, immediately updates all logger handlers
- No restart needed - affects running process

### 3. Deployment Script (`scripts/deploy.sh`)

**Purpose:** One-command deployment on a fresh server.

**Steps executed:**
```bash
1. check_prerequisites()     # Python 3.11+, uv, git
2. setup_repository()        # Clone or git pull
3. setup_venv()             # uv venv + uv sync
4. setup_env()              # Copy .env.example to .env
5. setup_log_dir()          # Create log directory
6. install_systemd_service() # Install systemd unit
7. start_service()          # systemctl start
```

**Systemd unit created:**
```ini
[Unit]
Description=Browser-Use Backend Service
After=network.target

[Service]
Type=simple
User=browseruse
WorkingDirectory=/root/browser-use
ExecStart=/root/browser-use/.venv/bin/python -m browser_use.server.app
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Docker Execution Flow

### 1. Build Image

```bash
cd /path/to/browser-use
docker build -t browseruse .
```

**What happens inside Dockerfile:**
```
FROM python:3.12-slim
    │
    ▼
Install apt dependencies (curl, wget, etc.)
    │
    ▼
Install Chromium browser + fonts
    │
    ▼
Create 'browseruse' user (UID 911)
    │
    ▼
Copy pyproject.toml + uv.lock
    │
    ▼
uv venv (create virtual environment)
    │
    ▼
uv sync (install Python dependencies)
    │
    ▼
Copy entire codebase
    │
    ▼
uv sync --locked (final install with lock file)
    │
    ▼
Set volume mount: /data
    │
    ▼
Expose ports: 9242, 9222
```

### 2. Run Container (Ephemeral)

```bash
docker run --rm \
  -v "$(pwd)/logs:/root/.config/browseruse/logs" \
  -e OPENAI_API_KEY \
  -e BROWSER_USE_LOGGING_LEVEL=debug \
  browseruse \
  browser --task "Navigate to amazon.com and extract price"
```

**Breakdown:**
| Flag | Purpose |
|------|---------|
| `--rm` | Auto-delete container when done |
| `-v ./logs:/root/.config/browseruse/logs` | Mount host's `./logs` to container's log directory |
| `-e OPENAI_API_KEY` | Pass API key from host environment |
| `browseruse` | Image name |
| `browser --task "..."` | Command to execute inside container |

### 3. Container Lifecycle

```
Container Start
    │
    ├── Read environment variables (OPENAI_API_KEY, etc.)
    │
    ├── Initialize logging (writes to /root/.config/browseruse/logs)
    │
    ├── Parse command: "browser --task '...'"
    │
    ├── Create BrowserProfile (headless Chromium)
    │
    ├── Start BrowserSession (Chrome + CDP)
    │
    ├── Create Agent with task description
    │
    ├── Agent.run() - LLM-driven automation loop
    │   │
    │   ├── LLM decides action (click, type, navigate, etc.)
    │   ├── Execute via CDP (Chrome DevTools Protocol)
    │   ├── Capture DOM state
    │   ├── Feed back to LLM
    │   └── Repeat until done or max_steps
    │
    ├── Extract result
    │
    ├── Write invocation log to JSONL
    │
    ├── Container exits (--rm triggers auto-delete)
    │
    ▼
Container deleted, but logs persist in host's ./logs/
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `ANTHROPIC_API_KEY` | (optional) | Anthropic API key |
| `BROWSER_USE_LOGGING_LEVEL` | `info` | Log level: debug/info/result/critical |
| `BROWSER_USE_INVOCATION_LOGGING` | `true` | Enable JSONL invocation logging |
| `BROWSER_USE_SERVER_PORT` | `18792` | HTTP server port (FastAPI mode) |
| `BROWSER_USE_SERVER_HOST` | `127.0.0.1` | Bind address (FastAPI mode) |

---

## Log Persistence

### Without Volume Mount
```
Container /root/.config/browseruse/logs/
    └── invocations.jsonl  ← LOST when container deleted
```

### With Volume Mount (Recommended)
```
Host ./logs/
    └── invocations.jsonl  ← PERSISTS after container deleted

Docker run: -v "$(pwd)/logs:/root/.config/browseruse/logs"
```

**Key insight:** The symlink `/home/browseruse/.config/browseruse` → `/data` in Dockerfile means logs written to `~/.config/browseruse/logs/` in container land in `/data` which is volume-mounted.

---

## API Integration Examples

### Python (FastAPI calling Docker)

```python
import subprocess
import json
import os

@app.post("/scrape")
async def scrape(url: str, query: str):
    """Scrape data using browser-use Docker container."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.getcwd()}/logs:/root/.config/browseruse/logs",
        "-e", f"OPENAI_API_KEY={os.getenv('OPENAI_API_KEY')}",
        "-e", "BROWSER_USE_LOGGING_LEVEL=info",
        "browseruse",
        "browser", "--task", f"Navigate to {url} and {query}"
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300  # 5 min max
    )

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)

    return json.loads(result.stdout)
```

### Shell Script Wrapper

```bash
#!/bin/bash
# browser-use wrapper - call this from your API

set -e

LOG_DIR="${1:-./logs}"
shift  # Remove first arg, rest is command

docker run --rm \
  -v "${LOG_DIR}:/root/.config/browseruse/logs" \
  -e OPENAI_API_KEY \
  -e BROWSER_USE_LOGGING_LEVEL \
  browseruse \
  browser "$@"
```

**Usage:**
```bash
./browser-use.sh ./logs --task "Navigate to google.com and search for AI"
```

---

## Directory Structure

```
browser-use/
├── Dockerfile                    # Standard full build
├── Dockerfile.fast             # Fast build using base images
├── docker/
│   ├── build-base-images.sh   # Build caching layers
│   └── base-images/          # Base image Dockerfiles
│       ├── system/           # Python + system deps
│       ├── chromium/         # Chromium browser
│       └── python-deps/      # pip dependencies
├── browser_use/
│   ├── server/               # NEW: Server components
│   │   ├── __init__.py
│   │   ├── app.py           # FastAPI app
│   │   ├── models.py        # Pydantic models
│   │   ├── invocation_logger.py
│   │   └── session_manager.py
│   ├── logging_config.py    # MODIFIED: runtime log control
│   └── ...
├── scripts/
│   └── deploy.sh            # Server deployment script
├── pyproject.toml           # MODIFIED: fastapi deps
└── ...
```

---

## Debugging

### Check if container image exists
```bash
docker images | grep browseruse
```

### Run container interactively
```bash
docker run -it --rm \
  -v "./logs:/root/.config/browseruse/logs" \
  -e OPENAI_API_KEY \
  browseruse \
  bash
```

### View invocation logs
```bash
tail -f ./logs/invocations.jsonl | jq .
```

### Check Docker daemon
```bash
sudo systemctl status docker
sudo usermod -aG docker $USER  # Add user to docker group
```

---

## Comparison: Docker vs Direct Service

| Aspect | Docker Ephemeral | Direct Service |
|--------|-----------------|----------------|
| Startup | ~2-5 sec (container) | ~1-2 sec (process) |
| State between tasks | None (fresh) | Persistent |
| Resource usage | Higher (per-task containers) | Lower (reused) |
| Cleanup | Automatic (--rm) | Manual |
| Portability | Full isolation | Host-dependent |
| Debugging | docker logs | Direct stdout |
| Complexity | Higher (Docker required) | Lower |

**Choose Docker when:**
- Tasks must be isolated (no cache pollution)
- You need clean state per request
- Portability is important

**Choose Direct Service when:**
- Speed is critical (~2 sec savings)
- Session reuse is acceptable
- Resources are constrained

---

## Files and Their Roles

### `browser_use/server/invocation_logger.py`

```python
# Key functions:
init_invocation_logger(log_file_path)  # Initialize with path
log_invocation(...)                    # Write JSONL entry
update_invocation(...)                # Update running invocation
get_recent_invocations(limit)         # Read back logs
set_invocation_logging(enabled)        # Toggle logging
```

### `browser_use/logging_config.py`

```python
# Added functions:
set_log_level_runtime(level)   # Change level: debug/info/result/critical
get_log_level_runtime()        # Get current level
```

### `scripts/deploy.sh`

```bash
# Main steps:
check_prerequisites()          # Verify Python, uv, git
setup_repository()             # Clone or pull
setup_venv()                   # Create + install deps
setup_env()                    # Create .env
setup_log_dir()                # Create logs directory
install_systemd_service()      # Install .service file
start_service()                # systemctl start
```

### `pyproject.toml`

```toml
# Added dependencies:
dependencies = [
    "fastapi>=0.128.0",
    "uvicorn>=0.40.0",
    # ... existing deps ...
]

# Added script entry:
[project.scripts]
browser-use-server = "browser_use.server.app:run_server"
```

---

## Summary

1. **Build** `browseruse` Docker image once (`docker build -t browseruse .`)
2. **Execute** tasks via `docker run --rm ... browseruse browser --task "..."`
3. **Results** returned from container to stdout
4. **Logs** persist to mounted volume (`./logs/invocations.jsonl`)
5. **Cleanup** automatic - container deleted after exit
6. **Fresh state** per task - no cache pollution

This architecture provides maximum isolation and correctness for scraping tasks, at the cost of ~2-5 seconds startup overhead per task.