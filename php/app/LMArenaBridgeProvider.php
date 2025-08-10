<?php
// php/app/LMArenaBridgeProvider.php
// LMArenaBridge integration for PHP AI API gateway

namespace GatewayApp;

class LMArenaBridgeProvider
{
    private array $config;
    private int $timeout;
    private ?array $models = null;
    private ?array $bridgeConfig = null;
    private ?array $modelEndpointMap = null;

    public function __construct(?array $config = null)
    {
        $this->config = $config ?: Config::lmarenaBridgeConfig();
        $this->timeout = $this->config['timeout'];
        $this->loadBridgeConfiguration();
    }

    public function isEnabled(): bool
    {
        return $this->config['enabled'] && !empty($this->config['api_base_url']);
    }

    /**
     * Load LMArenaBridge configuration files
     */
    private function loadBridgeConfiguration(): void
    {
        // Load models.json
        if (file_exists($this->config['models_file'])) {
            $modelsContent = file_get_contents($this->config['models_file']);
            $this->models = json_decode($modelsContent, true) ?: [];
        }

        // Load config.jsonc
        if (file_exists($this->config['config_file'])) {
            $configContent = file_get_contents($this->config['config_file']);
            // Remove JSONC comments
            $configContent = preg_replace('/\/\/.*/', '', $configContent);
            $configContent = preg_replace('/\/\*.*?\*\//', '', $configContent, -1, PREG_SET_ORDER);
            $this->bridgeConfig = json_decode($configContent, true) ?: [];
        }

        // Load model_endpoint_map.json
        if (file_exists($this->config['model_endpoint_map_file'])) {
            $mapContent = file_get_contents($this->config['model_endpoint_map_file']);
            $this->modelEndpointMap = json_decode($mapContent, true) ?: [];
        }
    }

    /**
     * Get available models from LMArenaBridge
     */
    public function getModels(): array
    {
        if (!$this->isEnabled()) {
            return ['data' => [], 'error' => 'LMArenaBridge is not enabled'];
        }

        if (empty($this->models)) {
            return ['data' => [], 'error' => 'No models available'];
        }

        $modelList = [];
        foreach ($this->models as $modelName => $modelId) {
            $modelList[] = [
                'id' => $modelName,
                'object' => 'model',
                'created' => time(),
                'owned_by' => 'LMArenaBridge'
            ];
        }

        return [
            'object' => 'list',
            'data' => $modelList
        ];
    }

    /**
     * Forward chat completion request to LMArenaBridge
     */
    public function chatCompletion(array $payload, array $sessionMapping = []): array
    {
        if (!$this->isEnabled()) {
            throw new \RuntimeException('LMArenaBridge is not enabled');
        }

        $url = rtrim($this->config['api_base_url'], '/') . '/v1/chat/completions';
        
        $headers = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-Bridge/1.0',
        ];

        if (!empty($this->config['api_key'])) {
            $headers[] = 'Authorization: Bearer ' . $this->config['api_key'];
        }

        // Add session context headers if available
        if (!empty($sessionMapping['session_id'])) {
            $headers[] = 'X-LMArena-Session-ID: ' . $sessionMapping['session_id'];
        }
        if (!empty($sessionMapping['message_id'])) {
            $headers[] = 'X-LMArena-Message-ID: ' . $sessionMapping['message_id'];
        }

        return $this->makeRequest($url, $payload, $headers);
    }

    /**
     * Stream chat completion response from LMArenaBridge
     */
    public function streamChatCompletion(array $payload, array $sessionMapping = []): void
    {
        if (!$this->isEnabled()) {
            throw new \RuntimeException('LMArenaBridge is not enabled');
        }

        $url = rtrim($this->config['api_base_url'], '/') . '/v1/chat/completions';
        
        $headers = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-Bridge/1.0',
        ];

        if (!empty($this->config['api_key'])) {
            $headers[] = 'Authorization: Bearer ' . $this->config['api_key'];
        }

        // Add session context headers if available
        if (!empty($sessionMapping['session_id'])) {
            $headers[] = 'X-LMArena-Session-ID: ' . $sessionMapping['session_id'];
        }
        if (!empty($sessionMapping['message_id'])) {
            $headers[] = 'X-LMArena-Message-ID: ' . $sessionMapping['message_id'];
        }

        $this->streamResponse($url, $payload, $headers);
    }

    /**
     * Get session mapping for a specific model
     */
    public function getSessionMapping(string $modelName): ?array
    {
        // First check model-specific endpoint mapping
        if (!empty($this->modelEndpointMap[$modelName])) {
            $mapping = $this->modelEndpointMap[$modelName];
            
            // Handle array of mappings (select random one)
            if (is_array($mapping) && isset($mapping[0])) {
                $mapping = $mapping[array_rand($mapping)];
            }
            
            return [
                'session_id' => $mapping['session_id'] ?? null,
                'message_id' => $mapping['message_id'] ?? null,
                'mode' => $mapping['mode'] ?? null,
                'battle_target' => $mapping['battle_target'] ?? null,
            ];
        }

        // Fall back to global configuration
        if (!empty($this->bridgeConfig)) {
            return [
                'session_id' => $this->bridgeConfig['session_id'] ?? null,
                'message_id' => $this->bridgeConfig['message_id'] ?? null,
                'mode' => $this->bridgeConfig['id_updater_last_mode'] ?? 'direct_chat',
                'battle_target' => $this->bridgeConfig['id_updater_battle_target'] ?? 'A',
            ];
        }

        return null;
    }

    /**
     * Validate if model exists in LMArenaBridge
     */
    public function hasModel(string $modelName): bool
    {
        return !empty($this->models[$modelName]);
    }

    /**
     * Get model ID for LMArenaBridge
     */
    public function getModelId(string $modelName): ?string
    {
        return $this->models[$modelName] ?? null;
    }

    private function makeRequest(string $url, array $payload, array $headers): array
    {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, $this->timeout);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_USERAGENT, 'LMArena-Gateway-Bridge/1.0');

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($response === false || !empty($error)) {
            throw new \RuntimeException("cURL error: $error");
        }

        if ($httpCode >= 400) {
            throw new \RuntimeException("HTTP error $httpCode: $response");
        }

        $decoded = json_decode($response, true);
        if (json_last_error() !== JSON_ERROR_NONE) {
            throw new \RuntimeException("Invalid JSON response: " . json_last_error_msg());
        }

        return $decoded;
    }

    private function streamResponse(string $url, array $payload, array $headers): void
    {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
        curl_setopt($ch, CURLOPT_HEADER, false);
        curl_setopt($ch, CURLOPT_TIMEOUT, $this->timeout);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        curl_setopt($ch, CURLOPT_USERAGENT, 'LMArena-Gateway-Bridge/1.0');

        // Set up streaming headers
        header('Content-Type: text/event-stream');
        header('Cache-Control: no-cache');
        header('Connection: keep-alive');
        header('X-Accel-Buffering: no'); // Disable nginx buffering

        // Stream callback function
        curl_setopt($ch, CURLOPT_WRITEFUNCTION, function($ch, $data) {
            echo $data;
            if (ob_get_level()) {
                ob_flush();
            }
            flush();
            return strlen($data);
        });

        $result = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($result === false || !empty($error)) {
            // Send error as SSE event
            echo "data: " . json_encode(['error' => "cURL error: $error"]) . "\n\n";
            if (ob_get_level()) {
                ob_flush();
            }
            flush();
        }

        if ($httpCode >= 400) {
            // Send HTTP error as SSE event
            echo "data: " . json_encode(['error' => "HTTP error $httpCode"]) . "\n\n";
            if (ob_get_level()) {
                ob_flush();
            }
            flush();
        }
    }

    /**
     * Health check for LMArenaBridge
     */
    public function healthCheck(): array
    {
        try {
            $start = microtime(true);
            $url = rtrim($this->config['api_base_url'], '/') . '/v1/models';
            $this->makeRequest($url, [], []);
            $latency = round((microtime(true) - $start) * 1000, 2);
            
            return [
                'status' => 'healthy',
                'latency_ms' => $latency,
                'provider' => 'LMArenaBridge',
                'base_url' => $this->config['api_base_url'],
                'models_loaded' => count($this->models ?? []),
                'has_config' => !empty($this->bridgeConfig),
                'has_model_map' => !empty($this->modelEndpointMap)
            ];
        } catch (\Exception $e) {
            return [
                'status' => 'unhealthy',
                'error' => $e->getMessage(),
                'provider' => 'LMArenaBridge',
                'base_url' => $this->config['api_base_url']
            ];
        }
    }

    /**
     * Get provider configuration (sanitized)
     */
    public function getConfig(): array
    {
        $config = $this->config;
        // Remove sensitive information
        if (isset($config['api_key'])) {
            $config['api_key'] = $config['api_key'] ? '***' : null;
        }
        $config['models_count'] = count($this->models ?? []);
        $config['has_bridge_config'] = !empty($this->bridgeConfig);
        $config['has_model_endpoint_map'] = !empty($this->modelEndpointMap);
        return $config;
    }
}
