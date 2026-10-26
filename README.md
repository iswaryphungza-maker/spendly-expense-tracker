# Spendly — Private Daily Expenses Tracker

A responsive Flask expense tracker with individual user accounts. Each signed-in user can only access their own expenses. Built with Flask, Flask-Login, SQLAlchemy, CSRF-protected forms, and PostgreSQL support.

## Features

- Account registration and login (passwords are stored as secure hashes, never plain text)
- User-scoped expense add, edit, delete, search, filter, and CSV export
- Dashboard totals, category breakdown, and monthly chart
- INR formatting, payment methods, categories, notes, and responsive layout
- SQLite for local development; PostgreSQL via `DATABASE_URL` for hosting
- CSRF protection on forms and basic security headers

## Run locally

1. Install Python 3.10 or newer.
2. Extract this folder and open a terminal inside it.
3. Create and activate a virtual environment (optional but recommended):
   - Windows: `py -m venv .venv` then `.venv\\Scripts\\activate`
   - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Start: `python app.py`
6. Open `http://127.0.0.1:5000` and register an account.

Local data is stored in `expenses.db`. Keep a backup of that file if you have important local records.

## Free hosting (Render + Neon PostgreSQL)

Render free web services use an ephemeral filesystem, so **do not use the local SQLite file for hosted user data**. A free Render Postgres database currently expires after 30 days; use a separate PostgreSQL provider such as Neon if you need a free database for a hobby project. Free tiers can change, pause, or have usage limits, so review current terms and keep backups.

1. Create a GitHub account and a new **private** repository (you can keep the source private even though the deployed website will be public).
2. Upload/push all files from this project to the repository. Do not upload `.env`, database files, passwords, or database URLs.
3. Create a free PostgreSQL project at https://neon.tech/ and copy its connection string. Treat it as a password; do not share it publicly.
4. In Render, create a new **Web Service** and connect your GitHub repository.
5. Configure:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Plan: `Free`
6. In Render's Environment settings, set:
   - `SECRET_KEY`: generate a long random secret, or use Render's generated value from the Blueprint setup.
   - `DATABASE_URL`: paste the Neon PostgreSQL connection string (use the pooled URL if Neon provides one; include SSL settings as supplied).
7. Deploy. When the deploy succeeds, open the Render `onrender.com` URL, create your account, and share the public URL.

### Important notes before sharing

- Free web services can sleep after inactivity, so the first visit may take around a minute.
- A free database provider may pause inactive projects or change its free-tier terms. This setup is for learning/hobby use, not a guaranteed production service. Keep backups and upgrade if you need dependable long-term storage.
- This starter creates tables automatically on app startup. For a larger live service, add migrations, email verification, password reset, login rate limiting, automated backups, and a formal security review.
- All expense queries and edits are scoped to the logged-in user's ID. Do not remove these owner checks.
- Chart.js is loaded from a CDN; the chart feature requires internet access.
- Existing records from the old SQLite version are not automatically imported. This new version starts with a separate database unless you deliberately migrate data.
