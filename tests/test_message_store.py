"""Tests for the phishing fields added to the message store.

Focus areas:
  * phishing data is stored and read back
  * legacy rows without phishing columns still load
  * spam and phishing are counted independently, never inferred from each other
  * a HAM + PHISHING message is possible and counted correctly
"""

import csv
import os

import pytest

from src.storage import message_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a temp directory so real mailboxes are untouched."""
    quarantine = tmp_path / "quarantine.csv"
    inbox = tmp_path / "inbox.csv"

    monkeypatch.setattr(message_store, "QUARANTINE_FILE", str(quarantine))
    monkeypatch.setattr(message_store, "INBOX_FILE", str(inbox))
    monkeypatch.setattr(message_store, "BOXES", {
        message_store.QUARANTINE: str(quarantine),
        message_store.INBOX: str(inbox),
    })
    return message_store


# ==========================================================================
# Storing and reading phishing data
# ==========================================================================


def test_phishing_fields_round_trip(store):
    stored = store.add_message(
        store.QUARANTINE, "Verify your account now", "spam",
        confidence=0.97, phishing_label="PHISHING",
        phishing_confidence=0.9982, risk_level="HIGH",
    )

    assert stored["phishing_available"] is True
    assert stored["phishing_label"] == "PHISHING"
    assert stored["phishing_confidence"] == pytest.approx(0.9982, abs=1e-4)
    assert stored["risk_level"] == "HIGH"

    [read_back] = store.list_messages(store.QUARANTINE)
    assert read_back["phishing_label"] == "PHISHING"
    assert read_back["risk_level"] == "HIGH"


def test_message_without_phishing_is_marked_unavailable(store):
    """The existing call signature must keep working and store no verdict."""
    stored = store.add_message(store.INBOX, "Lunch at one?", "ham", confidence=0.9)

    assert stored["phishing_available"] is False
    assert stored["phishing_label"] is None
    assert stored["phishing_confidence"] is None
    assert stored["risk_level"] is None


def test_quarantine_email_wrapper_still_works(store):
    """src/quarantine/store.quarantine_email must not have broken."""
    from src.quarantine import store as quarantine_store

    record = quarantine_store.quarantine_email("You won a prize", "spam")
    assert record["label"] == "spam"
    assert record["phishing_available"] is False


# ==========================================================================
# Legacy rows
# ==========================================================================


def test_legacy_rows_without_phishing_columns_load(store, tmp_path):
    """A file written before the phishing columns existed must still read."""
    path = tmp_path / "quarantine.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["id", "timestamp", "label", "confidence", "moved", "text"]
        )
        writer.writeheader()
        writer.writerow({
            "id": "abc123", "timestamp": "2026-08-01T10:00:00", "label": "spam",
            "confidence": "0.9900", "moved": "", "text": "Old spam message",
        })

    messages = store.list_messages(store.QUARANTINE)

    assert len(messages) == 1
    assert messages[0]["label"] == "spam"
    assert messages[0]["confidence"] == pytest.approx(0.99)
    # The important part: no phishing verdict is invented for it.
    assert messages[0]["phishing_available"] is False
    assert messages[0]["phishing_label"] is None


def test_very_old_legacy_schema_still_loads(store, tmp_path):
    """The original timestamp/label/email_text layout."""
    path = tmp_path / "quarantine.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "label", "email_text"])
        writer.writeheader()
        writer.writerow({
            "timestamp": "2026-08-08T20:10:09", "label": "spam", "email_text": "You won!",
        })

    messages = store.list_messages(store.QUARANTINE)
    assert len(messages) == 1
    assert messages[0]["text"] == "You won!"
    assert messages[0]["phishing_available"] is False


# ==========================================================================
# Statistics: independent dimensions
# ==========================================================================


def test_ham_can_also_be_phishing(store):
    """The key semantic: HAM != LEGITIMATE."""
    stored = store.add_message(
        store.QUARANTINE, "Hi, please confirm your password here", "ham",
        confidence=0.8, phishing_label="PHISHING",
        phishing_confidence=0.99, risk_level="HIGH",
    )

    assert stored["label"] == "ham"
    assert stored["phishing_label"] == "PHISHING"

    stats = store.get_stats()
    assert stats["ham_count"] == 1
    assert stats["spam_count"] == 0
    assert stats["phishing_count"] == 1
    assert stats["legitimate_count"] == 0
    assert stats["high_risk_count"] == 1


def test_spam_can_be_legitimate(store):
    """And SPAM != PHISHING."""
    store.add_message(
        store.QUARANTINE, "50% off winter sale", "spam",
        confidence=0.95, phishing_label="LEGITIMATE",
        phishing_confidence=0.02, risk_level="MEDIUM",
    )

    stats = store.get_stats()
    assert stats["spam_count"] == 1
    assert stats["phishing_count"] == 0
    assert stats["legitimate_count"] == 1
    assert stats["risk_counts"]["MEDIUM"] == 1


def test_stats_count_all_four_combinations(store):
    combinations = [
        ("spam", "PHISHING", "HIGH"),
        ("spam", "LEGITIMATE", "MEDIUM"),
        ("ham", "PHISHING", "HIGH"),
        ("ham", "LEGITIMATE", "LOW"),
    ]
    for index, (label, phishing, risk) in enumerate(combinations):
        box = store.QUARANTINE if label == "spam" or phishing == "PHISHING" else store.INBOX
        store.add_message(box, f"message {index}", label, confidence=0.9,
                          phishing_label=phishing, phishing_confidence=0.5,
                          risk_level=risk)

    stats = store.get_stats()

    assert stats["total"] == 4
    assert stats["spam_count"] == 2
    assert stats["ham_count"] == 2
    assert stats["phishing_count"] == 2
    assert stats["legitimate_count"] == 2
    assert stats["high_risk_count"] == 2
    assert stats["phishing_analysed"] == 4
    assert stats["phishing_unknown"] == 0


def test_legacy_messages_excluded_from_phishing_counts(store):
    store.add_message(store.INBOX, "no phishing data", "ham", confidence=0.9)
    store.add_message(store.QUARANTINE, "analysed", "spam", confidence=0.9,
                      phishing_label="PHISHING", phishing_confidence=0.99,
                      risk_level="HIGH")

    stats = store.get_stats()

    assert stats["total"] == 2
    assert stats["phishing_analysed"] == 1
    assert stats["phishing_unknown"] == 1
    # The unanalysed message is NOT counted as legitimate.
    assert stats["legitimate_count"] == 0
    assert stats["phishing_rate"] == 1.0


def test_existing_stats_keys_still_present(store):
    """Backwards compatibility with anything already reading /stats."""
    store.add_message(store.QUARANTINE, "spam text", "spam", confidence=0.9)

    stats = store.get_stats()
    for key in ("spam_count", "ham_count", "total", "spam_rate",
                "ham_rate", "moved_count", "last_analysed"):
        assert key in stats, f"existing stats key '{key}' disappeared"


def test_empty_store_does_not_divide_by_zero(store):
    stats = store.get_stats()

    assert stats["total"] == 0
    assert stats["spam_rate"] == 0.0
    assert stats["phishing_rate"] == 0.0
    assert stats["phishing_analysed"] == 0


# ==========================================================================
# Moving preserves the phishing verdict
# ==========================================================================


def test_move_keeps_phishing_verdict(store):
    """Correcting the spam label must not erase what BERT concluded."""
    stored = store.add_message(
        store.QUARANTINE, "borderline message", "spam", confidence=0.6,
        phishing_label="PHISHING", phishing_confidence=0.97, risk_level="HIGH",
    )

    moved = store.move_message(stored["id"], store.QUARANTINE, store.INBOX)

    assert moved["label"] == "ham"           # spam verdict corrected
    assert moved["phishing_label"] == "PHISHING"   # phishing verdict intact
    assert moved["phishing_confidence"] == pytest.approx(0.97, abs=1e-4)
    assert moved["risk_level"] == "HIGH"
