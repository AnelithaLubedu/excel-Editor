# Excel Editor

Excel Editor is a Flask web application for uploading Excel files, previewing and editing their rows in the browser, and importing the cleaned data into an existing PostgreSQL database table.

The app is designed for a simple workflow:

1. Select an Excel file (`.xls` or `.xlsx`).
2. Choose a target PostgreSQL table.
3. Preview the spreadsheet in the browser.
4. Edit values before importing.
5. Confirm the import into the selected table.

## Features

- Upload Excel workbooks from the browser.
- Read spreadsheet data with `pandas`.
- Drop completely empty Excel columns before preview.
- Preview uploaded data in an editable HTML table.
- Save preview edits before importing.
- Import only columns that match the selected database table.
- Match Excel headers to database columns with basic normalization, for example:
  - `Phase Name` can match `phase_name`.
  - `phase_name` can match `PhaseName`.
  - A column ending in `_name` can match a database `name` column.
- Skip primary key `Id`/`id` fields so the database can generate them.
- Fill supported audit columns automatically when they exist:
  - `DateCreatedUtc`
  - `DateUpdatedUtc`
  - `CreatedBy`
  - `LastUpdatedBy`
  - `IsDeleted`
  - `DeletedAt`
  - `DeletedBy`
- Detect duplicates using a table `UNIQUE` constraint when available.
- Fall back to common candidate key columns when no unique constraint is available, such as `natemis`, `name`, `code`, `email`, or `reference`.
- Provide a JSON API endpoint for programmatic row imports.

## Tech Stack

- Python
- Flask
- Pandas
- PostgreSQL
- psycopg2
- Bootstrap 5
- openpyxl / xlsxwriter for Excel file handling

## Project Structure

```text
excel-Editor/
|-- api/
|   |-- excel_api.py       # JSON API endpoint for adding rows
|   `-- external_api.py    # Optional forwarding to an external API
|-- app/
|   |-- __init__.py        # Flask app factory and blueprint registration
|   |-- routes.py          # Web upload, preview, save, confirm, and download routes
|   `-- templates/
|       |-- index.html     # Upload page and table list
|       `-- show_data.html # Preview/edit page
|-- config/
|   `-- config.py          # App, upload, API, and database settings
|-- db/
|   |-- connection.py      # PostgreSQL connection helper
|   |-- models.py          # Table creation and insert helpers
|   `-- query.py           # Database metadata and duplicate-check helpers
|-- main/
|   `-- run.py             # Application entry point
|-- uploads/               # Uploaded Excel files and temporary preview CSV
|-- requirements.txt       # Python dependencies
`-- README.md
```

## Requirements

- Python 3.10 or newer
- PostgreSQL running locally or on a reachable server
- A PostgreSQL database with the target tables already created

The current configuration points to this database by default:

```text
Host: localhost
Port: 5432
User: postgres
Password: root
Database: lunge_orchestration_db
```

Update these values in `config/config.py` if your PostgreSQL setup is different.

## Setup

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `psycopg2-binary` fails to install, make sure PostgreSQL client libraries are installed on your machine, or use your operating system's package manager to install PostgreSQL development headers.

## Database Setup

Before running the app, confirm that PostgreSQL is running and that the database from `config/config.py` exists.

Example using `psql`:

```bash
createdb lunge_orchestration_db
```

The upload page lists user tables from the PostgreSQL `public` schema. At least one table must exist before you can import a spreadsheet through the web UI.

The app imports data into existing tables. It does not create a target table during the normal web upload flow.

## Running the App

Start the Flask app from the project root:

```bash
python main/run.py
```

By default, Flask starts at:

```text
http://127.0.0.1:5000
```

Open that URL in your browser.

## How to Use the Web App

1. Go to `http://127.0.0.1:5000`.
2. Choose an Excel file with the `.xls` or `.xlsx` extension.
3. Select the database table where the data should be imported.
4. Click `Upload`.
5. Review the preview table.
6. Edit any values that need to change.
7. Click `Save Changes (Keep Preview)` if you edited the preview.
8. Click `Confirm & Import` to insert rows into PostgreSQL.

After import, the app redirects back to the upload page and displays a success message with the number of inserted and skipped duplicate rows.

## Import Rules

### File Types

Only these extensions are accepted:

- `.xls`
- `.xlsx`

### Column Matching

The app compares Excel headers to database column names after normalizing them:

- Trims whitespace.
- Converts names to lowercase.
- Replaces spaces with underscores.
- Allows matches that only differ by underscores.
- Allows names ending in `_name` to match a database column named `name`.

If an Excel column cannot be matched to the selected table, the import is rejected with a message listing the unmatched columns.

### Primary Keys

Columns named `Id` or `id` are removed before insert so PostgreSQL can generate primary keys itself.

### Audit Columns

When audit columns exist in the selected table, the app fills them automatically:

```text
DateCreatedUtc  -> current UTC timestamp
DateUpdatedUtc  -> current UTC timestamp
CreatedBy       -> excel_import
LastUpdatedBy   -> excel_import
IsDeleted       -> false
DeletedAt       -> null
DeletedBy       -> null
```

### Required Columns

If the target table has required `NOT NULL` columns that were not supplied by Excel, the app tries to fill safe default values:

- Numeric columns: `0`
- Boolean columns: `false`
- Other columns: empty string

Columns that participate in a `UNIQUE` constraint are not auto-filled, because using the same default value for every row would create duplicate key errors.

### Duplicate Handling

The app first looks for a `UNIQUE` constraint on the target table. If the uploaded data includes all columns from that constraint, inserts use `ON CONFLICT DO NOTHING`.

If no usable unique constraint exists, the app tries to pick a candidate key from common column names:

```text
natemis, name, level, code, id, externalid, key, number, email, username, ref, reference
```

Rows with matching candidate-key values are skipped.

## API Endpoint

### `POST /api/add`

Accepts a JSON array of objects:

```json
[
  {
    "name": "Example",
    "code": "EX001"
  }
]
```

Behavior:

- Creates a table named from `excel_upload` if it does not already exist.
- Sanitizes JSON keys into safe PostgreSQL column names.
- Sends each row to the external API configured in `Config.API_URL`.
- Inserts each row into PostgreSQL.

Example:

```bash
curl -X POST http://127.0.0.1:5000/api/add \
  -H "Content-Type: application/json" \
  -d '[{"name":"Example","code":"EX001"}]'
```

## Configuration

Configuration lives in `config/config.py`.

Important settings:

```python
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
API_URL = "https://example.com/api/add"
DB_HOST = "localhost"
DB_PORT = 5432
DB_USER = "postgres"
DB_PASSWORD = "root"
DB_NAME = "lunge_orchestration_db"
SECRET_KEY = os.urandom(24)
```

For local development, editing this file is enough.

For production or shared environments, move secrets such as `DB_PASSWORD` and `SECRET_KEY` into environment variables instead of committing them directly in the source code.

## Main Routes

| Route | Method | Description |
| --- | --- | --- |
| `/` | `GET` | Shows the upload page and lists available PostgreSQL tables. |
| `/upload` | `POST` | Uploads an Excel file, reads it, stores a temporary CSV preview, and renders editable data. |
| `/save_preview/<file_id>` | `POST` | Saves edited preview data back to the temporary CSV. |
| `/confirm` | `POST` | Imports the preview data into the selected target table. |
| `/api/add` | `POST` | Accepts JSON rows, forwards them to an external API, and inserts them into PostgreSQL. |
| `/show/<file_id>` | `GET` | Legacy route for loading a previously uploaded table. |
| `/download/<file_id>` | `GET` | Legacy route for downloading stored table data as Excel. |

## Development Notes

- Uploaded files and the temporary preview CSV are stored in `uploads/`.
- `uploads/temp_data.csv` is removed after a successful confirm/import.
- `main/run.py` adds the project root to `sys.path`, creates the Flask app, and runs it in debug mode.
- The app uses PostgreSQL double-quoted identifiers in the active insert paths.
- Some legacy routes still reference an `uploaded_files` table and MySQL-style behavior. Review `/show/<file_id>` and `/download/<file_id>` before relying on those routes in PostgreSQL.
- `SECRET_KEY` is regenerated on every app restart, so browser sessions are not stable across restarts. Use a fixed secret value for production or repeatable development sessions.

## Troubleshooting

### `No tables found in the database`

The app connected to PostgreSQL, but no user tables were found in the `public` schema. Create the target tables first.

### `Target table has no importable columns`

The selected table has no columns after excluding common metadata fields like `id`, `DateCreatedUtc`, and `IsDeleted`.

### `These Excel columns do not exist in the target table`

One or more Excel headers do not match columns in the selected database table. Rename the Excel columns or update the table schema.

### `No temporary data found`

The preview CSV is missing. Upload the Excel file again before confirming the import.

### PostgreSQL connection errors

Check:

- PostgreSQL is running.
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` are correct.
- The configured user has permission to read metadata and insert into the selected table.

## Recommended Next Improvements

- Move database settings and secrets to environment variables.
- Add automated tests for column matching and duplicate handling.
- Update legacy `/show/<file_id>` and `/download/<file_id>` routes for PostgreSQL.
- Add a database migration or seed script for local development.
- Add validation for very large Excel files before rendering them in the browser.
