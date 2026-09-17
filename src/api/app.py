# Lifecycle stage 9 — Serving API
#
# Wraps the trained MultinomialNB + CountVectorizer pipeline in a FastAPI
# service that the React dashboard (frontend/) talks to.
#
# The prediction path is unchanged from the original implementation:
#   raw text -> clean_text() -> vectorizer.transform() -> model.predict()
# The extra fields (confidence, explanation, top signals) are derived from the
# same model object, so the ML pipeline itself is untouched.

import os

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.api.text_cleaning import clean_text, get_cleaner_info
from src.storage import message_store
from src.storage.message_store import INBOX, QUARANTINE

# --------------------------------------------------------------------------
# Paths and configuration
# --------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "spam_model.pkl")
VECTORIZER_PATH = os.path.join(PROJECT_ROOT, "models", "count_vectorizer.pkl")

# Vite dev server defaults, plus the preview server port.
DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

# Override with e.g. ALLOWED_ORIGINS="https://my-app.example.com" if deployed.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")
    if o.strip()
]

# Reported model quality (see src/models/evaluate.py output).
MODEL_METRICS = {
    "test_accuracy": 0.98,
    "spam_precision": 0.96,
    "spam_recall": 0.90,
    "algorithm": "Multinomial Naive Bayes",
    "features": "CountVectorizer, 5000 features, unigrams + bigrams",
}

MAX_INPUT_CHARS = 20000

app = FastAPI(
    title="Email Spam Detection Agent API",
    description=(
        "Classifies an email or SMS message as spam or ham using a "
        "Multinomial Naive Bayes model trained on CountVectorizer features."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# Model loading
# --------------------------------------------------------------------------

model = joblib.load(MODEL_PATH)
vectorizer = joblib.load(VECTORIZER_PATH)

FEATURE_NAMES = np.asarray(vectorizer.get_feature_names_out())
CLASSES = [str(c) for c in model.classes_]

# Naive Bayes log-probability gap per token: how much more likely a token is
# under the spam class than under the ham class. Used to name the words that
# pushed a prediction one way, which is what the UI shows as "key signals".
if "spam" in CLASSES and "ham" in CLASSES:
    _spam_idx = CLASSES.index("spam")
    _ham_idx = CLASSES.index("ham")
    TOKEN_SPAM_SCORE = (
        model.feature_log_prob_[_spam_idx] - model.feature_log_prob_[_ham_idx]
    )
else:  # pragma: no cover - defensive, model is trained on ham/spam
    TOKEN_SPAM_SCORE = np.zeros(len(FEATURE_NAMES))


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class Email(BaseModel):
    text: str = Field(..., description="Raw email or message body to classify.")


class MoveRequest(BaseModel):
    to: str = Field(
        ...,
        description="Destination mailbox: 'inbox' or 'quarantine'.",
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _top_signals(vector, label, limit=6):
    """Return the tokens in this message that argued hardest for the label."""
    indices = vector.nonzero()[1]
    if indices.size == 0:
        return []

    scores = TOKEN_SPAM_SCORE[indices]
    counts = np.asarray(vector.todense()).ravel()[indices]

    # A token's pull is its per-occurrence score times how often it appears.
    weights = scores * counts
    if label == "ham":
        weights = -weights

    order = np.argsort(weights)[::-1]

    signals = []
    for pos in order[:limit]:
        weight = float(weights[pos])
        if weight <= 0:
            continue
        signals.append(
            {
                "term": str(FEATURE_NAMES[indices[pos]]),
                "weight": round(weight, 3),
                "count": int(counts[pos]),
            }
        )
    return signals


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
            base += (
                " Confidence is on the low side, so give it a quick manual glance."
            )

    if cleaned_words < 3:
        base += (
            " Note that very little text survived cleaning, which makes any "
            "prediction shaky."
        )

    return base


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/")
def root():
    return {
        "service": "Email Spam Detection Agent API",
        "status": "ok",
        "endpoints": [
            "/health",
            "/predict",
            "/metrics",
            "/stats",
            "/messages",
            "/docs",
        ],
    }


@app.get("/health")
def health():
    """Cheap liveness probe the frontend uses to detect a cold backend."""
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "vectorizer_loaded": vectorizer is not None,
        "classes": CLASSES,
        "vocabulary_size": int(len(FEATURE_NAMES)),
        "cleaner": get_cleaner_info(),
    }


@app.get("/metrics")
def metrics():
    """Reported evaluation numbers, used by the How It Works panel."""
    return MODEL_METRICS


@app.post("/predict")
def predict(email: Email):
    raw = (email.text or "").strip()

    if not raw:
        raise HTTPException(
            status_code=422,
            detail="Email text is empty. Paste a message before analysing.",
        )

    if len(raw) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message is too long. Limit is {MAX_INPUT_CHARS} characters.",
        )

    cleaned = clean_text(raw)
    X = vectorizer.transform([cleaned])

    label = str(model.predict(X)[0])

    proba = model.predict_proba(X)[0]
    probabilities = {cls: float(p) for cls, p in zip(CLASSES, proba)}
    confidence = float(probabilities.get(label, max(proba)))

    signals = _top_signals(X, label)
    known_words = int(X.nnz)
    cleaned_words = len(cleaned.split())

    # Every analysed message is filed: spam into quarantine, ham into the inbox.
    # Spam quarantining preserves the original behaviour.
    box = QUARANTINE if label == "spam" else INBOX
    stored = message_store.add_message(box, raw, label, confidence=confidence)
    quarantined = label == "spam"

    return {
        "id": stored["id"],
        "box": box,
        # "label" is kept for backwards compatibility with the original API.
        "label": label,
        "prediction": label,
        "is_spam": label == "spam",
        "confidence": round(confidence, 4),
        "confidence_percent": round(confidence * 100, 2),
        "confidence_band": _confidence_band(confidence),
        "probabilities": {k: round(v, 4) for k, v in probabilities.items()},
        "explanation": _build_explanation(
            label, confidence, signals, known_words, cleaned_words
        ),
        "top_signals": signals,
        "cleaned_text": cleaned,
        "stats": {
            "characters": len(raw),
            "words": len(raw.split()),
            "cleaned_words": cleaned_words,
            "recognised_features": known_words,
        },
        "quarantined": quarantined,
    }


@app.get("/stats")
def stats():
    """Totals for the Overview section: spam vs ham across both mailboxes."""
    return message_store.get_stats()


@app.get("/messages")
def messages(box: str, limit: int = 200):
    """List one mailbox, newest first.

    `box` is either `quarantine` (predicted spam) or `inbox` (predicted ham).
    """
    try:
        items = message_store.list_messages(box, limit=limit)
    except message_store.UnknownBox as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"box": box, "count": len(items), "messages": items}


@app.post("/messages/{message_id}/move")
def move_message(message_id: str, request: MoveRequest):
    """Move a message to the other mailbox and relabel it.

    Used to correct the model: restore a false positive from quarantine to the
    inbox, or flag a false negative in the inbox as spam.
    """
    target = request.to
    source = QUARANTINE if target == INBOX else INBOX

    if target not in (INBOX, QUARANTINE):
        raise HTTPException(
            status_code=422,
            detail="Destination must be 'inbox' or 'quarantine'.",
        )

    moved = message_store.move_message(message_id, source, target)

    if moved is None:
        raise HTTPException(
            status_code=404,
            detail=f"No message with id '{message_id}' in the {source}.",
        )

    return {"moved": moved, "from": source, "to": target}
