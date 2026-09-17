# Lifecycle stage 10 — Quarantine store
#
# Kept as the public entry point for quarantining a message. The actual CSV
# handling now lives in src/storage/message_store.py, which manages both the
# quarantine and the inbox mailboxes with a shared schema so the dashboard can
# list, count and move messages.
#
# The function signature is unchanged, so existing callers keep working.

from src.storage.message_store import QUARANTINE, QUARANTINE_FILE, add_message

__all__ = ["quarantine_email", "QUARANTINE_FILE"]


def quarantine_email(email_text, label, confidence=None):
    """Append a spam message to data/quarantine/quarantine.csv."""
    return add_message(QUARANTINE, email_text, label, confidence=confidence)
