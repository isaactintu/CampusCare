import os
from functools import wraps

import mysql.connector
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, session, url_for
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "change-this-secret-key"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Render uses HTTPS
app.config["SESSION_COOKIE_SECURE"] = (
    os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
)

# Needed behind Render reverse proxy
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1
)


# ============================================================
# EMAIL CONFIGURATION
# ============================================================

app.config["MAIL_SERVER"] = os.getenv(
    "MAIL_SERVER",
    "smtp.gmail.com"
)

app.config["MAIL_PORT"] = int(
    os.getenv("MAIL_PORT", "587")
)

app.config["MAIL_USERNAME"] = os.getenv(
    "MAIL_USERNAME",
    ""
)

app.config["MAIL_PASSWORD"] = os.getenv(
    "MAIL_PASSWORD",
    ""
)

app.config["MAIL_USE_TLS"] = (
    os.getenv("MAIL_USE_TLS", "true").lower() == "true"
)

app.config["MAIL_USE_SSL"] = (
    os.getenv("MAIL_USE_SSL", "false").lower() == "true"
)

app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
    "MAIL_DEFAULT_SENDER",
    app.config["MAIL_USERNAME"]
)

mail = Mail(app)


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():
    """
    Create a new MySQL connection.
    Works with Render environment variables.
    """

    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME")

    if not host:
        raise RuntimeError("DB_HOST is missing")

    if not user:
        raise RuntimeError("DB_USER is missing")

    if not database:
        raise RuntimeError("DB_NAME is missing")

    return mysql.connector.connect(
        host=host,
        port=int(port),
        user=user,
        password=password or "",
        database=database,
        connection_timeout=15,
        autocommit=False
    )


# ============================================================
# DATABASE CLOSE HELPER
# ============================================================

def close_db(cursor=None, db=None):

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


# ============================================================
# GET TABLE COLUMNS
# ============================================================

def get_table_columns(table_name):

    db = None
    cursor = None

    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")

        rows = cursor.fetchall()

        return {
            row[0]
            for row in rows
        }

    except Exception:
        app.logger.exception(
            "Could not read columns from table: %s",
            table_name
        )
        return set()

    finally:
        close_db(cursor, db)


# ============================================================
# ADMIN LOGIN PROTECTION
# ============================================================

def admin_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))

        return view(*args, **kwargs)

    return wrapped


# ============================================================
# STUDENT LOGIN PROTECTION
# ============================================================

def student_required(view):

    @wraps(view)
    def wrapped(*args, **kwargs):

        # We only require a valid student identity.
        # Email is retrieved separately when needed.
        if not session.get("student_id") or not session.get("roll_no"):
            return redirect(url_for("complaint"))

        return view(*args, **kwargs)

    return wrapped


# ============================================================
# GET CURRENT STUDENT EMAIL
# ============================================================

def get_student_email():

    # First try session
    email = session.get("student_email")

    if email:
        return email

    student_id = session.get("student_id")

    if not student_id:
        return None

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            SELECT email
            FROM students
            WHERE id=%s
            """,
            (student_id,)
        )

        student = cursor.fetchone()

        if student and student[0]:

            email = student[0]

            # Save it in session
            session["student_email"] = email

            return email

    except Exception:

        app.logger.exception(
            "Could not retrieve student email"
        )

    finally:

        close_db(cursor, db)

    return None


# ============================================================
# EMAIL FUNCTION
# ============================================================

def send_status_email(student_email, complaint_id, status):

    # Email is optional.
    if not student_email:
        app.logger.warning(
            "No student email available. Skipping email."
        )
        return

    if not app.config["MAIL_USERNAME"]:
        app.logger.warning(
            "MAIL_USERNAME is not configured. Skipping email."
        )
        return

    if not app.config["MAIL_PASSWORD"]:
        app.logger.warning(
            "MAIL_PASSWORD is not configured. Skipping email."
        )
        return

    try:

        subject = "CampusCare - Complaint Status Updated"

        body = f"""
Dear Student,

Your complaint status has been updated.

Complaint ID: {complaint_id}
Current Status: {status}

Thank you,
CampusCare Admin
"""

        message = Message(
            subject=subject,
            sender=app.config["MAIL_DEFAULT_SENDER"],
            recipients=[student_email]
        )

        message.body = body

        mail.send(message)

        app.logger.info(
            "Status email sent successfully for %s",
            complaint_id
        )

    except Exception:

        # IMPORTANT:
        # Email failure should NEVER break complaint submission.
        app.logger.exception(
            "Email sending failed for complaint %s",
            complaint_id
        )


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    return render_template("home.html")


# ============================================================
# LOGIN / SIGNUP PAGE
# ============================================================

@app.route("/complaint")
def complaint():

    return render_template("complaint.html")


# ============================================================
# LOGIN + SIGNUP
# ============================================================

@app.route("/login-signup", methods=["POST"])
def login_signup():

    action = request.form.get("action", "").strip()

    if action not in {"signup", "login"}:
        return "Invalid action ❌", 400

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        # ====================================================
        # SIGNUP
        # ====================================================

        if action == "signup":

            roll_no = request.form.get(
                "roll_no",
                ""
            ).strip()

            fullname = request.form.get(
                "fullname",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip().lower()

            password = request.form.get(
                "password",
                ""
            )

            confirm_password = request.form.get(
                "confirm_password",
                ""
            )

            if not all([
                roll_no,
                fullname,
                email,
                password,
                confirm_password
            ]):

                return "All fields are required ❌", 400

            if password != confirm_password:

                return (
                    "Password and Confirm Password do not match ❌",
                    400
                )

            cursor.execute(
                """
                SELECT id
                FROM students
                WHERE roll_no=%s OR email=%s
                """,
                (roll_no, email)
            )

            if cursor.fetchone():

                return "Student already registered ❌", 409

            hashed_password = generate_password_hash(
                password
            )

            cursor.execute(
                """
                INSERT INTO students
                (
                    roll_no,
                    fullname,
                    email,
                    password_hash
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    roll_no,
                    fullname,
                    email,
                    hashed_password
                )
            )

            db.commit()

            student_id = cursor.lastrowid

            # Create fresh session
            session.clear()

            session["student_id"] = student_id
            session["roll_no"] = roll_no
            session["student_name"] = fullname
            session["student_email"] = email

            session.permanent = False

            return redirect(
                url_for("student_dashboard")
            )

        # ====================================================
        # LOGIN
        # ====================================================

        login_value = request.form.get(
            "login_value",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not login_value or not password:

            return (
                "Roll Number / Email and Password are required ❌",
                400
            )

        cursor.execute(
            """
            SELECT
                id,
                roll_no,
                fullname,
                email,
                password_hash
            FROM students
            WHERE roll_no=%s OR email=%s
            """,
            (
                login_value,
                login_value.lower()
            )
        )

        user = cursor.fetchone()

        if user:

            try:

                password_valid = check_password_hash(
                    user[4],
                    password
                )

            except Exception:

                password_valid = False

            if password_valid:

                session.clear()

                session["student_id"] = user[0]
                session["roll_no"] = user[1]
                session["student_name"] = user[2]
                session["student_email"] = user[3]

                session.permanent = False

                return redirect(
                    url_for("student_dashboard")
                )

        return (
            "Invalid Roll Number / Email or Password ❌",
            401
        )

    except mysql.connector.Error:

        app.logger.exception(
            "MYSQL ERROR during login/signup"
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return (
            "Database connection/query error ❌",
            500
        )

    except Exception:

        app.logger.exception(
            "UNEXPECTED ERROR during login/signup"
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return (
            "Unexpected server error ❌",
            500
        )

    finally:

        close_db(cursor, db)


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        roll_no = request.form.get(
            "roll_no",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not all([
            roll_no,
            email,
            new_password,
            confirm_password
        ]):

            return "All fields are required ❌", 400

        if new_password != confirm_password:

            return (
                "New Password and Confirm Password do not match ❌",
                400
            )

        db = None
        cursor = None

        try:

            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                SELECT id
                FROM students
                WHERE roll_no=%s AND email=%s
                """,
                (roll_no, email)
            )

            student = cursor.fetchone()

            if not student:

                return (
                    "Invalid Roll Number or Registered Email ❌",
                    404
                )

            hashed_password = generate_password_hash(
                new_password
            )

            cursor.execute(
                """
                UPDATE students
                SET password_hash=%s
                WHERE roll_no=%s AND email=%s
                """,
                (
                    hashed_password,
                    roll_no,
                    email
                )
            )

            db.commit()

            return render_template(
                "reset_sucessful.html"
            )

        except mysql.connector.Error:

            app.logger.exception(
                "Database error while resetting password"
            )

            if db:
                db.rollback()

            return (
                "Database error while resetting password ❌",
                500
            )

        except Exception:

            app.logger.exception(
                "Unexpected error while resetting password"
            )

            if db:
                db.rollback()

            return (
                "Unexpected server error ❌",
                500
            )

        finally:

            close_db(cursor, db)

    return render_template(
        "reset_password.html"
    )


# ============================================================
# STUDENT DASHBOARD
# ============================================================

@app.route("/student-dashboard")
@student_required
def student_dashboard():

    roll_no = session.get("roll_no")

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        columns = get_table_columns("complaints")

        # Handle either submitted_date or created_at
        if "submitted_date" in columns:

            date_columns = """
                submitted_date,
                updated_date
            """

        elif "created_at" in columns:

            date_columns = """
                created_at AS submitted_date,
                created_at AS updated_date
            """

        else:

            date_columns = """
                NULL AS submitted_date,
                NULL AS updated_date
            """

        cursor.execute(
            f"""
            SELECT
                complaint_id,
                category,
                description,
                priority,
                status,
                department,
                {date_columns}
            FROM complaints
            WHERE register_number=%s
            ORDER BY
                COALESCE(
                    submitted_date,
                    created_at
                ) DESC
            """,
            (roll_no,)
        )

        complaints = cursor.fetchall()

        return render_template(
            "student_dashboard.html",
            complaints=complaints,
            student_name=session.get("student_name"),
            roll_no=roll_no
        )

    except Exception:

        app.logger.exception(
            "ERROR loading student dashboard"
        )

        return (
            "Database error while loading student dashboard ❌",
            500
        )

    finally:

        close_db(cursor, db)


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("complaint")
    )


# ============================================================
# PROBLEM / COMPLAINT FORM
# ============================================================

@app.route("/problem")
@student_required
def problem():

    return render_template(
        "problem.html",
        student_name=session.get("student_name"),
        roll_no=session.get("roll_no"),
        student_email=get_student_email()
    )


# ============================================================
# SUBMIT COMPLAINT
# ============================================================

@app.route("/submit-complaint", methods=["POST"])
@student_required
def submit_complaint():

    app.logger.info(
        "========== COMPLAINT SUBMISSION STARTED =========="
    )

    # --------------------------------------------------------
    # GET STUDENT DETAILS
    # --------------------------------------------------------

    student_id = session.get("student_id")
    student_name = session.get("student_name")
    register_number = session.get("roll_no")

    # Get email safely
    email = get_student_email()

    app.logger.info(
        "Student ID: %s",
        student_id
    )

    app.logger.info(
        "Student Name: %s",
        student_name
    )

    app.logger.info(
        "Register Number: %s",
        register_number
    )

    app.logger.info(
        "Student Email available: %s",
        bool(email)
    )

    # --------------------------------------------------------
    # VALIDATE STUDENT SESSION
    # --------------------------------------------------------

    if not student_id or not register_number:

        app.logger.error(
            "Student session is incomplete."
        )

        return (
            "Your login session has expired. "
            "Please logout and login again ❌",
            401
        )

    if not student_name:

        app.logger.error(
            "Student name missing from session."
        )

        return (
            "Student information is missing. "
            "Please logout and login again ❌",
            401
        )

    # --------------------------------------------------------
    # GET FORM DATA
    # --------------------------------------------------------

    department = request.form.get(
        "department",
        ""
    ).strip()

    category = request.form.get(
        "category",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    priority = request.form.get(
        "priority",
        ""
    ).strip()

    app.logger.info(
        "Department: %s",
        department
    )

    app.logger.info(
        "Category: %s",
        category
    )

    app.logger.info(
        "Priority: %s",
        priority
    )

    # --------------------------------------------------------
    # VALIDATE FORM
    # --------------------------------------------------------

    if not all([
        department,
        category,
        description,
        priority
    ]):

        app.logger.warning(
            "Complaint form contains missing fields."
        )

        return (
            "All complaint fields are required ❌",
            400
        )

    db = None
    cursor = None

    try:

        # ----------------------------------------------------
        # CONNECT DATABASE
        # ----------------------------------------------------

        app.logger.info(
            "Connecting to database..."
        )

        db = get_db_connection()

        app.logger.info(
            "Database connection successful."
        )

        cursor = db.cursor()

        # ----------------------------------------------------
        # CHECK COMPLAINT TABLE COLUMNS
        # ----------------------------------------------------

        cursor.execute(
            "SHOW COLUMNS FROM complaints"
        )

        column_rows = cursor.fetchall()

        complaint_columns = {
            row[0]
            for row in column_rows
        }

        app.logger.info(
            "Complaint table columns: %s",
            complaint_columns
        )

        # ----------------------------------------------------
        # INSERT COMPLAINT
        # ----------------------------------------------------

        insert_columns = [
            "student_name",
            "register_number",
            "department",
            "category",
            "description",
            "priority"
        ]

        insert_values = [
            student_name,
            register_number,
            department,
            category,
            description,
            priority
        ]

        # Add email only if the column exists
        if "email" in complaint_columns:

            insert_columns.append("email")
            insert_values.append(email)

        # Add status if the column exists
        if "status" in complaint_columns:

            insert_columns.append("status")
            insert_values.append("Pending")

        # First insert without complaint_id.
        # This lets MySQL generate the numeric ID.
        placeholders = ", ".join(
            ["%s"] * len(insert_columns)
        )

        column_string = ", ".join(
            f"`{column}`"
            for column in insert_columns
        )

        sql = f"""
            INSERT INTO complaints
            ({column_string})
            VALUES
            ({placeholders})
        """

        app.logger.info(
            "Executing complaint INSERT..."
        )

        cursor.execute(
            sql,
            tuple(insert_values)
        )

        db.commit()

        # ----------------------------------------------------
        # GET AUTO GENERATED ID
        # ----------------------------------------------------

        complaint_number = cursor.lastrowid

        app.logger.info(
            "Generated database ID: %s",
            complaint_number
        )

        if not complaint_number:

            raise Exception(
                "MySQL did not return complaint ID"
            )

        complaint_id = f"CMP{complaint_number}"

        # ----------------------------------------------------
        # UPDATE COMPLAINT ID
        # ----------------------------------------------------

        if "complaint_id" in complaint_columns:

            cursor.execute(
                """
                UPDATE complaints
                SET complaint_id=%s
                WHERE id=%s
                """,
                (
                    complaint_id,
                    complaint_number
                )
            )

            db.commit()

        app.logger.info(
            "Complaint created successfully: %s",
            complaint_id
        )

        # ----------------------------------------------------
        # SEND EMAIL
        # ----------------------------------------------------

        send_status_email(
            email,
            complaint_id,
            "Pending"
        )

        app.logger.info(
            "========== COMPLAINT SUBMISSION SUCCESS =========="
        )

        # ----------------------------------------------------
        # SUCCESS PAGE
        # ----------------------------------------------------

        return render_template(
            "success.html",
            complaint_id=complaint_id
        )

    except mysql.connector.Error as error:

        app.logger.exception(
            "MYSQL ERROR WHILE SUBMITTING COMPLAINT: %s",
            error
        )

        if db:

            try:
                db.rollback()
            except Exception:
                pass

        return (
            "Complaint submission failed due to database error ❌ "
            "Please check Render Logs.",
            500
        )

    except Exception as error:

        app.logger.exception(
            "UNEXPECTED ERROR WHILE SUBMITTING COMPLAINT: %s",
            error
        )

        if db:

            try:
                db.rollback()
            except Exception:
                pass

        return (
            "Complaint submission failed ❌ "
            "Please check Render Logs.",
            500
        )

    finally:

        close_db(cursor, db)


# ============================================================
# TRACK COMPLAINT
# ============================================================

@app.route("/track", methods=["GET", "POST"])
def track():

    complaint = None

    if request.method == "POST":

        complaint_id = request.form.get(
            "complaint_id",
            ""
        ).strip()

        if not complaint_id:

            return render_template(
                "track.html",
                complaint=None
            )

        db = None
        cursor = None

        try:

            db = get_db_connection()
            cursor = db.cursor()

            columns = get_table_columns(
                "complaints"
            )

            if "submitted_date" in columns:

                submitted_date = "submitted_date"

            elif "created_at" in columns:

                submitted_date = "created_at AS submitted_date"

            else:

                submitted_date = "NULL AS submitted_date"

            if "updated_date" in columns:

                updated_date = "updated_date"

            else:

                updated_date = "NULL AS updated_date"

            email_column = (
                "email"
                if "email" in columns
                else "NULL"
            )

            cursor.execute(
                f"""
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
                    {email_column},
                    {submitted_date},
                    {updated_date}
                FROM complaints
                WHERE complaint_id=%s
                """,
                (complaint_id,)
            )

            complaint = cursor.fetchone()

        except Exception:

            app.logger.exception(
                "Database error while tracking complaint"
            )

            return (
                "Database error while tracking complaint ❌",
                500
            )

        finally:

            close_db(cursor, db)

    return render_template(
        "track.html",
        complaint=complaint
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            return (
                "Username and password are required ❌",
                400
            )

        db = None
        cursor = None

        try:

            db = get_db_connection()
            cursor = db.cursor()

            cursor.execute(
                """
                SELECT *
                FROM admins
                WHERE username=%s
                AND password=%s
                """,
                (
                    username,
                    password
                )
            )

            admin = cursor.fetchone()

            if admin:

                session.clear()

                session["admin_logged_in"] = True
                session["admin_username"] = username

                return redirect(
                    url_for("admin")
                )

            return (
                "Invalid Admin Credentials ❌",
                401
            )

        except Exception:

            app.logger.exception(
                "Database error during admin login"
            )

            return (
                "Database error during admin login ❌",
                500
            )

        finally:

            close_db(cursor, db)

    return render_template(
        "adlog.html"
    )


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route("/admin-logout")
def admin_logout():

    session.pop(
        "admin_logged_in",
        None
    )

    session.pop(
        "admin_username",
        None
    )

    return redirect(
        url_for("admin_login")
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin():

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        columns = get_table_columns(
            "complaints"
        )

        if "submitted_date" in columns:

            order_column = "submitted_date"

        elif "created_at" in columns:

            order_column = "created_at"

        else:

            order_column = "id"

        cursor.execute(
            f"""
            SELECT *
            FROM complaints
            ORDER BY `{order_column}` DESC
            """
        )

        complaints = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*) FROM complaints"
        )

        total = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM complaints
            WHERE status='Pending'
            """
        )

        pending = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM complaints
            WHERE status='In Process'
            """
        )

        inprocess = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM complaints
            WHERE status='Resolved'
            """
        )

        resolved = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM complaints
            WHERE status='Rejected'
            """
        )

        rejected = cursor.fetchone()[0]

        return render_template(
            "admin.html",
            complaints=complaints,
            total=total,
            pending=pending,
            inprocess=inprocess,
            resolved=resolved,
            rejected=rejected
        )

    except Exception:

        app.logger.exception(
            "Database error while loading admin dashboard"
        )

        return (
            "Database error while loading admin dashboard ❌",
            500
        )

    finally:

        close_db(cursor, db)


# ============================================================
# UPDATE COMPLAINT STATUS
# ============================================================

def update_complaint_status(
    complaint_id,
    new_status
):

    db = None
    cursor = None

    try:

        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            UPDATE complaints
            SET status=%s
            WHERE id=%s
            """,
            (
                new_status,
                complaint_id
            )
        )

        db.commit()

        cursor.execute(
            """
            SELECT email, complaint_id
            FROM complaints
            WHERE id=%s
            """,
            (complaint_id,)
        )

        data = cursor.fetchone()

        if data:

            send_status_email(
                data[0],
                data[1],
                new_status
            )

        return redirect(
            url_for("admin")
        )

    except Exception:

        app.logger.exception(
            "Database error while updating complaint status"
        )

        if db:

            try:
                db.rollback()
            except Exception:
                pass

        return (
            "Database error while updating status ❌",
            500
        )

    finally:

        close_db(cursor, db)


# ============================================================
# STATUS ROUTES
# ============================================================

@app.route("/pending/<int:id>")
@admin_required
def pending(id):

    return update_complaint_status(
        id,
        "Pending"
    )


@app.route("/inprocess/<int:id>")
@admin_required
def inprocess(id):

    return update_complaint_status(
        id,
        "In Process"
    )


@app.route("/resolve/<int:id>")
@admin_required
def resolve(id):

    return update_complaint_status(
        id,
        "Resolved"
    )


@app.route("/reject/<int:id>")
@admin_required
def reject(id):

    return update_complaint_status(
        id,
        "Rejected"
    )


# ============================================================
# CONTACT
# ============================================================

@app.route("/contact")
def contact():

    return render_template(
        "contact.html"
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    db = None

    try:

        db = get_db_connection()

        if db.is_connected():

            return {
                "status": "ok",
                "database": "connected"
            }, 200

        return {
            "status": "error",
            "database": "disconnected"
        }, 503

    except Exception:

        app.logger.exception(
            "Health check database failure"
        )

        return {
            "status": "error",
            "database": "unavailable"
        }, 503

    finally:

        close_db(db=db)


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@app.errorhandler(500)
def internal_server_error(error):

    app.logger.exception(
        "GLOBAL 500 ERROR: %s",
        error
    )

    return (
        "Internal Server Error ❌ "
        "Please check Render Logs.",
        500
    )


# ============================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================

@app.errorhandler(Exception)
def handle_exception(error):

    app.logger.exception(
        "UNHANDLED EXCEPTION: %s",
        error
    )

    return (
        "Unexpected server error ❌ "
        "Please check Render Logs.",
        500
    )


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
