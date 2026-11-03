"""
Project settings.  Edit this file to change the database or the rules.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ---------------------------------------------------------------
# DATABASE
#   "sqlite" -> works immediately, no installation (default)
#   "mysql"  -> uses MySQL; fill in the MYSQL_* values below
# ---------------------------------------------------------------
DB_TYPE = os.environ.get("DB_TYPE", "sqlite")

def _db_path():
    """Use the project folder if it is writable, otherwise a temp folder (some hosts are read-only)."""
    import tempfile
    try:
        test = os.path.join(BASE_DIR, ".write_test")
        with open(test, "w") as f:
            f.write("x")
        os.remove(test)
        return os.path.join(BASE_DIR, "student_performance.db")
    except OSError:
        return os.path.join(tempfile.gettempdir(), "student_performance.db")


SQLITE_PATH = _db_path()

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "your_mysql_password")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "student_performance")

# ---------------------------------------------------------------
# APPLICATION
# ---------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key-before-real-use")

MIN_PERCENTAGE = 40      # below this a subject is "Fail" / overall marks alert
MIN_ATTENDANCE = 75      # below this percentage an attendance alert is raised

DEFAULT_STUDENT_PASSWORD = "student123"   # given to students created by Admin

# ---------------------------------------------------------------
# EMAIL ALERTS (optional extension).  Keep False if you do not need it.
# For Gmail use an "App Password", not your normal password.
# ---------------------------------------------------------------
SMTP_ENABLED = False
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your_email@gmail.com"
SMTP_PASSWORD = "your_app_password"
SMTP_FROM = "Student Performance System <your_email@gmail.com>"
