<?php
// php/app/ClientConfigGenerator.php
// Generate configuration files and scripts for client-side LMArenaBridge instances

namespace GatewayApp;

class ClientConfigGenerator
{
    private string $platformUrl;
    private string $templatesPath;

    public function __construct(string $platformUrl = null, string $templatesPath = '../templates')
    {
        $this->platformUrl = $platformUrl ?: $this->detectPlatformUrl();
        $this->templatesPath = $templatesPath;
        
        // Ensure templates directory exists
        if (!is_dir($this->templatesPath)) {
            mkdir($this->templatesPath, 0775, true);
        }
    }

    /**
     * Generate complete client package
     */
    public function generateClientPackage(array $clientConfig): array
    {
        $clientId = $clientConfig['client_id'];
        $apiKey = $clientConfig['api_key'];
        
        return [
            'client_id' => $clientId,
            'api_key' => $apiKey,
            'platform_url' => $this->platformUrl,
            'files' => [
                'config.jsonc' => $this->generateConfigFile($clientConfig),
                'platform_integration.py' => $this->generatePlatformIntegration($clientConfig),
                'setup_instructions.md' => $this->generateSetupInstructions($clientConfig),
                'docker-compose.yml' => $this->generateDockerCompose($clientConfig),
                'start_client.sh' => $this->generateStartScript($clientConfig),
                'requirements_platform.txt' => $this->generatePlatformRequirements()
            ],
            'userscript' => $this->generateEnhancedUserscript($clientConfig)
        ];
    }

    /**
     * Generate LMArenaBridge config.jsonc with platform integration
     */
    private function generateConfigFile(array $clientConfig): string
    {
        $config = [
            'version' => '2.0.0',
            'session_id' => 'YOUR_SESSION_ID_HERE',
            'message_id' => 'YOUR_MESSAGE_ID_HERE',
            'id_updater_last_mode' => 'direct_chat',
            'id_updater_battle_target' => 'A',
            'api_key' => null,
            'tavern_mode_enabled' => false,
            'bypass_enabled' => false,
            'enable_auto_update' => true,
            'enable_idle_restart' => false,
            'idle_restart_timeout_seconds' => 300,
            'stream_response_timeout_seconds' => 360,
            'use_default_ids_if_mapping_not_found' => true,
            
            // Platform integration settings
            'platform_integration' => [
                'enabled' => true,
                'platform_url' => $this->platformUrl,
                'client_id' => $clientConfig['client_id'],
                'api_key' => $clientConfig['api_key'],
                'heartbeat_interval_seconds' => 30,
                'request_timeout_seconds' => 300,
                'retry_attempts' => 3,
                'health_check_endpoint' => '/health',
                'registration_endpoint' => '/clients/register',
                'capabilities' => ['chat', 'models', 'images']
            ]
        ];

        return $this->arrayToJsonc($config, 'LMArenaBridge Configuration with Platform Integration');
    }

    /**
     * Generate platform integration Python module
     */
    private function generatePlatformIntegration(array $clientConfig): string
    {
        return <<<PYTHON
# platform_integration.py
# Platform integration module for LMArenaBridge client

import asyncio
import aiohttp
import json
import logging
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class PlatformIntegration:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('platform_integration', {})
        self.platform_url = self.config.get('platform_url')
        self.client_id = self.config.get('client_id')
        self.api_key = self.config.get('api_key')
        self.heartbeat_interval = self.config.get('heartbeat_interval_seconds', 30)
        self.session = None
        self.heartbeat_task = None
        
    async def initialize(self):
        """Initialize platform integration"""
        if not self.config.get('enabled', False):
            logger.info("Platform integration disabled")
            return
            
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.get('request_timeout_seconds', 300)),
            headers={
                'User-Agent': 'LMArenaBridge-Client/1.0',
                'X-Client-ID': self.client_id,
                'Authorization': f'Bearer {self.api_key}'
            }
        )
        
        # Start heartbeat
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Platform integration initialized for client {self.client_id}")
        
    async def shutdown(self):
        """Shutdown platform integration"""
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            
        if self.session:
            await self.session.close()
            
        logger.info("Platform integration shutdown complete")
        
    async def register_with_platform(self):
        """Register this client with the platform"""
        if not self.session:
            return False
            
        try:
            registration_data = {
                'client_id': self.client_id,
                'status': 'active',
                'capabilities': self.config.get('capabilities', ['chat', 'models']),
                'lmarena_bridge_url': 'http://127.0.0.1:5102',
                'metadata': {
                    'version': '2.0.0',
                    'started_at': time.time()
                }
            }
            
            async with self.session.post(
                f"{self.platform_url}/clients/{self.client_id}/status",
                json=registration_data
            ) as response:
                if response.status == 200:
                    logger.info("Successfully registered with platform")
                    return True
                else:
                    logger.error(f"Platform registration failed: {response.status}")
                    return False
                    
        except Exception as e:
            logger.error(f"Platform registration error: {e}")
            return False
            
    async def _heartbeat_loop(self):
        """Send periodic heartbeats to platform"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                
    async def _send_heartbeat(self):
        """Send heartbeat to platform"""
        if not self.session:
            return
            
        try:
            heartbeat_data = {
                'client_id': self.client_id,
                'timestamp': time.time(),
                'status': 'active'
            }
            
            async with self.session.post(
                f"{self.platform_url}/clients/{self.client_id}/heartbeat",
                json=heartbeat_data
            ) as response:
                if response.status != 200:
                    logger.warning(f"Heartbeat failed: {response.status}")
                    
        except Exception as e:
            logger.debug(f"Heartbeat send error: {e}")

# Global platform integration instance
platform_integration = None

async def initialize_platform_integration(config):
    """Initialize global platform integration"""
    global platform_integration
    platform_integration = PlatformIntegration(config)
    await platform_integration.initialize()
    await platform_integration.register_with_platform()

async def shutdown_platform_integration():
    """Shutdown global platform integration"""
    global platform_integration
    if platform_integration:
        await platform_integration.shutdown()
PYTHON;
    }

    /**
     * Generate setup instructions
     */
    private function generateSetupInstructions(array $clientConfig): string
    {
        $clientId = $clientConfig['client_id'];
        $apiKey = $clientConfig['api_key'];
        
        return <<<MARKDOWN
# LMArenaBridge Client Setup Instructions

## Overview
This package configures your local LMArenaBridge instance to work with our centralized platform at `{$this->platformUrl}`.

## Prerequisites
- Python 3.8 or higher
- LMArenaBridge repository cloned locally
- Chrome/Firefox with Tampermonkey extension

## Setup Steps

### 1. Install LMArenaBridge
```bash
git clone https://github.com/Lianues/LMArenaBridge.git
cd LMArenaBridge
pip install -r requirements.txt
```

### 2. Install Platform Integration
```bash
# Copy the platform integration files to your LMArenaBridge directory
cp platform_integration.py /path/to/LMArenaBridge/
cp requirements_platform.txt /path/to/LMArenaBridge/
pip install -r requirements_platform.txt
```

### 3. Configure LMArenaBridge
```bash
# Replace the existing config.jsonc with the provided one
cp config.jsonc /path/to/LMArenaBridge/config.jsonc
```

### 4. Set Up Session IDs
```bash
# Run the ID updater to capture your LMArena session IDs
cd /path/to/LMArenaBridge
python id_updater.py
```

### 5. Install Userscript
1. Open Tampermonkey in your browser
2. Create a new script
3. Copy and paste the provided userscript
4. Save and enable the script

### 6. Start the Client
```bash
# Use the provided start script
chmod +x start_client.sh
./start_client.sh

# Or start manually
python api_server.py
```

## Configuration Details

### Client Information
- **Client ID**: `{$clientId}`
- **API Key**: `{$apiKey}`
- **Platform URL**: `{$this->platformUrl}`

### Platform Integration
Your LMArenaBridge instance will:
- Register with our platform automatically
- Send heartbeats every 30 seconds
- Receive and process requests from our platform
- Report health status and statistics

### Verification
1. Check that your client appears in the platform dashboard
2. Test API requests through our platform
3. Monitor logs for any connection issues

## Troubleshooting

### Connection Issues
- Verify your internet connection
- Check firewall settings (port 5102 should be accessible)
- Ensure API key is correct

### Authentication Errors
- Verify client ID and API key match the registration
- Check that the platform URL is correct

### Session ID Issues
- Run `python id_updater.py` again to capture fresh session IDs
- Ensure you're logged into LMArena in your browser
- Check that the Tampermonkey script is active

## Support
For support, contact our platform administrators or check the documentation at `{$this->platformUrl}/docs`.
MARKDOWN;
    }

    /**
     * Generate Docker Compose configuration
     */
    private function generateDockerCompose(array $clientConfig): string
    {
        return <<<YAML
version: '3.8'

services:
  lmarena-bridge-client:
    build: .
    ports:
      - "5102:5102"
    environment:
      - PLATFORM_INTEGRATION_ENABLED=true
      - PLATFORM_URL={$this->platformUrl}
      - CLIENT_ID={$clientConfig['client_id']}
      - API_KEY={$clientConfig['api_key']}
    volumes:
      - ./config.jsonc:/app/config.jsonc
      - ./models.json:/app/models.json
      - ./model_endpoint_map.json:/app/model_endpoint_map.json
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5102/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  # Optional: Add monitoring
  # prometheus:
  #   image: prom/prometheus
  #   ports:
  #     - "9090:9090"
  #   volumes:
  #     - ./prometheus.yml:/etc/prometheus/prometheus.yml
YAML;
    }

    /**
     * Generate start script
     */
    private function generateStartScript(array $clientConfig): string
    {
        return <<<BASH
#!/bin/bash
# start_client.sh - Start LMArenaBridge client with platform integration

set -e

echo "Starting LMArenaBridge Client..."
echo "Client ID: {$clientConfig['client_id']}"
echo "Platform URL: {$this->platformUrl}"

# Check if config exists
if [ ! -f "config.jsonc" ]; then
    echo "Error: config.jsonc not found. Please copy the provided configuration file."
    exit 1
fi

# Check if session IDs are configured
if grep -q "YOUR_SESSION_ID_HERE" config.jsonc; then
    echo "Warning: Session IDs not configured. Run 'python id_updater.py' first."
    echo "Continuing anyway..."
fi

# Install platform integration requirements
if [ -f "requirements_platform.txt" ]; then
    echo "Installing platform integration requirements..."
    pip install -r requirements_platform.txt
fi

# Start the server
echo "Starting LMArenaBridge server..."
python api_server.py

echo "LMArenaBridge client started successfully!"
BASH;
    }

    /**
     * Generate platform requirements
     */
    private function generatePlatformRequirements(): string
    {
        return <<<TXT
# Platform integration requirements
aiohttp>=3.8.0
asyncio-mqtt>=0.11.0
TXT;
    }

    /**
     * Generate enhanced userscript with platform integration
     */
    private function generateEnhancedUserscript(array $clientConfig): string
    {
        $clientId = $clientConfig['client_id'];
        $platformUrl = $this->platformUrl;
        
        return <<<JAVASCRIPT
// ==UserScript==
// @name         LMArena Platform Bridge Client ({$clientId})
// @namespace    {$platformUrl}
// @version      2.0.0
// @description  Enhanced LMArena bridge with platform integration
// @author       LMArena Gateway Platform
// @match        https://lmarena.ai/*
// @match        https://*.lmarena.ai/*
// @icon         https://www.google.com/s2/favicons?sz=64&domain=lmarena.ai
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';
    
    // Configuration
    const CONFIG = {
        CLIENT_ID: '{$clientId}',
        PLATFORM_URL: '{$platformUrl}',
        LMARENA_BRIDGE_URL: 'ws://127.0.0.1:5102/ws',
        HEARTBEAT_INTERVAL: 30000,
        RECONNECT_DELAY: 5000,
        MAX_RECONNECT_ATTEMPTS: 10
    };
    
    // State management
    let websocket = null;
    let reconnectAttempts = 0;
    let heartbeatInterval = null;
    let isConnected = false;
    
    // Logging
    function log(level, message, ...args) {
        const timestamp = new Date().toISOString();
        const prefix = `[LMArena Bridge Client {$clientId}]`;
        console[level](`\${prefix} [\${timestamp}]`, message, ...args);
    }
    
    // WebSocket connection management
    function connectWebSocket() {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            return;
        }
        
        log('info', 'Connecting to LMArenaBridge...');
        
        try {
            websocket = new WebSocket(CONFIG.LMARENA_BRIDGE_URL);
            
            websocket.onopen = function(event) {
                log('info', 'Connected to LMArenaBridge');
                isConnected = true;
                reconnectAttempts = 0;
                startHeartbeat();
                
                // Notify platform of connection
                notifyPlatform('connected');
            };
            
            websocket.onmessage = function(event) {
                try {
                    const message = JSON.parse(event.data);
                    handleBridgeMessage(message);
                } catch (e) {
                    log('error', 'Failed to parse WebSocket message:', e);
                }
            };
            
            websocket.onclose = function(event) {
                log('warn', 'WebSocket connection closed:', event.code, event.reason);
                isConnected = false;
                stopHeartbeat();
                
                // Attempt reconnection
                if (reconnectAttempts < CONFIG.MAX_RECONNECT_ATTEMPTS) {
                    reconnectAttempts++;
                    log('info', `Reconnecting in \${CONFIG.RECONNECT_DELAY}ms (attempt \${reconnectAttempts})`);
                    setTimeout(connectWebSocket, CONFIG.RECONNECT_DELAY);
                } else {
                    log('error', 'Max reconnection attempts reached');
                    notifyPlatform('disconnected');
                }
            };
            
            websocket.onerror = function(error) {
                log('error', 'WebSocket error:', error);
            };
            
        } catch (e) {
            log('error', 'Failed to create WebSocket connection:', e);
        }
    }
    
    // Handle messages from LMArenaBridge
    function handleBridgeMessage(message) {
        if (message.command) {
            handleCommand(message.command, message.data);
        } else if (message.request_id && message.payload) {
            handleRequest(message.request_id, message.payload);
        }
    }
    
    // Handle commands from bridge
    function handleCommand(command, data) {
        log('debug', 'Received command:', command, data);
        
        switch (command) {
            case 'refresh':
                location.reload();
                break;
            case 'reconnect':
                connectWebSocket();
                break;
            case 'ping':
                sendToBridge({ command: 'pong', timestamp: Date.now() });
                break;
        }
    }
    
    // Handle API requests from bridge
    async function handleRequest(requestId, payload) {
        log('debug', 'Processing request:', requestId, payload);
        
        try {
            // Make request to LMArena API
            const response = await makeLMArenaRequest(payload);
            
            // Stream response back to bridge
            if (response.body && response.body.getReader) {
                streamResponseToBridge(requestId, response);
            } else {
                sendToBridge({ request_id: requestId, data: response });
            }
            
        } catch (error) {
            log('error', 'Request processing failed:', error);
            sendToBridge({ 
                request_id: requestId, 
                error: error.message || 'Request processing failed' 
            });
        }
    }
    
    // Make request to LMArena API
    async function makeLMArenaRequest(payload) {
        const url = `/api/stream/retry-evaluation-session-message/\${payload.session_id}/messages/\${payload.message_id}`;
        
        const requestBody = {
            messages: payload.message_templates || [],
            modelId: payload.target_model_id
        };
        
        return fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify(requestBody)
        });
    }
    
    // Stream response to bridge
    async function streamResponseToBridge(requestId, response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        try {
            while (true) {
                const { done, value } = await reader.read();
                
                if (done) {
                    sendToBridge({ request_id: requestId, data: '[DONE]' });
                    break;
                }
                
                const chunk = decoder.decode(value, { stream: true });
                sendToBridge({ request_id: requestId, data: chunk });
            }
        } catch (error) {
            log('error', 'Streaming error:', error);
            sendToBridge({ 
                request_id: requestId, 
                error: 'Streaming failed: ' + error.message 
            });
        }
    }
    
    // Send message to bridge
    function sendToBridge(message) {
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify(message));
        } else {
            log('warn', 'Cannot send message - WebSocket not connected');
        }
    }
    
    // Heartbeat management
    function startHeartbeat() {
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
        }
        
        heartbeatInterval = setInterval(() => {
            if (isConnected) {
                sendToBridge({ 
                    command: 'heartbeat', 
                    client_id: CONFIG.CLIENT_ID,
                    timestamp: Date.now() 
                });
            }
        }, CONFIG.HEARTBEAT_INTERVAL);
    }
    
    function stopHeartbeat() {
        if (heartbeatInterval) {
            clearInterval(heartbeatInterval);
            heartbeatInterval = null;
        }
    }
    
    // Platform notification
    async function notifyPlatform(status) {
        try {
            await fetch(`\${CONFIG.PLATFORM_URL}/clients/\${CONFIG.CLIENT_ID}/browser-status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    status: status,
                    timestamp: Date.now(),
                    url: location.href
                })
            });
        } catch (e) {
            log('debug', 'Platform notification failed:', e);
        }
    }
    
    // Initialize
    log('info', 'LMArena Platform Bridge Client initializing...');
    
    // Wait for page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connectWebSocket);
    } else {
        connectWebSocket();
    }
    
    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        stopHeartbeat();
        if (websocket) {
            websocket.close();
        }
        notifyPlatform('disconnected');
    });
    
})();
JAVASCRIPT;
    }

    /**
     * Convert array to JSONC format with comments
     */
    private function arrayToJsonc(array $data, string $title = ''): string
    {
        $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        
        $header = $title ? "// $title\n// Generated on " . gmdate('Y-m-d H:i:s T') . "\n" : '';
        
        return $header . $json;
    }

    /**
     * Detect platform URL from current request
     */
    private function detectPlatformUrl(): string
    {
        $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
        $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || 
                   (!empty($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
        $protocol = $isHttps ? 'https' : 'http';
        
        return "{$protocol}://{$host}/api";
    }
}
JAVASCRIPT;
    }
}
