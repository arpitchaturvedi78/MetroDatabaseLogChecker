#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/tmp/sample_db_test"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/db1" "$WORKDIR/db2" "$WORKDIR/output"

# 1. Create DB 1
sqlite3 "$WORKDIR/db1/app.db" << 'SQL'
CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    level TEXT,
    message TEXT
);
INSERT INTO logs VALUES (1, '2026-11-10 10:00:00', 'INFO', 'System boot completed');
INSERT INTO logs VALUES (2, '2026-11-10 10:05:23', 'ERROR', 'Connection timed out to redis:6379');
INSERT INTO logs VALUES (3, '2026-11-10 10:15:00', 'WARN', 'High memory usage: 85%');

CREATE TABLE audit (
    audit_id INTEGER PRIMARY KEY,
    user TEXT,
    action TEXT,
    status TEXT
);
INSERT INTO audit VALUES (101, 'admin', 'login', 'SUCCESS');
INSERT INTO audit VALUES (102, 'guest', 'access_denied_resource', 'FAILED');
SQL

# 2. Create DB 2
sqlite3 "$WORKDIR/db2/app.db" << 'SQL'
CREATE TABLE event_logs (
    id INTEGER PRIMARY KEY,
    event_type TEXT,
    details TEXT
);
INSERT INTO event_logs VALUES (1, 'AUTH_FAILURE', 'User alice bad password attempt');
INSERT INTO event_logs VALUES (2, 'DB_QUERY', 'SELECT * FROM users executed in 12ms');
INSERT INTO event_logs VALUES (3, 'FATAL_ERROR', 'Out of memory exception in worker-2');
SQL

# Zip inner databases
(cd "$WORKDIR/db1" && zip -q "$WORKDIR/output/service_alpha_db.zip" app.db)
(cd "$WORKDIR/db2" && zip -q "$WORKDIR/output/service_beta_db.zip" app.db)

# Create master outer zip
(cd "$WORKDIR/output" && zip -q "/Users/arpitchaturvedi/.gemini/antigravity/scratch/db_log_checker/sample_databases_master.zip" service_alpha_db.zip service_beta_db.zip)

rm -rf "$WORKDIR"
echo "Created sample master zip at /Users/arpitchaturvedi/.gemini/antigravity/scratch/db_log_checker/sample_databases_master.zip"
