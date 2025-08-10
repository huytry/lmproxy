# LMArena Gateway - Distributed Architecture Implementation Guide

## 🏗️ Architecture Overview

This implementation creates a distributed AI API gateway system where:

- **cPanel-hosted PHP Gateway** (Our Platform): Acts as the centralized middle manager
- **Client-side LMArenaBridge instances**: Handle actual LMArena.ai communication
- **Seamless Integration**: Clients connect their local instances to our centralized platform

## 🌐 System Architecture

```
┌─────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   API Clients   │───▶│  cPanel PHP Platform │───▶│ Client LMArenaBridge│
│                 │    │                      │    │                     │
│ - OpenAI Format │    │ - Authentication     │    │ - LMArena.ai Comm  │
│ - Standard APIs │    │ - Request Routing    │    │ - Session Management│
│ - Any Language  │    │ - Load Balancing     │    │ - Response Streaming│
└─────────────────┘    │ - Analytics & Billing│    └─────────────────────┘
                       │ - Client Management  │
                       └──────────────────────┘
```

## 📁 Project Structure

```
php/
├── app/
│   ├── ClientManager.php           # Client registration & management
│   ├── RequestRouter.php           # Distributed request routing
│   ├── ClientConfigGenerator.php   # Client package generation
│   ├── Config.php                  # Configuration management
│   ├── SessionStore.php           # Session storage
│   └── LMArenaBridgeProvider.php   # Direct integration fallback
├── public/
│   ├── index.php                   # Main API gateway
│   └── dashboard.html              # Client management dashboard
└── storage/
    └── clients.json                # Client registry

client-integration/
├── lmarena_platform_integration.py # Platform integration module
├── config_template.jsonc          # Configuration template
├── setup_client.sh               # Automated setup script
├── docker-compose.yml             # Docker deployment
├── Dockerfile                     # Container configuration
├── .env.example                   # Environment variables
└── README.md                      # Client setup guide
```

## 🚀 Platform Deployment (cPanel)

### 1. Upload PHP Files

```bash
# Upload to your cPanel hosting
/public_html/api/
├── index.php
├── dashboard.html
└── app/
    ├── ClientManager.php
    ├── RequestRouter.php
    ├── ClientConfigGenerator.php
    └── ...
```

### 2. Configure Environment

Create `.htaccess` in `/public_html/api/`:

```apache
RewriteEngine On
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^(.*)$ index.php [QSA,L]

# Enable CORS
Header always set Access-Control-Allow-Origin "*"
Header always set Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS"
Header always set Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With, X-Session-Name, X-Target-Domain, X-Provider"
```

### 3. Set Permissions

```bash
chmod 755 /public_html/api/
chmod 644 /public_html/api/*.php
chmod 755 /public_html/api/app/
chmod 644 /public_html/api/app/*.php
mkdir -p /public_html/api/storage
chmod 755 /public_html/api/storage
```

### 4. Test Platform

Visit: `https://your-domain.com/api/providers/status`

Expected response:
```json
{
  "distributed_clients": {
    "enabled": true,
    "total_clients": 0,
    "routing_stats": {...}
  }
}
```

## 👥 Client Registration Process

### 1. Access Dashboard

Visit: `https://your-domain.com/api/dashboard.html`

### 2. Register New Client

1. Click "Register New Client"
2. Fill in client details:
   - **Name**: Friendly identifier
   - **Email**: Contact information
   - **LMArenaBridge URL**: `http://127.0.0.1:5102`
   - **Rate Limits**: Set appropriate limits

3. Download the generated client package (ZIP file)

### 3. Client Package Contents

```
lmarena-client-{CLIENT_ID}.zip
├── config.jsonc                    # Pre-configured settings
├── lmarena_platform_integration.py # Integration module
├── setup_client.sh                # Automated setup
├── docker-compose.yml             # Container deployment
├── Dockerfile                     # Container configuration
├── .env.example                   # Environment template
├── userscript.js                  # Enhanced Tampermonkey script
└── README.md                      # Setup instructions
```

## 🖥️ Client Setup Process

### Option 1: Automated Setup

```bash
# Extract client package
unzip lmarena-client-{CLIENT_ID}.zip
cd lmarena-client-{CLIENT_ID}

# Run automated setup
chmod +x setup_client.sh
./setup_client.sh
```

### Option 2: Manual Setup

```bash
# Clone LMArenaBridge
git clone https://github.com/Lianues/LMArenaBridge.git
cd LMArenaBridge

# Install dependencies
pip install -r requirements.txt

# Copy platform integration files
cp /path/to/client-package/lmarena_platform_integration.py ./
cp /path/to/client-package/config.jsonc ./

# Configure session IDs
python id_updater.py

# Install Tampermonkey userscript
# (Copy from client package)

# Start client
python api_server.py
```

### Option 3: Docker Deployment

```bash
# Extract client package
unzip lmarena-client-{CLIENT_ID}.zip
cd lmarena-client-{CLIENT_ID}

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Start with Docker
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f lmarena-bridge-client
```

## 🔄 Request Flow

### 1. Client Request

```bash
curl -X POST https://your-domain.com/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -H "X-Provider: distributed" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

### 2. Platform Processing

1. **Authentication**: Validate API key
2. **Client Selection**: Choose available LMArenaBridge client
3. **Rate Limiting**: Check client limits
4. **Request Forwarding**: Send to selected client
5. **Response Streaming**: Stream back to original client

### 3. Client Processing

1. **Request Reception**: Receive from platform
2. **LMArena Communication**: Use local session
3. **Response Streaming**: Stream back to platform
4. **Statistics Reporting**: Update performance metrics

## 📊 Monitoring and Management

### Platform Dashboard

Access: `https://your-domain.com/api/dashboard.html`

Features:
- **Client Registration**: Register new clients
- **Client Status**: Monitor connection status
- **Performance Metrics**: View request statistics
- **Health Checks**: Monitor client health
- **Configuration Downloads**: Get client packages

### API Endpoints

```bash
# List all clients
GET /api/clients

# Get client details
GET /api/clients/{client_id}

# Download client package
GET /api/clients/{client_id}/download

# Perform health checks
POST /api/clients/health

# Platform statistics
GET /api/providers/status
```

### Client Monitoring

```bash
# Health check
curl http://127.0.0.1:5102/health

# Platform integration status
curl http://127.0.0.1:5102/platform/status

# Statistics
curl http://127.0.0.1:5102/stats
```

## 🔧 Configuration Options

### Platform Configuration

Environment variables for cPanel hosting:

```bash
GATEWAY_REQUEST_TIMEOUT=300
GATEWAY_RETRY_ATTEMPTS=3
GATEWAY_LOAD_BALANCING=least_load
```

### Client Configuration

Key settings in `config.jsonc`:

```jsonc
{
  "platform_integration": {
    "enabled": true,
    "platform_url": "https://your-domain.com/api",
    "client_id": "your-client-id",
    "api_key": "your-api-key",
    "heartbeat_interval_seconds": 30,
    "capabilities": ["chat", "models", "images"]
  }
}
```

## 🛠️ Troubleshooting

### Common Issues

1. **Client Connection Failed**
   - Check internet connectivity
   - Verify platform URL and credentials
   - Check firewall settings

2. **Session ID Errors**
   - Run `python id_updater.py`
   - Ensure Tampermonkey script is active
   - Check LMArena.ai login status

3. **Rate Limiting**
   - Check client rate limits in dashboard
   - Monitor request patterns
   - Adjust limits if needed

4. **Performance Issues**
   - Monitor client health in dashboard
   - Check system resources
   - Review network connectivity

### Debug Mode

Enable debug logging:

```jsonc
{
  "platform_integration": {
    "log_level": "DEBUG",
    "enable_request_logging": true
  }
}
```

## 🔒 Security Considerations

### Platform Security

- **API Key Authentication**: Secure client authentication
- **Rate Limiting**: Prevent abuse
- **Request Validation**: Validate all inputs
- **HTTPS Only**: Use secure connections

### Client Security

- **Secure API Keys**: Keep credentials safe
- **Local Network**: Bind to localhost only
- **Session Protection**: Secure LMArena sessions
- **Regular Updates**: Keep software updated

## 📈 Scaling and Performance

### Load Balancing Strategies

1. **Least Load**: Route to client with lowest load
2. **Round Robin**: Distribute requests evenly
3. **Random**: Random client selection

### Performance Optimization

- **Connection Pooling**: Reuse HTTP connections
- **Request Queuing**: Handle burst traffic
- **Caching**: Cache responses when appropriate
- **Compression**: Enable response compression

### Monitoring Metrics

- **Request Rate**: Requests per second
- **Response Time**: Average response latency
- **Success Rate**: Percentage of successful requests
- **Client Health**: Connection status and performance

## 🚀 Production Deployment

### Platform Checklist

- [ ] Upload all PHP files to cPanel
- [ ] Configure `.htaccess` for routing
- [ ] Set proper file permissions
- [ ] Test API endpoints
- [ ] Configure monitoring
- [ ] Set up SSL certificate

### Client Checklist

- [ ] Register client in dashboard
- [ ] Download client package
- [ ] Configure LMArenaBridge
- [ ] Set up session IDs
- [ ] Install Tampermonkey script
- [ ] Test connection to platform
- [ ] Configure monitoring
- [ ] Set up auto-restart

This distributed architecture provides a scalable, manageable solution for LMArena.ai integration while maintaining centralized control and monitoring through your cPanel-hosted PHP platform.
