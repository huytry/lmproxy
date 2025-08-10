#!/usr/bin/env python3
# flask_services/app.py
# Flask auxiliary services for PHP AI API gateway

import os
import json
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string, Response
from flask_cors import CORS
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Configuration
class Config:
    PHP_GATEWAY_URL = os.getenv('PHP_GATEWAY_URL', 'http://127.0.0.1:8080')
    FLASK_API_KEY = os.getenv('FLASK_SERVICES_API_KEY')
    SESSION_STORAGE_PATH = os.getenv('SESSION_STORAGE_PATH', '../php/storage/sessions.json')
    ANALYTICS_STORAGE_PATH = os.getenv('ANALYTICS_STORAGE_PATH', './analytics/session_analytics.json')
    USERSCRIPT_TEMPLATE_PATH = os.getenv('USERSCRIPT_TEMPLATE_PATH', './templates/userscript_template.js')
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(ANALYTICS_STORAGE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(USERSCRIPT_TEMPLATE_PATH), exist_ok=True)

def require_api_key(f):
    """Decorator to require API key authentication"""
    def decorated_function(*args, **kwargs):
        if Config.FLASK_API_KEY:
            auth_header = request.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                return jsonify({'error': 'API key required'}), 401
            
            provided_key = auth_header.split(' ')[1]
            if provided_key != Config.FLASK_API_KEY:
                return jsonify({'error': 'Invalid API key'}), 401
        
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def load_session_data() -> Dict:
    """Load session data from PHP storage"""
    try:
        if os.path.exists(Config.SESSION_STORAGE_PATH):
            with open(Config.SESSION_STORAGE_PATH, 'r') as f:
                return json.load(f)
        return {'domains': {}}
    except Exception as e:
        logger.error(f"Failed to load session data: {e}")
        return {'domains': {}}

def save_analytics_data(data: Dict):
    """Save analytics data"""
    try:
        analytics_data = {}
        if os.path.exists(Config.ANALYTICS_STORAGE_PATH):
            with open(Config.ANALYTICS_STORAGE_PATH, 'r') as f:
                analytics_data = json.load(f)
        
        # Merge new data
        for key, value in data.items():
            analytics_data[key] = value
        
        with open(Config.ANALYTICS_STORAGE_PATH, 'w') as f:
            json.dump(analytics_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save analytics data: {e}")

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'flask-auxiliary-services',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    })

@app.route('/analytics/sessions')
@require_api_key
def session_analytics():
    """Get session analytics"""
    try:
        session_data = load_session_data()
        domains = session_data.get('domains', {})
        
        analytics = {
            'total_domains': len(domains),
            'total_sessions': sum(len(sessions) for sessions in domains.values()),
            'domains_breakdown': {},
            'recent_activity': [],
            'generated_at': datetime.utcnow().isoformat()
        }
        
        # Domain breakdown
        for domain, sessions in domains.items():
            analytics['domains_breakdown'][domain] = {
                'session_count': len(sessions),
                'sessions': {}
            }
            
            for session_name, session_info in sessions.items():
                created_at = session_info.get('created_at')
                updated_at = session_info.get('updated_at')
                
                analytics['domains_breakdown'][domain]['sessions'][session_name] = {
                    'created_at': created_at,
                    'updated_at': updated_at,
                    'has_bridge_config': bool(session_info.get('bridge_base_url')),
                    'has_custom_models': bool(session_info.get('models'))
                }
                
                # Add to recent activity
                if updated_at:
                    analytics['recent_activity'].append({
                        'domain': domain,
                        'session_name': session_name,
                        'updated_at': updated_at,
                        'action': 'session_update'
                    })
        
        # Sort recent activity by timestamp
        analytics['recent_activity'].sort(
            key=lambda x: x['updated_at'], 
            reverse=True
        )
        analytics['recent_activity'] = analytics['recent_activity'][:50]  # Last 50 activities
        
        return jsonify(analytics)
        
    except Exception as e:
        logger.error(f"Failed to generate session analytics: {e}")
        return jsonify({'error': 'Failed to generate analytics'}), 500

@app.route('/userscript/advanced-generate')
@require_api_key
def advanced_userscript_generator():
    """Advanced userscript generator with enhanced features"""
    try:
        session_name = request.args.get('session_name', 'default')
        domain_filter = request.args.get('domain_filter', 'all')  # all, lmarena.ai, canary.lmarena.ai, etc.
        enable_analytics = request.args.get('enable_analytics', 'true').lower() == 'true'
        auto_retry = request.args.get('auto_retry', 'true').lower() == 'true'
        debug_mode = request.args.get('debug_mode', 'false').lower() == 'true'
        
        # Validate session name
        if not session_name or not session_name.replace('-', '').replace('_', '').isalnum():
            return jsonify({'error': 'Invalid session name format'}), 400
        
        # Get gateway URL from request or config
        gateway_url = request.args.get('gateway_url', Config.PHP_GATEWAY_URL)
        
        # Generate enhanced userscript
        userscript = generate_enhanced_userscript(
            session_name=session_name,
            gateway_url=gateway_url,
            domain_filter=domain_filter,
            enable_analytics=enable_analytics,
            auto_retry=auto_retry,
            debug_mode=debug_mode
        )
        
        response = Response(userscript, mimetype='text/javascript')
        response.headers['Content-Disposition'] = f'attachment; filename="lmarena-enhanced-{session_name}.user.js"'
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to generate enhanced userscript: {e}")
        return jsonify({'error': 'Failed to generate userscript'}), 500

def generate_enhanced_userscript(session_name: str, gateway_url: str, domain_filter: str, 
                               enable_analytics: bool, auto_retry: bool, debug_mode: bool) -> str:
    """Generate enhanced Tampermonkey userscript"""
    
    # Domain matching logic
    if domain_filter == 'all':
        match_patterns = [
            "https://lmarena.ai/*",
            "https://*.lmarena.ai/*"
        ]
        allowed_domains = ['lmarena.ai', 'canary.lmarena.ai', 'alpha.lmarena.ai', 'beta.lmarena.ai']
    else:
        match_patterns = [f"https://{domain_filter}/*"]
        allowed_domains = [domain_filter]
    
    match_lines = '\n'.join(f'// @match        {pattern}' for pattern in match_patterns)
    allowed_domains_js = json.dumps(allowed_domains)
    
    userscript_template = f"""// ==UserScript==
// @name         LMArena Enhanced Session Registrar ({session_name})
// @namespace    https://lmarena-gateway.local/
// @version      2.0.0
// @description  Enhanced LMArena session registrar with analytics, auto-retry, and advanced error handling
// @author       LMArena Gateway Enhanced
{match_lines}
// @icon         https://www.google.com/s2/favicons?sz=64&domain=lmarena.ai
// @grant        none
// @run-at       document-start
// @updateURL    {gateway_url}/userscript/advanced-generate?session_name={session_name}&domain_filter={domain_filter}&enable_analytics={str(enable_analytics).lower()}&auto_retry={str(auto_retry).lower()}&debug_mode={str(debug_mode).lower()}
// @downloadURL  {gateway_url}/userscript/advanced-generate?session_name={session_name}&domain_filter={domain_filter}&enable_analytics={str(enable_analytics).lower()}&auto_retry={str(auto_retry).lower()}&debug_mode={str(debug_mode).lower()}
// ==/UserScript==

(function() {{
    'use strict';
    
    // Configuration
    const CONFIG = {{
        SESSION_NAME: {json.dumps(session_name)},
        GATEWAY_URL: {json.dumps(gateway_url)},
        ALLOWED_DOMAINS: {allowed_domains_js},
        ENABLE_ANALYTICS: {str(enable_analytics).lower()},
        AUTO_RETRY: {str(auto_retry).lower()},
        DEBUG_MODE: {str(debug_mode).lower()},
        MAX_RETRY_ATTEMPTS: 3,
        RETRY_DELAY_MS: 2000,
        HEARTBEAT_INTERVAL_MS: 30000
    }};
    
    // State management
    let state = {{
        isRegistering: false,
        lastRegistration: null,
        retryCount: 0,
        sessionPersistence: {{}},
        analytics: {{
            registrations: 0,
            errors: 0,
            lastActivity: null
        }}
    }};
    
    // Utility functions
    function log(level, message, ...args) {{
        const timestamp = new Date().toISOString();
        const prefix = `[LMArena Enhanced ${{CONFIG.SESSION_NAME}}]`;
        
        if (CONFIG.DEBUG_MODE || level !== 'debug') {{
            console[level](`${{prefix}} [${{timestamp}}]`, message, ...args);
        }}
        
        // Send to analytics if enabled
        if (CONFIG.ENABLE_ANALYTICS && level === 'error') {{
            state.analytics.errors++;
            sendAnalytics('error', {{ message, args }});
        }}
    }}
    
    function getDomain() {{
        const hostname = location.hostname.toLowerCase();
        for (const domain of CONFIG.ALLOWED_DOMAINS) {{
            if (hostname === domain || hostname.endsWith('.' + domain)) {{
                return domain;
            }}
        }}
        return CONFIG.ALLOWED_DOMAINS[0]; // fallback
    }}
    
    function generateSessionId() {{
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {{
            const r = Math.random() * 16 | 0;
            const v = c == 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        }});
    }}
    
    async function sendAnalytics(event, data) {{
        if (!CONFIG.ENABLE_ANALYTICS) return;
        
        try {{
            await fetch(`${{CONFIG.GATEWAY_URL}}/analytics/event`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    session_name: CONFIG.SESSION_NAME,
                    domain: getDomain(),
                    event,
                    data,
                    timestamp: new Date().toISOString(),
                    user_agent: navigator.userAgent
                }})
            }});
        }} catch (e) {{
            log('debug', 'Analytics send failed:', e);
        }}
    }}
    
    async function registerSession(sessionId, messageId, attempt = 1) {{
        if (state.isRegistering) {{
            log('debug', 'Registration already in progress, skipping');
            return;
        }}
        
        state.isRegistering = true;
        const domain = getDomain();
        
        try {{
            log('info', `Registering session (attempt ${{attempt}}/${{CONFIG.MAX_RETRY_ATTEMPTS}}):`, {{
                domain,
                sessionName: CONFIG.SESSION_NAME,
                sessionId: sessionId.substring(0, 8) + '...',
                messageId: messageId.substring(0, 8) + '...'
            }});
            
            const response = await fetch(`${{CONFIG.GATEWAY_URL}}/session/register`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    domain,
                    session_name: CONFIG.SESSION_NAME,
                    session_id: sessionId,
                    message_id: messageId
                }})
            }});
            
            if (!response.ok) {{
                throw new Error(`HTTP ${{response.status}}: ${{await response.text()}}`);
            }}
            
            const result = await response.json();
            log('info', 'Session registered successfully:', result);
            
            // Update state
            state.lastRegistration = {{
                domain,
                sessionId,
                messageId,
                timestamp: new Date().toISOString()
            }};
            state.retryCount = 0;
            state.analytics.registrations++;
            state.analytics.lastActivity = new Date().toISOString();
            
            // Persist session info
            state.sessionPersistence[domain] = {{
                sessionId,
                messageId,
                registeredAt: new Date().toISOString()
            }};
            
            // Save to localStorage
            localStorage.setItem(`lmarena_session_${{CONFIG.SESSION_NAME}}`, JSON.stringify(state.sessionPersistence));
            
            if (CONFIG.ENABLE_ANALYTICS) {{
                sendAnalytics('registration_success', {{ domain, sessionId, messageId }});
            }}
            
        }} catch (error) {{
            log('error', `Registration failed (attempt ${{attempt}}):`, error);
            
            if (CONFIG.AUTO_RETRY && attempt < CONFIG.MAX_RETRY_ATTEMPTS) {{
                state.retryCount++;
                setTimeout(() => {{
                    registerSession(sessionId, messageId, attempt + 1);
                }}, CONFIG.RETRY_DELAY_MS * attempt);
            }} else {{
                log('error', 'Max retry attempts reached, giving up');
                if (CONFIG.ENABLE_ANALYTICS) {{
                    sendAnalytics('registration_failed', {{ error: error.message, attempts: attempt }});
                }}
            }}
        }} finally {{
            state.isRegistering = false;
        }}
    }}
    
    // Session persistence recovery
    function recoverPersistedSessions() {{
        try {{
            const persisted = localStorage.getItem(`lmarena_session_${{CONFIG.SESSION_NAME}}`);
            if (persisted) {{
                state.sessionPersistence = JSON.parse(persisted);
                log('info', 'Recovered persisted sessions:', Object.keys(state.sessionPersistence));
            }}
        }} catch (e) {{
            log('debug', 'Failed to recover persisted sessions:', e);
        }}
    }}
    
    // Heartbeat to maintain session
    function startHeartbeat() {{
        setInterval(async () => {{
            if (state.lastRegistration) {{
                try {{
                    await fetch(`${{CONFIG.GATEWAY_URL}}/session/heartbeat`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            domain: getDomain(),
                            session_name: CONFIG.SESSION_NAME,
                            timestamp: new Date().toISOString()
                        }})
                    }});
                    log('debug', 'Heartbeat sent');
                }} catch (e) {{
                    log('debug', 'Heartbeat failed:', e);
                }}
            }}
        }}, CONFIG.HEARTBEAT_INTERVAL_MS);
    }}
    
    // Initialize
    log('info', 'Enhanced session registrar initialized', CONFIG);
    recoverPersistedSessions();
    startHeartbeat();
    
    if (CONFIG.ENABLE_ANALYTICS) {{
        sendAnalytics('script_loaded', {{ domain: getDomain() }});
    }}
    
    // Intercept fetch requests to capture session IDs
    const originalFetch = window.fetch;
    window.fetch = function(...args) {{
        const [url, options] = args;
        
        if (typeof url === 'string' && url.includes('/api/v1/chat/completions')) {{
            const urlObj = new URL(url, location.origin);
            const sessionMatch = urlObj.pathname.match(/\\/([a-f0-9-]{{36}})\\/([a-f0-9-]{{36}})$/);
            
            if (sessionMatch) {{
                const [, sessionId, messageId] = sessionMatch;
                log('debug', 'Captured session IDs from fetch:', {{ sessionId: sessionId.substring(0, 8) + '...', messageId: messageId.substring(0, 8) + '...' }});
                
                // Register session asynchronously
                setTimeout(() => registerSession(sessionId, messageId), 100);
            }}
        }}
        
        return originalFetch.apply(this, args);
    }};
    
    log('info', 'Fetch interceptor installed, monitoring for session IDs...');
    
}})();"""
    
    return userscript_template

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5104))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    
    logger.info(f"Starting Flask auxiliary services on port {port}")
    logger.info(f"PHP Gateway URL: {Config.PHP_GATEWAY_URL}")
    logger.info(f"Session storage: {Config.SESSION_STORAGE_PATH}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
