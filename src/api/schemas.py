"""Pydantic request and response models.

These drive both validation and the Swagger documentation at /docs.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

MAX_INPUT_CHARS = 20000

# Pydantic v2 reserves the "model_" prefix for its own attributes and warns on
# any field that uses it. Several fields here are legitimately called `model`
# or `model_loaded` (the latter is part of the existing frontend contract), so
# the protection is switched off on those models rather than renaming fields
# and breaking clients.
ALLOW_MODEL_PREFIX = {"protected_namespaces": ()}


class EmailPredictionRequest(BaseModel):
    """An email to analyse."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_INPUT_CHARS,
        description="Raw email or message body. Subject and body may be "
                    "concatenated. Must not be empty.",
    )
    phishing_threshold: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional override for the phishing decision threshold. "
                    "Defaults to 0.5. Lower it to catch more phishing at the "
                    "cost of more false positives.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "text": "Your bank account has been suspended. Click here "
                        "immediately to verify your identity."
            }
        }
    }


class SpamDetectionResult(BaseModel):
    """Output of the Naive Bayes spam detector. This IS a model prediction."""

    available: bool = Field(..., description="False if the model failed to load.")
    prediction: Optional[str] = Field(
        None, description="SPAM or HAM (uppercase in this block)."
    )
    probability: Optional[float] = Field(
        None, description="Model probability that the email is spam."
    )
    confidence: Optional[float] = Field(
        None, description="Probability assigned to the predicted class."
    )
    model: str = Field(..., description="Which model produced this.")
    error: Optional[str] = None

    model_config = ALLOW_MODEL_PREFIX


class PhishingDetectionResult(BaseModel):
    """Output of the fine-tuned BERT detector. This IS a model prediction."""

    available: bool = Field(..., description="False if the model failed to load.")
    prediction: Optional[str] = Field(
        None, description="PHISHING or LEGITIMATE."
    )
    probability: Optional[float] = Field(
        None, description="Model probability that the email is phishing."
    )
    confidence: Optional[float] = Field(
        None, description="Probability assigned to the predicted class."
    )
    model: str = Field(..., description="Which model produced this.")
    truncated: Optional[bool] = Field(
        None, description="True if the email exceeded 512 tokens and was "
                          "head-truncated before classification."
    )
    error: Optional[str] = None

    model_config = ALLOW_MODEL_PREFIX


class SecurityAssessment(BaseModel):
    """Rule-based risk level.

    NOT a machine-learning output. A deterministic lookup over the two
    detector verdicts, so it carries no probability and no accuracy figure.
    """

    risk_level: str = Field(..., description="LOW, MEDIUM or HIGH.")
    reason: str = Field(..., description="Why this level was chosen.")
    recommended_action: str
    method: str = Field(..., description="Always 'rule-based'.")
    is_ml_prediction: bool = Field(
        ..., description="Always false. Present so clients cannot mistake this "
                         "for a model score."
    )
    triggered_by: Dict[str, bool]
    degraded: Optional[bool] = Field(
        None, description="True if one detector was unavailable, so the "
                          "assessment is based on partial information."
    )


class EmailThreatResponse(BaseModel):
    """Combined result of both detectors plus the rule-based assessment.

    The flat fields after `security_assessment` are the original spam-only
    response, kept so existing clients continue to work unchanged.
    """

    spam_detection: SpamDetectionResult
    phishing_detection: PhishingDetectionResult
    security_assessment: SecurityAssessment

    # -- legacy spam-only fields, retained for backward compatibility --
    id: Optional[str] = None
    box: Optional[str] = None
    label: Optional[str] = Field(None, description="Legacy: 'spam' or 'ham'.")
    prediction: Optional[str] = Field(None, description="Legacy: 'spam' or 'ham'.")
    is_spam: Optional[bool] = None
    confidence: Optional[float] = None
    confidence_percent: Optional[float] = None
    confidence_band: Optional[str] = None
    probabilities: Optional[Dict[str, float]] = None
    explanation: Optional[str] = None
    top_signals: Optional[List[Dict[str, Any]]] = None
    cleaned_text: Optional[str] = None
    stats: Optional[Dict[str, int]] = None
    quarantined: Optional[bool] = None


class DetectorHealth(BaseModel):
    loaded: bool
    algorithm: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Service and model status.

    The fields below `detectors` are the original spam-only health payload,
    kept because the existing frontend reads them. FastAPI strips anything not
    declared on the response model, so they have to be declared here.
    """

    status: str = Field(..., description="healthy, degraded or unhealthy.")
    spam_model: str = Field(..., description="loaded or not loaded.")
    phishing_model: str = Field(..., description="loaded or not loaded.")
    detectors: Dict[str, Any]

    # -- legacy fields, retained for backward compatibility --
    model_loaded: Optional[bool] = None
    vectorizer_loaded: Optional[bool] = None
    classes: Optional[List[str]] = None
    vocabulary_size: Optional[int] = None
    cleaner: Optional[Dict[str, Any]] = None

    model_config = ALLOW_MODEL_PREFIX


class ErrorResponse(BaseModel):
    """What every 4xx and 5xx returns. No stack traces are ever included."""

    detail: str
