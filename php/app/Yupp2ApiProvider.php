<?php
// php/app/Yupp2ApiProvider.php
// yupp2Api provider integration for AI API gateway

namespace GatewayApp;

class Yupp2ApiProvider
{
    private array $config;
    private int $timeout;
    private int $retryAttempts;

    public function __construct(?array $config = null)
    {
        $this->config = $config ?: Config::yupp2ApiConfig();
        $this->timeout = $this->config['timeout'];
        $this->retryAttempts = $this->config['retry_attempts'];
    }

    public function isEnabled(): bool
    {
        return $this->config['enabled'] && !empty($this->config['base_url']);
    }

    /**
     * Forward OpenAI-compatible request to yupp2Api provider
     */
    public function forwardRequest(string $endpoint, array $payload, array $headers = []): array
    {
        if (!$this->isEnabled()) {
            throw new \RuntimeException('yupp2Api provider is not enabled');
        }

        $url = rtrim($this->config['base_url'], '/') . $endpoint;
        
        $defaultHeaders = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-yupp2Api/1.0',
        ];

        if (!empty($this->config['api_key'])) {
            $defaultHeaders[] = 'Authorization: Bearer ' . $this->config['api_key'];
        }

        $allHeaders = array_merge($defaultHeaders, $headers);

        for ($attempt = 1; $attempt <= $this->retryAttempts; $attempt++) {
            try {
                $result = $this->makeRequest($url, $payload, $allHeaders);
                return $result;
            } catch (\Exception $e) {
                if ($attempt === $this->retryAttempts) {
                    throw new \RuntimeException(
                        "yupp2Api request failed after {$this->retryAttempts} attempts: " . $e->getMessage()
                    );
                }
                
                // Exponential backoff
                usleep(pow(2, $attempt) * 100000); // 200ms, 400ms, 800ms...
            }
        }
    }

    /**
     * Stream response from yupp2Api provider
     */
    public function streamRequest(string $endpoint, array $payload, array $headers = []): void
    {
        if (!$this->isEnabled()) {
            throw new \RuntimeException('yupp2Api provider is not enabled');
        }

        $url = rtrim($this->config['base_url'], '/') . $endpoint;
        
        $defaultHeaders = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-yupp2Api/1.0',
        ];

        if (!empty($this->config['api_key'])) {
            $defaultHeaders[] = 'Authorization: Bearer ' . $this->config['api_key'];
        }

        $allHeaders = array_merge($defaultHeaders, $headers);

        $this->streamResponse($url, $payload, $allHeaders);
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
        curl_setopt($ch, CURLOPT_USERAGENT, 'LMArena-Gateway-yupp2Api/1.0');

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
        curl_setopt($ch, CURLOPT_USERAGENT, 'LMArena-Gateway-yupp2Api/1.0');

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
     * Get available models from yupp2Api provider
     */
    public function getModels(): array
    {
        try {
            return $this->forwardRequest('/v1/models', []);
        } catch (\Exception $e) {
            error_log("yupp2Api getModels failed: " . $e->getMessage());
            return ['data' => [], 'error' => $e->getMessage()];
        }
    }

    /**
     * Health check for yupp2Api provider
     */
    public function healthCheck(): array
    {
        try {
            $start = microtime(true);
            $this->forwardRequest('/health', []);
            $latency = round((microtime(true) - $start) * 1000, 2);
            
            return [
                'status' => 'healthy',
                'latency_ms' => $latency,
                'provider' => 'yupp2Api',
                'base_url' => $this->config['base_url']
            ];
        } catch (\Exception $e) {
            return [
                'status' => 'unhealthy',
                'error' => $e->getMessage(),
                'provider' => 'yupp2Api',
                'base_url' => $this->config['base_url']
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
        return $config;
    }
}
