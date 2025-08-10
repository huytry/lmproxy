<?php
// php/app/RequestRouter.php
// Request routing system for distributed LMArenaBridge architecture

namespace GatewayApp;

class RequestRouter
{
    private ClientManager $clientManager;
    private array $config;
    private array $activeRequests = [];

    public function __construct(ClientManager $clientManager, array $config = [])
    {
        $this->clientManager = $clientManager;
        $this->config = array_merge([
            'request_timeout' => 300,
            'retry_attempts' => 3,
            'health_check_interval' => 60,
            'load_balancing_strategy' => 'least_load' // least_load, round_robin, random
        ], $config);
    }

    /**
     * Route request to appropriate client LMArenaBridge
     */
    public function routeRequest(array $request, array $requiredCapabilities = []): array
    {
        $requestId = $this->generateRequestId();
        
        try {
            // Get available clients
            $availableClients = $this->clientManager->getAvailableClients($requiredCapabilities);
            
            if (empty($availableClients)) {
                return [
                    'success' => false,
                    'error' => 'No available clients for request',
                    'error_code' => 'NO_CLIENTS_AVAILABLE'
                ];
            }

            // Select client based on load balancing strategy
            $selectedClient = $this->selectClient($availableClients);
            
            // Check rate limits
            $rateLimitCheck = $this->clientManager->checkRateLimit($selectedClient['client_id']);
            if (!$rateLimitCheck['allowed']) {
                return [
                    'success' => false,
                    'error' => $rateLimitCheck['reason'],
                    'error_code' => 'RATE_LIMIT_EXCEEDED',
                    'rate_limit_info' => $rateLimitCheck
                ];
            }

            // Forward request to client
            $startTime = microtime(true);
            $response = $this->forwardToClient($selectedClient, $request, $requestId);
            $responseTime = (microtime(true) - $startTime) * 1000; // Convert to milliseconds

            // Record statistics
            $this->clientManager->recordRequest(
                $selectedClient['client_id'],
                $response['success'],
                $responseTime
            );

            return array_merge($response, [
                'client_id' => $selectedClient['client_id'],
                'response_time_ms' => round($responseTime, 2)
            ]);

        } catch (\Exception $e) {
            error_log("Request routing error: " . $e->getMessage());
            return [
                'success' => false,
                'error' => 'Internal routing error',
                'error_code' => 'ROUTING_ERROR'
            ];
        }
    }

    /**
     * Stream request to client LMArenaBridge
     */
    public function streamRequest(array $request, array $requiredCapabilities = []): \Generator
    {
        $requestId = $this->generateRequestId();
        
        try {
            // Get available clients
            $availableClients = $this->clientManager->getAvailableClients($requiredCapabilities);
            
            if (empty($availableClients)) {
                yield json_encode([
                    'error' => 'No available clients for streaming request'
                ]) . "\n";
                return;
            }

            // Select client
            $selectedClient = $this->selectClient($availableClients);
            
            // Check rate limits
            $rateLimitCheck = $this->clientManager->checkRateLimit($selectedClient['client_id']);
            if (!$rateLimitCheck['allowed']) {
                yield json_encode([
                    'error' => $rateLimitCheck['reason'],
                    'rate_limit_info' => $rateLimitCheck
                ]) . "\n";
                return;
            }

            // Stream from client
            $startTime = microtime(true);
            $success = true;
            
            try {
                foreach ($this->streamFromClient($selectedClient, $request, $requestId) as $chunk) {
                    yield $chunk;
                }
            } catch (\Exception $e) {
                $success = false;
                yield json_encode(['error' => $e->getMessage()]) . "\n";
            }

            $responseTime = (microtime(true) - $startTime) * 1000;
            
            // Record statistics
            $this->clientManager->recordRequest(
                $selectedClient['client_id'],
                $success,
                $responseTime
            );

        } catch (\Exception $e) {
            error_log("Stream routing error: " . $e->getMessage());
            yield json_encode(['error' => 'Internal streaming error']) . "\n";
        }
    }

    /**
     * Select client based on load balancing strategy
     */
    private function selectClient(array $availableClients): array
    {
        if (empty($availableClients)) {
            throw new \RuntimeException('No clients available');
        }

        switch ($this->config['load_balancing_strategy']) {
            case 'round_robin':
                return $this->selectRoundRobin($availableClients);
            
            case 'random':
                return $availableClients[array_rand($availableClients)];
            
            case 'least_load':
            default:
                return $availableClients[0]; // Already sorted by load score
        }
    }

    /**
     * Round robin client selection
     */
    private function selectRoundRobin(array $availableClients): array
    {
        static $lastIndex = -1;
        $lastIndex = ($lastIndex + 1) % count($availableClients);
        return $availableClients[$lastIndex];
    }

    /**
     * Forward request to client LMArenaBridge
     */
    private function forwardToClient(array $client, array $request, string $requestId): array
    {
        $clientData = $client['client'];
        $url = rtrim($clientData['lmarena_bridge_url'], '/') . '/v1/chat/completions';
        
        $headers = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-Platform/1.0',
            'X-Request-ID: ' . $requestId,
            'X-Client-ID: ' . $clientData['client_id'],
            'Authorization: Bearer ' . $clientData['api_key']
        ];

        return $this->makeHttpRequest($url, $request, $headers, false);
    }

    /**
     * Stream from client LMArenaBridge
     */
    private function streamFromClient(array $client, array $request, string $requestId): \Generator
    {
        $clientData = $client['client'];
        $url = rtrim($clientData['lmarena_bridge_url'], '/') . '/v1/chat/completions';
        
        $headers = [
            'Content-Type: application/json',
            'User-Agent: LMArena-Gateway-Platform/1.0',
            'X-Request-ID: ' . $requestId,
            'X-Client-ID: ' . $clientData['client_id'],
            'Authorization: Bearer ' . $clientData['api_key']
        ];

        // Ensure streaming is enabled
        $request['stream'] = true;

        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($request));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
        curl_setopt($ch, CURLOPT_HEADER, false);
        curl_setopt($ch, CURLOPT_TIMEOUT, $this->config['request_timeout']);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);

        // Stream callback
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
            throw new \RuntimeException("Client request failed: $error");
        }

        if ($httpCode >= 400) {
            throw new \RuntimeException("Client returned HTTP $httpCode");
        }
    }

    /**
     * Make HTTP request to client
     */
    private function makeHttpRequest(string $url, array $data, array $headers, bool $stream = false): array
    {
        $ch = curl_init($url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, $this->config['request_timeout']);
        curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        if ($response === false || !empty($error)) {
            return [
                'success' => false,
                'error' => "Client request failed: $error",
                'error_code' => 'CLIENT_REQUEST_FAILED'
            ];
        }

        if ($httpCode >= 400) {
            return [
                'success' => false,
                'error' => "Client returned HTTP $httpCode: $response",
                'error_code' => 'CLIENT_HTTP_ERROR',
                'http_code' => $httpCode
            ];
        }

        $decoded = json_decode($response, true);
        if (json_last_error() !== JSON_ERROR_NONE) {
            return [
                'success' => false,
                'error' => 'Invalid JSON response from client',
                'error_code' => 'INVALID_CLIENT_RESPONSE'
            ];
        }

        return [
            'success' => true,
            'data' => $decoded
        ];
    }

    /**
     * Health check for all clients
     */
    public function performHealthChecks(): array
    {
        $results = [];
        $clients = $this->clientManager->getAllClients();

        foreach ($clients as $clientInfo) {
            $client = $clientInfo['client'];
            $clientId = $client['client_id'];
            
            try {
                $healthResult = $this->checkClientHealth($client);
                $results[$clientId] = $healthResult;
                
                // Update client status based on health check
                $status = $healthResult['healthy'] ? 'active' : 'unhealthy';
                $this->clientManager->updateClientStatus($clientId, $status, [
                    'last_health_check' => gmdate('c'),
                    'health_details' => $healthResult
                ]);
                
            } catch (\Exception $e) {
                $results[$clientId] = [
                    'healthy' => false,
                    'error' => $e->getMessage(),
                    'checked_at' => gmdate('c')
                ];
                
                $this->clientManager->updateClientStatus($clientId, 'unhealthy', [
                    'last_health_check' => gmdate('c'),
                    'health_error' => $e->getMessage()
                ]);
            }
        }

        return $results;
    }

    /**
     * Check individual client health
     */
    private function checkClientHealth(array $client): array
    {
        $url = rtrim($client['lmarena_bridge_url'], '/') . '/health';
        
        $headers = [
            'User-Agent: LMArena-Gateway-Platform-HealthCheck/1.0',
            'X-Client-ID: ' . $client['client_id']
        ];

        $startTime = microtime(true);
        $result = $this->makeHttpRequest($url, [], $headers);
        $responseTime = (microtime(true) - $startTime) * 1000;

        return [
            'healthy' => $result['success'],
            'response_time_ms' => round($responseTime, 2),
            'details' => $result['data'] ?? null,
            'error' => $result['error'] ?? null,
            'checked_at' => gmdate('c')
        ];
    }

    /**
     * Generate unique request ID
     */
    private function generateRequestId(): string
    {
        return 'req_' . bin2hex(random_bytes(16));
    }

    /**
     * Get routing statistics
     */
    public function getRoutingStats(): array
    {
        $clients = $this->clientManager->getAllClients();
        $totalRequests = 0;
        $totalSuccessful = 0;
        $totalFailed = 0;
        $averageResponseTime = 0;

        foreach ($clients as $clientInfo) {
            $stats = $clientInfo['stats'];
            $totalRequests += $stats['total_requests'] ?? 0;
            $totalSuccessful += $stats['successful_requests'] ?? 0;
            $totalFailed += $stats['failed_requests'] ?? 0;
        }

        if ($totalRequests > 0) {
            $successRate = $totalSuccessful / $totalRequests;
            $failureRate = $totalFailed / $totalRequests;
        } else {
            $successRate = 0;
            $failureRate = 0;
        }

        return [
            'total_clients' => count($clients),
            'active_clients' => count(array_filter($clients, fn($c) => $c['client']['status'] === 'active')),
            'total_requests' => $totalRequests,
            'successful_requests' => $totalSuccessful,
            'failed_requests' => $totalFailed,
            'success_rate' => round($successRate * 100, 2),
            'failure_rate' => round($failureRate * 100, 2),
            'load_balancing_strategy' => $this->config['load_balancing_strategy']
        ];
    }
}
