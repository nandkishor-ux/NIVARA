from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///nivara.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "nivara-dev"

db = SQLAlchemy(app)

import models  # noqa: E402,F401

with app.app_context():
    db.create_all()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    if request.method == "POST":
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
            return render_template("checkin.html", error=error, mood_note=mood_note), 400

        checkin = models.CheckIn(mood_level=mood_level, mood_note=mood_note)
        db.session.add(checkin)
        db.session.commit()

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


if __name__ == "__main__":
    app.run()