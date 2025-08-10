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
}

