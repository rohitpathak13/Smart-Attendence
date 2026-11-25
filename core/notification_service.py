"""
SmartAttend AI - Multi-Channel Notification Service
Handles automated alerts and transactional communications:
- Attendance confirmation (instant push/email)
- Absence notifications
- Late arrival alerts
- Low attendance shortage warnings (<75% threshold)
- Parent alerts (daily absence / shortage warning)
- Teacher summary alerts
- Administrator security & system alerts

SECURITY & RELIABILITY RULES:
- Never hardcode SMTP credentials.
- Reads SMTP settings safely from config / environment.
- If SMTP server is unreachable or unconfigured, records notification safely
  to the database queue with error status without crashing or interrupting operations.
"""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
import smtplib
from typing import Dict, List, Optional, Tuple, Any
import config

logger = logging.getLogger(__name__)


class NotificationType:
    CONFIRMATION = "ATTENDANCE_CONFIRMED"
    ABSENT = "STUDENT_ABSENT"
    LATE = "STUDENT_LATE"
    LOW_ATTENDANCE = "LOW_ATTENDANCE_WARNING"
    PARENT_ALERT = "PARENT_ATTENDANCE_ALERT"
    TEACHER_SESSION_SUMMARY = "TEACHER_SESSION_SUMMARY"
    ADMIN_SECURITY_ALERT = "ADMIN_SECURITY_ALERT"
    LEAVE_STATUS_UPDATE = "LEAVE_STATUS_UPDATE"


class NotificationService:
    """
    Manages notifications across student, parent, teacher, and admin channels.
    Persists all messages into the database queue.
    """

    def __init__(self, db_manager: Any):
        self.db = db_manager

    def queue_notification(
        self,
        recipient_type: str,
        recipient_id: int,
        recipient_email: Optional[str],
        notification_type: str,
        subject: str,
        body: str
    ) -> int:
        """
        Stores a notification in the database queue and attempts delivery if SMTP is configured.
        Returns the queued notification ID.
        """
        notif_id = self.db.create_notification_record(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            recipient_email=recipient_email,
            notification_type=notification_type,
            subject=subject,
            body=body
        )

        smtp_host = getattr(config, "SMTP_HOST", getattr(config, "SMTP_SERVER", ""))
        smtp_user = getattr(config, "SMTP_USER", "")
        # Attempt immediate delivery if recipient has an email
        if recipient_email and smtp_host and smtp_user:
            self._send_email(notif_id, recipient_email, subject, body)

        return notif_id

    def _send_email(self, notif_id: int, to_email: str, subject: str, body: str) -> bool:
        """
        Attempts to deliver an email via SMTP securely.
        Updates notification status in database upon success or failure.
        """
        smtp_host = getattr(config, "SMTP_HOST", getattr(config, "SMTP_SERVER", ""))
        smtp_user = getattr(config, "SMTP_USER", "")
        smtp_pass = getattr(config, "SMTP_PASSWORD", getattr(config, "SMTP_PASS", ""))
        smtp_port = getattr(config, "SMTP_PORT", 587)
        smtp_tls = getattr(config, "SMTP_USE_TLS", True)
        smtp_from = getattr(config, "SMTP_FROM", smtp_user)

        if not smtp_host or not smtp_user:
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[SmartAttend AI] {subject}"
            msg["From"] = smtp_from or smtp_user
            msg["To"] = to_email

            part_text = MIMEText(body, "plain")
            msg.attach(part_text)

            # HTML version
            html_body = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
                <div style="border-bottom: 2px solid #4F46E5; padding-bottom: 10px; margin-bottom: 20px;">
                    <h2 style="color: #4F46E5; margin: 0;">SmartAttend AI</h2>
                    <p style="margin: 0; font-size: 12px; color: #666;">Intelligent Attendance & College Management</p>
                </div>
                <div style="white-space: pre-line; line-height: 1.6;">{body}</div>
                <div style="margin-top: 30px; padding-top: 10px; border-top: 1px solid #eee; font-size: 11px; color: #888;">
                    This is an automated institutional notification from SmartAttend AI. Please do not reply directly to this email.
                </div>
            </div>
            """
            part_html = MIMEText(html_body, "html")
            msg.attach(part_html)

            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            if smtp_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            
            server.sendmail(msg["From"], [to_email], msg.as_string())
            server.quit()

            self.db.mark_notification_sent(notif_id, is_sent=1)
            return True
        except Exception as e:
            logger.warning(f"SMTP delivery failed for notification {notif_id}: {e}")
            self.db.mark_notification_sent(notif_id, is_sent=0, error_message=str(e))
            return False

    # --- Convenience Trigger Methods ---
    def notify_attendance_marked(
        self,
        student_id: int,
        student_name: str,
        student_email: Optional[str],
        subject_name: str,
        timestamp: str
    ):
        subject = f"Attendance Confirmed - {subject_name}"
        body = (
            f"Dear {student_name},\n\n"
            f"Your attendance has been successfully recorded for {subject_name} at {timestamp}.\n\n"
            f"You can check your live attendance record on the SmartAttend Student Portal."
        )
        return self.queue_notification(
            recipient_type="STUDENT",
            recipient_id=student_id,
            recipient_email=student_email,
            notification_type=NotificationType.CONFIRMATION,
            subject=subject,
            body=body
        )

    def notify_low_attendance_warning(
        self,
        student_id: int,
        student_name: str,
        student_email: Optional[str],
        current_pct: float,
        classes_needed: int
    ):
        subject = f"Urgent: Attendance Shortage Warning ({current_pct:.1f}%)"
        body = (
            f"Dear {student_name},\n\n"
            f"Your current attendance has fallen to {current_pct:.1f}%, which is below the mandatory 75% institutional threshold.\n\n"
            f"You must attend at least {classes_needed} consecutive upcoming classes without absence to regain the required standing.\n\n"
            f"Please meet your academic advisor immediately if you have valid medical or official reasons."
        )
        return self.queue_notification(
            recipient_type="STUDENT",
            recipient_id=student_id,
            recipient_email=student_email,
            notification_type=NotificationType.LOW_ATTENDANCE,
            subject=subject,
            body=body
        )

    def notify_parent_absence(
        self,
        parent_id: int,
        parent_name: str,
        parent_email: Optional[str],
        student_name: str,
        subject_name: str,
        date_str: str
    ):
        subject = f"Absence Notice: {student_name} - {subject_name}"
        body = (
            f"Dear {parent_name},\n\n"
            f"This is an automated notification to inform you that {student_name} was marked absent for {subject_name} on {date_str}.\n\n"
            f"If this absence is unexcused, please review this with the student. For medical or official leave, please submit a leave request via the parent portal."
        )
        return self.queue_notification(
            recipient_type="PARENT",
            recipient_id=parent_id,
            recipient_email=parent_email,
            notification_type=NotificationType.PARENT_ALERT,
            subject=subject,
            body=body
        )
