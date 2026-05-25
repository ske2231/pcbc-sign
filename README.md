# Ponca City Beauty College - Document Signing System

A free, self-hosted DocuSign alternative built specifically for Ponca City Beauty College / Academy of Cosmetology Barbering and Esthetics. Upload PDFs, generate unique signing links for students, capture electronic signatures, and maintain a complete audit trail.

## Features

- **PDF Upload & Storage** - Securely upload and store PDF documents
- **Unique Signing Links** - Generate unguessable URLs for each student
- **Dual Signature Capture** - Students can draw their signature AND type their name
- **Audit Trail** - Every action logged with timestamp and IP address
- **Admin Dashboard** - View all documents, signature status, and audit logs
- **100% Free** - Uses Python, Flask, and SQLite. No subscriptions, no limits.

## Quick Start

### 1. Install Python
Make sure Python 3.8+ is installed on your computer.

### 2. Run the App

**Windows:**
```cmd
start.bat
```

**Mac/Linux:**
```bash
bash start.sh
```

Then open your browser to: **http://localhost:5000**

### 3. Log In
- Username: `admin`
- Password: `ponca2024`

### 4. Upload & Sign
1. Click **Upload New Document**
2. Select a PDF and give it a title
3. Click **Manage** on the document
4. Enter a **student name and email**, then click **Generate Sign Link**
5. The system **automatically emails the student** the signing link
6. Student opens the link, reviews the PDF, and signs
7. You see the status change to "Signed" on your dashboard

### Email Notifications (SendGrid)
When you enter a student's email and create a signing link, the app automatically sends a professional email with the signing link. To enable this:

1. Create a free account at [sendgrid.com](https://sendgrid.com)
2. Generate an API key with **Full Access** or **Restricted Access** with "Mail Send" permission
3. Add the API key to your Render environment variables as `SENDGRID_API_KEY`
4. Optionally change `FROM_EMAIL` (default: `documents@poncabeautycollege.edu`)

SendGrid's free tier includes **100 emails/day** — plenty for a beauty college.

## Security Notes

- **Change the default password immediately!** Set the `ADMIN_PASSWORD_HASH` environment variable or edit `app.py`.
- The app runs on your local network by default (`0.0.0.0:5000`). Only devices on your WiFi can access it.
- Signing links use random UUID tokens that are impossible to guess.
- All signatures, timestamps, and IP addresses are recorded in the SQLite database.
- Original PDFs are never modified. Signature images are stored separately.

## File Structure

```
ponca-sign/
├── app.py              # Main Flask application
├── database.db         # SQLite database (auto-created)
├── uploads/            # Original PDFs
├── signed/             # Signature images
├── venv/               # Python virtual environment
├── start.sh            # Linux/Mac startup script
├── start.bat           # Windows startup script
├── render.yaml         # Render.com deployment config
├── templates/          # HTML pages
├── static/             # CSS and JavaScript
└── README.md           # This file
```

## Changing the Admin Password

### Option 1: Environment Variable (Recommended)

**Windows:**
```cmd
set ADMIN_PASSWORD_HASH=your_hashed_password
```

**Mac/Linux:**
```bash
export ADMIN_PASSWORD_HASH=your_hashed_password
```

To generate a hashed password, run:
```python
from werkzeug.security import generate_password_hash
print(generate_password_hash('your_new_password'))
```

### Option 2: Edit app.py
Change this line near the top:
```python
DEFAULT_ADMIN_HASH = generate_password_hash('ponca2024')
```

## Backup & Data

Your data lives in three places:
1. `database.db` - All document metadata, signatures, and audit logs
2. `uploads/` - Original PDF files
3. `signed/` - Signature images

**To back up:** Copy these three items to a USB drive or cloud storage.

## Hosting Options

### Option 1: Local School Computer (Default)
Runs on a computer at your school. Other computers on the same WiFi can access it.

### Option 2: Render.com (Free Cloud Hosting)
Deploy online so students can sign from home or their phones. Render's free tier never expires.

#### Step 1: Generate Your Admin Password Hash
Before deploying, generate a secure password hash locally:
```bash
cd ponca-sign
source venv/bin/activate  # or venv\Scripts\activate on Windows
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_new_password'))"
```
Copy the long `scrypt:...` output.

#### Step 2: Create a GitHub Repo
```bash
git init
git add .
git commit -m "Initial commit"
```
Then create a new repo on GitHub and push.

#### Step 3: Deploy on Render
1. Go to [render.com](https://render.com) and sign up with GitHub
2. Click **New +** → **Blueprint**
3. Connect your GitHub repo
4. Render will read `render.yaml` automatically
5. **IMPORTANT:** In the environment variables section, replace the placeholder `ADMIN_PASSWORD_HASH` value with your real hash from Step 1
6. Click **Apply**
7. Wait 2-3 minutes for deployment

#### Step 4: Add SendGrid API Key (Optional but Recommended)
If you want automatic email notifications:
1. Go to [sendgrid.com](https://sendgrid.com) → create free account → Settings → API Keys → Create API Key
2. In your Render dashboard, click your service → **Environment** tab
3. Add a new variable:
   - Key: `SENDGRID_API_KEY`
   - Value: your SendGrid API key starting with `SG.`
4. Save — Render will redeploy

### Step 5: Access Your App
Render will give you a URL like `https://pcbc-document-sign.onrender.com`

**⚠️ CRITICAL RENDER NOTE:**
Render's free tier uses an **ephemeral filesystem**. This means:
- Your data survives server restarts ✅
- Your data is LOST if you redeploy or push code updates ❌

**To protect your data, download a backup regularly:**
1. Log into your admin dashboard
2. Go to `https://your-app.onrender.com/backup`
3. Save the `.db` file
4. Before any redeploy, download the backup, then upload it back afterward (via Render's shell or by replacing the file)

**Alternative:** If you outgrow the free tier, upgrade to Render's paid plan ($7/month) which includes a persistent disk, or switch to Render's free PostgreSQL database.

## Requirements

- Python 3.8+
- Flask + Gunicorn (installed automatically)

## License

This tool was built for Ponca City Beauty College. Use and modify freely.
