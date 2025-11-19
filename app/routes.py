from flask import Blueprint, render_template, request, current_app, redirect, url_for, flash,session
import pandas as pd
import os
from werkzeug.utils import secure_filename
import re

from api.external_api import send_to_api
from db import models
from db.connection import get_connection
from db.query import get_uploaded_excel_files

routes = Blueprint('routes', __name__)

ALLOWED_EXT = {'.xls', '.xlsx'}

def allowed_filename(fname):
    ext = os.path.splitext(fname)[1].lower()
    return ext in ALLOWED_EXT


# HOMEPAGE
@routes.route('/')
def index():
    files = get_uploaded_excel_files()
    return render_template('index.html', excel_files=files)


# UPLOAD EXCEL + SHOW PREVIEW
@routes.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    if not file:
        return "No file uploaded!", 400

    filename = secure_filename(file.filename)
    if not allowed_filename(filename):
        return "Invalid file type. Upload .xls or .xlsx", 400

    upload_folder = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)

    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    try:
        df = pd.read_excel(filepath, dtype=object)
    except Exception as e:
        return f"Error reading Excel: {e}", 400

    temp_csv = os.path.join(upload_folder, 'temp_data.csv')
    df.to_csv(temp_csv, index=False)

    return render_template(
        'show_data.html',
        df=df,
        filename=filename,
        file_id=0,
        total_rows=len(df)
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
    files = get_uploaded_excel_files()
    table_info = next((f for f in files if f["id"] == file_id), None)

    if table_info:
        # Existing DB table
        table_name = table_info["table_name"]
        conn = get_connection()
        df = pd.read_sql(f"SELECT * FROM `{table_name}`", conn)
        conn.close()
        df = df.drop(columns=['id'], errors='ignore')
    else:
        # New upload preview from temp CSV
        upload_folder = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
        temp_csv = os.path.join(upload_folder, 'temp_data.csv')
        if not os.path.exists(temp_csv):
            return "No temporary data found!", 400
        df = pd.read_csv(temp_csv, dtype=object)
        table_name = None  # new upload

    # Apply all edits from form
    for i in range(len(df)):
        for col in df.columns:
            key = f"{col}_{i}"
            if key in request.form:
                df.at[i, col] = request.form[key]

    if table_name:
        # Save changes to DB table
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM `{table_name}`")
        conn.commit()
        for _, row in df.iterrows():
            values = [row.get(c) for c in df.columns]
            models.insert_row(table_name, df.columns.tolist(), values)
        cursor.close()
        conn.close()
    else:
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



@routes.route('/confirm', methods=['POST'])
def confirm_upload():
    upload_folder = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    temp_csv = os.path.join(upload_folder, 'temp_data.csv')

    #Check for temp CSV OR session data
    if os.path.exists(temp_csv):
        # New upload
        df = pd.read_csv(temp_csv, dtype=object)
        orig_filename = os.path.splitext(request.form.get('orig_filename'))[0]

        # sanitize table name
        base_name = orig_filename.lower().replace(' ', '_')
        base_name = re.sub(r'[^a-z0-9_]', '', base_name)
        timestamp = pd.Timestamp.now().strftime('%Y%m%d%H%M%S')
        max_base_length = 64 - len('_' + timestamp) - 2
        if len(base_name) > max_base_length:
            base_name = base_name[:max_base_length]

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT table_name FROM uploaded_files WHERE original_filename=%s",
            (orig_filename,)
        )
        existing = cursor.fetchone()

        if existing:
            # Use existing table
            table_name = existing['table_name']
            cursor.execute(f"DELETE FROM `{table_name}`")
            conn.commit()
            sanitized_cols = [c.strip().lower().replace(' ', '_') for c in df.columns]
        else:
            # Create new table
            table_name = f"t_{base_name}_{timestamp}"
            table_name, sanitized_cols = models.create_table_if_not_exists_from_columns(
                table_name, list(df.columns)
            )
            cursor.execute(
                "INSERT INTO uploaded_files (table_name, original_filename, row_count) VALUES (%s, %s, %s)",
                (table_name, orig_filename, 0)
            )
            conn.commit()
        df.columns = sanitized_cols

    elif "table_info" in session:
        # Editing existing table
        table_name = session["table_info"]["table_name"]
        sanitized_cols = session["table_info"]["sanitized_cols"]

        # load df from database
        conn = get_connection()
        df = pd.read_sql(f"SELECT * FROM `{table_name}`", conn)
        conn.close()
        df = df.drop(columns=['id'], errors='ignore')
        df.columns = sanitized_cols

    else:
        return "No temporary data found!", 400

    # Insert/update rows
    conn = get_connection()
    cursor = conn.cursor()
    for _, row in df.iterrows():
        values = [row[c] for c in sanitized_cols]
        models.insert_row(table_name, sanitized_cols, values)

    # Update row count
    cursor.execute(
        "UPDATE uploaded_files SET row_count=%s WHERE table_name=%s",
        (len(df), table_name)
    )
    conn.commit()
    cursor.close()
    conn.close()

    # Clean up
    if os.path.exists(temp_csv):
        os.remove(temp_csv)
    session.pop("table_info", None)

    flash(f"Successfully imported {len(df)} rows into '{table_name}'!")
    return redirect(url_for('routes.index'))
