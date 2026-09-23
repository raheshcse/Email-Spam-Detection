# Unified AI Email Threat Detection API
#
# One FastAPI service that runs BOTH detectors over a single email:
#
#     Spam/Ham      CountVectorizer + Multinomial Naive Bayes  (existing)
#     Phishing      fine-tuned bert-base-uncased               (new)
#
# and then applies a deterministic, rule-based security assessment on top.
#
# BACKWARD COMPATIBILITY
# ----------------------
# POST /predict was previously spam-only and the React frontend reads its flat
# fields (label, confidence, top_signals, probabilities, ...). Those fields are
# all still present and unchanged. The three new blocks - spam_detection,
# phishing_detection, security_assessment - were ADDED alongside them, so no
# existing client breaks. /stats, /messages and /messages/{id}/move are
# untouched.
#
# Neither model is retrained or modified here. Both are loaded once at startup.

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.schemas import (MAX_INPUT_CHARS, EmailPredictionRequest,
                             EmailThreatResponse, HealthResponse)
from src.services.email_threat_service import (EmailThreatServiceError,
                                               email_threat_service)
from src.storage import message_store
from src.storage.message_store import INBOX, QUARANTINE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("email_threat_api")

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if o.strip()
]

# Reported evaluation numbers. Spam figures come from src/models/evaluate.py;
# phishing figures are read from the saved model at startup.
MODEL_METRICS = {
    "spam": {
        "test_accuracy": 0.98,
        "spam_precision": 0.96,
        "spam_recall": 0.90,
        "algorithm": "Multinomial Naive Bayes",
        "features": "CountVectorizer, 5000 features, unigrams + bigrams",
    },
    "phishing": {},
}


# --------------------------------------------------------------------------
# Startup: load both models once
# --------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load both models before the first request is served.

    Models are loaded here, not per request. A detector that fails to load is
    logged and reported through /health; the service still starts so the other
    detector remains usable.
    """
    logger.info("=" * 62)
    logger.info("AI Email Threat Detection API - starting up")
    logger.info("=" * 62)

    results = email_threat_service.load_all()

    for name, outcome in results.items():
        if outcome["loaded"]:
            logger.info("  %-9s model: LOADED", name)
        else:
            logger.error("  %-9s model: FAILED - %s", name, outcome["error"])

    phishing_info = email_threat_service.phishing.info()
    if phishing_info["loaded"]:
        logger.info("  phishing device: %s", phishing_info["device"])
        MODEL_METRICS["phishing"] = phishing_info.get("test_metrics") or {}

    if email_threat_service.is_ready:
        logger.info("API ready. Docs at /docs")
    else:
        logger.error("NO detectors loaded. /predict will return 503.")
    logger.info("=" * 62)

    yield

    logger.info("Shutting down.")


app = FastAPI(
    title="AI Email Threat Detection Agent API",
    description=(
        "Runs two independent detectors over one email:\n\n"
        "* **Spam/Ham** - CountVectorizer + Multinomial Naive Bayes\n"
        "* **Phishing** - fine-tuned bert-base-uncased\n\n"
        "and combines them with a deterministic, rule-based risk assessment. "
        "The risk level is **not** a machine-learning output."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Error handling - never leak a stack trace to the client
# --------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log the real error, return a generic message."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check the server logs."},
    )


# --------------------------------------------------------------------------
# Legacy schemas (kept for the existing mailbox endpoints)
# --------------------------------------------------------------------------


class Email(BaseModel):
    text: str = Field(..., description="Raw email or message body to classify.")


class MoveRequest(BaseModel):
    to: str = Field(..., description="Destination mailbox: 'inbox' or 'quarantine'.")


# --------------------------------------------------------------------------
# Presentation helpers (unchanged behaviour)
# --------------------------------------------------------------------------


def _confidence_band(confidence):
    if confidence >= 0.90:
        return "high"
    if confidence >= 0.70:
        return "medium"
    return "low"


def _build_explanation(label, confidence, signals, known_words, cleaned_words):
    """Plain-English reason the user can actually read."""
    band = _confidence_band(confidence)
    pct = f"{confidence * 100:.1f}%"

    if known_words == 0:
        return (
            "None of the words in this message appear in the model's vocabulary, "
            "so the result falls back to the overall balance of the training data. "
            "Treat this prediction as unreliable and try a longer message."
        )

    terms = ", ".join(f'"{s["term"]}"' for s in signals[:3])

    if label == "spam":
        base = (
            f"This message looks like spam ({pct} confidence). "
            "Its wording closely matches the promotional and scam-style emails "
            "in the training data"
        )
        base += f", especially terms like {terms}." if terms else "."
        if band == "low":
            base += (
                " The margin is narrow though, so a human should confirm before "
                "acting on it."
            )
        else:
            base += " It has been added to the quarantine log."
    else:
        base = (
            f"This message looks legitimate ({pct} confidence). "
            "Its vocabulary matches normal, personal or transactional messages"
        )
        base += f", with everyday terms like {terms}." if terms else "."
        if band == "low":
            base += " Confidence is on the low side, so give it a quick manual glance."

    if cleaned_words < 3:
        base += (
            " Note that very little text survived cleaning, which makes any "
            "prediction shaky."
        )

    return base


def _validate_text(raw):
    """Shared input validation. Returns the trimmed text or raises."""
    text = (raw or "").strip()

    if not text:
        raise HTTPException(
            status_code=422,
            detail="Email text is empty. Paste a message before analysing.",
        )

    if len(text) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message is too long. Limit is {MAX_INPUT_CHARS} characters.",
        )

    return text


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "AI Email Threat Detection Agent API",
        "version": "2.0.0",
        "status": "ok",
        "detectors": ["spam/ham (Naive Bayes)", "phishing (BERT)"],
        "endpoints": [
            "/health", "/predict", "/metrics", "/stats", "/messages", "/docs",
        ],
    }


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health():
    """Liveness probe reporting the load state of both models."""
    info = email_threat_service.info()

    spam_loaded = info["spam"]["loaded"]
    phishing_loaded = info["phishing"]["loaded"]

    if spam_loaded and phishing_loaded:
        status = "healthy"
    elif spam_loaded or phishing_loaded:
        status = "degraded"
    else:
        status = "unhealthy"

    return {
        "status": status,
        "spam_model": "loaded" if spam_loaded else "not loaded",
        "phishing_model": "loaded" if phishing_loaded else "not loaded",
        "detectors": info,
        # Legacy keys the existing frontend reads.
        "model_loaded": spam_loaded,
        "vectorizer_loaded": spam_loaded,
        "classes": info["spam"].get("classes", []),
        "vocabulary_size": info["spam"].get("vocabulary_size", 0),
        "cleaner": info["spam"].get("cleaner"),
    }


@app.get("/metrics", tags=["meta"])
def metrics():
    """Reported evaluation numbers for both models."""
    spam = dict(MODEL_METRICS["spam"])
    # The existing frontend reads these at the top level.
    spam["phishing"] = MODEL_METRICS["phishing"]
    return spam


@app.post(
    "/predict",
    response_model=EmailThreatResponse,
    response_model_exclude_none=True,
    tags=["detection"],
    summary="Analyse one email with both detectors",
    responses={
        422: {"description": "Empty or invalid input"},
        413: {"description": "Input too long"},
        503: {"description": "No detector is available"},
    },
)
def predict(request: EmailPredictionRequest):
    """Run the spam/ham model and the phishing model over one email.

    Returns both ML predictions plus a rule-based risk level. The flat
    spam-only fields from the previous API version are still included.
    """
    raw = _validate_text(request.text)

    try:
        combined = email_threat_service.analyse(
            raw, phishing_threshold=request.phishing_threshold
        )
    except EmailThreatServiceError as error:
        raise HTTPException(status_code=503, detail=str(error))

    response = {
        "spam_detection": combined["spam_detection"],
        "phishing_detection": combined["phishing_detection"],
        "security_assessment": combined["security_assessment"],
    }

    # ---- legacy spam-only fields, byte-for-byte as before ----
    spam = combined["_spam_raw"]
    phishing = combined["_phishing_raw"]
    assessment = combined["security_assessment"]

    if spam is not None:
        label = spam["prediction"]
        confidence = spam["confidence"]

        # Routing: anything either detector flags goes to quarantine, which is
        # now "messages requiring security review" rather than "spam".
        #
        # Previously only spam was quarantined, which meant a HAM + PHISHING
        # email was delivered straight to the inbox - the wrong outcome for a
        # security tool, and inconsistent with the backend's own
        # recommended_action ("Quarantine and do not click any links").
        needs_review = spam["is_spam"] or bool(phishing and phishing["is_phishing"])
        box = QUARANTINE if needs_review else INBOX

        stored = message_store.add_message(
            box, raw, label,
            confidence=confidence,
            # Stored so Overview and Quarantine can show phishing as its own
            # dimension instead of inferring it from the spam label.
            phishing_label=phishing["prediction"] if phishing else None,
            phishing_confidence=(
                phishing["phishing_probability"] if phishing else None
            ),
            risk_level=assessment["risk_level"],
        )

        response.update({
            "id": stored["id"],
            "box": box,
            "label": label,
            "prediction": label,
            "is_spam": spam["is_spam"],
            "confidence": round(confidence, 4),
            "confidence_percent": round(confidence * 100, 2),
            "confidence_band": _confidence_band(confidence),
            "probabilities": {k: round(v, 4) for k, v in spam["probabilities"].items()},
            "explanation": _build_explanation(
                label, confidence, spam["top_signals"],
                spam["recognised_features"], spam["cleaned_words"],
            ),
            "top_signals": spam["top_signals"],
            "cleaned_text": spam["cleaned_text"],
            "stats": {
                "characters": len(raw),
                "words": len(raw.split()),
                "cleaned_words": spam["cleaned_words"],
                "recognised_features": spam["recognised_features"],
            },
            # True when the message was filed into quarantine, which is now
            # driven by either detector rather than by spam alone.
            "quarantined": box == QUARANTINE,
        })

    return response


@app.get("/stats", tags=["mailbox"])
def stats():
    """Totals for the Overview section: spam vs ham across both mailboxes."""
    return message_store.get_stats()


@app.get("/messages", tags=["mailbox"])
def messages(box: str, limit: int = 200):
    """List one mailbox, newest first: `quarantine` or `inbox`."""
    try:
        items = message_store.list_messages(box, limit=limit)
    except message_store.UnknownBox as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"box": box, "count": len(items), "messages": items}


@app.post("/messages/{message_id}/move", tags=["mailbox"])
def move_message(message_id: str, request: MoveRequest):
    """Move a message to the other mailbox and relabel it."""
    target = request.to

    if target not in (INBOX, QUARANTINE):
        raise HTTPException(
            status_code=422, detail="Destination must be 'inbox' or 'quarantine'."
        )

    source = QUARANTINE if target == INBOX else INBOX
    moved = message_store.move_message(message_id, source, target)

    if moved is None:
        raise HTTPException(
            status_code=404,
            detail=f"No message with id '{message_id}' in the {source}.",
        )

    return {"moved": moved, "from": source, "to": target}
