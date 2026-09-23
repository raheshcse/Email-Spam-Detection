"""Phishing detector service - fine-tuned bert-base-uncased.

Wraps the EXISTING trained model at models/phishing_bert/. Nothing is
retrained and no weight file is written.

The model is loaded once, moved to the available device and put in eval mode.
Inference runs under torch.no_grad(), so no gradients are allocated.

Labels come from the saved config rather than being hard-coded:
    0 = LEGITIMATE
    1 = PHISHING
"""

import json
import os
import threading

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "phishing_bert")

DEFAULT_MAX_LENGTH = 512
# Phishing probability at or above which the email is flagged. 0.5 is the
# neutral default; lowering it buys recall at the cost of precision, which is
# often the right trade in email security.
DEFAULT_THRESHOLD = 0.5


class PhishingDetectorError(RuntimeError):
    """Raised when the detector cannot load or cannot predict."""


class PhishingDetector:
    """Loads the fine-tuned BERT classifier once and serves predictions."""

    def __init__(self, model_dir=DEFAULT_MODEL_DIR, threshold=DEFAULT_THRESHOLD):
        self.model_dir = model_dir
        self.threshold = threshold

        self.model = None
        self.tokenizer = None
        self.device = None
        self.torch = None
        self.id2label = {0: "LEGITIMATE", 1: "PHISHING"}
        self.max_length = DEFAULT_MAX_LENGTH
        self.model_info = {}

        self._lock = threading.Lock()
        self._load_error = None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_loaded(self):
        return self.model is not None and self.tokenizer is not None

    def load(self):
        """Load weights and tokenizer. Idempotent; safe to call at startup."""
        with self._lock:
            if self.is_loaded:
                return True

            try:
                if not os.path.isdir(self.model_dir):
                    raise FileNotFoundError(
                        f"{self.model_dir} does not exist. Train the model, or run "
                        "python -m src.models.train_phishing_bert --finalize"
                    )

                import torch
                from transformers import (AutoModelForSequenceClassification,
                                          AutoTokenizer)

                self.torch = torch
                self.device = torch.device(
                    "cuda" if torch.cuda.is_available() else "cpu"
                )

                self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_dir
                )
                self.model.to(self.device)
                self.model.eval()

                # Trust the saved config for the label mapping.
                config_labels = getattr(self.model.config, "id2label", None)
                if config_labels:
                    self.id2label = {int(k): str(v) for k, v in config_labels.items()}

                # Optional sidecar written by the training script.
                info_path = os.path.join(self.model_dir, "phishing_model_info.json")
                if os.path.exists(info_path):
                    with open(info_path, encoding="utf-8") as handle:
                        self.model_info = json.load(handle)
                    self.max_length = self.model_info.get(
                        "max_length", DEFAULT_MAX_LENGTH
                    )

                self._load_error = None
                return True

            except Exception as error:
                self.model = None
                self.tokenizer = None
                self._load_error = f"{type(error).__name__}: {error}"
                raise PhishingDetectorError(
                    f"Could not load the phishing model: {self._load_error}"
                ) from error

    def info(self):
        """Status for the /health endpoint."""
        return {
            "loaded": self.is_loaded,
            "algorithm": "Fine-tuned BERT (bert-base-uncased)",
            "labels": self.id2label,
            "max_length": self.max_length,
            "threshold": self.threshold,
            "device": str(self.device) if self.device else None,
            "model_path": os.path.relpath(self.model_dir, PROJECT_ROOT),
            "test_metrics": self.model_info.get("test_metrics"),
            "error": self._load_error,
        }

    # -- prediction -------------------------------------------------------

    def predict(self, text, threshold=None):
        """Classify one email as PHISHING or LEGITIMATE."""
        if not self.is_loaded:
            raise PhishingDetectorError("Phishing model is not loaded.")

        threshold = self.threshold if threshold is None else threshold
        raw = str(text)

        encoded = self.tokenizer(
            raw,
            truncation=True,            # head truncation, matching training
            max_length=self.max_length,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        with self.torch.no_grad():
            logits = self.model(**encoded).logits

        probabilities = self.torch.softmax(logits, dim=-1)[0]
        phishing_probability = float(probabilities[1])
        legitimate_probability = float(probabilities[0])

        is_phishing = phishing_probability >= threshold
        label_id = 1 if is_phishing else 0

        # How much of the email the model actually saw.
        full_length = len(
            self.tokenizer.encode(raw, truncation=False, add_special_tokens=True)
        )

        return {
            "prediction": self.id2label.get(label_id, str(label_id)),
            "label_id": label_id,
            "is_phishing": is_phishing,
            "phishing_probability": phishing_probability,
            "legitimate_probability": legitimate_probability,
            "confidence": max(phishing_probability, legitimate_probability),
            "threshold_used": threshold,
            "tokens": full_length,
            "truncated": full_length > self.max_length,
        }


# Module-level singleton, loaded once per process at application startup.
phishing_detector = PhishingDetector()
