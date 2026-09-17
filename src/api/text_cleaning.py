# Text cleaning adapter for the API layer.
#
# The API always prefers the exact same cleaner used to build the training
# data (src/data/preprocess.clean_text, spaCy-based). If the spaCy model
# "en_core_web_sm" is not installed on the machine running the API, importing
# preprocess raises OSError and the whole service would fail to boot. To keep
# the API usable in that situation we fall back to a lightweight cleaner that
# mirrors the regex + stop-word steps of the real pipeline (minus
# lemmatisation) and flag the degraded mode through get_cleaner_info().
#
# Nothing in src/data/preprocess.py is modified.

import re

_MODE = "spacy"
_REASON = None

try:
    from src.data.preprocess import clean_text as _spacy_clean_text
except Exception as exc:  # pragma: no cover - depends on local install
    _spacy_clean_text = None
    _MODE = "fallback"
    _REASON = str(exc)


# A compact English stop-word list, only used by the fallback cleaner.
_FALLBACK_STOP_WORDS = {
    "a", "about", "above", "after", "again", "all", "am", "an", "and", "any",
    "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "can", "did", "do", "does", "doing",
    "down", "during", "each", "few", "for", "from", "further", "had", "has",
    "have", "having", "he", "her", "here", "hers", "herself", "him",
    "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its",
    "itself", "just", "me", "more", "most", "my", "myself", "no", "nor",
    "not", "now", "of", "off", "on", "once", "only", "or", "other", "our",
    "ours", "ourselves", "out", "over", "own", "s", "same", "she", "should",
    "so", "some", "such", "t", "than", "that", "the", "their", "theirs",
    "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "until", "up", "very", "was", "we",
    "were", "what", "when", "where", "which", "while", "who", "whom", "why",
    "will", "with", "you", "your", "yours", "yourself", "yourselves",
}


def _fallback_clean_text(text):
    text = str(text).lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^a-zA-Z ]", "", text)
    words = [w for w in text.split() if w and w not in _FALLBACK_STOP_WORDS]
    return " ".join(words)


def clean_text(text):
    """Clean raw email text exactly like the training pipeline does."""
    if _spacy_clean_text is not None:
        return _spacy_clean_text(text)
    return _fallback_clean_text(text)


def get_cleaner_info():
    """Describe which cleaner is active, for /health and diagnostics."""
    return {
        "mode": _MODE,
        "description": (
            "spaCy en_core_web_sm - lowercase, URL strip, non-alpha strip, "
            "stop-word removal, lemmatisation"
            if _MODE == "spacy"
            else "Fallback cleaner - spaCy model unavailable, lemmatisation skipped"
        ),
        "warning": (
            None
            if _MODE == "spacy"
            else (
                "spaCy model 'en_core_web_sm' could not be loaded, so predictions "
                "use a reduced cleaner and may be less accurate. Install it with: "
                "python -m spacy download en_core_web_sm"
            )
        ),
        "error": _REASON,
    }
