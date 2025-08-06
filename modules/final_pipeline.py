from flask import Flask
from flask_session import Session
import os, tempfile
from cleaning import csv_blueprint
from audience import fb_blueprint

app = Flask(__name__)
app.secret_key = "your-secret-key"

# ---------- server-side session ---------- #
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(tempfile.gettempdir(), "flask_sessions")
app.config["SESSION_PERMANENT"] = False
Session(app)
# ----------------------------------------- #


# Register blueprints
app.register_blueprint(csv_blueprint)
app.register_blueprint(fb_blueprint)


if __name__ == "__main__":
    # Run with SSL for Facebook OAuth compliance
    app.run(port=8090, ssl_context="adhoc", debug=True)
