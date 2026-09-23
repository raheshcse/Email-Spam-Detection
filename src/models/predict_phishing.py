"""Load the fine-tuned phishing BERT model and classify a new email.

This is a standalone demonstration that the saved model loads and predicts
without retraining. It is deliberately NOT wired into the FastAPI backend or
the React frontend - integration is a separate step.

USAGE
-----
    # built-in demo emails
    python -m src.models.predict_phishing

    # one email from a file
    python -m src.models.predict_phishing --file suspicious.txt

    # one email from the command line
    python -m src.models.predict_phishing --text "Verify your account now"

FROM PYTHON
-----------
    from src.models.predict_phishing import PhishingDetector

    detector = PhishingDetector()
    result = detector.predict("Your account has been suspended, click here")
    print(result["label"], result["phishing_probability"])
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "phishing_bert")

DEFAULT_MAX_LENGTH = 512


class PhishingDetector:
    """Thin wrapper around the saved model and tokenizer."""

    def __init__(self, model_dir=MODEL_DIR, device=None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if not os.path.isdir(model_dir):
            raise FileNotFoundError(
                f"No saved model at {model_dir}. Run the training script first:\n"
                "    python -m src.models.train_phishing_bert"
            )

        self.torch = torch
        self.model_dir = model_dir

        # Pick the device unless one was supplied.
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.model.to(self.device)
        self.model.eval()  # disables dropout; required for stable inference

        # id2label is stored in config.json at training time, so inference does
        # not have to hard-code which index means phishing.
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}

        # Optional sidecar written by the training script.
        self.max_length = DEFAULT_MAX_LENGTH
        info_path = os.path.join(model_dir, "phishing_model_info.json")
        if os.path.exists(info_path):
            with open(info_path, encoding="utf-8") as handle:
                self.info = json.load(handle)
            self.max_length = self.info.get("max_length", DEFAULT_MAX_LENGTH)
        else:
            self.info = {}

    def predict(self, text, threshold=0.5):
        """Classify one email.

        `threshold` is the phishing probability above which the email is
        flagged. Lowering it below 0.5 buys recall at the cost of precision,
        which is often the right trade in email security: a quarantined
        newsletter is recoverable, a delivered credential-harvesting page may
        not be.
        """
        return self.predict_batch([text], threshold=threshold)[0]

    def predict_batch(self, texts, threshold=0.5, batch_size=8):
        results = []

        for start in range(0, len(texts), batch_size):
            chunk = [str(t) for t in texts[start : start + batch_size]]

            encoded = self.tokenizer(
                chunk,
                truncation=True,             # same head truncation as training
                max_length=self.max_length,
                padding=True,
                return_tensors="pt",
            ).to(self.device)

            with self.torch.no_grad():       # no gradients needed for inference
                logits = self.model(**encoded).logits

            probabilities = self.torch.softmax(logits, dim=-1).cpu().numpy()

            for text, row in zip(chunk, probabilities):
                phishing_probability = float(row[1])
                is_phishing = phishing_probability >= threshold
                results.append({
                    "label": "PHISHING" if is_phishing else "LEGITIMATE",
                    "label_id": 1 if is_phishing else 0,
                    "phishing_probability": round(phishing_probability, 6),
                    "legitimate_probability": round(float(row[0]), 6),
                    "confidence": round(max(float(row[0]), phishing_probability), 6),
                    "threshold_used": threshold,
                    "characters": len(text),
                    "truncated": len(
                        self.tokenizer.encode(text, truncation=False,
                                              add_special_tokens=True)
                    ) > self.max_length,
                })

        return results


DEMO_EMAILS = [
    (
        "Classic credential-harvesting attempt",
        "URGENT: Your PayPal account has been limited!\n\n"
        "Dear Customer,\n\nWe detected unusual activity on your account. Your "
        "access has been temporarily suspended. To restore full access you must "
        "verify your identity within 24 hours or your account will be closed "
        "permanently.\n\nVerify now: http://paypa1-secure-verify.com/login\n\n"
        "Failure to act will result in permanent suspension.\n\nPayPal Security Team",
    ),
    (
        "Ordinary work email",
        "Re: Q3 planning doc\n\nHi Sam,\n\nThanks for sending that over. I've "
        "added comments to the second section, mostly around the timeline - I "
        "think we need another week for the migration testing. Can we discuss "
        "at Thursday's standup?\n\nCheers,\nRahesh",
    ),
    (
        "Advance-fee fraud",
        "CONFIDENTIAL BUSINESS PROPOSAL\n\nDear Friend,\n\nI am the personal "
        "assistant to a late government official. I have access to the sum of "
        "USD 15,500,000 which requires a foreign partner for transfer. I am "
        "offering you 30% for your assistance. Please send your full name, "
        "bank details and telephone number to proceed urgently.",
    ),
]


def main():
    parser = argparse.ArgumentParser(description="Classify an email as phishing or legitimate")
    parser.add_argument("--text", type=str, help="email text to classify")
    parser.add_argument("--file", type=str, help="path to a file containing the email")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="phishing probability threshold (default 0.5)")
    parser.add_argument("--model-dir", type=str, default=MODEL_DIR)
    args = parser.parse_args()

    print("=" * 70)
    print("PHISHING DETECTOR - LOADING SAVED MODEL")
    print("=" * 70)

    try:
        detector = PhishingDetector(model_dir=args.model_dir)
    except FileNotFoundError as error:
        sys.exit(str(error))
    except ImportError:
        sys.exit("torch and transformers are required.\n"
                 "    pip install torch transformers")

    print(f"Model dir : {detector.model_dir}")
    print(f"Device    : {detector.device}")
    print(f"Labels    : {detector.id2label}")
    print(f"Max length: {detector.max_length}")

    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as handle:
            samples = [(os.path.basename(args.file), handle.read())]
    elif args.text:
        samples = [("command line input", args.text)]
    else:
        samples = DEMO_EMAILS
        print("\nNo --text or --file given, running the built-in demo emails.")

    for title, text in samples:
        result = detector.predict(text, threshold=args.threshold)

        print()
        print("-" * 70)
        print(f"{title}")
        print("-" * 70)
        preview = text.replace("\n", " ")[:120]
        print(f"Preview  : {preview}...")
        print(f"VERDICT  : {result['label']}")
        print(f"P(phishing)   : {result['phishing_probability']:.4f}")
        print(f"P(legitimate) : {result['legitimate_probability']:.4f}")
        if result["truncated"]:
            print(f"Note     : longer than {detector.max_length} tokens, head-truncated")

    print()
    print("Reminder: this is a research baseline trained on 2002-2008 corpora.")
    print("Do not rely on it alone to protect a live mailbox.")


if __name__ == "__main__":
    main()
