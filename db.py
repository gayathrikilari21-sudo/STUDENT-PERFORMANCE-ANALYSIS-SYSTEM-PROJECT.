"""
Database layer.  The same code works with SQLite and MySQL.
All SQL in the project is written with %s placeholders; for SQLite they are
converted to ? automatically.
"""
import sqlite3
from flask import g
from werkzeug.security import generate_password_hash
import config


def is_mysql():
    return config.DB_TYPE.lower() == "mysql"


# ------------------------------------------------------------------ schema
MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS students (
        roll_no     VARCHAR(15)  PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        email       VARCHAR(120) NULL,
        branch      VARCHAR(30)  NOT NULL DEFAULT 'CSE',
        section     VARCHAR(5)   NOT NULL,
        study_year  TINYINT      NOT NULL DEFAULT 3
    )""",
    """CREATE TABLE IF NOT EXISTS subjects (
        subject_code  VARCHAR(10)  PRIMARY KEY,
        subject_name  VARCHAR(100) NOT NULL,
        faculty_name  VARCHAR(100) NOT NULL,
        max_internal  INT NOT NULL DEFAULT 40,
        max_external  INT NOT NULL DEFAULT 60
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        user_id        INT AUTO_INCREMENT PRIMARY KEY,
        username       VARCHAR(50)  NOT NULL UNIQUE,
        password_hash  VARCHAR(255) NOT NULL,
        full_name      VARCHAR(100) NOT NULL DEFAULT '',
        role           ENUM('Admin','Faculty','Student') NOT NULL,
        roll_no        VARCHAR(15) NULL,
        FOREIGN KEY (roll_no) REFERENCES students(roll_no) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS marks (
        mark_id       INT AUTO_INCREMENT PRIMARY KEY,
        roll_no       VARCHAR(15) NOT NULL,
        subject_code  VARCHAR(10) NOT NULL,
        internal      INT NOT NULL,
        external      INT NOT NULL,
        UNIQUE (roll_no, subject_code),
        FOREIGN KEY (roll_no)      REFERENCES students(roll_no)      ON DELETE CASCADE,
        FOREIGN KEY (subject_code) REFERENCES subjects(subject_code) ON DELETE CASCADE,
        CHECK (internal >= 0),
        CHECK (external >= 0)
    )""",
    """CREATE TABLE IF NOT EXISTS attendance (
        att_id            INT AUTO_INCREMENT PRIMARY KEY,
        roll_no           VARCHAR(15) NOT NULL,
        subject_code      VARCHAR(10) NOT NULL,
        classes_held      INT NOT NULL,
        classes_attended  INT NOT NULL,
        UNIQUE (roll_no, subject_code),
        FOREIGN KEY (roll_no)      REFERENCES students(roll_no)      ON DELETE CASCADE,
        FOREIGN KEY (subject_code) REFERENCES subjects(subject_code) ON DELETE CASCADE,
        CHECK (classes_attended <= classes_held)
    )""",
]

SQLITE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS students (
        roll_no     TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        email       TEXT,
        branch      TEXT NOT NULL DEFAULT 'CSE',
        section     TEXT NOT NULL,
        study_year  INTEGER NOT NULL DEFAULT 3
    )""",
    """CREATE TABLE IF NOT EXISTS subjects (
        subject_code  TEXT PRIMARY KEY,
        subject_name  TEXT NOT NULL,
        faculty_name  TEXT NOT NULL,
        max_internal  INTEGER NOT NULL DEFAULT 40,
        max_external  INTEGER NOT NULL DEFAULT 60
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        username       TEXT NOT NULL UNIQUE,
        password_hash  TEXT NOT NULL,
        full_name      TEXT NOT NULL DEFAULT '',
        role           TEXT NOT NULL CHECK (role IN ('Admin','Faculty','Student')),
        roll_no        TEXT,
        FOREIGN KEY (roll_no) REFERENCES students(roll_no) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS marks (
        mark_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no       TEXT NOT NULL,
        subject_code  TEXT NOT NULL,
        internal      INTEGER NOT NULL CHECK (internal >= 0),
        external      INTEGER NOT NULL CHECK (external >= 0),
        UNIQUE (roll_no, subject_code),
        FOREIGN KEY (roll_no)      REFERENCES students(roll_no)      ON DELETE CASCADE,
        FOREIGN KEY (subject_code) REFERENCES subjects(subject_code) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS attendance (
        att_id            INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_no           TEXT NOT NULL,
        subject_code      TEXT NOT NULL,
        classes_held      INTEGER NOT NULL,
        classes_attended  INTEGER NOT NULL CHECK (classes_attended <= classes_held),
        UNIQUE (roll_no, subject_code),
        FOREIGN KEY (roll_no)      REFERENCES students(roll_no)      ON DELETE CASCADE,
        FOREIGN KEY (subject_code) REFERENCES subjects(subject_code) ON DELETE CASCADE
    )""",
]

# ------------------------------------------------------------- connections
def _connect():
    if is_mysql():
        import pymysql
        return pymysql.connect(
            host=config.MYSQL_HOST, port=config.MYSQL_PORT,
            user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _prep(sql):
    return sql if is_mysql() else sql.replace("%s", "?")


def integrity_errors():
    errs = [sqlite3.IntegrityError]
    if is_mysql():
        import pymysql
        errs.append(pymysql.err.IntegrityError)
    return tuple(errs)


def _run(conn, sql, params=()):
    """Run one statement on a connection and return the cursor."""
    if is_mysql():
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    return conn.execute(_prep(sql), params)


def query(sql, params=(), one=False):
    """SELECT helper: returns a list of dicts (or one dict / None)."""
    cur = _run(get_db(), sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, params=()):
    """INSERT / UPDATE / DELETE helper (commits)."""
    conn = get_db()
    try:
        cur = _run(conn, sql, params)
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise


# -------------------------------------------------------------- initial data
def init_db():
    """Create the database/tables on first run and add demo data."""
    if is_mysql():
        import pymysql
        boot = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                               user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                               charset="utf8mb4")
        with boot.cursor() as cur:
            cur.execute("CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4"
                        % config.MYSQL_DATABASE)
        boot.commit()
        boot.close()

    conn = _connect()
    for stmt in (MYSQL_SCHEMA if is_mysql() else SQLITE_SCHEMA):
        _run(conn, stmt).close()
    conn.commit()

    cur = _run(conn, "SELECT COUNT(*) AS c FROM users")
    count = list(dict(cur.fetchone()).values())[0]
    cur.close()
    if count == 0:
        _seed(conn)
    conn.close()


def _seed(conn):
    def ex(sql, params=()):
        _run(conn, sql, params).close()

    students = [
        ("25102A0430", "ALLU JASWANTH REDDY"),
        ("25102A0393", "PALYAM VINAY"),
        ("25102A0404", "ELURI RATHNA SAHANA"),
        ("25102A0395", "K GAYATHRI"),
        ("25102A0406", "RAMAVATH SIVA SANKAR NAIK"),
    ]
    for roll, name in students:
        ex("INSERT INTO students (roll_no, name, section) VALUES (%s, %s, %s)",
           (roll, name, "A7"))

    subjects = [
        ("CS301", "Database Management Systems", "Faculty 1"),
        ("CS302", "Operating Systems", "Faculty 2"),
        ("CS303", "Computer Networks", "Faculty 3"),
        ("CS304", "Web Technologies", "Faculty 4"),
    ]
    for code, name, fac in subjects:
        ex("INSERT INTO subjects (subject_code, subject_name, faculty_name) "
           "VALUES (%s, %s, %s)", (code, name, fac))

    ex("INSERT INTO users (username, password_hash, full_name, role, roll_no) "
       "VALUES (%s, %s, %s, %s, %s)",
       ("admin", generate_password_hash("admin123"), "System Admin", "Admin", None))
    ex("INSERT INTO users (username, password_hash, full_name, role, roll_no) "
       "VALUES (%s, %s, %s, %s, %s)",
       ("faculty1", generate_password_hash("faculty123"), "Faculty 1", "Faculty", None))
    for roll, name in students:
        ex("INSERT INTO users (username, password_hash, full_name, role, roll_no) "
           "VALUES (%s, %s, %s, %s, %s)",
           (roll, generate_password_hash(config.DEFAULT_STUDENT_PASSWORD),
            name.title(), "Student", roll))

    marks = {
        "25102A0430": [(35, 52), (30, 45), (33, 50), (38, 55)],
        "25102A0393": [(28, 40), (25, 35), (30, 42), (32, 48)],
        "25102A0404": [(38, 57), (36, 54), (37, 55), (39, 58)],
        "25102A0395": [(20, 18), (18, 15), (22, 25), (25, 30)],
        "25102A0406": [(31, 44), (29, 38), (27, 36), (33, 46)],
    }
    attended = {
        "25102A0430": [38, 36, 37, 39],
        "25102A0393": [32, 30, 33, 35],
        "25102A0404": [40, 39, 38, 40],
        "25102A0395": [22, 24, 26, 28],
        "25102A0406": [34, 31, 29, 35],
    }
    codes = [s[0] for s in subjects]
    for roll, _ in students:
        for i, code in enumerate(codes):
            internal, external = marks[roll][i]
            ex("INSERT INTO marks (roll_no, subject_code, internal, external) "
               "VALUES (%s, %s, %s, %s)", (roll, code, internal, external))
            ex("INSERT INTO attendance (roll_no, subject_code, classes_held, classes_attended) "
               "VALUES (%s, %s, %s, %s)", (roll, code, 40, attended[roll][i]))
    conn.commit()
