from flask import Blueprint, render_template, request, current_app, redirect, url_for, flash, session, send_file
import pandas as pd
import os
from werkzeug.utils import secure_filename
import re
import io

from api.external_api import send_to_api
from db import models
from db.connection import get_connection
from db.query import (
    get_all_tables,
    get_table_columns,
    get_audit_columns_with_defaults,
    get_not_null_columns,
    get_defaults_for_columns,
    get_unique_key_columns,
    get_columns_in_any_unique_constraint,
    get_candidate_key_for_duplicate_check,
    row_exists_by_key,
)
import psycopg2

routes = Blueprint('routes', __name__)

ALLOWED_EXT = {'.xls', '.xlsx'}

def allowed_filename(fname):
    ext = os.path.splitext(fname)[1].lower()
    return ext in ALLOWED_EXT


@routes.route("/")
def index():
    tables = get_all_tables()
    return render_template("index.html", tables=tables)


@routes.route("/upload", methods=["POST"])
def upload_file():
    file = request.files.get("file")
    target_table = request.form.get("target_table")

    if not file:
        return "No file uploaded!", 400
    if not target_table:
        return "No target table selected!", 400

    # Basic safety check on table name (must match existing tables anyway)
    if not re.match(r"^[A-Za-z0-9_]+$", target_table):
        return "Invalid table name.", 400

    filename = secure_filename(file.filename)
    if not allowed_filename(filename):
        return "Invalid file type. Upload .xls or .xlsx", 400

    upload_folder = current_app.config.get("UPLOAD_FOLDER") or "uploads"
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    try:
        df = pd.read_excel(filepath, dtype=object)
        # Drop columns that are completely empty
        df = df.dropna(axis=1, how="all")
    except Exception as e:
        return f"Error reading Excel: {e}", 400

    # Persist preview to temp CSV
    temp_csv = os.path.join(upload_folder, "temp_data.csv")
    df.to_csv(temp_csv, index=False)

    # Remember chosen table for confirmation step
    session["target_table"] = target_table

    return render_template(
        "show_data.html",
        df=df,
        filename=filename,
        file_id=0,
        total_rows=len(df),
        target_table=target_table,
    )

# LOAD EXISTING TABLE FOR EDITING
@routes.route('/show/<int:file_id>')
def show_existing(file_id):
    # Fetch table name
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT table_name FROM uploaded_files WHERE id=%s", (file_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        return "Table not found", 404

    table_name = result["table_name"]

    # Load table into dataframe
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM `{table_name}`", conn)
    conn.close()
    df = df.drop(columns=['id'], errors='ignore')

   
    from flask import session
    session["table_info"] = {
        "table_name": table_name,
        "sanitized_cols": list(df.columns)
    }
  

    return render_template(
        "show_data.html",
        df=df,
        filename=table_name,
        file_id=file_id,
        total_rows=len(df)
    )



#save previews

@routes.route('/save_preview/<int:file_id>', methods=['POST'])
def save_preview(file_id):
    # For now, only support editing the current preview (no uploaded_files metadata)
    upload_folder = current_app.config.get("UPLOAD_FOLDER") or "uploads"
    temp_csv = os.path.join(upload_folder, "temp_data.csv")
    if not os.path.exists(temp_csv):
        return "No temporary data found!", 400
    df = pd.read_csv(temp_csv, dtype=object)
    table_name = None

    # Apply all edits from form
    for i in range(len(df)):
        for col in df.columns:
            key = f"{col}_{i}"
            if key in request.form:
                df.at[i, col] = request.form[key]

    # Save changes back to temp CSV for new upload
    df.to_csv(temp_csv, index=False)

    flash("Changes saved successfully!")
    return render_template(
        "show_data.html",
        df=df,
        filename=table_name or "Preview",
        file_id=file_id,
        total_rows=len(df)
    )



@routes.route("/confirm", methods=["POST"])
def confirm_upload():
    upload_folder = current_app.config.get("UPLOAD_FOLDER") or "uploads"
    temp_csv = os.path.join(upload_folder, "temp_data.csv")

    if not os.path.exists(temp_csv):
        return "No temporary data found!", 400

    df = pd.read_csv(temp_csv, dtype=object)
    target_table = request.form.get("target_table") or session.get("target_table")
    if not target_table:
        return "No target table specified!", 400

    if not re.match(r"^[A-Za-z0-9_]+$", target_table):
        return "Invalid table name.", 400

    # Ensure DataFrame columns line up with target table columns (excluding id/metadata)
    table_cols = get_table_columns(target_table)
    if not table_cols:
        return "Target table has no importable columns.", 400

    # Normalize: lowercase, spaces -> underscores (Excel "Phase Name" -> "phase_name")
    norm = lambda s: str(s).strip().lower().replace(" ", "_")
    normalized_db = [norm(c) for c in table_cols]
    normalized_xl = [norm(c) for c in df.columns]
    db_norm_to_col = {norm(c): c for c in table_cols}

    def excel_matches_db(xl_norm, db_norm):
        """Match Excel header to DB column (exact, or ignore underscores, or Phase Name -> Name)."""
        if xl_norm == db_norm:
            return True
        if xl_norm.replace("_", "") == db_norm.replace("_", ""):
            return True
        if db_norm == "name" and xl_norm.endswith("_name"):
            return True
        return False

    # Every Excel column must match some DB column
    missing_in_db = []
    for xl_norm in normalized_xl:
        if not any(excel_matches_db(xl_norm, db_norm) for db_norm in normalized_db):
            missing_in_db.append(xl_norm)
    if missing_in_db:
        return (
            f"These Excel columns do not exist in the target table: {missing_in_db}",
            400,
        )

    # Build import_db_cols and the Excel column that maps to each (same order)
    import_db_cols = []
    import_df_cols = []
    for db_col in table_cols:
        target_norm = norm(db_col)
        for xl_col in df.columns:
            xl_norm = norm(xl_col)
            if excel_matches_db(xl_norm, target_norm):
                import_db_cols.append(db_col)
                import_df_cols.append(xl_col)
                break

    if not import_db_cols:
        return "No overlapping columns between Excel and target table.", 400

    # Never include primary key Id (GUID or serial) - DB auto-generates it
    keep = [i for i, c in enumerate(import_db_cols) if c.lower() != "id"]
    import_db_cols = [import_db_cols[i] for i in keep]
    import_df_cols = [import_df_cols[i] for i in keep]

    df = df[import_df_cols]
    df.columns = import_db_cols

    # Required audit columns (e.g. DateCreatedUtc, DateUpdatedUtc) with defaults
    audit_cols, audit_vals = get_audit_columns_with_defaults(target_table)
    all_cols = import_db_cols + audit_cols
    not_null_cols = get_not_null_columns(target_table)

    # Table has other NOT NULL columns we're not providing - fill with type-appropriate defaults
    # Never include primary key Id - the DB auto-generates it
    # Don't auto-fill columns that are in a UNIQUE constraint (would duplicate 0 or '' for every row)
    unique_constraint_cols = get_columns_in_any_unique_constraint(target_table)
    missing_required = {
        c for c in (not_null_cols - set(all_cols))
        if c.lower() != "id" and c not in unique_constraint_cols
    }
    if missing_required:
        missing_list = sorted(missing_required)
        all_cols = all_cols + missing_list
        extra_defaults = get_defaults_for_columns(target_table, missing_list)
    else:
        extra_defaults = []

    # Strip Id from all_cols so we never send it (DB auto-generates GUID/serial)
    def _is_id_col(c):
        if c is None:
            return False
        n = "".join(ch for ch in str(c).strip().lower() if ch.isalnum())
        return n == "id"
    _keep_idx = [i for i, c in enumerate(all_cols) if not _is_id_col(c)]
    all_cols = [all_cols[i] for i in _keep_idx]

    # Duplicate check: use UNIQUE constraint if present, else fallback to candidate key (e.g. Natemis)
    unique_key_cols = get_unique_key_columns(target_table)
    import_db_set = set(import_db_cols)
    if not all(k in import_db_set for k in unique_key_cols):
        unique_key_cols = []
    candidate_key = None
    if not unique_key_cols:
        candidate_key = get_candidate_key_for_duplicate_check(import_db_cols)

    inserted = 0
    skipped = 0
    for _, row in df.iterrows():
        values = []
        for c in import_db_cols:
            v = row.get(c)
            if pd.isna(v) or v == "" or (isinstance(v, float) and str(v) == "nan"):
                v = None
            # NOT NULL columns must not be null; use empty string if missing
            if v is None and c in not_null_cols:
                v = ""
            values.append(v)
        values = values + list(audit_vals) + list(extra_defaults)
        values = [values[i] for i in _keep_idx]

        try:
            if unique_key_cols:
                n = models.insert_row_skip_duplicates(
                    target_table, all_cols, values, unique_key_cols
                )
                if n == 1:
                    inserted += 1
                else:
                    skipped += 1
            elif candidate_key:
                key_val = values[all_cols.index(candidate_key)] if candidate_key in all_cols else None
                if key_val is None:
                    key_val = ""
                if row_exists_by_key(
                    target_table, [candidate_key], [key_val]
                ):
                    skipped += 1
                else:
                    models.insert_row(target_table, all_cols, values)
                    inserted += 1
            else:
                models.insert_row(target_table, all_cols, values)
                inserted += 1
        except psycopg2.IntegrityError as e:
            if e.pgcode == "23505":  # unique_violation
                skipped += 1
            else:
                raise

    # Clean up
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
    session.pop("table_info", None)
    session.pop("target_table", None)

    if (unique_key_cols or candidate_key) and (inserted > 0 or skipped > 0):
        flash(
            f"Import complete: {inserted} row(s) added, {skipped} duplicate(s) skipped for '{target_table}'."
        )
    else:
        flash(f"Imported {inserted} row(s) into '{target_table}'.")
    return redirect(url_for("routes.index"))


@routes.route('/download/<int:file_id>')
def download_excel(file_id):
    #Get table info
    conn= get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT table_name,original_filename FROM uploaded_files WHERE id=%s",(file_id))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    
    if not result:
        return "File not found",404
    
    table_name = result['table_name']
    orig_filename = result['original_filename']
    
    
    #Fetch data on DB
    conn = get_connection()
    df = pd.read_sql(f"SELECT * FROM `{table_name}`", conn)
    conn.close()
    df = df.drop(columns=['id'], errors='ignore')
    
    #Convert to Excel in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    output.seek(0)
    
    #Send as downloadable file
    safe_filename = orig_filename.replace(' ', '_') + '.xlsx'
    return send_file(output, download_name=safe_filename, as_attachment=True)