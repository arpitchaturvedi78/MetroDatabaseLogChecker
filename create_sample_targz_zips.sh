#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/tmp/sample_targz_test"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/pos_terminal_1" "$WORKDIR/pos_terminal_2" "$WORKDIR/output"

# 1. POS Terminal 1 app.db
sqlite3 "$WORKDIR/pos_terminal_1/app.db" << 'SQL'
CREATE TABLE emv_transaction (
    id INTEGER PRIMARY KEY,
    transaction_uuid TEXT,
    card_scheme TEXT,
    masked_pan TEXT,
    amount REAL,
    currency TEXT,
    status INTEGER,
    cc_status TEXT,
    auth_code TEXT,
    created_at TEXT,
    timestamp TEXT
);
INSERT INTO emv_transaction VALUES (
    1, 'tx-9012-a1', 'VISA', '411111******1111', 125.50, 'USD', 4, 'to_upload', 'AUTH8812', '2026-10-15 10:14:00', '2026-10-15 10:14:00'
);
INSERT INTO emv_transaction VALUES (
    2, 'tx-9012-a2', 'MASTERCARD', '550000******2222', 45.00, 'USD', 4, 'uploaded', 'AUTH7731', '2026-10-20 10:20:15', '2026-10-20 10:20:15'
);
INSERT INTO emv_transaction VALUES (
    3, 'tx-9012-a3', 'AMEX', '378282******0005', 310.00, 'USD', 1, 'to_upload', 'AUTH5540', '2026-10-25 10:25:30', '2026-10-25 10:25:30'
);
INSERT INTO emv_transaction VALUES (
    4, 'tx-9012-a4', 'VISA', '400000******4000', 12.99, 'USD', 2, 'completed', 'AUTH1102', '2026-11-10 10:30:00', '2026-11-10 10:30:00'
);
INSERT INTO emv_transaction VALUES (
    5, 'tx-9012-a5', 'VISA', '499999******9999', 55.00, 'USD', 4, 'to_upload', 'AUTH9901', '2026-11-10 16:00:00', '2026-11-10 16:00:00'
);

CREATE TABLE system_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO system_config VALUES ('terminal_id', 'TERM_NYC_001');
INSERT INTO system_config VALUES ('merchant_name', 'Flagship Store Manhattan');
SQL

# 2. POS Terminal 2 app.db
sqlite3 "$WORKDIR/pos_terminal_2/app.db" << 'SQL'
CREATE TABLE emv_transaction (
    id INTEGER PRIMARY KEY,
    transaction_uuid TEXT,
    card_scheme TEXT,
    masked_pan TEXT,
    amount REAL,
    currency TEXT,
    status INTEGER,
    cc_status TEXT,
    auth_code TEXT,
    created_at TEXT,
    timestamp TEXT
);
INSERT INTO emv_transaction VALUES (
    101, 'tx-8831-b1', 'VISA', '424242******4242', 88.00, 'EUR', 4, 'to_upload', 'AUTH9920', '2026-10-18 10:45:00', '2026-10-18 10:45:00'
);
INSERT INTO emv_transaction VALUES (
    102, 'tx-8831-b2', 'DISCOVER', '601100******1111', 15.75, 'USD', 4, 'pending', 'AUTH3319', '2026-11-09 10:50:00', '2026-11-09 10:50:00'
);
INSERT INTO emv_transaction VALUES (
    103, 'tx-8831-b3', 'RUPAY', '817400******3333', 95.00, 'INR', 0, 'to_upload', 'AUTH4412', '2026-09-28 14:10:00', '2026-09-28 14:10:00'
);

CREATE TABLE batch_summary (
    batch_id INTEGER PRIMARY KEY,
    total_count INTEGER,
    batch_status TEXT
);
INSERT INTO batch_summary VALUES (1, 150, 'OPEN');
SQL

# Create .tar.gz archives
tar -czf "$WORKDIR/output/terminal_nyc_001.tar.gz" -C "$WORKDIR/pos_terminal_1" app.db
tar -czf "$WORKDIR/output/terminal_nyc_002.tar.gz" -C "$WORKDIR/pos_terminal_2" app.db

# Create master zip containing the .tar.gz files
MASTER_TARGET="/Users/arpitchaturvedi/.gemini/antigravity/scratch/db_log_checker/sample_master_with_targz.zip"
(cd "$WORKDIR/output" && zip -q "$MASTER_TARGET" terminal_nyc_001.tar.gz terminal_nyc_002.tar.gz)

rm -rf "$WORKDIR"
echo "Created sample master zip with emv_transaction at: $MASTER_TARGET"
