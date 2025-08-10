# cPanel Deployment Guide for LMArena AI Gateway

This guide provides step-by-step instructions for deploying the PHP-based AI API gateway system on cPanel hosting with yupp2Api integration and Flask auxiliary services.

## Prerequisites

- cPanel hosting account with PHP 8.1+ support
- Python 3.8+ support (for Flask services)
- SSH access (recommended) or File Manager access
- Domain or subdomain for the gateway

## Quick Deployment

### 1. Automated Deployment (Recommended)

```bash
# Set environment variables
export CPANEL_USER="your_cpanel_username"
export CPANEL_DOMAIN="your-domain.com"

# Run deployment script
chmod +x cpanel/deploy.sh
./cpanel/deploy.sh
```

### 2. Manual Deployment

#### Step 1: Upload Files

1. **Upload PHP Application**
   - Create directory: `public_html/api/`
   - Upload all files from `php/` directory
   - Set permissions: 755 for directories, 644 for files
   - Set permissions: 775 for `storage/` directory

2. **Upload Flask Services**
   - Create directory: `flask_app/`
   - Upload all files from `flask_services/` directory

#### Step 2: Configure PHP Application

1. **Set Document Root** (if using subdomain)
   - In cPanel → Subdomains
   - Create subdomain: `api.your-domain.com`
   - Set document root to: `public_html/api/public`

2. **Configure .htaccess**
   ```apache
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
   ```

#### Step 3: Configure Flask Services

1. **Create Python App in cPanel**
   - Go to cPanel → Python App
   - Create new app:
     - Python version: 3.8+
     - App directory: `flask_app`
     - App URL: `/flask` (or subdomain)
     - Startup file: `passenger_wsgi.py`

2. **Install Dependencies**
   ```bash
   # In Python app terminal
   pip install -r requirements.txt
   ```

#### Step 4: Environment Configuration

1. **PHP Environment Variables** (cPanel → Environment Variables)
   ```
   LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102
   YUPP2_API_ENABLED=true
   YUPP2_API_BASE_URL=http://127.0.0.1:5103
   GATEWAY_MAX_SESSIONS_PER_DOMAIN=100
   GATEWAY_SESSION_CLEANUP_DAYS=30
   GATEWAY_ENABLE_SESSION_ANALYTICS=true
   ```

2. **Flask Environment Variables**
   ```
   FLASK_SERVICES_ENABLED=true
   PHP_GATEWAY_URL=https://your-domain.com/api
   FLASK_SERVICES_API_KEY=your_secure_api_key
   ```

## Configuration Details

### PHP Gateway Configuration

The PHP gateway supports multiple configuration methods:

1. **Environment Variables** (Recommended for cPanel)
2. **Config.php modifications**
3. **.env file** (if supported by hosting)

### Key Configuration Options

```php
// Core LMArenaBridge settings
LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102
LMARENA_BRIDGE_API_KEY=your_bridge_api_key

// yupp2Api provider settings
YUPP2_API_ENABLED=true
YUPP2_API_BASE_URL=http://127.0.0.1:5103
YUPP2_API_KEY=your_yupp2_api_key
YUPP2_API_TIMEOUT=30
YUPP2_API_RETRY_ATTEMPTS=3

// Session management
GATEWAY_MAX_SESSIONS_PER_DOMAIN=100
GATEWAY_SESSION_CLEANUP_DAYS=30
GATEWAY_ENABLE_SESSION_ANALYTICS=true
GATEWAY_CONCURRENT_SESSIONS_LIMIT=10

// Security
GATEWAY_API_KEY=your_gateway_api_key
GATEWAY_RATE_LIMIT_PER_MINUTE=60
```

## Testing the Deployment

### 1. Health Check

```bash
curl https://your-domain.com/api/health
```

Expected response:
```json
{
  "status": "ok",
  "time": "2024-01-15T10:30:00Z",
  "services": {
    "session_store": "healthy",
    "yupp2_api": "enabled"
  }
}
```

### 2. Provider Status

```bash
curl https://your-domain.com/api/providers/status
```

### 3. Generate Userscript

```bash
curl "https://your-domain.com/api/userscript/generate?session_name=test-session"
```

## Monitoring and Maintenance

### 1. Set Up Cron Jobs

Add to cPanel → Cron Jobs:

```bash
# Health monitoring (every 5 minutes)
*/5 * * * * /path/to/monitor-gateway.sh

# Session cleanup (daily at 2 AM)
0 2 * * * php /path/to/public_html/api/scripts/cleanup-sessions.php 30

# Log rotation (weekly)
0 0 * * 0 find /path/to/logs -name "*.log" -mtime +7 -delete
```

### 2. Log Monitoring

Monitor these log files:
- `logs/gateway-monitor.log` - Health check logs
- `logs/error.log` - PHP error logs
- `flask_app/logs/` - Flask service logs

### 3. Performance Optimization

1. **Enable PHP OPcache** in cPanel
2. **Configure memory limits**:
   ```php
   memory_limit = 256M
   max_execution_time = 300
   ```
3. **Enable gzip compression** in .htaccess

## Troubleshooting

### Common Issues

1. **Storage Permission Errors**
   ```bash
   chmod 775 public_html/api/storage/
   chown username:username public_html/api/storage/
   ```

2. **Flask App Not Starting**
   - Check Python version compatibility
   - Verify passenger_wsgi.py exists
   - Check Flask app logs

3. **CORS Issues**
   - Verify .htaccess CORS headers
   - Check if mod_headers is enabled

4. **Session Registration Failing**
   - Check storage directory permissions
   - Verify domain validation in Config.php
   - Test with curl commands

### Debug Mode

Enable debug mode temporarily:
```php
// In Config.php or environment variable
DEBUG_MODE=true
LOG_REQUESTS=true
```

## Security Considerations

1. **API Key Protection**
   - Use strong, unique API keys
   - Store in environment variables, not code
   - Rotate keys regularly

2. **Rate Limiting**
   - Configure appropriate limits
   - Monitor for abuse patterns

3. **HTTPS Only**
   - Force HTTPS redirects
   - Use secure headers

4. **File Permissions**
   - Restrict access to sensitive files
   - Regular permission audits

## Support and Updates

- Check logs for error details
- Monitor health endpoints
- Keep dependencies updated
- Regular security patches

For advanced configuration and troubleshooting, refer to the main documentation or contact support.
