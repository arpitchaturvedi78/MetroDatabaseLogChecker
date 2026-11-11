#!/usr/bin/env python3
"""
server.py
=========
Backend Web Server for Database Log Checker.
Runs on Python standard library only (no pip dependencies required).
"""

import datetime
import email
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SAMPLE_MASTER_ZIP = BASE_DIR / "sample_databases_master.zip"
SAMPLE_TARGZ_MASTER_ZIP = BASE_DIR / "sample_master_with_targz.zip"
SESSIONS_DIR = Path(tempfile.gettempdir()) / "db_log_checker_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".tar",
    ".gz",
)


def is_supported_archive(path: Path) -> bool:
    """Check if file matches supported archive extensions, skipping macOS metadata junk."""
    if path.name.startswith("._") or "__MACOSX" in path.parts:
        return False
    name = path.name.lower()
    return any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def is_sqlite_database(path: Path) -> bool:
    """Check if file is a valid SQLite 3 database (by header magic or verified SQLite open)."""
    if not path.is_file() or path.name.startswith("._") or "__MACOSX" in path.parts:
        return False
    # Check SQLite 3 file header: first 16 bytes are b"SQLite format 3\x00"
    try:
        if path.stat().st_size >= 100:
            with open(path, "rb") as f:
                header = f.read(16)
                if header == b"SQLite format 3\x00":
                    return True
    except Exception:
        pass

    # Fallback to extension check with connection validation
    name_lower = path.name.lower()
    if name_lower.startswith("._") or "__macosx" in name_lower:
        return False
    if name_lower.endswith((".db", ".sqlite", ".sqlite3", ".db3")) or "app.db" in name_lower:
        try:
            conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            conn.execute("SELECT 1;")
            conn.close()
            return True
        except Exception:
            return False
    return False


def unpack_archive(archive_path: Path, target_dir: Path) -> bool:
    """
    Safely unpack an archive (.zip, .tar.gz, .tgz, .tar, .gz, etc.) into target_dir.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()

    # 1. Try zipfile
    if zipfile.is_zipfile(archive_path):
        try:
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(target_dir)
            return True
        except Exception:
            pass

    # 2. Try tarfile
    if tarfile.is_tarfile(archive_path) or any(name.endswith(ext) for ext in (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")):
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                try:
                    tar.extractall(path=target_dir, filter="data")
                except TypeError:
                    tar.extractall(path=target_dir)
            return True
        except Exception as e:
            print(f"tarfile extraction failed for {archive_path.name}: {e}")

    # 3. Fallback: single gzipped file
    if name.endswith(".gz"):
        try:
            import gzip
            out_file = target_dir / archive_path.stem
            with gzip.open(archive_path, "rb") as f_in, open(out_file, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            if tarfile.is_tarfile(out_file) or out_file.name.endswith(".tar"):
                with tarfile.open(out_file, "r:*") as tar:
                    try:
                        tar.extractall(path=target_dir, filter="data")
                    except TypeError:
                        tar.extractall(path=target_dir)
                out_file.unlink()
            return True
        except Exception as e:
            print(f"gzip fallback failed: {e}")

    return False

SAFE_BUILTINS = {
    "str": str,
    "int": int,
    "float": float,
    "len": len,
    "bool": bool,
    "dict": dict,
    "list": list,
    "set": set,
    "min": min,
    "max": max,
    "abs": abs,
    "True": True,
    "False": False,
    "None": None,
}

# In-memory session registry: session_id -> { "dir": Path, "metadata": Dict }
SESSIONS: Dict[str, Dict[str, Any]] = {}


def inspect_session_databases(session_dir: Path) -> Dict[str, Any]:
    """
    Unpack uploaded archive (.zip, .tar.gz, .tgz, .tar, etc.) in session_dir,
    recursively unpack any nested archives, discover all SQLite databases,
    and inspect schemas (tables, columns, types, row counts).
    """
    master_extract = session_dir / "master_extract"
    master_extract.mkdir(parents=True, exist_ok=True)

    # Find the uploaded file in session_dir
    uploaded_files = [
        f for f in session_dir.iterdir()
        if f.is_file() and (is_supported_archive(f) or is_sqlite_database(f))
    ]
    if not uploaded_files:
        raise ValueError("No valid archive (.zip, .tar.gz, .tgz) or database found in upload.")

    main_file = uploaded_files[0]

    # If user directly uploaded an uncompressed SQLite database file
    if is_sqlite_database(main_file):
        meta = get_db_metadata(main_file, main_file.name)
        return {
            "filename": main_file.name,
            "database_count": 1,
            "databases": [meta],
        }

    # Extract the uploaded archive (.zip, .tar.gz, .tar, etc.)
    if not unpack_archive(main_file, master_extract):
        raise ValueError(f"Failed to extract uploaded archive '{main_file.name}'.")

    # Recursively unpack any nested archives (.tar.gz, .tgz, .zip, etc.)
    processed_archives = set()
    while True:
        nested_archives = [
            f for f in master_extract.rglob("*")
            if f.is_file() and is_supported_archive(f) and f not in processed_archives
        ]
        if not nested_archives:
            break
        for arch in nested_archives:
            processed_archives.add(arch)
            sub_extract = arch.parent / f"_unpacked_{arch.name}"
            unpack_archive(arch, sub_extract)

    # Now discover ALL SQLite databases across all unpacked folders
    discovered_dbs = []
    seen_paths = set()
    for f in master_extract.rglob("*"):
        if f.is_file() and is_sqlite_database(f) and f.resolve() not in seen_paths:
            seen_paths.add(f.resolve())
            discovered_dbs.append(f)

    # Prioritize databases named app.db, then *.db, then others
    discovered_dbs.sort(
        key=lambda p: (
            0 if p.name.lower() == "app.db" else (1 if p.name.lower().endswith(".db") else 2),
            p.name.lower(),
        )
    )

    databases_meta = []
    for db_path in discovered_dbs:
        rel = db_path.relative_to(master_extract)
        archive_name = main_file.name
        for part in reversed(rel.parts):
            if part.startswith("_unpacked_"):
                archive_name = part[len("_unpacked_"):]
                break

        label = archive_name if db_path.name.lower() == "app.db" else f"{archive_name} [{db_path.name}]"
        try:
            meta = get_db_metadata(db_path, label)
            databases_meta.append(meta)
        except Exception as e:
            print(f"Error reading database {db_path}: {e}")

    return {
        "filename": main_file.name,
        "database_count": len(databases_meta),
        "databases": databases_meta,
    }


def get_db_metadata(db_file: Path, db_label: str) -> Dict[str, Any]:
    """Retrieve tables, columns, and row counts from SQLite database."""
    conn = sqlite3.connect(f"file:{db_file.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables_info = []
    try:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
        tables = [row["name"] for row in cursor.fetchall()]

        for table in tables:
            cursor.execute(f'PRAGMA table_info("{table}");')
            cols = [
                {
                    "cid": r["cid"],
                    "name": r["name"],
                    "type": r["type"] or "TEXT",
                    "pk": bool(r["pk"]),
                }
                for r in cursor.fetchall()
            ]

            try:
                cursor.execute(f'SELECT count(*) AS cnt FROM "{table}";')
                count = cursor.fetchone()["cnt"]
            except Exception:
                count = 0

            tables_info.append(
                {
                    "name": table,
                    "row_count": count,
                    "columns": cols,
                }
            )
    finally:
        conn.close()

    return {
        "name": db_label,
        "path": str(db_file.resolve()),
        "tables": tables_info,
    }


def is_value_older_than(val: Any, threshold: datetime.datetime) -> bool:
    """Check if a timestamp or date string/epoch is older than the threshold datetime."""
    if val is None or val == "":
        return False
    # 1. Numeric epoch timestamps (seconds or milliseconds)
    try:
        num = float(val)
        if num > 1e11:  # milliseconds
            num /= 1000.0
        if 1e8 < num < 3e10:
            return datetime.datetime.fromtimestamp(num) < threshold
    except (ValueError, TypeError, OverflowError):
        pass

    # 2. String datetimes
    s = str(val).strip().replace("T", " ").replace("Z", "")
    if "+" in s:
        s = s.split("+")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(s[:19] if fmt == "%Y-%m-%d %H:%M:%S" and len(s) >= 19 else s, fmt)
            return dt < threshold
        except (ValueError, TypeError):
            pass

    # 3. Lexicographical comparison for ISO strings (YYYY-MM-DD...)
    t_str = threshold.strftime("%Y-%m-%d %H:%M:%S")
    if len(s) >= 10 and s[:4].isdigit() and s[4] == "-":
        return s < t_str
    return False


def execute_database_query(
    session_data: Dict[str, Any],
    db_name: str,
    table_name: str,
    filter_type: str = "all",
    limit: int = 500,
    older_than_days: Optional[int] = 7,
) -> Dict[str, Any]:
    """
    Search / filter database records checking status = 4 and cc_status = 'to_upload'
    separately or combined, and optionally filtering for records where created_at
    is older than a given number of days from current date (default: 7 days = 1 week).
    """
    start_time = time.time()
    databases = session_data["metadata"]["databases"]

    # Threshold for age filter
    threshold_dt = None
    threshold_str = None
    threshold_epoch = None
    threshold_epoch_ms = None
    if older_than_days is not None and older_than_days > 0:
        threshold_dt = datetime.datetime.now() - datetime.timedelta(days=older_than_days)
        threshold_str = threshold_dt.strftime("%Y-%m-%d %H:%M:%S")
        threshold_epoch = threshold_dt.timestamp()
        threshold_epoch_ms = threshold_epoch * 1000.0

    # Filter target databases
    target_dbs = (
        databases
        if db_name in ("__all__", "", None)
        else [d for d in databases if d["name"] == db_name]
    )

    all_matched_records = []
    warnings = []
    tables_scanned = 0

    for db_info in target_dbs:
        db_file = db_info["path"]
        if not os.path.exists(db_file):
            continue

        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            target_tables = [
                t
                for t in db_info["tables"]
                if table_name in ("__all__", "", None) or t["name"] == table_name
            ]

            for t_meta in target_tables:
                tables_scanned += 1
                t_name = t_meta["name"]
                cols = t_meta["columns"]
                col_lookup = {c["name"].lower(): c["name"] for c in cols}

                status_col = col_lookup.get("status")
                cc_status_col = col_lookup.get("cc_status")
                created_at_col = col_lookup.get("created_at") or col_lookup.get("createdat") or col_lookup.get("timestamp")

                # If age filter is requested, verify table has a date column
                if threshold_dt is not None:
                    if not created_at_col:
                        if table_name not in ("__all__", "", None):
                            warnings.append(
                                f"Table '{t_name}' in {db_info['name']} has no 'created_at' column to filter by age (> {older_than_days} days)."
                            )
                        continue

                status_sql = f'("{status_col}" = 4 OR "{status_col}" = \'4\')' if status_col else None
                cc_sql = f'(LOWER("{cc_status_col}") = \'to_upload\' OR "{cc_status_col}" = \'to_upload\')' if cc_status_col else None

                where_clause = None

                if filter_type == "both":
                    if status_sql and cc_sql:
                        where_clause = f"{status_sql} AND {cc_sql}"
                    else:
                        if table_name not in ("__all__", "", None):
                            warnings.append(
                                f"Table '{t_name}' in {db_info['name']} requires both 'status' and 'cc_status' columns to match 'Both'."
                            )
                        continue
                elif filter_type == "status_4":
                    if status_sql:
                        where_clause = status_sql
                    else:
                        any_clauses = [f'("{c["name"]}" = 4 OR "{c["name"]}" = \'4\')' for c in cols if c["name"].lower() not in ("created_at", "timestamp")]
                        if any_clauses:
                            where_clause = " OR ".join(any_clauses)
                elif filter_type == "cc_to_upload":
                    if cc_sql:
                        where_clause = cc_sql
                    else:
                        any_clauses = [f'(LOWER("{c["name"]}") = \'to_upload\' OR "{c["name"]}" = \'to_upload\')' for c in cols if c["name"].lower() not in ("created_at", "timestamp")]
                        if any_clauses:
                            where_clause = " OR ".join(any_clauses)
                else:  # 'all' - check separately!
                    clauses = []
                    if status_sql:
                        clauses.append(status_sql)
                    if cc_sql:
                        clauses.append(cc_sql)
                    if not clauses:
                        for c in cols:
                            if c["name"].lower() not in ("created_at", "timestamp"):
                                clauses.append(f'("{c["name"]}" = 4 OR "{c["name"]}" = \'4\' OR LOWER("{c["name"]}") = \'to_upload\')')
                    where_clause = " OR ".join(clauses)

                if not where_clause:
                    continue

                # Append age condition on created_at column
                if threshold_dt is not None and created_at_col:
                    date_sql = f"""(
                        (datetime("{created_at_col}") IS NOT NULL AND datetime("{created_at_col}") < datetime('{threshold_str}'))
                        OR ("{created_at_col}" < '{threshold_str}')
                        OR (CAST("{created_at_col}" AS REAL) > 100000000 AND (
                            CAST("{created_at_col}" AS REAL) < {threshold_epoch} OR
                            (CAST("{created_at_col}" AS REAL) < {threshold_epoch_ms} AND CAST("{created_at_col}" AS REAL) > 100000000000)
                        ))
                    )"""
                    where_clause = f"({where_clause}) AND {date_sql}"

                sql = f'SELECT * FROM "{t_name}" WHERE {where_clause} LIMIT {limit};'

                try:
                    cursor.execute(sql)
                    for r in cursor:
                        row_dict = dict(r)

                        # Precise age check in Python
                        if threshold_dt is not None and created_at_col:
                            val = row_dict.get(created_at_col)
                            if not is_value_older_than(val, threshold_dt):
                                continue

                        reasons = []

                        # Check status
                        if status_col and str(row_dict.get(status_col, "")).strip() in ("4", "4.0"):
                            reasons.append("status = 4")
                        # Check cc_status
                        if cc_status_col and str(row_dict.get(cc_status_col, "")).strip().lower() == "to_upload":
                            reasons.append("cc_status = 'to_upload'")

                        # Check any other column
                        for k, v in row_dict.items():
                            if k not in (status_col, cc_status_col, created_at_col):
                                v_str = str(v).strip()
                                if v_str in ("4", "4.0"):
                                    reasons.append(f"{k} = 4")
                                elif v_str.lower() == "to_upload":
                                    reasons.append(f"{k} = 'to_upload'")

                        reason_label = " & ".join(reasons) if reasons else "Matched"

                        all_matched_records.append(
                            {
                                "database": db_info["name"],
                                "table": t_name,
                                "match_reason": reason_label,
                                "row": row_dict,
                            }
                        )
                        if len(all_matched_records) >= limit:
                            break
                except sqlite3.OperationalError as e:
                    warnings.append(f"Query error on '{t_name}': {e}")

                if len(all_matched_records) >= limit:
                    break

        finally:
            conn.close()

        if len(all_matched_records) >= limit:
            break

    duration_ms = round((time.time() - start_time) * 1000, 2)
    return {
        "filter": f"Separate check (status = 4 / cc_status = 'to_upload') [Mode: {filter_type}]",
        "tables_scanned": tables_scanned,
        "total_matches": len(all_matched_records),
        "execution_time_ms": duration_ms,
        "older_than_days": older_than_days,
        "threshold_date": threshold_str if threshold_dt else None,
        "results": all_matched_records,
        "warnings": warnings,
    }




class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_json(self, data: Any, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            index_path = STATIC_DIR / "index.html"
            if index_path.exists():
                with open(index_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        # 1. Direct Binary Zip Upload
        if parsed.path == "/api/upload":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length <= 0:
                    self.end_json({"error": "Empty upload body"}, 400)
                    return

                content_type = self.headers.get("Content-Type", "")
                raw_filename = unquote(self.headers.get("X-Filename", "uploaded_databases.zip"))

                session_id = str(uuid.uuid4())[:8]
                session_dir = SESSIONS_DIR / session_id
                session_dir.mkdir(parents=True, exist_ok=True)

                # Check if multipart form data
                if "multipart/form-data" in content_type:
                    boundary = content_type.split("boundary=")[-1].strip()
                    # Parse multipart body
                    raw_data = self.rfile.read(content_length)
                    # Use email message parser
                    msg_bytes = (
                        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
                        + raw_data
                    )
                    msg = email.message_from_bytes(msg_bytes)
                    saved = False
                    for part in msg.walk():
                        if part.get_filename():
                            raw_filename = part.get_filename()
                            zip_path = session_dir / raw_filename
                            with open(zip_path, "wb") as f:
                                f.write(part.get_payload(decode=True))
                            saved = True
                            break
                    if not saved:
                        self.end_json({"error": "No file payload found in form"}, 400)
                        return
                else:
                    # Direct binary stream
                    zip_path = session_dir / raw_filename
                    with open(zip_path, "wb") as f:
                        remaining = content_length
                        while remaining > 0:
                            chunk = self.rfile.read(min(remaining, 65536))
                            if not chunk:
                                break
                            f.write(chunk)
                            remaining -= len(chunk)

                # Inspect database schemas inside zip
                meta = inspect_session_databases(session_dir)
                SESSIONS[session_id] = {
                    "dir": session_dir,
                    "metadata": meta,
                }

                self.end_json(
                    {
                        "session_id": session_id,
                        "metadata": meta,
                    }
                )
            except Exception as e:
                self.end_json({"error": f"Failed to process zip file: {str(e)}"}, 500)
            return

        # 2. Load Sample Zip
        if parsed.path == "/api/load-sample":
            try:
                query_params = parse_qs(parsed.query)
                sample_type = query_params.get("type", [""])[0]

                sample_file = SAMPLE_TARGZ_MASTER_ZIP if sample_type == "targz" else SAMPLE_MASTER_ZIP
                if not sample_file.exists():
                    sample_file = SAMPLE_MASTER_ZIP

                if not sample_file.exists():
                    self.end_json({"error": "Sample zip not found on server"}, 404)
                    return

                session_id = f"sample_{str(uuid.uuid4())[:6]}"
                session_dir = SESSIONS_DIR / session_id
                session_dir.mkdir(parents=True, exist_ok=True)

                dest_zip = session_dir / sample_file.name
                shutil.copyfile(sample_file, dest_zip)

                meta = inspect_session_databases(session_dir)
                SESSIONS[session_id] = {
                    "dir": session_dir,
                    "metadata": meta,
                }

                self.end_json(
                    {
                        "session_id": session_id,
                        "metadata": meta,
                    }
                )
            except Exception as e:
                self.end_json({"error": f"Failed to load sample zip: {str(e)}"}, 500)
            return

        # 3. Query Database Logs
        if parsed.path == "/api/query":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_length)
                params = json.loads(raw_body.decode("utf-8"))

                session_id = params.get("session_id")
                if not session_id or session_id not in SESSIONS:
                    self.end_json({"error": "Invalid or expired session. Please upload zip again."}, 404)
                    return

                session_data = SESSIONS[session_id]

                db_name = params.get("database", "__all__")
                table_name = params.get("table", "__all__")
                filter_type = params.get("filter_type", "all")
                limit = int(params.get("limit", 500))

                days_val = params.get("older_than_days", 7)
                try:
                    older_than_days = int(days_val) if days_val not in (None, "", "all", 0, "0") else None
                except (ValueError, TypeError):
                    older_than_days = 7

                result = execute_database_query(
                    session_data=session_data,
                    db_name=db_name,
                    table_name=table_name,
                    filter_type=filter_type,
                    limit=limit,
                    older_than_days=older_than_days,
                )

                if "error" in result:
                    self.end_json(result, 400)
                else:
                    self.end_json(result, 200)

            except Exception as e:
                self.end_json({"error": f"Query execution failed: {str(e)}"}, 500)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")


def run_server(port: int = 8080):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, AppHandler)
    print(f"=====================================================")
    print(f" Database Log Checker Web App running!")
    print(f" URL: http://localhost:{port}")
    print(f"=====================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
