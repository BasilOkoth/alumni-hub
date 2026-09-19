# Alumni Hub — PostgreSQL on Render

This version is already configured to use PostgreSQL whenever `DATABASE_URL` is present.
SQLite remains only as a local-development fallback.

## Easiest deployment: Render Blueprint

1. Upload the **contents of this folder** to your GitHub repository.
2. In Render, choose **New → Blueprint**.
3. Select the GitHub repository.
4. Render reads `render.yaml` and creates:
   - the `alumni-hub` web service
   - the `alumni-hub-db` PostgreSQL database
   - the `DATABASE_URL` connection automatically
5. Set `BASE_URL` to your final public Render URL after the first deployment.
6. Leave WhatsApp variables blank until you are ready to connect Meta.

The app creates its database tables automatically on first start with `db.create_all()`.

## If you create the PostgreSQL database manually

Create a PostgreSQL database in Render, then open your web service and add:

```text
DATABASE_URL=<Render Internal Database URL>
```

Do **not** paste the database password into GitHub or `app.py`.

## Build settings

```text
Build command: pip install -r requirements.txt
Start command: gunicorn app:app
Health check: /health
```

## Confirm PostgreSQL is connected

After deployment visit:

```text
https://YOUR-APP.onrender.com/health
```

Expected response:

```json
{"status":"ok","database":"connected"}
```

## Local development

Without `DATABASE_URL`, the app uses SQLite automatically:

```powershell
py -m venv .venv
.\.venv\Scripts\activate
py -m pip install -r requirements.txt
py app.py
```

If you want local PostgreSQL instead, set `DATABASE_URL` before running the app.

## Important production note

This MVP currently calls `db.create_all()` automatically. That is fine for the first deployment. Once we begin changing live database columns and tables, add Alembic/Flask-Migrate so future schema changes are migrated safely without deleting member data.
