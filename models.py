from datetime import datetime, timezone

from app import db


def utcnow():
    return datetime.now(timezone.utc)


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    display_name = db.Column(db.String, nullable=True)
    email = db.Column(db.String, unique=True, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    hostel_name = db.Column(db.String, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    otp_code = db.Column(db.String, nullable=True)
    otp_created_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    check_ins = db.relationship("CheckIn", backref="student")
    chat_sessions = db.relationship("ChatSession", backref="student")


class CheckIn(db.Model):
    __tablename__ = "check_ins"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    mood_note = db.Column(db.Text, nullable=True)
    mood_level = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    category = db.Column(db.String, nullable=False)
    description = db.Column(db.Text, nullable=False)
    is_anonymous = db.Column(db.Boolean, default=True)
    status = db.Column(db.String, default="open")
    created_at = db.Column(db.DateTime, default=utcnow)


class ChatSession(db.Model):
    __tablename__ = "chat_sessions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    mood_signal_flag = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    messages = db.relationship("ChatMessage", backref="chat_session")


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    chat_session_id = db.Column(
        db.Integer, db.ForeignKey("chat_sessions.id"), nullable=False
    )
    sender = db.Column(db.String, nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class EmergencyContact(db.Model):
    __tablename__ = "emergency_contacts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    name = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    relationship = db.Column(db.String, nullable=True)
    category = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
