# LMArenaBridge Client Integration Guide

## Overview

This guide helps you set up your local LMArenaBridge instance to work with our centralized PHP-based AI API Gateway platform. In this distributed architecture:

- **Our Platform** (cPanel-hosted PHP): Acts as the central manager, handling authentication, routing, analytics, and billing
- **Your LMArenaBridge** (Local): Handles the actual communication with LMArena.ai domains
- **Integration**: Your LMArenaBridge connects to our platform and processes requests on behalf of our users

## Architecture Flow

```
API Client → Our PHP Platform → Your LMArenaBridge → LMArena.ai
                    ↓
            (Manages auth, routing, analytics)
```

## Prerequisites

- Python 3.8 or higher
- LMArenaBridge repository cloned locally
- Chrome/Firefox with Tampermonkey extension
- Active LMArena.ai account with valid session
- Stable internet connection

## Quick Setup

### 1. Register Your Client

Visit our platform dashboard and register your LMArenaBridge instance:

1. Go to `https://your-platform-domain.com/dashboard.html`
2. Click "Register New Client"
3. Fill in your details:
   - **Client Name**: A friendly name for your instance
   - **Email**: Your contact email (optional)
   - **LMArenaBridge URL**: `http://127.0.0.1:5102` (default)
   - **Rate Limits**: Set your preferred limits

4. Download the generated client package (ZIP file)

### 2. Install LMArenaBridge

```bash
# Clone the repository
git clone https://github.com/Lianues/LMArenaBridge.git
cd LMArenaBridge

# Install dependencies
pip install -r requirements.txt
```

### 3. Install Platform Integration

```bash
# Extract your client package
unzip lmarena-client-YOUR_CLIENT_ID.zip

# Copy platform integration files
cp lmarena_platform_integration.py /path/to/LMArenaBridge/
cp config.jsonc /path/to/LMArenaBridge/config.jsonc
cp requirements_platform.txt /path/to/LMArenaBridge/

# Install platform dependencies
pip install -r requirements_platform.txt
```

### 4. Configure Session IDs

```bash
# Run the ID updater to capture your LMArena session IDs
cd /path/to/LMArenaBridge
python id_updater.py

# Follow the prompts to select mode (DirectChat/Battle)
# Open LMArena.ai in your browser and trigger a request
```

### 5. Install Enhanced Userscript

1. Open Tampermonkey in your browser
2. Create a new script
3. Copy the contents from `userscript.js` in your client package
4. Save and enable the script
5. Visit LMArena.ai to activate the script

### 6. Start Your Client

```bash
# Use the provided start script
chmod +x start_client.sh
./start_client.sh

# Or start manually
python api_server.py
```

## Integration Details

### Platform Communication

Your LMArenaBridge will automatically:

- **Register** with our platform on startup
- **Send heartbeats** every 30 seconds to maintain connection
- **Receive requests** from our platform via HTTP API
- **Process requests** using your local LMArena.ai session
- **Stream responses** back to our platform
- **Report statistics** for monitoring and analytics

### Request Flow

1. **Client Request**: User makes API request to our platform
2. **Authentication**: Our platform validates the request
3. **Routing**: Our platform selects your LMArenaBridge instance
4. **Forwarding**: Request is forwarded to your local instance
5. **Processing**: Your instance communicates with LMArena.ai
6. **Response**: Response is streamed back through our platform to the client

### Configuration Options

Your `config.jsonc` includes platform-specific settings:

```jsonc
{
  "platform_integration": {
    "enabled": true,
    "platform_url": "https://your-platform-domain.com/api",
    "client_id": "your-client-id",
    "api_key": "your-api-key",
    "heartbeat_interval_seconds": 30,
    "capabilities": ["chat", "models", "images"]
  }
}
```

## Monitoring and Management

### Health Checks

Your client automatically reports health status:

- **Connection Status**: Whether connected to our platform
- **Request Statistics**: Success/failure rates, response times
- **Resource Usage**: Memory, CPU, active requests
- **LMArena Status**: Session validity, rate limits

### Dashboard Access

Monitor your client through our platform dashboard:

- **Real-time Statistics**: Request counts, success rates
- **Performance Metrics**: Response times, throughput
- **Health Status**: Connection status, error rates
- **Configuration**: Update settings, download configs

### Logs and Debugging

Enable detailed logging in your `config.jsonc`:

```jsonc
{
  "platform_integration": {
    "log_level": "DEBUG",
    "enable_request_logging": true,
    "enable_performance_monitoring": true
  }
}
```

## Troubleshooting

### Connection Issues

**Problem**: Client can't connect to platform
**Solutions**:
- Verify internet connection
- Check firewall settings (allow outbound HTTPS)
- Validate client ID and API key
- Check platform URL in config

**Problem**: Frequent disconnections
**Solutions**:
- Check network stability
- Increase heartbeat interval
- Review platform logs for errors

### Authentication Errors

**Problem**: "Client not found" or "Invalid API key"
**Solutions**:
- Re-download client package from dashboard
- Verify client ID matches registration
- Check API key hasn't been regenerated

### Session ID Issues

**Problem**: "Session ID invalid" errors
**Solutions**:
- Run `python id_updater.py` again
- Ensure you're logged into LMArena.ai
- Check Tampermonkey script is active
- Clear browser cache and cookies

### Performance Issues

**Problem**: Slow response times
**Solutions**:
- Check your internet connection speed
- Monitor LMArena.ai status
- Review request queue size
- Check system resources (CPU, memory)

## Advanced Configuration

### Custom Request Handling

Modify `lmarena_platform_integration.py` to customize request processing:

```python
async def _handle_chat_completion(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    # Custom logic for chat completions
    # Integrate with existing LMArenaBridge functions
    pass
```

### Load Balancing

If running multiple instances, configure load balancing preferences:

```jsonc
{
  "platform_features": {
    "preferred_routing_strategy": "least_load",
    "max_concurrent_requests": 10
  }
}
```

### Security Settings

Configure security options:

```jsonc
{
  "platform_features": {
    "enable_request_validation": true,
    "allowed_origins": ["https://your-platform-domain.com"]
  }
}
```

## Support and Maintenance

### Regular Updates

1. **Platform Integration**: Updates distributed via our platform
2. **LMArenaBridge Core**: Follow upstream repository updates
3. **Configuration**: Download updated configs from dashboard

### Backup and Recovery

1. **Backup Configuration**: Save your `config.jsonc` and session IDs
2. **Export Statistics**: Download performance data from dashboard
3. **Recovery**: Re-register client if needed, restore configuration

### Contact Support

- **Platform Issues**: Contact our support team
- **LMArenaBridge Issues**: Check upstream repository
- **Integration Issues**: Review logs and documentation

## API Reference

### Health Check Endpoint

```bash
GET http://127.0.0.1:5102/health
```

Response:
```json
{
  "enabled": true,
  "connected": true,
  "healthy": true,
  "platform_url": "https://your-platform-domain.com/api",
  "client_id": "your-client-id",
  "stats": {
    "requests_processed": 1234,
    "success_rate": 98.5,
    "uptime_seconds": 86400
  }
}
```

### Platform Integration Status

```bash
GET http://127.0.0.1:5102/platform/status
```

### Manual Registration

```bash
POST http://127.0.0.1:5102/platform/register
```

## Best Practices

1. **Keep Session IDs Updated**: Run `id_updater.py` regularly
2. **Monitor Health**: Check dashboard for issues
3. **Stable Network**: Ensure reliable internet connection
4. **Resource Management**: Monitor system resources
5. **Security**: Keep API keys secure, use HTTPS
6. **Logging**: Enable appropriate log levels for debugging
7. **Updates**: Keep platform integration and LMArenaBridge updated

## License and Terms

By connecting your LMArenaBridge to our platform, you agree to:

- Process requests on behalf of our platform users
- Maintain reasonable uptime and performance
- Follow LMArena.ai terms of service
- Protect user data and maintain privacy
- Report issues and cooperate with debugging

Your LMArenaBridge instance remains under your control, and you can disconnect at any time.
