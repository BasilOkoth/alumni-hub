
from functools import wraps
from urllib.parse import quote
from datetime import datetime
import os

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///alumnihub.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

WA_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WA_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "alumnihub-verify-token")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "")
COMMUNITY_NAME = os.environ.get("COMMUNITY_NAME", "Alumni Circle")
COMMUNITY_TAGLINE = os.environ.get("COMMUNITY_TAGLINE", "Support each other. Open doors. Build a legacy.")
try:
    COMMUNITY_SIZE = int(os.environ.get("COMMUNITY_SIZE", "66"))
except ValueError:
    COMMUNITY_SIZE = 66


class Member(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    phone = db.Column(db.String(40), unique=True, nullable=False)
    class_year = db.Column(db.String(40), default="")
    location = db.Column(db.String(120), default="")
    profession = db.Column(db.String(140), default="")
    can_help = db.Column(db.Text, default="")
    looking_for = db.Column(db.Text, default="")
    welfare_status = db.Column(db.String(30), default="Network only")
    annual_commitment = db.Column(db.Float, default=0)
    amount_paid = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def welfare_balance(self):
        return max((self.annual_commitment or 0) - (self.amount_paid or 0), 0)

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0].upper() for p in parts[:2]) or "A"


class Contribution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(120), default="")
    kind = db.Column(db.String(50), default="Welfare")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship("Member", backref="contributions")


class WelfareEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    event_type = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    approved_support = db.Column(db.Float, default=0)
    status = db.Column(db.String(40), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship("Member", backref="welfare_events")


class Opportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), default="Job")
    organization = db.Column(db.String(160), default="")
    location = db.Column(db.String(120), default="")
    deadline = db.Column(db.String(50), default="")
    link = db.Column(db.String(500), default="")
    description = db.Column(db.Text, default="")
    posted_by = db.Column(db.String(140), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LegacyProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    target_amount = db.Column(db.Float, default=0)
    amount_raised = db.Column(db.Float, default=0)
    status = db.Column(db.String(40), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(220), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    options = db.relationship("PollOption", backref="poll", cascade="all, delete-orphan")


class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("poll.id"), nullable=False)
    label = db.Column(db.String(180), nullable=False)
    votes = db.Column(db.Integer, default=0)


def normalize_phone(phone):
    p = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if p.startswith("0") and len(p) >= 10:
        p = "+254" + p[1:]
    elif p.startswith("254"):
        p = "+" + p
    return p


def share_url(text):
    return "https://wa.me/?text=" + quote(text)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Committee access is required for that action.", "error")
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def send_whatsapp_text(to_phone, body):
    if not (WA_TOKEN and WA_PHONE_NUMBER_ID):
        return {"ok": False, "reason": "WhatsApp credentials not configured"}
    url = f"https://graph.facebook.com/v23.0/{WA_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": normalize_phone(to_phone).replace("+", ""),
        "type": "text",
        "text": {"body": body},
    }
    headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"text": r.text}
    return {"ok": r.ok, "status": r.status_code, "data": data}


def bot_response(member, command):
    cmd = command.strip().upper()
    if not member:
        return f"Your number is not registered in {COMMUNITY_NAME}.\nJoin here: {BASE_URL}/register"
    if cmd in ("BALANCE", "WELFARE"):
        return (
            f"{COMMUNITY_NAME.upper()} — WELFARE\n\n"
            f"Member: {member.name}\nStatus: {member.welfare_status}\n"
            f"Annual commitment: KES {member.annual_commitment:,.0f}\n"
            f"Paid: KES {member.amount_paid:,.0f}\nBalance: KES {member.welfare_balance:,.0f}\n\n"
            f"View: {BASE_URL}/member/{member.id}"
        )
    if cmd == "JOBS":
        items = Opportunity.query.order_by(Opportunity.created_at.desc()).limit(3).all()
        if not items:
            return "There are no current opportunities yet."
        lines = [f"{COMMUNITY_NAME.upper()} — OPPORTUNITIES", ""]
        for item in items:
            lines.append(f"• {item.title} — {item.organization or item.category}")
            if item.deadline:
                lines.append(f"  Deadline: {item.deadline}")
        lines += ["", f"View all: {BASE_URL}/opportunities"]
        return "\n".join(lines)
    if cmd == "FUND":
        project = LegacyProject.query.filter_by(status="Active").order_by(LegacyProject.id.desc()).first()
        if not project:
            return "There is no active legacy project right now."
        pct = 0 if not project.target_amount else min(100, (project.amount_raised / project.target_amount) * 100)
        return (
            f"{COMMUNITY_NAME.upper()} — LEGACY\n\n{project.title}\n"
            f"Target: KES {project.target_amount:,.0f}\nRaised: KES {project.amount_raised:,.0f}\n"
            f"Progress: {pct:.0f}%\n\nDetails: {BASE_URL}/legacy"
        )
    if cmd == "PROFILE":
        return (
            f"{member.name}\nClass: {member.class_year or 'Not set'}\nLocation: {member.location or 'Not set'}\n"
            f"Profession: {member.profession or 'Not set'}\nCan help with: {member.can_help or 'Not set'}\n"
            f"Looking for: {member.looking_for or 'Not set'}\n\nProfile: {BASE_URL}/member/{member.id}"
        )
    return (
        f"{COMMUNITY_NAME.upper()} ASSISTANT\n\n"
        "Reply with:\nBALANCE — welfare account\nJOBS — latest opportunities\n"
        "FUND — legacy project progress\nPROFILE — your profile\nHELP — this menu"
    )


@app.context_processor
def helpers():
    return {
        "share_url": share_url,
        "community_name": COMMUNITY_NAME,
        "community_tagline": COMMUNITY_TAGLINE,
        "community_size": COMMUNITY_SIZE,
    }


@app.route("/")
def dashboard():
    members = Member.query.order_by(Member.name).all()
    active_count = Member.query.filter_by(welfare_status="Active").count()
    contributions = Contribution.query.filter_by(kind="Welfare").all()
    fund_total = sum(c.amount for c in contributions)
    events_all = WelfareEvent.query.order_by(WelfareEvent.created_at.desc()).all()
    paid_out = sum(e.approved_support for e in events_all if e.status == "Paid")
    fund_balance = fund_total - paid_out
    events = events_all[:4]
    opportunities = Opportunity.query.order_by(Opportunity.created_at.desc()).limit(5).all()
    opportunity_count = Opportunity.query.count()
    project = LegacyProject.query.filter_by(status="Active").order_by(LegacyProject.id.desc()).first()
    polls = Poll.query.filter_by(active=True).order_by(Poll.created_at.desc()).all()
    registration_pct = min(100, (len(members) / COMMUNITY_SIZE * 100)) if COMMUNITY_SIZE else 0
    return render_template(
        "dashboard.html",
        members=members,
        active_count=active_count,
        fund_total=fund_total,
        fund_balance=fund_balance,
        events=events,
        opportunities=opportunities,
        opportunity_count=opportunity_count,
        project=project,
        polls=polls,
        registration_pct=registration_pct,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        phone = normalize_phone(request.form["phone"])
        existing = Member.query.filter_by(phone=phone).first()
        if existing:
            flash("That WhatsApp number is already registered.", "error")
            return redirect(url_for("member_profile", member_id=existing.id))
        member = Member(
            name=request.form["name"].strip(),
            phone=phone,
            class_year=request.form.get("class_year", "").strip(),
            location=request.form.get("location", "").strip(),
            profession=request.form.get("profession", "").strip(),
            can_help=request.form.get("can_help", "").strip(),
            looking_for=request.form.get("looking_for", "").strip(),
            welfare_status=request.form.get("welfare_status", "Network only"),
            annual_commitment=float(request.form.get("annual_commitment", 0) or 0),
        )
        db.session.add(member)
        db.session.commit()
        flash("Welcome to the circle. Your profile is now live.", "success")
        return redirect(url_for("member_profile", member_id=member.id))
    return render_template("register.html")


@app.route("/members")
def members():
    q = request.args.get("q", "").strip().lower()
    items = Member.query.order_by(Member.name).all()
    if q:
        items = [
            m for m in items
            if q in " ".join([m.name or "", m.profession or "", m.location or "", m.can_help or "", m.looking_for or ""]).lower()
        ]
    return render_template("members.html", members=items, q=q)


@app.route("/member/<int:member_id>")
def member_profile(member_id):
    return render_template("member.html", member=Member.query.get_or_404(member_id))


@app.route("/opportunities", methods=["GET", "POST"])
def opportunities():
    if request.method == "POST":
        item = Opportunity(
            title=request.form["title"].strip(),
            category=request.form.get("category", "Job"),
            organization=request.form.get("organization", "").strip(),
            location=request.form.get("location", "").strip(),
            deadline=request.form.get("deadline", "").strip(),
            link=request.form.get("link", "").strip(),
            description=request.form.get("description", "").strip(),
            posted_by=request.form.get("posted_by", "").strip(),
        )
        db.session.add(item)
        db.session.commit()
        flash("Opportunity shared with the network.", "success")
        return redirect(url_for("opportunities"))
    return render_template("opportunities.html", opportunities=Opportunity.query.order_by(Opportunity.created_at.desc()).all())


@app.route("/welfare")
def welfare():
    members = Member.query.order_by(Member.name).all()
    events = WelfareEvent.query.order_by(WelfareEvent.created_at.desc()).all()
    contributions = Contribution.query.order_by(Contribution.created_at.desc()).limit(50).all()
    fund_total = sum(c.amount for c in Contribution.query.filter_by(kind="Welfare").all())
    total_paid_out = sum(e.approved_support for e in events if e.status == "Paid")
    return render_template(
        "welfare.html",
        members=members,
        events=events,
        contributions=contributions,
        fund_total=fund_total,
        total_paid_out=total_paid_out,
        current_balance=fund_total - total_paid_out,
    )


@app.route("/welfare/contribution", methods=["POST"])
@admin_required
def add_contribution():
    member = Member.query.get_or_404(int(request.form["member_id"]))
    amount = float(request.form["amount"])
    db.session.add(Contribution(member_id=member.id, amount=amount, reference=request.form.get("reference", "").strip()))
    member.amount_paid = (member.amount_paid or 0) + amount
    db.session.commit()
    flash("Contribution recorded.", "success")
    return redirect(url_for("welfare"))


@app.route("/welfare/event", methods=["POST"])
@admin_required
def add_welfare_event():
    event = WelfareEvent(
        member_id=int(request.form["member_id"]),
        event_type=request.form["event_type"].strip(),
        description=request.form.get("description", "").strip(),
        approved_support=float(request.form.get("approved_support", 0) or 0),
        status=request.form.get("status", "Approved"),
    )
    db.session.add(event)
    db.session.commit()
    flash("Welfare event recorded.", "success")
    return redirect(url_for("welfare"))


@app.route("/legacy", methods=["GET", "POST"])
def legacy():
    if request.method == "POST":
        if not session.get("is_admin"):
            flash("Committee access is required to change legacy projects.", "error")
            return redirect(url_for("admin_login", next=url_for("legacy")))
        action = request.form.get("action")
        if action == "project":
            db.session.add(LegacyProject(
                title=request.form["title"].strip(),
                description=request.form.get("description", "").strip(),
                target_amount=float(request.form.get("target_amount", 0) or 0),
                amount_raised=float(request.form.get("amount_raised", 0) or 0),
            ))
        elif action == "update":
            project = LegacyProject.query.get_or_404(int(request.form["project_id"]))
            project.amount_raised = float(request.form.get("amount_raised", project.amount_raised) or 0)
        elif action == "poll":
            poll = Poll(question=request.form["question"].strip())
            db.session.add(poll)
            db.session.flush()
            for key in ("option1", "option2", "option3"):
                value = request.form.get(key, "").strip()
                if value:
                    db.session.add(PollOption(poll_id=poll.id, label=value))
        db.session.commit()
        flash("Legacy section updated.", "success")
        return redirect(url_for("legacy"))
    return render_template(
        "legacy.html",
        projects=LegacyProject.query.order_by(LegacyProject.id.desc()).all(),
        polls=Poll.query.order_by(Poll.id.desc()).all(),
    )


@app.route("/poll/vote/<int:option_id>", methods=["POST"])
def vote(option_id):
    option = PollOption.query.get_or_404(option_id)
    option.votes = (option.votes or 0) + 1
    db.session.commit()
    flash("Your vote has been counted.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if not ADMIN_PIN:
            flash("Set ADMIN_PIN in Render before using committee access.", "error")
        elif request.form.get("pin", "") == ADMIN_PIN:
            session["is_admin"] = True
            flash("Committee access unlocked.", "success")
            return redirect(request.args.get("next") or url_for("admin"))
        else:
            flash("That access code is incorrect.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Committee access closed.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin")
@admin_required
def admin():
    members = Member.query.order_by(Member.created_at.desc()).all()
    return render_template("admin.html", members=members)


@app.route("/admin/member/<int:member_id>/status", methods=["POST"])
@admin_required
def update_member_status(member_id):
    member = Member.query.get_or_404(member_id)
    member.welfare_status = request.form["welfare_status"]
    member.annual_commitment = float(request.form.get("annual_commitment", member.annual_commitment) or 0)
    db.session.commit()
    flash("Member welfare status updated.", "success")
    return redirect(url_for("admin"))


@app.route("/assistant", methods=["GET", "POST"])
def assistant_simulator():
    reply = None
    if request.method == "POST":
        phone = normalize_phone(request.form["phone"])
        member = Member.query.filter_by(phone=phone).first()
        reply = bot_response(member, request.form["command"])
    return render_template("assistant.html", reply=reply)


@app.route("/webhook/whatsapp", methods=["GET"])
def whatsapp_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        return challenge or "", 200
    return "Verification failed", 403


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    payload = request.get_json(silent=True) or {}
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        for msg in value.get("messages", []):
            if msg.get("type") != "text":
                continue
            phone = normalize_phone(msg.get("from", ""))
            member = Member.query.filter_by(phone=phone).first()
            reply = bot_response(member, msg["text"]["body"])
            send_whatsapp_text(phone, reply)
    except Exception as exc:
        app.logger.warning("Webhook parse error: %s", exc)
    return jsonify({"status": "ok"}), 200


@app.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected", "community": COMMUNITY_NAME}), 200
    except Exception as exc:
        return jsonify({"status": "error", "database": "unavailable", "detail": str(exc)}), 503


@app.route("/api/summary")
def api_summary():
    project = LegacyProject.query.filter_by(status="Active").order_by(LegacyProject.id.desc()).first()
    return jsonify({
        "community": COMMUNITY_NAME,
        "community_size": COMMUNITY_SIZE,
        "members": Member.query.count(),
        "active_welfare_members": Member.query.filter_by(welfare_status="Active").count(),
        "opportunities": Opportunity.query.count(),
        "legacy_project": None if not project else {
            "title": project.title,
            "target": project.target_amount,
            "raised": project.amount_raised,
        },
    })


def remove_old_demo_data():
    """Remove only the exact demo records shipped in the earlier prototype."""
    demo_phones = ["+254712000001", "+254712000002", "+254712000003", "+254712000004"]
    demo_members = Member.query.filter(Member.phone.in_(demo_phones)).all()
    for member in demo_members:
        Contribution.query.filter_by(member_id=member.id).delete(synchronize_session=False)
        WelfareEvent.query.filter_by(member_id=member.id).delete(synchronize_session=False)
        db.session.delete(member)

    for title in ["Procurement Officer", "Small Business Accounting Support"]:
        Opportunity.query.filter_by(title=title).delete(synchronize_session=False)

    LegacyProject.query.filter_by(title="School Library Renewal").delete(synchronize_session=False)
    old_poll = Poll.query.filter_by(question="Which project should the alumni prioritize next year?").first()
    if old_poll:
        db.session.delete(old_poll)
    db.session.commit()


with app.app_context():
    db.create_all()
    remove_old_demo_data()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
