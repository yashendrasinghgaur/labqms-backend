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
            city          TEXT DEFAULT '',
            contact       TEXT DEFAULT '',
            email         TEXT DEFAULT '',
            pass_hash     TEXT NOT NULL,
            sec_q         TEXT DEFAULT '',
            sec_a_hash    TEXT DEFAULT '',
            registered_at TEXT,
            last_login    TEXT,
            status        TEXT DEFAULT 'active'
        )
    ''')

    # Generic per-lab key-value store (mirrors localStorage keys)
    c.execute('''
        CREATE TABLE IF NOT EXISTS lab_data (
            lab_code   TEXT NOT NULL,
            data_key   TEXT NOT NULL,
            value_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (lab_code, data_key)
        )
    ''')

    # Super-admin table
    c.execute('''
        CREATE TABLE IF NOT EXISTS superadmin (
            id          INTEGER PRIMARY KEY,
            username    TEXT NOT NULL,
            pass_hash   TEXT NOT NULL,
            must_change INTEGER DEFAULT 0
        )
    ''')

    # Insert default super-admin if none exists
    if not c.execute('SELECT id FROM superadmin').fetchone():
        # Default password: LabAdmin@1  (same hash the JS client would compute)
        default_hash = js_simple_hash('LabAdmin@1')
        c.execute(
            'INSERT INTO superadmin (username, pass_hash, must_change) VALUES (?, ?, ?)',
            ('superadmin', default_hash, 0)
        )

    conn.commit()
    conn.close()
    log.info(f"Database ready at: {DB_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# Hash helper — mirrors the JS simpleHash function exactly
# ─────────────────────────────────────────────────────────────────────────────
def js_simple_hash(s: str) -> str:
    """
    Replicates the JavaScript simpleHash function:
        let h = 0;
        for (let i = 0; i < str.length; i++) {
            h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
        }
        return h.toString(16);
    """
    import ctypes
    h = ctypes.c_int32(0).value
    for ch in s:
        product = ctypes.c_int32(31 * h).value
        h = ctypes.c_int32(product + ord(ch)).value
    if h < 0:
        return '-' + format(-h, 'x')
    return format(h, 'x')


# ─────────────────────────────────────────────────────────────────────────────
# Email helper
# ─────────────────────────────────────────────────────────────────────────────
def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send via Brevo or SendGrid (HTTPS API), SMTP as local fallback."""
    import requests as _req
    config     = get_config()
    from_email = config.get('smtp_user', 'no-reply@labqms.com')

    # ── Brevo (Sendinblue) path ──────────────────────────────────────────────
    brevo_key = os.environ.get('BREVO_API_KEY', '')
    if brevo_key:
        payload = {
            "sender":      {"name": "LabQMS", "email": from_email},
            "to":          [{"email": to_email}],
            "subject":     subject,
            "htmlContent": html_body
        }
        try:
            resp = _req.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": brevo_key, "Content-Type": "application/json"},
                json=payload,
                timeout=15
            )
            if resp.status_code in (200, 201):
                log.info(f"Email sent to {to_email}: {subject}")
                return True
            else:
                log.error(f"Brevo send failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            log.error(f"Brevo send failed: {e}")
            return False

    # ── SendGrid path ────────────────────────────────────────────────────────
    sg_key = os.environ.get('SENDGRID_API_KEY', '')
    if sg_key:
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from":    {"email": from_email, "name": "LabQMS"},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}]
        }
        try:
            resp = _req.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sg_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=15
            )
            if resp.status_code == 202:
                log.info(f"Email sent to {to_email}: {subject}")
                return True
            else:
                log.error(f"SendGrid send failed: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            log.error(f"SendGrid send failed: {e}")
            return False

    # ── SMTP fallback (for local dev) ────────────────────────────────────────
    config    = get_config()
    smtp_host = config.get('smtp_host', 'smtp.gmail.com')
    smtp_port = int(config.get('smtp_port', 587))
    smtp_user = config.get('smtp_user', '')
    smtp_pass = config.get('smtp_pass', '')

    if not smtp_user or not smtp_pass:
        log.warning("Email not configured — skipping email send.")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"LabQMS <{smtp_user}>"
        msg['To']      = to_email
        msg.attach(MIMEText(html_body, 'html'))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())

        log.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False


def welcome_email_html(lab: dict) -> str:
    return f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:10px;overflow:hidden;
              box-shadow:0 2px 8px rgba(0,0,0,.1);">
    <div style="background:#1a56db;padding:24px;text-align:center;">
      <h1 style="color:#fff;margin:0;font-size:22px;">🔬 LabQMS</h1>
      <p style="color:#bfdbfe;margin:6px 0 0;">Laboratory Quality Management System</p>
    </div>
    <div style="padding:28px;">
      <h2 style="color:#1e293b;margin-top:0;">Welcome, {lab.get('name','Your Lab')}! 🎉</h2>
      <p style="color:#475569;">Your LabQMS account has been created successfully. Here are your details:</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;">
        <tr style="background:#f1f5f9;">
          <td style="padding:10px 14px;font-weight:bold;color:#334155;width:40%;">Lab Name</td>
          <td style="padding:10px 14px;color:#1e293b;">{lab.get('name','')}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;color:#334155;">Lab Code</td>
          <td style="padding:10px 14px;color:#1a56db;font-size:18px;font-weight:bold;">{lab.get('code','')}</td>
        </tr>
        <tr style="background:#f1f5f9;">
          <td style="padding:10px 14px;font-weight:bold;color:#334155;">City</td>
          <td style="padding:10px 14px;color:#1e293b;">{lab.get('city','—')}</td>
        </tr>
        <tr>
          <td style="padding:10px 14px;font-weight:bold;color:#334155;">Registered On</td>
          <td style="padding:10px 14px;color:#1e293b;">{lab.get('registered_at','')[:10]}</td>
        </tr>
      </table>
      <div style="background:#fef3c7;border:1px solid #fbbf24;border-radius:8px;padding:14px;margin:16px 0;">
        <p style="margin:0;color:#92400e;font-size:13px;">
          ⚠️ <strong>Security Note:</strong> Keep your Lab Code and Password safe.
          Do not share your credentials with anyone outside your authorised team.
        </p>
      </div>
      <p style="color:#475569;">You can log in at any time by opening LabQMS and entering your
         <strong>Lab Code</strong> and <strong>Password</strong>.</p>
    </div>
    <div style="background:#f8fafc;padding:16px;text-align:center;border-top:1px solid #e2e8f0;">
      <p style="margin:0;color:#94a3b8;font-size:12px;">
        This email was sent automatically by LabQMS. Please do not reply.
      </p>
    </div>
  </div>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# CORS helper (needed when app is opened as file:// during development)
# ─────────────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

@app.route('/api/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    return '', 204


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Register
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/auth/register', methods=['POST'])
def api_register():
    d = request.json or {}
    code      = (d.get('code', '') or '').strip().upper()
    name      = (d.get('name', '') or '').strip()
    city      = (d.get('city', '') or '').strip()
    contact   = (d.get('contact', '') or '').strip()
    email     = (d.get('email', '') or '').strip()
    pass_hash = (d.get('passHash', '') or '').strip()
    sec_q     = (d.get('secQ', '') or '').strip()
    sec_a_hash= (d.get('secAHash', '') or '').strip()

    if not code or not name or not pass_hash:
        return jsonify({'ok': False, 'error': 'Lab Code, Name and Password are required.'}), 400

    conn = get_db()
    try:
        if conn.execute('SELECT code FROM labs WHERE code=?', (code,)).fetchone():
            return jsonify({'ok': False, 'error': 'A lab with this code already exists.'}), 409

        now = datetime.utcnow().isoformat() + 'Z'
        conn.execute(
            '''INSERT INTO labs
               (code, name, city, contact, email, pass_hash, sec_q, sec_a_hash, registered_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
            (code, name, city, contact, email, pass_hash, sec_q, sec_a_hash, now)
        )
        conn.commit()
        log.info(f"New lab registered: {code} — {name}")

        # Send welcome email
        if email:
            lab_info = {'name': name, 'code': code, 'city': city, 'registered_at': now}
            send_email(email, f"Welcome to LabQMS — {name} Account Created", welcome_email_html(lab_info))

        return jsonify({'ok': True, 'message': 'Lab registered successfully.'})
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Login
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/auth/login', methods=['POST'])
def api_login():
    d = request.json or {}
    code      = (d.get('code', '') or '').strip().upper()
    pass_hash = (d.get('passHash', '') or '').strip()

    if not code or not pass_hash:
        return jsonify({'ok': False, 'error': 'Lab Code and Password are required.'}), 400

    conn = get_db()
    try:
        lab = conn.execute('SELECT * FROM labs WHERE code=?', (code,)).fetchone()
        if not lab:
            return jsonify({'ok': False, 'error': 'Lab not found. Please register first.'}), 404
        if lab['status'] != 'active':
            return jsonify({'ok': False, 'error': 'This lab account is deactivated. Contact your administrator.'}), 403
        if lab['pass_hash'] != pass_hash:
            return jsonify({'ok': False, 'error': 'Incorrect password.'}), 401

        # Update last login
        now = datetime.utcnow().isoformat() + 'Z'
        conn.execute('UPDATE labs SET last_login=? WHERE code=?', (now, code))
        conn.commit()

        # Fetch all saved lab data from DB
        rows = conn.execute(
            'SELECT data_key, value_json FROM lab_data WHERE lab_code=?', (code,)
        ).fetchall()
        data = {}
        for row in rows:
            try:
                data[row['data_key']] = json.loads(row['value_json'])
            except Exception:
                pass

        lab_info = dict(lab)
        lab_info.pop('pass_hash', None)
        lab_info.pop('sec_a_hash', None)

        return jsonify({'ok': True, 'lab': lab_info, 'data': data})
    except Exception as e:
        log.error(f"Login error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# AUTH — Forgot Password (3-step)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/auth/forgot/step1', methods=['POST'])
def api_forgot_step1():
    code = ((request.json or {}).get('code', '') or '').strip().upper()
    conn = get_db()
    try:
        lab = conn.execute('SELECT code, sec_q FROM labs WHERE code=?', (code,)).fetchone()
        if not lab:
            return jsonify({'ok': False, 'error': 'Lab not found.'}), 404
        if not lab['sec_q']:
            return jsonify({'ok': False, 'error': 'No security question on file. Contact administrator.'}), 400
        return jsonify({'ok': True, 'secQ': lab['sec_q']})
    finally:
        conn.close()


@app.route('/api/auth/forgot/step2', methods=['POST'])
def api_forgot_step2():
    d = request.json or {}
    code       = (d.get('code', '') or '').strip().upper()
    sec_a_hash = (d.get('secAHash', '') or '').strip()
    conn = get_db()
    try:
        lab = conn.execute('SELECT sec_a_hash FROM labs WHERE code=?', (code,)).fetchone()
        if not lab or lab['sec_a_hash'] != sec_a_hash:
            return jsonify({'ok': False, 'error': 'Incorrect answer. Please try again.'}), 401
        return jsonify({'ok': True})
    finally:
        conn.close()


@app.route('/api/auth/forgot/step3', methods=['POST'])
def api_forgot_step3():
    d = request.json or {}
    code      = (d.get('code', '') or '').strip().upper()
    pass_hash = (d.get('passHash', '') or '').strip()
    conn = get_db()
    try:
        conn.execute('UPDATE labs SET pass_hash=? WHERE code=?', (pass_hash, code))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# DATA SYNC — Push (localStorage → SQLite)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/sync/push', methods=['POST'])
def api_sync_push():
    d = request.json or {}
    lab_code = (d.get('lab', '') or '').strip().upper()
    items    = d.get('items', {}) or {}

    if not lab_code:
        return jsonify({'ok': False, 'error': 'Missing lab code.'}), 400

    conn = get_db()
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        for data_key, value in items.items():
            conn.execute(
                '''INSERT OR REPLACE INTO lab_data (lab_code, data_key, value_json, updated_at)
                   VALUES (?, ?, ?, ?)''',
                (lab_code, data_key, json.dumps(value), now)
            )
        conn.commit()
        return jsonify({'ok': True, 'synced': len(items)})
    except Exception as e:
        log.error(f"Sync push error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# DATA SYNC — Pull (SQLite → localStorage)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/sync/pull', methods=['GET'])
def api_sync_pull():
    lab_code = (request.args.get('lab', '') or '').strip().upper()
    if not lab_code:
        return jsonify({'ok': False, 'error': 'Missing lab code.'}), 400

    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT data_key, value_json FROM lab_data WHERE lab_code=?', (lab_code,)
        ).fetchall()
        data = {}
        for row in rows:
            try:
                data[row['data_key']] = json.loads(row['value_json'])
            except Exception:
                pass
        return jsonify({'ok': True, 'data': data})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Login
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/login', methods=['POST'])
def api_admin_login():
    d = request.json or {}
    username  = (d.get('username', '') or '').strip()
    pass_hash = (d.get('passHash', '') or '').strip()
    conn = get_db()
    try:
        admin = conn.execute('SELECT * FROM superadmin').fetchone()
        if not admin or admin['username'] != username or admin['pass_hash'] != pass_hash:
            return jsonify({'ok': False, 'error': 'Invalid administrator credentials.'}), 401
        return jsonify({'ok': True, 'mustChange': bool(admin['must_change'])})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Labs list
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/labs', methods=['GET'])
def api_admin_labs():
    conn = get_db()
    try:
        labs = conn.execute(
            'SELECT code, name, city, contact, email, registered_at, last_login, status FROM labs'
        ).fetchall()
        result = []
        for lab in labs:
            rec = dict(lab)
            # Compute stats from stored data
            key_entries = f"{lab['code']}_qc_entries"
            key_capas   = f"{lab['code']}_capas"
            row_e = conn.execute(
                'SELECT value_json FROM lab_data WHERE lab_code=? AND data_key=?',
                (lab['code'], key_entries)
            ).fetchone()
            row_c = conn.execute(
                'SELECT value_json FROM lab_data WHERE lab_code=? AND data_key=?',
                (lab['code'], key_capas)
            ).fetchone()
            try:
                entries = json.loads(row_e['value_json']) if row_e else []
                rec['totalEntries'] = len(entries)
            except Exception:
                rec['totalEntries'] = 0
            try:
                capas = json.loads(row_c['value_json']) if row_c else []
                rec['openCAPAs'] = sum(1 for c in capas if c.get('status') == 'open')
            except Exception:
                rec['openCAPAs'] = 0
            result.append(rec)
        return jsonify({'ok': True, 'labs': result})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Reset lab password
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/reset-password', methods=['POST'])
def api_admin_reset_password():
    d = request.json or {}
    code      = (d.get('code', '') or '').strip().upper()
    pass_hash = (d.get('passHash', '') or '').strip()
    conn = get_db()
    try:
        conn.execute('UPDATE labs SET pass_hash=? WHERE code=?', (pass_hash, code))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Toggle lab status
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/toggle-status', methods=['POST'])
def api_admin_toggle_status():
    d = request.json or {}
    code   = (d.get('code', '') or '').strip().upper()
    status = d.get('status', 'active')
    conn = get_db()
    try:
        conn.execute('UPDATE labs SET status=? WHERE code=?', (status, code))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Change admin password
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/change-password', methods=['POST'])
def api_admin_change_password():
    d = request.json or {}
    pass_hash = (d.get('passHash', '') or '').strip()
    conn = get_db()
    try:
        conn.execute('UPDATE superadmin SET pass_hash=?, must_change=0', (pass_hash,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — Get all labs for lqms_labs localStorage key (for AdminPortal compat)
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/api/admin/labs-registry', methods=['GET'])
def api_admin_labs_registry():
    """Returns labs in the same shape as lqms_labs localStorage array."""
    conn = get_db()
    try:
        labs = conn.execute('SELECT * FROM labs').fetchall()
        result = []
        for lab in labs:
            result.append({
                'code':         lab['code'],
                'name':         lab['name'],
                'city':         lab['city'],
                'contact':      lab['contact'],
                'passHash':     lab['pass_hash'],
                'secQ':         lab['sec_q'],
                'secAHash':     lab['sec_a_hash'],
                'registeredAt': lab['registered_at'],
                'lastLogin':    lab['last_login'],
                'status':       lab['status'],
            })
        return jsonify({'ok': True, 'labs': result})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Static file serving — serves index.html and all JS/CSS assets
# ─────────────────────────────────────────────────────────────────────────────
@app.route('/')
def serve_index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

# Always initialise DB (works for both direct run and gunicorn/cloud)
init_db()

if __name__ == '__main__':
    import os as _os
    _port = int(_os.environ.get('PORT', 5000))
    print("\n" + "=" * 60)
    print("  LabQMS Server")
    print("=" * 60)
    print(f"  Database : {DB_PATH}")
    print(f"  URL      : http://localhost:{_port}")
    print(f"  Email cfg: {CONFIG_PATH}")
    print("=" * 60)
    print("  Press CTRL+C to stop the server")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=_port, debug=False)
