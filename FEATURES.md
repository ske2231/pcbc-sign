# PCBC Document Sign — Quick Recap

**Ponca City Beauty College / Academy of Cosmetology Barbering and Esthetics**

A free, self-hosted alternative to DocuSign built specifically for our school.

---

## What It Does

- **Upload PDFs** — Enrollment agreements, consent forms, policy acknowledgments, or any document that needs a signature
- **Generate Unique Signing Links** — Create a private, unguessable URL for each student (no accidental access to other students' documents)
- **Capture Electronic Signatures** — Students draw their signature with a mouse or finger AND type their legal name for binding consent
- **View Documents In-Browser** — Students see the full PDF embedded on the signing page before they agree to anything
- **Track Status in Real Time** — Dashboard shows which documents are Pending vs. Signed at a glance
- **Full Audit Trail** — Every upload, link creation, view, and signature is logged with timestamp and IP address for compliance
- **Download Originals & Backups** — One-click download of original PDFs and the entire database for safekeeping
- **100% Free** — No subscriptions, no per-document fees, no user limits

---

## Who It's For

- Future students signing enrollment agreements
- Current students acknowledging policy updates
- Staff managing signed records for state board audits

---

## How It Works (3 Steps)

1. **Admin uploads a PDF** and clicks "Generate Sign Link"
2. **Link is sent to the student** via email, text, or QR code
3. **Student reviews, signs, and submits** — admin sees it instantly

---

## Security & Compliance

- Password-protected admin dashboard
- Random UUID tokens on every signing link (impossible to guess)
- SQLite database stores all records locally/securely
- Original PDFs are never modified; signatures stored separately
- Complete timestamp + IP logging for audit defense

---

## Live URL

https://pcbc-document-sign.onrender.com

---

## Tech Stack

Python + Flask + SQLite + Gunicorn + Render.com (Free Tier)
