# Metro Database Log Checker

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/arpitchaturvedi78/MetroDatabaseLogChecker)
[![CI & Test Suite](https://github.com/arpitchaturvedi78/MetroDatabaseLogChecker/actions/workflows/ci.yml/badge.svg)](https://github.com/arpitchaturvedi78/MetroDatabaseLogChecker/actions/workflows/ci.yml)

A high-performance, zero-dependency tool and web application to recursively extract nested database archives (`.zip`, `.tar.gz`, `.tgz`), locate SQLite `app.db` / `.db` files, and scan every table for specific logs, pending upload transactions, and device diagnostics.

---

## 🚀 How to Run in GitHub (Quick Start)

### Option 1: One-Click Cloud Browser (GitHub Codespaces)

You can run this application entirely in your browser without installing anything locally:

1. Click the badge: [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/arpitchaturvedi78/MetroDatabaseLogChecker)
   *(Or click **`< > Code`** $\rightarrow$ **Codespaces** $\rightarrow$ **Create codespace on main**)*
2. GitHub automatically starts the container, launches the web app, and forwards port **8080**.
3. When prompted, click **"Open in Browser"** to access the web application!

---

### Option 2: Run with Docker / Docker Compose

If you or your team use Docker:

```bash
# Using Docker Compose (Single command):
docker compose up --build

# Or standard Docker:
docker build -t metro-db-log-checker .
docker run -p 8080:8080 metro-db-log-checker
```
Then open [http://localhost:8080](http://localhost:8080) in your browser.

---

### Option 3: Automated Testing & CI in GitHub Actions

The repository includes a GitHub Actions workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) that:
- Automatically validates CLI scripts on Ubuntu runners on every push and pull request.
- Can be manually triggered from the **Actions** tab in GitHub (**CI & Test Suite** $\rightarrow$ **Run workflow**).

---

### Option 4: Run Locally (macOS / Linux)

```bash
# 1. Clone repository
git clone https://github.com/arpitchaturvedi78/MetroDatabaseLogChecker.git
cd MetroDatabaseLogChecker

# 2. Start the Web App
./start_app.sh 8080
# Open http://localhost:8080 in your browser
```

---

## 🌟 Key Features

- **Nested Archive Decompression**: Recursively unpacks outer master archives containing multiple `.tar.gz`, `.tgz`, or `.zip` archives.
- **SQLite Database Auto-Discovery**: Locates SQLite databases via header magic (`b"SQLite format 3\x00"`), automatically skipping macOS resource fork files (`._*`, `__MACOSX/`).
- **Separate Condition Checks**: Evaluates `status = 4` and `cc_status = 'to_upload'` separately or combined with matched reason tagging.
- **Log Age (`created_at`) Filtering**: Defaults to showing records where `created_at` is older than 1 week (7 days) from the current date to immediately surface stale/stuck logs. Interactive pills allow toggling to `> 2 Weeks`, `> 1 Month`, or `All Dates`.
- **Default Table Selection**: Automatically detects and pre-selects `emv_transaction` whenever present in the database.
- **Device Serial Number Extraction & CSV Export**: Extracts the POS Device Serial Number from database archive filenames (e.g., `1640104014_2026-11-08...` $\rightarrow$ `1640104014`) and exports a dedicated deduplicated `device_serial_numbers.csv`.
- **Interactive Web UI**: Modern dark-theme responsive interface with live upload progress tracking, cascading database & table dropdowns, warning banners, search, and instant data export (CSV/JSON).
- **Zero External Dependencies**: Pure Python standard library (`sqlite3`, `tarfile`, `zipfile`, `http.server`, `urllib`).

---

## 📁 File Structure

| File | Description | Requirements |
|---|---|---|
| [`server.py`](server.py) | **Web Application Backend**. REST API for uploading archives, inspecting schemas, querying logs, and age filtering. | Python 3.8+ |
| [`static/index.html`](static/index.html) | **Web Application Frontend**. Single-page app with progress bar, cascading selectors, and export buttons. | Modern Browser |
| [`start_app.sh`](start_app.sh) | Launcher script for the Web App on port 8080 (or custom port). | Bash / Zsh |
| [`check_db_logs.sh`](check_db_logs.sh) | **Zero-dependency CLI script**. Native shell script for macOS/Linux using system `tar`, `unzip`, and `sqlite3`. | `bash`/`zsh`, `sqlite3`, `tar`, `unzip` |
| [`check_db_logs.py`](check_db_logs.py) | **Full-featured Python CLI script**. Standalone script supporting SQL WHERE, regex, and age filtering. | Python 3.8+ |
| [`create_sample_targz_zips.sh`](create_sample_targz_zips.sh) | Generates test master archive (`sample_master_with_targz.zip`) containing nested `.tar.gz` databases. | `sqlite3`, `tar`, `zip` |
| [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json) | Configuration for 1-click execution in **GitHub Codespaces**. | GitHub |
| [`Dockerfile`](Dockerfile) & [`docker-compose.yml`](docker-compose.yml) | Docker containerization for portability. | Docker |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | GitHub Actions CI workflow to run automated tests on GitHub. | GitHub Actions |

---

## 💻 Command Line Usage

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

# Export results to CSV or JSON (includes device_serial_no column):
python3 check_db_logs.py sample_master_with_targz.zip --csv matched_logs.csv
python3 check_db_logs.py sample_master_with_targz.zip --json matched_logs.json
```

---

## License

MIT License.
