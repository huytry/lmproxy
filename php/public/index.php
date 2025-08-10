<?php
// php/public/index.php
// Front controller for the PHP AI API gateway

use GatewayApp\Config;
use GatewayApp\SessionStore;
use GatewayApp\LMArenaBridgeProvider;
use GatewayApp\ClientManager;
use GatewayApp\RequestRouter;
use GatewayApp\ClientConfigGenerator;

require_once __DIR__ . '/../app/Config.php';
require_once __DIR__ . '/../app/SessionStore.php';
require_once __DIR__ . '/../app/LMArenaBridgeProvider.php';
require_once __DIR__ . '/../app/ClientManager.php';
require_once __DIR__ . '/../app/RequestRouter.php';
require_once __DIR__ . '/../app/ClientConfigGenerator.php';

// Error reporting for production
error_reporting(E_ERROR | E_WARNING | E_PARSE);
ini_set('display_errors', '0');
ini_set('log_errors', '1');

// Basic router
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);

// CORS for Tampermonkey and browser-origin calls
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization, X-Session-Name, X-Target-Domain');
if ($method === 'OPTIONS') {
    http_response_code(204);
    exit;
}

function jsonResponse($data, int $status = 200): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}

function errorResponse(string $message, int $status = 400, ?string $code = null): void {
    $response = ['error' => $message];
    if ($code) $response['code'] = $code;
    jsonResponse($response, $status);
}

function getJsonBody(): array {
    $raw = file_get_contents('php://input');
    if ($raw === '' || $raw === false) return [];
    $data = json_decode($raw, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        throw new InvalidArgumentException('Invalid JSON: ' . json_last_error_msg());
    }
    return is_array($data) ? $data : [];
}

function validateSessionName(string $name): bool {
    return preg_match('/^[a-zA-Z0-9_-]{1,64}$/', $name);
}

function validateDomain(string $domain): bool {
    return in_array($domain, Config::allowedDomains(), true);
}

function validateUuid(string $uuid): bool {
    return preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/', $uuid);
}

function getFileMimeType(string $fileName): string
{
    $extension = strtolower(pathinfo($fileName, PATHINFO_EXTENSION));

    $mimeTypes = [
        'json' => 'application/json',
        'jsonc' => 'application/json',
        'py' => 'text/x-python',
        'md' => 'text/markdown',
        'yml' => 'text/yaml',
        'yaml' => 'text/yaml',
        'sh' => 'text/x-shellscript',
        'txt' => 'text/plain',
        'js' => 'text/javascript'
    ];

    return $mimeTypes[$extension] ?? 'text/plain';
}

function logError(string $message, array $context = []): void {
    $timestamp = gmdate('Y-m-d H:i:s');
    $contextStr = $context ? ' ' . json_encode($context, JSON_UNESCAPED_SLASHES) : '';
    error_log("[$timestamp] Gateway Error: $message$contextStr");
}

try {
    $store = new SessionStore();
    $lmarenaBridge = new LMArenaBridgeProvider();
    $clientManager = new ClientManager();
    $requestRouter = new RequestRouter($clientManager, [
        'request_timeout' => (int)(getenv('GATEWAY_REQUEST_TIMEOUT') ?: 300),
        'retry_attempts' => (int)(getenv('GATEWAY_RETRY_ATTEMPTS') ?: 3),
        'load_balancing_strategy' => getenv('GATEWAY_LOAD_BALANCING') ?: 'least_load'
    ]);
    $configGenerator = new ClientConfigGenerator();
} catch (Exception $e) {
    logError('Failed to initialize services', ['error' => $e->getMessage()]);
    errorResponse('Service temporarily unavailable', 503, 'STORAGE_ERROR');
    exit;
}

// Health check with provider status
if ($path === '/health') {
    $health = [
        'status' => 'ok',
        'time' => gmdate('c'),
        'services' => [
            'session_store' => 'healthy',
            'lmarena_bridge' => $lmarenaBridge->isEnabled() ? 'enabled' : 'disabled'
        ]
    ];

    // Check LMArenaBridge health if enabled
    if ($lmarenaBridge->isEnabled()) {
        $bridgeHealth = $lmarenaBridge->healthCheck();
        $health['services']['lmarena_bridge'] = $bridgeHealth['status'];
        $health['lmarena_bridge_details'] = $bridgeHealth;
    }

    jsonResponse($health);
    exit;
}

// Provider status endpoint
if ($path === '/providers/status' && $method === 'GET') {
    $providers = [
        'lmarena_bridge_legacy' => [
            'enabled' => true,
            'base_url' => Config::defaultBridgeBaseUrl(),
            'has_api_key' => !empty(Config::defaultBridgeApiKey()),
            'type' => 'legacy_websocket'
        ],
        'lmarena_bridge_direct' => $lmarenaBridge->getConfig(),
        'distributed_clients' => [
            'enabled' => true,
            'total_clients' => count($clientManager->getAllClients()),
            'routing_stats' => $requestRouter->getRoutingStats()
        ]
    ];

    jsonResponse($providers);
    exit;
}

// Client registration endpoint
if ($path === '/clients/register' && $method === 'POST') {
    try {
        $data = getJsonBody();

        $requiredFields = ['name', 'lmarena_bridge_url'];
        foreach ($requiredFields as $field) {
            if (empty($data[$field])) {
                errorResponse("Field '$field' is required", 400, 'MISSING_FIELD');
                exit;
            }
        }

        // Validate LMArenaBridge URL
        if (!filter_var($data['lmarena_bridge_url'], FILTER_VALIDATE_URL)) {
            errorResponse('Invalid LMArenaBridge URL', 400, 'INVALID_URL');
            exit;
        }

        $result = $clientManager->registerClient($data);

        // Generate client package
        $clientPackage = $configGenerator->generateClientPackage($result);

        jsonResponse([
            'registration' => $result,
            'client_package' => $clientPackage
        ]);
        exit;

    } catch (Exception $e) {
        logError('Client registration failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to register client', 500, 'REGISTRATION_ERROR');
        exit;
    }
}

// Client management endpoints
if (preg_match('#^/clients/([^/]+)$#', $path, $matches) && $method === 'GET') {
    $clientId = $matches[1];
    $client = $clientManager->getClient($clientId);

    if (!$client) {
        errorResponse('Client not found', 404, 'CLIENT_NOT_FOUND');
        exit;
    }

    jsonResponse([
        'client' => $client,
        'stats' => $clientManager->getAllClients()
    ]);
    exit;
}

// List all clients
if ($path === '/clients' && $method === 'GET') {
    $clients = $clientManager->getAllClients();
    jsonResponse([
        'clients' => $clients,
        'total' => count($clients)
    ]);
    exit;
}

// Client health check endpoint
if ($path === '/clients/health' && $method === 'POST') {
    try {
        $healthResults = $requestRouter->performHealthChecks();
        jsonResponse([
            'health_checks' => $healthResults,
            'checked_at' => gmdate('c')
        ]);
        exit;

    } catch (Exception $e) {
        logError('Health check failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to perform health checks', 500, 'HEALTH_CHECK_ERROR');
        exit;
    }
}

// Client configuration download
if (preg_match('#^/clients/([^/]+)/download/([^/]+)$#', $path, $matches) && $method === 'GET') {
    $clientId = $matches[1];
    $fileName = $matches[2];

    $client = $clientManager->getClient($clientId);
    if (!$client) {
        errorResponse('Client not found', 404, 'CLIENT_NOT_FOUND');
        exit;
    }

    try {
        $clientPackage = $configGenerator->generateClientPackage($client);

        if (!isset($clientPackage['files'][$fileName])) {
            errorResponse('File not found', 404, 'FILE_NOT_FOUND');
            exit;
        }

        $content = $clientPackage['files'][$fileName];
        $mimeType = getFileMimeType($fileName);

        header("Content-Type: $mimeType");
        header("Content-Disposition: attachment; filename=\"$fileName\"");
        header('Content-Length: ' . strlen($content));

        echo $content;
        exit;

    } catch (Exception $e) {
        logError('File download failed', ['error' => $e->getMessage(), 'client_id' => $clientId, 'file' => $fileName]);
        errorResponse('Failed to generate file', 500, 'FILE_GENERATION_ERROR');
        exit;
    }
}

// Client package download (ZIP)
if (preg_match('#^/clients/([^/]+)/download$#', $path, $matches) && $method === 'GET') {
    $clientId = $matches[1];

    $client = $clientManager->getClient($clientId);
    if (!$client) {
        errorResponse('Client not found', 404, 'CLIENT_NOT_FOUND');
        exit;
    }

    try {
        $clientPackage = $configGenerator->generateClientPackage($client);

        // Create temporary ZIP file
        $tempFile = tempnam(sys_get_temp_dir(), 'lmarena_client_');
        $zip = new ZipArchive();

        if ($zip->open($tempFile, ZipArchive::CREATE) !== TRUE) {
            throw new Exception('Cannot create ZIP file');
        }

        // Add all files to ZIP
        foreach ($clientPackage['files'] as $fileName => $content) {
            $zip->addFromString($fileName, $content);
        }

        // Add userscript
        $zip->addFromString('userscript.js', $clientPackage['userscript']);

        $zip->close();

        // Send ZIP file
        header('Content-Type: application/zip');
        header("Content-Disposition: attachment; filename=\"lmarena-client-{$clientId}.zip\"");
        header('Content-Length: ' . filesize($tempFile));

        readfile($tempFile);
        unlink($tempFile);
        exit;

    } catch (Exception $e) {
        logError('Package download failed', ['error' => $e->getMessage(), 'client_id' => $clientId]);
        errorResponse('Failed to generate package', 500, 'PACKAGE_GENERATION_ERROR');
        exit;
    }
}

// Register or update a session mapping
// POST /session/register { domain, session_name, session_id, message_id, bridge_base_url?, bridge_api_key? }
if ($path === '/session/register' && $method === 'POST') {
    try {
        $data = getJsonBody();
        $domain = trim($data['domain'] ?? '');
        $sessionName = trim($data['session_name'] ?? '');
        $sessionId = trim($data['session_id'] ?? '');
        $messageId = trim($data['message_id'] ?? '');

        if (!$domain || !$sessionName || !$sessionId || !$messageId) {
            errorResponse('domain, session_name, session_id, message_id are required', 400, 'MISSING_FIELDS');
            exit;
        }

        if (!validateDomain($domain)) {
            errorResponse('unsupported domain: ' . $domain, 400, 'INVALID_DOMAIN');
            exit;
        }

        if (!validateSessionName($sessionName)) {
            errorResponse('session_name must be 1-64 alphanumeric characters, hyphens, or underscores', 400, 'INVALID_SESSION_NAME');
            exit;
        }

        if (!validateUuid($sessionId) || !validateUuid($messageId)) {
            errorResponse('session_id and message_id must be valid UUIDs', 400, 'INVALID_UUID');
            exit;
        }

        $payload = [
            'session_id' => $sessionId,
            'message_id' => $messageId,
        ];

        if (!empty($data['bridge_base_url'])) {
            $url = filter_var($data['bridge_base_url'], FILTER_VALIDATE_URL);
            if (!$url) {
                errorResponse('bridge_base_url must be a valid URL', 400, 'INVALID_URL');
                exit;
            }
            $payload['bridge_base_url'] = $url;
        }

        if (!empty($data['bridge_api_key'])) {
            $payload['bridge_api_key'] = trim($data['bridge_api_key']);
        }

        if (!empty($data['models']) && is_array($data['models'])) {
            $payload['models'] = $data['models'];
        }

        $store->setMapping($domain, $sessionName, $payload);
        jsonResponse(['status' => 'ok', 'domain' => $domain, 'session_name' => $sessionName]);
        exit;

    } catch (InvalidArgumentException $e) {
        errorResponse('Invalid request: ' . $e->getMessage(), 400, 'INVALID_JSON');
        exit;
    } catch (Exception $e) {
        logError('Session registration failed', ['error' => $e->getMessage()]);
        errorResponse('Registration failed', 500, 'STORAGE_ERROR');
        exit;
    }
}

// For diagnostics: list sessions
if ($path === '/session/list' && $method === 'GET') {
    try {
        $domain = $_GET['domain'] ?? null;
        if ($domain && !validateDomain($domain)) {
            errorResponse('Invalid domain parameter', 400, 'INVALID_DOMAIN');
            exit;
        }
        $result = $store->listSessions($domain);
        jsonResponse(['domains' => $result]);
        exit;
    } catch (Exception $e) {
        logError('Session list failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to list sessions', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Delete a session mapping
// DELETE /session/{domain}/{session_name}
if (preg_match('#^/session/([^/]+)/([^/]+)$#', $path, $matches) && $method === 'DELETE') {
    try {
        $domain = urldecode($matches[1]);
        $sessionName = urldecode($matches[2]);

        if (!validateDomain($domain)) {
            errorResponse('Invalid domain: ' . $domain, 400, 'INVALID_DOMAIN');
            exit;
        }

        if (!validateSessionName($sessionName)) {
            errorResponse('Invalid session name format', 400, 'INVALID_SESSION_NAME');
            exit;
        }

        $deleted = $store->deleteMapping($domain, $sessionName);
        if ($deleted) {
            jsonResponse(['status' => 'deleted', 'domain' => $domain, 'session_name' => $sessionName]);
        } else {
            errorResponse('Session not found', 404, 'SESSION_NOT_FOUND');
        }
        exit;

    } catch (Exception $e) {
        logError('Session deletion failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to delete session', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Session heartbeat endpoint
if ($path === '/session/heartbeat' && $method === 'POST') {
    try {
        $data = getJsonBody();
        $domain = trim($data['domain'] ?? '');
        $sessionName = trim($data['session_name'] ?? '');

        if (!$domain || !$sessionName) {
            errorResponse('domain and session_name are required', 400, 'MISSING_FIELDS');
            exit;
        }

        if (!validateDomain($domain)) {
            errorResponse('unsupported domain: ' . $domain, 400, 'INVALID_DOMAIN');
            exit;
        }

        // Update session timestamp
        $mapping = $store->getMapping($domain, $sessionName);
        if ($mapping) {
            $mapping['last_heartbeat'] = gmdate('c');
            $store->setMapping($domain, $sessionName, $mapping);
            jsonResponse(['status' => 'heartbeat_recorded', 'timestamp' => $mapping['last_heartbeat']]);
        } else {
            errorResponse('Session not found', 404, 'SESSION_NOT_FOUND');
        }
        exit;

    } catch (Exception $e) {
        logError('Session heartbeat failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to record heartbeat', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Analytics event endpoint
if ($path === '/analytics/event' && $method === 'POST') {
    try {
        $data = getJsonBody();
        $sessionName = trim($data['session_name'] ?? '');
        $domain = trim($data['domain'] ?? '');
        $event = trim($data['event'] ?? '');

        if (!$sessionName || !$domain || !$event) {
            errorResponse('session_name, domain, and event are required', 400, 'MISSING_FIELDS');
            exit;
        }

        // Log analytics event (could be enhanced to store in database)
        $timestamp = gmdate('Y-m-d H:i:s');
        error_log("[$timestamp] Analytics: $domain/$sessionName - $event: " . json_encode($data));

        jsonResponse(['status' => 'event_recorded', 'timestamp' => gmdate('c')]);
        exit;

    } catch (Exception $e) {
        logError('Analytics event failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to record event', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Helper function for proxying requests to LMArenaBridge
function proxyToBridge(string $endpoint, array $openaiReq, array $mapping, bool $isStream = true): void {
    $bridgeBase = $mapping['bridge_base_url'] ?? Config::defaultBridgeBaseUrl();
    $bridgeKey = $mapping['bridge_api_key'] ?? Config::defaultBridgeApiKey();

    $url = rtrim($bridgeBase, '/') . $endpoint;
    $headers = [
        'Content-Type: application/json',
        'User-Agent: LMArena-Gateway/1.0',
    ];
    if ($bridgeKey) $headers[] = 'Authorization: Bearer ' . $bridgeKey;

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_POSTFIELDS => json_encode($openaiReq, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        CURLOPT_RETURNTRANSFER => !$isStream,
        CURLOPT_HEADER => false,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 300,
        CURLOPT_CONNECTTIMEOUT => 30,
        CURLOPT_SSL_VERIFYPEER => false, // For local development
    ]);

    if ($isStream) {
        header('Content-Type: text/event-stream');
        header('Cache-Control: no-cache');
        header('X-Accel-Buffering: no');

        curl_setopt($ch, CURLOPT_WRITEFUNCTION, function ($ch_unused, $data) {
            echo $data;
            @ob_flush();
            flush();
            return strlen($data);
        });

        $success = curl_exec($ch);
        if (!$success) {
            $error = curl_error($ch);
            logError('Bridge streaming failed', ['url' => $url, 'error' => $error]);
        }
    } else {
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);

        if ($response === false) {
            logError('Bridge request failed', ['url' => $url, 'error' => $error]);
            errorResponse('Bridge connection failed: ' . $error, 502, 'BRIDGE_ERROR');
        } else {
            http_response_code($httpCode);
            header('Content-Type: application/json');
            echo $response;
        }
    }

    curl_close($ch);
}

// OpenAI-compatible passthrough with provider routing
// POST /v1/chat/completions
if ($path === '/v1/chat/completions' && $method === 'POST') {
    try {
        $openaiReq = getJsonBody();

        // Session selection strategy
        $sessionName = trim($_SERVER['HTTP_X_SESSION_NAME'] ?? ($_SERVER['HTTP_X_SESSION_ID'] ?? 'default'));
        $targetDomain = trim($_SERVER['HTTP_X_TARGET_DOMAIN'] ?? 'lmarena.ai');
        $preferredProvider = trim($_SERVER['HTTP_X_PROVIDER'] ?? 'auto'); // auto, lmarena, bridge_direct, distributed

        if (!validateDomain($targetDomain)) {
            errorResponse('X-Target-Domain not allowed: ' . $targetDomain, 400, 'INVALID_DOMAIN');
            exit;
        }

        if (!validateSessionName($sessionName)) {
            errorResponse('X-Session-Name invalid format', 400, 'INVALID_SESSION_NAME');
            exit;
        }

        // Provider selection logic
        $model = $openaiReq['model'] ?? '';

        // Check if we should use distributed client routing
        if ($preferredProvider === 'distributed' || $preferredProvider === 'auto') {
            try {
                $requiredCapabilities = ['chat'];

                if ($openaiReq['stream'] ?? true) {
                    // Stream from distributed clients
                    header('Content-Type: text/event-stream');
                    header('Cache-Control: no-cache');
                    header('Connection: keep-alive');
                    header('X-Accel-Buffering: no');

                    foreach ($requestRouter->streamRequest($openaiReq, $requiredCapabilities) as $chunk) {
                        echo $chunk;
                        if (ob_get_level()) {
                            ob_flush();
                        }
                        flush();
                    }
                } else {
                    // Non-streaming request to distributed clients
                    $result = $requestRouter->routeRequest($openaiReq, $requiredCapabilities);

                    if ($result['success']) {
                        jsonResponse($result['data']);
                    } else {
                        errorResponse($result['error'], 500, $result['error_code'] ?? 'ROUTING_ERROR');
                    }
                }
                exit;

            } catch (Exception $e) {
                logError('Distributed routing failed, falling back to direct integration', ['error' => $e->getMessage()]);
                // Fall through to direct integration
            }
        }

        // Direct LMArenaBridge integration fallback
        $useBridgeDirect = false;
        if ($preferredProvider === 'bridge_direct' && $lmarenaBridge->isEnabled()) {
            $useBridgeDirect = true;
        } elseif ($preferredProvider === 'auto' && $lmarenaBridge->isEnabled()) {
            if ($lmarenaBridge->hasModel($model)) {
                $useBridgeDirect = true;
            }
        }

        // Route to direct LMArenaBridge if selected and model is available
        if ($useBridgeDirect && $lmarenaBridge->hasModel($model)) {
            try {
                $sessionMapping = $lmarenaBridge->getSessionMapping($model);

                if ($openaiReq['stream'] ?? true) {
                    $lmarenaBridge->streamChatCompletion($openaiReq, $sessionMapping ?: []);
                } else {
                    $result = $lmarenaBridge->chatCompletion($openaiReq, $sessionMapping ?: []);
                    jsonResponse($result);
                }
                exit;
            } catch (Exception $e) {
                logError('Direct LMArenaBridge request failed, falling back to legacy WebSocket bridge', ['error' => $e->getMessage()]);
                // Fall through to legacy WebSocket LMArenaBridge
            }
        }

        $mapping = $store->getMapping($targetDomain, $sessionName);
        if (!$mapping) {
            errorResponse('Session mapping not found for domain/session. Register first via /session/register', 404, 'SESSION_NOT_FOUND');
            exit;
        }

        // Default to streaming true if not specified
        $isStream = $openaiReq['stream'] ?? true;

        // Inject model mapping overrides if present
        if (!empty($mapping['models']) && is_array($mapping['models']) && !empty($openaiReq['model'])) {
            if (isset($mapping['models'][$openaiReq['model']])) {
                $openaiReq['model'] = $mapping['models'][$openaiReq['model']];
            }
        }

        proxyToBridge('/v1/chat/completions', $openaiReq, $mapping, $isStream);
        exit;

    } catch (InvalidArgumentException $e) {
        errorResponse('Invalid request: ' . $e->getMessage(), 400, 'INVALID_JSON');
        exit;
    } catch (Exception $e) {
        logError('Chat completion failed', ['error' => $e->getMessage()]);
        errorResponse('Request failed', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// POST /v1/images/generations - Image generation passthrough
if ($path === '/v1/images/generations' && $method === 'POST') {
    try {
        $openaiReq = getJsonBody();

        $sessionName = trim($_SERVER['HTTP_X_SESSION_NAME'] ?? 'default');
        $targetDomain = trim($_SERVER['HTTP_X_TARGET_DOMAIN'] ?? 'lmarena.ai');

        if (!validateDomain($targetDomain)) {
            errorResponse('X-Target-Domain not allowed: ' . $targetDomain, 400, 'INVALID_DOMAIN');
            exit;
        }

        if (!validateSessionName($sessionName)) {
            errorResponse('X-Session-Name invalid format', 400, 'INVALID_SESSION_NAME');
            exit;
        }

        $mapping = $store->getMapping($targetDomain, $sessionName);
        if (!$mapping) {
            errorResponse('Session mapping not found for domain/session. Register first via /session/register', 404, 'SESSION_NOT_FOUND');
            exit;
        }

        // Image generation is always non-streaming
        proxyToBridge('/v1/images/generations', $openaiReq, $mapping, false);
        exit;

    } catch (InvalidArgumentException $e) {
        errorResponse('Invalid request: ' . $e->getMessage(), 400, 'INVALID_JSON');
        exit;
    } catch (Exception $e) {
        logError('Image generation failed', ['error' => $e->getMessage()]);
        errorResponse('Request failed', 500, 'INTERNAL_ERROR');
        exit;
    }

    // Inject model mapping overrides if present
    if (!empty($mapping['models']) && is_array($mapping['models']) && !empty($openaiReq['model'])) {
        // Allow a per-session aliasing: e.g. user-facing model name -> real bridge model name
        if (isset($mapping['models'][$openaiReq['model']])) {
            $openaiReq['model'] = $mapping['models'][$openaiReq['model']];
        }
    }

    // Use curl for streaming passthrough
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($openaiReq, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
    curl_setopt($ch, CURLOPT_HEADER, false);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);

    if ($isStream) {
        header('Content-Type: text/event-stream');
        header('Cache-Control: no-cache');
        header('X-Accel-Buffering: no'); // for nginx, harmless otherwise

        curl_setopt($ch, CURLOPT_WRITEFUNCTION, function ($ch, $data) {
            echo $data;
            @ob_flush();
            flush();
            return strlen($data);
        });
        $ok = curl_exec($ch);
        if ($ok === false) {
            error_log('Bridge stream error: ' . curl_error($ch));
        }
        curl_close($ch);
        exit;
    } else {
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE) ?: 200;
        $err = curl_error($ch);
        curl_close($ch);
        if ($resp === false) {
            errorResponse('Bridge error: ' . $err, 502);
            exit;
        }
        http_response_code($code);
        header('Content-Type: application/json');
        echo $resp;
        exit;
    }
}

// Forward models list
if ($path === '/v1/models' && $method === 'GET') {
    try {
        $sessionName = trim($_SERVER['HTTP_X_SESSION_NAME'] ?? 'default');
        $targetDomain = trim($_SERVER['HTTP_X_TARGET_DOMAIN'] ?? 'lmarena.ai');

        if (!validateDomain($targetDomain)) {
            errorResponse('X-Target-Domain not allowed: ' . $targetDomain, 400, 'INVALID_DOMAIN');
            exit;
        }

        if (!validateSessionName($sessionName)) {
            errorResponse('X-Session-Name invalid format', 400, 'INVALID_SESSION_NAME');
            exit;
        }

        $mapping = $store->getMapping($targetDomain, $sessionName) ?? [];
        $bridgeBase = $mapping['bridge_base_url'] ?? Config::defaultBridgeBaseUrl();
        $bridgeKey = $mapping['bridge_api_key'] ?? Config::defaultBridgeApiKey();

        $url = rtrim($bridgeBase, '/') . '/v1/models';
        $headers = ['User-Agent: LMArena-Gateway/1.0'];
        if ($bridgeKey) $headers[] = 'Authorization: Bearer ' . $bridgeKey;

        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_HTTPGET => true,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_SSL_VERIFYPEER => false,
        ]);

        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_HTTP_CODE) ?: 200;
        $err = curl_error($ch);
        curl_close($ch);

        if ($resp === false) {
            logError('Models request failed', ['url' => $url, 'error' => $err]);
            errorResponse('Bridge error: ' . $err, 502, 'BRIDGE_ERROR');
            exit;
        }

        http_response_code($code);
        header('Content-Type: application/json');
        echo $resp;
        exit;

    } catch (Exception $e) {
        logError('Models endpoint failed', ['error' => $e->getMessage()]);
        errorResponse('Request failed', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Tampermonkey userscript generator
if ($path === '/userscript/generate' && $method === 'GET') {
    $sessionName = trim($_GET['session_name'] ?? 'default');

    if (!validateSessionName($sessionName)) {
        errorResponse('session_name parameter invalid format', 400, 'INVALID_SESSION_NAME');
        exit;
    }

    // Try to infer public base URL for registrations
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    $base = $scheme . '://' . $host;
    $registerUrl = $base . '/session/register';

    header('Content-Type: text/javascript; charset=utf-8');
    header('Content-Disposition: attachment; filename="lmarena-registrar-' . $sessionName . '.user.js"');

    echo "// ==UserScript==\n";
    echo "// @name         LMArena Session Registrar (" . htmlspecialchars($sessionName, ENT_QUOTES) . ")\n";
    echo "// @namespace    https://" . htmlspecialchars($host, ENT_QUOTES) . "/\n";
    echo "// @version      1.0.0\n";
    echo "// @description  Captures LMArena evaluation session/message IDs and registers them to the PHP gateway for domain+session mapping. Supports all LMArena domains with error handling.\n";
    echo "// @author       LMArena Gateway\n";
    echo "// @match        https://lmarena.ai/*\n";
    echo "// @match        https://*.lmarena.ai/*\n";
    echo "// @icon         https://www.google.com/s2/favicons?sz=64&domain=lmarena.ai\n";
    echo "// @grant        none\n";
    echo "// @run-at       document-start\n";
    echo "// @updateURL    " . $base . "/userscript/generate?session_name=" . urlencode($sessionName) . "\n";
    echo "// @downloadURL  " . $base . "/userscript/generate?session_name=" . urlencode($sessionName) . "\n";
    echo "// ==/UserScript==\n\n";

    $js = <<<JS
(function(){
  'use strict';

  // Configuration
  const SESSION_NAME = %s;
  const REGISTER_URL = %s;
  const ALLOWED_DOMAINS = ['lmarena.ai', 'canary.lmarena.ai', 'alpha.lmarena.ai', 'beta.lmarena.ai'];

  // State management
  let isRegistering = false;
  let lastRegistration = null;

  // Utility functions
  function log(message, ...args) {
    console.log('[LMArena Registrar]', message, ...args);
  }

  function warn(message, ...args) {
    console.warn('[LMArena Registrar]', message, ...args);
  }

  function error(message, ...args) {
    console.error('[LMArena Registrar]', message, ...args);
  }

  function getDomain() {
    const h = location.hostname.toLowerCase();
    for (const domain of ALLOWED_DOMAINS) {
      if (h === domain || h.endsWith('.' + domain)) {
        return domain;
      }
    }
    return 'lmarena.ai'; // fallback
  }

  function isValidUuid(str) {
    return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(str);
  }

  const KEY = (dom) => 'lm_session_' + dom + '_' + SESSION_NAME;

  const saveLocal = (dom, sessId, msgId) => {
    try {
      const obj = {
        session_id: sessId,
        message_id: msgId,
        domain: dom,
        session_name: SESSION_NAME,
        updated_at: new Date().toISOString(),
        user_agent: navigator.userAgent
      };
      localStorage.setItem(KEY(dom), JSON.stringify(obj));
      log('Saved to localStorage:', dom, SESSION_NAME);
    } catch (e) {
      warn('Failed to save to localStorage:', e.message);
    }
  };

  const registerRemote = async (dom, sessId, msgId) => {
    if (isRegistering) {
      log('Registration already in progress, skipping...');
      return;
    }

    // Prevent duplicate registrations within 5 seconds
    const now = Date.now();
    if (lastRegistration && (now - lastRegistration) < 5000) {
      log('Recent registration detected, skipping duplicate...');
      return;
    }

    isRegistering = true;
    lastRegistration = now;

    try {
      log('Registering session:', { domain: dom, session_name: SESSION_NAME, session_id: sessId.substring(0, 8) + '...' });

      const resp = await fetch(REGISTER_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'LMArena-Registrar/1.0'
        },
        body: JSON.stringify({
          domain: dom,
          session_name: SESSION_NAME,
          session_id: sessId,
          message_id: msgId
        })
      });

      if (resp.ok) {
        const result = await resp.json();
        log('✅ Successfully registered session:', result);

        // Update page title to show success
        if (document.title && !document.title.includes('✅')) {
          document.title = '✅ ' + document.title;
        }
      } else {
        const errorText = await resp.text();
        warn('❌ Registration failed with status', resp.status, ':', errorText);
      }
    } catch (e) {
      error('❌ Registration request failed:', e.message);
    } finally {
      isRegistering = false;
    }
  };

  // Enhanced fetch interceptor with validation
  const originalFetch = window.fetch;
  window.fetch = function(...args){
    let urlString = '';
    const urlArg = args[0];
    if (urlArg instanceof Request) urlString = urlArg.url;
    else if (urlArg instanceof URL) urlString = urlArg.href;
    else if (typeof urlArg === 'string') urlString = urlArg;

    if (urlString) {
      const m = urlString.match(/\/api\/stream\/retry-evaluation-session-message\/([a-f0-9-]+)\/messages\/([a-f0-9-]+)/);
      if (m) {
        const sessionId = m[1];
        const messageId = m[2];
        const dom = getDomain();

        // Validate UUIDs
        if (!isValidUuid(sessionId) || !isValidUuid(messageId)) {
          warn('Invalid UUID format detected:', { sessionId, messageId });
          return originalFetch.apply(this, args);
        }

        log('🎯 Captured session IDs:', {
          domain: dom,
          session_name: SESSION_NAME,
          session_id: sessionId.substring(0, 8) + '...',
          message_id: messageId.substring(0, 8) + '...'
        });

        saveLocal(dom, sessionId, messageId);
        registerRemote(dom, sessionId, messageId);
      }
    }
    return originalFetch.apply(this, args);
  };

  // Initialize
  log('🚀 LMArena Session Registrar initialized');
  log('Session Name:', SESSION_NAME);
  log('Target Domain:', getDomain());
  log('Register URL:', REGISTER_URL);

  // Show status in page title
  if (document.title && !document.title.includes('🎯')) {
    document.title = '🎯 ' + document.title;
  }
})();
JS;

    printf($js,
      json_encode($sessionName, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE),
      json_encode($registerUrl, JSON_UNESCAPED_SLASHES)
    );
    exit;
}

// OpenAI-compatible models endpoint
// GET /v1/models
if ($path === '/v1/models' && $method === 'GET') {
    try {
        $models = [];

        // Add models from direct LMArenaBridge integration
        if ($lmarenaBridge->isEnabled()) {
            $bridgeModels = $lmarenaBridge->getModels();
            if (isset($bridgeModels['data'])) {
                $models = array_merge($models, $bridgeModels['data']);
            }
        }

        // Add fallback models for legacy WebSocket bridge
        $legacyModels = [
            'gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo', 'claude-3-opus',
            'claude-3-sonnet', 'claude-3-haiku', 'gemini-pro'
        ];

        foreach ($legacyModels as $modelName) {
            // Only add if not already present from direct bridge
            $exists = false;
            foreach ($models as $existingModel) {
                if ($existingModel['id'] === $modelName) {
                    $exists = true;
                    break;
                }
            }

            if (!$exists) {
                $models[] = [
                    'id' => $modelName,
                    'object' => 'model',
                    'created' => time(),
                    'owned_by' => 'LMArenaBridge-Legacy'
                ];
            }
        }

        jsonResponse([
            'object' => 'list',
            'data' => $models
        ]);
        exit;

    } catch (Exception $e) {
        logError('Models endpoint failed', ['error' => $e->getMessage()]);
        errorResponse('Failed to retrieve models', 500, 'INTERNAL_ERROR');
        exit;
    }
}

// Not found
errorResponse('Not found', 404);

