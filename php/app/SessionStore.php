<?php
// php/app/SessionStore.php
// File-backed session name/ID mapping with domain isolation and concurrency safety

namespace GatewayApp;

class SessionStore
{
    private string $path;
    private int $maxRetries = 3;
    private int $lockTimeout = 10; // seconds

    public function __construct(?string $path = null)
    {
        $this->path = $path ?: Config::storageFile();
        $this->initializeStorage();
    }

    private function initializeStorage(): void
    {
        if (!file_exists($this->path)) {
            $dir = dirname($this->path);
            if (!is_dir($dir)) {
                if (!@mkdir($dir, 0775, true)) {
                    throw new \RuntimeException("Cannot create storage directory: $dir");
                }
            }

            $initialData = ["domains" => new \stdClass(), "created_at" => gmdate('c')];
            if (file_put_contents($this->path, json_encode($initialData, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)) === false) {
                throw new \RuntimeException("Cannot create storage file: {$this->path}");
            }
        }

        if (!is_readable($this->path) || !is_writable($this->path)) {
            throw new \RuntimeException("Storage file not accessible: {$this->path}");
        }
    }

    private function readAll(): array
    {
        for ($attempt = 0; $attempt < $this->maxRetries; $attempt++) {
            $fh = fopen($this->path, 'c+');
            if (!$fh) {
                if ($attempt === $this->maxRetries - 1) {
                    throw new \RuntimeException("Cannot open storage file for reading");
                }
                usleep(100000); // 100ms
                continue;
            }

            if (flock($fh, LOCK_SH | LOCK_NB)) {
                $json = stream_get_contents($fh);
                flock($fh, LOCK_UN);
                fclose($fh);

                $data = json_decode($json ?: '{}', true);
                if (json_last_error() !== JSON_ERROR_NONE) {
                    throw new \RuntimeException("Storage file corrupted: " . json_last_error_msg());
                }

                if (!is_array($data)) $data = [];
                $data['domains'] = $data['domains'] ?? [];
                return $data;
            }

            fclose($fh);
            if ($attempt === $this->maxRetries - 1) {
                throw new \RuntimeException("Cannot acquire read lock on storage file");
            }
            usleep(100000); // 100ms
        }

        return ["domains" => []]; // fallback
    }

    private function writeAll(array $data): void
    {
        for ($attempt = 0; $attempt < $this->maxRetries; $attempt++) {
            $fh = fopen($this->path, 'c+');
            if (!$fh) {
                if ($attempt === $this->maxRetries - 1) {
                    throw new \RuntimeException('Cannot open storage file for writing');
                }
                usleep(100000); // 100ms
                continue;
            }

            if (flock($fh, LOCK_EX | LOCK_NB)) {
                ftruncate($fh, 0);
                rewind($fh);
                $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
                if ($json === false) {
                    flock($fh, LOCK_UN);
                    fclose($fh);
                    throw new \RuntimeException('Cannot encode data to JSON');
                }

                if (fwrite($fh, $json) === false) {
                    flock($fh, LOCK_UN);
                    fclose($fh);
                    throw new \RuntimeException('Cannot write to storage file');
                }

                fflush($fh);
                flock($fh, LOCK_UN);
                fclose($fh);
                return;
            }

            fclose($fh);
            if ($attempt === $this->maxRetries - 1) {
                throw new \RuntimeException('Cannot acquire write lock on storage file');
            }
            usleep(100000); // 100ms
        }
    }

    // Upsert a mapping: domain + sessionName -> {session_id, message_id, bridge_base_url}
    public function setMapping(string $domain, string $sessionName, array $payload): void
    {
        $this->validatePayload($payload);

        $all = $this->readAll();
        if (!isset($all['domains'][$domain])) $all['domains'][$domain] = [];
        $all['domains'][$domain][$sessionName] = [
            'session_id' => $payload['session_id'] ?? null,
            'message_id' => $payload['message_id'] ?? null,
            'bridge_base_url' => $payload['bridge_base_url'] ?? null,
            'bridge_api_key' => $payload['bridge_api_key'] ?? null,
            'models' => $payload['models'] ?? null, // optional override for model mapping
            'updated_at' => gmdate('c'),
            'created_at' => $all['domains'][$domain][$sessionName]['created_at'] ?? gmdate('c'),
        ];
        $this->writeAll($all);
    }

    public function getMapping(string $domain, string $sessionName): ?array
    {
        $all = $this->readAll();
        if (!isset($all['domains'][$domain])) return null;
        return $all['domains'][$domain][$sessionName] ?? null;
    }

    public function deleteMapping(string $domain, string $sessionName): bool
    {
        $all = $this->readAll();
        if (!isset($all['domains'][$domain][$sessionName])) return false;

        unset($all['domains'][$domain][$sessionName]);
        if (empty($all['domains'][$domain])) {
            unset($all['domains'][$domain]);
        }

        $this->writeAll($all);
        return true;
    }

    // Enumerate sessions per domain for diagnostics
    public function listSessions(?string $domain = null): array
    {
        $all = $this->readAll();
        if ($domain === null) return $all['domains'];
        return $all['domains'][$domain] ?? [];
    }

    // Clean up sessions older than specified days
    public function cleanupOldSessions(int $daysOld = 30): int
    {
        $cutoff = gmdate('c', time() - ($daysOld * 24 * 3600));
        $all = $this->readAll();
        $cleaned = 0;

        foreach ($all['domains'] as $domain => &$sessions) {
            foreach ($sessions as $sessionName => $data) {
                $updatedAt = $data['updated_at'] ?? '1970-01-01T00:00:00Z';
                if ($updatedAt < $cutoff) {
                    unset($sessions[$sessionName]);
                    $cleaned++;
                }
            }
            if (empty($sessions)) {
                unset($all['domains'][$domain]);
            }
        }

        if ($cleaned > 0) {
            $this->writeAll($all);
        }

        return $cleaned;
    }

    private function validatePayload(array $payload): void
    {
        if (empty($payload['session_id']) || empty($payload['message_id'])) {
            throw new \InvalidArgumentException('session_id and message_id are required');
        }

        if (!preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/', $payload['session_id'])) {
            throw new \InvalidArgumentException('session_id must be a valid UUID');
        }

        if (!preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/', $payload['message_id'])) {
            throw new \InvalidArgumentException('message_id must be a valid UUID');
        }

        if (!empty($payload['bridge_base_url']) && !filter_var($payload['bridge_base_url'], FILTER_VALIDATE_URL)) {
            throw new \InvalidArgumentException('bridge_base_url must be a valid URL');
        }
    }

    public function getStats(): array
    {
        $all = $this->readAll();
        $stats = [
            'total_domains' => count($all['domains']),
            'total_sessions' => 0,
            'domains' => [],
        ];

        foreach ($all['domains'] as $domain => $sessions) {
            $sessionCount = count($sessions);
            $stats['total_sessions'] += $sessionCount;
            $stats['domains'][$domain] = $sessionCount;
        }

        return $stats;
    }
}

