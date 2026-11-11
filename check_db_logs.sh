#!/usr/bin/env bash
# ==============================================================================
# Script: check_db_logs.sh
# Purpose: Unpack master/inner zip files, inspect each SQLite app.db, and check
#          every table's logs against a given search expression or SQL condition.
# ==============================================================================

set -uo pipefail

# ANSI color codes
BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
RESET='\033[0m'

DB_TARGET_NAME="app.db"
SEARCH_EXPR=""
SQL_WHERE=""
FILTER_TABLE=""
DAYS_FILTER=7
VERBOSE=0
COUNT_ONLY=0

usage() {
    cat << EOF
${BOLD}Usage:${RESET} $0 <master_zip_file_or_dir> [OPTIONS]

${BOLD}Description:${RESET}
  Unpacks database zip archives (supporting nested zips), locates '$DB_TARGET_NAME',
  and scans every table for records matching status = 4 or cc_status = 'to_upload'
  where created_at is older than 1 week from current date (or custom options).

${BOLD}Options:${RESET}
  -d, --days <N>                Filter logs older than N days from now in created_at (default: 7 = 1 week, 0 to disable).
  -e, --expression <REGEX/TEXT>  Search pattern (grep regex) to match across all columns of every table.
  -w, --where <SQL_WHERE>       SQL WHERE condition (e.g., "level = 'ERROR'" or "status = 'FAILED'").
  -t, --table <TABLE_NAME>      Only check a specific table name (default: all tables).
  -f, --db-name <FILENAME>      Target database file name inside archives (default: app.db).
  -c, --count-only              Only show the count of matches per table/database.
  -v, --verbose                 Show verbose progress information.
  -h, --help                    Display this help message.

${BOLD}Examples:${RESET}
  # 1. Search for any mention of ERROR or timeout in all tables across all databases:
  $0 master_databases.zip -e "ERROR|timeout"

  # 2. Match with SQL condition on tables that have matching columns:
  $0 master_databases.zip -w "level = 'ERROR'"

  # 3. Search a specific table 'logs' for 'admin':
  $0 master_databases.zip -t logs -e "admin"
EOF
    exit 1
}

# Ensure at least 1 argument
if [[ $# -lt 1 ]]; then
    usage
fi

INPUT_PATH=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--days)
            DAYS_FILTER="$2"
            shift 2
            ;;
        -e|--expression)
            SEARCH_EXPR="$2"
            shift 2
            ;;
        -w|--where)
            SQL_WHERE="$2"
            shift 2
            ;;
        -t|--table)
            FILTER_TABLE="$2"
            shift 2
            ;;
        -f|--db-name)
            DB_TARGET_NAME="$2"
            shift 2
            ;;
        -c|--count-only)
            COUNT_ONLY=1
            shift
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            if [[ -z "$INPUT_PATH" ]]; then
                INPUT_PATH="$1"
                shift
            else
                echo -e "${RED}Error:${RESET} Unknown option or multiple input paths: $1"
                usage
            fi
            ;;
    esac
done

if [[ -z "$INPUT_PATH" ]]; then
    echo -e "${RED}Error:${RESET} No master zip or directory specified."
    usage
fi

if [[ ! -e "$INPUT_PATH" ]]; then
    echo -e "${RED}Error:${RESET} Input path '$INPUT_PATH' does not exist."
    exit 1
fi

THRESHOLD_DATE=""
if [[ "$DAYS_FILTER" -gt 0 ]]; then
    THRESHOLD_DATE=$(python3 -c "import datetime; print((datetime.datetime.now() - datetime.timedelta(days=$DAYS_FILTER)).strftime('%Y-%m-%d %H:%M:%S'))" 2>/dev/null || date -v-${DAYS_FILTER}d "+%Y-%m-%d %H:%M:%S" 2>/dev/null || true)
fi

if [[ -z "$SEARCH_EXPR" && -z "$SQL_WHERE" ]]; then
    SQL_WHERE="(status = 4 OR status = '4') OR (LOWER(cc_status) = 'to_upload' OR cc_status = 'to_upload')"
    echo -e "${GREEN}Default Filter Applied:${RESET} status = 4 OR cc_status = 'to_upload' (checked separately)"
    if [[ -n "$THRESHOLD_DATE" ]]; then
        echo -e "${GREEN}Age Filter Applied:${RESET} created_at older than $DAYS_FILTER days (< $THRESHOLD_DATE)"
    fi
fi

# Ensure prerequisite tools exist
for cmd in unzip tar sqlite3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo -e "${RED}Error:${RESET} Required command '$cmd' is not installed or not in PATH."
        exit 1
    fi
done

# Setup temporary working directory with auto-cleanup
TEMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t 'db_log_checker')
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

echo -e "${BOLD}${BLUE}======================================================${RESET}"
echo -e "${BOLD}${BLUE} Database Log Checker${RESET}"
echo -e "${BOLD}${BLUE}======================================================${RESET}"
echo -e "${CYAN}Input:${RESET}        $INPUT_PATH"
if [[ -n "$SEARCH_EXPR" ]]; then
    echo -e "${CYAN}Expression:${RESET}   $SEARCH_EXPR"
fi
if [[ -n "$SQL_WHERE" ]]; then
    echo -e "${CYAN}SQL WHERE:${RESET}    $SQL_WHERE"
fi
if [[ -n "$FILTER_TABLE" ]]; then
    echo -e "${CYAN}Table Filter:${RESET} $FILTER_TABLE"
fi
echo -e "${CYAN}Target DB:${RESET}    $DB_TARGET_NAME"
echo -e "${BOLD}${BLUE}======================================================${RESET}\n"

# Step 1: Collect all database archives to process (.zip, .tar.gz, .tgz, .tar)
DB_ZIPS=()

if [[ -d "$INPUT_PATH" ]]; then
    # Directory passed
    while IFS= read -r -d '' zf; do
        DB_ZIPS+=("$zf")
    done < <(find "$INPUT_PATH" -type f \( -name "*.zip" -o -name "*.tar.gz" -o -name "*.tgz" -o -name "*.tar" \) -print0)
elif [[ -f "$INPUT_PATH" ]]; then
    # Could be a master zip containing inner archives, or a single database archive
    MASTER_EXTRACT="$TEMP_DIR/master_extract"
    mkdir -p "$MASTER_EXTRACT"
    
    if [[ "$VERBOSE" -eq 1 ]]; then
        echo "Extracting outer archive: $INPUT_PATH"
    fi
    input_lower=$(echo "$INPUT_PATH" | tr '[:upper:]' '[:lower:]')
    if [[ "$input_lower" == *.tar.gz || "$input_lower" == *.tgz ]]; then
        tar -xzf "$INPUT_PATH" -C "$MASTER_EXTRACT" 2>/dev/null || {
            echo -e "${RED}Error:${RESET} Failed to untar $INPUT_PATH"
            exit 1
        }
    elif [[ "$input_lower" == *.tar ]]; then
        tar -xf "$INPUT_PATH" -C "$MASTER_EXTRACT" 2>/dev/null || {
            echo -e "${RED}Error:${RESET} Failed to untar $INPUT_PATH"
            exit 1
        }
    else
        unzip -q "$INPUT_PATH" -d "$MASTER_EXTRACT" 2>/dev/null || {
            echo -e "${RED}Error:${RESET} Failed to unzip $INPUT_PATH"
            exit 1
        }
    fi
    
    # Check if there are nested .zip or .tar.gz / .tgz / .tar files
    while IFS= read -r -d '' zf; do
        DB_ZIPS+=("$zf")
    done < <(find "$MASTER_EXTRACT" -type f \( -name "*.zip" -o -name "*.tar.gz" -o -name "*.tgz" -o -name "*.tar" \) -print0)
    
    # If no inner archives found, check if app.db exists directly in master extract
    if [[ ${#DB_ZIPS[@]} -eq 0 ]]; then
        if find "$MASTER_EXTRACT" -type f -iname "$DB_TARGET_NAME" | grep -q .; then
            DB_ZIPS+=("$INPUT_PATH")
        fi
    fi
fi

if [[ ${#DB_ZIPS[@]} -eq 0 ]]; then
    echo -e "${RED}Error:${RESET} No database archives (.tar.gz / .zip) or '$DB_TARGET_NAME' found in '$INPUT_PATH'."
    exit 1
fi

TOTAL_DBS=0
TOTAL_MATCHES=0

# Step 2: Iterate over each database archive
for db_zip in "${DB_ZIPS[@]}"; do
    ((TOTAL_DBS++))
    db_base=$(basename "$db_zip")
    echo -e "${BOLD}${MAGENTA}▶ Database Archive [$TOTAL_DBS/${#DB_ZIPS[@]}]: $db_base${RESET}"
    
    DB_EXTRACT_DIR="$TEMP_DIR/db_$TOTAL_DBS"
    mkdir -p "$DB_EXTRACT_DIR"
    
    # Unpack inner archive (.tar.gz, .tgz, .tar, or .zip)
    db_lower=$(echo "$db_base" | tr '[:upper:]' '[:lower:]')
    if [[ "$db_lower" == *.tar.gz || "$db_lower" == *.tgz ]]; then
        tar -xzf "$db_zip" -C "$DB_EXTRACT_DIR" 2>/dev/null || {
            echo -e "  ${RED}Failed to unpack tar.gz archive $db_base${RESET}"
            continue
        }
    elif [[ "$db_lower" == *.tar ]]; then
        tar -xf "$db_zip" -C "$DB_EXTRACT_DIR" 2>/dev/null || {
            echo -e "  ${RED}Failed to unpack tar archive $db_base${RESET}"
            continue
        }
    else
        unzip -q "$db_zip" -d "$DB_EXTRACT_DIR" 2>/dev/null || {
            echo -e "  ${RED}Failed to unpack zip archive $db_base${RESET}"
            continue
        }
    fi
    
    # Locate target db (e.g. app.db)
    DB_FILE=$(find "$DB_EXTRACT_DIR" -type f -iname "$DB_TARGET_NAME" | head -n 1)
    
    if [[ -z "$DB_FILE" || ! -f "$DB_FILE" ]]; then
        echo -e "  ${YELLOW}No '$DB_TARGET_NAME' found inside $db_base (Skipping)${RESET}\n"
        continue
    fi
    
    # Get all tables
    TABLES_QUERY="SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    TABLE_LIST=$(sqlite3 "$DB_FILE" "$TABLES_QUERY" 2>/dev/null)
    
    if [[ -z "$TABLE_LIST" ]]; then
        echo -e "  ${YELLOW}No tables found in $DB_TARGET_NAME${RESET}\n"
        continue
    fi
    
    DB_MATCH_COUNT=0
    
    while IFS= read -r table_name; do
        [[ -z "$table_name" ]] && continue
        
        # Check if table filter is set
        if [[ -n "$FILTER_TABLE" && "$FILTER_TABLE" != "$table_name" ]]; then
            continue
        fi
        
        TABLE_MATCHES=0
        
        # Mode 1: SQL WHERE condition specified
        if [[ -n "$SQL_WHERE" ]]; then
            WHERE_EXP="$SQL_WHERE"
            if [[ -n "$THRESHOLD_DATE" ]]; then
                DATE_COL=$(sqlite3 "$DB_FILE" "PRAGMA table_info(\"$table_name\");" 2>/dev/null | grep -iE 'created_at|timestamp' | head -n 1 | awk -F'|' '{print $2}' || true)
                if [[ -n "$DATE_COL" ]]; then
                    WHERE_EXP="($WHERE_EXP) AND (datetime(\"$DATE_COL\") < datetime('$THRESHOLD_DATE') OR \"$DATE_COL\" < '$THRESHOLD_DATE')"
                else
                    if [[ -n "$FILTER_TABLE" && "$VERBOSE" -eq 1 ]]; then
                        echo -e "  Table ${BOLD}$table_name${RESET}: ${YELLOW}Skipped (no created_at/timestamp column to filter age)${RESET}"
                    fi
                    continue
                fi
            fi
            QUERY_SQL="SELECT * FROM \"$table_name\" WHERE $WHERE_EXP;"
            
            # Test query execution
            QUERY_OUTPUT=$(sqlite3 -header -column "$DB_FILE" "$QUERY_SQL" 2>&1)
            STATUS=$?
            
            if [[ $STATUS -ne 0 ]]; then
                if [[ "$VERBOSE" -eq 1 ]]; then
                    echo -e "  Table ${BOLD}$table_name${RESET}: ${YELLOW}Skipped (WHERE condition inapplicable: $QUERY_OUTPUT)${RESET}"
                fi
                continue
            fi
            
            # If SEARCH_EXPR is also provided, filter further with regex
            if [[ -n "$SEARCH_EXPR" && -n "$QUERY_OUTPUT" ]]; then
                # Keep header (first 2 lines) and matching rows
                HEADER=$(echo "$QUERY_OUTPUT" | head -n 2)
                ROWS=$(echo "$QUERY_OUTPUT" | tail -n +3 | grep -E -i "$SEARCH_EXPR" || true)
                if [[ -n "$ROWS" ]]; then
                    QUERY_OUTPUT="${HEADER}"$'\n'"${ROWS}"
                else
                    QUERY_OUTPUT=""
                fi
            fi
            
            if [[ -n "$QUERY_OUTPUT" ]]; then
                # Count rows (excluding 2 header lines)
                ROW_COUNT=$(echo "$QUERY_OUTPUT" | tail -n +3 | sed '/^\s*$/d' | wc -l | tr -d ' ')
                if [[ "$ROW_COUNT" -gt 0 ]]; then
                    TABLE_MATCHES="$ROW_COUNT"
                    echo -e "  ${GREEN}✔ Table '$table_name'${RESET} - Found ${BOLD}$TABLE_MATCHES${RESET} matching row(s):"
                    if [[ "$COUNT_ONLY" -eq 0 ]]; then
                        echo "$QUERY_OUTPUT" | sed 's/^/    /'
                        echo ""
                    fi
                fi
            fi

        # Mode 2: Search Expression / Regex across all columns
        elif [[ -n "$SEARCH_EXPR" ]]; then
            # Query all rows formatted as table
            ALL_ROWS=$(sqlite3 -header -column "$DB_FILE" "SELECT * FROM \"$table_name\";" 2>/dev/null)
            if [[ -n "$ALL_ROWS" ]]; then
                HEADER=$(echo "$ALL_ROWS" | head -n 2)
                MATCHING_ROWS=$(echo "$ALL_ROWS" | tail -n +3 | grep -E -i "$SEARCH_EXPR" || true)
                
                if [[ -n "$MATCHING_ROWS" ]]; then
                    TABLE_MATCHES=$(echo "$MATCHING_ROWS" | sed '/^\s*$/d' | wc -l | tr -d ' ')
                    echo -e "  ${GREEN}✔ Table '$table_name'${RESET} - Found ${BOLD}$TABLE_MATCHES${RESET} matching row(s):"
                    if [[ "$COUNT_ONLY" -eq 0 ]]; then
                        echo "$HEADER" | sed 's/^/    /'
                        echo "$MATCHING_ROWS" | sed 's/^/    /'
                        echo ""
                    fi
                elif [[ "$VERBOSE" -eq 1 ]]; then
                    echo -e "  Table '$table_name': 0 matches"
                fi
            fi

        # Mode 3: No filter specified, show all rows
        else
            ALL_ROWS=$(sqlite3 -header -column "$DB_FILE" "SELECT * FROM \"$table_name\";" 2>/dev/null)
            if [[ -n "$ALL_ROWS" ]]; then
                ROW_COUNT=$(echo "$ALL_ROWS" | tail -n +3 | sed '/^\s*$/d' | wc -l | tr -d ' ')
                TABLE_MATCHES="$ROW_COUNT"
                echo -e "  ${GREEN}✔ Table '$table_name'${RESET} - Total rows: ${BOLD}$TABLE_MATCHES${RESET}:"
                if [[ "$COUNT_ONLY" -eq 0 ]]; then
                    echo "$ALL_ROWS" | sed 's/^/    /'
                    echo ""
                fi
            fi
        fi
        
        DB_MATCH_COUNT=$((DB_MATCH_COUNT + TABLE_MATCHES))
        TOTAL_MATCHES=$((TOTAL_MATCHES + TABLE_MATCHES))
        
    done <<< "$TABLE_LIST"
    
    echo -e "  ${BOLD}Subtotal for $db_base:${RESET} $DB_MATCH_COUNT match(es)\n"
done

echo -e "${BOLD}${BLUE}======================================================${RESET}"
echo -e "${BOLD}Scan Summary:${RESET}"
echo -e "  Total Database Archives Processed: ${BOLD}$TOTAL_DBS${RESET}"
echo -e "  Total Matching Records Found:      ${BOLD}${GREEN}$TOTAL_MATCHES${RESET}"
echo -e "${BOLD}${BLUE}======================================================${RESET}"
