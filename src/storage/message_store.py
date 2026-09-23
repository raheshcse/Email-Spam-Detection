# Lifecycle stage 11 — Message store
#
# Every analysed message is filed into one of two CSV "mailboxes":
#
#   data/quarantine/quarantine.csv   messages predicted as spam
#   data/inbox/inbox.csv             messages predicted as ham
#
# CSV keeps the project dependency-free and the files stay openable in Excel.
# Writes go through a lock because uvicorn serves requests on a thread pool.

import csv
import os
import threading
import uuid
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

QUARANTINE_FILE = os.path.join(PROJECT_ROOT, "data", "quarantine", "quarantine.csv")
INBOX_FILE = os.path.join(PROJECT_ROOT, "data", "inbox", "inbox.csv")

QUARANTINE = "quarantine"
INBOX = "inbox"

BOXES = {QUARANTINE: QUARANTINE_FILE, INBOX: INBOX_FILE}

# Spam/ham has always been stored. The three phishing columns were added later
# so the Overview and Quarantine pages can show phishing as a first-class
# metric instead of inferring it from the spam label (which would be wrong -
# the two detectors are independent).
#
# Backwards compatibility: rows written before these columns existed simply
# have them empty. _normalise() fills the gap and _to_public() reports them as
# None, which the UI renders as "Phishing analysis unavailable" rather than
# guessing a verdict.
FIELDS = [
    "id", "timestamp", "label", "confidence", "moved", "text",
    "phishing_label", "phishing_confidence", "risk_level",
]

# The original quarantine.csv written by src/quarantine/store.py.
LEGACY_FIELDS = ["timestamp", "label", "email_text"]

# Values the phishing column may hold, mirroring the model's own labels.
PHISHING = "PHISHING"
LEGITIMATE = "LEGITIMATE"

_lock = threading.RLock()


class UnknownBox(ValueError):
    """Raised when a caller asks for a mailbox that does not exist."""


def _path_for(box):
    try:
        return BOXES[box]
    except KeyError:
        raise UnknownBox(f"Unknown mailbox '{box}'. Use 'quarantine' or 'inbox'.")


def _new_id():
    return uuid.uuid4().hex[:12]


def _normalise(row):
    """Coerce one CSV row into the current schema, upgrading legacy rows."""
    if "email_text" in row and "text" not in row:
        # Legacy layout: timestamp, label, email_text.
        return {
            "id": _new_id(),
            "timestamp": row.get("timestamp", ""),
            "label": row.get("label", ""),
            "confidence": "",
            "moved": "",
            "text": row.get("email_text", ""),
        }

    return {
        "id": row.get("id") or _new_id(),
        "timestamp": row.get("timestamp", ""),
        "label": row.get("label", ""),
        "confidence": row.get("confidence", ""),
        "moved": row.get("moved", ""),
        "text": row.get("text", ""),
        # Absent on rows written before the phishing columns existed.
        "phishing_label": row.get("phishing_label", ""),
        "phishing_confidence": row.get("phishing_confidence", ""),
        "risk_level": row.get("risk_level", ""),
    }


def _read_raw(box):
    path = _path_for(box)
    if not os.path.exists(path):
        return [], False

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [_normalise(row) for row in reader]
        needs_upgrade = reader.fieldnames is not None and list(
            reader.fieldnames
        ) != FIELDS

    return rows, needs_upgrade


def _write_raw(box, rows):
    path = _path_for(box)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDS})


def _as_float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_public(row):
    """Shape a stored row for the API, with sensible types.

    Phishing fields are None when the message predates the phishing detector
    or when the detector was unavailable at the time. `phishing_available`
    makes that explicit so the UI never has to guess, and never infers a
    phishing verdict from the spam label.
    """
    phishing_label = (row.get("phishing_label") or "").strip().upper()

    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "label": row["label"],
        "confidence": _as_float(row.get("confidence")),
        "moved": bool(row.get("moved")),
        "text": row["text"],

        "phishing_available": phishing_label in (PHISHING, LEGITIMATE),
        "phishing_label": phishing_label or None,
        "phishing_confidence": _as_float(row.get("phishing_confidence")),
        "risk_level": (row.get("risk_level") or "").strip().upper() or None,
    }


def _load(box):
    """Read a mailbox, rewriting the file once if it used the legacy schema."""
    rows, needs_upgrade = _read_raw(box)
    if needs_upgrade and rows:
        _write_raw(box, rows)
    return rows


def add_message(box, text, label, confidence=None, moved=False,
                phishing_label=None, phishing_confidence=None, risk_level=None):
    """File a message into a mailbox and return the stored record.

    The phishing arguments are optional and default to None, so every existing
    caller (including src/quarantine/store.quarantine_email) keeps working
    unchanged and simply stores no phishing data.
    """
    record = {
        "id": _new_id(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "confidence": "" if confidence is None else f"{float(confidence):.4f}",
        "moved": "yes" if moved else "",
        "text": text,
        "phishing_label": (phishing_label or "").upper(),
        "phishing_confidence": (
            "" if phishing_confidence is None else f"{float(phishing_confidence):.4f}"
        ),
        "risk_level": (risk_level or "").upper(),
    }

    with _lock:
        rows = _load(box)
        rows.append(record)
        _write_raw(box, rows)

    return _to_public(record)


def list_messages(box, limit=None):
    """Return a mailbox newest-first."""
    with _lock:
        rows = _load(box)

    messages = [_to_public(row) for row in reversed(rows)]
    return messages[:limit] if limit else messages


def move_message(message_id, source, target):
    """Move one message between mailboxes, re-labelling it to match.

    Returns the moved record, or None if the id was not in the source box.
    """
    if source == target:
        raise ValueError("Source and target mailboxes must differ.")

    _path_for(source)
    _path_for(target)

    with _lock:
        source_rows = _load(source)

        index = next(
            (i for i, row in enumerate(source_rows) if row["id"] == message_id),
            None,
        )
        if index is None:
            return None

        record = source_rows.pop(index)
        record["label"] = "spam" if target == QUARANTINE else "ham"
        record["moved"] = "yes"

        target_rows = _load(target)
        target_rows.append(record)

        _write_raw(source, source_rows)
        _write_raw(target, target_rows)

    return _to_public(record)


def get_stats():
    """Counts driving the Overview section.

    Spam and phishing are counted INDEPENDENTLY, from their own stored labels.
    Neither is inferred from the other, and neither is inferred from which
    mailbox a message sits in - a message can be HAM and PHISHING at once, and
    quarantine now holds anything needing review, not just spam.
    """
    with _lock:
        quarantine_rows = _load(QUARANTINE)
        inbox_rows = _load(INBOX)

    all_rows = quarantine_rows + inbox_rows
    total = len(all_rows)

    # Counted from the label, not from the mailbox. For data written before
    # quarantine held anything but spam these give identical results.
    spam_count = sum(1 for row in all_rows if row.get("label") == "spam")
    ham_count = sum(1 for row in all_rows if row.get("label") == "ham")

    # Only rows that actually carry a phishing verdict are counted. Legacy
    # rows are reported separately rather than being silently bucketed.
    phishing_count = sum(
        1 for row in all_rows
        if (row.get("phishing_label") or "").upper() == PHISHING
    )
    legitimate_count = sum(
        1 for row in all_rows
        if (row.get("phishing_label") or "").upper() == LEGITIMATE
    )
    phishing_analysed = phishing_count + legitimate_count
    phishing_unknown = total - phishing_analysed

    risk_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for row in all_rows:
        level = (row.get("risk_level") or "").upper()
        if level in risk_counts:
            risk_counts[level] += 1

    return {
        # -- existing keys, unchanged --
        "spam_count": spam_count,
        "ham_count": ham_count,
        "total": total,
        "spam_rate": round(spam_count / total, 4) if total else 0.0,
        "ham_rate": round(ham_count / total, 4) if total else 0.0,
        "moved_count": sum(1 for row in all_rows if row.get("moved")),

        # -- added: phishing, as an independent dimension --
        "phishing_count": phishing_count,
        "legitimate_count": legitimate_count,
        "phishing_analysed": phishing_analysed,
        "phishing_unknown": phishing_unknown,
        "phishing_rate": (
            round(phishing_count / phishing_analysed, 4) if phishing_analysed else 0.0
        ),
        "legitimate_rate": (
            round(legitimate_count / phishing_analysed, 4) if phishing_analysed else 0.0
        ),

        # -- added: rule-based risk distribution --
        "risk_counts": risk_counts,
        "high_risk_count": risk_counts["HIGH"],
        "last_analysed": max(
            (row["timestamp"] for row in quarantine_rows + inbox_rows if row["timestamp"]),
            default=None,
        ),
    }
