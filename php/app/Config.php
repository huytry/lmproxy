<?php
// php/app/Config.php
// Central configuration for the PHP AI API gateway

namespace GatewayApp;

class Config
{
    // Base URL(s) for LMArenaBridge instances.
    // If not provided by a registered session mapping, this default is used.
    public static function defaultBridgeBaseUrl(): string
    {
        // You can override with an environment variable in cPanel UI
        return getenv('LMARENA_BRIDGE_BASE_URL') ?: 'http://127.0.0.1:5102';
    }

    // Optional API key for LMArenaBridge (Authorization: Bearer ...)
    public static function defaultBridgeApiKey(): ?string
    {
        $key = getenv('LMARENA_BRIDGE_API_KEY');
        return $key !== false && $key !== '' ? $key : null;
    }

    // Storage path for session mappings
    public static function storageFile(): string
    {
        $base = __DIR__ . '/../../storage';
        if (!is_dir($base)) {
            @mkdir($base, 0775, true);
        }
        return $base . '/sessions.json';
    }

    // Allowed LMArena domains
    public static function allowedDomains(): array
    {
        return [
            'lmarena.ai',
            'canary.lmarena.ai',
            'alpha.lmarena.ai',
            'beta.lmarena.ai',
        ];
    }

    // LMArenaBridge integration configuration
    public static function lmarenaBridgeConfig(): array
    {
        return [
            'enabled' => getenv('LMARENA_BRIDGE_ENABLED') !== 'false', // enabled by default
            'websocket_url' => getenv('LMARENA_BRIDGE_WS_URL') ?: 'ws://127.0.0.1:5102/ws',
            'api_base_url' => getenv('LMARENA_BRIDGE_BASE_URL') ?: 'http://127.0.0.1:5102',
            'api_key' => getenv('LMARENA_BRIDGE_API_KEY') ?: null,
            'timeout' => (int)(getenv('LMARENA_BRIDGE_TIMEOUT') ?: 180),
            'models_file' => getenv('LMARENA_BRIDGE_MODELS_FILE') ?: '../LMArenaBridge/models.json',
            'config_file' => getenv('LMARENA_BRIDGE_CONFIG_FILE') ?: '../LMArenaBridge/config.jsonc',
            'model_endpoint_map_file' => getenv('LMARENA_BRIDGE_MODEL_MAP_FILE') ?: '../LMArenaBridge/model_endpoint_map.json',
        ];
    }

    // Flask auxiliary services configuration
    public static function flaskConfig(): array
    {
        return [
            'enabled' => getenv('FLASK_SERVICES_ENABLED') === 'true',
            'base_url' => getenv('FLASK_SERVICES_BASE_URL') ?: 'http://127.0.0.1:5104',
            'api_key' => getenv('FLASK_SERVICES_API_KEY') ?: null,
        ];
    }

    // Enhanced session management configuration
    public static function sessionConfig(): array
    {
        return [
            'max_sessions_per_domain' => (int)(getenv('GATEWAY_MAX_SESSIONS_PER_DOMAIN') ?: 100),
            'session_cleanup_days' => (int)(getenv('GATEWAY_SESSION_CLEANUP_DAYS') ?: 30),
            'enable_session_analytics' => getenv('GATEWAY_ENABLE_SESSION_ANALYTICS') === 'true',
            'concurrent_sessions_limit' => (int)(getenv('GATEWAY_CONCURRENT_SESSIONS_LIMIT') ?: 10),
        ];
    }
}

