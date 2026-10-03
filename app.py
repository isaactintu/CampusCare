
from flask import Flask, render_template, request, redirect, session
from supabase import create_client, Client
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

import os

from datetime import datetime, timezone, timedelta


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY is not configured.")


# ============================================================
# SUPABASE CONFIGURATION
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_KEY must be configured."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# EMAIL CONFIGURATION
# ============================================================

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)


# ============================================================
# EMAIL FUNCTION
# ============================================================

def send_status_email(student_email, complaint_id, status):

    try:

        if not student_email:
            print("No student email available.")
            return

        subject = "Complaint Status Updated"

        body = f"""
Dear Student,

Your complaint status has been updated.

Complaint ID: {complaint_id}
Current Status: {status}

Thank you,
CampusCare Admin
"""

        msg = Message(
            subject,
            sender=app.config['MAIL_USERNAME'],
            recipients=[student_email]
        )

        msg.body = body

        mail.send(msg)

        print(
            f"Status email sent to {student_email} "
            f"for {complaint_id}: {status}"
        )

    except Exception as e:

        print("Email sending failed:", e)


# ============================================================
# DATE/TIME FORMAT FUNCTION
# ============================================================

def format_datetime(value):

    if not value:
        return ""

    try:

        # ----------------------------------------------------
        # Supabase normally returns ISO timestamps such as:
        #
        # 2026-10-03T07:30:00+00:00
        #
        # or:
        #
        # 2026-10-03T07:30:00Z
        # ----------------------------------------------------

        value_string = str(value)

        if value_string.endswith("Z"):
            value_string = value_string[:-1] + "+00:00"

        dt = datetime.fromisoformat(value_string)

        # ----------------------------------------------------
        # Convert UTC to Indian Standard Time
        # ----------------------------------------------------

        ist = timezone(
            timedelta(
                hours=5,
                minutes=30
            )
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        dt = dt.astimezone(ist)

        return dt.strftime(
            "%d-%m-%Y %H:%M:%S"
        )

    except Exception as e:

        print(
            "Date formatting error:",
            e
        )

        return str(value)


# ============================================================
# HOME PAGE
# ============================================================

@app.route('/')
def home():

    return render_template(
        'home.html'
    )


# ============================================================
# LOGIN SIGNUP PAGE
# ============================================================

@app.route('/complaint')
def complaint():

    return render_template(
        'complaint.html'
    )


# ============================================================
# LOGIN + SIGNUP
# ============================================================

@app.route('/login-signup', methods=['POST'])
def login_signup():

    action = request.form.get('action')

    try:

        # ====================================================
        # SIGNUP
        # ====================================================

        if action == "signup":

            roll_no = request.form.get('roll_no')
            fullname = request.form.get('fullname')
            email = request.form.get('email')
            password = request.form.get('password')
            confirm_password = request.form.get(
                'confirm_password'
            )

            if (
                not roll_no
                or not fullname
                or not email
                or not password
                or not confirm_password
            ):
                return "All fields are required ❌"

            if password != confirm_password:
                return (
                    "Password and Confirm Password "
                    "do not match ❌"
                )

            # ------------------------------------------------
            # CHECK ROLL NUMBER
            # ------------------------------------------------

            roll_result = (
                supabase
                .table("students")
                .select("id")
                .eq("roll_no", roll_no)
                .limit(1)
                .execute()
            )

            if roll_result.data:
                return "Roll Number already registered ❌"

            # ------------------------------------------------
            # CHECK EMAIL
            # ------------------------------------------------

            email_result = (
                supabase
                .table("students")
                .select("id")
                .eq("email", email)
                .limit(1)
                .execute()
            )

            if email_result.data:
                return "Email already registered ❌"

            # ------------------------------------------------
            # HASH PASSWORD
            # ------------------------------------------------

            hashed_password = generate_password_hash(
                password
            )

            # ------------------------------------------------
            # INSERT STUDENT
            # ------------------------------------------------

            result = (
                supabase
                .table("students")
                .insert({
                    "roll_no": roll_no,
                    "fullname": fullname,
                    "email": email,
                    "password_hash": hashed_password
                })
                .execute()
            )

            if not result.data:
                return "Student registration failed ❌"

            student = result.data[0]

            # ------------------------------------------------
            # CREATE SESSION
            # ------------------------------------------------

            session['student_id'] = student.get('id')
            session['roll_no'] = student.get('roll_no')
            session['student_name'] = student.get('fullname')
            session['student_email'] = student.get('email')

            return redirect(
                '/student-dashboard'
            )


        # ====================================================
        # LOGIN
        # ====================================================

        elif action == "login":

            login_value = request.form.get(
                'login_value'
            )

            password = request.form.get(
                'password'
            )

            if not login_value or not password:
                return (
                    "Roll Number / Email and "
                    "Password are required ❌"
                )

            # ------------------------------------------------
            # SEARCH BY ROLL NUMBER OR EMAIL
            # ------------------------------------------------

            result = (
                supabase
                .table("students")
                .select(
                    "id, roll_no, fullname, "
                    "email, password_hash"
                )
                .or_(
                    f"roll_no.eq.{login_value},"
                    f"email.eq.{login_value}"
                )
                .limit(1)
                .execute()
            )

            if not result.data:
                return (
                    "Invalid Roll Number / Email "
                    "or Password ❌"
                )

            user = result.data[0]

            stored_password = user.get(
                "password_hash"
            )

            if not stored_password:
                return (
                    "Student password is not configured ❌"
                )

            # ------------------------------------------------
            # PASSWORD CHECK
            # ------------------------------------------------

            try:

                password_valid = check_password_hash(
                    stored_password,
                    password
                )

            except Exception:

                password_valid = False

            if password_valid:

                session['student_id'] = user.get('id')
                session['roll_no'] = user.get('roll_no')
                session['student_name'] = user.get('fullname')
                session['student_email'] = user.get('email')

                return redirect(
                    '/student-dashboard'
                )

            return (
                "Invalid Roll Number / Email "
                "or Password ❌"
            )


        # ====================================================
        # INVALID ACTION
        # ====================================================

        else:

            return "Invalid action ❌"

    except Exception as err:

        print(
            "LOGIN/SIGNUP ERROR:",
            repr(err)
        )

        return (
            "Database connection/query error ❌"
        )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():

    if request.method == 'POST':

        roll_no = request.form.get('roll_no')
        email = request.form.get('email')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get(
            'confirm_password'
        )

        if (
            not roll_no
            or not email
            or not new_password
            or not confirm_password
        ):
            return "All fields are required ❌"

        if new_password != confirm_password:
            return (
                "New Password and Confirm Password "
                "do not match ❌"
            )

        try:

            # ------------------------------------------------
            # FIND STUDENT
            # ------------------------------------------------

            result = (
                supabase
                .table("students")
                .select("id")
                .eq("roll_no", roll_no)
                .eq("email", email)
                .limit(1)
                .execute()
            )

            if not result.data:
                return (
                    "Invalid Roll Number or "
                    "Registered Email ❌"
                )

            # ------------------------------------------------
            # HASH NEW PASSWORD
            # ------------------------------------------------

            hashed_password = generate_password_hash(
                new_password
            )

            # ------------------------------------------------
            # UPDATE
            # ------------------------------------------------

            update_result = (
                supabase
                .table("students")
                .update({
                    "password_hash": hashed_password
                })
                .eq("roll_no", roll_no)
                .eq("email", email)
                .execute()
            )

            if not update_result.data:
                return "Password reset failed ❌"

            return render_template(
                "reset_sucessful.html"
            )

        except Exception as err:

            print(
                "FORGOT PASSWORD ERROR:",
                repr(err)
            )

            return (
                "Database error while "
                "resetting password ❌"
            )

    return render_template(
        'reset_password.html'
    )


# ============================================================
# STUDENT DASHBOARD / MY COMPLAINTS
# ============================================================

@app.route('/student-dashboard')
def student_dashboard():

    if 'student_email' not in session:
        return redirect('/complaint')

    roll_no = session.get('roll_no')

    if not roll_no:

        session.clear()

        return redirect('/complaint')

    try:

        # ----------------------------------------------------
        # GET STUDENT COMPLAINTS
        # ----------------------------------------------------

        result = (
            supabase
            .table("complaints")
            .select(
                "complaint_id, "
                "category, "
                "description, "
                "priority, "
                "status, "
                "department, "
                "submitted_date, "
                "updated_date"
            )
            .eq(
                "register_number",
                roll_no
            )
            .order(
                "submitted_date",
                desc=True
            )
            .execute()
        )

        complaints_data = result.data or []

        complaints = []

        # ----------------------------------------------------
        # CONVERT TO TUPLES FOR HTML
        # ----------------------------------------------------

        for complaint in complaints_data:

            complaint_tuple = (

                complaint.get(
                    "complaint_id"
                ),

                complaint.get(
                    "category"
                ),

                complaint.get(
                    "description"
                ),

                complaint.get(
                    "priority"
                ),

                complaint.get(
                    "status"
                ),

                complaint.get(
                    "department"
                ),

                format_datetime(
                    complaint.get(
                        "submitted_date"
                    )
                ),

                format_datetime(
                    complaint.get(
                        "updated_date"
                    )
                )
            )

            complaints.append(
                complaint_tuple
            )

        print(
            "Student Roll Number:",
            roll_no
        )

        print(
            "Student Complaints:",
            complaints
        )

        return render_template(
            'student_dashboard.html',
            complaints=complaints,
            student_name=session.get(
                'student_name'
            ),
            roll_no=session.get(
                'roll_no'
            )
        )

    except Exception as err:

        print(
            "STUDENT DASHBOARD ERROR:",
            repr(err)
        )

        return (
            "Database error while loading "
            "student dashboard ❌"
        )


# ============================================================
# STUDENT LOGOUT
# ============================================================

@app.route('/logout')
def logout():

    session.clear()

    return redirect(
        '/complaint'
    )


# ============================================================
# PROBLEM PAGE
# ============================================================

@app.route('/problem')
def problem():

    if 'student_email' not in session:
        return redirect('/complaint')

    return render_template(
        'problem.html',
        student_name=session.get(
            'student_name'
        ),
        roll_no=session.get(
            'roll_no'
        ),
        student_email=session.get(
            'student_email'
        )
    )


# ============================================================
# SUBMIT COMPLAINT
# ============================================================

@app.route('/submit-complaint', methods=['POST'])
def submit_complaint():

    if 'student_email' not in session:
        return redirect('/complaint')

    student_name = session.get(
        'student_name'
    )

    register_number = session.get(
        'roll_no'
    )

    email = session.get(
        'student_email'
    )

    department = request.form.get(
        'department'
    )

    category = request.form.get(
        'category'
    )

    description = request.form.get(
        'description'
    )

    priority = request.form.get(
        'priority'
    )

    if (
        not department
        or not category
        or not description
        or not priority
    ):
        return (
            "All complaint fields "
            "are required ❌"
        )

    try:

        # ----------------------------------------------------
        # INSERT COMPLAINT
        # ----------------------------------------------------

        result = (
            supabase
            .table("complaints")
            .insert({
                "student_name": student_name,
                "register_number": register_number,
                "department": department,
                "category": category,
                "description": description,
                "priority": priority,
                "email": email,
                "status": "Pending"
            })
            .execute()
        )

        if not result.data:
            return (
                "Complaint submission failed ❌"
            )

        inserted_complaint = result.data[0]

        # ----------------------------------------------------
        # GET AUTO GENERATED ID
        # ----------------------------------------------------

        complaint_number = inserted_complaint.get(
            "id"
        )

        if complaint_number is None:
            return (
                "Complaint ID generation failed ❌"
            )

        complaint_id = f"CMP{complaint_number}"

        # ----------------------------------------------------
        # UPDATE complaint_id
        # ----------------------------------------------------

        update_result = (
            supabase
            .table("complaints")
            .update({
                "complaint_id": complaint_id
            })
            .eq(
                "id",
                complaint_number
            )
            .execute()
        )

        if not update_result.data:
            return (
                "Complaint ID generation failed ❌"
            )

        # ----------------------------------------------------
        # SEND EMAIL
        # ----------------------------------------------------

        send_status_email(
            email,
            complaint_id,
            "Pending"
        )

        return render_template(
            'success.html',
            complaint_id=complaint_id
        )

    except Exception as err:

        print(
            "SUBMIT COMPLAINT ERROR:",
            repr(err)
        )

        return (
            "Complaint submission failed "
            "due to database error ❌"
        )


# ============================================================
# TRACK COMPLAINT
# ============================================================

@app.route('/track', methods=['GET', 'POST'])
def track():

    complaint = None

    if request.method == 'POST':

        complaint_id = request.form.get(
            'complaint_id',
            ''
        ).strip()

        if not complaint_id:
            return (
                "Complaint ID is required ❌"
            )

        try:

            result = (
                supabase
                .table("complaints")
                .select(
                    "id, "
                    "complaint_id, "
                    "student_name, "
                    "register_number, "
                    "department, "
                    "category, "
                    "description, "
                    "priority, "
                    "status, "
                    "email, "
                    "submitted_date, "
                    "updated_date"
                )
                .ilike(
                    "complaint_id",
                    complaint_id
                )
                .limit(1)
                .execute()
            )

            if result.data:

                data = result.data[0]

                # ------------------------------------------
                # FORMAT DATES
                # ------------------------------------------

                submitted_date = format_datetime(
                    data.get(
                        "submitted_date"
                    )
                )

                updated_date = format_datetime(
                    data.get(
                        "updated_date"
                    )
                )

                # ------------------------------------------
                # TUPLE ORDER
                # ------------------------------------------

                complaint = (

                    data.get("id"),                  # [0]

                    data.get("complaint_id"),        # [1]

                    data.get("student_name"),        # [2]

                    data.get("register_number"),     # [3]

                    data.get("department"),          # [4]

                    data.get("category"),            # [5]

                    data.get("description"),         # [6]

                    data.get("priority"),            # [7]

                    data.get("status"),              # [8]

                    data.get("email"),               # [9]

                    submitted_date,                  # [10]

                    updated_date                     # [11]
                )

                print(
                    "TRACK COMPLAINT:",
                    complaint
                )

        except Exception as err:

            print(
                "TRACK COMPLAINT ERROR:",
                repr(err)
            )

            return (
                "Database error while "
                "tracking complaint ❌"
            )

    return render_template(
        'track.html',
        complaint=complaint
    )


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():

    if request.method == 'POST':

        username = request.form.get(
            'username'
        )

        password = request.form.get(
            'password'
        )

        if not username or not password:
            return (
                "Username and Password "
                "are required ❌"
            )

        try:

            # ------------------------------------------------
            # FIND ADMIN
            # ------------------------------------------------

            result = (
                supabase
                .table("admins")
                .select(
                    "id, username, password"
                )
                .eq(
                    "username",
                    username
                )
                .limit(1)
                .execute()
            )

            if not result.data:
                return (
                    "Invalid Admin Credentials ❌"
                )

            admin_data = result.data[0]

            stored_password = admin_data.get(
                "password"
            )

            if not stored_password:
                return (
                    "Admin password is not "
                    "configured ❌"
                )

            # ------------------------------------------------
            # PASSWORD CHECK
            # ------------------------------------------------

            password_valid = False

            if (
                stored_password.startswith(
                    "pbkdf2:"
                )
                or stored_password.startswith(
                    "scrypt:"
                )
            ):

                try:

                    password_valid = (
                        check_password_hash(
                            stored_password,
                            password
                        )
                    )

                except Exception:

                    password_valid = False

            else:

                password_valid = (
                    stored_password == password
                )

            # ------------------------------------------------
            # LOGIN SUCCESS
            # ------------------------------------------------

            if password_valid:

                session['admin_logged_in'] = True

                session['admin_id'] = (
                    admin_data.get('id')
                )

                session['admin_username'] = (
                    admin_data.get('username')
                )

                return redirect(
                    '/admin'
                )

            return (
                "Invalid Admin Credentials ❌"
            )

        except Exception as err:

            print(
                "ADMIN LOGIN ERROR:",
                repr(err)
            )

            return (
                "Database error during "
                "admin login ❌"
            )

    return render_template(
        'adlog.html'
    )


# ============================================================
# ADMIN LOGOUT
# ============================================================

@app.route('/admin-logout')
def admin_logout():

    session.pop(
        'admin_logged_in',
        None
    )

    session.pop(
        'admin_id',
        None
    )

    session.pop(
        'admin_username',
        None
    )

    return redirect(
        '/admin-login'
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route('/admin')
def admin():

    if not session.get(
        'admin_logged_in'
    ):
        return redirect(
            '/admin-login'
        )

    try:

        # ----------------------------------------------------
        # GET COMPLAINTS
        # ----------------------------------------------------

        complaints_result = (
            supabase
            .table("complaints")
            .select(
                "id, "
                "complaint_id, "
                "student_name, "
                "register_number, "
                "department, "
                "category, "
                "description, "
                "priority, "
                "status, "
                "email, "
                "submitted_date, "
                "updated_date"
            )
            .order(
                "submitted_date",
                desc=True
            )
            .execute()
        )

        complaints_data = (
            complaints_result.data or []
        )

        complaints = []

        # ----------------------------------------------------
        # CREATE TUPLES FOR admin.html
        #
        # [0]  id
        # [1]  complaint_id
        # [2]  student_name
        # [3]  register_number
        # [4]  department
        # [5]  category
        # [6]  description
        # [7]  priority
        # [8]  status
        # [9]  email
        # [10] submitted_date
        # [11] submitted_date
        # [12] updated_date
        #
        # Your current HTML uses:
        # complaint[11] = submitted date
        # complaint[12] = updated date
        # ----------------------------------------------------

        for complaint in complaints_data:

            complaint_tuple = (

                complaint.get(
                    "id"
                ),                                      # [0]

                complaint.get(
                    "complaint_id"
                ),                                      # [1]

                complaint.get(
                    "student_name"
                ),                                      # [2]

                complaint.get(
                    "register_number"
                ),                                      # [3]

                complaint.get(
                    "department"
                ),                                      # [4]

                complaint.get(
                    "category"
                ),                                      # [5]

                complaint.get(
                    "description"
                ),                                      # [6]

                complaint.get(
                    "priority"
                ),                                      # [7]

                complaint.get(
                    "status"
                ),                                      # [8]

                complaint.get(
                    "email"
                ),                                      # [9]

                format_datetime(
                    complaint.get(
                        "submitted_date"
                    )
                ),                                      # [10]

                format_datetime(
                    complaint.get(
                        "submitted_date"
                    )
                ),                                      # [11]

                format_datetime(
                    complaint.get(
                        "updated_date"
                    )
                )                                       # [12]
            )

            complaints.append(
                complaint_tuple
            )

        print(
            "ADMIN COMPLAINTS:",
            complaints
        )

        # ----------------------------------------------------
        # TOTAL
        # ----------------------------------------------------

        total_result = (
            supabase
            .table("complaints")
            .select(
                "id",
                count="exact"
            )
            .execute()
        )

        total = total_result.count or 0

        # ----------------------------------------------------
        # PENDING
        # ----------------------------------------------------

        pending_result = (
            supabase
            .table("complaints")
            .select(
                "id",
                count="exact"
            )
            .eq(
                "status",
                "Pending"
            )
            .execute()
        )

        pending = pending_result.count or 0

        # ----------------------------------------------------
        # IN PROCESS
        # ----------------------------------------------------

        inprocess_result = (
            supabase
            .table("complaints")
            .select(
                "id",
                count="exact"
            )
            .eq(
                "status",
                "In Process"
            )
            .execute()
        )

        inprocess = (
            inprocess_result.count or 0
        )

        # ----------------------------------------------------
        # RESOLVED
        # ----------------------------------------------------

        resolved_result = (
            supabase
            .table("complaints")
            .select(
                "id",
                count="exact"
            )
            .eq(
                "status",
                "Resolved"
            )
            .execute()
        )

        resolved = (
            resolved_result.count or 0
        )

        # ----------------------------------------------------
        # REJECTED
        # ----------------------------------------------------

        rejected_result = (
            supabase
            .table("complaints")
            .select(
                "id",
                count="exact"
            )
            .eq(
                "status",
                "Rejected"
            )
            .execute()
        )

        rejected = (
            rejected_result.count or 0
        )

        # ----------------------------------------------------
        # SEND DATA TO HTML
        # ----------------------------------------------------

        return render_template(
            'admin.html',
            complaints=complaints,
            total=total,
            pending=pending,
            inprocess=inprocess,
            resolved=resolved,
            rejected=rejected
        )

    except Exception as err:

        print(
            "ADMIN DASHBOARD ERROR:",
            repr(err)
        )

        return (
            "Database error while loading "
            "admin dashboard ❌"
        )


# ============================================================
# COMMON STATUS UPDATE FUNCTION
# ============================================================

def update_complaint_status(
    id,
    new_status
):

    # --------------------------------------------------------
    # ADMIN LOGIN CHECK
    # --------------------------------------------------------

    if not session.get(
        'admin_logged_in'
    ):
        return redirect(
            '/admin-login'
        )

    try:

        # ----------------------------------------------------
        # ALLOWED STATUSES
        # ----------------------------------------------------

        allowed_statuses = {
            "Pending",
            "In Process",
            "Resolved",
            "Rejected"
        }

        if new_status not in allowed_statuses:

            return (
                "Invalid complaint status ❌"
            ), 400

        # ----------------------------------------------------
        # GET CURRENT COMPLAINT
        # ----------------------------------------------------

        current_result = (
            supabase
            .table("complaints")
            .select(
                "id, complaint_id, status, email"
            )
            .eq(
                "id",
                id
            )
            .limit(1)
            .execute()
        )

        if not current_result.data:

            return (
                "Complaint not found ❌"
            ), 404

        current_complaint = (
            current_result.data[0]
        )

        current_status = (
            current_complaint.get(
                "status"
            )
        )

        # ----------------------------------------------------
        # VALID STATUS TRANSITIONS
        #
        # Pending:
        #     In Process
        #     Rejected
        #
        # In Process:
        #     Resolved
        #     Rejected
        #
        # Resolved:
        #     No changes
        #
        # Rejected:
        #     No changes
        # ----------------------------------------------------

        allowed_transitions = {

            "Pending": {
                "In Process",
                "Rejected"
            },

            "In Process": {
                "Resolved",
                "Rejected"
            },

            "Resolved": set(),

            "Rejected": set()
        }

        if new_status not in allowed_transitions.get(
            current_status,
            set()
        ):

            return (
                f"Cannot change complaint status "
                f"from '{current_status}' "
                f"to '{new_status}' ❌"
            ), 400

        # ----------------------------------------------------
        # CURRENT UTC TIME
        # ----------------------------------------------------

        updated_time = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        # ----------------------------------------------------
        # UPDATE STATUS
        # ----------------------------------------------------

        result = (
            supabase
            .table("complaints")
            .update({
                "status": new_status,
                "updated_date": updated_time
            })
            .eq(
                "id",
                id
            )
            .execute()
        )

        if not result.data:

            return (
                "Complaint status update failed ❌"
            )

        # ----------------------------------------------------
        # SEND STATUS EMAIL
        # ----------------------------------------------------

        send_status_email(
            current_complaint.get(
                "email"
            ),
            current_complaint.get(
                "complaint_id"
            ),
            new_status
        )

        print(
            "STATUS UPDATED:",
            current_complaint.get(
                "complaint_id"
            ),
            current_status,
            "->",
            new_status
        )

        return redirect(
            '/admin'
        )

    except Exception as err:

        print(
            "STATUS UPDATE ERROR:",
            repr(err)
        )

        return (
            "Database error while "
            "updating status ❌"
        )


# ============================================================
# NEW DROPDOWN STATUS UPDATE ROUTE
# ============================================================

@app.route(
    '/update-status/<int:id>',
    methods=['POST']
)
def update_status(id):

    # --------------------------------------------------------
    # ADMIN LOGIN CHECK
    # --------------------------------------------------------

    if not session.get(
        'admin_logged_in'
    ):
        return redirect(
            '/admin-login'
        )

    # --------------------------------------------------------
    # GET SELECTED STATUS
    # --------------------------------------------------------

    new_status = request.form.get(
        'status'
    )

    if not new_status:

        return (
            "Please select a status ❌"
        ), 400

    # --------------------------------------------------------
    # ALLOWED STATUS VALUES
    # --------------------------------------------------------

    allowed_statuses = {
        "In Process",
        "Resolved",
        "Rejected"
    }

    if new_status not in allowed_statuses:

        return (
            "Invalid status selected ❌"
        ), 400

    # --------------------------------------------------------
    # UPDATE COMPLAINT
    # --------------------------------------------------------

    return update_complaint_status(
        id,
        new_status
    )


# ============================================================
# OLD STATUS UPDATE ROUTES
#
# These are kept so any existing links/bookmarks
# continue to work.
# ============================================================

@app.route('/pending/<int:id>')
def pending(id):

    return update_complaint_status(
        id,
        "Pending"
    )


@app.route('/inprocess/<int:id>')
def inprocess(id):

    return update_complaint_status(
        id,
        "In Process"
    )


@app.route('/resolve/<int:id>')
def resolve(id):

    return update_complaint_status(
        id,
        "Resolved"
    )


@app.route('/reject/<int:id>')
def reject(id):

    return update_complaint_status(
        id,
        "Rejected"
    )


# ============================================================
# CONTACT PAGE
# ============================================================

@app.route('/contact')
def contact():

    return render_template(
        'contact.html'
    )


# ============================================================
# RUN APP
# ============================================================

if __name__ == '__main__':

    port = int(
        os.getenv(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
