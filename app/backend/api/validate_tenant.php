<?php
// api/validate_tenant.php
// Called internally by nginx auth_request before serving any frontend file.
// Returns 200 if tenant is valid and active, 401 otherwise.

$host     = getenv('DB_HOST');
$username = getenv('DB_USERNAME');
$password = getenv('DB_PASSWORD');

$subdomain = $_SERVER['HTTP_X_TENANT_ID'] ?? null;

if (!$subdomain) {
    http_response_code(401);
    exit;
}

$subdomain = strtolower($subdomain);
$subdomain = str_replace('-', '_', $subdomain);
$subdomain = preg_replace('/[^a-z0-9_-]/', '', $subdomain);

try {
    $registry = new PDO(
        "mysql:host=$host;dbname=tenants_registry;charset=utf8",
        $username,
        $password
    );
    $stmt = $registry->prepare(
        "SELECT id FROM tenants WHERE subdomain = ? AND status = 'active'"
    );
    $stmt->execute([$subdomain]);

    if ($stmt->fetch()) {
        http_response_code(200);
    } else {
        http_response_code(401);
    }
} catch (Exception $e) {
    http_response_code(500);
}
exit;
?>
