import re
from db.connection import get_connection

# Only allow letters, numbers and underscores for identifiers
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _safe_identifier(name: str) -> str:
    """
    Normalize an arbitrary name into a safe PostgreSQL identifier.
    """
    n = str(name).strip()
    n = re.sub(r"\.xlsx?$", "", n, flags=re.IGNORECASE)
    n = re.sub(r"\s+", "_", n)
    n = re.sub(r"[^A-Za-z0-9_]", "", n)
    n = n.lower()
    if not n:
        n = "table_untitled"
    if not re.match(r"^[A-Za-z]", n):
        n = "t_" + n
    return n


def create_table_if_not_exists_from_columns(table_name, columns):
    """
    Create a PostgreSQL table (if it does not exist yet) using
    the given column names, returning the sanitized table name
    and the list of sanitized column names.
    """
    table = _safe_identifier(table_name)
    cols = []
    for c in columns:
        col_name = str(c).strip()
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", col_name).lower()
        if not _IDENTIFIER_RE.match(sanitized):
            sanitized = "col_" + sanitized
        cols.append(sanitized)

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

    # PostgreSQL DDL: id as serial primary key, user columns as TEXT
    columns_sql = ",\n  ".join(f'"{col}" TEXT' for col in clean_cols)
    create_sql = f'''
    CREATE TABLE IF NOT EXISTS "{table}" (
      id SERIAL PRIMARY KEY,
      {columns_sql}
    );
    '''

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(create_sql)
    conn.commit()
    cursor.close()
    conn.close()

    return table, clean_cols


def _normalize_col_name(name):
    """Normalize for comparison: strip, lower, alphanumeric only."""
    if name is None:
        return ""
    return "".join(ch for ch in str(name).strip().lower() if ch.isalnum())


def _drop_id_column(cols, vals):
    """Remove Id column and its value so the DB can auto-generate it (GUID/serial)."""
    if len(cols) != len(vals):
        return cols, vals
    new_cols = []
    new_vals = []
    for c, v in zip(cols, vals):
        if _normalize_col_name(c) == "id":
            continue
        new_cols.append(c)
        new_vals.append(v)
    return new_cols, new_vals


def insert_row(table, sanitized_cols, row_values):
    """
    Insert a single row into the given PostgreSQL table.
    """
    import datetime

    sanitized_cols, row_values = _drop_id_column(sanitized_cols, row_values)
    if not sanitized_cols:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cols_sql = ", ".join(f'"{c}"' for c in sanitized_cols)
    placeholders = ", ".join(["%s"] * len(sanitized_cols))
    insert_sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders})'

    def to_db_val(v):
        if v is None:
            return None
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v
        return str(v)

    vals = [to_db_val(v) for v in row_values]
    cursor.execute(insert_sql, vals)
    conn.commit()
    cursor.close()
    conn.close()


def insert_row_skip_duplicates(table, sanitized_cols, row_values, unique_key_cols):
    """
    Insert a row, or do nothing if a row with the same unique key already exists.
    unique_key_cols must be a subset of sanitized_cols and match a UNIQUE constraint.
    Returns 1 if a row was inserted, 0 if skipped (duplicate).
    """
    import datetime

    sanitized_cols, row_values = _drop_id_column(sanitized_cols, row_values)
    if not sanitized_cols:
        return 0
    unique_key_cols = [c for c in unique_key_cols if c and str(c).strip().lower() != "id"]

    conn = get_connection()
    cursor = conn.cursor()

    cols_sql = ", ".join(f'"{c}"' for c in sanitized_cols)
    placeholders = ", ".join(["%s"] * len(sanitized_cols))
    insert_sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders})'
    if unique_key_cols:
        conflict_cols = ", ".join(f'"{c}"' for c in unique_key_cols)
        insert_sql += f" ON CONFLICT ({conflict_cols}) DO NOTHING"

    def to_db_val(v):
        if v is None:
            return None
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v
        return str(v)

    vals = [to_db_val(v) for v in row_values]
    cursor.execute(insert_sql, vals)
    rowcount = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    return rowcount

