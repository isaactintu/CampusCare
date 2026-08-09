import os
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env locally.
# On Render/Railway/other hosts, configure the same variables in the platform dashboard.
load_dotenv()

app = Flask(__name__)

# ---------------- APP / SESSION CONFIGURATION ----------------

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

# Required when the app is behind a production reverse proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ---------------- EMAIL CONFIGURATION ----------------

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD", "")
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
    "MAIL_DEFAULT_SENDER",
    app.config["MAIL_USERNAME"],
)

mail = Mail(app)


# ---------------- MYSQL CONNECTION FUNCTION ----------------

def get_db_connection():
    """Create a fresh MySQL connection using environment variables."""
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "complaint_system"),
        connection_timeout=10,
    )


# ---------------- DATABASE HELPERS ----------------

def close_db(cursor=None, db=None):
    """Safely close database resources."""
    try:
        if cursor is not None:
            cursor.close()
    except Exception:
        pass

    try:
        if db is not None and db.is_connected():
            db.close()
    except Exception:
        pass


def admin_required(view):
    """Protect admin-only routes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def student_required(view):
    """Protect student-only routes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("student_email"):
            return redirect(url_for("complaint"))
        return view(*args, **kwargs)

    return wrapped


# ---------------- EMAIL FUNCTION ----------------

def send_status_email(student_email, complaint_id, status):
    """Send complaint status notification. Email failure won't break the request."""
    if not student_email or not app.config["MAIL_USERNAME"] or not app.config["MAIL_PASSWORD"]:
        app.logger.warning("Email is not configured; skipping notification.")
        return

    try:
        subject = "CampusCare - Complaint Status Updated"
        body = f"""Dear Student,

Your complaint status has been updated.

Complaint ID: {complaint_id}
Current Status: {status}

Thank you,
CampusCare Admin
"""

        msg = Message(
            subject=subject,
            sender=app.config["MAIL_DEFAULT_SENDER"],
            recipients=[student_email],
        )
        msg.body = body
        mail.send(msg)

    except Exception:
        app.logger.exception("Email sending failed")


# ---------------- HOME PAGE ----------------

@app.route("/")
def home():
    return render_template("home.html")


# ---------------- LOGIN SIGNUP PAGE ----------------

@app.route("/complaint")
def complaint():
    return render_template("complaint.html")


# ---------------- LOGIN + SIGNUP ----------------

@app.route("/login-signup", methods=["POST"])
def login_signup():
    action = request.form.get("action")

    if action not in {"signup", "login"}:
        return "Invalid action ❌", 400

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        # ---------- SIGNUP ----------
        if action == "signup":
            roll_no = request.form.get("roll_no", "").strip()
            fullname = request.form.get("fullname", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not all([roll_no, fullname, email, password, confirm_password]):
                return "All fields are required ❌", 400

            if password != confirm_password:
                return "Password and Confirm Password do not match ❌", 400

            cursor.execute(
                "SELECT id FROM students WHERE roll_no=%s OR email=%s",
                (roll_no, email),
            )
            if cursor.fetchone():
                return "Student already registered ❌", 409

            hashed_password = generate_password_hash(password)

            cursor.execute(
                """
                INSERT INTO students
                (roll_no, fullname, email, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (roll_no, fullname, email, hashed_password),
            )
            db.commit()

            session.clear()
            session["student_id"] = cursor.lastrowid
            session["roll_no"] = roll_no
            session["student_name"] = fullname
            session["student_email"] = email

            return redirect(url_for("student_dashboard"))

        # ---------- LOGIN ----------
        login_value = request.form.get("login_value", "").strip()
        password = request.form.get("password", "")

        if not login_value or not password:
            return "Roll Number / Email and Password are required ❌", 400

        cursor.execute(
            """
            SELECT id, roll_no, fullname, email, password_hash
            FROM students
            WHERE roll_no=%s OR email=%s
            """,
            (login_value, login_value.lower()),
        )
        user = cursor.fetchone()

        if user and check_password_hash(user[4], password):
            session.clear()
            session["student_id"] = user[0]
            session["roll_no"] = user[1]
            session["student_name"] = user[2]
            session["student_email"] = user[3]
            return redirect(url_for("student_dashboard"))

        return "Invalid Roll Number / Email or Password ❌", 401

    except mysql.connector.Error:
        app.logger.exception("Database error during login/signup")
        return "Database connection/query error ❌", 500

    finally:
        close_db(cursor, db)


# ---------------- FORGOT PASSWORD ----------------

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        roll_no = request.form.get("roll_no", "").strip()
        email = request.form.get("email", "").strip().lower()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([roll_no, email, new_password, confirm_password]):
            return "All fields are required ❌", 400

        if new_password != confirm_password:
            return "New Password and Confirm Password do not match ❌", 400

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                SELECT id FROM students
                WHERE roll_no=%s AND email=%s
                """,
                (roll_no, email),
            )
            student = cursor.fetchone()

            if not student:
                return "Invalid Roll Number or Registered Email ❌", 404

            hashed_password = generate_password_hash(new_password)

            cursor.execute(
                """
                UPDATE students
                SET password_hash=%s
                WHERE roll_no=%s AND email=%s
                """,
                (hashed_password, roll_no, email),
            )
            db.commit()

            return render_template("reset_sucessful.html")

        except mysql.connector.Error:
            app.logger.exception("Database error while resetting password")
            if db:
                db.rollback()
            return "Database error while resetting password ❌", 500

        finally:
            close_db(cursor, db)

    return render_template("reset_password.html")


# ---------------- STUDENT DASHBOARD / MY COMPLAINTS ----------------

@app.route("/student-dashboard")
@student_required
def student_dashboard():
    roll_no = session.get("roll_no")
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            SELECT
                complaint_id,
                category,
                description,
                priority,
                status,
                department,
                submitted_date,
                updated_date
            FROM complaints
            WHERE register_number = %s
            ORDER BY submitted_date DESC
            """,
            (roll_no,),
        )
        complaints = cursor.fetchall()

        return render_template(
            "student_dashboard.html",
            complaints=complaints,
            student_name=session.get("student_name"),
            roll_no=session.get("roll_no"),
        )

    except mysql.connector.Error:
        app.logger.exception("Database error while loading student dashboard")
        return "Database error while loading student dashboard ❌", 500

    finally:
        close_db(cursor, db)


# ---------------- STUDENT LOGOUT ----------------

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("complaint"))


# ---------------- PROBLEM PAGE ----------------

@app.route("/problem")
@student_required
def problem():
    return render_template(
        "problem.html",
        student_name=session.get("student_name"),
        roll_no=session.get("roll_no"),
        student_email=session.get("student_email"),
    )


# ---------------- SUBMIT COMPLAINT ----------------

@app.route("/submit-complaint", methods=["POST"])
@student_required
def submit_complaint():
    student_name = session["student_name"]
    register_number = session["roll_no"]
    email = session["student_email"]

    department = request.form.get("department", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "").strip()

    if not all([department, category, description, priority]):
        return "All complaint fields are required ❌", 400

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            INSERT INTO complaints
            (
                complaint_id,
                student_name,
                register_number,
                department,
                category,
                description,
                priority,
                email,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "",
                student_name,
                register_number,
                department,
                category,
                description,
                priority,
                email,
                "Pending",
            ),
        )

        db.commit()

        complaint_number = cursor.lastrowid
        complaint_id = f"CMP{complaint_number}"

        cursor.execute(
            "UPDATE complaints SET complaint_id=%s WHERE id=%s",
            (complaint_id, complaint_number),
        )
        db.commit()

        send_status_email(email, complaint_id, "Pending")

        return render_template("success.html", complaint_id=complaint_id)

    except mysql.connector.Error:
        app.logger.exception("Database error while submitting complaint")
        if db:
            db.rollback()
        return "Complaint submission failed due to database error ❌", 500

    finally:
        close_db(cursor, db)


# ---------------- TRACK COMPLAINT ----------------

@app.route("/track", methods=["GET", "POST"])
def track():
    complaint = None

    if request.method == "POST":
        complaint_id = request.form.get("complaint_id", "").strip()

        if not complaint_id:
            return render_template("track.html", complaint=None)

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                SELECT
                    id,
                    complaint_id,
                    student_name,
                    register_number,
                    department,
                    category,
                    description,
                    priority,
                    status,
                    email,
                    submitted_date,
                    updated_date
                FROM complaints
                WHERE complaint_id=%s
                """,
                (complaint_id,),
            )
            complaint = cursor.fetchone()

        except mysql.connector.Error:
            app.logger.exception("Database error while tracking complaint")
            return "Database error while tracking complaint ❌", 500

        finally:
            close_db(cursor, db)

    return render_template("track.html", complaint=complaint)


# ---------------- ADMIN LOGIN ----------------

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return "Username and password are required ❌", 400

        db = None
        cursor = None

        try:
            db = get_db_connection()
            cursor = db.cursor()

            # Preserves the existing admin table/schema from the supplied project.
            cursor.execute(
                "SELECT * FROM admins WHERE username=%s AND password=%s",
                (username, password),
            )
            admin = cursor.fetchone()

            if admin:
                session.clear()
                session["admin_logged_in"] = True
                session["admin_username"] = username
                return redirect(url_for("admin"))

            return "Invalid Admin Credentials ❌", 401

        except mysql.connector.Error:
            app.logger.exception("Database error during admin login")
            return "Database error during admin login ❌", 500

        finally:
            close_db(cursor, db)

    return render_template("adlog.html")


# ---------------- ADMIN LOGOUT ----------------

@app.route("/admin-logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin_login"))


# ---------------- ADMIN DASHBOARD ----------------

@app.route("/admin")
@admin_required
def admin():
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute("SELECT * FROM complaints ORDER BY submitted_date DESC")
        complaints = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM complaints")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'")
        pending = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM complaints WHERE status='In Process'")
        inprocess = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'")
        resolved = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM complaints WHERE status='Rejected'")
        rejected = cursor.fetchone()[0]

        return render_template(
            "admin.html",
            complaints=complaints,
            total=total,
            pending=pending,
            inprocess=inprocess,
            resolved=resolved,
            rejected=rejected,
        )

    except mysql.connector.Error:
        app.logger.exception("Database error while loading admin dashboard")
        return "Database error while loading admin dashboard ❌", 500

    finally:
        close_db(cursor, db)


# ---------------- COMMON STATUS UPDATE FUNCTION ----------------

def update_complaint_status(complaint_id, new_status):
    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            "UPDATE complaints SET status=%s WHERE id=%s",
            (new_status, complaint_id),
        )
        db.commit()

        cursor.execute(
            "SELECT email, complaint_id FROM complaints WHERE id=%s",
            (complaint_id,),
        )
        data = cursor.fetchone()

        if data:
            send_status_email(data[0], data[1], new_status)

        return redirect(url_for("admin"))

    except mysql.connector.Error:
        app.logger.exception("Database error while updating complaint status")
        if db:
            db.rollback()
        return "Database error while updating status ❌", 500

    finally:
        close_db(cursor, db)


# ---------------- STATUS UPDATE ROUTES ----------------

@app.route("/pending/<int:id>")
@admin_required
def pending(id):
    return update_complaint_status(id, "Pending")


@app.route("/inprocess/<int:id>")
@admin_required
def inprocess(id):
    return update_complaint_status(id, "In Process")


@app.route("/resolve/<int:id>")
@admin_required
def resolve(id):
    return update_complaint_status(id, "Resolved")


@app.route("/reject/<int:id>")
@admin_required
def reject(id):
    return update_complaint_status(id, "Rejected")


# ---------------- CONTACT PAGE ----------------

@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():
    """Simple deployment health endpoint."""
    db = None
    try:
        db = get_db_connection()
        if db.is_connected():
            return {"status": "ok", "database": "connected"}, 200
        return {"status": "error", "database": "disconnected"}, 503
    except Exception:
        app.logger.exception("Health check database failure")
        return {"status": "error", "database": "unavailable"}, 503
    finally:
        close_db(db=db)


# ---------------- RUN APP ----------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(port=port, debug=False)
