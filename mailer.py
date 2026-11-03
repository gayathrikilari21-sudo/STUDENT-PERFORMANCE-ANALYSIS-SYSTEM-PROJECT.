"""Optional e-mail alerts (extension).  Disabled unless SMTP_ENABLED = True."""
import smtplib
from email.message import EmailMessage
import config


def send_alert(to_address, student_name, reasons):
    """Send one alert e-mail.  Returns (True, "") or (False, error message)."""
    if not config.SMTP_ENABLED:
        return False, "E-mail is disabled (set SMTP_ENABLED = True in config.py)."
    msg = EmailMessage()
    msg["Subject"] = "Academic alert - Student Performance Analysis System"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_address
    body = "Dear %s,\n\nThe system has found the following points in your academic record:\n\n" % student_name
    body += "\n".join("  - " + r for r in reasons)
    body += "\n\nPlease meet your mentor and improve your performance.\n\nMohan Babu University"
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True, ""
    except Exception as exc:  # network / login problems
        return False, str(exc)
