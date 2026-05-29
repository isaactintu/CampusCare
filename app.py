from flask import Flask, render_template, request, redirect, session
import mysql.connector
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ---------------- SECRET KEY FOR SESSION ----------------

app.secret_key = "campuscare_secret_key"


# ---------------- EMAIL CONFIGURATION ----------------

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = 'stenyisaac1627@gmail.com'

# IMPORTANT:
# Put your Gmail App Password here only in your local laptop.
# Do not share this password publicly.
app.config['MAIL_PASSWORD'] = 'bsyf sarv ujpf lgmh'

app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False

mail = Mail(app)


# ---------------- MYSQL CONNECTION FUNCTION ----------------

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Isaac_777",
        database="complaint_system"
    )


# ---------------- EMAIL FUNCTION ----------------

def send_status_email(student_email, complaint_id, status):
    try:
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
            sender="stenyisaac1627@gmail.com",
            recipients=[student_email]
        )

        msg.body = body
        mail.send(msg)

    except Exception as e:
        print("Email sending failed:", e)


# ---------------- HOME PAGE ----------------

@app.route('/')
def home():
    return render_template('home.html')


# ---------------- LOGIN SIGNUP PAGE ----------------

@app.route('/complaint')
def complaint():
    return render_template('complaint.html')


# ---------------- LOGIN + SIGNUP ----------------

@app.route('/login-signup', methods=['POST'])
def login_signup():

    action = request.form.get('action')

    db = get_db_connection()
    cursor = db.cursor()

    try:
        # ---------- SIGNUP ----------
        if action == "signup":

            roll_no = request.form.get('roll_no')
            fullname = request.form.get('fullname')
            email = request.form.get('email')
            password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')

            if not roll_no or not fullname or not email or not password or not confirm_password:
                return "All fields are required ❌"

            if password != confirm_password:
                return "Password and Confirm Password do not match ❌"

            cursor.execute(
                "SELECT * FROM students WHERE roll_no=%s OR email=%s",
                (roll_no, email)
            )

            existing_user = cursor.fetchone()

            if existing_user:
                return "Student already registered ❌"

            hashed_password = generate_password_hash(password)

            cursor.execute(
                """
                INSERT INTO students
                (roll_no, fullname, email, password_hash)
                VALUES (%s, %s, %s, %s)
                """,
                (roll_no, fullname, email, hashed_password)
            )

            db.commit()

            session['roll_no'] = roll_no
            session['student_name'] = fullname
            session['student_email'] = email

            return redirect('/student-dashboard')

        # ---------- LOGIN ----------
        elif action == "login":

            login_value = request.form.get('login_value')
            password = request.form.get('password')

            if not login_value or not password:
                return "Roll Number / Email and Password are required ❌"

            cursor.execute(
                """
                SELECT id, roll_no, fullname, email, password_hash
                FROM students
                WHERE roll_no=%s OR email=%s
                """,
                (login_value, login_value)
            )

            user = cursor.fetchone()

            if user and check_password_hash(user[4], password):
                session['student_id'] = user[0]
                session['roll_no'] = user[1]
                session['student_name'] = user[2]
                session['student_email'] = user[3]

                return redirect('/student-dashboard')
            else:
                return "Invalid Roll Number / Email or Password ❌"

        else:
            return "Invalid action ❌"

    except mysql.connector.Error as err:
        print("Database error:", err)
        return "Database connection/query error ❌"

    finally:
        cursor.close()
        db.close()


# ---------------- FORGOT PASSWORD ----------------

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():

    if request.method == 'POST':

        roll_no = request.form.get('roll_no')
        email = request.form.get('email')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not roll_no or not email or not new_password or not confirm_password:
            return "All fields are required ❌"

        if new_password != confirm_password:
            return "New Password and Confirm Password do not match ❌"

        db = get_db_connection()
        cursor = db.cursor()

        try:
            cursor.execute(
                """
                SELECT id FROM students
                WHERE roll_no=%s AND email=%s
                """,
                (roll_no, email)
            )

            student = cursor.fetchone()

            if not student:
                return "Invalid Roll Number or Registered Email ❌"

            hashed_password = generate_password_hash(new_password)

            cursor.execute(
                """
                UPDATE students
                SET password_hash=%s
                WHERE roll_no=%s AND email=%s
                """,
                (hashed_password, roll_no, email)
            )

            db.commit()

            # Corrected: opens styled success HTML page
            return render_template("reset_sucessful.html")

        except mysql.connector.Error as err:
            print("Database error:", err)
            db.rollback()
            return "Database error while resetting password ❌"

        finally:
            cursor.close()
            db.close()

    return render_template('reset_password.html')


# ---------------- STUDENT DASHBOARD / MY COMPLAINTS ----------------

@app.route('/student-dashboard')
def student_dashboard():

    if 'student_email' not in session:
        return redirect('/complaint')

    roll_no = session.get('roll_no')

    db = get_db_connection()
    cursor = db.cursor()

    try:
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
            (roll_no,)
        )

        complaints = cursor.fetchall()

        return render_template(
            'student_dashboard.html',
            complaints=complaints,
            student_name=session.get('student_name'),
            roll_no=session.get('roll_no')
        )

    except mysql.connector.Error as err:
        print("Database error:", err)
        return "Database error while loading student dashboard ❌"

    finally:
        cursor.close()
        db.close()


# ---------------- STUDENT LOGOUT ----------------

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/complaint')


# ---------------- PROBLEM PAGE ----------------

@app.route('/problem')
def problem():

    if 'student_email' not in session:
        return redirect('/complaint')

    return render_template(
        'problem.html',
        student_name=session.get('student_name'),
        roll_no=session.get('roll_no'),
        student_email=session.get('student_email')
    )


# ---------------- SUBMIT COMPLAINT ----------------

@app.route('/submit-complaint', methods=['POST'])
def submit_complaint():

    if 'student_email' not in session:
        return redirect('/complaint')

    student_name = session['student_name']
    register_number = session['roll_no']
    email = session['student_email']

    department = request.form['department']
    category = request.form['category']
    description = request.form['description']
    priority = request.form['priority']

    db = get_db_connection()
    cursor = db.cursor()

    try:
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
                "Pending"
            )
        )

        db.commit()

        complaint_number = cursor.lastrowid
        complaint_id = f"CMP{complaint_number}"

        cursor.execute(
            "UPDATE complaints SET complaint_id=%s WHERE id=%s",
            (complaint_id, complaint_number)
        )

        db.commit()

        send_status_email(email, complaint_id, "Pending")

        return render_template(
            'success.html',
            complaint_id=complaint_id
        )

    except mysql.connector.Error as err:
        print("Database error:", err)
        db.rollback()
        return "Complaint submission failed due to database error ❌"

    finally:
        cursor.close()
        db.close()


# ---------------- TRACK COMPLAINT ----------------

@app.route('/track', methods=['GET', 'POST'])
def track():

    complaint = None

    if request.method == 'POST':

        complaint_id = request.form['complaint_id']

        db = get_db_connection()
        cursor = db.cursor()

        try:
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
                (complaint_id,)
            )

            complaint = cursor.fetchone()

        except mysql.connector.Error as err:
            print("Database error:", err)
            return "Database error while tracking complaint ❌"

        finally:
            cursor.close()
            db.close()

    return render_template(
        'track.html',
        complaint=complaint
    )


# ---------------- ADMIN LOGIN ----------------

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():

    if request.method == 'POST':

        username = request.form['username']
        password = request.form['password']

        db = get_db_connection()
        cursor = db.cursor()

        try:
            cursor.execute(
                "SELECT * FROM admins WHERE username=%s AND password=%s",
                (username, password)
            )

            admin = cursor.fetchone()

            if admin:
                session['admin_logged_in'] = True
                return redirect('/admin')
            else:
                return "Invalid Admin Credentials ❌"

        except mysql.connector.Error as err:
            print("Database error:", err)
            return "Database error during admin login ❌"

        finally:
            cursor.close()
            db.close()

    return render_template('adlog.html')


# ---------------- ADMIN LOGOUT ----------------

@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin-login')


# ---------------- ADMIN DASHBOARD ----------------

@app.route('/admin')
def admin():

    if 'admin_logged_in' not in session:
        return redirect('/admin-login')

    db = get_db_connection()
    cursor = db.cursor()

    try:
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
            'admin.html',
            complaints=complaints,
            total=total,
            pending=pending,
            inprocess=inprocess,
            resolved=resolved,
            rejected=rejected
        )

    except mysql.connector.Error as err:
        print("Database error:", err)
        return "Database error while loading admin dashboard ❌"

    finally:
        cursor.close()
        db.close()


# ---------------- COMMON STATUS UPDATE FUNCTION ----------------

def update_complaint_status(id, new_status):

    if 'admin_logged_in' not in session:
        return redirect('/admin-login')

    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute(
            "UPDATE complaints SET status=%s WHERE id=%s",
            (new_status, id)
        )

        db.commit()

        cursor.execute(
            "SELECT email, complaint_id FROM complaints WHERE id=%s",
            (id,)
        )

        data = cursor.fetchone()

        if data:
            send_status_email(data[0], data[1], new_status)

        return redirect('/admin')

    except mysql.connector.Error as err:
        print("Database error:", err)
        db.rollback()
        return "Database error while updating status ❌"

    finally:
        cursor.close()
        db.close()


# ---------------- STATUS UPDATE ROUTES ----------------

@app.route('/pending/<int:id>')
def pending(id):
    return update_complaint_status(id, "Pending")


@app.route('/inprocess/<int:id>')
def inprocess(id):
    return update_complaint_status(id, "In Process")


@app.route('/resolve/<int:id>')
def resolve(id):
    return update_complaint_status(id, "Resolved")


@app.route('/reject/<int:id>')
def reject(id):
    return update_complaint_status(id, "Rejected")


# ---------------- CONTACT PAGE ----------------

@app.route('/contact')
def contact():
    return render_template('contact.html')


# ---------------- RUN APP ----------------

if __name__ == '__main__':
    app.run(debug=True)