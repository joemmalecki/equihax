-- tenant_setup.sql
-- Runs against a newly created tenant schema to set up tables and seed data.

CREATE TABLE IF NOT EXISTS messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO messages (message) VALUES
('Hello from the database!'),
('Welcome to our three-tier architecture demo'),
('This is a simple example showing frontend, backend, and database');
