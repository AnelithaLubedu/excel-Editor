import re
from db.connection import get_connection

# Only allow letters, numbers and underscores for identifiers
_IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_]+$')

def _safe_identifier(name):
    # normalize: remove extension, spaces -> underscore, lowercase
    n = str(name).strip()
    n = re.sub(r'\.xlsx?$','', n, flags=re.IGNORECASE)  # remove .xls/.xlsx
    n = re.sub(r'\s+', '_', n)
    n = re.sub(r'[^A-Za-z0-9_]', '', n)  # remove bad chars
    n = n.lower()
    if not n:
        n = 'table_untitled'
    # final fallback ensure starts with letter
    if not re.match(r'^[A-Za-z]', n):
        n = 't_' + n
    return n

def create_table_if_not_exists_from_columns(table_name, columns):
    # columns: list of strings
    table = _safe_identifier(table_name)
    cols = []
    for c in columns:
        col_name = c.strip()
        # sanitize column to allowed identifier
        sanitized = re.sub(r'[^A-Za-z0-9_]', '_', col_name).lower()
        if not _IDENTIFIER_RE.match(sanitized):
            sanitized = 'col_' + sanitized
        # Avoid duplicate column names
        cols.append(sanitized)
    # unique preserving order
    seen = set()
    clean_cols = []
    for c in cols:
        original = c
        i = 1
        while c in seen:
            c = f"{original}_{i}"
            i += 1
        seen.add(c)
        clean_cols.append(c)

    # Build CREATE TABLE SQL - use VARCHAR(255) for all columns
    columns_sql = ",\n  ".join(f"`{col}` VARCHAR(255)" for col in clean_cols)
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table}` (
      id INT AUTO_INCREMENT PRIMARY KEY,
      {columns_sql}
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(create_sql)
    conn.commit()
    cursor.close()
    conn.close()

    return table, clean_cols  # return sanitized table name and sanitized column names list

def insert_row(table, sanitized_cols, row_values):
    """
    table: sanitized table name (string)
    sanitized_cols: list of column identifiers (in order, sanitized)
    row_values: list of values in same order (strings or None)
    """
    conn = get_connection()
    cursor = conn.cursor()

    cols_sql = ", ".join(f"`{c}`" for c in sanitized_cols)
    placeholders = ", ".join(["%s"] * len(sanitized_cols))
    insert_sql = f"INSERT INTO `{table}` ({cols_sql}) VALUES ({placeholders})"

    # Normalize values to strings (or None)
    vals = [ (str(v) if v is not None else None) for v in row_values ]
    cursor.execute(insert_sql, vals)
    conn.commit()
    cursor.close()
    conn.close()
