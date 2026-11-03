"""
Student Performance Analysis System - Flask web application
Mohan Babu University | Dept. of CSE & AIML | Team 7

Run:  python app.py      then open  http://127.0.0.1:5000
"""
import csv
import io
import secrets
import sys
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import analytics
import config
import db
import mailer

import site_assets
from jinja2 import DictLoader

# Pages (HTML), CSS and JavaScript are stored inside site_assets.py, so the project
# works even if the templates/static folders are missing (easy GitHub / Render upload).
app = Flask(__name__, static_folder=None)
app.jinja_loader = DictLoader(site_assets.TEMPLATES)
app.secret_key = config.SECRET_KEY


@app.route("/static/<path:filename>", endpoint="static")
def static_files(filename):
    content = site_assets.STATIC.get(filename)
    if content is None:
        abort(404)
    mime = "text/css" if filename.endswith(".css") else "application/javascript"
    return Response(content, mimetype=mime, headers={"Cache-Control": "public, max-age=3600"})
app.teardown_appcontext(db.close_db)


# ------------------------------------------------------------ CSRF protection
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf_token", "")
        if not sent or sent != session.get("_csrf"):
            abort(400)


# ------------------------------------------------------------------ helpers
def load_analysis():
    """Read the raw tables and let analytics.py do all the calculations."""
    return analytics.analyse(
        db.query("SELECT * FROM students ORDER BY roll_no"),
        db.query("SELECT * FROM subjects ORDER BY subject_code"),
        db.query("SELECT * FROM marks"),
        db.query("SELECT * FROM attendance"),
    )


def role_required(*roles):
    """Allow a page only for logged-in users with one of the given roles."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            uid = session.get("user_id")
            user = db.query(
                "SELECT user_id, username, full_name, role, roll_no FROM users "
                "WHERE user_id = %s", (uid,), one=True) if uid else None
            if not user:
                session.clear()
                return redirect(url_for("login"))
            if roles and user["role"] not in roles:
                abort(403)
            g.user = user
            return view(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_globals():
    return {"user": g.get("user"), "cfg": config, "csrf_token": csrf_token}


def to_int(text):
    """Convert a form value to int, or return None if it is not a number."""
    try:
        return int(str(text).strip())
    except (ValueError, TypeError):
        return None


# -------------------------------------------------------------- login/logout
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = db.query("SELECT * FROM users WHERE username = %s", (username,), one=True)
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user_id"] = row["user_id"]
            return redirect(url_for("dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@role_required()
def dashboard():
    if g.user["role"] == "Student":
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("staff_dashboard"))


# ------------------------------------------------------------ staff dashboard
@app.route("/staff")
@role_required("Admin", "Faculty")
def staff_dashboard():
    return render_template("staff_dashboard.html", a=load_analysis())


@app.route("/staff/results")
@role_required("Admin", "Faculty")
def results():
    a = load_analysis()
    rows = sorted(a["students"], key=lambda r: (r["rank"] is None, r["rank"] or 0, r["roll_no"]))
    return render_template("results.html", a=a, rows=rows)


@app.route("/staff/results.csv")
@role_required("Admin", "Faculty")
def results_csv():
    a = load_analysis()
    codes = [s["subject_code"] for s in a["subjects"]]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Rank", "Roll No", "Name"] + codes +
               ["Total", "Max", "Percentage", "Grade", "Result", "Attendance %"])
    for r in sorted(a["students"], key=lambda r: (r["rank"] is None, r["rank"] or 0)):
        by_code = {s["subject_code"]: s["total"] for s in r["subjects"]}
        w.writerow([r["rank"] or "-", r["roll_no"], r["name"]] +
                   [by_code.get(c, "") for c in codes] +
                   [r["total"], r["max_total"], r["percentage"], r["grade"],
                    r["result"], r["att_pct"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=class_results.csv"})


def student_extras(a, me):
    """Insights and radar-chart data for one student."""
    stats = {s["subject_code"]: s for s in a["subject_stats"]}
    radar = {
        "labels": [s["subject_code"] for s in me["subjects"]],
        "me": [s["percentage"] for s in me["subjects"]],
        "avg": [stats[s["subject_code"]]["average_pct"] for s in me["subjects"]],
    }
    return analytics.student_insights(me, a), radar


@app.route("/staff/student/<roll_no>")
@role_required("Admin", "Faculty")
def staff_view_student(roll_no):
    a = load_analysis()
    me = next((s for s in a["students"] if s["roll_no"] == roll_no), None)
    if not me:
        abort(404)
    tips, radar = student_extras(a, me)
    return render_template("student_dashboard.html", me=me, a=a, staff_view=True,
                           tips=tips, radar=radar)


# ------------------------------------------------------------- marks entry
@app.route("/staff/marks", methods=["GET", "POST"])
@role_required("Admin", "Faculty")
def marks_entry():
    subjects = db.query("SELECT * FROM subjects ORDER BY subject_code")
    students = db.query("SELECT roll_no, name FROM students ORDER BY roll_no")
    code = request.values.get("subject") or (subjects[0]["subject_code"] if subjects else None)
    subject = next((s for s in subjects if s["subject_code"] == code), None)

    if request.method == "POST" and subject:
        errors, saved = [], 0
        for st in students:
            roll = st["roll_no"]
            raw_i = request.form.get("internal_" + roll, "").strip()
            raw_e = request.form.get("external_" + roll, "").strip()
            if raw_i == "" and raw_e == "":
                continue
            internal, external = to_int(raw_i), to_int(raw_e)
            if internal is None or external is None:
                errors.append("%s: enter both internal and external marks as numbers." % roll)
                continue
            if not 0 <= internal <= subject["max_internal"]:
                errors.append("%s: internal must be between 0 and %d." % (roll, subject["max_internal"]))
                continue
            if not 0 <= external <= subject["max_external"]:
                errors.append("%s: external must be between 0 and %d." % (roll, subject["max_external"]))
                continue
            old = db.query("SELECT mark_id FROM marks WHERE roll_no = %s AND subject_code = %s",
                           (roll, code), one=True)
            if old:
                db.execute("UPDATE marks SET internal = %s, external = %s WHERE mark_id = %s",
                           (internal, external, old["mark_id"]))
            else:
                db.execute("INSERT INTO marks (roll_no, subject_code, internal, external) "
                           "VALUES (%s, %s, %s, %s)", (roll, code, internal, external))
            saved += 1
        for e in errors:
            flash(e, "error")
        if saved:
            flash("Marks saved for %d student(s)." % saved, "success")
        return redirect(url_for("marks_entry", subject=code))

    existing = {m["roll_no"]: m for m in db.query(
        "SELECT * FROM marks WHERE subject_code = %s", (code,))} if code else {}
    return render_template("marks_entry.html", subjects=subjects, subject=subject,
                           students=students, existing=existing)


@app.route("/staff/marks/template.csv")
@role_required("Admin", "Faculty")
def marks_template():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["roll_no", "subject_code", "internal", "external"])
    w.writerow(["25102A0430", "CS301", 35, 52])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=marks_template.csv"})


@app.route("/staff/marks/upload", methods=["POST"])
@role_required("Admin", "Faculty")
def marks_upload():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".csv"):
        flash("Please choose a .csv file (use the template for the format).", "error")
        return redirect(url_for("marks_entry"))
    try:
        text = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("Could not read the file. Save it as CSV (UTF-8).", "error")
        return redirect(url_for("marks_entry"))
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    need = {"roll_no", "subject_code", "internal", "external"}
    if not need.issubset(set(reader.fieldnames)):
        flash("CSV must have the columns: roll_no, subject_code, internal, external.", "error")
        return redirect(url_for("marks_entry"))

    students = {s["roll_no"] for s in db.query("SELECT roll_no FROM students")}
    subjects = {s["subject_code"]: s for s in db.query("SELECT * FROM subjects")}
    saved, errors = 0, []
    for line, row in enumerate(reader, start=2):
        roll = (row.get("roll_no") or "").strip().upper()
        code = (row.get("subject_code") or "").strip().upper()
        internal, external = to_int(row.get("internal")), to_int(row.get("external"))
        sub = subjects.get(code)
        if roll not in students:
            errors.append("line %d: unknown roll number %s" % (line, roll))
        elif not sub:
            errors.append("line %d: unknown subject %s" % (line, code))
        elif internal is None or external is None:
            errors.append("line %d: marks must be numbers" % line)
        elif not 0 <= internal <= sub["max_internal"] or not 0 <= external <= sub["max_external"]:
            errors.append("line %d: marks out of range for %s" % (line, code))
        else:
            old = db.query("SELECT mark_id FROM marks WHERE roll_no = %s AND subject_code = %s",
                           (roll, code), one=True)
            if old:
                db.execute("UPDATE marks SET internal = %s, external = %s WHERE mark_id = %s",
                           (internal, external, old["mark_id"]))
            else:
                db.execute("INSERT INTO marks (roll_no, subject_code, internal, external) "
                           "VALUES (%s, %s, %s, %s)", (roll, code, internal, external))
            saved += 1
    if saved:
        flash("Uploaded: %d mark row(s) saved." % saved, "success")
    for e in errors[:5]:
        flash("Skipped - " + e, "error")
    if len(errors) > 5:
        flash("...and %d more rows skipped." % (len(errors) - 5), "error")
    return redirect(url_for("marks_entry"))


# -------------------------------------------------------- attendance entry
@app.route("/staff/attendance", methods=["GET", "POST"])
@role_required("Admin", "Faculty")
def attendance_entry():
    subjects = db.query("SELECT * FROM subjects ORDER BY subject_code")
    students = db.query("SELECT roll_no, name FROM students ORDER BY roll_no")
    code = request.values.get("subject") or (subjects[0]["subject_code"] if subjects else None)
    subject = next((s for s in subjects if s["subject_code"] == code), None)

    if request.method == "POST" and subject:
        held = to_int(request.form.get("classes_held"))
        if held is None or held <= 0:
            flash("Enter the total number of classes held (a positive number).", "error")
            return redirect(url_for("attendance_entry", subject=code))
        errors, saved = [], 0
        for st in students:
            roll = st["roll_no"]
            raw = request.form.get("attended_" + roll, "").strip()
            if raw == "":
                continue
            attended = to_int(raw)
            if attended is None or not 0 <= attended <= held:
                errors.append("%s: classes attended must be between 0 and %d." % (roll, held))
                continue
            old = db.query("SELECT att_id FROM attendance WHERE roll_no = %s AND subject_code = %s",
                           (roll, code), one=True)
            if old:
                db.execute("UPDATE attendance SET classes_held = %s, classes_attended = %s "
                           "WHERE att_id = %s", (held, attended, old["att_id"]))
            else:
                db.execute("INSERT INTO attendance (roll_no, subject_code, classes_held, classes_attended) "
                           "VALUES (%s, %s, %s, %s)", (roll, code, held, attended))
            saved += 1
        for e in errors:
            flash(e, "error")
        if saved:
            flash("Attendance saved for %d student(s)." % saved, "success")
        return redirect(url_for("attendance_entry", subject=code))

    existing = {a["roll_no"]: a for a in db.query(
        "SELECT * FROM attendance WHERE subject_code = %s", (code,))} if code else {}
    held_default = next(iter(existing.values()))["classes_held"] if existing else ""
    return render_template("attendance_entry.html", subjects=subjects, subject=subject,
                           students=students, existing=existing, held_default=held_default)


# ------------------------------------------------------------------ alerts
@app.route("/staff/alerts")
@role_required("Admin", "Faculty")
def alerts():
    return render_template("alerts.html", a=load_analysis())


@app.route("/staff/alerts/send", methods=["POST"])
@role_required("Admin", "Faculty")
def send_alerts():
    sent, problems = 0, []
    for r in load_analysis()["alerts"]:
        if not r["email"]:
            continue
        ok, err = mailer.send_alert(r["email"], r["name"], r["alerts"])
        if ok:
            sent += 1
        else:
            problems.append(err)
            break                       # same error would repeat for everyone
    if sent:
        flash("Alert e-mails sent to %d student(s)." % sent, "success")
    elif problems:
        flash("E-mail not sent: " + problems[0], "error")
    else:
        flash("No student with an alert has an e-mail address saved.", "error")
    return redirect(url_for("alerts"))


# ------------------------------------------------------------ admin: students
@app.route("/admin/students", methods=["GET", "POST"])
@role_required("Admin")
def manage_students():
    if request.method == "POST":
        roll = request.form.get("roll_no", "").strip().upper()
        name = request.form.get("name", "").strip().upper()
        section = request.form.get("section", "").strip().upper()
        email = request.form.get("email", "").strip() or None
        if not roll or not name or not section:
            flash("Roll number, name and section are required.", "error")
        else:
            try:
                db.execute("INSERT INTO students (roll_no, name, email, section) "
                           "VALUES (%s, %s, %s, %s)", (roll, name, email, section))
                db.execute("INSERT INTO users (username, password_hash, full_name, role, roll_no) "
                           "VALUES (%s, %s, %s, %s, %s)",
                           (roll, generate_password_hash(config.DEFAULT_STUDENT_PASSWORD),
                            name.title(), "Student", roll))
                flash("Student %s added. Login: %s / %s" %
                      (roll, roll, config.DEFAULT_STUDENT_PASSWORD), "success")
            except db.integrity_errors():
                flash("A student or user with roll number %s already exists." % roll, "error")
        return redirect(url_for("manage_students"))
    students = db.query("SELECT * FROM students ORDER BY roll_no")
    return render_template("students.html", students=students)


@app.route("/admin/students/<roll_no>/delete", methods=["POST"])
@role_required("Admin")
def delete_student(roll_no):
    db.execute("DELETE FROM users WHERE roll_no = %s", (roll_no,))
    db.execute("DELETE FROM marks WHERE roll_no = %s", (roll_no,))
    db.execute("DELETE FROM attendance WHERE roll_no = %s", (roll_no,))
    db.execute("DELETE FROM students WHERE roll_no = %s", (roll_no,))
    flash("Student %s deleted." % roll_no, "success")
    return redirect(url_for("manage_students"))


# ------------------------------------------------------------ admin: subjects
@app.route("/admin/subjects", methods=["GET", "POST"])
@role_required("Admin")
def manage_subjects():
    if request.method == "POST":
        code = request.form.get("subject_code", "").strip().upper()
        name = request.form.get("subject_name", "").strip()
        faculty = request.form.get("faculty_name", "").strip()
        max_i = to_int(request.form.get("max_internal", "40"))
        max_e = to_int(request.form.get("max_external", "60"))
        if not code or not name or not faculty or not max_i or not max_e or max_i < 0 or max_e < 0:
            flash("All fields are required and maximum marks must be positive numbers.", "error")
        else:
            try:
                db.execute("INSERT INTO subjects (subject_code, subject_name, faculty_name, "
                           "max_internal, max_external) VALUES (%s, %s, %s, %s, %s)",
                           (code, name, faculty, max_i, max_e))
                flash("Subject %s added." % code, "success")
            except db.integrity_errors():
                flash("Subject code %s already exists." % code, "error")
        return redirect(url_for("manage_subjects"))
    return render_template("subjects.html",
                           subjects=db.query("SELECT * FROM subjects ORDER BY subject_code"))


@app.route("/admin/subjects/<code>/delete", methods=["POST"])
@role_required("Admin")
def delete_subject(code):
    db.execute("DELETE FROM marks WHERE subject_code = %s", (code,))
    db.execute("DELETE FROM attendance WHERE subject_code = %s", (code,))
    db.execute("DELETE FROM subjects WHERE subject_code = %s", (code,))
    flash("Subject %s deleted." % code, "success")
    return redirect(url_for("manage_subjects"))


# ---------------------------------------------------------- admin: faculty
@app.route("/admin/faculty", methods=["GET", "POST"])
@role_required("Admin")
def manage_faculty():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        if not username or not full_name or len(password) < 6:
            flash("Username and name are required; password needs at least 6 characters.", "error")
        else:
            try:
                db.execute("INSERT INTO users (username, password_hash, full_name, role, roll_no) "
                           "VALUES (%s, %s, %s, %s, %s)",
                           (username, generate_password_hash(password), full_name, "Faculty", None))
                flash("Faculty user %s created." % username, "success")
            except db.integrity_errors():
                flash("Username %s is already taken." % username, "error")
        return redirect(url_for("manage_faculty"))
    staff = db.query("SELECT user_id, username, full_name, role FROM users "
                     "WHERE role IN ('Admin', 'Faculty') ORDER BY role, username")
    return render_template("faculty.html", staff=staff)


@app.route("/admin/faculty/<int:user_id>/delete", methods=["POST"])
@role_required("Admin")
def delete_faculty(user_id):
    if user_id == g.user["user_id"]:
        flash("You cannot delete your own account.", "error")
    else:
        db.execute("DELETE FROM users WHERE user_id = %s AND role = 'Faculty'", (user_id,))
        flash("Faculty user deleted.", "success")
    return redirect(url_for("manage_faculty"))


# ---------------------------------------------------------------- student
@app.route("/student")
@role_required("Student")
def student_dashboard():
    a = load_analysis()
    me = next((s for s in a["students"] if s["roll_no"] == g.user["roll_no"]), None)
    if not me:
        abort(404)
    tips, radar = student_extras(a, me)
    return render_template("student_dashboard.html", me=me, a=a, staff_view=False,
                           tips=tips, radar=radar)


@app.route("/report/<roll_no>")
@role_required("Admin", "Faculty", "Student")
def report(roll_no):
    if g.user["role"] == "Student" and g.user["roll_no"] != roll_no:
        abort(403)
    a = load_analysis()
    me = next((s for s in a["students"] if s["roll_no"] == roll_no), None)
    if not me:
        abort(404)
    return render_template("report.html", me=me, a=a)


# ------------------------------------------------------------ diagnostics
@app.route("/health")
def health():
    """Open /health on the live site to see whether the database and files are fine."""
    import os
    info = {"database_type": config.DB_TYPE}
    try:
        info["students_in_database"] = db.query("SELECT COUNT(*) AS c FROM students", one=True)["c"]
        info["status"] = "ok"
    except Exception as exc:
        info["status"] = "error"
        info["error"] = repr(exc)
    info["pages_loaded"] = len(site_assets.TEMPLATES)
    info["static_files_loaded"] = len(site_assets.STATIC)
    return info


# ----------------------------------------------------------------- account
@app.route("/account", methods=["GET", "POST"])
@role_required("Admin", "Faculty", "Student")
def account():
    if request.method == "POST":
        row = db.query("SELECT password_hash FROM users WHERE user_id = %s",
                       (g.user["user_id"],), one=True)
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        if not check_password_hash(row["password_hash"], current):
            flash("Current password is wrong.", "error")
        elif len(new) < 6:
            flash("New password must have at least 6 characters.", "error")
        elif new != confirm:
            flash("New password and confirmation do not match.", "error")
        else:
            db.execute("UPDATE users SET password_hash = %s WHERE user_id = %s",
                       (generate_password_hash(new), g.user["user_id"]))
            flash("Password changed successfully.", "success")
        return redirect(url_for("account"))
    return render_template("account.html")


# ------------------------------------------------------------------ errors
@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400,
                           message="The form expired. Go back, refresh the page and try again."), 400

@app.errorhandler(500)
def server_error(e):
    app.logger.exception("Unhandled error: %s", e)
    return ("<h2>Something went wrong on the server.</h2>"
            "<p>Open <a href='/health'>/health</a> to see what is wrong, "
            "and check the hosting log for the line starting with 'Traceback'.</p>"), 500


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


# -------------------------------------------------------------------- start
def prepare_database():
    try:
        db.init_db()
    except Exception as exc:
        print("\nCould not prepare the database (%s mode):\n  %s\n" % (config.DB_TYPE, exc))
        if db.is_mysql():
            print("Check that MySQL is running and that MYSQL_USER / MYSQL_PASSWORD in "
                  "config.py are correct,\nor set DB_TYPE = \"sqlite\" to run without MySQL.")
        sys.exit(1)


prepare_database()

if __name__ == "__main__":
    print("\n  Open  http://127.0.0.1:5000  in your browser\n")
    app.run(debug=True)
