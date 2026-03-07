-- registry_setup.sql
-- Creates the tenants_registry database and tenants table on a fresh RDS instance.
-- Run once per environment immediately after CDK deploy.

CREATE DATABASE IF NOT EXISTS tenants_registry;

CREATE TABLE IF NOT EXISTS tenants_registry.tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    schema_name VARCHAR(100) NOT NULL UNIQUE,
    subdomain VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    tier VARCHAR(50) NOT NULL DEFAULT 'free',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
