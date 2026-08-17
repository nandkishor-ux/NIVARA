import logging
import os
import random
import re
import traceback
from datetime import datetime, timedelta, timezone
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///nivara.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "nivara-dev"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")

mail = Mail(app)

db = SQLAlchemy(app)

import models  # noqa: E402,F401
import chatbot  # noqa: E402,F401

with app.app_context():
    db.create_all()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("student_id") is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_student():
    student_id = session.get("student_id")
    student = None
    if student_id is not None:
        student = db.session.get(models.Student, student_id)
    return {"current_student": student}


@app.route("/profile")
@login_required
def profile():
    student = db.session.get(models.Student, session["student_id"])
    if student is None:
        session.clear()
        return redirect(url_for("login"))

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    history = models.CheckIn.query.filter(
        models.CheckIn.student_id == student.id,
        models.CheckIn.created_at >= cutoff,
    ).order_by(models.CheckIn.created_at).all()

    daily = {}
    for ci in history:
        day = ci.created_at.date()
        values = daily.setdefault(day, [])
        values.append(ci.mood_level)

    mood_history = [
        {"date": day.isoformat(), "label": day.strftime("%b %d"), "mood": round(sum(v) / len(v), 1)}
        for day, v in sorted(daily.items())
    ]

    return render_template(
        "profile.html",
        student=student,
        streak=current_streak(student.id),
        total_check_ins=models.CheckIn.query.filter_by(student_id=student.id).count(),
        contacts=models.EmergencyContact.query.filter_by(student_id=student.id)
        .order_by(models.EmergencyContact.created_at)
        .all(),
        reports_count=models.Report.query.filter_by(
            student_id=student.id, is_anonymous=False
        ).count(),
        mood_history=mood_history,
        mood_checkin_count=len(history),
    )


@app.route("/profile/export")
@login_required
def profile_export():
    student = db.session.get(models.Student, session["student_id"])
    if student is None:
        session.clear()
        return redirect(url_for("login"))

    check_ins = [
        {
            "mood_level": ci.mood_level,
            "mood_note": ci.mood_note,
            "created_at": ci.created_at.isoformat() if ci.created_at else None,
        }
        for ci in models.CheckIn.query.filter_by(student_id=student.id)
        .order_by(models.CheckIn.created_at)
        .all()
    ]
    reports = [
        {
            "category": r.category,
            "description": r.description,
            "is_anonymous": r.is_anonymous,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in models.Report.query.filter_by(
            student_id=student.id, is_anonymous=False
        )
        .order_by(models.Report.created_at)
        .all()
    ]
    contacts = [
        {
            "name": c.name,
            "phone_number": c.phone_number,
            "relationship": c.relationship,
            "category": c.category,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in models.EmergencyContact.query.filter_by(student_id=student.id)
        .order_by(models.EmergencyContact.created_at)
        .all()
    ]

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "name": student.display_name,
            "email": student.email,
            "phone_number": student.phone_number,
            "hostel_name": student.hostel_name,
            "member_since": student.created_at.isoformat() if student.created_at else None,
        },
        "check_ins": check_ins,
        "non_anonymous_reports": reports,
        "emergency_contacts": contacts,
    }

    filename = f"nivara-{student.email.split('@')[0]}-data.json"
    response = jsonify(payload)
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/profile/delete", methods=["POST"])
@login_required
def profile_delete():
    student = db.session.get(models.Student, session["student_id"])
    if student is None:
        session.clear()
        return redirect(url_for("login"))

    session_ids = [
        cs.id for cs in models.ChatSession.query.filter_by(student_id=student.id).all()
    ]
    if session_ids:
        models.ChatMessage.query.filter(
            models.ChatMessage.chat_session_id.in_(session_ids)
        ).delete(synchronize_session=False)
    models.ChatSession.query.filter_by(student_id=student.id).delete(
        synchronize_session=False
    )
    models.CheckIn.query.filter_by(student_id=student.id).delete(synchronize_session=False)
    models.EmergencyContact.query.filter_by(student_id=student.id).delete(
        synchronize_session=False
    )
    models.Report.query.filter_by(student_id=student.id, is_anonymous=False).delete(
        synchronize_session=False
    )
    db.session.delete(student)
    db.session.commit()

    session.clear()
    flash("Your account has been deleted.", "success")
    return redirect(url_for("login"))


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    student = db.session.get(models.Student, session["student_id"])
    if student is None:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        phone_number = request.form.get("phone_number", "").strip()
        hostel_name = request.form.get("hostel_name", "").strip()

        error = None
        if not phone_number:
            error = "Please enter your phone number."
        elif not hostel_name:
            error = "Please enter your hostel name."

        if error:
            return render_template(
                "profile_edit.html",
                student=student,
                error=error,
                phone_number=phone_number,
                hostel_name=hostel_name,
            ), 400

        student.phone_number = phone_number
        student.hostel_name = hostel_name
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))

    return render_template(
        "profile_edit.html",
        student=student,
        phone_number=student.phone_number,
        hostel_name=student.hostel_name,
    )


@app.route("/")
@login_required
def index():
    return render_template("index.html", streak=current_streak(session["student_id"]))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            return render_template("login.html", error="Please enter your email."), 400

        student = models.Student.query.filter_by(email=email).first()
        if not student or not student.is_verified:
            flash(
                "No verified account found for that email. Please register first.",
                "error",
            )
            return redirect(url_for("register"))

        otp = generate_otp()
        student.otp_code = otp
        student.otp_created_at = datetime.now(timezone.utc)
        db.session.commit()

        if not send_otp_email(student, otp):
            flash("We couldn't send your login code by email. Please try again later.", "error")
            return redirect(url_for("login"))

        flash("Check your email for a login code.", "success")
        return redirect(url_for("verify_otp", email=email))

    return render_template("login.html")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("login"))


def current_streak(student_id):
    today = datetime.now(timezone.utc).date()
    rows = models.CheckIn.query.filter_by(student_id=student_id).with_entities(
        models.CheckIn.created_at
    ).all()
    checked_days = {r[0].date() for r in rows}

    streak = 0
    day = today
    if day not in checked_days:
        day = day - timedelta(days=1)
    while day in checked_days:
        streak += 1
        day = day - timedelta(days=1)
    return streak


def generate_otp():
    return f"{random.randint(0, 999999):06d}"


OTP_LIFETIME_MINUTES = 10
OTP_RESEND_COOLDOWN_SECONDS = 60


def otp_recently_sent(student):
    if student is None or student.otp_created_at is None:
        return False
    otp_created_at = student.otp_created_at
    if otp_created_at.tzinfo is not None:
        otp_created_at = otp_created_at.replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - otp_created_at).total_seconds() < OTP_RESEND_COOLDOWN_SECONDS


def send_otp_email(student, otp):
    try:
        msg = Message(
            subject="Your NIVARA verification code",
            recipients=[student.email],
            body=(
                f"Hi {student.display_name or 'there'},\n\n"
                f"Your NIVARA verification code is: {otp}\n\n"
                "This code expires in 10 minutes. If you didn't request this, you can ignore this email."
            ),
        )
        mail.send(msg)
        logging.info("OTP email sent to %s", student.email)
        return True
    except Exception:
        print("=" * 60)
        print("EMAIL SEND FAILED - FULL TRACEBACK:")
        print(traceback.format_exc())
        print("=" * 60)
        logging.error("Failed to send OTP email to %s:\n%s", student.email, traceback.format_exc())
        return False


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone_number", "").strip()
        hostel_name = request.form.get("hostel_name", "").strip()

        error = None
        if not name:
            error = "Please enter your name."
        elif not email:
            error = "Please enter your email."
        elif not re.match(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            error = "Please enter a valid email address."
        elif not phone_number:
            error = "Please enter your phone number."
        elif not hostel_name:
            error = "Please enter your hostel name."
        else:
            existing = models.Student.query.filter_by(email=email).first()
            if existing and otp_recently_sent(existing):
                error = "Please wait a moment before requesting another code"
            elif existing:
                error = "This email is already registered."

        if error:
            return render_template(
                "register.html",
                error=error,
                name=name,
                email=email,
                phone_number=phone_number,
                hostel_name=hostel_name,
            ), 400

        otp = generate_otp()
        student = models.Student(
            display_name=name,
            email=email,
            phone_number=phone_number,
            hostel_name=hostel_name,
            is_verified=False,
            otp_code=otp,
            otp_created_at=datetime.now(timezone.utc),
        )
        db.session.add(student)
        db.session.commit()

        if not send_otp_email(student, otp):
            flash("We couldn't send your verification code by email. Please try again later.", "error")
            db.session.delete(student)
            db.session.commit()
            return redirect(url_for("register"))

        return redirect(url_for("verify_otp", email=email))

    return render_template("register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = request.args.get("email", "").strip().lower()
    student = models.Student.query.filter_by(email=email).first()

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        student = models.Student.query.filter_by(email=email).first()
        code = request.form.get("code", "").strip()

        if not student:
            return render_template("verify_otp.html", email=email, error="No account found for that email."), 400

        if not code:
            return render_template("verify_otp.html", email=email, error="Please enter the 6-digit code."), 400

        otp_created_at = student.otp_created_at
        if otp_created_at is not None and otp_created_at.tzinfo is not None:
            otp_created_at = otp_created_at.replace(tzinfo=None)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        is_expired = (
            otp_created_at is None
            or (now - otp_created_at) > timedelta(minutes=OTP_LIFETIME_MINUTES)
        )
        if is_expired:
            return render_template(
                "verify_otp.html",
                email=email,
                error="This code has expired. Please resend a new one.",
            ), 400

        if student.otp_code != code:
            return render_template(
                "verify_otp.html",
                email=email,
                error="That code doesn't match. Please try again.",
            ), 400

        student.is_verified = True
        student.otp_code = None
        student.otp_created_at = None
        db.session.commit()

        session["student_id"] = student.id
        session.permanent = True
        flash("Welcome to NIVARA! Your account is verified.", "success")
        return redirect(url_for("index"))

    return render_template("verify_otp.html", email=email)


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    email = request.form.get("email", "").strip().lower()
    student = models.Student.query.filter_by(email=email).first()

    if not student:
        flash("No account found for that email.", "error")
        return redirect(url_for("register"))

    if otp_recently_sent(student):
        flash("Please wait a moment before requesting another code", "error")
        return redirect(url_for("verify_otp", email=email))

    otp = generate_otp()
    student.otp_code = otp
    student.otp_created_at = datetime.now(timezone.utc)
    db.session.commit()

    if send_otp_email(student, otp):
        flash("A new code has been sent to your email.", "success")
    else:
        flash("We couldn't resend the code by email. Please try again later.", "error")

    return redirect(url_for("verify_otp", email=email))


@app.route("/checkin", methods=["GET", "POST"])
@login_required
def checkin():
    if request.method == "POST":
        is_json = request.is_json

        if is_json:
            data = request.get_json(silent=True) or {}
            mood_level = data.get("mood_level")
            mood_note = data.get("mood_note", "").strip() or None
        else:
            mood_level = request.form.get("mood_level")
            mood_note = request.form.get("mood_note", "").strip() or None

        error = None
        try:
            mood_level = int(mood_level)
            if mood_level < 1 or mood_level > 5:
                error = "Please pick a mood between 1 and 5."
        except (TypeError, ValueError):
            error = "Please select a mood to check in."

        if error:
            if is_json:
                return jsonify({"error": error}), 400
            return render_template("checkin.html", error=error, mood_note=mood_note), 400

        checkin = models.CheckIn(
            mood_level=mood_level, mood_note=mood_note, student_id=session["student_id"]
        )
        db.session.add(checkin)
        db.session.commit()

        if is_json:
            return jsonify({"ok": True, "streak": current_streak(session["student_id"])})

        flash("Thanks for checking in today!", "success")
        return redirect(url_for("checkin"))

    return render_template("checkin.html")


@app.route("/speakup", methods=["GET", "POST"])
@login_required
def speakup():
    if request.method == "POST":
        category = request.form.get("category") or "other"
        description = request.form.get("description", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"

        if not description:
            return render_template("speakup.html", error="Please describe what's going on."), 400

        report = models.Report(
            category=category,
            description=description,
            is_anonymous=is_anonymous,
            status="open",
            student_id=None if is_anonymous else session["student_id"],
        )
        db.session.add(report)
        db.session.commit()

        flash("Your report has been submitted. Hostel staff will review it.", "success")
        return redirect(url_for("speakup"))

    return render_template("speakup.html")


HELP_CATEGORIES = {
    "medical": {
        "title": "Medical Help",
        "contact": "Hostel Medical Desk",
        "numbers": [
            {"label": "Ambulance", "value": "102"},
            {"label": "Emergency Ambulance", "value": "108"},
        ],
    },
    "safety": {
        "title": "Safety Concern",
        "contact": "Hostel Safety Officer",
        "numbers": [
            {"label": "Women Helpline", "value": "1091"},
            {"label": "Police", "value": "100"},
        ],
    },
    "emergency": {
        "title": "Hostel Emergency",
        "contact": "24/7 Hostel Emergency Line",
        "numbers": [
            {"label": "National Emergency", "value": "112"},
            {"label": "Emergency Ambulance", "value": "108"},
        ],
    },
    "general": {
        "title": "General Support",
        "contact": "Hostel Support Staff",
        "numbers": [
            {"label": "National Emergency", "value": "112"},
        ],
    },
}


MAX_EMERGENCY_CONTACTS = 2


@app.route("/helphub")
@login_required
def helphub():
    contacts = models.EmergencyContact.query.filter_by(
        student_id=session["student_id"]
    ).order_by(models.EmergencyContact.created_at).all()
    return render_template(
        "helphub.html",
        contacts=contacts,
        max_contacts=MAX_EMERGENCY_CONTACTS,
        HELP_CATEGORIES=HELP_CATEGORIES,
    )


@app.route("/helphub/contacts/add", methods=["GET", "POST"])
@login_required
def helphub_contact_add():
    contact_count = models.EmergencyContact.query.filter_by(
        student_id=session["student_id"]
    ).count()
    if contact_count >= MAX_EMERGENCY_CONTACTS:
        flash("Maximum 2 contacts reached. Remove one to add another.", "error")
        return redirect(url_for("helphub"))

    contact_category = request.args.get("category", "").strip()
    if contact_category not in HELP_CATEGORIES:
        contact_category = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        relationship = request.form.get("relationship", "").strip() or None
        contact_category = request.form.get("category", "").strip()
        if contact_category not in HELP_CATEGORIES:
            contact_category = ""

        error = None
        if not name:
            error = "Please enter the contact's name."
        elif not phone_number:
            error = "Please enter a phone number."

        if error:
            return render_template(
                "helphub_contact_form.html",
                error=error,
                name=name,
                phone_number=phone_number,
                relationship=relationship,
                category=contact_category,
                HELP_CATEGORIES=HELP_CATEGORIES,
            ), 400

        contact = models.EmergencyContact(
            name=name,
            phone_number=phone_number,
            relationship=relationship,
            category=contact_category or None,
            student_id=session["student_id"],
        )
        db.session.add(contact)
        db.session.commit()

        flash("Contact saved.", "success")
        if contact_category:
            return redirect(url_for("helphub_" + contact_category))
        return redirect(url_for("helphub"))

    return render_template(
        "helphub_contact_form.html",
        category=contact_category,
        HELP_CATEGORIES=HELP_CATEGORIES,
    )


@app.route("/helphub/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def helphub_contact_delete(contact_id):
    contact = models.EmergencyContact.query.filter_by(
        id=contact_id, student_id=session["student_id"]
    ).first()
    if contact is not None:
        db.session.delete(contact)
        db.session.commit()
        flash("Contact removed.", "success")
    return redirect(url_for("helphub"))


def _category_page(slug):
    contact = (
        models.EmergencyContact.query.filter(
            models.EmergencyContact.student_id == session["student_id"],
            (models.EmergencyContact.category == slug)
            | (models.EmergencyContact.category.is_(None)),
        )
        .order_by(models.EmergencyContact.created_at)
        .first()
    )
    return render_template(
        "helphub_category.html",
        category=HELP_CATEGORIES[slug],
        slug=slug,
        contact=contact,
    )


@app.route("/helphub/medical")
@login_required
def helphub_medical():
    return _category_page("medical")


@app.route("/helphub/safety")
@login_required
def helphub_safety():
    return _category_page("safety")


@app.route("/helphub/emergency")
@login_required
def helphub_emergency():
    return _category_page("emergency")


@app.route("/helphub/general")
@login_required
def helphub_general():
    return _category_page("general")


CRISIS_REPLY = (
    "You're not alone in this — please reach a real person right now. "
    "Contact: [Hostel Emergency Line — to be configured] or [Crisis Helpline — to be configured]. "
    "Your safety matters most."
)


@app.route("/buddy")
@login_required
def buddy():
    return render_template("buddy.html")


@app.route("/buddy/message", methods=["POST"])
@login_required
def buddy_message():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Please type a message."}), 400

    if chatbot.check_crisis_keywords(message):
        return jsonify(
            {
                "reply": CRISIS_REPLY,
                "mood_signal_flag": "high",
                "crisis": True,
            }
        )

    chat_session_id = session.get("chat_session_id")
    if not chat_session_id:
        chat_session = models.ChatSession(student_id=session["student_id"])
        db.session.add(chat_session)
        db.session.commit()
        chat_session_id = chat_session.id
        session["chat_session_id"] = chat_session_id

    try:
        reply = chatbot.get_buddy_response(message)
    except Exception as exc:
        logging.error("Buddy service error:\n%s", traceback.format_exc())
        return jsonify({"error": f"Buddy service error: {exc}"}), 502

    db.session.add(
        models.ChatMessage(chat_session_id=chat_session_id, sender="student", content=message)
    )
    db.session.add(
        models.ChatMessage(chat_session_id=chat_session_id, sender="buddy", content=reply)
    )
    db.session.commit()

    return jsonify({"reply": reply, "mood_signal_flag": "low", "crisis": False})


if __name__ == "__main__":
    app.run()