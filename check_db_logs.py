#!/usr/bin/env python3
"""
check_db_logs.py
================
Inspect database logs from multiple SQLite `app.db` files packaged within
nested ZIP archives.

Given a master zip (or directory of zips), it unzips each database zip,
opens `app.db`, iterates over all tables, and evaluates a given expression / logic
(regex pattern, SQL WHERE clause, or Python expression).

Zero external dependencies required (uses standard library: sqlite3, zipfile, etc.).
"""

import argparse
import csv
import datetime
import json
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ARCHIVE_EXTENSIONS = (
    ".zip",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".tar",
)


def is_archive(p: Path) -> bool:
    name = p.name.lower()
    return any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def unpack_archive(archive_path: Path, target_dir: Path) -> bool:
    """Safely unpack an archive (.zip, .tar.gz, .tgz, .tar, etc.) into target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as z:
                z.extractall(target_dir)
            return True
        elif any(name.endswith(ext) for ext in (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")):
            with tarfile.open(archive_path, "r:*") as tar:
                try:
                    tar.extractall(path=target_dir, filter="data")
                except TypeError:
                    tar.extractall(path=target_dir)
            return True
    except Exception as e:
        print(f"Error unpacking {archive_path.name}: {e}")
        return False
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


# Terminal ANSI colors
class Colors:
    BOLD = "\033[1m"
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    MAGENTA = "\033[0;35m"
    RESET = "\033[0m"


# ==============================================================================
# Optional Custom Filter Function
# You can customize this function directly to implement custom logic!
# ==============================================================================
def custom_logic_filter(db_name: str, table_name: str, row: Dict[str, Any]) -> bool:
    """
    User-definable custom logic function.
    Return True if the row matches your criteria, False otherwise.

    Examples:
        # Check if any field contains 'ERROR' or 'EXCEPTION' (case-insensitive)
        for col, val in row.items():
            if val and re.search(r'error|exception|fail', str(val), re.IGNORECASE):
                return True

        # Check specific table and column
        if table_name == 'logs' and row.get('level') == 'ERROR':
            return True
    """
    # By default, match any row containing 'error' or 'fail' in any field
    for val in row.values():
        if val is not None and re.search(r"error|fail|exception", str(val), re.IGNORECASE):
            return True
    return False


# ==============================================================================
# Database & Archive Processing
# ==============================================================================
class DBLogChecker:
    def __init__(
        self,
        target_db_name: str = "app.db",
        regex_pattern: Optional[str] = None,
        sql_where: Optional[str] = None,
        python_expr: Optional[str] = None,
        use_custom_filter: bool = False,
        table_filter: Optional[str] = None,
        older_than_days: Optional[int] = 7,
        max_display_rows: int = 25,
        verbose: bool = False,
    ):
        self.target_db_name = target_db_name.lower()
        self.regex = re.compile(regex_pattern, re.IGNORECASE) if regex_pattern else None
        self.sql_where = sql_where.strip() if sql_where else None
        self.python_expr = python_expr.strip() if python_expr else None
        self.use_custom_filter = use_custom_filter
        self.table_filter = table_filter
        self.older_than_days = older_than_days if older_than_days and older_than_days > 0 else None
        self.max_display_rows = max_display_rows
        self.verbose = verbose

        self.threshold_dt = None
        self.threshold_str = None
        if self.older_than_days:
            self.threshold_dt = datetime.datetime.now() - datetime.timedelta(days=self.older_than_days)
            self.threshold_str = self.threshold_dt.strftime("%Y-%m-%d %H:%M:%S")

        self.compiled_code = None
        if self.python_expr:
            self.compiled_code = compile(self.python_expr, "<string>", "eval")

    def is_older_than_threshold(self, val: Any) -> bool:
        """Check if date value is older than configured threshold datetime."""
        if not self.threshold_dt or val is None or val == "":
            return False
        try:
            num = float(val)
            if num > 1e11:
                num /= 1000.0
            if 1e8 < num < 3e10:
                return datetime.datetime.fromtimestamp(num) < self.threshold_dt
        except Exception:
            pass
        s = str(val).strip().replace("T", " ").replace("Z", "")
        if "+" in s:
            s = s.split("+")[0]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(s[:19] if fmt == "%Y-%m-%d %H:%M:%S" and len(s) >= 19 else s, fmt)
                return dt < self.threshold_dt
            except Exception:
                pass
        if len(s) >= 10 and s[:4].isdigit() and s[4] == "-":
            return s < self.threshold_str
        return False

    def row_matches(self, db_name: str, table_name: str, row: Dict[str, Any]) -> bool:
        """Evaluate row against the configured filters."""
        # 1. Python Expression mode
        if self.compiled_code:
            try:
                context = {"row": row, "table": table_name, "db": db_name, "re": re}
                return bool(eval(self.compiled_code, {"__builtins__": SAFE_BUILTINS}, context))
            except Exception as e:
                if self.verbose:
                    print(f"    {Colors.YELLOW}[Expr Error]{Colors.RESET} {e} on row: {row}")
                return False

        # 2. Custom Filter mode
        if self.use_custom_filter:
            return custom_logic_filter(db_name, table_name, row)

        # 3. Regex / text search across all columns
        if self.regex:
            for val in row.values():
                if val is not None and self.regex.search(str(val)):
                    return True
            return False

        # If no filter specified, everything matches
        return True

    def find_target_db(self, directory: Path) -> Optional[Path]:
        """Find the target db file (case-insensitive) in an extracted folder, skipping macOS metadata."""
        for p in directory.rglob("*"):
            if p.is_file() and not p.name.startswith("._") and "__MACOSX" not in p.parts and p.name.lower() == self.target_db_name:
                return p
        # Fallback: look for any .db / sqlite file that is valid
        for p in directory.rglob("*.db"):
            if p.is_file() and not p.name.startswith("._") and "__MACOSX" not in p.parts:
                return p
        return None

    def inspect_database(
        self, db_path: Path, archive_name: str
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """
        Inspect each table in SQLite app.db and return (match_count, list_of_matches).
        """
        matches = []
        total_matches = 0

        # Open SQLite in read-only mode for safety
        conn_uri = f"file:{db_path.resolve()}?mode=ro"
        try:
            conn = sqlite3.connect(conn_uri, uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
        except sqlite3.Error as e:
            print(f"  {Colors.RED}Failed to open database '{db_path.name}': {e}{Colors.RESET}")
            return 0, []

        try:
            # Fetch all user tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            tables = [row["name"] for row in cursor.fetchall()]

            if not tables:
                if self.verbose:
                    print(f"  {Colors.YELLOW}No tables found in {archive_name}{Colors.RESET}")
                return 0, []

            for table in tables:
                if self.table_filter and self.table_filter.lower() != table.lower():
                    continue

                # Check table columns for created_at
                cursor.execute(f'PRAGMA table_info("{table}");')
                cols_meta = cursor.fetchall()
                col_lookup = {c["name"].lower(): c["name"] for c in cols_meta}
                created_at_col = col_lookup.get("created_at") or col_lookup.get("createdat") or col_lookup.get("timestamp")

                if self.threshold_dt and not created_at_col:
                    if self.table_filter and self.verbose:
                        print(f"  Table '{table}': {Colors.YELLOW}Skipped (no created_at/timestamp column to filter age){Colors.RESET}")
                    continue

                table_matched_rows = []

                if self.sql_where:
                    where_clause = self.sql_where
                    if self.threshold_dt and created_at_col:
                        date_sql = f"""(
                            (datetime("{created_at_col}") IS NOT NULL AND datetime("{created_at_col}") < datetime('{self.threshold_str}'))
                            OR ("{created_at_col}" < '{self.threshold_str}')
                        )"""
                        where_clause = f"({where_clause}) AND {date_sql}"

                    query = f'SELECT * FROM "{table}" WHERE {where_clause};'
                    try:
                        cursor.execute(query)
                        rows = [dict(r) for r in cursor.fetchall()]
                    except sqlite3.OperationalError as e:
                        if self.verbose:
                            print(
                                f"  Table '{table}': {Colors.YELLOW}Skipped (WHERE condition not applicable: {e}){Colors.RESET}"
                            )
                        continue

                    # Further filter if age, regex, or python expr is given
                    for row in rows:
                        if self.threshold_dt and created_at_col:
                            if not self.is_older_than_threshold(row.get(created_at_col)):
                                continue
                        if self.row_matches(archive_name, table, row):
                            table_matched_rows.append(row)
                else:
                    # Fetch all rows from table and evaluate in Python
                    try:
                        cursor.execute(f'SELECT * FROM "{table}";')
                        for r in cursor:
                            row_dict = dict(r)
                            if self.row_matches(archive_name, table, row_dict):
                                table_matched_rows.append(row_dict)
                    except sqlite3.OperationalError as e:
                        print(f"  {Colors.RED}Error reading table '{table}': {e}{Colors.RESET}")
                        continue

                count = len(table_matched_rows)
                if count > 0:
                    total_matches += count
                    print(
                        f"  {Colors.GREEN}✔ Table '{table}'{Colors.RESET} - "
                        f"Found {Colors.BOLD}{count}{Colors.RESET} matching row(s):"
                    )
                    self.print_table_rows(table_matched_rows[: self.max_display_rows])
                    if count > self.max_display_rows:
                        print(
                            f"    ... and {count - self.max_display_rows} more row(s) (use --limit to see more)\n"
                        )
                    else:
                        print()

                    for row in table_matched_rows:
                        matches.append(
                            {
                                "archive": archive_name,
                                "table": table,
                                "data": row,
                            }
                        )

        finally:
            conn.close()

        return total_matches, matches

    def print_table_rows(self, rows: List[Dict[str, Any]]):
        """Format and print rows nicely aligned."""
        if not rows:
            return

        cols = list(rows[0].keys())
        # Determine column widths
        widths = {col: len(col) for col in cols}
        for r in rows:
            for col in cols:
                val_str = str(r.get(col, ""))
                if len(val_str) > widths[col]:
                    widths[col] = min(len(val_str), 50)  # cap at 50 chars for display

        # Header
        header_line = "  ".join(f"{col:<{widths[col]}}" for col in cols)
        divider_line = "  ".join("-" * widths[col] for col in cols)
        print(f"    {Colors.BOLD}{header_line}{Colors.RESET}")
        print(f"    {divider_line}")

        # Rows
        for r in rows:
            row_vals = []
            for col in cols:
                val_str = str(r.get(col, ""))
                if len(val_str) > widths[col]:
                    val_str = val_str[: widths[col] - 3] + "..."
                row_vals.append(f"{val_str:<{widths[col]}}")
            print(f"    {'  '.join(row_vals)}")

    def run(self, input_path: Path) -> List[Dict[str, Any]]:
        """Main execution loop for unpacking and inspecting database logs."""
        all_matches = []
        total_dbs = 0

        with tempfile.TemporaryDirectory(prefix="db_log_checker_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            db_zips: List[Path] = []

            # Determine input type: master zip, directory, or single archive
            if input_path.is_dir():
                db_zips = sorted([f for f in input_path.glob("*") if is_archive(f)])
            elif input_path.is_file():
                # Extract master zip to inspect its contents
                master_extract = tmp_dir / "master_extract"
                master_extract.mkdir(parents=True, exist_ok=True)
                if not unpack_archive(input_path, master_extract):
                    print(f"{Colors.RED}Error: Failed to extract {input_path}{Colors.RESET}")
                    return []

                # Find nested archives (.tar.gz, .tgz, .zip, etc.) inside master archive
                nested_archives = sorted([f for f in master_extract.rglob("*") if f.is_file() and is_archive(f)])
                if nested_archives:
                    db_zips = nested_archives
                else:
                    # Maybe the input path itself is already a database archive with app.db
                    if self.find_target_db(master_extract):
                        db_zips = [input_path]
            else:
                print(f"{Colors.RED}Error: Input path '{input_path}' not found.{Colors.RESET}")
                return []

            if not db_zips:
                print(
                    f"{Colors.RED}Error: No database archives (.tar.gz / .zip) found in '{input_path}'.{Colors.RESET}"
                )
                return []

            print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
            print(f"{Colors.BOLD}{Colors.BLUE} Database Log Checker (Python){Colors.RESET}")
            print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
            print(f"{Colors.CYAN}Input Source:{Colors.RESET}   {input_path}")
            print(f"{Colors.CYAN}Target DB:{Colors.RESET}      {self.target_db_name}")
            if self.regex:
                print(f"{Colors.CYAN}Expression:{Colors.RESET}     {self.regex.pattern}")
            if self.sql_where:
                print(f"{Colors.CYAN}SQL WHERE:{Colors.RESET}      {self.sql_where}")
            if self.python_expr:
                print(f"{Colors.CYAN}Python Expr:{Colors.RESET}    {self.python_expr}")
            if self.use_custom_filter:
                print(f"{Colors.CYAN}Filter Mode:{Colors.RESET}    Custom Logic Function")
            if self.table_filter:
                print(f"{Colors.CYAN}Table Filter:{Colors.RESET}   {self.table_filter}")
            print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}\n")

            for idx, zpath in enumerate(db_zips, 1):
                total_dbs += 1
                db_name = zpath.name
                print(
                    f"{Colors.BOLD}{Colors.MAGENTA}▶ Database Archive [{idx}/{len(db_zips)}]: {db_name}{Colors.RESET}"
                )

                sub_extract = tmp_dir / f"db_sub_{idx}"
                sub_extract.mkdir(parents=True, exist_ok=True)

                if not unpack_archive(zpath, sub_extract):
                    print(f"  {Colors.RED}Failed to unpack archive '{zpath.name}'{Colors.RESET}")
                    continue

                db_file = self.find_target_db(sub_extract)
                if not db_file:
                    print(
                        f"  {Colors.YELLOW}Target '{self.target_db_name}' not found inside {db_name} (Skipping){Colors.RESET}\n"
                    )
                    continue

                count, matches = self.inspect_database(db_file, db_name)
                all_matches.extend(matches)
                print(f"  {Colors.BOLD}Subtotal for {db_name}:{Colors.RESET} {count} match(es)\n")

        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
        print(f"{Colors.BOLD}Scan Summary:{Colors.RESET}")
        print(f"  Total Database Archives Processed: {Colors.BOLD}{total_dbs}{Colors.RESET}")
        print(
            f"  Total Matching Records Found:      {Colors.BOLD}{Colors.GREEN}{len(all_matches)}{Colors.RESET}"
        )
        print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")

        return all_matches


# ==============================================================================
# CLI Entrypoint
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Unzip master/inner database zips, inspect SQLite app.db, and check tables for given expression/logic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Regex search across all columns in all tables:
  %(prog)s master.zip -r "ERROR|timeout"

  # 2. SQL WHERE clause:
  %(prog)s master.zip -w "status = 'FAILED'"

  # 3. Python expression (row is a dictionary of columns):
  %(prog)s master.zip -e "row.get('level') == 'ERROR' and 'redis' in str(row).lower()"

  # 4. Use custom logic filter function inside the script:
  %(prog)s master.zip --custom

  # 5. Export results to JSON:
  %(prog)s master.zip -r "ERROR" --json results.json
        """,
    )

    parser.add_argument(
        "zip_source",
        type=str,
        help="Path to outer master zip file, directory of zips, or single zip",
    )
    parser.add_argument(
        "-r",
        "--regex",
        type=str,
        default=None,
        help="Search regex/text pattern across all columns of each table",
    )
    parser.add_argument(
        "-w",
        "--where",
        type=str,
        default=None,
        help="SQL WHERE condition (e.g. \"level = 'ERROR'\")",
    )
    parser.add_argument(
        "-e",
        "--expr",
        type=str,
        default=None,
        help="Python expression evaluated on each row (e.g. \"'fail' in row.get('status','').lower()\")",
    )
    parser.add_argument(
        "--custom",
        action="store_true",
        help="Use custom_logic_filter() defined in this script for complex logic",
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=7,
        help="Filter records older than N days in created_at (default: 7 = 1 week, 0 to disable)",
    )
    parser.add_argument(
        "-t",
        "--table",
        type=str,
        default=None,
        help="Filter by specific table name (default: all tables)",
    )
    parser.add_argument(
        "-f",
        "--db-name",
        type=str,
        default="app.db",
        help="Target database filename inside archives (default: app.db)",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=50,
        help="Maximum rows to display per table in console (default: 50)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        type=str,
        default=None,
        help="Save matched records to a JSON file",
    )
    parser.add_argument(
        "--csv",
        dest="csv_output",
        type=str,
        default=None,
        help="Save matched records to a CSV file",
    )

    args = parser.parse_args()

    input_path = Path(args.zip_source)

    sql_where = args.where
    if not (args.regex or args.where or args.expr or args.custom):
        sql_where = "(status = 4 OR status = '4') OR (LOWER(cc_status) = 'to_upload' OR cc_status = 'to_upload')"

    checker = DBLogChecker(
        target_db_name=args.db_name,
        regex_pattern=args.regex,
        sql_where=sql_where,
        python_expr=args.expr,
        use_custom_filter=args.custom,
        table_filter=args.table,
        older_than_days=args.days,
        max_display_rows=args.limit,
        verbose=args.verbose,
    )

    start_time = time.time()
    matches = checker.run(input_path)
    elapsed = time.time() - start_time
    print(f"Elapsed time: {elapsed:.2f} seconds\n")

    # Export to JSON if requested
    if args.json_output:
        out_path = Path(args.json_output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(matches, f, indent=2, default=str)
        print(f"Saved {len(matches)} match(es) to JSON: {out_path.resolve()}")

    # Export to CSV if requested
    if args.csv_output:
        out_path = Path(args.csv_output)
        if matches:
            # Flatten row data with device_serial_no as first column
            fieldnames = ["device_serial_no", "archive", "table"]
            all_cols = set()
            for m in matches:
                all_cols.update(m["data"].keys())
            fieldnames.extend(sorted(all_cols))

            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for m in matches:
                    archive_name = Path(m["archive"]).name
                    serial_no = archive_name.split("_")[0] if "_" in archive_name else archive_name
                    flat_row = {"device_serial_no": serial_no, "archive": m["archive"], "table": m["table"]}
                    flat_row.update(m["data"])
                    writer.writerow(flat_row)
            print(f"Saved {len(matches)} match(es) to CSV: {out_path.resolve()}")
        else:
            print("No matches to export to CSV.")


if __name__ == "__main__":
    main()
