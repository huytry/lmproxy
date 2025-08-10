#!/bin/bash
# cpanel/deploy.sh
# Automated deployment script for cPanel hosting

set -e

echo "=========================================="
echo "  LMArena AI Gateway - cPanel Deployment"
echo "=========================================="

# Configuration
CPANEL_USER=${CPANEL_USER:-""}
CPANEL_DOMAIN=${CPANEL_DOMAIN:-""}
DEPLOYMENT_PATH=${DEPLOYMENT_PATH:-"public_html/api"}
BACKUP_PATH=${BACKUP_PATH:-"backups/api-$(date +%Y%m%d-%H%M%S)"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if [ -z "$CPANEL_USER" ]; then
        log_error "CPANEL_USER environment variable not set"
        exit 1
    fi
    
    if [ -z "$CPANEL_DOMAIN" ]; then
        log_error "CPANEL_DOMAIN environment variable not set"
        exit 1
    fi
    
    # Check if PHP files exist
    if [ ! -d "php" ]; then
        log_error "PHP directory not found. Run this script from the project root."
        exit 1
    fi
    
    # Check if Flask services exist
    if [ ! -d "flask_services" ]; then
        log_error "Flask services directory not found."
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

# Create backup
create_backup() {
    log_info "Creating backup..."
    
    if [ -d "$DEPLOYMENT_PATH" ]; then
        mkdir -p "$(dirname "$BACKUP_PATH")"
        cp -r "$DEPLOYMENT_PATH" "$BACKUP_PATH"
        log_info "Backup created at: $BACKUP_PATH"
    else
        log_warn "No existing deployment found, skipping backup"
    fi
}

# Deploy PHP application
deploy_php() {
    log_info "Deploying PHP application..."
    
    # Create deployment directory
    mkdir -p "$DEPLOYMENT_PATH"
    
    # Copy PHP files
    cp -r php/* "$DEPLOYMENT_PATH/"
    
    # Set permissions
    chmod -R 755 "$DEPLOYMENT_PATH"
    chmod -R 775 "$DEPLOYMENT_PATH/storage"
    
    # Create .htaccess for pretty URLs
    cat > "$DEPLOYMENT_PATH/.htaccess" << 'EOF'
RewriteEngine On

# Handle CORS preflight requests
RewriteCond %{REQUEST_METHOD} OPTIONS
RewriteRule ^(.*)$ $1 [R=200,L]

# Route all requests to index.php
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^(.*)$ index.php [QSA,L]

# Security headers
Header always set X-Content-Type-Options nosniff
Header always set X-Frame-Options DENY
Header always set X-XSS-Protection "1; mode=block"

# CORS headers
Header always set Access-Control-Allow-Origin "*"
Header always set Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS"
Header always set Access-Control-Allow-Headers "Content-Type, Authorization, X-Session-Name, X-Target-Domain, X-Provider"
EOF
    
    log_info "PHP application deployed successfully"
}

# Deploy Flask services
deploy_flask() {
    log_info "Deploying Flask services..."
    
    FLASK_PATH="flask_app"
    mkdir -p "$FLASK_PATH"
    
    # Copy Flask files
    cp -r flask_services/* "$FLASK_PATH/"
    
    # Create passenger_wsgi.py for cPanel Python app
    cat > "$FLASK_PATH/passenger_wsgi.py" << 'EOF'
#!/usr/bin/env python3
import sys
import os

# Add the Flask app directory to Python path
sys.path.insert(0, os.path.dirname(__file__))

from app import app as application

if __name__ == "__main__":
    application.run()
EOF
    
    # Create startup script
    cat > "$FLASK_PATH/startup.sh" << 'EOF'
#!/bin/bash
# Install dependencies
pip3 install --user -r requirements.txt

# Set environment variables
export FLASK_ENV=production
export PHP_GATEWAY_URL="https://CPANEL_DOMAIN/api"

# The application will be started by Passenger
echo "Flask services configured for cPanel Python app"
EOF
    
    chmod +x "$FLASK_PATH/startup.sh"
    
    log_info "Flask services deployed successfully"
    log_warn "Remember to:"
    log_warn "1. Create a Python app in cPanel pointing to flask_app/"
    log_warn "2. Run startup.sh to install dependencies"
    log_warn "3. Set environment variables in cPanel"
}

# Configure environment
configure_environment() {
    log_info "Configuring environment..."
    
    # Create environment configuration
    cat > "$DEPLOYMENT_PATH/.env" << EOF
# LMArena Gateway Environment Configuration for cPanel
LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102
LMARENA_BRIDGE_API_KEY=

# LMArenaBridge Direct Integration Configuration
LMARENA_BRIDGE_ENABLED=true
LMARENA_BRIDGE_WS_URL=ws://127.0.0.1:5102/ws
LMARENA_BRIDGE_TIMEOUT=180
LMARENA_BRIDGE_MODELS_FILE=../LMArenaBridge/models.json
LMARENA_BRIDGE_CONFIG_FILE=../LMArenaBridge/config.jsonc
LMARENA_BRIDGE_MODEL_MAP_FILE=../LMArenaBridge/model_endpoint_map.json

# Flask Services Configuration
FLASK_SERVICES_ENABLED=true
FLASK_SERVICES_BASE_URL=https://${CPANEL_DOMAIN}/flask
FLASK_SERVICES_API_KEY=

# Gateway Configuration
GATEWAY_LOG_LEVEL=INFO
GATEWAY_MAX_SESSIONS_PER_DOMAIN=100
GATEWAY_SESSION_CLEANUP_DAYS=30
GATEWAY_ENABLE_SESSION_ANALYTICS=true
GATEWAY_CONCURRENT_SESSIONS_LIMIT=10

# Security
GATEWAY_API_KEY=
GATEWAY_RATE_LIMIT_PER_MINUTE=60

# Storage Configuration
STORAGE_PATH=../storage/sessions.json

# Development/Debug
DEBUG_MODE=false
LOG_REQUESTS=false
EOF
    
    log_info "Environment configuration created"
    log_warn "Please update .env file with your specific configuration"
}

# Create cPanel-specific files
create_cpanel_files() {
    log_info "Creating cPanel-specific files..."
    
    # Create PHP version file
    cat > "$DEPLOYMENT_PATH/.htaccess.php" << 'EOF'
# Force PHP version (adjust as needed)
AddHandler application/x-httpd-php81 .php
EOF
    
    # Create health check script
    cat > "$DEPLOYMENT_PATH/health-check.php" << 'EOF'
<?php
// Simple health check for cPanel monitoring
header('Content-Type: application/json');

$health = [
    'status' => 'ok',
    'timestamp' => date('c'),
    'php_version' => PHP_VERSION,
    'server' => $_SERVER['SERVER_SOFTWARE'] ?? 'unknown'
];

// Check if storage directory is writable
$storageDir = __DIR__ . '/storage';
if (!is_writable($storageDir)) {
    $health['status'] = 'warning';
    $health['warnings'][] = 'Storage directory not writable';
}

echo json_encode($health, JSON_PRETTY_PRINT);
?>
EOF
    
    log_info "cPanel-specific files created"
}

# Set up monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."
    
    # Create monitoring script
    cat > "monitor-gateway.sh" << 'EOF'
#!/bin/bash
# Gateway monitoring script for cPanel cron jobs

GATEWAY_URL="https://CPANEL_DOMAIN/api"
LOG_FILE="logs/gateway-monitor.log"

# Create logs directory
mkdir -p logs

# Check gateway health
response=$(curl -s -w "%{http_code}" "$GATEWAY_URL/health" -o /tmp/health_response.json)
http_code="${response: -3}"

timestamp=$(date '+%Y-%m-%d %H:%M:%S')

if [ "$http_code" = "200" ]; then
    echo "[$timestamp] Gateway health check: OK" >> "$LOG_FILE"
else
    echo "[$timestamp] Gateway health check: FAILED (HTTP $http_code)" >> "$LOG_FILE"
    # You can add email notification here
fi

# Clean up old logs (keep last 100 lines)
tail -n 100 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
EOF
    
    chmod +x monitor-gateway.sh
    
    log_info "Monitoring setup complete"
    log_warn "Add this to cPanel cron jobs to run every 5 minutes:"
    log_warn "*/5 * * * * /path/to/monitor-gateway.sh"
}

# Main deployment process
main() {
    log_info "Starting deployment process..."
    
    check_prerequisites
    create_backup
    deploy_php
    deploy_flask
    configure_environment
    create_cpanel_files
    setup_monitoring
    
    log_info "Deployment completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Upload files to your cPanel file manager"
    echo "2. Set document root to: $DEPLOYMENT_PATH/public"
    echo "3. Create Python app in cPanel for Flask services"
    echo "4. Configure environment variables in cPanel"
    echo "5. Set up cron job for monitoring"
    echo "6. Test the deployment: https://$CPANEL_DOMAIN/api/health"
    echo ""
    echo "For support, check the documentation or logs."
}

# Run main function
main "$@"
