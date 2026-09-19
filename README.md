# Alumni Hub MVP

A working alumni mutual-value network designed to sit behind an existing WhatsApp group.

## Included

- Member registration and searchable directory
- Active Welfare Member vs Network-only status
- Annual welfare commitment, paid amount and balance
- Welfare contributions ledger and welfare events
- Welfare fund totals
- Jobs / business / tender / scholarship / mentorship board
- One-tap **Share to WhatsApp** links
- Annual legacy project tracker
- Polls and voting
- Admin member-status controls
- Private WhatsApp Assistant simulator
- Meta WhatsApp Cloud API webhook
- Bot commands: `BALANCE`, `JOBS`, `FUND`, `PROFILE`, `HELP`
- JSON summary endpoint at `/api/summary`
- PWA shell for phone installation
- Seed data for testing

## Run on Windows

```powershell
cd AlumniHub-MVP
py -m venv .venv
.\.venv\Scripts\activate
py -m pip install -r requirements.txt
py app.py
```

Open `http://127.0.0.1:5000`.

Try the WhatsApp simulator at `http://127.0.0.1:5000/assistant` using:

```text
Phone: 0712000001
Command: BALANCE
```

## WhatsApp Cloud API

Webhook path:

```text
/webhook/whatsapp
```

Production environment variables:

```text
WHATSAPP_ACCESS_TOKEN
WHATSAPP_PHONE_NUMBER_ID
WHATSAPP_VERIFY_TOKEN
BASE_URL
```

Configure Meta's callback URL as:

```text
https://YOUR-DOMAIN/webhook/whatsapp
```

The app uses private one-to-one bot replies. Your existing alumni WhatsApp group remains the community discussion space. Group announcements use the **Share to WhatsApp** button, so an admin can send prepared messages into the existing group without unofficial group scraping or automation.

For proactive business-initiated WhatsApp messages outside Meta's customer-service window, approved message templates are required.

## Deploy to Render

Upload the project to GitHub and create a Render Web Service. `render.yaml` is already included.

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
gunicorn app:app
```

## Before real public use

Add login/authentication, admin/treasurer roles, PostgreSQL, M-Pesa callbacks, audit logs, duplicate-vote prevention, privacy/consent controls, payment receipts and formal welfare eligibility rules.
