<?php
// php/scripts/test-gateway.php
// Simple test script to verify gateway functionality

require_once __DIR__ . '/../app/Config.php';
require_once __DIR__ . '/../app/SessionStore.php';

use GatewayApp\Config;
use GatewayApp\SessionStore;

function testSessionStore(): bool {
    echo "Testing SessionStore...\n";
    
    try {
        $store = new SessionStore();
        
        // Test setting a mapping
        $testPayload = [
            'session_id' => '12345678-1234-1234-1234-123456789abc',
            'message_id' => '87654321-4321-4321-4321-cba987654321',
            'bridge_base_url' => 'http://localhost:5102',
        ];
        
        $store->setMapping('lmarena.ai', 'test-session', $testPayload);
        echo "  ✅ Set test mapping\n";
        
        // Test getting the mapping
        $retrieved = $store->getMapping('lmarena.ai', 'test-session');
        if ($retrieved && $retrieved['session_id'] === $testPayload['session_id']) {
            echo "  ✅ Retrieved test mapping correctly\n";
        } else {
            echo "  ❌ Failed to retrieve test mapping\n";
            return false;
        }
        
        // Test stats
        $stats = $store->getStats();
        if ($stats['total_sessions'] >= 1) {
            echo "  ✅ Stats working (total sessions: {$stats['total_sessions']})\n";
        } else {
            echo "  ❌ Stats not working correctly\n";
            return false;
        }
        
        // Clean up test data
        $store->deleteMapping('lmarena.ai', 'test-session');
        echo "  ✅ Cleaned up test mapping\n";
        
        return true;
        
    } catch (Exception $e) {
        echo "  ❌ SessionStore test failed: " . $e->getMessage() . "\n";
        return false;
    }
}

function testConfig(): bool {
    echo "Testing Config...\n";
    
    try {
        $bridgeUrl = Config::defaultBridgeBaseUrl();
        if (filter_var($bridgeUrl, FILTER_VALIDATE_URL)) {
            echo "  ✅ Bridge URL valid: $bridgeUrl\n";
        } else {
            echo "  ❌ Bridge URL invalid: $bridgeUrl\n";
            return false;
        }
        
        $domains = Config::allowedDomains();
        if (is_array($domains) && in_array('lmarena.ai', $domains)) {
            echo "  ✅ Allowed domains configured (" . count($domains) . " domains)\n";
        } else {
            echo "  ❌ Allowed domains not configured correctly\n";
            return false;
        }
        
        return true;
        
    } catch (Exception $e) {
        echo "  ❌ Config test failed: " . $e->getMessage() . "\n";
        return false;
    }
}

function testStoragePermissions(): bool {
    echo "Testing storage permissions...\n";
    
    try {
        $storageFile = Config::storageFile();
        $storageDir = dirname($storageFile);
        
        if (!is_dir($storageDir)) {
            if (!@mkdir($storageDir, 0775, true)) {
                echo "  ❌ Cannot create storage directory: $storageDir\n";
                return false;
            }
        }
        
        if (!is_writable($storageDir)) {
            echo "  ❌ Storage directory not writable: $storageDir\n";
            return false;
        }
        
        echo "  ✅ Storage directory writable: $storageDir\n";
        
        // Test file creation
        $testFile = $storageDir . '/test-write.tmp';
        if (file_put_contents($testFile, 'test') !== false) {
            unlink($testFile);
            echo "  ✅ Can write to storage directory\n";
        } else {
            echo "  ❌ Cannot write to storage directory\n";
            return false;
        }
        
        return true;
        
    } catch (Exception $e) {
        echo "  ❌ Storage permissions test failed: " . $e->getMessage() . "\n";
        return false;
    }
}

function main(): void {
    echo "LMArena Gateway Test Suite\n";
    echo "=========================\n\n";
    
    $tests = [
        'Config' => 'testConfig',
        'Storage Permissions' => 'testStoragePermissions',
        'SessionStore' => 'testSessionStore',
    ];
    
    $passed = 0;
    $total = count($tests);
    
    foreach ($tests as $name => $function) {
        if ($function()) {
            $passed++;
        }
        echo "\n";
    }
    
    echo "Test Results: $passed/$total passed\n";
    
    if ($passed === $total) {
        echo "🎉 All tests passed! Gateway is ready for deployment.\n";
        exit(0);
    } else {
        echo "❌ Some tests failed. Please fix the issues before deployment.\n";
        exit(1);
    }
}

if (php_sapi_name() === 'cli') {
    main();
} else {
    echo "This script must be run from the command line.\n";
    exit(1);
}
