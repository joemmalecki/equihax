<?php
// api/db_connection.php
/**
 * Get database connection
 * 
 * @return PDO
 */
function getDatabaseConnection() {
    $host = $_ENV['DB_HOST'] ?? getenv('DB_HOST');
    $username = $_ENV['DB_USERNAME'] ?? getenv('DB_USERNAME');
    $password = $_ENV['DB_PASSWORD'] ?? getenv('DB_PASSWORD');

    $tenant = $_SERVER['HTTP_X_TENANT_ID'] ?? null;

    if (!$tenant) {
      http_response_code(404);
      die('Not found');
    }
    
    $tenant = preg_replace('/[^a-z0-9_-]/', '', strtolower($tenant));

    // 4. Validate against your tenants registry
    $registry = new PDO("mysql:host=$host;dbname=tenants_registry", $username, $password);
    $stmt = $registry->prepare("SELECT schema_name FROM tenants WHERE subdomain = ? AND status = 'active'");
    $stmt->execute([$tenant]);
    $row = $stmt->fetch();
    
    if (!$row) {
        http_response_code(404);
        die('Not found');
    }

    $options = [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ];
    
    return new PDO("mysql:host=$host;dbname={$row['schema_name']}", $username, $password, $options);
}
?>
