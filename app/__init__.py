from flask import Flask, render_template
from .routes import routes
from api.excel_api import excel_api
from config.config import Config
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not os.path.exists(Config.UPLOAD_FOLDER):
        os.makedirs(Config.UPLOAD_FOLDER)

    # Register blueprints
    app.register_blueprint(routes)
    app.register_blueprint(excel_api)

    @app.route("/")
    def index():
        from db.query import get_all_tables

        tables = get_all_tables()
        return render_template("index.html", tables=tables)

    return app
