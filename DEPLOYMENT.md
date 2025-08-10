# LMArena Gateway - Complete Deployment Guide

This guide provides step-by-step instructions for deploying the PHP AI API Gateway system on cPanel hosting with Apache APISIX integration.

## Prerequisites

- cPanel hosting account with PHP 7.4+ support
- SSH access (optional but recommended)
- Domain or subdomain for the gateway
- LMArenaBridge instance (can be on same server or remote)

## Step 1: File Upload and Structure

### Upload Files to cPanel

1. **Access File Manager** in cPanel
2. **Navigate** to your domain's document root (usually `public_html/`)
3. **Create subdirectory** (optional): `mkdir ai-gateway`
4. **Upload** the entire `php/` directory contents
5. **Set Document Root** to point to `php/public/` directory

### Expected Directory Structure
```
your-domain.com/
├── php/
│   ├── app/
│   │   ├── Config.php
│   │   └── SessionStore.php
│   ├── public/
│   │   ├── index.php
│   │   └── .htaccess
│   ├── scripts/
│   │   ├── cleanup-sessions.php
│   │   └── test-gateway.php
│   ├── storage/          # Auto-created, needs write permissions
│   ├── composer.json
│   ├── .env.example
│   └── README.md
```

## Step 2: Environment Configuration

### Set Environment Variables in cPanel

1. **Navigate** to "Environment Variables" in cPanel
2. **Add** the following variables:

```bash
# Required
LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102

# Optional
LMARENA_BRIDGE_API_KEY=your_bridge_api_key_if_needed
GATEWAY_SESSION_CLEANUP_DAYS=30
DEBUG_MODE=false
```

### Alternative: Create .env file

If environment variables aren't available, create `.env` file:

```bash
# Copy example file
cp .env.example .env

# Edit with your values
nano .env
```

## Step 3: Permissions and Security

### Set File Permissions

```bash
# Via SSH
chmod 755 php/
chmod 755 php/public/
chmod 644 php/public/index.php
chmod 644 php/public/.htaccess
chmod 775 php/storage/          # Must be writable
chmod 755 php/scripts/
chmod +x php/scripts/*.php

# Via cPanel File Manager
# Right-click → Change Permissions
# storage/ directory: 775 (rwxrwxr-x)
# Other directories: 755 (rwxr-xr-x)
# PHP files: 644 (rw-r--r--)
```

### Security Hardening

```bash
# Protect sensitive files
echo "deny from all" > php/storage/.htaccess
echo "deny from all" > php/app/.htaccess
echo "deny from all" > php/scripts/.htaccess

# Hide .env file
echo -e "Files ~ \"^\.env\"\n  Require all denied\n</Files>" >> php/public/.htaccess
```

## Step 4: Test Installation

### Run Test Script

```bash
# Via SSH
cd php/
php scripts/test-gateway.php

# Expected output:
# LMArena Gateway Test Suite
# =========================
# 
# Testing Config...
#   ✅ Bridge URL valid: http://127.0.0.1:5102
#   ✅ Allowed domains configured (4 domains)
# 
# Testing storage permissions...
#   ✅ Storage directory writable: /path/to/storage
#   ✅ Can write to storage directory
# 
# Testing SessionStore...
#   ✅ Set test mapping
#   ✅ Retrieved test mapping correctly
#   ✅ Stats working (total sessions: 1)
#   ✅ Cleaned up test mapping
# 
# Test Results: 3/3 passed
# 🎉 All tests passed! Gateway is ready for deployment.
```

### Test Web Endpoints

```bash
# Health check
curl https://your-domain.com/health

# Expected response:
# {"status":"ok","time":"2024-01-15T10:30:00Z"}
```

## Step 5: LMArenaBridge Setup

### Option A: Same Server Deployment

If running LMArenaBridge on the same cPanel server:

1. **Upload LMArenaBridge** to a separate directory
2. **Install Python dependencies** (if cPanel supports Python apps)
3. **Configure** LMArenaBridge to bind to `127.0.0.1:5102`
4. **Start** LMArenaBridge service

### Option B: Remote LMArenaBridge

If LMArenaBridge runs on a separate server:

1. **Update environment variable**:
   ```bash
   LMARENA_BRIDGE_BASE_URL=http://your-bridge-server:5102
   ```
2. **Ensure network connectivity** between servers
3. **Configure firewall** to allow communication

## Step 6: Session Registration Setup

### Generate Tampermonkey Script

1. **Visit** your gateway URL:
   ```
   https://your-domain.com/userscript/generate?session_name=team-alpha
   ```

2. **Copy** the generated JavaScript code

3. **Install in Tampermonkey**:
   - Open Tampermonkey dashboard
   - Click "Create a new script"
   - Paste the generated code
   - Save the script

### Test Session Capture

1. **Open** lmarena.ai in your browser
2. **Perform** any "Retry" action to trigger an API call
3. **Check** browser console for registration messages:
   ```
   [LMArena Registrar] 🎯 Captured session IDs: {domain: "lmarena.ai", session_name: "team-alpha", ...}
   [LMArena Registrar] ✅ Successfully registered session: {...}
   ```

4. **Verify** registration via API:
   ```bash
   curl https://your-domain.com/session/list?domain=lmarena.ai
   ```

## Step 7: Apache APISIX Integration (Optional)

### Install APISIX

```bash
# Via Docker (recommended)
docker run -d --name apisix \
  -p 9080:9080 \
  -p 9443:9443 \
  -p 2379:2379 \
  -v /path/to/apisix.yaml:/usr/local/apisix/conf/apisix.yaml \
  apache/apisix:latest
```

### Configure Routes

Create `apisix.yaml`:

```yaml
routes:
  - uri: /v1/*
    name: openai-api
    methods: [GET, POST, OPTIONS]
    upstream:
      type: roundrobin
      nodes:
        your-php-server:80: 1
    plugins:
      cors: {}
      rate-limit:
        count: 100
        time_window: 60

  - uri: /session/*
    name: session-management
    methods: [GET, POST, DELETE, OPTIONS]
    upstream:
      type: roundrobin
      nodes:
        your-php-server:80: 1
    plugins:
      cors: {}

  - uri: /userscript/*
    name: userscript-generator
    methods: [GET]
    upstream:
      type: roundrobin
      nodes:
        your-php-server:80: 1

  - uri: /health
    name: health-check
    methods: [GET]
    upstream:
      type: roundrobin
      nodes:
        your-php-server:80: 1
```

### Add Authentication (Production)

```yaml
# Add to route plugins
key-auth:
  key: your-api-key-here
```

## Step 8: Usage Examples

### Register Session Manually

```bash
curl -X POST https://your-domain.com/session/register \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "lmarena.ai",
    "session_name": "my-session",
    "session_id": "12345678-1234-1234-1234-123456789abc",
    "message_id": "87654321-4321-4321-4321-cba987654321"
  }'
```

### Chat Completion

```bash
curl -X POST https://your-domain.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Session-Name: my-session" \
  -H "X-Target-Domain: lmarena.ai" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### List Models

```bash
curl -H "X-Session-Name: my-session" \
     -H "X-Target-Domain: lmarena.ai" \
     https://your-domain.com/v1/models
```

## Step 9: Monitoring and Maintenance

### Set Up Cron Jobs

Add to cPanel Cron Jobs:

```bash
# Clean up old sessions daily at 2 AM
0 2 * * * /usr/bin/php /path/to/php/scripts/cleanup-sessions.php 30

# Health check every 5 minutes
*/5 * * * * curl -s https://your-domain.com/health > /dev/null
```

### Log Monitoring

Monitor logs in cPanel:
- **Error Logs**: Check for PHP errors and gateway issues
- **Access Logs**: Monitor API usage patterns
- **Resource Usage**: Watch CPU and memory consumption

### Performance Optimization

```bash
# PHP configuration (php.ini)
memory_limit = 256M
max_execution_time = 300
upload_max_filesize = 10M
post_max_size = 10M

# Apache configuration (.htaccess)
Header set Cache-Control "no-cache"
Header unset ETag
FileETag None
```

## Troubleshooting

### Common Issues

1. **Storage Permission Errors**
   ```bash
   chmod 775 php/storage/
   chown www-data:www-data php/storage/
   ```

2. **Bridge Connection Failed**
   - Verify `LMARENA_BRIDGE_BASE_URL` is correct
   - Check firewall rules
   - Test connectivity: `curl http://127.0.0.1:5102/health`

3. **Session Registration Fails**
   - Check browser console for errors
   - Verify Tampermonkey script is active
   - Test manual registration via API

4. **CORS Issues**
   - Gateway includes permissive CORS headers
   - For production, configure APISIX with specific origins

### Debug Mode

Enable debug logging:

```bash
# Environment variable
DEBUG_MODE=true
LOG_REQUESTS=true

# Check logs
tail -f /path/to/error.log
```

## Security Checklist

- [ ] Set proper file permissions (755/644)
- [ ] Protect sensitive directories with .htaccess
- [ ] Use HTTPS for all external communication
- [ ] Set strong API keys if using authentication
- [ ] Configure APISIX rate limiting
- [ ] Monitor access logs for suspicious activity
- [ ] Keep LMArenaBridge on private network
- [ ] Regular security updates

## Support

For issues:
1. Check this deployment guide
2. Review error logs
3. Run test script: `php scripts/test-gateway.php`
4. Verify LMArenaBridge connectivity
5. Check session registration in browser console

## Next Steps

After successful deployment:
- Set up monitoring and alerting
- Configure backup procedures
- Plan scaling strategy
- Implement additional security measures
- Document your specific configuration
