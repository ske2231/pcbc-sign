"""
Ponca City Beauty College - Digital Document Signing System
A free, self-hosted DocuSign alternative for educational institutions.

Now with PostgreSQL + BLOB storage for cloud persistence.
- Local dev: SQLite + filesystem (backward compatible)
- Production (DATABASE_URL set): PostgreSQL + database BLOBs
"""

import os
import uuid
import hashlib
import datetime
from datetime import timezone
import sys
from functools import wraps
from pathlib import Path
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()  # Read .env file into environment variables

# ── Database imports ────────────────────────────────────────────────────
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import Binary as DbBinary
else:
    import sqlite3
    from sqlite3 import Binary as DbBinary

# ── Optional SendGrid ───────────────────────────────────────────────────
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

# ── Email / SMTP imports ────────────────────────────────────────────────
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Flask setup ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'ponca-beauty-college-default-key-change-me')

BASE_DIR = Path(__file__).parent
DATABASE = BASE_DIR / 'database.db'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Admin credentials (default: admin / ponca2024)
DEFAULT_ADMIN_HASH = generate_password_hash('ponca2024')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', DEFAULT_ADMIN_HASH)

# Email config
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
FROM_EMAIL = os.environ.get('FROM_EMAIL', 'documents@poncabeautycollege.edu')

# SMTP fallback (use your existing school email)
SMTP_HOST = os.environ.get('SMTP_HOST')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')

# ── Database helpers ────────────────────────────────────────────────────

def get_db():
    """Return a DB connection with dict-like rows."""
    ensure_db()
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        # Return RealDictCursor by default
        return conn
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn


def get_cursor(conn):
    """Return a cursor appropriate for the DB type."""
    if IS_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def ph(count=1):
    """Return placeholder string (? or %s)."""
    if IS_POSTGRES:
        return ', '.join(['%s'] * count)
    return ', '.join(['?'] * count)


def last_id(cursor):
    """Return last insert ID."""
    if IS_POSTGRES:
        row = cursor.fetchone()
        return row['id'] if row else None
    return cursor.lastrowid


def init_db():
    # Use raw connection to avoid recursion with ensure_db() → get_db()
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

    if IS_POSTGRES:
        # PostgreSQL schema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                content_type TEXT,
                data BYTEA NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                status TEXT DEFAULT 'pending',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                upload_ip TEXT,
                created_by TEXT DEFAULT 'admin'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sign_requests (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                signer_name TEXT,
                signer_email TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                signed_at TIMESTAMP,
                sign_ip TEXT,
                signature_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
                typed_name TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                document_id INTEGER,
                action TEXT NOT NULL,
                actor TEXT,
                details TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sign_requests_token ON sign_requests(token)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_audit_logs_document ON audit_logs(document_id)
        ''')
    else:
        # SQLite schema (original with BLOB files)
        cursor.executescript('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                content_type TEXT,
                data BLOB NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                status TEXT DEFAULT 'pending',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                upload_ip TEXT,
                created_by TEXT DEFAULT 'admin'
            );

            CREATE TABLE IF NOT EXISTS sign_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                signer_name TEXT,
                signer_email TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                signed_at TIMESTAMP,
                sign_ip TEXT,
                signature_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
                typed_name TEXT
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER,
                action TEXT NOT NULL,
                actor TEXT,
                details TEXT,
                ip_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_sign_requests_token ON sign_requests(token);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_document ON audit_logs(document_id);
        ''')

    conn.commit()
    conn.close()


# DB initialization is lazy — called on first request, not at import.
# This prevents the app from crashing on startup if PostgreSQL isn't ready yet.
_db_initialized = False


def ensure_db():
    """Initialize tables on first use. Safe for multiple workers."""
    global _db_initialized
    if _db_initialized:
        return
    try:
        init_db()
        _db_initialized = True
    except Exception as e:
        print(f"[db] initialization warning: {e}")


# ── File storage helpers ────────────────────────────────────────────────

def save_file(cursor, filename, content_type, data):
    """Store a file in the DB and return its file_id."""
    if IS_POSTGRES:
        cursor.execute(
            'INSERT INTO files (filename, content_type, data) VALUES (%s, %s, %s) RETURNING id',
            (filename, content_type, DbBinary(data))
        )
    else:
        cursor.execute(
            'INSERT INTO files (filename, content_type, data) VALUES (?, ?, ?)',
            (filename, content_type, DbBinary(data))
        )
    return last_id(cursor)


def get_file(cursor, file_id):
    """Fetch a file from the DB. Returns dict or None."""
    if IS_POSTGRES:
        cursor.execute('SELECT filename, content_type, data FROM files WHERE id = %s', (file_id,))
    else:
        cursor.execute('SELECT filename, content_type, data FROM files WHERE id = ?', (file_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        'filename': row['filename'],
        'content_type': row['content_type'] or 'application/octet-stream',
        'data': bytes(row['data']) if row['data'] else b'',
    }


def delete_file(cursor, file_id):
    """Delete a file from the DB."""
    if IS_POSTGRES:
        cursor.execute('DELETE FROM files WHERE id = %s', (file_id,))
    else:
        cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))


# ── Audit & email ───────────────────────────────────────────────────────

def log_audit(document_id, action, actor=None, details=None, ip_address=None):
    conn = get_db()
    cursor = get_cursor(conn)
    if IS_POSTGRES:
        cursor.execute(
            'INSERT INTO audit_logs (document_id, action, actor, details, ip_address) VALUES (%s, %s, %s, %s, %s)',
            (document_id, action, actor, details, ip_address)
        )
    else:
        cursor.execute(
            'INSERT INTO audit_logs (document_id, action, actor, details, ip_address) VALUES (?, ?, ?, ?, ?)',
            (document_id, action, actor, details, ip_address)
        )
    conn.commit()
    conn.close()


def _build_email_html(signer_name, document_title, sign_url):
    return f"""\
<html>
<body style="font-family: Arial, sans-serif; color: #1e293b; line-height: 1.6; max-width: 600px; margin: 0 auto;">
    <div style="background: #2563eb; color: white; padding: 1.5rem; text-align: center;">
        <h1 style="margin: 0; font-size: 1.25rem;">Ponca City Beauty College</h1>
        <p style="margin: 0.25rem 0 0 0; font-size: 0.9rem;">Academy of Cosmetology, Barbering & Esthetics</p>
    </div>
    <div style="padding: 1.5rem; background: #ffffff;">
        <p>Hello {signer_name or 'Student'},</p>
        <p>You have a document ready for your electronic signature:</p>
        <div style="background: #f8fafc; border-left: 4px solid #2563eb; padding: 1rem; margin: 1rem 0;">
            <strong>{document_title}</strong>
        </div>
        <p>Please review the document and sign it using the secure link below:</p>
        <div style="text-align: center; margin: 2rem 0;">
            <a href="{sign_url}" style="background: #2563eb; color: white; padding: 0.75rem 1.5rem; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: 600;">Review & Sign Document</a>
        </div>
        <p style="font-size: 0.85rem; color: #64748b;">Or copy and paste this link into your browser:<br>{sign_url}</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 1.5rem 0;">
        <p style="font-size: 0.85rem; color: #64748b;">
            This is a secure document signing request from Ponca City Beauty College.
            Your electronic signature is legally binding. If you did not expect this email, please disregard it.
        </p>
    </div>
    <div style="background: #f8fafc; padding: 1rem; text-align: center; font-size: 0.8rem; color: #64748b;">
        Ponca City Beauty College<br>
        Secure Document Management System
    </div>
</body>
</html>"""


def send_signature_email(to_email, signer_name, document_title, sign_url):
    subject = f"Document Ready for Signature — {document_title}"
    html_content = _build_email_html(signer_name, document_title, sign_url)

    # ── Try SendGrid first ────────────────────────────────────────────
    if SENDGRID_AVAILABLE and SENDGRID_API_KEY:
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            message = Mail(
                from_email=FROM_EMAIL,
                to_emails=to_email,
                subject=subject,
                html_content=html_content
            )
            response = sg.send(message)
            if response.status_code in (200, 201, 202):
                return True
        except Exception as e:
            print(f"[email] SendGrid failed: {e}")

    # ── Fallback: Resend HTTP API (HTTPS, never blocked) ─────────────
    # Render blocks SMTP port 587, so we use Resend's REST API instead
    if SMTP_HOST == 'smtp.resend.com' and SMTP_PASSWORD:
        try:
            import httpx
            resp = httpx.post(
                'https://api.resend.com/emails',
                headers={
                    'Authorization': f'Bearer {SMTP_PASSWORD}',
                    'Content-Type': 'application/json',
                },
                json={
                    'from': FROM_EMAIL,
                    'to': [to_email],
                    'subject': subject,
                    'html': html_content,
                },
                timeout=30.0,
            )
            if resp.status_code in (200, 202):
                print(f"[email] Sent via Resend HTTP API to {to_email}")
                return True
            else:
                print(f"[email] Resend HTTP API error {resp.status_code}: {resp.text}")
        except Exception as e:
            import traceback
            print(f"[email] Resend HTTP API failed: {e}")
            traceback.print_exc()

    # ── Final fallback: SMTP (for local dev / other providers) ────────
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = FROM_EMAIL
            msg['To'] = to_email
            msg.attach(MIMEText(html_content, 'html'))

            if SMTP_USE_TLS:
                server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)

            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
            server.quit()
            print(f"[email] Sent via SMTP to {to_email}")
            return True
        except Exception as e:
            import traceback
            print(f"[email] SMTP failed: {e}")
            traceback.print_exc()

    return False


# ── Auth helpers ────────────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ── Routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if session.get('admin_logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Welcome to Ponca City Beauty College Document System!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('''
            SELECT d.*,
                   COUNT(s.id) as total_requests,
                   COALESCE(SUM(CASE WHEN s.status = 'signed' THEN 1 ELSE 0 END), 0) as signed_count
            FROM documents d
            LEFT JOIN sign_requests s ON d.id = s.document_id
            GROUP BY d.id
            ORDER BY d.uploaded_at DESC
        ''')
    else:
        cursor.execute('''
            SELECT d.*,
                   COUNT(s.id) as total_requests,
                   SUM(CASE WHEN s.status = 'signed' THEN 1 ELSE 0 END) as signed_count
            FROM documents d
            LEFT JOIN sign_requests s ON d.id = s.document_id
            GROUP BY d.id
            ORDER BY d.uploaded_at DESC
        ''')
    documents = cursor.fetchall()

    cursor.execute('''
        SELECT a.*, d.title as document_title
        FROM audit_logs a
        LEFT JOIN documents d ON a.document_id = d.id
        ORDER BY a.timestamp DESC
        LIMIT 50
    ''')
    audit_logs = cursor.fetchall()
    conn.close()

    return render_template('dashboard.html', documents=documents, audit_logs=audit_logs)


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(request.url)

        file = request.files['pdf_file']
        title = request.form.get('title', '').strip()

        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(request.url)
        if not title:
            flash('Please enter a document title.', 'danger')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            file_bytes = file.read()

            conn = get_db()
            cursor = get_cursor(conn)

            # Store file in DB
            file_id = save_file(cursor, original_filename, 'application/pdf', file_bytes)

            if IS_POSTGRES:
                cursor.execute(
                    'INSERT INTO documents (title, filename, file_id, upload_ip, created_by) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                    (title, original_filename, file_id, request.remote_addr, session.get('admin_username'))
                )
            else:
                cursor.execute(
                    'INSERT INTO documents (title, filename, file_id, upload_ip, created_by) VALUES (?, ?, ?, ?, ?)',
                    (title, original_filename, file_id, request.remote_addr, session.get('admin_username'))
                )
            document_id = last_id(cursor)
            conn.commit()
            conn.close()

            log_audit(document_id, 'DOCUMENT_UPLOADED',
                     actor=session.get('admin_username'),
                     details=f"Uploaded: {original_filename}",
                     ip_address=request.remote_addr)

            flash(f'Document "{title}" uploaded successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Only PDF files are allowed.', 'danger')

    return render_template('upload.html')


@app.route('/document/<int:doc_id>')
@login_required
def document_detail(doc_id):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT * FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('SELECT * FROM documents WHERE id = ?', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        conn.close()
        abort(404)

    if IS_POSTGRES:
        cursor.execute('SELECT * FROM sign_requests WHERE document_id = %s ORDER BY created_at DESC', (doc_id,))
        cursor.execute('SELECT * FROM audit_logs WHERE document_id = %s ORDER BY timestamp DESC', (doc_id,))
    else:
        cursor.execute('SELECT * FROM sign_requests WHERE document_id = ? ORDER BY created_at DESC', (doc_id,))
        cursor.execute('SELECT * FROM audit_logs WHERE document_id = ? ORDER BY timestamp DESC', (doc_id,))

    # Need to run queries separately for psycopg2
    sign_requests = cursor.fetchall()
    if IS_POSTGRES:
        cursor.execute('SELECT * FROM audit_logs WHERE document_id = %s ORDER BY timestamp DESC', (doc_id,))
    else:
        cursor.execute('SELECT * FROM audit_logs WHERE document_id = ? ORDER BY timestamp DESC', (doc_id,))
    audit_logs = cursor.fetchall()

    conn.close()
    return render_template('document.html', document=doc, sign_requests=sign_requests, audit_logs=audit_logs)


@app.route('/create-sign-link/<int:doc_id>', methods=['POST'])
@login_required
def create_sign_link(doc_id):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT * FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('SELECT * FROM documents WHERE id = ?', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        conn.close()
        abort(404)

    signer_name = request.form.get('signer_name', '').strip()
    signer_email = request.form.get('signer_email', '').strip()
    token = str(uuid.uuid4())

    if IS_POSTGRES:
        cursor.execute(
            'INSERT INTO sign_requests (document_id, token, signer_name, signer_email) VALUES (%s, %s, %s, %s)',
            (doc_id, token, signer_name or None, signer_email or None)
        )
    else:
        cursor.execute(
            'INSERT INTO sign_requests (document_id, token, signer_name, signer_email) VALUES (?, ?, ?, ?)',
            (doc_id, token, signer_name or None, signer_email or None)
        )
    conn.commit()
    conn.close()

    log_audit(doc_id, 'SIGN_LINK_CREATED',
             actor=session.get('admin_username'),
             details=f"Token: {token}, For: {signer_name or 'Unnamed'}",
             ip_address=request.remote_addr)

    sign_url = url_for('sign_document', token=token, _external=True)

    email_sent = False
    if signer_email:
        email_sent = send_signature_email(signer_email, signer_name, doc['title'], sign_url)
        if email_sent:
            flash(f'Email sent to {signer_email}! Signing link also available below.', 'success')
            log_audit(doc_id, 'EMAIL_SENT',
                     actor=session.get('admin_username'),
                     details=f"Sent to: {signer_email}",
                     ip_address=request.remote_addr)
        else:
            flash(f'Could not send email to {signer_email}. Please send the link manually.', 'warning')
    else:
        flash(f'Signing link created! URL: {sign_url}', 'success')

    return redirect(url_for('document_detail', doc_id=doc_id))


@app.route('/sign/<token>', methods=['GET', 'POST'])
def sign_document(token):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('''
            SELECT s.*, d.title, d.file_id, d.filename as original_filename, d.id as doc_id
            FROM sign_requests s
            JOIN documents d ON s.document_id = d.id
            WHERE s.token = %s
        ''', (token,))
    else:
        cursor.execute('''
            SELECT s.*, d.title, d.file_id, d.filename as original_filename, d.id as doc_id
            FROM sign_requests s
            JOIN documents d ON s.document_id = d.id
            WHERE s.token = ?
        ''', (token,))
    sign_req = cursor.fetchone()

    if not sign_req:
        conn.close()
        abort(404)

    if sign_req['status'] == 'signed':
        conn.close()
        return render_template('already_signed.html', sign_req=sign_req)

    if request.method == 'POST':
        signer_name = request.form.get('signer_name', '').strip()
        signer_email = request.form.get('signer_email', '').strip()
        typed_name = request.form.get('typed_name', '').strip()
        signature_data = request.form.get('signature_data', '').strip()

        if not signer_name:
            flash('Please enter your full name.', 'danger')
            conn.close()
            return render_template('sign.html', doc=sign_req, token=token)
        if not typed_name:
            flash('Please type your name in the signature field.', 'danger')
            conn.close()
            return render_template('sign.html', doc=sign_req, token=token)

        # Save signature image
        sig_file_id = None
        if signature_data and signature_data.startswith('data:image/png;base64,'):
            import base64
            img_data = signature_data.split(',')[1]
            img_bytes = base64.b64decode(img_data)
            sig_file_id = save_file(cursor, f"sig_{token}.png", 'image/png', img_bytes)

        if IS_POSTGRES:
            cursor.execute('''
                UPDATE sign_requests
                SET status = 'signed',
                    signed_at = CURRENT_TIMESTAMP,
                    sign_ip = %s,
                    signer_name = %s,
                    signer_email = %s,
                    typed_name = %s,
                    signature_file_id = %s
                WHERE token = %s
            ''', (request.remote_addr, signer_name, signer_email, typed_name, sig_file_id, token))
            cursor.execute(
                "UPDATE documents SET status = 'signed' WHERE id = %s",
                (sign_req['doc_id'],)
            )
        else:
            cursor.execute('''
                UPDATE sign_requests
                SET status = 'signed',
                    signed_at = CURRENT_TIMESTAMP,
                    sign_ip = ?,
                    signer_name = ?,
                    signer_email = ?,
                    typed_name = ?,
                    signature_file_id = ?
                WHERE token = ?
            ''', (request.remote_addr, signer_name, signer_email, typed_name, sig_file_id, token))
            cursor.execute(
                "UPDATE documents SET status = 'signed' WHERE id = ?",
                (sign_req['doc_id'],)
            )

        conn.commit()
        conn.close()

        log_audit(sign_req['doc_id'], 'DOCUMENT_SIGNED',
                 actor=signer_name,
                 details=f"Signed by: {signer_name}, Method: Typed + Drawn",
                 ip_address=request.remote_addr)

        return render_template('sign_success.html', sign_req=sign_req, signer_name=signer_name)

    conn.close()
    return render_template('sign.html', doc=sign_req, token=token)


@app.route('/download/<int:doc_id>')
@login_required
def download_document(doc_id):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT file_id, filename FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('SELECT file_id, filename FROM documents WHERE id = ?', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        conn.close()
        abort(404)

    f = get_file(cursor, doc['file_id'])
    conn.close()
    if not f:
        abort(404)

    return send_file(
        BytesIO(f['data']),
        mimetype='application/pdf',
        download_name=doc['filename'],
        as_attachment=True
    )


@app.route('/download-signature/<token>')
@login_required
def download_signature(token):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT signature_file_id FROM sign_requests WHERE token = %s', (token,))
    else:
        cursor.execute('SELECT signature_file_id FROM sign_requests WHERE token = ?', (token,))
    sign_req = cursor.fetchone()

    if not sign_req or not sign_req['signature_file_id']:
        conn.close()
        abort(404)

    f = get_file(cursor, sign_req['signature_file_id'])
    conn.close()
    if not f:
        abort(404)

    return send_file(
        BytesIO(f['data']),
        mimetype='image/png',
        download_name=f"signature_{token}.png",
        as_attachment=True
    )


@app.route('/delete/<int:doc_id>', methods=['POST'])
@login_required
def delete_document(doc_id):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT file_id FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('SELECT file_id FROM documents WHERE id = ?', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        conn.close()
        abort(404)

    # Delete associated signature files
    if IS_POSTGRES:
        cursor.execute('SELECT signature_file_id FROM sign_requests WHERE document_id = %s', (doc_id,))
    else:
        cursor.execute('SELECT signature_file_id FROM sign_requests WHERE document_id = ?', (doc_id,))
    sigs = cursor.fetchall()
    for sr in sigs:
        if sr['signature_file_id']:
            delete_file(cursor, sr['signature_file_id'])

    # Delete main document file
    delete_file(cursor, doc['file_id'])

    if IS_POSTGRES:
        cursor.execute('DELETE FROM sign_requests WHERE document_id = %s', (doc_id,))
        cursor.execute('DELETE FROM audit_logs WHERE document_id = %s', (doc_id,))
        cursor.execute('DELETE FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('DELETE FROM sign_requests WHERE document_id = ?', (doc_id,))
        cursor.execute('DELETE FROM audit_logs WHERE document_id = ?', (doc_id,))
        cursor.execute('DELETE FROM documents WHERE id = ?', (doc_id,))

    conn.commit()
    conn.close()

    flash('Document deleted successfully.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/view-pdf/<int:doc_id>')
def view_pdf(doc_id):
    conn = get_db()
    cursor = get_cursor(conn)

    if IS_POSTGRES:
        cursor.execute('SELECT file_id FROM documents WHERE id = %s', (doc_id,))
    else:
        cursor.execute('SELECT file_id FROM documents WHERE id = ?', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        conn.close()
        abort(404)

    f = get_file(cursor, doc['file_id'])
    conn.close()
    if not f:
        abort(404)

    return send_file(BytesIO(f['data']), mimetype='application/pdf')


@app.route('/backup')
@login_required
def backup_database():
    if IS_POSTGRES:
        flash('PostgreSQL mode active — backups are handled by your database provider.', 'info')
        return redirect(url_for('dashboard'))

    from flask import send_file
    if not DATABASE.exists():
        abort(404)
    return send_file(
        DATABASE,
        mimetype='application/x-sqlite3',
        as_attachment=True,
        download_name=f'pcbc_backup_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    )


# ── Health & status ─────────────────────────────────────────────────────

@app.route('/debug-email')
@login_required
def debug_email():
    """Test email configuration and show detailed diagnostics."""
    import smtplib
    import traceback

    try:
        results = []
        results.append(f"SMTP_HOST: {SMTP_HOST}")
        results.append(f"SMTP_PORT: {SMTP_PORT}")
        results.append(f"SMTP_USER: {SMTP_USER}")
        results.append(f"SMTP_PASSWORD: {'SET' if SMTP_PASSWORD else 'NOT SET'}")
        results.append(f"SMTP_USE_TLS: {SMTP_USE_TLS}")
        results.append(f"FROM_EMAIL: {FROM_EMAIL}")
        results.append(f"SENDGRID_API_KEY: {'SET' if SENDGRID_API_KEY else 'NOT SET'}")
        results.append("")

        # Test Resend HTTP API
        if SMTP_HOST == 'smtp.resend.com' and SMTP_PASSWORD:
            try:
                import httpx
                resp = httpx.post(
                    'https://api.resend.com/emails',
                    headers={
                        'Authorization': f'Bearer {SMTP_PASSWORD}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'from': FROM_EMAIL,
                        'to': ['matt.janway@gmail.com'],
                        'subject': 'PCBC Test Email',
                        'html': '<p>This is a test from the debug endpoint.</p>',
                    },
                    timeout=30.0,
                )
                results.append(f"Resend HTTP status: {resp.status_code}")
                results.append(f"Resend response: {resp.text}")
                if resp.status_code in (200, 202):
                    results.append("✅ RESEND HTTP API SUCCESS")
                else:
                    results.append("❌ RESEND HTTP API FAILED")
            except Exception as e:
                results.append(f"❌ RESEND HTTP EXCEPTION: {e}")
                results.append(traceback.format_exc())
        else:
            results.append("❌ RESEND NOT CONFIGURED")

        results.append("")

        # Test SMTP connection with short timeout
        if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
            try:
                if SMTP_USE_TLS:
                    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
                    server.starttls()
                else:
                    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)

                server.login(SMTP_USER, SMTP_PASSWORD)
                results.append("✅ SMTP LOGIN SUCCESS")
                server.quit()
            except Exception as e:
                results.append(f"❌ SMTP FAILED: {e}")
                results.append("")
                results.append("Full traceback:")
                results.append(traceback.format_exc())
        else:
            results.append("❌ SMTP NOT CONFIGURED")

        return '<pre style="font-family:monospace;white-space:pre-wrap;padding:20px">' + '\n'.join(results) + '</pre>'
    except Exception as e:
        return '<pre style="font-family:monospace;white-space:pre-wrap;padding:20px;color:red">ROUTE ERROR: ' + str(e) + '\n' + traceback.format_exc() + '</pre>'


@app.route('/health')
def health_check():
    """Render-compatible health endpoint. Returns 200 only if DB is reachable."""
    try:
        conn = get_db()
        cursor = get_cursor(conn)
        if IS_POSTGRES:
            cursor.execute('SELECT 1')
        else:
            cursor.execute('SELECT 1')
        cursor.fetchone()
        conn.close()
        return {
            'status': 'healthy',
            'database': 'connected',
            'mode': 'postgresql' if IS_POSTGRES else 'sqlite',
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }, 200
    except Exception as e:
        return {
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }, 503


@app.route('/status')
@login_required
def status_page():
    """Admin status dashboard."""
    conn = get_db()
    cursor = get_cursor(conn)

    stats = {}
    try:
        cursor.execute('SELECT COUNT(*) as c FROM documents')
        stats['total_documents'] = cursor.fetchone()['c']

        cursor.execute('SELECT COUNT(*) as c FROM sign_requests')
        stats['total_sign_requests'] = cursor.fetchone()['c']

        cursor.execute("SELECT COUNT(*) as c FROM sign_requests WHERE status = 'signed'")
        stats['signed_count'] = cursor.fetchone()['c']

        cursor.execute('SELECT COUNT(*) as c FROM audit_logs')
        stats['total_audit_logs'] = cursor.fetchone()['c']

        cursor.execute('SELECT COUNT(*) as c FROM files')
        stats['total_files'] = cursor.fetchone()['c']

        cursor.execute('''
            SELECT d.title, s.signer_name, s.signed_at
            FROM sign_requests s
            JOIN documents d ON s.document_id = d.id
            WHERE s.status = 'signed'
            ORDER BY s.signed_at DESC
            LIMIT 5
        ''')
        stats['recent_signatures'] = cursor.fetchall()
    except Exception as e:
        stats['error'] = str(e)

    conn.close()

    return render_template('status.html',
        stats=stats,
        is_postgres=IS_POSTGRES,
        db_url_masked='***configured***' if DATABASE_URL else 'None (SQLite)',
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )


@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}


if __name__ == '__main__':
    print("=" * 60)
    print("Ponca City Beauty College - Document Signing System")
    print("=" * 60)
    print(f"Database: {'PostgreSQL (cloud)' if IS_POSTGRES else 'SQLite (local)'}")
    print("=" * 60)
    print("Default login: admin / ponca2024")
    print("Change password: set ADMIN_PASSWORD_HASH environment variable")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
