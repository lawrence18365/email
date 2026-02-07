"""
Email verification via Verifalia API (25 free/day).
Verifies emails just-in-time before sending to protect sender reputation.
"""

import os
import logging
import requests
from datetime import datetime, date

logger = logging.getLogger(__name__)

VERIFALIA_API_URL = "https://api.verifalia.com/v2.7/email-validations"


class EmailVerifier:
    """Verifalia email verification with daily quota tracking."""

    def __init__(self, db_session):
        self.db_session = db_session
        self.username = os.getenv('VERIFALIA_USERNAME', '')
        self.password = os.getenv('VERIFALIA_PASSWORD', '')

    def _has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def verify_email(self, lead) -> str:
        """
        Verify a lead's email address.

        Returns the classification: 'Deliverable', 'Undeliverable', 'Risky', 'Unknown', or 'Skipped'.
        Updates the lead record with verification results.
        """
        # Already verified today - use cached result
        if lead.email_verified_at and lead.email_verified_at.date() == date.today():
            logger.debug(f"Using cached verification for {lead.email}: {lead.email_verification_status}")
            return lead.email_verification_status or 'Unknown'

        # Already permanently classified as undeliverable
        if lead.email_verification_status == 'Undeliverable':
            return 'Undeliverable'

        if not self._has_credentials():
            logger.warning("Verifalia credentials not configured, skipping verification")
            return 'Skipped'

        # Check daily quota
        if not self._has_quota_remaining():
            logger.info("Verifalia daily quota exhausted (25/day), skipping verification")
            return 'Skipped'

        # Call Verifalia API
        try:
            status = self._call_verifalia(lead.email)

            # Update lead record
            lead.email_verification_status = status
            lead.email_verified_at = datetime.utcnow()
            if status == 'Deliverable':
                lead.email_verified = True
            self.db_session.commit()

            logger.info(f"Verified {lead.email}: {status}")
            return status

        except Exception as e:
            logger.error(f"Verifalia verification failed for {lead.email}: {e}")
            return 'Skipped'

    def _call_verifalia(self, email: str) -> str:
        """Call Verifalia API to verify a single email. Returns classification string."""
        resp = requests.post(
            f"{VERIFALIA_API_URL}?waitTime=30000",
            json={"entries": [{"inputData": email}]},
            auth=(self.username, self.password),
            timeout=35,
        )

        if resp.status_code == 200:
            # Completed synchronously
            data = resp.json()
            return self._extract_classification(data)

        if resp.status_code == 202:
            # Job accepted but not complete yet - poll for result
            data = resp.json()
            job_url = data.get('overview', {}).get('id')
            if job_url:
                return self._poll_result(job_url)
            return 'Unknown'

        if resp.status_code == 401:
            logger.error("Verifalia authentication failed - check VERIFALIA_USERNAME/PASSWORD")
            raise ValueError("Verifalia auth failed")

        if resp.status_code == 402:
            logger.warning("Verifalia daily quota exceeded (402)")
            return 'Skipped'

        if resp.status_code == 429:
            logger.warning("Verifalia rate limited (429)")
            return 'Skipped'

        logger.error(f"Verifalia API error: {resp.status_code} {resp.text[:200]}")
        return 'Unknown'

    def _poll_result(self, job_id: str, max_attempts: int = 6) -> str:
        """Poll for async job completion."""
        import time
        url = f"{VERIFALIA_API_URL}/{job_id}?waitTime=10000"

        for _ in range(max_attempts):
            resp = requests.get(
                url,
                auth=(self.username, self.password),
                timeout=15,
            )
            if resp.status_code == 200:
                return self._extract_classification(resp.json())
            time.sleep(5)

        logger.warning(f"Verifalia job {job_id} did not complete in time")
        return 'Unknown'

    def _extract_classification(self, data: dict) -> str:
        """Extract the classification from a completed job response."""
        try:
            entries = data.get('entries', {}).get('data', [])
            if entries:
                return entries[0].get('classification', 'Unknown')
        except (KeyError, IndexError, TypeError):
            pass
        return 'Unknown'

    def _has_quota_remaining(self) -> int:
        """Check if we've used fewer than 25 verifications today."""
        from models import Lead
        today_start = datetime.combine(date.today(), datetime.min.time())
        verified_today = Lead.query.filter(
            Lead.email_verified_at >= today_start,
            Lead.email_verified_at.isnot(None),
        ).count()
        remaining = 25 - verified_today
        if remaining <= 0:
            return False
        logger.debug(f"Verifalia quota: {remaining}/25 remaining today")
        return True

    def should_send(self, status: str) -> bool:
        """Decide whether to proceed with sending based on verification status."""
        # Send if deliverable, skipped (no credentials/quota), or unknown
        # Block only confirmed undeliverable
        if status == 'Undeliverable':
            return False
        # Risky = catch-all, disposable, etc. - skip these too
        if status == 'Risky':
            return False
        return True
