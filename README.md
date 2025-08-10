# LMArena AI API Gateway System

A comprehensive PHP-based AI API gateway system with Apache APISIX integration, yupp2Api provider support, and advanced session management for LMArena platforms.

## 🚀 Features

### Core Components
- **PHP API Gateway**: High-performance OpenAI-compatible API gateway
- **Apache APISIX Integration**: Enterprise-grade API management and routing
- **LMArenaBridge Integration**: Direct integration with LMArenaBridge for LMArena.ai access
- **Flask Auxiliary Services**: Advanced analytics and userscript generation
- **Enhanced Session Management**: Multi-session concurrent support with domain isolation

### Advanced Capabilities
- **Multi-Provider Routing**: Intelligent routing between legacy WebSocket and direct LMArenaBridge
- **Domain-Specific Isolation**: Separate sessions for lmarena.ai, canary.lmarena.ai, alpha.lmarena.ai, beta.lmarena.ai
- **Concurrent Session Support**: Multiple sessions per user in the same browser
- **Auto-Generated Userscripts**: Dynamic Tampermonkey script generation with persistence
- **Real-time Analytics**: Session monitoring and performance metrics
- **cPanel Deployment Ready**: Optimized for shared hosting environments

## 📋 System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Apache APISIX │────│  PHP API Gateway │────│  Session Store  │
│   (Rate Limit,  │    │  (Multi-Provider │    │  (JSON/Redis)   │
│   Auth, CORS)   │    │   Routing)       │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                        │                        │
         │                        ├────────────────────────┼─────────────┐
         │                        │                        │             │
         ▼                        ▼                        ▼             ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────┐
│ Tampermonkey    │    │  LMArenaBridge   │    │ LMArenaBridge   │    │ Flask        │
│ Userscripts     │    │  (Legacy WS)     │    │ (Direct API)    │    │ Services     │
│ (Auto-generated)│    │                  │    │                 │    │ (Analytics)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────┘
```

## 🛠 Installation

### Quick Start (Recommended)

1. **Clone Repository**
   ```bash
   git clone https://github.com/your-repo/lmarena-gateway.git
   cd lmarena-gateway
   ```

2. **Configure Environment**
   ```bash
   cp php/.env.example php/.env
   # Edit php/.env with your configuration
   ```

3. **Deploy to cPanel**
   ```bash
   export CPANEL_USER="your_username"
   export CPANEL_DOMAIN="your-domain.com"
   chmod +x cpanel/deploy.sh
   ./cpanel/deploy.sh
   ```

### Manual Installation

#### 1. PHP Gateway Setup

```bash
# Install PHP dependencies
cd php
composer install --no-dev --optimize-autoloader

# Set permissions
chmod -R 755 .
chmod -R 775 storage/

# Configure environment
cp .env.example .env
# Edit .env file with your settings
```

#### 2. Flask Services Setup

```bash
# Install Python dependencies
cd flask_services
pip install -r requirements.txt

# Configure environment
export FLASK_SERVICES_API_KEY="your-secure-key"
export PHP_GATEWAY_URL="https://your-domain.com/api"

# Start Flask services
python app.py
```

#### 3. Apache APISIX Setup

```bash
# Install APISIX (Docker recommended)
docker run -d --name apisix \
  -p 9080:9080 -p 9091:9091 -p 9443:9443 \
  -v $(pwd)/apisix/apisix.yaml:/usr/local/apisix/conf/apisix.yaml \
  apache/apisix:latest

# Or use the configuration file
cp apisix/apisix.yaml /path/to/apisix/conf/
```

## 🔧 Configuration

### Environment Variables

```bash
# LMArenaBridge Legacy WebSocket
LMARENA_BRIDGE_BASE_URL=http://127.0.0.1:5102
LMARENA_BRIDGE_API_KEY=your_bridge_key

# LMArenaBridge Direct Integration
LMARENA_BRIDGE_ENABLED=true
LMARENA_BRIDGE_WS_URL=ws://127.0.0.1:5102/ws
LMARENA_BRIDGE_TIMEOUT=180
LMARENA_BRIDGE_MODELS_FILE=../LMArenaBridge/models.json
LMARENA_BRIDGE_CONFIG_FILE=../LMArenaBridge/config.jsonc
LMARENA_BRIDGE_MODEL_MAP_FILE=../LMArenaBridge/model_endpoint_map.json

# Flask Services
FLASK_SERVICES_ENABLED=true
FLASK_SERVICES_BASE_URL=http://127.0.0.1:5104
FLASK_SERVICES_API_KEY=your_flask_key

# Session Management
GATEWAY_MAX_SESSIONS_PER_DOMAIN=100
GATEWAY_SESSION_CLEANUP_DAYS=30
GATEWAY_ENABLE_SESSION_ANALYTICS=true
GATEWAY_CONCURRENT_SESSIONS_LIMIT=10

# Security
GATEWAY_API_KEY=your_gateway_key
GATEWAY_RATE_LIMIT_PER_MINUTE=60
```

## 📚 API Documentation

### Core Endpoints

#### OpenAI-Compatible API
```bash
# Chat completions with provider routing
POST /v1/chat/completions
Headers:
  Content-Type: application/json
  Authorization: Bearer your-api-key
  X-Session-Name: session-name
  X-Target-Domain: lmarena.ai
  X-Provider: auto|lmarena|bridge_direct

# Image generation
POST /v1/images/generations

# List models
GET /v1/models
```

#### Session Management
```bash
# Register session
POST /session/register
{
  "domain": "lmarena.ai",
  "session_name": "my-session",
  "session_id": "uuid-here",
  "message_id": "uuid-here"
}

# List sessions
GET /session/list?domain=lmarena.ai

# Delete session
DELETE /session/{domain}/{session_name}

# Session heartbeat
POST /session/heartbeat
{
  "domain": "lmarena.ai",
  "session_name": "my-session"
}
```

#### Analytics & Monitoring
```bash
# Session analytics
GET /analytics/sessions
Headers:
  Authorization: Bearer analytics-api-key

# Provider status
GET /providers/status

# Health check
GET /health
```

#### Userscript Generation
```bash
# Basic userscript
GET /userscript/generate?session_name=my-session

# Advanced userscript (Flask services)
GET /userscript/advanced-generate?session_name=my-session&domain_filter=all&enable_analytics=true
Headers:
  Authorization: Bearer flask-api-key
```

## 🎯 Usage Examples

### 1. Basic Chat Completion

```bash
curl -X POST https://your-domain.com/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-api-key" \
  -H "X-Session-Name: my-session" \
  -H "X-Target-Domain: lmarena.ai" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### 2. Provider-Specific Routing

```bash
# Force direct LMArenaBridge integration
curl -X POST https://your-domain.com/api/v1/chat/completions \
  -H "X-Provider: bridge_direct" \
  -H "X-Session-Name: bridge-session" \
  -d '{"model": "gpt-4", "messages": [...]}'

# Force legacy WebSocket LMArenaBridge
curl -X POST https://your-domain.com/api/v1/chat/completions \
  -H "X-Provider: lmarena" \
  -H "X-Session-Name: lmarena-session" \
  -d '{"model": "gpt-4", "messages": [...]}'
```

### 3. Session Registration

```bash
# Register a new session
curl -X POST https://your-domain.com/api/session/register \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "lmarena.ai",
    "session_name": "team-alpha",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
  }'
```

### 4. Generate Enhanced Userscript

```bash
# Generate userscript with analytics
curl "https://your-domain.com/api/userscript/advanced-generate?session_name=enhanced-session&enable_analytics=true&auto_retry=true&debug_mode=false" \
  -H "Authorization: Bearer flask-api-key" \
  -o enhanced-userscript.user.js
```

## 🏗 cPanel Deployment

### Automated Deployment

The system includes automated deployment scripts optimized for cPanel hosting:

```bash
# Set your cPanel credentials
export CPANEL_USER="your_username"
export CPANEL_DOMAIN="your-domain.com"

# Run automated deployment
chmod +x cpanel/deploy.sh
./cpanel/deploy.sh
```

### Manual cPanel Setup

1. **Upload Files**
   - Upload `php/` contents to `public_html/api/`
   - Upload `flask_services/` contents to `flask_app/`

2. **Configure PHP App**
   - Set document root to `public_html/api/public`
   - Configure environment variables in cPanel

3. **Setup Python App**
   - Create Python app in cPanel
   - Point to `flask_app/` directory
   - Install dependencies: `pip install -r requirements.txt`

4. **Configure Cron Jobs**
   ```bash
   # Session cleanup (daily)
   0 2 * * * php /path/to/api/scripts/cleanup-sessions.php 30

   # Health monitoring (every 5 minutes)
   */5 * * * * /path/to/monitor-gateway.sh
   ```

For detailed cPanel setup instructions, see [cpanel/CPANEL_SETUP.md](cpanel/CPANEL_SETUP.md).

## 🔍 Monitoring & Analytics

### Health Monitoring

```bash
# Check overall system health
curl https://your-domain.com/api/health

# Check provider status
curl https://your-domain.com/api/providers/status

# Flask services health
curl https://your-domain.com/flask/health
```

### Session Analytics

```bash
# Get session analytics
curl -H "Authorization: Bearer analytics-key" \
  https://your-domain.com/analytics/sessions

# Response includes:
# - Total domains and sessions
# - Domain breakdown
# - Recent activity
# - Usage statistics
```

### Performance Metrics

The system integrates with Prometheus for metrics collection:
- Request rates and latencies
- Error rates by provider
- Session creation/deletion rates
- Provider health status

## 🛡 Security Features

### Authentication & Authorization
- **API Key Authentication**: Secure access to all endpoints
- **Rate Limiting**: Configurable per-endpoint rate limits
- **CORS Protection**: Proper CORS headers for web security
- **Input Validation**: Request validation and sanitization

### Session Security
- **Domain Isolation**: Sessions isolated by domain
- **Session Validation**: UUID format validation
- **Secure Storage**: File-based storage with proper permissions
- **Session Cleanup**: Automatic cleanup of old sessions

### Provider Security
- **Provider Isolation**: Separate authentication for each provider
- **Retry Logic**: Exponential backoff for failed requests
- **Timeout Protection**: Configurable request timeouts
- **Error Handling**: Graceful fallback between providers

## 🔧 Advanced Configuration

### Multi-Provider Routing

The system supports intelligent routing between providers:

```php
// Automatic provider selection based on model
X-Provider: auto

// Force specific provider
X-Provider: lmarena
X-Provider: yupp2api
```

### Session Persistence

Enhanced session management with persistence:

```javascript
// Userscript automatically persists sessions
localStorage.setItem('lmarena_session_name', sessionData);

// Recovers sessions on page reload
const persistedSessions = localStorage.getItem('lmarena_session_name');
```

### Custom Model Mapping

Per-session model aliasing:

```json
{
  "domain": "lmarena.ai",
  "session_name": "custom-session",
  "models": {
    "gpt-4": "gpt-4-turbo-preview",
    "claude": "claude-3-opus"
  }
}
```

## 📁 Project Structure

```
lmarena-gateway/
├── php/                          # PHP API Gateway
│   ├── app/                      # Application classes
│   │   ├── Config.php           # Configuration management
│   │   ├── SessionStore.php     # Session storage
│   │   └── Yupp2ApiProvider.php # yupp2Api integration
│   ├── public/                   # Web root
│   │   └── index.php            # Main entry point
│   ├── storage/                  # Session storage
│   ├── scripts/                  # Utility scripts
│   └── composer.json            # PHP dependencies
├── flask_services/               # Flask auxiliary services
│   ├── app.py                   # Main Flask application
│   ├── requirements.txt         # Python dependencies
│   └── templates/               # Userscript templates
├── apisix/                       # Apache APISIX configuration
│   └── apisix.yaml              # APISIX routes and plugins
├── cpanel/                       # cPanel deployment
│   ├── deploy.sh                # Automated deployment
│   └── CPANEL_SETUP.md         # Manual setup guide
├── LMArenaBridge/               # Original LMArenaBridge
├── lmarena-proxy/               # Original proxy system
└── README.md                    # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: Check the [cpanel/CPANEL_SETUP.md](cpanel/CPANEL_SETUP.md) for detailed setup
- **Issues**: Report bugs and feature requests via GitHub Issues
- **Discussions**: Join community discussions for help and tips

## 🙏 Acknowledgments

- **Apache APISIX**: For the excellent API gateway platform
- **LMArenaBridge**: For the original bridge implementation
- **yupp2Api**: For the AI provider integration
- **Community**: For feedback and contributions

---

**Built with ❤️ for the LMArena community**
