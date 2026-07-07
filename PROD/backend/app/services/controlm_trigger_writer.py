"""ControlM trigger file writer — handles atomic file writes to the landing zone.

Responsible for generating trigger and recovery files with correct naming,
content formatting, and atomic write semantics (temp file + rename) so that
ControlM File Watchers never detect partial files.
"""
import logging
import os
import re
import tempfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.controlm_settings import ControlMSettings
from app.models.alert_rule import AlertRule
from app.schemas.notifications import AlertContext

logger = logging.getLogger(__name__)


class TriggerFileWriter:
    """Writes trigger and recovery files atomically to the landing zone."""

    def write_trigger_file(
        self, rule: AlertRule, context: AlertContext, timestamp: datetime
    ) -> tuple[bool, str]:
        """Write a trigger file to the landing zone.

        Returns (success, file_path_or_error).
        """
        try:
            db: Session = SessionLocal()
            try:
                landing_zone = self._get_landing_zone(db)
            finally:
                db.close()

            sanitized = self.sanitize_name(rule.name)
            ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"CROIT_ALERT_{sanitized}_{ts_str}.trigger"
            content = self.format_file_content(rule, context, timestamp)

            self._atomic_write(landing_zone, filename, content)

            file_path = os.path.join(landing_zone, filename)
            logger.info(
                "Trigger file written: %s for rule '%s'", file_path, rule.name
            )
            return (True, file_path)

        except Exception as e:
            error_msg = f"Failed to write trigger file for rule '{rule.name}': {e}"
            logger.error(error_msg)
            return (False, error_msg)

    def write_recovery_file(
        self, rule: AlertRule, timestamp: datetime
    ) -> tuple[bool, str]:
        """Write a recovery file to the landing zone.

        Returns (success, file_path_or_error).
        """
        try:
            db: Session = SessionLocal()
            try:
                landing_zone = self._get_landing_zone(db)
            finally:
                db.close()

            sanitized = self.sanitize_name(rule.name)
            ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"CROIT_RECOVERY_{sanitized}_{ts_str}.trigger"
            content = f"rule_name={rule.name}\nevent=RECOVERY\ntimestamp={timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"

            self._atomic_write(landing_zone, filename, content)

            file_path = os.path.join(landing_zone, filename)
            logger.info(
                "Recovery file written: %s for rule '%s'", file_path, rule.name
            )
            return (True, file_path)

        except Exception as e:
            error_msg = f"Failed to write recovery file for rule '{rule.name}': {e}"
            logger.error(error_msg)
            return (False, error_msg)

    @staticmethod
    def sanitize_name(name: str) -> str:
        """Replace non-alphanumeric chars (except _) with _, truncate to 100 chars.

        Returns 'UNKNOWN' if the sanitized result is empty.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        sanitized = sanitized[:100]
        if not sanitized:
            return "UNKNOWN"
        return sanitized

    @staticmethod
    def format_file_content(
        rule: AlertRule, context: AlertContext, timestamp: datetime
    ) -> str:
        """Generate KEY=VALUE content for the trigger file.

        Keys: rule_name, route_id, route_name, condition_type,
        failure_message (truncated to 500 chars), alert_timestamp (ISO 8601 UTC),
        severity (CRITICAL if rule.critical else WARNING).
        """
        # Extract failure message from context metric_values
        if context.metric_values:
            failure_message = str(context.metric_values)
        else:
            failure_message = ""
        # Truncate to 500 characters
        failure_message = failure_message[:500]

        severity = "CRITICAL" if rule.critical else "WARNING"
        alert_timestamp = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")

        lines = [
            f"rule_name={rule.name}",
            f"route_id={context.route_id}",
            f"route_name={context.route_name}",
            f"condition_type={context.condition_type}",
            f"failure_message={failure_message}",
            f"alert_timestamp={alert_timestamp}",
            f"severity={severity}",
        ]
        return "\n".join(lines) + "\n"

    def _get_landing_zone(self, db: Session) -> str:
        """Read landing_zone path from controlm_settings table."""
        settings_row = db.query(ControlMSettings).filter(
            ControlMSettings.id == 1
        ).first()
        if settings_row and settings_row.landing_zone:
            return settings_row.landing_zone
        # Fallback default
        return "/app/data/controlm_alerts/"

    def _atomic_write(
        self, landing_zone: str, filename: str, content: str
    ) -> None:
        """Write to a temp file in the landing zone dir, then os.rename() to final path.

        Creates the landing zone directory if it doesn't exist.
        """
        os.makedirs(landing_zone, exist_ok=True)

        final_path = os.path.join(landing_zone, filename)

        # Write to a temp file in the same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            dir=landing_zone, prefix=".tmp_", suffix=".trigger"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            # Atomic rename
            os.rename(tmp_path, final_path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# Module-level singleton
trigger_writer = TriggerFileWriter()
