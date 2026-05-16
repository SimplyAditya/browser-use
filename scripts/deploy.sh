#!/bin/bash
# =============================================================================
# Browser-Use Backend Service Deployment Script
# =============================================================================
# This script deploys browser-use as a backend service on a Linux server.
# Run this on a fresh server after cloning the repository.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/browser-use/browser-use/main/scripts/deploy.sh | bash
#   - or -
#   cd /path/to/browser-use && ./scripts/deploy.sh
#
# =============================================================================

set -e

# Configuration
SERVICE_NAME="browser-use-backend"
SERVICE_USER="${SERVICE_USER:-$(whoami)}"
SERVICE_PORT="${SERVICE_PORT:-18792}"
SERVICE_HOST="${SERVICE_HOST:-127.0.0.1}"
LOG_DIR="${LOG_DIR:-$HOME/.config/browseruse/logs}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/browser-use}"
VENV_DIR="${VENV_DIR:-$INSTALL_DIR/.venv}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# Step 1: Check prerequisites
# =============================================================================

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found. Please install Python 3.11+"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [ "$(echo "$PYTHON_VERSION < 3.11" | bc)" = "1" ]; then
        log_error "Python 3.11+ required, found $PYTHON_VERSION"
        exit 1
    fi
    log_info "Python version: $PYTHON_VERSION"

    # Check if uv is installed
    if ! command -v uv &> /dev/null; then
        log_info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
    log_info "uv installed: $(uv --version)"

    # Check git
    if ! command -v git &> /dev/null; then
        log_error "git not found. Please install git"
        exit 1
    fi
    log_info "git found: $(git --version)"
}

# =============================================================================
# Step 2: Setup or update repository
# =============================================================================

setup_repository() {
    log_info "Setting up repository at $INSTALL_DIR..."

    if [ -d "$INSTALL_DIR/.git" ]; then
        log_info "Repository exists, pulling latest..."
        cd "$INSTALL_DIR"
        git pull
    else
        log_info "Cloning repository..."
        git clone https://github.com/browser-use/browser-use.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
}

# =============================================================================
# Step 3: Create virtual environment and install dependencies
# =============================================================================

setup_venv() {
    log_info "Setting up virtual environment..."
    cd "$INSTALL_DIR"

    # Create venv if not exists
    if [ ! -d "$VENV_DIR" ]; then
        uv venv --python 3.11 "$VENV_DIR"
    fi

    # Activate venv and sync dependencies
    source "$VENV_DIR/bin/activate"
    uv sync --extra cli

    log_info "Dependencies installed"
}

# =============================================================================
# Step 4: Setup environment file
# =============================================================================

setup_env() {
    log_info "Setting up environment file..."

    ENV_FILE="$INSTALL_DIR/.env"
    if [ ! -f "$ENV_FILE" ]; then
        if [ -f "$INSTALL_DIR/.env.example" ]; then
            cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
            log_info "Created .env from .env.example"
            log_warn "Please edit $ENV_FILE and add your API keys!"
        else
            cat > "$ENV_FILE" << EOF
# Browser-Use Backend Service Configuration
BROWSER_USE_LOGGING_LEVEL=info
BROWSER_USE_SERVER_PORT=$SERVICE_PORT
BROWSER_USE_SERVER_HOST=$SERVICE_HOST
BROWSER_USE_INVOCATION_LOGGING=true

# LLM API Keys (add your keys here)
OPENAI_API_KEY=your-openai-api-key-here
ANTHROPIC_API_KEY=your-anthropic-api-key-here
GOOGLE_API_KEY=your-google-api-key-here
EOF
            log_info "Created default .env file"
            log_warn "Please edit $ENV_FILE and add your API keys!"
        fi
    else
        log_info ".env file already exists, skipping"
    fi
}

# =============================================================================
# Step 5: Create log directory
# =============================================================================

setup_log_dir() {
    log_info "Setting up log directory at $LOG_DIR..."
    mkdir -p "$LOG_DIR"
    chmod 755 "$LOG_DIR"
}

# =============================================================================
# Step 6: Install systemd service
# =============================================================================

install_systemd_service() {
    log_info "Installing systemd service..."

    SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

    cat > /tmp/$SERVICE_NAME.service << EOF
[Unit]
Description=Browser-Use Backend Service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$VENV_DIR/bin:$PATH
Environment=PYTHONPATH=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/browser-use-server
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=browser-use-server

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    sudo mv /tmp/$SERVICE_NAME.service "$SERVICE_FILE"
    sudo chmod 644 "$SERVICE_FILE"

    log_info "Systemd service installed at $SERVICE_FILE"
}

# =============================================================================
# Step 7: Start service
# =============================================================================

start_service() {
    log_info "Starting service..."

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl start "$SERVICE_NAME"

    # Wait a moment for service to start
    sleep 2

    # Check service status
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        log_info "Service started successfully!"

        # Show status
        echo ""
        echo "=========================================="
        echo "Service Status:"
        sudo systemctl status "$SERVICE_NAME" --no-pager
        echo ""
        echo "Service endpoints:"
        echo "  Health: http://$SERVICE_HOST:$SERVICE_PORT/health"
        echo "  Logs level: POST http://$SERVICE_HOST:$SERVICE_PORT/logs/level"
        echo "  Run task: POST http://$SERVICE_HOST:$SERVICE_PORT/task"
        echo ""
        echo "Log file: $LOG_DIR/invocations.jsonl"
        echo "View logs: journalctl -u $SERVICE_NAME -f"
        echo "=========================================="
    else
        log_error "Service failed to start. Check logs with:"
        echo "  journalctl -u $SERVICE_NAME -n 50"
        sudo systemctl status "$SERVICE_NAME" --no-pager
    fi
}

# =============================================================================
# Main deployment flow
# =============================================================================

main() {
    echo ""
    echo "=================================================="
    echo "  Browser-Use Backend Service Deployment"
    echo "=================================================="
    echo ""

    check_prerequisites
    setup_repository
    setup_venv
    setup_env
    setup_log_dir
    install_systemd_service
    start_service

    log_info "Deployment complete!"
}

main "$@"