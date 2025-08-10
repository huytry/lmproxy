#!/bin/bash
# setup_client.sh - Automated setup script for LMArenaBridge client integration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
LMARENA_BRIDGE_REPO="https://github.com/Lianues/LMArenaBridge.git"
INSTALL_DIR="$HOME/lmarena-bridge-client"
PYTHON_MIN_VERSION="3.8"

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_python_version() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        REQUIRED_VERSION="3.8"
        
        if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
            log_success "Python $PYTHON_VERSION found (>= $REQUIRED_VERSION required)"
            return 0
        else
            log_error "Python $PYTHON_VERSION found, but >= $REQUIRED_VERSION required"
            return 1
        fi
    else
        log_error "Python 3 not found. Please install Python 3.8 or higher."
        return 1
    fi
}

check_git() {
    if command -v git &> /dev/null; then
        log_success "Git found"
        return 0
    else
        log_error "Git not found. Please install Git."
        return 1
    fi
}

check_curl() {
    if command -v curl &> /dev/null; then
        log_success "curl found"
        return 0
    else
        log_error "curl not found. Please install curl."
        return 1
    fi
}

install_lmarena_bridge() {
    log_info "Installing LMArenaBridge..."
    
    if [ -d "$INSTALL_DIR" ]; then
        log_warning "Installation directory already exists: $INSTALL_DIR"
        read -p "Do you want to remove it and reinstall? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
        else
            log_error "Installation cancelled"
            exit 1
        fi
    fi
    
    git clone "$LMARENA_BRIDGE_REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    
    log_success "LMArenaBridge cloned to $INSTALL_DIR"
}

install_dependencies() {
    log_info "Installing Python dependencies..."
    
    cd "$INSTALL_DIR"
    
    # Install base requirements
    pip3 install -r requirements.txt
    
    # Install platform integration requirements if available
    if [ -f "requirements_platform.txt" ]; then
        pip3 install -r requirements_platform.txt
    fi
    
    log_success "Dependencies installed"
}

setup_platform_integration() {
    log_info "Setting up platform integration..."
    
    cd "$INSTALL_DIR"
    
    # Copy platform integration files if they exist in the current directory
    if [ -f "../lmarena_platform_integration.py" ]; then
        cp ../lmarena_platform_integration.py ./
        log_success "Platform integration module copied"
    else
        log_warning "Platform integration module not found. You'll need to copy it manually."
    fi
    
    # Copy configuration template
    if [ -f "../config_template.jsonc" ]; then
        if [ ! -f "config.jsonc" ]; then
            cp ../config_template.jsonc ./config.jsonc
            log_success "Configuration template copied"
        else
            log_warning "config.jsonc already exists. Template not copied."
        fi
    else
        log_warning "Configuration template not found."
    fi
}

configure_client() {
    log_info "Configuring client..."
    
    cd "$INSTALL_DIR"
    
    # Check if config.jsonc exists
    if [ ! -f "config.jsonc" ]; then
        log_error "config.jsonc not found. Please copy the configuration from your client package."
        return 1
    fi
    
    # Prompt for client configuration
    echo
    log_info "Please provide your client configuration details:"
    
    read -p "Platform URL (e.g., https://your-domain.com/api): " PLATFORM_URL
    read -p "Client ID: " CLIENT_ID
    read -p "API Key: " API_KEY
    
    if [ -z "$PLATFORM_URL" ] || [ -z "$CLIENT_ID" ] || [ -z "$API_KEY" ]; then
        log_error "All configuration fields are required"
        return 1
    fi
    
    # Update configuration file
    sed -i.bak "s|https://your-platform-domain.com/api|$PLATFORM_URL|g" config.jsonc
    sed -i.bak "s|CLIENT_ID_PLACEHOLDER|$CLIENT_ID|g" config.jsonc
    sed -i.bak "s|API_KEY_PLACEHOLDER|$API_KEY|g" config.jsonc
    
    log_success "Configuration updated"
}

setup_session_ids() {
    log_info "Setting up LMArena session IDs..."
    
    cd "$INSTALL_DIR"
    
    echo
    log_warning "You need to capture your LMArena session IDs."
    log_info "Steps:"
    log_info "1. Make sure you're logged into LMArena.ai in your browser"
    log_info "2. Install the provided Tampermonkey userscript"
    log_info "3. Run the ID updater script"
    echo
    
    read -p "Do you want to run the ID updater now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python3 id_updater.py
    else
        log_warning "Remember to run 'python3 id_updater.py' before starting the client"
    fi
}

create_start_script() {
    log_info "Creating start script..."
    
    cd "$INSTALL_DIR"
    
    cat > start_client.sh << 'EOF'
#!/bin/bash
# Start LMArenaBridge client with platform integration

set -e

echo "Starting LMArenaBridge Client..."

# Check if config exists
if [ ! -f "config.jsonc" ]; then
    echo "Error: config.jsonc not found. Please configure the client first."
    exit 1
fi

# Check if session IDs are configured
if grep -q "YOUR_SESSION_ID_HERE" config.jsonc; then
    echo "Warning: Session IDs not configured. Run 'python3 id_updater.py' first."
    echo "Continuing anyway..."
fi

# Check if platform integration is available
if [ ! -f "lmarena_platform_integration.py" ]; then
    echo "Warning: Platform integration module not found."
fi

# Start the server
echo "Starting LMArenaBridge server..."
python3 api_server.py
EOF
    
    chmod +x start_client.sh
    log_success "Start script created: start_client.sh"
}

create_systemd_service() {
    log_info "Creating systemd service..."
    
    SERVICE_FILE="$HOME/.config/systemd/user/lmarena-bridge-client.service"
    mkdir -p "$(dirname "$SERVICE_FILE")"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=LMArenaBridge Client
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 api_server.py
Restart=always
RestartSec=10
Environment=PATH=/usr/bin:/usr/local/bin
Environment=PYTHONPATH=$INSTALL_DIR

[Install]
WantedBy=default.target
EOF
    
    # Reload systemd and enable service
    systemctl --user daemon-reload
    systemctl --user enable lmarena-bridge-client.service
    
    log_success "Systemd service created and enabled"
    log_info "Use 'systemctl --user start lmarena-bridge-client' to start the service"
    log_info "Use 'systemctl --user status lmarena-bridge-client' to check status"
}

show_completion_message() {
    echo
    log_success "LMArenaBridge client setup completed!"
    echo
    log_info "Next steps:"
    log_info "1. Configure your session IDs: cd $INSTALL_DIR && python3 id_updater.py"
    log_info "2. Install the Tampermonkey userscript from your client package"
    log_info "3. Start the client: cd $INSTALL_DIR && ./start_client.sh"
    log_info "4. Or use systemd: systemctl --user start lmarena-bridge-client"
    echo
    log_info "Configuration file: $INSTALL_DIR/config.jsonc"
    log_info "Logs: Check the terminal output or systemd logs"
    echo
    log_warning "Remember to keep your API key secure and don't share it!"
}

# Main execution
main() {
    echo "=========================================="
    echo "  LMArenaBridge Client Setup Script"
    echo "=========================================="
    echo
    
    # Check prerequisites
    log_info "Checking prerequisites..."
    check_python_version || exit 1
    check_git || exit 1
    check_curl || exit 1
    
    # Install LMArenaBridge
    install_lmarena_bridge
    
    # Install dependencies
    install_dependencies
    
    # Setup platform integration
    setup_platform_integration
    
    # Configure client
    configure_client || exit 1
    
    # Setup session IDs
    setup_session_ids
    
    # Create start script
    create_start_script
    
    # Create systemd service (optional)
    read -p "Do you want to create a systemd service for auto-start? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        create_systemd_service
    fi
    
    # Show completion message
    show_completion_message
}

# Run main function
main "$@"
