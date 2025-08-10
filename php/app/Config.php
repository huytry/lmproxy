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

    // yupp2Api provider configuration
    public static function yupp2ApiConfig(): array
    {
        return [
            'enabled' => getenv('YUPP2_API_ENABLED') === 'true',
            'base_url' => getenv('YUPP2_API_BASE_URL') ?: 'http://127.0.0.1:5103',
            'api_key' => getenv('YUPP2_API_KEY') ?: null,
            'timeout' => (int)(getenv('YUPP2_API_TIMEOUT') ?: 30),
            'retry_attempts' => (int)(getenv('YUPP2_API_RETRY_ATTEMPTS') ?: 3),
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

