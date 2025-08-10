# lmarena_platform_integration.py
# Platform integration module for client-side LMArenaBridge instances
# This module should be added to the client's LMArenaBridge installation

import asyncio
import aiohttp
import json
import logging
import time
import threading
from typing import Optional, Dict, Any, Callable
from datetime import datetime

logger = logging.getLogger(__name__)

class PlatformIntegration:
    """
    Handles communication between client LMArenaBridge and the centralized platform
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get('platform_integration', {})
        self.enabled = self.config.get('enabled', False)
        self.platform_url = self.config.get('platform_url')
        self.client_id = self.config.get('client_id')
        self.api_key = self.config.get('api_key')
        self.heartbeat_interval = self.config.get('heartbeat_interval_seconds', 30)
        
        # Connection state
        self.session = None
        self.heartbeat_task = None
        self.is_connected = False
        self.last_heartbeat = None
        
        # Request handling
        self.request_handlers = {}
        self.active_requests = {}
        
        # Statistics
        self.stats = {
            'requests_processed': 0,
            'requests_successful': 0,
            'requests_failed': 0,
            'last_request_time': None,
            'uptime_start': time.time()
        }

    async def initialize(self):
        """Initialize platform integration"""
        if not self.enabled:
            logger.info("Platform integration disabled")
            return False
            
        if not all([self.platform_url, self.client_id, self.api_key]):
            logger.error("Platform integration configuration incomplete")
            return False
            
        try:
            # Create HTTP session
            timeout = aiohttp.ClientTimeout(total=self.config.get('request_timeout_seconds', 300))
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    'User-Agent': 'LMArenaBridge-Client/2.0',
                    'X-Client-ID': self.client_id,
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                }
            )
            
            # Register with platform
            if await self.register_with_platform():
                # Start heartbeat
                self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                self.is_connected = True
                logger.info(f"Platform integration initialized for client {self.client_id}")
                return True
            else:
                logger.error("Failed to register with platform")
                return False
                
        except Exception as e:
            logger.error(f"Platform integration initialization failed: {e}")
            return False

    async def shutdown(self):
        """Shutdown platform integration"""
        logger.info("Shutting down platform integration...")
        
        # Cancel heartbeat
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Notify platform of shutdown
        if self.session and self.is_connected:
            try:
                await self.update_status('offline')
            except Exception as e:
                logger.debug(f"Failed to notify platform of shutdown: {e}")
        
        # Close session
        if self.session:
            await self.session.close()
            
        self.is_connected = False
        logger.info("Platform integration shutdown complete")

    async def register_with_platform(self) -> bool:
        """Register this client with the platform"""
        try:
            registration_data = {
                'client_id': self.client_id,
                'status': 'active',
                'capabilities': self.config.get('capabilities', ['chat', 'models', 'images']),
                'lmarena_bridge_url': 'http://127.0.0.1:5102',
                'metadata': {
                    'version': '2.0.0',
                    'started_at': self.stats['uptime_start'],
                    'platform_integration_version': '1.0'
                }
            }
            
            async with self.session.put(
                f"{self.platform_url}/clients/{self.client_id}/status",
                json=registration_data
            ) as response:
                if response.status == 200:
                    logger.info("Successfully registered with platform")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Platform registration failed: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Platform registration error: {e}")
            return False

    async def update_status(self, status: str, metadata: Dict[str, Any] = None):
        """Update client status on platform"""
        if not self.session or not self.is_connected:
            return
            
        try:
            status_data = {
                'status': status,
                'timestamp': time.time(),
                'stats': self.get_stats(),
                'metadata': metadata or {}
            }
            
            async with self.session.post(
                f"{self.platform_url}/clients/{self.client_id}/status",
                json=status_data
            ) as response:
                if response.status != 200:
                    logger.warning(f"Status update failed: {response.status}")
                    
        except Exception as e:
            logger.debug(f"Status update error: {e}")

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
                'status': 'active',
                'stats': self.get_stats()
            }
            
            async with self.session.post(
                f"{self.platform_url}/clients/{self.client_id}/heartbeat",
                json=heartbeat_data
            ) as response:
                if response.status == 200:
                    self.last_heartbeat = time.time()
                else:
                    logger.warning(f"Heartbeat failed: {response.status}")
                    
        except Exception as e:
            logger.debug(f"Heartbeat send error: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get current client statistics"""
        uptime = time.time() - self.stats['uptime_start']
        
        return {
            'requests_processed': self.stats['requests_processed'],
            'requests_successful': self.stats['requests_successful'],
            'requests_failed': self.stats['requests_failed'],
            'success_rate': (
                self.stats['requests_successful'] / max(self.stats['requests_processed'], 1) * 100
            ),
            'uptime_seconds': uptime,
            'last_request_time': self.stats['last_request_time'],
            'last_heartbeat': self.last_heartbeat,
            'active_requests': len(self.active_requests)
        }

    def record_request(self, success: bool):
        """Record request statistics"""
        self.stats['requests_processed'] += 1
        self.stats['last_request_time'] = time.time()
        
        if success:
            self.stats['requests_successful'] += 1
        else:
            self.stats['requests_failed'] += 1

    async def handle_platform_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle incoming request from platform"""
        request_id = request_data.get('request_id')
        request_type = request_data.get('type', 'chat_completion')
        
        if not request_id:
            return {'error': 'Missing request_id'}
        
        try:
            self.active_requests[request_id] = {
                'start_time': time.time(),
                'type': request_type
            }
            
            # Route request based on type
            if request_type == 'chat_completion':
                result = await self._handle_chat_completion(request_data)
            elif request_type == 'models_list':
                result = await self._handle_models_list(request_data)
            elif request_type == 'image_generation':
                result = await self._handle_image_generation(request_data)
            else:
                result = {'error': f'Unsupported request type: {request_type}'}
            
            self.record_request(success='error' not in result)
            return result
            
        except Exception as e:
            logger.error(f"Request handling error: {e}")
            self.record_request(success=False)
            return {'error': f'Request processing failed: {str(e)}'}
        
        finally:
            if request_id in self.active_requests:
                del self.active_requests[request_id]

    async def _handle_chat_completion(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat completion request"""
        # This would integrate with the existing LMArenaBridge chat completion logic
        # For now, return a placeholder response
        return {
            'type': 'chat_completion',
            'status': 'processing',
            'message': 'Chat completion request received and being processed'
        }

    async def _handle_models_list(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle models list request"""
        # This would integrate with the existing LMArenaBridge models logic
        return {
            'type': 'models_list',
            'models': [],
            'message': 'Models list request processed'
        }

    async def _handle_image_generation(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle image generation request"""
        # This would integrate with the existing LMArenaBridge image generation logic
        return {
            'type': 'image_generation',
            'status': 'processing',
            'message': 'Image generation request received and being processed'
        }

    def is_healthy(self) -> bool:
        """Check if the integration is healthy"""
        if not self.enabled or not self.is_connected:
            return False
            
        # Check if heartbeat is recent
        if self.last_heartbeat:
            time_since_heartbeat = time.time() - self.last_heartbeat
            if time_since_heartbeat > (self.heartbeat_interval * 3):  # 3x heartbeat interval
                return False
        
        return True

    def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status"""
        return {
            'enabled': self.enabled,
            'connected': self.is_connected,
            'healthy': self.is_healthy(),
            'last_heartbeat': self.last_heartbeat,
            'uptime': time.time() - self.stats['uptime_start'],
            'platform_url': self.platform_url,
            'client_id': self.client_id,
            'stats': self.get_stats()
        }


# Global platform integration instance
platform_integration: Optional[PlatformIntegration] = None

async def initialize_platform_integration(config: Dict[str, Any]) -> bool:
    """Initialize global platform integration"""
    global platform_integration
    
    try:
        platform_integration = PlatformIntegration(config)
        success = await platform_integration.initialize()
        
        if success:
            logger.info("Platform integration initialized successfully")
        else:
            logger.warning("Platform integration initialization failed")
            
        return success
        
    except Exception as e:
        logger.error(f"Failed to initialize platform integration: {e}")
        return False

async def shutdown_platform_integration():
    """Shutdown global platform integration"""
    global platform_integration
    
    if platform_integration:
        await platform_integration.shutdown()
        platform_integration = None

def get_platform_integration() -> Optional[PlatformIntegration]:
    """Get the global platform integration instance"""
    return platform_integration

def is_platform_integration_enabled() -> bool:
    """Check if platform integration is enabled and healthy"""
    return platform_integration is not None and platform_integration.is_healthy()

# Health check endpoint handler
async def handle_health_check() -> Dict[str, Any]:
    """Handle health check requests"""
    if platform_integration:
        return platform_integration.get_health_status()
    else:
        return {
            'enabled': False,
            'connected': False,
            'healthy': False,
            'message': 'Platform integration not initialized'
        }
