"""
LabQMS Backend Server
=====================
Flask + SQLite backend for the Laboratory Quality Management System.
Handles: user registration, login, session, data persistence, email notifications.

Run this file with: python server.py
Then open: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import json
import os
import smtplib
import ssl
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, 'lqms.db')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

app = Flask(__name__, static_folder=BASE_DIR)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_config():
        # Environment variables take priority over config.json (used for secure cloud deployment)
        cfg = {}
        if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, 'r') as f:
                                    cfg = json.load(f)
                            # Override with env vars if present
                            if os.environ.get('SMTP_USER'):
                                        cfg['smtp_user'] = os.environ['SMTP_USER']
                                    if os.environ.get('SMTP_PASS'):
                                                cfg['smtp_pass'] = os.environ['SMTP_PASS']
                                            if os.environ.get('SMTP_HOST'):
                                                        cfg['smtp_host'] = os.environ['SMTP_HOST']
                                                    if os.environ.get('SMTP_PORT'):
                                                                cfg['smtp_port'] = int(os.environ['SMTP_PORT'])
                                                            return cfg

# ─────────────────────────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
        """Create all tables and seed default super-admin if needed."""
        conn = get_db()
        c = conn.cursor()

    # Labs table — stores every registered laboratory
        c.execute('''
            CREATE TABLE IF NOT EXISTS labs (
                code          TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                city          TEXT DEFAUL"""
    LabQMS Backend Server
    =====================
    Flask + SQLite backend for the Laboratory Quality Management System.
    Handles: user registration, login, session, data persistence, email notifications.

    Run this file with: python server.py
    Then open: http://localhost:5000
    """

    from flask import Flask, request, jsonify, send_from_directory
    import sqlite3
    import json
    import os
    import smtplib
    import ssl
    import logging
    from datetime import datetime
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    # ─────────────────────────────────────────────────────────────────────────────
    # Configuration
    # ─────────────────────────────────────────────────────────────────────────────
    BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
    DB_PATH     = os.path.join(BASE_DIR, 'lqm
