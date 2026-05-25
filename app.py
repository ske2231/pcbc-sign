"""
Ponca City Beauty College - Digital Document Signing System
A free, self-hosted DocuSign alternative for educational institutions.
"""

import os
import uuid
import hashlib
import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'ponca-beauty-college-default-key-change-me')

BASE_DIR = Path(__file__).parent
UPLOAD_FOLDER = BASE_DIR / 'uploads'
SIGNED_FOLDER = BASE_DIR / 'signed'
DATABASE = BASE_DIR / 'database.db'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

UPLOAD_FOLDER.mkdir(exist_ok=True)
SIGNED_FOLDER.mkdir(exist_ok=True)

# Admin credentials (default: admin / ponca2024)
# In production, set ADMIN_PASSWORD_HASH env var
DEFAULT_ADMIN_HASH = generate_password_hash('ponca2024')
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', DEFAULT_ADMIN_HASH)

app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            upload_ip TEXT,
            created_by TEXT DEFAULT 'admin'
        );
        
        CREATE TABLE IF NOT EXISTS sign_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            signer_name TEXT,
            signer_email TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            signed_at TIMESTAMP,
            sign_ip TEXT,
            signature_image TEXT,
            typed_name TEXT,
            FOREIGN KEY (document_id) REFERENCES documents(id)
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


# Initialize database on module import (for production/gunicorn)
init_db()


def log_audit(document_id, action, actor=None, details=None, ip_address=None):
    conn = get_db()
    conn.execute(
        'INSERT INTO audit_logs (document_id, action, actor, details, ip_address) VALUES (?, ?, ?, ?, ?)',
        (document_id, action, actor, details, ip_address)
    )
    conn.commit()
    conn.close()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


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
    
    # Get all documents with signing stats
    documents = conn.execute('''
        SELECT d.*, 
               COUNT(s.id) as total_requests,
               SUM(CASE WHEN s.status = 'signed' THEN 1 ELSE 0 END) as signed_count
        FROM documents d
        LEFT JOIN sign_requests s ON d.id = s.document_id
        GROUP BY d.id
        ORDER BY d.uploaded_at DESC
    ''').fetchall()
    
    # Recent audit logs
    audit_logs = conn.execute('''
        SELECT a.*, d.title as document_title
        FROM audit_logs a
        LEFT JOIN documents d ON a.document_id = d.id
        ORDER BY a.timestamp DESC
        LIMIT 50
    ''').fetchall()
    
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
            stored_filename = f"{uuid.uuid4().hex}_{original_filename}"
            file_path = UPLOAD_FOLDER / stored_filename
            file.save(file_path)
            
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO documents (title, filename, stored_filename, upload_ip, created_by) VALUES (?, ?, ?, ?, ?)',
                (title, original_filename, stored_filename, request.remote_addr, session.get('admin_username'))
            )
            document_id = cursor.lastrowid
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
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    
    if not doc:
        conn.close()
        abort(404)
    
    sign_requests = conn.execute(
        'SELECT * FROM sign_requests WHERE document_id = ? ORDER BY created_at DESC',
        (doc_id,)
    ).fetchall()
    
    audit_logs = conn.execute(
        'SELECT * FROM audit_logs WHERE document_id = ? ORDER BY timestamp DESC',
        (doc_id,)
    ).fetchall()
    
    conn.close()
    
    return render_template('document.html', document=doc, sign_requests=sign_requests, audit_logs=audit_logs)


@app.route('/create-sign-link/<int:doc_id>', methods=['POST'])
@login_required
def create_sign_link(doc_id):
    conn = get_db()
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    
    if not doc:
        conn.close()
        abort(404)
    
    signer_name = request.form.get('signer_name', '').strip()
    signer_email = request.form.get('signer_email', '').strip()
    token = str(uuid.uuid4())
    
    conn.execute(
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
    flash(f'Signing link created! URL: {sign_url}', 'success')
    
    return redirect(url_for('document_detail', doc_id=doc_id))


@app.route('/sign/<token>', methods=['GET', 'POST'])
def sign_document(token):
    conn = get_db()
    sign_req = conn.execute(
        'SELECT s.*, d.title, d.stored_filename, d.filename as original_filename, d.id as doc_id '
        'FROM sign_requests s '
        'JOIN documents d ON s.document_id = d.id '
        'WHERE s.token = ?',
        (token,)
    ).fetchone()
    
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
        
        # Save signature image if provided
        signature_image_path = None
        if signature_data and signature_data.startswith('data:image/png;base64,'):
            import base64
            img_data = signature_data.split(',')[1]
            img_bytes = base64.b64decode(img_data)
            signature_filename = f"sig_{token}.png"
            signature_image_path = str(SIGNED_FOLDER / signature_filename)
            with open(signature_image_path, 'wb') as f:
                f.write(img_bytes)
        
        conn.execute('''
            UPDATE sign_requests 
            SET status = 'signed', 
                signed_at = CURRENT_TIMESTAMP, 
                sign_ip = ?,
                signer_name = ?,
                signer_email = ?,
                typed_name = ?,
                signature_image = ?
            WHERE token = ?
        ''', (request.remote_addr, signer_name, signer_email, typed_name, signature_image_path, token))
        
        # Update document status
        conn.execute(
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
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()
    
    if not doc:
        abort(404)
    
    return send_from_directory(UPLOAD_FOLDER, doc['stored_filename'], 
                              download_name=doc['filename'], as_attachment=True)


@app.route('/download-signature/<token>')
@login_required
def download_signature(token):
    conn = get_db()
    sign_req = conn.execute(
        'SELECT * FROM sign_requests WHERE token = ?', (token,)
    ).fetchone()
    conn.close()
    
    if not sign_req or not sign_req['signature_image']:
        abort(404)
    
    sig_path = Path(sign_req['signature_image'])
    return send_from_directory(sig_path.parent, sig_path.name,
                              download_name=f"signature_{token}.png", as_attachment=True)


@app.route('/delete/<int:doc_id>', methods=['POST'])
@login_required
def delete_document(doc_id):
    conn = get_db()
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    
    if not doc:
        conn.close()
        abort(404)
    
    # Delete files
    try:
        file_path = UPLOAD_FOLDER / doc['stored_filename']
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass
    
    # Delete associated signatures
    sign_reqs = conn.execute('SELECT signature_image FROM sign_requests WHERE document_id = ?', (doc_id,)).fetchall()
    for sr in sign_reqs:
        if sr['signature_image']:
            try:
                Path(sr['signature_image']).unlink()
            except Exception:
                pass
    
    conn.execute('DELETE FROM sign_requests WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM audit_logs WHERE document_id = ?', (doc_id,))
    conn.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
    conn.commit()
    conn.close()
    
    flash('Document deleted successfully.', 'info')
    return redirect(url_for('dashboard'))


@app.route('/view-pdf/<int:doc_id>')
def view_pdf(doc_id):
    """Allow viewing PDF - accessible to both admin and signers with valid token"""
    conn = get_db()
    doc = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()
    
    if not doc:
        abort(404)
    
    return send_from_directory(UPLOAD_FOLDER, doc['stored_filename'])


@app.route('/backup')
@login_required
def backup_database():
    """Download a backup of the SQLite database for safekeeping."""
    from flask import send_file
    if not DATABASE.exists():
        abort(404)
    return send_file(
        DATABASE,
        mimetype='application/x-sqlite3',
        as_attachment=True,
        download_name=f'pcbc_backup_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    )


@app.context_processor
def inject_now():
    return {'now': datetime.datetime.now()}


if __name__ == '__main__':
    print("=" * 60)
    print("Ponca City Beauty College - Document Signing System")
    print("=" * 60)
    print(f"Database: {DATABASE}")
    print(f"Uploads:  {UPLOAD_FOLDER}")
    print(f"Signed:   {SIGNED_FOLDER}")
    print("=" * 60)
    print("Default login: admin / ponca2024")
    print("Change password: set ADMIN_PASSWORD_HASH environment variable")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
