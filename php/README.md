# PHP AI API Gateway for LMArenaBridge

A production-ready PHP application that provides OpenAI-compatible API endpoints with session management and domain isolation for LMArenaBridge integration.

## Features

- **OpenAI-Compatible API**: Full compatibility with OpenAI client libraries
- **Session Management**: Domain-isolated session mapping with concurrent support
- **Streaming Support**: Server-Sent Events (SSE) passthrough for real-time responses
- **Domain Isolation**: Separate sessions for lmarena.ai, canary.lmarena.ai, alpha.lmarena.ai, beta.lmarena.ai
- **Tampermonkey Integration**: Auto-generated userscripts for session capture
- **Production Ready**: Comprehensive error handling, logging, and monitoring
- **cPanel Compatible**: Designed for shared hosting environments

## API Endpoints

### Core Endpoints
- `POST /v1/chat/completions` - OpenAI-compatible chat completions with streaming
- `POST /v1/images/generations` - Image generation passthrough
- `GET /v1/models` - Available models list

### Session Management
- `POST /session/register` - Register domain+session mappings
- `GET /session/list` - List current sessions (optional domain filter)
- `DELETE /session/{domain}/{session_name}` - Remove session mapping

### Utilities
- `GET /userscript/generate` - Generate Tampermonkey userscript
- `GET /health` - Health check endpoint

## Quick Start

### 1. cPanel Deployment

1. **Upload Files**
   ```bash
   # Upload the php/ directory to your cPanel file manager
   # Set document root to: php/public/
   ```

2. **Configure Environment**
   ```bash
   # In cPanel, set environment variables:
   LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102
   LMARENA_BRIDGE_API_KEY=your_api_key_if_needed
   ```

3. **Set Permissions**
   ```bash
   # Ensure storage directory is writable
   chmod 775 storage/
   ```

4. **Test Installation**
   ```bash
   # Run from SSH or cPanel terminal
   php scripts/test-gateway.php
   ```

### 2. Session Registration Workflow

1. **Generate Userscript**
   ```bash
   # Visit your gateway URL
   https://your-domain.com/userscript/generate?session_name=team-alpha
   ```

2. **Install in Tampermonkey**
   - Copy the generated script
   - Install in Tampermonkey browser extension
   - Script will auto-capture session IDs from LMArena

3. **Trigger Session Capture**
   - Open lmarena.ai (or subdomain)
   - Perform any "Retry" action to trigger API call
   - Script automatically registers session mapping

### 3. Using the Gateway

```bash
# Chat completion with session isolation
curl -X POST https://your-domain.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Session-Name: team-alpha" \
  -H "X-Target-Domain: lmarena.ai" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'

# List available models
curl -H "X-Session-Name: team-alpha" \
     -H "X-Target-Domain: lmarena.ai" \
     https://your-domain.com/v1/models

# Check session mappings
curl https://your-domain.com/session/list?domain=lmarena.ai
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LMARENA_BRIDGE_BASE_URL` | `http://127.0.0.1:5102` | LMArenaBridge server URL |
| `LMARENA_BRIDGE_API_KEY` | - | Optional API key for Bridge |
| `STORAGE_PATH` | `../storage/sessions.json` | Session storage file path |
| `GATEWAY_SESSION_CLEANUP_DAYS` | `30` | Auto-cleanup threshold |

### Supported Domains

- `lmarena.ai` (production)
- `canary.lmarena.ai` (canary)
- `alpha.lmarena.ai` (alpha)
- `beta.lmarena.ai` (beta)

## Session Management

### Concurrent Sessions

The gateway supports multiple concurrent sessions per domain:

```bash
# Team A session
curl -H "X-Session-Name: team-a" -H "X-Target-Domain: lmarena.ai" ...

# Team B session (concurrent)
curl -H "X-Session-Name: team-b" -H "X-Target-Domain: lmarena.ai" ...

# Cross-domain isolation
curl -H "X-Session-Name: team-a" -H "X-Target-Domain: canary.lmarena.ai" ...
```

### Session Registration API

```bash
# Manual session registration
curl -X POST https://your-domain.com/session/register \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "lmarena.ai",
    "session_name": "my-session",
    "session_id": "12345678-1234-1234-1234-123456789abc",
    "message_id": "87654321-4321-4321-4321-cba987654321",
    "bridge_base_url": "http://custom-bridge:5102",
    "models": {
      "gpt-4": "claude-3-5-sonnet-20241022"
    }
  }'
```

## Maintenance

### Session Cleanup

```bash
# Clean sessions older than 30 days
php scripts/cleanup-sessions.php 30

# Check storage stats
php scripts/cleanup-sessions.php 0
```

### Health Monitoring

```bash
# Health check
curl https://your-domain.com/health

# Response
{
  "status": "ok",
  "time": "2024-01-15T10:30:00Z"
}
```

## Apache APISIX Integration

Example APISIX configuration for production deployment:

```yaml
# apisix/routes.yaml
routes:
  - uri: /v1/*
    name: openai-api
    upstream:
      nodes:
        your-php-server:80: 1
    plugins:
      key-auth: {}
      rate-limit:
        count: 100
        time_window: 60
      cors: {}

  - uri: /session/*
    name: session-mgmt
    upstream:
      nodes:
        your-php-server:80: 1
    plugins:
      key-auth: {}
      cors: {}
```

## Troubleshooting

### Common Issues

1. **Storage Permission Errors**
   ```bash
   chmod 775 storage/
   chown www-data:www-data storage/
   ```

2. **Bridge Connection Failed**
   - Verify `LMARENA_BRIDGE_BASE_URL` is accessible
   - Check firewall rules for internal communication
   - Ensure LMArenaBridge is running and healthy

3. **Session Not Found**
   - Verify userscript is installed and active
   - Check browser console for registration errors
   - Manually register session via API if needed

4. **CORS Issues**
   - Gateway includes permissive CORS headers
   - For production, configure APISIX with specific origins

### Debug Mode

```bash
# Enable debug logging (cPanel environment variables)
DEBUG_MODE=true
LOG_REQUESTS=true
```

### Log Files

- PHP errors: Check cPanel error logs
- Gateway logs: `error_log()` calls in application
- Session activity: Logged to PHP error log with timestamps

## Security Considerations

### Production Deployment

1. **API Key Protection**
   ```bash
   # Set in cPanel environment, not in code
   LMARENA_BRIDGE_API_KEY=your-secret-key
   ```

2. **APISIX Security**
   - Enable key-auth plugin
   - Configure rate limiting
   - Restrict CORS origins

3. **File Permissions**
   ```bash
   # Secure storage directory
   chmod 750 storage/
   # Secure config files
   chmod 640 .env
   ```

4. **Network Security**
   - Keep LMArenaBridge on private network
   - Use HTTPS for all external communication
   - Monitor access logs

## Performance Optimization

### cPanel Optimization

1. **PHP Configuration**
   ```ini
   ; php.ini optimizations
   memory_limit = 256M
   max_execution_time = 300
   upload_max_filesize = 10M
   ```

2. **Apache Configuration**
   ```apache
   # .htaccess optimizations
   Header set Cache-Control "no-cache"
   Header unset ETag
   FileETag None
   ```

3. **Session Storage**
   - Consider Redis/Memcached for high-traffic deployments
   - Implement session cleanup cron job
   - Monitor storage file size

### Scaling Considerations

- **Horizontal Scaling**: Deploy multiple PHP instances behind APISIX
- **Session Sharing**: Use shared storage (Redis) for multi-instance deployments
- **Load Balancing**: Configure APISIX upstream with multiple PHP servers
- **Monitoring**: Implement health checks and metrics collection

## License

MIT License - see LICENSE file for details.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for error details
3. Test with the provided test script
4. Verify LMArenaBridge connectivity

