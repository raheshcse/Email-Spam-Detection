"""Spam/Ham detector service - CountVectorizer + Multinomial Naive Bayes.

Wraps the EXISTING trained artefacts:
    models/spam_model.pkl
    models/count_vectorizer.pkl

Nothing is retrained and no model file is written. The prediction path is
identical to the one the API has always used:

    raw text -> clean_text() -> vectorizer.transform() -> model.predict()

The model and vectorizer are loaded once and held on the instance, so requests
do not pay the joblib load cost.
"""

import os
import threading

import joblib
import numpy as np

from src.api.text_cleaning import clean_text, get_cleaner_info

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "spam_model.pkl")
DEFAULT_VECTORIZER_PATH = os.path.join(PROJECT_ROOT, "models", "count_vectorizer.pkl")


class SpamDetectorError(RuntimeError):
    """Raised when the detector cannot load or cannot predict."""


class SpamDetector:
    """Loads the Naive Bayes spam model once and serves predictions from it."""

    def __init__(self, model_path=DEFAULT_MODEL_PATH,
                 vectorizer_path=DEFAULT_VECTORIZER_PATH):
        self.model_path = model_path
        self.vectorizer_path = vectorizer_path

        self.model = None
        self.vectorizer = None
        self.classes = []
        self.feature_names = None
        self.token_spam_score = None

        self._lock = threading.Lock()
        self._load_error = None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_loaded(self):
        return self.model is not None and self.vectorizer is not None

    def load(self):
        """Load the artefacts. Idempotent and safe to call from startup."""
        with self._lock:
            if self.is_loaded:
                return True

            try:
                for path in (self.model_path, self.vectorizer_path):
                    if not os.path.exists(path):
                        raise FileNotFoundError(path)

                self.model = joblib.load(self.model_path)
                self.vectorizer = joblib.load(self.vectorizer_path)

                self.feature_names = np.asarray(self.vectorizer.get_feature_names_out())
                self.classes = [str(c) for c in self.model.classes_]

                # Per-token log-probability gap between the spam and ham classes.
                # Used to name the words that drove a prediction.
                if "spam" in self.classes and "ham" in self.classes:
                    spam_index = self.classes.index("spam")
                    ham_index = self.classes.index("ham")
                    self.token_spam_score = (
                        self.model.feature_log_prob_[spam_index]
                        - self.model.feature_log_prob_[ham_index]
                    )
                else:  # pragma: no cover - the shipped model is ham/spam
                    self.token_spam_score = np.zeros(len(self.feature_names))

                self._load_error = None
                return True

            except Exception as error:
                self.model = None
                self.vectorizer = None
                self._load_error = f"{type(error).__name__}: {error}"
                raise SpamDetectorError(
                    f"Could not load the spam model: {self._load_error}"
                ) from error

    def info(self):
        """Status for the /health endpoint."""
        return {
            "loaded": self.is_loaded,
            "algorithm": "Multinomial Naive Bayes",
            "features": "CountVectorizer",
            "classes": self.classes,
            "vocabulary_size": int(len(self.feature_names)) if self.is_loaded else 0,
            "model_path": os.path.relpath(self.model_path, PROJECT_ROOT),
            "cleaner": get_cleaner_info(),
            "error": self._load_error,
        }

    # -- prediction -------------------------------------------------------

    def top_signals(self, vector, label, limit=6):
        """Tokens in this message that argued hardest for the predicted label."""
        indices = vector.nonzero()[1]
        if indices.size == 0:
            return []

        scores = self.token_spam_score[indices]
        counts = np.asarray(vector.todense()).ravel()[indices]

        weights = scores * counts
        if label == "ham":
            weights = -weights

        signals = []
        for position in np.argsort(weights)[::-1][:limit]:
            weight = float(weights[position])
            if weight <= 0:
                continue
            signals.append({
                "term": str(self.feature_names[indices[position]]),
                "weight": round(weight, 3),
                "count": int(counts[position]),
            })
        return signals

    def predict(self, text):
        """Classify one message.

        Returns the raw building blocks; the API layer decides how to present
        them. `prediction` keeps the model's own lowercase 'spam'/'ham' values
        so existing callers are unaffected.
        """
        if not self.is_loaded:
            raise SpamDetectorError("Spam model is not loaded.")

        raw = str(text)
        cleaned = clean_text(raw)
        vector = self.vectorizer.transform([cleaned])

        label = str(self.model.predict(vector)[0])
        proba = self.model.predict_proba(vector)[0]
        probabilities = {cls: float(p) for cls, p in zip(self.classes, proba)}
        confidence = float(probabilities.get(label, max(proba)))

        return {
            "prediction": label,                      # 'spam' or 'ham'
            "is_spam": label == "spam",
            "confidence": confidence,
            "spam_probability": float(probabilities.get("spam", 0.0)),
            "ham_probability": float(probabilities.get("ham", 0.0)),
            "probabilities": probabilities,
            "top_signals": self.top_signals(vector, label),
            "cleaned_text": cleaned,
            "recognised_features": int(vector.nnz),
            "cleaned_words": len(cleaned.split()),
        }


# Module-level singleton. Import this rather than constructing your own, so the
# model is loaded once per process.
spam_detector = SpamDetector()
