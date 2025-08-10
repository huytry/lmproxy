<?php
// php/scripts/cleanup-sessions.php
// Maintenance script to clean up old session mappings

require_once __DIR__ . '/../app/Config.php';
require_once __DIR__ . '/../app/SessionStore.php';

use GatewayApp\Config;
use GatewayApp\SessionStore;

function main(): void {
    $daysOld = (int)($argv[1] ?? 30);
    
    if ($daysOld < 1) {
        echo "Usage: php cleanup-sessions.php [days_old]\n";
        echo "Example: php cleanup-sessions.php 30\n";
        exit(1);
    }
    
    try {
        $store = new SessionStore();
        
        echo "Cleaning up sessions older than $daysOld days...\n";
        $cleaned = $store->cleanupOldSessions($daysOld);
        
        if ($cleaned > 0) {
            echo "✅ Cleaned up $cleaned old session(s).\n";
        } else {
            echo "ℹ️  No old sessions found to clean up.\n";
        }
        
        // Show current stats
        $stats = $store->getStats();
        echo "\nCurrent storage stats:\n";
        echo "  Total domains: {$stats['total_domains']}\n";
        echo "  Total sessions: {$stats['total_sessions']}\n";
        
        if (!empty($stats['domains'])) {
            echo "  Sessions per domain:\n";
            foreach ($stats['domains'] as $domain => $count) {
                echo "    $domain: $count\n";
            }
        }
        
    } catch (Exception $e) {
        echo "❌ Error: " . $e->getMessage() . "\n";
        exit(1);
    }
}

if (php_sapi_name() === 'cli') {
    main();
} else {
    echo "This script must be run from the command line.\n";
    exit(1);
}
