
from functools import wraps
from urllib.parse import quote
from datetime import datetime, date, timedelta
import os
import json

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}

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

# M-PESA B2C integration. Keep MPESA_MODE=disabled until Safaricom onboarding is complete.
MPESA_MODE = os.environ.get("MPESA_MODE", "disabled").strip().lower()
MPESA_CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "").strip()
MPESA_CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "").strip()
MPESA_B2C_SHORTCODE = os.environ.get("MPESA_B2C_SHORTCODE", "").strip()
MPESA_INITIATOR_NAME = os.environ.get("MPESA_INITIATOR_NAME", "").strip()
MPESA_SECURITY_CREDENTIAL = os.environ.get("MPESA_SECURITY_CREDENTIAL", "").strip()
MPESA_RESULT_URL = os.environ.get("MPESA_RESULT_URL", f"{BASE_URL}/webhook/mpesa/b2c/result").strip()
MPESA_TIMEOUT_URL = os.environ.get("MPESA_TIMEOUT_URL", f"{BASE_URL}/webhook/mpesa/b2c/timeout").strip()
MPESA_COMMAND_ID = os.environ.get("MPESA_COMMAND_ID", "BusinessPayment").strip()
MPESA_AUTO_RELEASE = os.environ.get("MPESA_AUTO_RELEASE", "true").strip().lower() in {"1", "true", "yes", "on"}

def mpesa_base_url():
    if MPESA_MODE == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"

MPESA_OAUTH_URL = os.environ.get("MPESA_OAUTH_URL", f"{mpesa_base_url()}/oauth/v1/generate?grant_type=client_credentials").strip()
MPESA_B2C_URL = os.environ.get("MPESA_B2C_URL", f"{mpesa_base_url()}/mpesa/b2c/v1/paymentrequest").strip()


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


class HouseholdMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    full_name = db.Column(db.String(140), nullable=False)
    relationship = db.Column(db.String(30), nullable=False)
    phone = db.Column(db.String(40), default="")
    date_of_birth = db.Column(db.Date, nullable=True)
    verified = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    cover_start_date = db.Column(db.Date, default=date.today)
    member = db.relationship("Member", backref="household_members")


class WelfareRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    support_type = db.Column(db.String(80), nullable=False)
    relationship = db.Column(db.String(30), nullable=False)
    benefit_amount = db.Column(db.Float, default=0)
    max_claims_per_year = db.Column(db.Integer, default=1)
    waiting_days = db.Column(db.Integer, default=30)
    eligibility_notes = db.Column(db.Text, default="")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SupportCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=False)
    household_member_id = db.Column(db.Integer, db.ForeignKey("household_member.id"), nullable=True)
    covered_name = db.Column(db.String(140), nullable=False)
    relationship = db.Column(db.String(30), nullable=False)
    support_type = db.Column(db.String(80), nullable=False)
    event_date = db.Column(db.Date, default=date.today)
    description = db.Column(db.Text, default="")
    approved_support = db.Column(db.Float, default=0)
    status = db.Column(db.String(40), default="Pending")
    evidence_reference = db.Column(db.String(220), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship("Member", backref="support_cases")
    household_member = db.relationship("HouseholdMember", backref="support_cases")


class MemberPayoutProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), unique=True, nullable=False)
    payout_phone = db.Column(db.String(40), default="")
    next_of_kin_name = db.Column(db.String(140), default="")
    next_of_kin_phone = db.Column(db.String(40), default="")
    verified = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    member = db.relationship("Member", backref=db.backref("payout_profile", uselist=False))


class CommitteeApprover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    role = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(40), unique=True, nullable=False)
    pin_hash = db.Column(db.String(255), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    member = db.relationship("Member", foreign_keys=[member_id])


class CaseApproval(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("support_case.id"), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("committee_approver.id"), nullable=False)
    decision = db.Column(db.String(20), nullable=False, default="Approved")
    note = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    case = db.relationship("SupportCase", backref="case_approvals")
    approver = db.relationship("CommitteeApprover", backref="case_approvals")
    __table_args__ = (db.UniqueConstraint("case_id", "approver_id", name="uq_case_approver"),)


class CaseMaker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("support_case.id"), unique=True, nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("committee_approver.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    case = db.relationship("SupportCase", backref=db.backref("maker", uselist=False))
    approver = db.relationship("CommitteeApprover")


class PayoutInstruction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("support_case.id"), unique=True, nullable=False)
    beneficiary_name = db.Column(db.String(140), nullable=False)
    beneficiary_phone = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    required_approvals = db.Column(db.Integer, default=2)
    status = db.Column(db.String(40), default="Awaiting approvals")
    provider = db.Column(db.String(40), default="M-PESA B2C")
    provider_ref = db.Column(db.String(140), default="")
    conversation_id = db.Column(db.String(140), default="")
    originator_conversation_id = db.Column(db.String(140), default="")
    provider_payload = db.Column(db.Text, default="")
    requested_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    case = db.relationship("SupportCase", backref=db.backref("payout", uselist=False))


class WelfareFundConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reserve_floor = db.Column(db.Float, default=20000)
    small_payment_limit = db.Column(db.Float, default=10000)
    small_payment_approvals = db.Column(db.Integer, default=2)
    large_payment_approvals = db.Column(db.Integer, default=3)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("support_case.id"), nullable=True)
    actor_type = db.Column(db.String(40), nullable=False)
    actor_name = db.Column(db.String(140), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    case = db.relationship("SupportCase", backref="audit_logs")


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


def approver_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        approver_id = session.get("approver_id")
        approver = CommitteeApprover.query.get(approver_id) if approver_id else None
        if not approver or not approver.active:
            session.pop("approver_id", None)
            flash("Sign in with your committee approval PIN.", "error")
            return redirect(url_for("approval_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def committee_or_approver_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("is_admin"):
            return view(*args, **kwargs)
        approver_id = session.get("approver_id")
        approver = CommitteeApprover.query.get(approver_id) if approver_id else None
        if approver and approver.active:
            return view(*args, **kwargs)
        flash("Committee or approval access is required for that action.", "error")
        return redirect(url_for("approval_login", next=request.path))
    return wrapped


def get_fund_config():
    cfg = WelfareFundConfig.query.first()
    if not cfg:
        cfg = WelfareFundConfig(reserve_floor=20000, small_payment_limit=10000, small_payment_approvals=2, large_payment_approvals=3)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def audit(case_id, actor_type, actor_name, action, detail=""):
    db.session.add(AuditLog(case_id=case_id, actor_type=actor_type, actor_name=actor_name, action=action, detail=detail))


def fund_snapshot(exclude_payout_id=None):
    contributions = sum(c.amount for c in Contribution.query.filter_by(kind="Welfare").all())
    support_paid = sum(c.approved_support for c in SupportCase.query.filter_by(status="Paid").all())
    legacy_paid = sum(c.approved_support for c in WelfareEvent.query.filter_by(status="Paid").all())
    current_balance = contributions - support_paid - legacy_paid
    committed_q = PayoutInstruction.query.filter(PayoutInstruction.status.in_(["Awaiting approvals", "Ready", "Processing"]))
    if exclude_payout_id:
        committed_q = committed_q.filter(PayoutInstruction.id != exclude_payout_id)
    committed = sum(p.amount for p in committed_q.all())
    cfg = get_fund_config()
    available = max(current_balance - (cfg.reserve_floor or 0) - committed, 0)
    return {
        "contributions": contributions,
        "paid": support_paid + legacy_paid,
        "current_balance": current_balance,
        "committed": committed,
        "reserve_floor": cfg.reserve_floor or 0,
        "available": available,
    }


def required_approvals_for_amount(amount):
    cfg = get_fund_config()
    return max(1, cfg.small_payment_approvals if amount <= (cfg.small_payment_limit or 0) else cfg.large_payment_approvals)


def eligible_approvers_for_case(case):
    q = CommitteeApprover.query.filter_by(active=True)
    approvers = q.order_by(CommitteeApprover.role, CommitteeApprover.name).all()
    # A member cannot approve a payment benefiting their own household, and the maker cannot approve their own case.
    maker_id = case.maker.approver_id if getattr(case, "maker", None) else None
    return [a for a in approvers if (not a.member_id or a.member_id != case.member_id) and a.id != maker_id]


def mpesa_ready():
    return all([
        MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_B2C_SHORTCODE,
        MPESA_INITIATOR_NAME, MPESA_SECURITY_CREDENTIAL, MPESA_RESULT_URL, MPESA_TIMEOUT_URL,
    ])


def request_mpesa_b2c(payout):
    if MPESA_MODE == "mock":
        return {"ok": True, "mock": True, "ConversationID": f"MOCK-{payout.id}-{int(datetime.utcnow().timestamp())}"}
    if MPESA_MODE not in {"sandbox", "production"}:
        return {"ok": False, "reason": "M-PESA mode is disabled"}
    if not mpesa_ready():
        return {"ok": False, "reason": "M-PESA B2C credentials are incomplete"}

    try:
        token_response = requests.get(MPESA_OAUTH_URL, auth=(MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET), timeout=20)
        try:
            token_data = token_response.json() if token_response.content else {}
        except Exception:
            token_data = {"raw": token_response.text}
    except requests.RequestException as exc:
        return {"ok": False, "reason": f"M-PESA OAuth connection failed: {exc}"}
    if not token_response.ok or not token_data.get("access_token"):
        return {"ok": False, "reason": "Could not obtain M-PESA access token", "data": token_data}

    phone = normalize_phone(payout.beneficiary_phone).replace("+", "")
    payload = {
        "InitiatorName": MPESA_INITIATOR_NAME,
        "SecurityCredential": MPESA_SECURITY_CREDENTIAL,
        "CommandID": MPESA_COMMAND_ID,
        "Amount": int(round(payout.amount)),
        "PartyA": MPESA_B2C_SHORTCODE,
        "PartyB": phone,
        "Remarks": f"{COMMUNITY_NAME} welfare case {payout.case_id}",
        "QueueTimeOutURL": MPESA_TIMEOUT_URL,
        "ResultURL": MPESA_RESULT_URL,
        "Occasion": f"Welfare-{payout.case_id}",
    }
    try:
        r = requests.post(MPESA_B2C_URL, json=payload, headers={"Authorization": f"Bearer {token_data['access_token']}", "Content-Type": "application/json"}, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
    except requests.RequestException as exc:
        return {"ok": False, "reason": f"M-PESA B2C connection failed: {exc}"}
    accepted = str(data.get("ResponseCode", "")) in {"0", "00"} and bool(data.get("ConversationID") or data.get("OriginatorConversationID"))
    return {"ok": r.ok and accepted, "status": r.status_code, "data": data}


def finalize_paid_payout(payout, provider_ref="", raw=None):
    payout.status = "Paid"
    payout.provider_ref = provider_ref or payout.provider_ref
    payout.paid_at = datetime.utcnow()
    if raw is not None:
        payout.provider_payload = json.dumps(raw)[:12000]
    payout.case.status = "Paid"
    audit(payout.case_id, "system", "Automatic payout engine", "Payment completed", f"KES {payout.amount:,.0f} to {payout.beneficiary_phone}; ref {payout.provider_ref}")
    db.session.commit()
    send_whatsapp_text(
        payout.beneficiary_phone,
        f"{COMMUNITY_NAME} welfare support paid ✓\n\nKES {payout.amount:,.0f}\nCase WF-{payout.case_id:04d}\nReference: {payout.provider_ref or 'processing reference'}",
    )


def attempt_automatic_release(case):
    payout = case.payout
    if not payout or payout.status not in {"Awaiting approvals", "Ready", "Blocked"}:
        return
    approved_count = CaseApproval.query.filter_by(case_id=case.id, decision="Approved").count()
    rejected_count = CaseApproval.query.filter_by(case_id=case.id, decision="Rejected").count()
    if rejected_count:
        payout.status = "Rejected"
        case.status = "Needs review"
        audit(case.id, "system", "Approval engine", "Payout stopped", "At least one committee approver rejected the case.")
        db.session.commit()
        return
    if approved_count < payout.required_approvals:
        return

    funds = fund_snapshot(exclude_payout_id=payout.id)
    if payout.amount > funds["available"]:
        payout.status = "Blocked"
        case.status = "Blocked — fund protection"
        audit(case.id, "system", "Fund protection", "Payout blocked", f"Requested KES {payout.amount:,.0f}; available KES {funds['available']:,.0f}; reserve KES {funds['reserve_floor']:,.0f}.")
        db.session.commit()
        return

    payout.status = "Ready"
    case.status = "Authorized"
    audit(case.id, "system", "Approval engine", "Approval quorum reached", f"{approved_count}/{payout.required_approvals} approvals. Payment instruction locked.")
    db.session.commit()

    if not MPESA_AUTO_RELEASE:
        return
    result = request_mpesa_b2c(payout)
    if result.get("mock") and result.get("ok"):
        finalize_paid_payout(payout, provider_ref=result.get("ConversationID", "MOCK"), raw=result)
        return
    if not result.get("ok"):
        payout.status = "Ready" if MPESA_MODE == "disabled" or not mpesa_ready() else "Failed"
        case.status = "Authorized" if payout.status == "Ready" else "Payment failed"
        payout.provider_payload = json.dumps(result)[:12000]
        audit(case.id, "system", "M-PESA B2C", "Automatic release not completed", result.get("reason", str(result.get("data", "Unknown error"))))
        db.session.commit()
        return

    data = result.get("data", {})
    payout.status = "Processing"
    case.status = "Payment processing"
    payout.requested_at = datetime.utcnow()
    payout.conversation_id = data.get("ConversationID", "")
    payout.originator_conversation_id = data.get("OriginatorConversationID", "")
    payout.provider_ref = payout.conversation_id or payout.originator_conversation_id
    payout.provider_payload = json.dumps(data)[:12000]
    audit(case.id, "system", "M-PESA B2C", "Automatic payout submitted", f"Conversation {payout.provider_ref}")
    db.session.commit()


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
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        try:
            data = r.json()
        except Exception:
            data = {"text": r.text}
        return {"ok": r.ok, "status": r.status_code, "data": data}
    except requests.RequestException as exc:
        return {"ok": False, "reason": str(exc)}


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
    if cmd == "COVER":
        people = HouseholdMember.query.filter_by(member_id=member.id, active=True).order_by(HouseholdMember.relationship, HouseholdMember.full_name).all()
        lines = [f"{COMMUNITY_NAME.upper()} — WELFARE COVER", "", f"Principal: {member.name} — covered while welfare membership is active"]
        if people:
            for person in people:
                state = "Verified" if person.verified else "Pending verification"
                lines.append(f"• {person.relationship}: {person.full_name} — {state}")
        else:
            lines.append("No household members registered yet.")
        lines += ["", f"View profile: {BASE_URL}/member/{member.id}"]
        return "\n".join(lines)
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
        snapshot = fund_snapshot()
        status = "GREEN" if snapshot["available"] > snapshot["reserve_floor"] else ("AMBER" if snapshot["available"] > 0 else "RED")
        return (
            f"{COMMUNITY_NAME.upper()} — WELFARE FUND\n\n"
            f"Recorded balance: KES {snapshot['current_balance']:,.0f}\n"
            f"Protected reserve: KES {snapshot['reserve_floor']:,.0f}\n"
            f"Committed claims: KES {snapshot['committed']:,.0f}\n"
            f"Available for new claims: KES {snapshot['available']:,.0f}\n"
            f"Status: {status}\n\nDetails: {BASE_URL}/welfare"
        )
    if cmd == "LEGACY":
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
        "FUND — welfare fund status\nLEGACY — legacy project progress\nCOVER — registered household cover\nPROFILE — your profile\nHELP — this menu"
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
    events_all = SupportCase.query.order_by(SupportCase.created_at.desc()).all()
    legacy_events = WelfareEvent.query.order_by(WelfareEvent.created_at.desc()).all()
    paid_out = sum(e.approved_support for e in events_all if e.status == "Paid") + sum(e.approved_support for e in legacy_events if e.status == "Paid")
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
        db.session.flush()

        household_inputs = [
            ("Spouse", request.form.get("spouse_name", "").strip(), request.form.get("spouse_phone", "").strip()),
            ("Mother", request.form.get("mother_name", "").strip(), ""),
            ("Father", request.form.get("father_name", "").strip(), ""),
        ]
        for relationship, full_name, phone_value in household_inputs:
            if full_name:
                db.session.add(HouseholdMember(
                    member_id=member.id, full_name=full_name, relationship=relationship,
                    phone=normalize_phone(phone_value) if phone_value else "", verified=False, active=True,
                    cover_start_date=date.today(),
                ))

        children = [line.strip() for line in request.form.get("children_names", "").splitlines() if line.strip()]
        for child_name in children:
            db.session.add(HouseholdMember(
                member_id=member.id, full_name=child_name, relationship="Child",
                verified=False, active=True, cover_start_date=date.today(),
            ))

        db.session.add(MemberPayoutProfile(
            member_id=member.id,
            payout_phone=normalize_phone(request.form.get("payout_phone", "").strip()) or member.phone,
            next_of_kin_name=request.form.get("next_of_kin_name", "").strip(),
            next_of_kin_phone=normalize_phone(request.form.get("next_of_kin_phone", "").strip()) if request.form.get("next_of_kin_phone") else "",
            verified=False,
        ))
        db.session.commit()
        flash("Welcome to the circle. Your profile and household cover have been submitted.", "success")
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
    support_cases = SupportCase.query.order_by(SupportCase.created_at.desc()).all()
    legacy_events = WelfareEvent.query.order_by(WelfareEvent.created_at.desc()).all()
    contributions = Contribution.query.order_by(Contribution.created_at.desc()).limit(50).all()
    fund_total = sum(c.amount for c in Contribution.query.filter_by(kind="Welfare").all())
    total_paid_out = sum(e.approved_support for e in support_cases if e.status == "Paid") + sum(e.approved_support for e in legacy_events if e.status == "Paid")
    fund = fund_snapshot()
    household = HouseholdMember.query.filter_by(active=True).order_by(HouseholdMember.relationship, HouseholdMember.full_name).all()
    rules = WelfareRule.query.filter_by(active=True).order_by(WelfareRule.support_type, WelfareRule.relationship).all()
    coverage = {
        "members": Member.query.filter_by(welfare_status="Active").count(),
        "spouses": HouseholdMember.query.filter_by(active=True, relationship="Spouse").count(),
        "children": HouseholdMember.query.filter_by(active=True, relationship="Child").count(),
        "parents": HouseholdMember.query.filter(HouseholdMember.active.is_(True), HouseholdMember.relationship.in_(["Mother", "Father"])).count(),
    }
    coverage["lives"] = coverage["members"] + coverage["spouses"] + coverage["children"] + coverage["parents"]
    return render_template(
        "welfare.html",
        members=members,
        events=support_cases,
        contributions=contributions,
        fund_total=fund_total,
        total_paid_out=total_paid_out,
        current_balance=fund_total - total_paid_out,
        fund=fund,
        household=household,
        rules=rules,
        coverage=coverage,
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
    # Kept for backward compatibility with any old links; new cases use /welfare/case.
    return redirect(url_for("welfare"))


@app.route("/member/<int:member_id>/household", methods=["POST"])
@admin_required
def add_household_member(member_id):
    member = Member.query.get_or_404(member_id)
    relationship = request.form.get("relationship", "").strip()
    if relationship not in {"Spouse", "Child", "Mother", "Father"}:
        flash("Choose a valid covered relationship.", "error")
        return redirect(url_for("member_profile", member_id=member.id))
    if relationship in {"Spouse", "Mother", "Father"}:
        existing_relationship = HouseholdMember.query.filter_by(member_id=member.id, relationship=relationship, active=True).first()
        if existing_relationship:
            flash(f"{member.name} already has an active {relationship.lower()} registered. Deactivate the old record before replacing it.", "error")
            return redirect(url_for("member_profile", member_id=member.id))
    full_name = request.form.get("full_name", "").strip()
    if not full_name:
        flash("Enter the covered person's name.", "error")
        return redirect(url_for("member_profile", member_id=member.id))
    dob = None
    if request.form.get("date_of_birth"):
        try:
            dob = date.fromisoformat(request.form["date_of_birth"])
        except ValueError:
            pass
    db.session.add(HouseholdMember(
        member_id=member.id, full_name=full_name, relationship=relationship,
        phone=normalize_phone(request.form.get("phone", "")) if request.form.get("phone") else "",
        date_of_birth=dob, verified=request.form.get("verified") == "on",
        active=True, cover_start_date=date.today(),
    ))
    db.session.commit()
    flash("Covered household member added.", "success")
    return redirect(url_for("member_profile", member_id=member.id))


@app.route("/household/<int:household_id>/verify", methods=["POST"])
@admin_required
def verify_household_member(household_id):
    person = HouseholdMember.query.get_or_404(household_id)
    person.verified = True
    db.session.commit()
    flash(f"{person.full_name} is now verified for household cover.", "success")
    return redirect(url_for("member_profile", member_id=person.member_id))


@app.route("/household/<int:household_id>/deactivate", methods=["POST"])
@admin_required
def deactivate_household_member(household_id):
    person = HouseholdMember.query.get_or_404(household_id)
    person.active = False
    db.session.commit()
    flash(f"{person.full_name} was removed from active cover.", "success")
    return redirect(url_for("member_profile", member_id=person.member_id))


@app.route("/member/<int:member_id>/payout-profile", methods=["POST"])
@admin_required
def update_payout_profile(member_id):
    member = Member.query.get_or_404(member_id)
    profile = member.payout_profile or MemberPayoutProfile(member_id=member.id)
    if not profile.id:
        db.session.add(profile)
    profile.payout_phone = normalize_phone(request.form.get("payout_phone", "").strip()) or member.phone
    profile.next_of_kin_name = request.form.get("next_of_kin_name", "").strip()
    profile.next_of_kin_phone = normalize_phone(request.form.get("next_of_kin_phone", "").strip()) if request.form.get("next_of_kin_phone") else ""
    profile.verified = request.form.get("verified") == "on"
    db.session.commit()
    flash("Payout and next-of-kin details updated.", "success")
    return redirect(url_for("member_profile", member_id=member.id))


@app.route("/welfare/rule", methods=["POST"])
@admin_required
def add_welfare_rule():
    support_type = request.form.get("support_type", "").strip()
    relationship = request.form.get("relationship", "").strip()
    if support_type not in {"Bereavement", "Serious illness", "Hospitalisation", "Accident / emergency"}:
        flash("Choose a valid support type.", "error")
        return redirect(url_for("welfare"))
    if relationship not in {"Principal", "Spouse", "Child", "Mother", "Father"}:
        flash("Choose a valid relationship.", "error")
        return redirect(url_for("welfare"))
    rule = WelfareRule.query.filter_by(support_type=support_type, relationship=relationship).first()
    if not rule:
        rule = WelfareRule(support_type=support_type, relationship=relationship)
        db.session.add(rule)
    rule.benefit_amount = float(request.form.get("benefit_amount", 0) or 0)
    rule.max_claims_per_year = int(request.form.get("max_claims_per_year", 1) or 1)
    rule.waiting_days = int(request.form.get("waiting_days", 0) or 0)
    rule.eligibility_notes = request.form.get("eligibility_notes", "").strip()
    rule.active = True
    db.session.commit()
    flash("Welfare benefit rule saved.", "success")
    return redirect(url_for("welfare"))


@app.route("/welfare/case", methods=["POST"])
@approver_required
def add_support_case():
    covered_key = request.form.get("covered_key", "").strip()
    if covered_key.startswith("P:"):
        member = Member.query.get_or_404(int(covered_key.split(":", 1)[1]))
        household_id = ""
    elif covered_key.startswith("H:"):
        preselected = HouseholdMember.query.get_or_404(int(covered_key.split(":", 1)[1]))
        member = Member.query.get_or_404(preselected.member_id)
        household_id = str(preselected.id)
    else:
        member = Member.query.get_or_404(int(request.form["member_id"]))
        household_id = request.form.get("household_member_id", "").strip()

    if member.welfare_status != "Active":
        flash("This principal member is not currently an active welfare member.", "error")
        return redirect(url_for("welfare"))

    person = None
    if household_id:
        person = HouseholdMember.query.get_or_404(int(household_id))
        if person.member_id != member.id or not person.active:
            flash("That covered person is not active under this member.", "error")
            return redirect(url_for("welfare"))
        if not person.verified:
            flash("Verify the household member before approving support.", "error")
            return redirect(url_for("welfare"))
        covered_name = person.full_name
        relationship = person.relationship
        cover_start = person.cover_start_date or person.registered_at.date()
    else:
        covered_name = member.name
        relationship = "Principal"
        cover_start = member.created_at.date()

    support_type = request.form.get("support_type", "").strip()
    event_date = date.today()
    if request.form.get("event_date"):
        try:
            event_date = date.fromisoformat(request.form["event_date"])
        except ValueError:
            pass

    rule = WelfareRule.query.filter_by(support_type=support_type, relationship=relationship, active=True).first()
    if rule:
        eligible_from = cover_start + timedelta(days=rule.waiting_days or 0)
        if event_date < eligible_from:
            flash(f"Cover for this event starts on {eligible_from.isoformat()} under the current waiting-period rule.", "error")
            return redirect(url_for("welfare"))
        year_start = date(event_date.year, 1, 1)
        year_end = date(event_date.year, 12, 31)
        q = SupportCase.query.filter(
            SupportCase.member_id == member.id,
            SupportCase.relationship == relationship,
            SupportCase.support_type == support_type,
            SupportCase.event_date >= year_start,
            SupportCase.event_date <= year_end,
            SupportCase.status.in_(["Approved", "Paid"]),
        )
        if person:
            q = q.filter(SupportCase.household_member_id == person.id)
        else:
            q = q.filter(SupportCase.household_member_id.is_(None))
        if q.count() >= max(rule.max_claims_per_year or 1, 1):
            flash("The annual claim limit for this support type has already been reached.", "error")
            return redirect(url_for("welfare"))
        amount = float(request.form.get("approved_support") or rule.benefit_amount or 0)
    else:
        amount = float(request.form.get("approved_support", 0) or 0)

    case = SupportCase(
        member_id=member.id,
        household_member_id=person.id if person else None,
        covered_name=covered_name,
        relationship=relationship,
        support_type=support_type,
        event_date=event_date,
        description=request.form.get("description", "").strip(),
        approved_support=amount,
        status="Pending",
        evidence_reference=request.form.get("evidence_reference", "").strip(),
    )
    db.session.add(case)
    db.session.flush()
    maker = CommitteeApprover.query.get(session["approver_id"])
    db.session.add(CaseMaker(case_id=case.id, approver_id=maker.id))
    audit(case.id, "maker", f"{maker.name} — {maker.role}", "Case created", f"{support_type}; {relationship}; KES {amount:,.0f}; covered person {covered_name}.")
    db.session.commit()
    flash("Welfare case created. Review it, then submit it for remote approval.", "success")
    return redirect(url_for("welfare"))


@app.route("/welfare/case/<int:case_id>/submit", methods=["POST"])
@committee_or_approver_required
def submit_case_for_approval(case_id):
    case = SupportCase.query.get_or_404(case_id)
    if case.status == "Paid":
        flash("This case has already been paid.", "error")
        return redirect(url_for("welfare"))
    if case.payout and case.payout.status in {"Processing", "Paid"}:
        flash("This payment can no longer be changed.", "error")
        return redirect(url_for("welfare"))
    if not case.approved_support or case.approved_support <= 0:
        flash("Set a positive welfare benefit before seeking approval.", "error")
        return redirect(url_for("welfare"))

    profile = case.member.payout_profile
    if case.relationship == "Principal" and case.support_type == "Bereavement":
        beneficiary_phone = normalize_phone(profile.next_of_kin_phone if profile else "")
        beneficiary_name = (profile.next_of_kin_name if profile else "") or f"Next of kin — {case.member.name}"
        if not beneficiary_phone:
            flash("A principal-member bereavement requires a verified next-of-kin payout number before approval.", "error")
            return redirect(url_for("member_profile", member_id=case.member_id))
    else:
        beneficiary_phone = normalize_phone((profile.payout_phone if profile else "") or case.member.phone)
        beneficiary_name = case.member.name
    if not beneficiary_phone:
        flash("The principal member needs a registered payout phone number.", "error")
        return redirect(url_for("member_profile", member_id=case.member_id))
    if not profile or not profile.verified:
        flash("The payout profile must be created and verified by the committee before a case can enter approval.", "error")
        return redirect(url_for("member_profile", member_id=case.member_id))

    required = required_approvals_for_amount(case.approved_support)
    eligible = eligible_approvers_for_case(case)
    if len(eligible) < required:
        flash(f"You need at least {required} active, non-conflicted approvers for this amount. Configure committee approvers first.", "error")
        return redirect(url_for("admin"))

    payout = case.payout
    if payout:
        CaseApproval.query.filter_by(case_id=case.id).delete(synchronize_session=False)
        payout.beneficiary_name = beneficiary_name
        payout.beneficiary_phone = beneficiary_phone
        payout.amount = case.approved_support
        payout.required_approvals = required
        payout.status = "Awaiting approvals"
        payout.provider_ref = ""
        payout.conversation_id = ""
        payout.originator_conversation_id = ""
        payout.provider_payload = ""
    else:
        payout = PayoutInstruction(
            case_id=case.id, beneficiary_name=beneficiary_name, beneficiary_phone=beneficiary_phone,
            amount=case.approved_support, required_approvals=required, status="Awaiting approvals",
        )
        db.session.add(payout)
        db.session.flush()

    funds = fund_snapshot(exclude_payout_id=payout.id)
    if payout.amount > funds["available"]:
        payout.status = "Blocked"
        case.status = "Blocked — fund protection"
        audit(case.id, "system", "Fund protection", "Approval submission blocked", f"Requested KES {payout.amount:,.0f}; safely available KES {funds['available']:,.0f}; reserve floor KES {funds['reserve_floor']:,.0f}.")
        db.session.commit()
        flash("The case exceeds funds safely available after the protected reserve.", "error")
        return redirect(url_for("welfare"))

    case.status = "Awaiting approvals"
    submitter = CommitteeApprover.query.get(session.get("approver_id")) if session.get("approver_id") else None
    actor_name = f"{submitter.name} — {submitter.role}" if submitter else "Committee admin"
    audit(case.id, "maker" if submitter else "committee", actor_name, "Case submitted for remote approval", f"Locked instruction: KES {payout.amount:,.0f} to {payout.beneficiary_phone}; {required} approvals required.")
    db.session.commit()

    for approver in eligible:
        send_whatsapp_text(
            approver.phone,
            f"{COMMUNITY_NAME}: welfare approval required\n\nCase WF-{case.id:04d}\n{case.covered_name} — {case.support_type}\nKES {payout.amount:,.0f}\n\nReview securely: {BASE_URL}/approvals/case/{case.id}",
        )
    flash(f"Case submitted. {required} remote approvals are required before release.", "success")
    return redirect(url_for("welfare"))


@app.route("/welfare/case/<int:case_id>/reset", methods=["POST"])
@admin_required
def reset_case_approval(case_id):
    case = SupportCase.query.get_or_404(case_id)
    payout = case.payout
    if payout and payout.status in {"Processing", "Paid"}:
        flash("A processing or paid transaction cannot be reset.", "error")
        return redirect(url_for("welfare"))
    CaseApproval.query.filter_by(case_id=case.id).delete(synchronize_session=False)
    if payout:
        db.session.delete(payout)
    case.status = "Pending"
    audit(case.id, "committee", "Committee admin", "Approval cycle reset", "Previous approvals were invalidated. The case must be submitted again.")
    db.session.commit()
    flash("Approval cycle reset. Any previous approvals no longer count.", "success")
    return redirect(url_for("welfare"))


@app.route("/approvals/login", methods=["GET", "POST"])
def approval_login():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone", ""))
        approver = CommitteeApprover.query.filter_by(phone=phone, active=True).first()
        if approver and check_password_hash(approver.pin_hash, request.form.get("pin", "")):
            session["approver_id"] = approver.id
            flash(f"Approval access opened for {approver.name}.", "success")
            return redirect(request.args.get("next") or url_for("approvals_dashboard"))
        flash("The committee phone or approval PIN is incorrect.", "error")
    return render_template("approval_login.html")


@app.route("/approvals/logout")
def approval_logout():
    session.pop("approver_id", None)
    flash("Approval session closed.", "success")
    return redirect(url_for("dashboard"))


@app.route("/approvals")
@approver_required
def approvals_dashboard():
    approver = CommitteeApprover.query.get(session["approver_id"])
    cases = SupportCase.query.filter(SupportCase.status.in_(["Awaiting approvals", "Authorized", "Payment processing", "Needs review", "Blocked — fund protection"])).order_by(SupportCase.created_at.desc()).all()
    visible = [c for c in cases if approver in eligible_approvers_for_case(c)]
    return render_template("approvals.html", approver=approver, cases=visible)


@app.route("/approvals/case/<int:case_id>")
@approver_required
def approval_case(case_id):
    approver = CommitteeApprover.query.get(session["approver_id"])
    case = SupportCase.query.get_or_404(case_id)
    if approver not in eligible_approvers_for_case(case):
        flash("You cannot approve a welfare payment benefiting your own household.", "error")
        return redirect(url_for("approvals_dashboard"))
    payout = case.payout
    funds = fund_snapshot(exclude_payout_id=payout.id if payout else None)
    existing = CaseApproval.query.filter_by(case_id=case.id, approver_id=approver.id).first()
    return render_template("approval_case.html", approver=approver, case=case, payout=payout, funds=funds, existing=existing)


@app.route("/approvals/case/<int:case_id>/decision", methods=["POST"])
@approver_required
def approval_decision(case_id):
    approver = CommitteeApprover.query.get(session["approver_id"])
    case = SupportCase.query.get_or_404(case_id)
    payout = case.payout
    if not payout or payout.status not in {"Awaiting approvals", "Ready", "Blocked"}:
        flash("This case is not currently open for approval.", "error")
        return redirect(url_for("approval_case", case_id=case.id))
    if approver not in eligible_approvers_for_case(case):
        flash("You cannot approve a payment benefiting your own household.", "error")
        return redirect(url_for("approvals_dashboard"))
    if CaseApproval.query.filter_by(case_id=case.id, approver_id=approver.id).first():
        flash("Your decision for this case has already been recorded.", "error")
        return redirect(url_for("approval_case", case_id=case.id))

    decision = request.form.get("decision", "Approved")
    if decision not in {"Approved", "Rejected"}:
        decision = "Rejected"
    db.session.add(CaseApproval(case_id=case.id, approver_id=approver.id, decision=decision, note=request.form.get("note", "").strip()))
    audit(case.id, "approver", f"{approver.name} — {approver.role}", f"Case {decision.lower()}", request.form.get("note", "").strip())
    db.session.commit()
    attempt_automatic_release(case)
    flash(f"Your {decision.lower()} decision was recorded.", "success" if decision == "Approved" else "error")
    return redirect(url_for("approval_case", case_id=case.id))


@app.route("/webhook/mpesa/b2c/result", methods=["POST"])
def mpesa_b2c_result():
    payload = request.get_json(silent=True) or {}
    result = payload.get("Result", {})
    conversation = result.get("ConversationID", "")
    originator = result.get("OriginatorConversationID", "")
    payout = None
    if conversation:
        payout = PayoutInstruction.query.filter_by(conversation_id=conversation).first()
    if not payout and originator:
        payout = PayoutInstruction.query.filter_by(originator_conversation_id=originator).first()
    if not payout:
        return jsonify({"status": "unknown payout"}), 200

    result_code = int(result.get("ResultCode", -1))
    params = {}
    for item in (result.get("ResultParameters", {}) or {}).get("ResultParameter", []) or []:
        params[str(item.get("Key"))] = item.get("Value")
    if result_code == 0:
        ref = str(params.get("TransactionReceipt") or conversation or originator)
        finalize_paid_payout(payout, provider_ref=ref, raw=payload)
    else:
        payout.status = "Failed"
        payout.case.status = "Payment failed"
        payout.provider_payload = json.dumps(payload)[:12000]
        audit(payout.case_id, "system", "M-PESA B2C", "Payment failed", str(result.get("ResultDesc", "M-PESA returned a failure")))
        db.session.commit()
    return jsonify({"status": "received"}), 200


@app.route("/webhook/mpesa/b2c/timeout", methods=["POST"])
def mpesa_b2c_timeout():
    payload = request.get_json(silent=True) or {}
    app.logger.warning("M-PESA B2C timeout: %s", payload)
    return jsonify({"status": "received"}), 200


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
    return render_template(
        "admin.html", members=members,
        approvers=CommitteeApprover.query.order_by(CommitteeApprover.role, CommitteeApprover.name).all(),
        fund_config=get_fund_config(), fund=fund_snapshot(), mpesa_mode=MPESA_MODE, mpesa_ready=mpesa_ready(),
    )


@app.route("/admin/member/<int:member_id>/status", methods=["POST"])
@admin_required
def update_member_status(member_id):
    member = Member.query.get_or_404(member_id)
    member.welfare_status = request.form["welfare_status"]
    member.annual_commitment = float(request.form.get("annual_commitment", member.annual_commitment) or 0)
    db.session.commit()
    flash("Member welfare status updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/approver", methods=["POST"])
@admin_required
def add_committee_approver():
    phone = normalize_phone(request.form.get("phone", ""))
    pin = request.form.get("pin", "").strip()
    if len(pin) < 6:
        flash("Use an approval PIN with at least 6 characters.", "error")
        return redirect(url_for("admin"))
    existing = CommitteeApprover.query.filter_by(phone=phone).first()
    member_id = request.form.get("member_id", "").strip()
    member_id = int(member_id) if member_id else None
    if existing:
        existing.name = request.form.get("name", existing.name).strip()
        existing.role = request.form.get("role", existing.role).strip()
        existing.member_id = member_id
        existing.pin_hash = generate_password_hash(pin)
        existing.active = True
    else:
        db.session.add(CommitteeApprover(
            name=request.form.get("name", "").strip(), role=request.form.get("role", "Committee").strip(),
            phone=phone, pin_hash=generate_password_hash(pin), member_id=member_id, active=True,
        ))
    db.session.commit()
    flash("Committee approver saved. Their approval PIN is stored only as a secure hash.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/approver/<int:approver_id>/toggle", methods=["POST"])
@admin_required
def toggle_committee_approver(approver_id):
    approver = CommitteeApprover.query.get_or_404(approver_id)
    approver.active = not approver.active
    db.session.commit()
    flash(f"{approver.name} is now {'active' if approver.active else 'inactive'} for approvals.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/welfare-config", methods=["POST"])
@admin_required
def update_welfare_config():
    cfg = get_fund_config()
    cfg.reserve_floor = max(0, float(request.form.get("reserve_floor", cfg.reserve_floor) or 0))
    cfg.small_payment_limit = max(0, float(request.form.get("small_payment_limit", cfg.small_payment_limit) or 0))
    cfg.small_payment_approvals = max(1, int(request.form.get("small_payment_approvals", cfg.small_payment_approvals) or 1))
    cfg.large_payment_approvals = max(1, int(request.form.get("large_payment_approvals", cfg.large_payment_approvals) or 1))
    db.session.commit()
    flash("Fund-protection and approval rules updated.", "success")
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
        return jsonify({"status": "ok", "database": "connected", "community": COMMUNITY_NAME, "mpesa_mode": MPESA_MODE, "mpesa_ready": mpesa_ready()}), 200
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
        "covered_household_members": HouseholdMember.query.filter_by(active=True).count(),
        "fund": fund_snapshot(),
        "pending_approval_cases": SupportCase.query.filter_by(status="Awaiting approvals").count(),
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
        for case in SupportCase.query.filter_by(member_id=member.id).all():
            CaseApproval.query.filter_by(case_id=case.id).delete(synchronize_session=False)
            CaseMaker.query.filter_by(case_id=case.id).delete(synchronize_session=False)
            AuditLog.query.filter_by(case_id=case.id).delete(synchronize_session=False)
            PayoutInstruction.query.filter_by(case_id=case.id).delete(synchronize_session=False)
            db.session.delete(case)
        HouseholdMember.query.filter_by(member_id=member.id).delete(synchronize_session=False)
        MemberPayoutProfile.query.filter_by(member_id=member.id).delete(synchronize_session=False)
        CommitteeApprover.query.filter_by(member_id=member.id).update({CommitteeApprover.member_id: None}, synchronize_session=False)
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
    get_fund_config()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
