<?php
$tenant = $_SERVER['HTTP_X_TENANT_ID'] ?? null;

if (!$tenant) {
    http_response_code(401);
    exit;
}

$host = $_ENV['DB_HOST'] ?? getenv('DB_HOST');
$username = $_ENV['DB_USERNAME'] ?? getenv('DB_USERNAME');
$password = $_ENV['DB_PASSWORD'] ?? getenv('DB_PASSWORD');

try {
    $registry = new PDO("mysql:host=$host;dbname=tenants_registry", $username, $password);
    $stmt = $registry->prepare("SELECT id FROM tenants WHERE subdomain = ? AND status = 'active'");
    $stmt->execute([$tenant]);

    if (!$stmt->fetch()) {
        http_response_code(401);
        exit;
    }

    http_response_code(200);
} catch (PDOException $e) {
    http_response_code(500);
}
exit;
