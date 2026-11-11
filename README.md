<<<<<<< HEAD
# Database Log Checker

A high-performance, zero-dependency tool and web application to recursively extract nested database archives (`.zip`, `.tar.gz`, `.tgz`), locate SQLite `app.db` / `.db` files, and scan every table for specific logs, pending upload transactions, and device diagnostics.

---

## Key Features

- **Nested Archive Decompression**: Recursively unpacks outer master archives containing multiple `.tar.gz`, `.tgz`, or `.zip` archives.
- **SQLite Database Auto-Discovery**: Locates SQLite databases via header magic (`b"SQLite format 3\x00"`), automatically skipping macOS resource fork files (`._*`, `__MACOSX/`).
- **Separate Condition Checks**: Evaluates `status = 4` and `cc_status = 'to_upload'` separately or combined with matched reason tagging.
- **Log Age (`created_at`) Filtering**: Defaults to showing records where `created_at` is older than 1 week (7 days) from the current date to immediately surface stale/stuck logs. Interactive pills allow toggling to `> 2 Weeks`, `> 1 Month`, or `All Dates`.
- **Default Table Selection**: Automatically detects and pre-selects `emv_transaction` whenever present in the database.
- **Device Serial Number Extraction & CSV Export**: Extracts the POS Device Serial Number from database archive filenames (e.g., `1640104014_2026-11-08...` $\rightarrow$ `1640104014`) and exports a dedicated deduplicated `device_serial_numbers.csv`.
- **Interactive Web UI**: Modern dark-theme responsive interface with live upload progress tracking, cascading database & table dropdowns, warning banners, search, and instant data export (CSV/JSON).
- **Zero External Dependencies**: Pure Python standard library (`sqlite3`, `tarfile`, `zipfile`, `http.server`, `urllib`).

---

## File Structure

| File | Description | Requirements |
|---|---|---|
| [`server.py`](server.py) | **Web Application Backend**. REST API for uploading archives, inspecting schemas, querying logs, and age filtering. | Python 3.8+ |
| [`static/index.html`](static/index.html) | **Web Application Frontend**. Single-page app with progress bar, cascading selectors, and export buttons. | Modern Browser |
| [`start_app.sh`](start_app.sh) | Launcher script for the Web App on port 8080 (or custom port). | Bash / Zsh |
| [`check_db_logs.sh`](check_db_logs.sh) | **Zero-dependency CLI script**. Native shell script for macOS/Linux using system `tar`, `unzip`, and `sqlite3`. | `bash`/`zsh`, `sqlite3`, `tar`, `unzip` |
| [`check_db_logs.py`](check_db_logs.py) | **Full-featured Python CLI script**. Standalone script supporting SQL WHERE, regex, and age filtering. | Python 3.8+ |
| [`create_sample_targz_zips.sh`](create_sample_targz_zips.sh) | Generates test master archive (`sample_master_with_targz.zip`) containing nested `.tar.gz` databases. | `sqlite3`, `tar`, `zip` |

---

## Quick Start (Web Application)

1. **Launch the Web App**:
   ```bash
   ./start_app.sh 8080
   ```
2. **Open in Browser**:
   Navigate to [http://localhost:8080](http://localhost:8080).

3. **Usage**:
   - **Step 1**: Drag and drop your `.zip` or `.tar.gz` archive, or click **"Load Sample (.tar.gz databases)"**.
   - **Step 2**: The app automatically selects `emv_transaction` and filters for records with `status = 4` or `cc_status = 'to_upload'` with `created_at` older than 7 days.
   - **Step 3**: View matching records and click:
     - **Download CSV**: Full CSV of all matched rows with `device_serial_no` as the first column.
     - **Download JSON**: Full JSON array of matched records.
     - **📱 Download Device Serial No**: Dedicated CSV of unique device serial numbers with their database archive and match count.

---

## Command Line Usage

### 1. Using `check_db_logs.sh` (Shell)

```bash
# Default check: status = 4 OR cc_status = 'to_upload' (older than 7 days in created_at)
./check_db_logs.sh sample_master_with_targz.zip

# Target specific table:
./check_db_logs.sh sample_master_with_targz.zip -t emv_transaction

# Custom age threshold (e.g. older than 14 days, or 0 to disable age filter):
./check_db_logs.sh sample_master_with_targz.zip -d 14
./check_db_logs.sh sample_master_with_targz.zip -d 0

# Custom SQL WHERE condition:
./check_db_logs.sh sample_master_with_targz.zip -w "status = 4"
```

### 2. Using `check_db_logs.py` (Python)

```bash
# Default check on emv_transaction:
python3 check_db_logs.py sample_master_with_targz.zip -t emv_transaction

# Disable age filter (all dates):
python3 check_db_logs.py sample_master_with_targz.zip -t emv_transaction -d 0

# Export results to CSV or JSON:
python3 check_db_logs.py sample_master_with_targz.zip --csv matched_logs.csv
python3 check_db_logs.py sample_master_with_targz.zip --json matched_logs.json
```

---

## License

MIT License.
=======
# MetroDatabaseLogChecker
>>>>>>> 15e8e0bc1bf398e94d896435d9b2e47d03dd5cc4
