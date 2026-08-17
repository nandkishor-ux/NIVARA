import logging
import traceback
from datetime import datetime, timedelta, timezone

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///nivara.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "nivara-dev"

db = SQLAlchemy(app)

import models  # noqa: E402,F401
import chatbot  # noqa: E402,F401

with app.app_context():
    db.create_all()


@app.route("/")
def index():
    return render_template("index.html", streak=current_streak())


def current_streak():
    today = datetime.now(timezone.utc).date()
    rows = models.CheckIn.query.with_entities(models.CheckIn.created_at).all()
    checked_days = {r[0].date() for r in rows}

    streak = 0
    day = today
    if day not in checked_days:
        day = day - timedelta(days=1)
    while day in checked_days:
        streak += 1
        day = day - timedelta(days=1)
    return streak


@app.route("/checkin", methods=["GET", "POST"])
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

        checkin = models.CheckIn(mood_level=mood_level, mood_note=mood_note)
        db.session.add(checkin)
        db.session.commit()

        if is_json:
            return jsonify({"ok": True, "streak": current_streak()})

        flash("Thanks for checking in today!", "success")
        return redirect(url_for("checkin"))

    return render_template("checkin.html")


@app.route("/speakup", methods=["GET", "POST"])
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
        )
        db.session.add(report)
        db.session.commit()

        flash("Your report has been submitted. Hostel staff will review it.", "success")
        return redirect(url_for("speakup"))

    return render_template("speakup.html")


HELP_CATEGORIES = {
    "medical": {"title": "Medical Help", "contact": "Hostel Medical Desk"},
    "safety": {"title": "Safety Concern", "contact": "Hostel Safety Officer"},
    "emergency": {"title": "Hostel Emergency", "contact": "24/7 Hostel Emergency Line"},
    "general": {"title": "General Support", "contact": "Hostel Support Staff"},
}


@app.route("/helphub")
def helphub():
    return render_template("helphub.html")


def _category_page(slug):
    return render_template("helphub_category.html", category=HELP_CATEGORIES[slug])


@app.route("/helphub/medical")
def helphub_medical():
    return _category_page("medical")


@app.route("/helphub/safety")
def helphub_safety():
    return _category_page("safety")


@app.route("/helphub/emergency")
def helphub_emergency():
    return _category_page("emergency")


@app.route("/helphub/general")
def helphub_general():
    return _category_page("general")


CRISIS_REPLY = (
    "You're not alone in this — please reach a real person right now. "
    "Contact: [Hostel Emergency Line — to be configured] or [Crisis Helpline — to be configured]. "
    "Your safety matters most."
)


@app.route("/buddy")
def buddy():
    return render_template("buddy.html")


@app.route("/buddy/message", methods=["POST"])
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
        chat_session = models.ChatSession()
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