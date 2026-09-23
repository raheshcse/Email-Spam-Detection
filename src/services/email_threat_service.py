"""Unified email threat service.

Runs both detectors over one email and combines their output:

        EMAIL
          |
    +-----+-----+
    |           |
 Spam/Ham    Phishing BERT
    |           |
    +-----+-----+
          |
   Combined result + rule-based risk level

TWO DIFFERENT KINDS OF OUTPUT LIVE HERE - DO NOT CONFLATE THEM
--------------------------------------------------------------
1. ML predictions
   `spam_detection` and `phishing_detection` come from trained models. Each
   carries a probability produced by that model.

2. Rule-based security assessment
   `security_assessment.risk_level` is NOT a model output. It is a fixed
   lookup over the two boolean predictions, defined in RISK_RULES below.
   It has no probability, no training data and no accuracy figure. It exists
   to turn two independent verdicts into one actionable label.
"""

from src.models.phishing_detector import PhishingDetectorError, phishing_detector
from src.models.spam_detector import SpamDetectorError, spam_detector

# --------------------------------------------------------------------------
# Rule-based security assessment  (NOT machine learning)
# --------------------------------------------------------------------------

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")

# Keyed by (is_spam, is_phishing). Edit this table to change the policy;
# nothing else needs to change.
RISK_RULES = {
    (False, False): {
        "risk_level": "LOW",
        "reason": "Neither detector flagged this email.",
        "recommended_action": "Deliver normally.",
    },
    (True, False): {
        "risk_level": "MEDIUM",
        "reason": "Flagged as spam but not as phishing. Likely unwanted bulk "
                  "mail rather than an attack.",
        "recommended_action": "Move to the junk folder. No credential risk identified.",
    },
    (False, True): {
        "risk_level": "HIGH",
        "reason": "Flagged as phishing. The email resembles a credential-harvesting "
                  "or fraud attempt.",
        "recommended_action": "Quarantine and do not click any links.",
    },
    (True, True): {
        "risk_level": "HIGH",
        "reason": "Flagged as both spam and phishing. Both detectors agree this "
                  "is hostile.",
        "recommended_action": "Quarantine and do not click any links.",
    },
}


def assess_risk(is_spam, is_phishing):
    """Deterministic rule lookup. No model, no probability, no randomness.

    The same two inputs always produce the same output.
    """
    rule = RISK_RULES[(bool(is_spam), bool(is_phishing))]

    return {
        "risk_level": rule["risk_level"],
        "reason": rule["reason"],
        "recommended_action": rule["recommended_action"],
        "method": "rule-based",
        "is_ml_prediction": False,
        "triggered_by": {
            "spam_detected": bool(is_spam),
            "phishing_detected": bool(is_phishing),
        },
    }


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------


class EmailThreatServiceError(RuntimeError):
    """Raised when neither detector could produce a result."""


class EmailThreatService:
    """Coordinates the two detectors. Holds no model state of its own."""

    def __init__(self, spam=None, phishing=None):
        self.spam = spam or spam_detector
        self.phishing = phishing or phishing_detector

    # -- lifecycle --------------------------------------------------------

    def load_all(self):
        """Load both models, reporting each independently.

        One detector failing does not prevent the other from serving. The API
        surfaces the failure through /health rather than refusing to start,
        because a spam-only service is still useful.
        """
        results = {}

        for name, detector in (("spam", self.spam), ("phishing", self.phishing)):
            try:
                detector.load()
                results[name] = {"loaded": True, "error": None}
            except (SpamDetectorError, PhishingDetectorError) as error:
                results[name] = {"loaded": False, "error": str(error)}
            except Exception as error:  # pragma: no cover - defensive
                results[name] = {
                    "loaded": False,
                    "error": f"{type(error).__name__}: {error}",
                }

        return results

    @property
    def is_ready(self):
        """True when at least one detector can serve."""
        return self.spam.is_loaded or self.phishing.is_loaded

    def info(self):
        return {"spam": self.spam.info(), "phishing": self.phishing.info()}

    # -- analysis ---------------------------------------------------------

    def analyse(self, text, phishing_threshold=None):
        """Run both detectors and combine the results.

        A detector that is unavailable yields `available: False` with an error
        message rather than taking the whole request down.
        """
        spam_result, spam_error = None, None
        phishing_result, phishing_error = None, None

        try:
            spam_result = self.spam.predict(text)
        except SpamDetectorError as error:
            spam_error = str(error)

        try:
            phishing_result = self.phishing.predict(
                text, threshold=phishing_threshold
            )
        except PhishingDetectorError as error:
            phishing_error = str(error)

        if spam_result is None and phishing_result is None:
            raise EmailThreatServiceError(
                f"Both detectors are unavailable. Spam: {spam_error}. "
                f"Phishing: {phishing_error}."
            )

        # Uppercase in the combined block so the two detectors read
        # consistently. The legacy lowercase values stay in the flat fields the
        # existing frontend already reads.
        spam_block = {
            "available": spam_result is not None,
            "prediction": spam_result["prediction"].upper() if spam_result else None,
            "probability": (
                round(spam_result["spam_probability"], 6) if spam_result else None
            ),
            "confidence": round(spam_result["confidence"], 6) if spam_result else None,
            "model": "Multinomial Naive Bayes + CountVectorizer",
            "error": spam_error,
        }

        phishing_block = {
            "available": phishing_result is not None,
            "prediction": phishing_result["prediction"] if phishing_result else None,
            "probability": (
                round(phishing_result["phishing_probability"], 6)
                if phishing_result else None
            ),
            "confidence": (
                round(phishing_result["confidence"], 6) if phishing_result else None
            ),
            "model": "Fine-tuned BERT (bert-base-uncased)",
            "truncated": phishing_result["truncated"] if phishing_result else None,
            "error": phishing_error,
        }

        # A detector that could not run counts as "did not flag", so the risk
        # rule still resolves. The degraded state is visible via `available`.
        assessment = assess_risk(
            is_spam=bool(spam_result and spam_result["is_spam"]),
            is_phishing=bool(phishing_result and phishing_result["is_phishing"]),
        )
        assessment["degraded"] = not (
            spam_block["available"] and phishing_block["available"]
        )

        return {
            "spam_detection": spam_block,
            "phishing_detection": phishing_block,
            "security_assessment": assessment,
            "_spam_raw": spam_result,
            "_phishing_raw": phishing_result,
        }


# Module-level singleton used by the API layer.
email_threat_service = EmailThreatService()
