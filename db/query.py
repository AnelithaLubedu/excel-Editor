from db.connection import get_connection

def get_uploaded_excel_files():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, table_name, original_filename, row_count
        FROM uploaded_files
        ORDER BY id DESC
    """)

    files = cursor.fetchall()

    cursor.close()
    conn.close()
    return files

