"""Shared pytest fixtures for the backend tests.

Two test modes:

  Fast (default)   Both detectors are replaced with fakes. Runs in seconds,
                   needs no model files, and exercises the API contract,
                   validation and the risk rules.

  Real models      Set PHISHING_TEST_REAL_MODELS=1 to load the actual BERT and
                   Naive Bayes models. Slower, and requires both models to be
                   present on disk.

Nothing here touches the training data. The example emails are short, hand
written strings.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

USE_REAL_MODELS = os.getenv("PHISHING_TEST_REAL_MODELS") == "1"


# --------------------------------------------------------------------------
# Fakes - deterministic stand-ins with the same interface as the real ones
# --------------------------------------------------------------------------

SPAM_WORDS = {"winner", "prize", "congratulations", "free", "claim", "won"}
PHISH_WORDS = {"suspended", "verify", "bank", "click", "password", "account"}


class FakeSpamDetector:
    """Keyword stub with the same interface as SpamDetector."""

    is_loaded = True

    def load(self):
        return True

    def info(self):
        return {
            "loaded": True, "algorithm": "fake", "classes": ["ham", "spam"],
            "vocabulary_size": 2, "cleaner": {"mode": "fake"}, "error": None,
        }

    def predict(self, text):
        words = set(str(text).lower().split())
        is_spam = bool(words & SPAM_WORDS)
        probability = 0.95 if is_spam else 0.05
        label = "spam" if is_spam else "ham"

        return {
            "prediction": label,
            "is_spam": is_spam,
            "confidence": probability if is_spam else 1 - probability,
            "spam_probability": probability,
            "ham_probability": 1 - probability,
            "probabilities": {"ham": 1 - probability, "spam": probability},
            "top_signals": [{"term": "fake", "weight": 1.0, "count": 1}],
            "cleaned_text": str(text).lower(),
            "recognised_features": len(words),
            "cleaned_words": len(words),
        }


class FakePhishingDetector:
    """Keyword stub with the same interface as PhishingDetector."""

    is_loaded = True
    threshold = 0.5

    def load(self):
        return True

    def info(self):
        return {
            "loaded": True, "algorithm": "fake", "labels": {0: "LEGITIMATE", 1: "PHISHING"},
            "max_length": 512, "threshold": 0.5, "device": "cpu", "error": None,
        }

    def predict(self, text, threshold=None):
        threshold = self.threshold if threshold is None else threshold
        words = set(str(text).lower().replace(".", " ").replace(",", " ").split())
        probability = 0.99 if words & PHISH_WORDS else 0.01
        is_phishing = probability >= threshold

        return {
            "prediction": "PHISHING" if is_phishing else "LEGITIMATE",
            "label_id": 1 if is_phishing else 0,
            "is_phishing": is_phishing,
            "phishing_probability": probability,
            "legitimate_probability": 1 - probability,
            "confidence": max(probability, 1 - probability),
            "threshold_used": threshold,
            "tokens": len(words),
            "truncated": False,
        }


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    """A TestClient with the detectors wired up and the mailbox redirected.

    The message store is pointed at a temporary directory so that running the
    tests never writes into the real data/quarantine or data/inbox files.
    """
    from fastapi.testclient import TestClient

    from src.services import email_threat_service as service_module
    from src.storage import message_store

    # Redirect the mailbox CSVs away from the real data directory.
    temp_dir = tmp_path_factory.mktemp("mailbox")
    message_store.QUARANTINE_FILE = str(temp_dir / "quarantine.csv")
    message_store.INBOX_FILE = str(temp_dir / "inbox.csv")
    message_store.BOXES = {
        message_store.QUARANTINE: message_store.QUARANTINE_FILE,
        message_store.INBOX: message_store.INBOX_FILE,
    }

    if not USE_REAL_MODELS:
        service_module.email_threat_service.spam = FakeSpamDetector()
        service_module.email_threat_service.phishing = FakePhishingDetector()

    from src.api.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ham_email():
    return "Hi John, just confirming our meeting tomorrow at 10 AM."


@pytest.fixture
def phishing_email():
    return ("Your bank account has been suspended. Click here immediately to "
            "verify your identity.")


@pytest.fixture
def spam_email():
    return "Congratulations! You have won a prize. Reply to claim your free gift."
