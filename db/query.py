from db.connection import get_connection
from psycopg2.extras import RealDictCursor


def get_all_tables():
    """
    Return a list of all user tables in the public schema.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
    )
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return tables


def get_table_columns(table_name):
    """
    Return the list of column names for a given table, excluding the primary key
    and common audit/soft-delete metadata columns.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (table_name,),
    )
    cols = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    # Filter out id and common metadata columns
    ignore = {
        "id",
        "datecreatedutc",
        "dateupdatedutc",
        "createdby",
        "lastupdatedby",
        "isdeleted",
        "deletedat",
        "deletedby",
    }
    return [c for c in cols if c.lower() not in ignore]


def get_audit_columns_with_defaults(table_name):
    """
    Return (column_names, default_values) for audit columns that exist in the table
    and should be set on insert (e.g. DateCreatedUtc, DateUpdatedUtc, CreatedBy).
    Only includes columns that actually exist in the table.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (table_name,),
    )
    all_cols = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()

    from datetime import datetime, timezone

    # Defaults for known audit columns (lowercase key = match regardless of casing)
    audit_defaults = {
        "datecreatedutc": lambda: datetime.now(timezone.utc),
        "dateupdatedutc": lambda: datetime.now(timezone.utc),
        "createdby": "excel_import",
        "lastupdatedby": "excel_import",
        "isdeleted": False,
        "deletedat": None,
        "deletedby": None,
    }

    col_names = []
    col_values = []
    for c in all_cols:
        key = c.lower()
        if key in audit_defaults:
            col_names.append(c)
            default = audit_defaults[key]
            col_values.append(default() if callable(default) else default)
    return col_names, col_values


def get_not_null_columns(table_name):
    """
    Return the set of column names that have NOT NULL constraint (is_nullable = 'NO').
    Used to fill empty Excel values with a default so inserts don't violate NOT NULL.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND is_nullable = 'NO';
        """,
        (table_name,),
    )
    cols = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return cols


def get_defaults_for_columns(table_name, column_names):
    """
    Return a list of type-appropriate default values for the given columns
    (for NOT NULL columns we're not supplying: integer -> 0, boolean -> False, else '').
    Order matches sorted(column_names).
    """
    if not column_names:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ", ".join(["%s"] * len(column_names))
    cursor.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = ANY(%s)
        ORDER BY column_name;
        """,
        (table_name, list(column_names)),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    int_types = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
    defaults = []
    for _name, data_type in rows:
        if data_type in int_types:
            defaults.append(0)
        elif data_type == "boolean":
            defaults.append(False)
        else:
            defaults.append("")
    return defaults


def get_unique_key_columns(table_name):
    """
    Return the list of column names for the first UNIQUE constraint (excluding PK).
    Used to skip or avoid inserting duplicate rows (e.g. ON CONFLICT DO NOTHING).
    Returns [] if no suitable UNIQUE constraint exists.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT tc.constraint_name, kcu.column_name, kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_schema = kcu.constraint_schema
         AND tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.table_name = %s
          AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position;
        """,
        (table_name,),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    if not rows:
        return []
    # Take first unique constraint's columns (group by constraint_name)
    first_constraint = rows[0][0]
    return [r[1] for r in rows if r[0] == first_constraint]


def get_columns_in_any_unique_constraint(table_name):
    """
    Return the set of column names that appear in any UNIQUE constraint.
    Used to avoid auto-filling them with the same value (e.g. 0) which would cause
    duplicate key errors on the second row.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_schema = kcu.constraint_schema
         AND tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.table_name = %s
          AND tc.constraint_type = 'UNIQUE';
        """,
        (table_name,),
    )
    cols = {row[0] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    return cols


def get_candidate_key_for_duplicate_check(import_db_cols):
    """
    When the table has no UNIQUE constraint, pick a single column to use for
    duplicate check (e.g. Natemis for Schools). Returns the first column from
    import_db_cols whose name (lowercase) is in our preferred list, or None.
    """
    preferred = (
        "natemis",
        "name",
        "level",
        "code",
        "id",
        "externalid",
        "key",
        "number",
        "email",
        "username",
        "ref",
        "reference",
    )
    import_lower = {c.lower(): c for c in import_db_cols}
    for p in preferred:
        if p in import_lower:
            return import_lower[p]
    return None


def row_exists_by_key(table_name, key_columns, key_values):
    """
    Return True if a row exists in table_name with the given key column values.
    key_columns and key_values must be same length. Handles NULL in key values.
    """
    if not key_columns or len(key_columns) != len(key_values):
        return False
    conn = get_connection()
    cursor = conn.cursor()
    conditions = []
    params = []
    for c, v in zip(key_columns, key_values):
        if v is None or (isinstance(v, float) and str(v) == "nan"):
            conditions.append(f'"{c}" IS NULL')
        else:
            conditions.append(f'"{c}" = %s')
            params.append(v)
    where = " AND ".join(conditions)
    sql = f'SELECT 1 FROM "{table_name}" WHERE {where} LIMIT 1'
    cursor.execute(sql, params)
    found = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return found

