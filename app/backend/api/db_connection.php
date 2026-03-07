<?php
// api/db_connection.php

/**
 * Get a connection to the correct tenant schema.
 * DB credentials are injected as environment variables by ECS from Secrets Manager.
 *
 * @return PDO
 */
function getDatabaseConnection(): PDO {
    $host     = getenv('DB_HOST');
    $username = getenv('DB_USERNAME');
    $password = getenv('DB_PASSWORD');

    // Read tenant from header set by nginx
    $subdomain = $_SERVER['HTTP_X_TENANT_ID'] ?? null;

    if (!$subdomain) {
        http_response_code(404);
        die(json_encode(['success' => false, 'error' => 'No tenant specified']));
    }

    // Sanitize subdomain
    $subdomain = strtolower($subdomain);
    $subdomain = str_replace('-', '_', $subdomain);
    $subdomain = preg_replace('/[^a-z0-9_-]/', '', $subdomain);

    // Look up schema name from tenants registry
    $registry = new PDO(
        "mysql:host=$host;dbname=tenants_registry;charset=utf8",
        $username,
        $password
    );

    $stmt = $registry->prepare(
        "SELECT schema_name FROM tenants WHERE subdomain = ? AND status = 'active'"
    );
    $stmt->execute([$subdomain]);
    $row = $stmt->fetch();

    if (!$row) {
        http_response_code(404);
        die(json_encode(['success' => false, 'error' => 'Tenant not found']));
    }

    $options = [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ];

    return new PDO(
        "mysql:host=$host;dbname={$row['schema_name']};charset=utf8",
        $username,
        $password,
        $options
    );
}
?>
