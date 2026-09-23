"""Backend API tests.

Covers the eight areas required for this phase:
  1. health endpoint          5. spam prediction
  2. valid prediction         6. phishing prediction
  3. empty email              7. combined response shape
  4. invalid request          8. risk assessment rules

Run from the project root:
    python -m pytest tests -v
"""

import pytest

from src.services.email_threat_service import RISK_RULES, assess_risk

# ==========================================================================
# 1. Health endpoint
# ==========================================================================


def test_health_returns_200(client):
    assert client.get("/health").status_code == 200


def test_health_reports_both_models(client):
    body = client.get("/health").json()

    assert body["status"] in {"healthy", "degraded", "unhealthy"}
    assert body["spam_model"] in {"loaded", "not loaded"}
    assert body["phishing_model"] in {"loaded", "not loaded"}
    assert "spam" in body["detectors"]
    assert "phishing" in body["detectors"]


def test_health_keeps_legacy_fields(client):
    """The existing frontend reads these; they must not disappear."""
    body = client.get("/health").json()

    for key in ("model_loaded", "vectorizer_loaded", "classes", "vocabulary_size"):
        assert key in body, f"legacy health field '{key}' was dropped"


def test_root_lists_endpoints(client):
    body = client.get("/").json()
    assert "/predict" in body["endpoints"]
    assert "/health" in body["endpoints"]


# ==========================================================================
# 2. Valid prediction request
# ==========================================================================


def test_predict_returns_200(client, ham_email):
    assert client.post("/predict", json={"text": ham_email}).status_code == 200


def test_predict_has_three_blocks(client, ham_email):
    body = client.post("/predict", json={"text": ham_email}).json()

    for block in ("spam_detection", "phishing_detection", "security_assessment"):
        assert block in body, f"missing block: {block}"


# ==========================================================================
# 3. Empty email
# ==========================================================================


@pytest.mark.parametrize("text", ["", "   ", "\n\t  \n"])
def test_empty_text_is_rejected(client, text):
    response = client.post("/predict", json={"text": text})

    # "" fails Pydantic's min_length (422); whitespace-only fails our own
    # check (also 422). Either way the client gets a clean error.
    assert response.status_code == 422
    assert "detail" in response.json()


def test_empty_error_has_no_stack_trace(client):
    body = client.post("/predict", json={"text": "   "}).json()
    rendered = str(body)

    assert "Traceback" not in rendered
    assert "File \"" not in rendered


# ==========================================================================
# 4. Invalid request
# ==========================================================================


def test_missing_text_field(client):
    assert client.post("/predict", json={}).status_code == 422


def test_wrong_type_for_text(client):
    assert client.post("/predict", json={"text": 12345}).status_code == 422


def test_malformed_json(client):
    response = client.post(
        "/predict",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_oversized_input_is_rejected(client):
    response = client.post("/predict", json={"text": "word " * 60_000})
    assert response.status_code in (413, 422)


def test_threshold_out_of_range(client, ham_email):
    response = client.post(
        "/predict", json={"text": ham_email, "phishing_threshold": 1.7}
    )
    assert response.status_code == 422


# ==========================================================================
# 5. Spam/Ham prediction
# ==========================================================================


def test_spam_block_shape(client, spam_email):
    spam = client.post("/predict", json={"text": spam_email}).json()["spam_detection"]

    assert spam["available"] is True
    assert spam["prediction"] in {"SPAM", "HAM"}
    assert 0.0 <= spam["probability"] <= 1.0


def test_legacy_spam_fields_present(client, ham_email):
    """The React app reads these flat fields. They must survive."""
    body = client.post("/predict", json={"text": ham_email}).json()

    for key in ("label", "prediction", "is_spam", "confidence",
                "probabilities", "top_signals", "explanation", "stats"):
        assert key in body, f"legacy field '{key}' was dropped"

    assert body["label"] in {"spam", "ham"}       # lowercase, as before


def test_ham_email_is_not_spam(client, ham_email):
    body = client.post("/predict", json={"text": ham_email}).json()
    assert body["spam_detection"]["prediction"] == "HAM"


# ==========================================================================
# 6. Phishing prediction
# ==========================================================================


def test_phishing_block_shape(client, phishing_email):
    block = client.post(
        "/predict", json={"text": phishing_email}
    ).json()["phishing_detection"]

    assert block["available"] is True
    assert block["prediction"] in {"PHISHING", "LEGITIMATE"}
    assert 0.0 <= block["probability"] <= 1.0


def test_phishing_email_flagged(client, phishing_email):
    body = client.post("/predict", json={"text": phishing_email}).json()
    assert body["phishing_detection"]["prediction"] == "PHISHING"


def test_benign_email_not_flagged(client, ham_email):
    body = client.post("/predict", json={"text": ham_email}).json()
    assert body["phishing_detection"]["prediction"] == "LEGITIMATE"


def test_threshold_override_changes_outcome(client, ham_email):
    """A threshold of 0 flags everything; it proves the override is wired."""
    body = client.post(
        "/predict", json={"text": ham_email, "phishing_threshold": 0.0}
    ).json()
    assert body["phishing_detection"]["prediction"] == "PHISHING"


# ==========================================================================
# 7. Combined response
# ==========================================================================


def test_combined_response_is_complete(client, phishing_email):
    body = client.post("/predict", json={"text": phishing_email}).json()

    assert body["spam_detection"]["model"]
    assert body["phishing_detection"]["model"]
    assert body["security_assessment"]["risk_level"] in {"LOW", "MEDIUM", "HIGH"}


def test_risk_is_clearly_not_ml(client, phishing_email):
    """The response must not let a client mistake the rule for a model score."""
    assessment = client.post(
        "/predict", json={"text": phishing_email}
    ).json()["security_assessment"]

    assert assessment["is_ml_prediction"] is False
    assert assessment["method"] == "rule-based"
    assert "probability" not in assessment


# ==========================================================================
# 8. Risk assessment rules  (pure functions, no HTTP)
# ==========================================================================


@pytest.mark.parametrize("is_spam,is_phishing,expected", [
    (False, False, "LOW"),
    (True,  False, "MEDIUM"),
    (False, True,  "HIGH"),
    (True,  True,  "HIGH"),
])
def test_risk_rule_table(is_spam, is_phishing, expected):
    assert assess_risk(is_spam, is_phishing)["risk_level"] == expected


def test_risk_rules_cover_every_combination():
    assert set(RISK_RULES) == {(False, False), (True, False),
                               (False, True), (True, True)}


def test_risk_is_deterministic():
    first = assess_risk(True, True)
    second = assess_risk(True, True)
    assert first == second


def test_phishing_always_outranks_spam_only():
    """Any phishing flag must produce a higher level than spam alone."""
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

    spam_only = order[assess_risk(True, False)["risk_level"]]
    phishing_only = order[assess_risk(False, True)["risk_level"]]

    assert phishing_only > spam_only


# ==========================================================================
# 9. Phishing persisted for Overview / Quarantine
# ==========================================================================


def test_stats_exposes_phishing_fields(client, phishing_email):
    client.post("/predict", json={"text": phishing_email})

    stats = client.get("/stats").json()

    for key in ("phishing_count", "legitimate_count", "phishing_analysed",
                "phishing_unknown", "phishing_rate", "high_risk_count",
                "risk_counts"):
        assert key in stats, f"missing phishing stat: {key}"


def test_stats_keeps_existing_fields(client, ham_email):
    client.post("/predict", json={"text": ham_email})

    stats = client.get("/stats").json()
    for key in ("spam_count", "ham_count", "total", "spam_rate",
                "ham_rate", "moved_count"):
        assert key in stats, f"existing stat '{key}' disappeared"


def test_stored_message_carries_phishing_verdict(client, phishing_email):
    client.post("/predict", json={"text": phishing_email})

    messages = client.get("/messages?box=quarantine").json()["messages"]
    assert len(messages) > 0

    latest = messages[0]
    assert latest["phishing_available"] is True
    assert latest["phishing_label"] in {"PHISHING", "LEGITIMATE"}
    assert latest["risk_level"] in {"LOW", "MEDIUM", "HIGH"}


def test_ham_phishing_email_is_quarantined(client):
    """A HAM + PHISHING email must reach the review queue, not the inbox.

    The fake spam detector only flags prize/winner wording, and the fake
    phishing detector only flags bank/verify wording, so this text is
    deliberately ham AND phishing.
    """
    body = client.post(
        "/predict",
        json={"text": "Please verify your bank account details at your convenience."},
    ).json()

    assert body["spam_detection"]["prediction"] == "HAM"
    assert body["phishing_detection"]["prediction"] == "PHISHING"
    assert body["box"] == "quarantine"
    assert body["quarantined"] is True

    quarantined = client.get("/messages?box=quarantine").json()["messages"]
    assert any(
        m["label"] == "ham" and m["phishing_label"] == "PHISHING"
        for m in quarantined
    ), "a ham+phishing message should be in quarantine"


def test_clean_email_still_goes_to_inbox(client, ham_email):
    body = client.post("/predict", json={"text": ham_email}).json()

    assert body["box"] == "inbox"
    assert body["quarantined"] is False


def test_spam_and_phishing_counted_independently(client):
    """Counts must not be derived from one another."""
    client.post("/predict", json={"text": "Congratulations you won a free prize"})
    client.post("/predict", json={"text": "verify your bank account password"})

    stats = client.get("/stats").json()

    # Neither count may simply mirror the other.
    assert stats["spam_count"] >= 1
    assert stats["phishing_count"] >= 1
    assert stats["total"] == stats["spam_count"] + stats["ham_count"]


def test_end_to_end_risk_levels(client, ham_email, spam_email, phishing_email):
    """The three worked examples from the spec."""
    cases = [
        (ham_email, "LOW"),
        (spam_email, "MEDIUM"),
        (phishing_email, "HIGH"),
    ]

    for text, expected in cases:
        body = client.post("/predict", json={"text": text}).json()
        actual = body["security_assessment"]["risk_level"]
        assert actual == expected, f"{text[:40]!r} -> {actual}, expected {expected}"
