from flask import Blueprint, request, jsonify
from db.models import create_table_if_not_exists_from_columns, insert_row
from api.external_api import send_to_api

excel_api = Blueprint('excel_api', __name__)

@excel_api.route('/api/add', methods=['POST'])
def add_data():
    data = request.get_json()
    if not data or not isinstance(data, list):
        return jsonify({"error": "Invalid data format"}), 400

    columns = list(data[0].keys())
    table_name, sanitized_cols = create_table_if_not_exists_from_columns("excel_upload", columns)

    for row in data:
        # send row to external API
        send_to_api(row)
        # save to database
        row_values = [row.get(col, None) for col in columns]
        insert_row(table_name, sanitized_cols, row_values)

    return jsonify({"message": f"Data sent to API and saved to `{table_name}`!"}), 200