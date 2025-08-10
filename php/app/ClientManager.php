<?php
// php/app/ClientManager.php
// Client management system for distributed LMArenaBridge architecture

namespace GatewayApp;

class ClientManager
{
    private string $clientsStoragePath;
    private array $clients = [];
    private array $clientStats = [];

    public function __construct(string $storagePath = '../storage/clients.json')
    {
        $this->clientsStoragePath = $storagePath;
        $this->loadClients();
    }

    /**
     * Load clients from storage
     */
    private function loadClients(): void
    {
        if (file_exists($this->clientsStoragePath)) {
            $data = json_decode(file_get_contents($this->clientsStoragePath), true);
            $this->clients = $data['clients'] ?? [];
            $this->clientStats = $data['stats'] ?? [];
        }
    }

    /**
     * Save clients to storage
     */
    private function saveClients(): void
    {
        $data = [
            'clients' => $this->clients,
            'stats' => $this->clientStats,
            'updated_at' => gmdate('c')
        ];
        
        $dir = dirname($this->clientsStoragePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        
        file_put_contents($this->clientsStoragePath, json_encode($data, JSON_PRETTY_PRINT));
    }

    /**
     * Register a new client
     */
    public function registerClient(array $clientData): array
    {
        $clientId = $this->generateClientId();
        $apiKey = $this->generateApiKey();
        
        $client = [
            'client_id' => $clientId,
            'api_key' => $apiKey,
            'name' => $clientData['name'] ?? 'Unnamed Client',
            'email' => $clientData['email'] ?? null,
            'lmarena_bridge_url' => $clientData['lmarena_bridge_url'] ?? 'http://127.0.0.1:5102',
            'status' => 'pending',
            'created_at' => gmdate('c'),
            'last_seen' => null,
            'capabilities' => $clientData['capabilities'] ?? ['chat', 'models'],
            'rate_limit' => [
                'requests_per_minute' => $clientData['rate_limit'] ?? 60,
                'requests_per_day' => $clientData['daily_limit'] ?? 1000
            ],
            'metadata' => $clientData['metadata'] ?? []
        ];

        $this->clients[$clientId] = $client;
        $this->clientStats[$clientId] = [
            'total_requests' => 0,
            'successful_requests' => 0,
            'failed_requests' => 0,
            'last_request_at' => null,
            'average_response_time' => 0,
            'health_status' => 'unknown'
        ];

        $this->saveClients();
        
        return [
            'client_id' => $clientId,
            'api_key' => $apiKey,
            'status' => 'registered',
            'lmarena_bridge_config' => $this->generateLMArenaBridgeConfig($clientId, $apiKey)
        ];
    }

    /**
     * Authenticate client by API key
     */
    public function authenticateClient(string $apiKey): ?array
    {
        foreach ($this->clients as $clientId => $client) {
            if ($client['api_key'] === $apiKey) {
                // Update last seen
                $this->clients[$clientId]['last_seen'] = gmdate('c');
                $this->saveClients();
                return $client;
            }
        }
        return null;
    }

    /**
     * Get client by ID
     */
    public function getClient(string $clientId): ?array
    {
        return $this->clients[$clientId] ?? null;
    }

    /**
     * Update client status
     */
    public function updateClientStatus(string $clientId, string $status, array $metadata = []): bool
    {
        if (!isset($this->clients[$clientId])) {
            return false;
        }

        $this->clients[$clientId]['status'] = $status;
        $this->clients[$clientId]['last_seen'] = gmdate('c');
        
        if (!empty($metadata)) {
            $this->clients[$clientId]['metadata'] = array_merge(
                $this->clients[$clientId]['metadata'],
                $metadata
            );
        }

        $this->saveClients();
        return true;
    }

    /**
     * Record client request statistics
     */
    public function recordRequest(string $clientId, bool $success, float $responseTime = 0): void
    {
        if (!isset($this->clientStats[$clientId])) {
            $this->clientStats[$clientId] = [
                'total_requests' => 0,
                'successful_requests' => 0,
                'failed_requests' => 0,
                'last_request_at' => null,
                'average_response_time' => 0,
                'health_status' => 'unknown'
            ];
        }

        $stats = &$this->clientStats[$clientId];
        $stats['total_requests']++;
        $stats['last_request_at'] = gmdate('c');

        if ($success) {
            $stats['successful_requests']++;
        } else {
            $stats['failed_requests']++;
        }

        // Update average response time
        if ($responseTime > 0) {
            $totalTime = $stats['average_response_time'] * ($stats['total_requests'] - 1);
            $stats['average_response_time'] = ($totalTime + $responseTime) / $stats['total_requests'];
        }

        // Update health status based on success rate
        $successRate = $stats['successful_requests'] / $stats['total_requests'];
        if ($successRate >= 0.95) {
            $stats['health_status'] = 'healthy';
        } elseif ($successRate >= 0.80) {
            $stats['health_status'] = 'degraded';
        } else {
            $stats['health_status'] = 'unhealthy';
        }

        $this->saveClients();
    }

    /**
     * Get available clients for request routing
     */
    public function getAvailableClients(array $capabilities = []): array
    {
        $available = [];
        
        foreach ($this->clients as $clientId => $client) {
            if ($client['status'] !== 'active') {
                continue;
            }

            // Check if client has required capabilities
            if (!empty($capabilities)) {
                $hasCapabilities = true;
                foreach ($capabilities as $capability) {
                    if (!in_array($capability, $client['capabilities'])) {
                        $hasCapabilities = false;
                        break;
                    }
                }
                if (!$hasCapabilities) {
                    continue;
                }
            }

            // Check if client is healthy
            $stats = $this->clientStats[$clientId] ?? [];
            if (($stats['health_status'] ?? 'unknown') === 'unhealthy') {
                continue;
            }

            $available[] = [
                'client_id' => $clientId,
                'client' => $client,
                'stats' => $stats,
                'load_score' => $this->calculateLoadScore($clientId)
            ];
        }

        // Sort by load score (lower is better)
        usort($available, fn($a, $b) => $a['load_score'] <=> $b['load_score']);

        return $available;
    }

    /**
     * Calculate load score for client selection
     */
    private function calculateLoadScore(string $clientId): float
    {
        $stats = $this->clientStats[$clientId] ?? [];
        
        // Base score from response time
        $responseTimeScore = ($stats['average_response_time'] ?? 1000) / 1000;
        
        // Penalty for recent failures
        $failureRate = $stats['failed_requests'] / max($stats['total_requests'], 1);
        $failurePenalty = $failureRate * 10;
        
        // Bonus for recent activity
        $lastRequest = $stats['last_request_at'] ?? null;
        $activityBonus = 0;
        if ($lastRequest) {
            $timeSinceLastRequest = time() - strtotime($lastRequest);
            $activityBonus = min($timeSinceLastRequest / 3600, 5); // Max 5 hour penalty
        }

        return $responseTimeScore + $failurePenalty + $activityBonus;
    }

    /**
     * Get all clients with statistics
     */
    public function getAllClients(): array
    {
        $result = [];
        foreach ($this->clients as $clientId => $client) {
            $result[] = [
                'client' => $client,
                'stats' => $this->clientStats[$clientId] ?? []
            ];
        }
        return $result;
    }

    /**
     * Generate unique client ID
     */
    private function generateClientId(): string
    {
        do {
            $clientId = 'client_' . bin2hex(random_bytes(8));
        } while (isset($this->clients[$clientId]));
        
        return $clientId;
    }

    /**
     * Generate secure API key
     */
    private function generateApiKey(): string
    {
        return 'lmbridge_' . bin2hex(random_bytes(32));
    }

    /**
     * Generate LMArenaBridge configuration for client
     */
    private function generateLMArenaBridgeConfig(string $clientId, string $apiKey): array
    {
        $platformUrl = $_SERVER['HTTP_HOST'] ?? 'your-domain.com';
        $isHttps = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') || 
                   (!empty($_SERVER['HTTP_X_FORWARDED_PROTO']) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https');
        $protocol = $isHttps ? 'https' : 'http';
        
        return [
            'platform_url' => "{$protocol}://{$platformUrl}/api",
            'client_id' => $clientId,
            'api_key' => $apiKey,
            'heartbeat_interval' => 30,
            'request_timeout' => 300,
            'retry_attempts' => 3,
            'capabilities' => ['chat', 'models', 'images'],
            'config_template' => [
                'version' => '2.0.0',
                'platform_integration' => [
                    'enabled' => true,
                    'platform_url' => "{$protocol}://{$platformUrl}/api",
                    'client_id' => $clientId,
                    'api_key' => $apiKey,
                    'heartbeat_interval_seconds' => 30
                ],
                'session_id' => 'YOUR_SESSION_ID_HERE',
                'message_id' => 'YOUR_MESSAGE_ID_HERE',
                'api_key' => null,
                'stream_response_timeout_seconds' => 300
            ]
        ];
    }

    /**
     * Check rate limits for client
     */
    public function checkRateLimit(string $clientId): array
    {
        $client = $this->clients[$clientId] ?? null;
        if (!$client) {
            return ['allowed' => false, 'reason' => 'Client not found'];
        }

        $stats = $this->clientStats[$clientId] ?? [];
        $rateLimit = $client['rate_limit'];
        
        // Check requests per minute
        $recentRequests = $this->getRecentRequestCount($clientId, 60);
        if ($recentRequests >= $rateLimit['requests_per_minute']) {
            return [
                'allowed' => false,
                'reason' => 'Rate limit exceeded (per minute)',
                'limit' => $rateLimit['requests_per_minute'],
                'current' => $recentRequests,
                'reset_in' => 60
            ];
        }

        // Check requests per day
        $dailyRequests = $this->getRecentRequestCount($clientId, 86400);
        if ($dailyRequests >= $rateLimit['requests_per_day']) {
            return [
                'allowed' => false,
                'reason' => 'Rate limit exceeded (per day)',
                'limit' => $rateLimit['requests_per_day'],
                'current' => $dailyRequests,
                'reset_in' => 86400
            ];
        }

        return [
            'allowed' => true,
            'remaining_minute' => $rateLimit['requests_per_minute'] - $recentRequests,
            'remaining_day' => $rateLimit['requests_per_day'] - $dailyRequests
        ];
    }

    /**
     * Get recent request count for rate limiting
     */
    private function getRecentRequestCount(string $clientId, int $seconds): int
    {
        // This is a simplified implementation
        // In production, you'd want to use a more sophisticated rate limiting system
        // like Redis with sliding window or token bucket algorithm
        
        $stats = $this->clientStats[$clientId] ?? [];
        $lastRequest = $stats['last_request_at'] ?? null;
        
        if (!$lastRequest) {
            return 0;
        }

        $timeSinceLastRequest = time() - strtotime($lastRequest);
        if ($timeSinceLastRequest > $seconds) {
            return 0;
        }

        // Simplified: assume even distribution of requests
        // This should be replaced with proper request logging
        return min($stats['total_requests'] ?? 0, 10);
    }
}
