"""Fine-tune BERT to classify emails as Legitimate (0) or Phishing (1).

    AI Email Threat Detection Agent - phishing pipeline

This is a NEW, independent pipeline. It does not read, write, import or depend
on the existing Spam/Ham pipeline (spam_model.pkl, count_vectorizer.pkl,
email_spam.csv, src/api/*). Nothing here touches the FastAPI app or the React
frontend.

USAGE
-----
    python -m src.models.train_phishing_bert --preflight    # checks only, no training
    python -m src.models.train_phishing_bert --split-only   # write train/val/test, no training
    python -m src.models.train_phishing_bert                # full run

SCRIPT LAYOUT
-------------
     1. Configuration            9. Model initialisation
     2. Imports                 10. Training
     3. Reproducibility         11. Validation
     4. Dataset loading         12. Final testing
     5. Dataset verification    13. Error analysis
     6. Train/val/test split    14. Model saving
     7. Tokenisation            15. Reporting
     8. Dataset preparation

A NOTE ON WHAT A GOOD SCORE HERE DOES AND DOES NOT MEAN
-------------------------------------------------------
A high test score on this dataset does not make this a production phishing
detector. The corpora behind it (Enron, SpamAssassin, Nazario, CEAS 2008,
Nigerian fraud) are largely from 2002-2008. Real phishing has moved on:
current attacks use different brands, shorter pretexts, cloud-hosted landing
pages and LLM-written prose. A model trained here is a solid coursework and
research artefact, and an honest baseline, but deploying it on live mail would
need current data, ongoing retraining, and evaluation against the base rate of
real traffic (where phishing is rare, not 50% as it is here).
"""

# ==========================================================================
# 2. IMPORTS
# ==========================================================================

import argparse
import hashlib
import json
import os
import platform
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

# Heavy / optional dependencies are imported lazily inside the functions that
# need them, so that --preflight and --split-only still run on a machine where
# PyTorch and Transformers are not installed yet.


# ==========================================================================
# 1. CONFIGURATION
# ==========================================================================


@dataclass
class Config:
    """Every knob worth turning, in one place."""

    # --- model / tokenisation ---
    MODEL_NAME: str = "bert-base-uncased"
    MAX_LENGTH: int = 512

    # --- optimisation ---
    BATCH_SIZE: int = 8            # per device; safe for a 6-8 GB GPU at 512 tokens
    GRAD_ACCUM_STEPS: int = 4      # effective batch = BATCH_SIZE * GRAD_ACCUM_STEPS = 32
    LEARNING_RATE: float = 2e-5    # the standard BERT fine-tuning rate
    NUM_EPOCHS: int = 3            # BERT converges fast; early stopping usually ends it sooner
    WEIGHT_DECAY: float = 0.01
    WARMUP_RATIO: float = 0.1
    MAX_GRAD_NORM: float = 1.0

    # --- reproducibility ---
    RANDOM_SEED: int = 42

    # --- split ---
    TRAIN_RATIO: float = 0.80
    VAL_RATIO: float = 0.10
    TEST_RATIO: float = 0.10

    # --- early stopping / model selection ---
    EARLY_STOPPING_PATIENCE: int = 2
    METRIC_FOR_BEST: str = "f1"    # see note in section 10 on why not "recall"
    EVAL_STEPS: int = 500
    SAVE_TOTAL_LIMIT: int = 2

    # --- error analysis ---
    MAX_MISCLASSIFIED_SAVED: int = 200
    MISCLASSIFIED_TEXT_CHARS: int = 1000

    # --- performance ---
    FP16: bool = True              # only used when CUDA is present
    DATALOADER_WORKERS: int = 2

    # --- duplicate detection (kept identical to the preprocessing stage) ---
    NEAR_DUP_PREFIX: int = 200

    # Third dedup layer: rare-token signatures. Catches near-duplicates whose
    # opening lines differ, which the prefix key cannot see. On this dataset it
    # removes ~4,449 extra records (6.4%). Measured on 400 flagged pairs, the
    # median text similarity is 0.92, so most are genuine template variants;
    # the lower-similarity remainder is mostly replies in the same thread that
    # share a quoted block, which is itself a leakage route. Set to False to
    # keep those records and compare the effect on the test score.
    USE_SIGNATURE_DEDUP: bool = True


CFG = Config()

# Label convention. Written into the model config so inference is unambiguous.
ID2LABEL = {0: "LEGITIMATE", 1: "PHISHING"}
LABEL2ID = {"LEGITIMATE": 0, "PHISHING": 1}
POSITIVE_CLASS = 1  # phishing; the class whose recall matters most

# --- paths ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
INPUT_CSV = os.path.join(DATA_DIR, "phishing_cleaned.csv")
TRAIN_CSV = os.path.join(DATA_DIR, "train.csv")
VAL_CSV = os.path.join(DATA_DIR, "validation.csv")
TEST_CSV = os.path.join(DATA_DIR, "test.csv")

MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "phishing_bert")
CHECKPOINT_DIR = os.path.join(PROJECT_ROOT, "models", "phishing_bert_checkpoints")

REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
REPORT_TXT = os.path.join(REPORTS_DIR, "phishing_classification_report.txt")
CONFUSION_PNG = os.path.join(REPORTS_DIR, "phishing_confusion_matrix.png")
METRICS_JSON = os.path.join(REPORTS_DIR, "phishing_metrics.json")
MISCLASSIFIED_CSV = os.path.join(REPORTS_DIR, "misclassified_emails.csv")
TRAINING_SUMMARY = os.path.join(REPORTS_DIR, "training_summary.txt")

REQUIRED_COLUMNS = ["text", "label"]
VALID_LABELS = {0, 1}


def banner(title):
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


def ensure_directories():
    """Create every output directory up front.

    Previously each writer created its own directory, and save_confusion_matrix
    was the one that did not. That turned a missing folder into a crash in
    Phase 6, AFTER training and test evaluation had finished but BEFORE the
    model was saved in Phase 8, which threw away hours of training. Creating
    all of them before any long work starts removes that class of failure.
    """
    for directory in (DATA_DIR, MODEL_DIR, CHECKPOINT_DIR, REPORTS_DIR):
        os.makedirs(directory, exist_ok=True)


# ==========================================================================
# 3. REPRODUCIBILITY
# ==========================================================================


def set_seeds(seed):
    """Seed every RNG that can affect the run.

    This makes the split and the training order deterministic. Exact bit-for-bit
    reproducibility on GPU also needs deterministic cuDNN kernels, which costs
    speed; we set the flag but leave benchmark mode off rather than forcing
    fully deterministic algorithms.
    """
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        pass


# ==========================================================================
# DEPENDENCY AND HARDWARE CHECKS
# ==========================================================================


def check_packages():
    """Report which required packages are present. Never installs anything.

    torch and transformers are always reported as blocking when absent, in
    every mode. Preflight exists precisely to surface that, so it must not be
    softened just because the current invocation would not have trained.
    """
    results = {}

    def probe(name, import_name=None):
        try:
            module = __import__(import_name or name)
            results[name] = getattr(module, "__version__", "unknown")
            return True
        except ImportError:
            results[name] = None
            return False

    probe("numpy")
    probe("pandas")
    probe("scikit-learn", "sklearn")
    probe("matplotlib")
    ok_torch = probe("torch")
    ok_tf = probe("transformers")
    probe("datasets")
    probe("accelerate")

    missing = [name for name, version in results.items() if version is None]

    print("Package check:")
    for name, version in results.items():
        mark = "OK  " if version else "MISSING"
        print(f"  {mark} {name:<14} {version or ''}")

    blocking = []
    if not ok_torch:
        blocking.append("torch")
    if not ok_tf:
        blocking.append("transformers")

    return results, missing, blocking


def detect_device():
    """Pick CUDA if it is genuinely available, otherwise CPU."""
    try:
        import torch
    except ImportError:
        return "unavailable", {"note": "torch not installed"}

    if torch.cuda.is_available():
        index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(index)
        return "cuda", {
            "name": properties.name,
            "total_memory_gb": round(properties.total_memory / 1024**3, 2),
            "cuda_version": torch.version.cuda,
        }

    return "cpu", {
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def estimate_runtime(device_type, n_train, cfg):
    """Rough wall-clock estimate, so a multi-day CPU run is not a surprise.

    Throughputs are order-of-magnitude figures for bert-base at 512 tokens.
    """
    # When torch is absent the device is unknown, so quote both so the cost of
    # having no GPU is visible before anyone starts a run.
    if device_type == "cuda":
        rates = [("this CUDA GPU", 18.0)]
    elif device_type == "cpu":
        rates = [("this CPU", 0.8)]
    else:
        rates = [("a mid-range CUDA GPU", 18.0), ("CPU only", 0.8)]

    estimates = []
    for note, samples_per_second in rates:
        seconds_per_epoch = n_train / samples_per_second
        estimates.append({
            "device": note,
            "hours_per_epoch": round(seconds_per_epoch / 3600, 2),
            "total_hours": round(seconds_per_epoch * cfg.NUM_EPOCHS / 3600, 2),
        })

    return estimates


# ==========================================================================
# 4. DATASET LOADING  &  5. DATASET VERIFICATION
# ==========================================================================


RE_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
RE_WHITESPACE = re.compile(r"\s+")


def dedup_key(text, prefix=None):
    """Normalised hash key - identical logic to the preprocessing stage.

    Used for comparison only. Nothing normalised here is ever trained on.
    """
    lowered = RE_NON_ALNUM.sub(" ", str(text).lower())
    collapsed = RE_WHITESPACE.sub(" ", lowered).strip()
    if prefix:
        collapsed = collapsed[:prefix]
    return hashlib.md5(collapsed.encode("utf-8")).hexdigest()


def signature_key(text, min_len=7, take=12):
    """A third, order-independent near-duplicate key.

    The prefix key from preprocessing misses pairs that differ in their opening
    lines but are otherwise the same email. This builds a signature from the
    rarest (longest) tokens instead, which survives reordering and edits to the
    opening. Returns None for texts too short to fingerprint reliably.
    """
    tokens = sorted({w for w in RE_NON_ALNUM.sub(" ", str(text).lower()).split() if len(w) >= min_len})
    if len(tokens) < 4:
        return None
    return hashlib.md5("|".join(tokens[:take]).encode("utf-8")).hexdigest()


def load_and_verify(path):
    """Load the dataset and prove its structure rather than assuming it."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path, low_memory=False)

    print(f"Loaded : {path}")
    print(f"Rows   : {len(df):,}")
    print(f"Columns: {list(df.columns)}")

    problems = []

    # -- columns --
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        problems.append(f"missing required column(s): {missing_cols}")

    if problems:
        return df, problems

    # -- missing values --
    null_text = int(df["text"].isna().sum())
    null_label = int(df["label"].isna().sum())
    print(f"Nulls  : text={null_text:,}  label={null_label:,}")
    if null_text or null_label:
        problems.append(f"null values present (text={null_text}, label={null_label})")

    # -- empty strings --
    empty = int((df["text"].astype(str).str.strip() == "").sum())
    print(f"Empty  : {empty:,}")
    if empty:
        problems.append(f"{empty} empty text records")

    # -- labels --
    observed = set(pd.unique(df["label"].dropna()))
    print(f"Labels : {sorted(observed)}")
    unexpected = observed - VALID_LABELS
    if unexpected:
        problems.append(f"unexpected label values: {sorted(unexpected)}")

    # -- class distribution --
    counts = df["label"].value_counts().to_dict()
    total = len(df)
    print("Classes:")
    for label in sorted(VALID_LABELS):
        count = int(counts.get(label, 0))
        print(f"  {label} = {ID2LABEL[label]:<11} {count:>8,}  ({count / total * 100:5.2f}%)")

    # -- duplicates --
    exact = int(df["text"].map(dedup_key).duplicated().sum())
    near = int(df["text"].map(lambda t: dedup_key(t, CFG.NEAR_DUP_PREFIX)).duplicated().sum())
    print(f"Dupes  : exact={exact:,}  near={near:,}")

    return df, problems


# ==========================================================================
# 6. TRAIN / VALIDATION / TEST SPLIT
# ==========================================================================


def audit_and_drop_leakage(df):
    """Remove residual near-duplicates BEFORE splitting.

    Deduplication has to happen before the split, not after. If two copies of
    an email survive into different splits, the model memorises one and is
    graded on the other, and the test score becomes a measure of recall from
    memory rather than generalisation.

    Three layers are applied, reusing the preprocessing logic:
      1. exact       full normalised text
      2. prefix      first 200 normalised characters
      3. signature   the 12 longest distinct tokens (order-independent)
    """
    before = len(df)
    stats = {"before": before}

    df = df.copy()
    df["_exact"] = df["text"].map(dedup_key)
    df = df.drop_duplicates(subset="_exact", keep="first")
    stats["removed_exact"] = before - len(df)

    step = len(df)
    df["_prefix"] = df["text"].map(lambda t: dedup_key(t, CFG.NEAR_DUP_PREFIX))
    df = df.drop_duplicates(subset="_prefix", keep="first")
    stats["removed_prefix"] = step - len(df)

    step = len(df)
    if CFG.USE_SIGNATURE_DEDUP:
        df["_sig"] = df["text"].map(signature_key)
        # Rows with no usable signature (too short) are kept as-is.
        has_sig = df["_sig"].notna()
        keep_mask = ~(has_sig & df["_sig"].duplicated(keep="first"))
        df = df[keep_mask]
    else:
        df["_sig"] = None
    stats["removed_signature"] = step - len(df)
    stats["signature_dedup_enabled"] = CFG.USE_SIGNATURE_DEDUP

    stats["after"] = len(df)
    stats["removed_total"] = before - len(df)

    return df.drop(columns=["_exact", "_prefix", "_sig"]).reset_index(drop=True), stats


def stratified_split(df, cfg):
    """80/10/10 stratified split with a fixed seed."""
    from sklearn.model_selection import train_test_split

    # First peel off train, then halve the remainder into validation and test.
    train_df, rest_df = train_test_split(
        df,
        train_size=cfg.TRAIN_RATIO,
        random_state=cfg.RANDOM_SEED,
        stratify=df["label"],
        shuffle=True,
    )

    relative_val = cfg.VAL_RATIO / (cfg.VAL_RATIO + cfg.TEST_RATIO)
    val_df, test_df = train_test_split(
        rest_df,
        train_size=relative_val,
        random_state=cfg.RANDOM_SEED,
        stratify=rest_df["label"],
        shuffle=True,
    )

    return (
        train_df.reset_index(drop=True),
        val_df.reset_index(drop=True),
        test_df.reset_index(drop=True),
    )


def verify_no_leakage(train_df, val_df, test_df):
    """Prove that no email appears in more than one split."""
    findings = {}

    for name, key_fn in [
        ("exact", lambda t: dedup_key(t)),
        ("prefix", lambda t: dedup_key(t, CFG.NEAR_DUP_PREFIX)),
        ("signature", signature_key),
    ]:
        keys = {}
        for split_name, split_df in [("train", train_df), ("validation", val_df), ("test", test_df)]:
            keys[split_name] = {k for k in split_df["text"].map(key_fn) if k is not None}

        findings[name] = {
            "train_validation": len(keys["train"] & keys["validation"]),
            "train_test": len(keys["train"] & keys["test"]),
            "validation_test": len(keys["validation"] & keys["test"]),
        }

    total_overlap = sum(sum(v.values()) for v in findings.values())
    return findings, total_overlap


def describe_split(name, split_df, total):
    counts = split_df["label"].value_counts().to_dict()
    n = len(split_df)
    legit = int(counts.get(0, 0))
    phish = int(counts.get(1, 0))
    print(
        f"  {name:<11} {n:>7,}  ({n / total * 100:5.2f}% of total)   "
        f"legit {legit:>6,} ({legit / n * 100:5.2f}%)   "
        f"phish {phish:>6,} ({phish / n * 100:5.2f}%)"
    )
    return {"total": n, "legitimate": legit, "phishing": phish}


def run_split(cfg, df=None):
    """Full Phase 1: audit, split, verify, save."""
    banner("PHASE 1  TRAIN / VALIDATION / TEST SPLIT")

    if df is None:
        df, problems = load_and_verify(INPUT_CSV)
        if problems:
            raise ValueError("; ".join(problems))

    print()
    print("Leakage audit before splitting (three duplicate layers):")
    df, dup_stats = audit_and_drop_leakage(df)
    print(f"  removed exact          : {dup_stats['removed_exact']:,}")
    print(f"  removed prefix-200     : {dup_stats['removed_prefix']:,}")
    print(f"  removed rare-token sig : {dup_stats['removed_signature']:,}")
    print(f"  records remaining      : {dup_stats['after']:,}")

    train_df, val_df, test_df = stratified_split(df, cfg)
    total = len(df)

    print()
    print(f"Total records after audit: {total:,}")
    split_stats = {
        "train": describe_split("Training", train_df, total),
        "validation": describe_split("Validation", val_df, total),
        "test": describe_split("Testing", test_df, total),
    }

    print()
    print("Leakage verification after splitting (0 means no overlap):")
    findings, total_overlap = verify_no_leakage(train_df, val_df, test_df)
    for layer, pairs in findings.items():
        print(f"  {layer:<10} " + "  ".join(f"{k}={v}" for k, v in pairs.items()))

    if total_overlap:
        raise RuntimeError(f"Data leakage detected across splits: {findings}")
    print("  PASS - no email appears in more than one split")

    os.makedirs(DATA_DIR, exist_ok=True)
    train_df[REQUIRED_COLUMNS].to_csv(TRAIN_CSV, index=False, encoding="utf-8")
    val_df[REQUIRED_COLUMNS].to_csv(VAL_CSV, index=False, encoding="utf-8")
    test_df[REQUIRED_COLUMNS].to_csv(TEST_CSV, index=False, encoding="utf-8")

    print()
    print(f"Saved: {TRAIN_CSV}")
    print(f"Saved: {VAL_CSV}")
    print(f"Saved: {TEST_CSV}")

    return train_df, val_df, test_df, {"duplicates": dup_stats, "splits": split_stats,
                                        "leakage": findings}


# ==========================================================================
# 7. TOKENISATION  &  8. DATASET PREPARATION
# ==========================================================================


def build_tokenizer(cfg):
    """Load the pretrained WordPiece tokenizer.

    No vocabulary is built by hand, and no CountVectorizer / TF-IDF / Word2Vec
    is involved: BERT must use the exact vocabulary its pretrained weights were
    learned with, otherwise the embeddings are meaningless.
    """
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(cfg.MODEL_NAME)

    print(f"Tokenizer      : {type(tokenizer).__name__}")
    print(f"Checkpoint     : {cfg.MODEL_NAME}")
    print(f"Vocabulary size: {tokenizer.vocab_size:,}")
    print(f"Max length     : {cfg.MAX_LENGTH}")
    print(f"Lowercases     : {getattr(tokenizer, 'do_lower_case', 'n/a')}")
    print(f"Special tokens : {tokenizer.cls_token} {tokenizer.sep_token} "
          f"{tokenizer.pad_token} {tokenizer.unk_token} {tokenizer.mask_token}")

    return tokenizer


class EmailDataset:
    """Tokenises lazily, one email at a time.

    Tokenising all 56k training emails up front at 512 tokens would hold roughly
    56,000 x 512 x 2 int64 tensors in RAM at once. Doing it per item in
    __getitem__ keeps memory flat and costs very little, because tokenisation
    is far cheaper than a BERT forward pass.
    """

    def __init__(self, texts, labels, tokenizer, max_length):
        self.texts = list(texts)
        self.labels = list(labels)
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, index):
        import torch

        encoding = self.tokenizer(
            str(self.texts[index]),
            truncation=True,          # cut anything past MAX_LENGTH
            max_length=self.max_length,
            padding="max_length",     # the collator could pad dynamically, but
                                      # fixed padding keeps shapes predictable
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": torch.tensor(int(self.labels[index]), dtype=torch.long),
        }


def report_truncation(tokenizer, texts, cfg, sample_size=2000):
    """Measure how many emails BERT will actually have to cut.

    HOW BERT HANDLES EMAILS LONGER THAN 512 TOKENS
    ----------------------------------------------
    It cannot handle them directly. BERT's learned positional embedding table
    has exactly 512 rows, so position 513 has no representation and the
    self-attention cost grows with the square of the sequence length anyway.
    Anything longer must be shortened before it reaches the model. The options:

      a. Head truncation (what this script does, truncation=True)
         Keep the first 512 tokens, discard the rest. Cheap, and phishing cues
         are usually front-loaded: subject line, greeting, the urgency hook and
         the first link nearly always appear early.
      b. Head + tail
         Keep the first ~384 and last ~128 tokens. Also catches sign-off cues
         such as spoofed signatures and fake unsubscribe footers.
      c. Chunk and pool
         Split into overlapping 512-token windows, classify each, then pool
         (max or mean) the results. Most faithful, several times the compute.
      d. A long-context model
         Longformer or BigBird handle 4096 tokens natively.

    This script uses (a) as the baseline and reports below exactly how much
    text that discards, so the trade-off is visible rather than hidden.
    """
    sample = texts[:sample_size] if len(texts) > sample_size else texts

    lengths = [len(tokenizer.encode(str(t), truncation=False,
                                    add_special_tokens=True)) for t in sample]
    lengths = np.array(lengths)
    over = lengths > cfg.MAX_LENGTH

    stats = {
        "sampled": int(len(lengths)),
        "median_tokens": float(np.median(lengths)),
        "mean_tokens": float(lengths.mean()),
        "p95_tokens": float(np.percentile(lengths, 95)),
        "max_tokens": int(lengths.max()),
        "over_limit": int(over.sum()),
        "over_limit_pct": float(over.mean() * 100),
        "mean_tokens_discarded_when_over": (
            float((lengths[over] - cfg.MAX_LENGTH).mean()) if over.any() else 0.0
        ),
    }

    print()
    print(f"Token length on a {stats['sampled']:,}-email sample:")
    print(f"  median {stats['median_tokens']:.0f} | mean {stats['mean_tokens']:.0f} | "
          f"p95 {stats['p95_tokens']:.0f} | max {stats['max_tokens']:,}")
    print(f"  over {cfg.MAX_LENGTH} tokens: {stats['over_limit']:,} "
          f"({stats['over_limit_pct']:.1f}%) - these are head-truncated")
    if stats["over_limit"]:
        print(f"  when truncated, {stats['mean_tokens_discarded_when_over']:.0f} tokens "
              f"are discarded on average")

    return stats


# ==========================================================================
# 9. MODEL INITIALISATION
# ==========================================================================


def build_model(cfg):
    """Load pretrained BERT with a fresh 2-way classification head.

    The encoder arrives pretrained; the classification head is randomly
    initialised and learned during fine-tuning. Transformers warns about those
    newly initialised weights, which is expected, not an error.
    """
    from transformers import AutoConfig, AutoModelForSequenceClassification

    config = AutoConfig.from_pretrained(
        cfg.MODEL_NAME,
        num_labels=2,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )
    model = AutoModelForSequenceClassification.from_pretrained(cfg.MODEL_NAME, config=config)

    total_params = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Model      : {cfg.MODEL_NAME}")
    print(f"Parameters : {total_params:,} total, {trainable:,} trainable")
    print(f"Label map  : {ID2LABEL}")

    return model


# ==========================================================================
# 11. VALIDATION - metrics
# ==========================================================================


def compute_metrics(eval_pred):
    """Accuracy, precision, recall, F1 and F2, reported for the phishing class.

    Accuracy alone is a poor guide here. Precision and recall trade against
    each other, and in email security the two errors have very different costs:

      False negative  phishing predicted legitimate. The attack lands in the
                      user's inbox. This is the expensive one.
      False positive  legitimate predicted phishing. A real email is
                      quarantined. Annoying, and at scale it erodes trust in
                      the filter, but nobody gets compromised.

    F2 is also reported because it weights recall twice as heavily as
    precision, which matches that asymmetry better than F1 does.
    """
    from sklearn.metrics import (accuracy_score, fbeta_score, precision_recall_fscore_support)

    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)

    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", pos_label=POSITIVE_CLASS, zero_division=0
    )

    return {
        "accuracy": accuracy_score(labels, predictions),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "f2": fbeta_score(labels, predictions, beta=2,
                          pos_label=POSITIVE_CLASS, zero_division=0),
    }


# ==========================================================================
# 10. TRAINING
# ==========================================================================


def compute_training_steps(n_train, cfg):
    """Total optimiser steps and the warm-up slice of them.

    Transformers 5.x removed `warmup_ratio`, so the ratio in Config has to be
    converted into an absolute `warmup_steps` count here.
    """
    import math

    effective_batch = cfg.BATCH_SIZE * cfg.GRAD_ACCUM_STEPS
    steps_per_epoch = math.ceil(n_train / effective_batch)
    total_steps = steps_per_epoch * cfg.NUM_EPOCHS
    warmup_steps = int(total_steps * cfg.WARMUP_RATIO)

    return {
        "effective_batch": effective_batch,
        "steps_per_epoch": steps_per_epoch,
        "total_steps": total_steps,
        "warmup_steps": warmup_steps,
    }


def build_training_arguments(cfg, device_type, n_train, verbose=True):
    """Build TrainingArguments, filtered against the installed Transformers.

    The Transformers training API changes between major versions. Rather than
    pin to one release, the desired settings are declared here and then matched
    against the TrainingArguments dataclass that is actually installed:

      * a setting the installed version still accepts is passed through
      * a setting it has renamed is passed under the new name
      * a setting it has dropped is skipped, and the omission is reported

    Known changes handled:
      transformers 5.x  removed `overwrite_output_dir`  -> directory cleared in Python
      transformers 5.x  removed `warmup_ratio`          -> converted to `warmup_steps`
      transformers 4.46 renamed `evaluation_strategy`   -> `eval_strategy`
    """
    import dataclasses

    from transformers import TrainingArguments

    available = {f.name for f in dataclasses.fields(TrainingArguments)}

    use_fp16 = cfg.FP16 and device_type == "cuda"
    steps = compute_training_steps(n_train, cfg)

    # Desired settings, expressed in the current (5.x) vocabulary.
    desired = {
        "output_dir": CHECKPOINT_DIR,

        "num_train_epochs": cfg.NUM_EPOCHS,
        "per_device_train_batch_size": cfg.BATCH_SIZE,
        "per_device_eval_batch_size": cfg.BATCH_SIZE * 2,
        "gradient_accumulation_steps": cfg.GRAD_ACCUM_STEPS,

        "learning_rate": cfg.LEARNING_RATE,
        "weight_decay": cfg.WEIGHT_DECAY,
        "warmup_steps": steps["warmup_steps"],
        "lr_scheduler_type": "linear",
        "max_grad_norm": cfg.MAX_GRAD_NORM,

        "eval_strategy": "steps",
        "eval_steps": cfg.EVAL_STEPS,
        "save_strategy": "steps",
        "save_steps": cfg.EVAL_STEPS,
        "save_total_limit": cfg.SAVE_TOTAL_LIMIT,

        "load_best_model_at_end": True,
        "metric_for_best_model": cfg.METRIC_FOR_BEST,
        "greater_is_better": True,

        "logging_steps": 100,
        "logging_first_step": True,
        "report_to": "none",

        "fp16": use_fp16,
        "dataloader_num_workers": cfg.DATALOADER_WORKERS,
        "seed": cfg.RANDOM_SEED,
        "data_seed": cfg.RANDOM_SEED,
    }

    # Name changes: new name -> older name to fall back on.
    aliases = {"eval_strategy": "evaluation_strategy"}

    kwargs, skipped, renamed = {}, [], []
    for name, value in desired.items():
        if name in available:
            kwargs[name] = value
        elif name in aliases and aliases[name] in available:
            kwargs[aliases[name]] = value
            renamed.append(f"{name} -> {aliases[name]}")
        else:
            skipped.append(name)

    if verbose:
        import transformers

        print(f"Transformers version  : {transformers.__version__}")
        print(f"Effective batch size  : {steps['effective_batch']} "
              f"({cfg.BATCH_SIZE} x {cfg.GRAD_ACCUM_STEPS} accumulation)")
        print(f"Steps per epoch       : {steps['steps_per_epoch']:,}")
        print(f"Total optimiser steps : {steps['total_steps']:,}")
        print(f"Warm-up steps         : {steps['warmup_steps']:,} "
              f"({cfg.WARMUP_RATIO:.0%} of total, converted from WARMUP_RATIO)")
        print(f"Mixed precision (fp16): {use_fp16}")
        if renamed:
            print(f"Renamed for this version: {', '.join(renamed)}")
        if skipped:
            print(f"Not supported here, skipped: {', '.join(skipped)}")

    return TrainingArguments(**kwargs), steps


def build_trainer(model, tokenizer, train_ds, val_ds, args, cfg):
    """Construct the Trainer, adapting to what the installed version accepts.

    `tokenizer=` was deprecated in 4.46 and replaced by `processing_class=`.
    Passing the wrong one raises, so the accepted name is detected at runtime.
    Either way the tokenizer is also saved explicitly in section 14, so the
    saved model is complete regardless.
    """
    import inspect

    from transformers import EarlyStoppingCallback, Trainer

    kwargs = {
        "model": model,
        "args": args,
        "train_dataset": train_ds,
        "eval_dataset": val_ds,
        "compute_metrics": compute_metrics,
        "callbacks": [
            EarlyStoppingCallback(early_stopping_patience=cfg.EARLY_STOPPING_PATIENCE)
        ],
    }

    try:
        accepted = set(inspect.signature(Trainer.__init__).parameters)
    except (TypeError, ValueError):
        accepted = set()

    if "processing_class" in accepted:
        kwargs["processing_class"] = tokenizer
    elif "tokenizer" in accepted:
        kwargs["tokenizer"] = tokenizer
    # If neither is exposed (Trainer takes **kwargs), leave it out: the
    # tokenizer is saved separately and nothing in training depends on it.

    return Trainer(**kwargs)


def train_model(model, tokenizer, train_ds, val_ds, cfg, device_type):
    """Fine-tune with early stopping, checkpointing and best-model selection.

    METRIC_FOR_BEST defaults to f1 rather than recall on purpose. Selecting on
    recall alone is degenerate: a model that labels every email as phishing
    scores recall 1.0 and is useless. F1 (or F2, for a recall-leaning choice)
    keeps both error types in view.
    """
    import shutil

    # `overwrite_output_dir` no longer exists in Transformers 5.x, so the
    # checkpoint directory is cleared here instead to keep the same behaviour.
    if os.path.isdir(CHECKPOINT_DIR):
        shutil.rmtree(CHECKPOINT_DIR, ignore_errors=True)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)

    args, _ = build_training_arguments(cfg, device_type, len(train_ds))
    trainer = build_trainer(model, tokenizer, train_ds, val_ds, args, cfg)

    print(f"Early stopping        : patience {cfg.EARLY_STOPPING_PATIENCE} "
          f"on validation {cfg.METRIC_FOR_BEST}")
    print()

    train_result = trainer.train()

    return trainer, train_result


# ==========================================================================
# 12. FINAL TESTING
# ==========================================================================


def evaluate_on_test(trainer, test_df, test_ds, cfg):
    """Evaluate the selected model on the held-out test set, once.

    The test set has not been seen during training or model selection. Early
    stopping and best-checkpoint selection both used validation only.
    """
    from scipy.special import softmax
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, fbeta_score,
                                 precision_recall_fscore_support, roc_auc_score)

    output = trainer.predict(test_ds)
    logits = output.predictions
    y_true = np.array(test_df["label"].values)
    y_pred = np.argmax(logits, axis=-1)
    probabilities = softmax(logits, axis=-1)
    phishing_prob = probabilities[:, POSITIVE_CLASS]

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", pos_label=POSITIVE_CLASS, zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()

    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "phishing_precision": float(precision),
        "phishing_recall": float(recall),
        "phishing_f1": float(f1),
        "phishing_f2": float(fbeta_score(y_true, y_pred, beta=2,
                                         pos_label=POSITIVE_CLASS, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, phishing_prob)),
        "confusion_matrix": {
            "true_negative_legit_as_legit": int(tn),
            "false_positive_legit_as_phish": int(fp),
            "false_negative_phish_as_legit": int(fn),
            "true_positive_phish_as_phish": int(tp),
        },
        "false_negative_rate": float(fn / (fn + tp)) if (fn + tp) else 0.0,
        "false_positive_rate": float(fp / (fp + tn)) if (fp + tn) else 0.0,
        "test_size": int(len(y_true)),
    }

    report_text = classification_report(
        y_true, y_pred, labels=[0, 1],
        target_names=[ID2LABEL[0], ID2LABEL[1]], digits=4, zero_division=0,
    )

    return metrics, report_text, matrix, y_true, y_pred, phishing_prob


def save_confusion_matrix(matrix, path):
    # The directory is created here as well as in ensure_directories(), so this
    # function is safe to call on its own from the finalize path.
    os.makedirs(os.path.dirname(path), exist_ok=True)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 5.2))
    ax.imshow(matrix, cmap="Blues")

    labels = [ID2LABEL[0], ID2LABEL[1]]
    ax.set_xticks([0, 1], labels=labels)
    ax.set_yticks([0, 1], labels=labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Phishing detection - confusion matrix (test set)")

    corner = ["True negative", "FALSE POSITIVE", "FALSE NEGATIVE", "True positive"]
    threshold = matrix.max() / 2
    for i in range(2):
        for j in range(2):
            value = matrix[i, j]
            ax.text(j, i, f"{value:,}\n{corner[i * 2 + j]}",
                    ha="center", va="center",
                    color="white" if value > threshold else "black", fontsize=11)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ==========================================================================
# 13. ERROR ANALYSIS
# ==========================================================================


def error_analysis(test_df, y_true, y_pred, phishing_prob, cfg):
    """Save a bounded sample of the model's mistakes.

    Only misclassified rows are saved, not the whole test set, and the text is
    truncated so the file stays readable.
    """
    wrong = y_true != y_pred
    indices = np.where(wrong)[0]

    false_negatives = [i for i in indices if y_true[i] == 1]  # phishing missed
    false_positives = [i for i in indices if y_true[i] == 0]  # legit blocked

    # Show the most confident mistakes first: those are the informative ones.
    false_negatives.sort(key=lambda i: phishing_prob[i])
    false_positives.sort(key=lambda i: -phishing_prob[i])

    half = cfg.MAX_MISCLASSIFIED_SAVED // 2
    chosen = false_negatives[:half] + false_positives[:half]

    rows = []
    for i in chosen:
        rows.append({
            "text": str(test_df["text"].iloc[i])[: cfg.MISCLASSIFIED_TEXT_CHARS],
            "actual_label": int(y_true[i]),
            "actual_name": ID2LABEL[int(y_true[i])],
            "predicted_label": int(y_pred[i]),
            "predicted_name": ID2LABEL[int(y_pred[i])],
            "prediction_probability": round(float(phishing_prob[i]), 6),
            "error_type": "FALSE_NEGATIVE" if y_true[i] == 1 else "FALSE_POSITIVE",
        })

    frame = pd.DataFrame(rows)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    frame.to_csv(MISCLASSIFIED_CSV, index=False, encoding="utf-8")

    return {
        "total_misclassified": int(wrong.sum()),
        "false_negatives": len(false_negatives),
        "false_positives": len(false_positives),
        "saved_to_csv": len(rows),
    }


# ==========================================================================
# 14. MODEL SAVING
# ==========================================================================


def save_model(trainer, tokenizer, cfg, metrics):
    """Persist weights, config, tokenizer and label mapping for later inference."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    trainer.save_model(MODEL_DIR)     # config.json + model.safetensors
    tokenizer.save_pretrained(MODEL_DIR)

    # A small sidecar so inference code never has to guess the conventions.
    metadata = {
        "model_name": cfg.MODEL_NAME,
        "task": "binary phishing email classification",
        "id2label": ID2LABEL,
        "label2id": LABEL2ID,
        "max_length": cfg.MAX_LENGTH,
        "truncation": "head (first %d tokens)" % cfg.MAX_LENGTH,
        "positive_class": POSITIVE_CLASS,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "test_metrics": metrics,
    }
    with open(os.path.join(MODEL_DIR, "phishing_model_info.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    print(f"Model and tokenizer saved to: {MODEL_DIR}")
    print("Contents:", sorted(os.listdir(MODEL_DIR)))


# ==========================================================================
# 15. REPORTING
# ==========================================================================


def write_reports(cfg, device_type, device_info, split_info, token_stats,
                  val_metrics, metrics, report_text, matrix, error_stats,
                  train_result, versions, duration_minutes):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # -- classification report --
    cm = metrics["confusion_matrix"]
    lines = [
        "=" * 74,
        "PHISHING DETECTION - TEST SET CLASSIFICATION REPORT",
        "=" * 74,
        f"Generated : {datetime.now().isoformat(timespec='seconds')}",
        f"Model     : {cfg.MODEL_NAME} fine-tuned",
        f"Test size : {metrics['test_size']:,} emails (never seen during training)",
        "",
        report_text,
        "",
        "-" * 74,
        "CONFUSION MATRIX",
        "-" * 74,
        "                        Predicted LEGITIMATE   Predicted PHISHING",
        f"  Actual LEGITIMATE    {cm['true_negative_legit_as_legit']:>18,}   "
        f"{cm['false_positive_legit_as_phish']:>18,}",
        f"  Actual PHISHING      {cm['false_negative_phish_as_legit']:>18,}   "
        f"{cm['true_positive_phish_as_phish']:>18,}",
        "",
        "-" * 74,
        "SECURITY-RELEVANT READING",
        "-" * 74,
        f"Phishing recall    : {metrics['phishing_recall']:.4f}",
        f"Phishing precision : {metrics['phishing_precision']:.4f}",
        f"Phishing F1        : {metrics['phishing_f1']:.4f}",
        f"Phishing F2        : {metrics['phishing_f2']:.4f}   (recall weighted 2x)",
        f"ROC AUC            : {metrics['roc_auc']:.4f}",
        "",
        f"False negatives    : {cm['false_negative_phish_as_legit']:,} "
        f"({metrics['false_negative_rate'] * 100:.2f}% of phishing)",
        "  Phishing delivered to the inbox. The expensive error: one click can",
        "  mean credential theft or malware execution.",
        "",
        f"False positives    : {cm['false_positive_legit_as_phish']:,} "
        f"({metrics['false_positive_rate'] * 100:.2f}% of legitimate)",
        "  Legitimate mail quarantined. Cheap per incident, but at scale it",
        "  trains users to ignore the filter, which costs recall indirectly.",
        "",
        "WHY RECALL IS THE HEADLINE NUMBER",
        "  The two errors are not symmetric. A quarantined newsletter is",
        "  recoverable; a delivered credential-harvesting page may not be. That",
        "  is why F2 is reported next to F1, and why the threshold can be moved",
        "  below 0.5 to buy recall at the cost of precision if the deployment",
        "  can absorb the extra false positives.",
        "",
        "LIMITS OF THIS EVALUATION",
        "  * The test set is ~50/50 phishing to legitimate. Real inbound mail is",
        "    nothing like that, so precision here is optimistic: at a realistic",
        "    base rate the same model produces far more false positives per true",
        "    catch.",
        "  * The source corpora are largely 2002-2008. Scores do not transfer to",
        "    current attacks without fresh data.",
        "  * No adversarial testing was done. Attackers adapt; this was measured",
        "    on a static dataset.",
        "=" * 74,
    ]
    with open(REPORT_TXT, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

    # -- metrics json --
    payload = {
        "test_metrics": metrics,
        "validation_metrics": val_metrics,
        "error_analysis": error_stats,
        "config": asdict(cfg),
        "dataset_sizes": split_info["splits"],
        "device": {"type": device_type, **device_info},
        "versions": versions,
        "training_duration_minutes": duration_minutes,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(METRICS_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    # -- training summary --
    dup = split_info["duplicates"]
    summary = [
        "=" * 74,
        "PHISHING BERT - TRAINING SUMMARY (REPRODUCIBILITY RECORD)",
        "=" * 74,
        f"Generated : {datetime.now().isoformat(timespec='seconds')}",
        "",
        "ENVIRONMENT",
        f"  Python       : {versions.get('python')}",
        f"  PyTorch      : {versions.get('torch')}",
        f"  Transformers : {versions.get('transformers')}",
        f"  scikit-learn : {versions.get('scikit-learn')}",
        f"  NumPy        : {versions.get('numpy')}",
        f"  pandas       : {versions.get('pandas')}",
        f"  Platform     : {versions.get('platform')}",
        f"  Device       : {device_type} {device_info}",
        "",
        "TRAINING PARAMETERS",
    ]
    for key, value in asdict(cfg).items():
        summary.append(f"  {key:<24}: {value}")

    summary += [
        "",
        "DATASET",
        f"  Source              : data/processed/phishing_cleaned.csv",
        f"  Records before audit: {dup['before']:,}",
        f"  Duplicates removed  : {dup['removed_total']:,} "
        f"(exact {dup['removed_exact']:,}, prefix {dup['removed_prefix']:,}, "
        f"signature {dup['removed_signature']:,})",
        f"  Records used        : {dup['after']:,}",
        f"  Training            : {split_info['splits']['train']['total']:,}",
        f"  Validation          : {split_info['splits']['validation']['total']:,}",
        f"  Test                : {split_info['splits']['test']['total']:,}",
        f"  Leakage check       : PASS (no overlap on any of 3 duplicate layers)",
        "",
        "TOKENISATION",
        f"  Tokenizer      : {cfg.MODEL_NAME} WordPiece",
        f"  Max length     : {cfg.MAX_LENGTH}",
        f"  Truncation     : head",
        f"  Over limit     : {token_stats['over_limit_pct']:.1f}% of sampled emails",
        "",
        "RESULTS",
        (f"  Training time       : {duration_minutes:.1f} minutes"
         if duration_minutes else
         "  Training time       : not recorded (reports regenerated with --finalize)"),
        f"  Best val {cfg.METRIC_FOR_BEST:<11}: {val_metrics.get('eval_' + cfg.METRIC_FOR_BEST, 'n/a')}",
        f"  Test accuracy       : {metrics['accuracy']:.4f}",
        f"  Test phishing recall: {metrics['phishing_recall']:.4f}",
        f"  Test phishing prec. : {metrics['phishing_precision']:.4f}",
        f"  Test phishing F1    : {metrics['phishing_f1']:.4f}",
        f"  Test ROC AUC        : {metrics['roc_auc']:.4f}",
        "",
        "REPRODUCING THIS RUN",
        f"  python -m src.models.train_phishing_bert",
        f"  Seed {cfg.RANDOM_SEED} is applied to random, numpy and torch. Split files are",
        "  written to data/processed/ and are deterministic for a given seed.",
        "  Exact GPU reproducibility also depends on cuDNN kernel selection.",
        "=" * 74,
    ]
    with open(TRAINING_SUMMARY, "w", encoding="utf-8") as handle:
        handle.write("\n".join(summary) + "\n")


def collect_versions():
    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for name, import_name in [("torch", "torch"), ("transformers", "transformers"),
                              ("scikit-learn", "sklearn"), ("numpy", "numpy"),
                              ("pandas", "pandas")]:
        try:
            versions[name] = getattr(__import__(import_name), "__version__", "unknown")
        except ImportError:
            versions[name] = None
    return versions


# ==========================================================================
# ORCHESTRATION
# ==========================================================================


def find_best_checkpoint():
    """Locate the best checkpoint left behind by a completed training run.

    Trainer records `best_model_checkpoint` in trainer_state.json, so the
    selection made during training is respected rather than guessed. If that
    path is missing (for example the run moved machines), the highest step
    number is used instead.
    """
    if not os.path.isdir(CHECKPOINT_DIR):
        return None, None

    checkpoints = [
        os.path.join(CHECKPOINT_DIR, name)
        for name in os.listdir(CHECKPOINT_DIR)
        if name.startswith("checkpoint-")
        and os.path.isdir(os.path.join(CHECKPOINT_DIR, name))
    ]
    if not checkpoints:
        return None, None

    checkpoints.sort(key=lambda p: int(p.rsplit("-", 1)[-1]))
    latest = checkpoints[-1]

    state_path = os.path.join(latest, "trainer_state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as handle:
            state = json.load(handle)

    best = state.get("best_model_checkpoint")
    if best:
        # The recorded path is absolute and from the original machine; match on
        # the folder name so a moved project still resolves.
        candidate = os.path.join(CHECKPOINT_DIR, os.path.basename(best))
        if os.path.isdir(candidate):
            return candidate, state

    return latest, state


def recover_validation_metrics(state, cfg):
    """Pull the final validation metrics out of the saved trainer state.

    These were computed during training on the validation split, so they do not
    need recomputing. Only the test metrics have to be regenerated.
    """
    evaluations = [entry for entry in state.get("log_history", []) if "eval_loss" in entry]
    if not evaluations:
        return {}, []

    best_step = state.get("best_global_step")
    chosen = next((e for e in evaluations if e.get("step") == best_step), evaluations[-1])
    return chosen, evaluations


def finalize_run(cfg):
    """Rescue a training run that finished but crashed before saving.

    Does NOT retrain. It loads the best checkpoint produced by the completed
    run, saves it properly, re-runs inference on the test split (evaluation
    only, no gradient updates), and writes every report.
    """
    banner("FINALIZE - RECOVERING A COMPLETED TRAINING RUN")

    ensure_directories()

    checkpoint, state = find_best_checkpoint()
    if checkpoint is None:
        sys.exit(
            f"No checkpoints found in {CHECKPOINT_DIR}.\n"
            "There is nothing to finalize - the training run would have to be repeated."
        )

    print(f"Best checkpoint  : {os.path.basename(checkpoint)}")
    print(f"Recorded metric  : {state.get('best_metric')} ({cfg.METRIC_FOR_BEST})")
    print(f"Epochs completed : {state.get('epoch')}")
    print(f"Steps completed  : {state.get('global_step')} of {state.get('max_steps')}")

    val_metrics, all_evals = recover_validation_metrics(state, cfg)
    print(f"Validation evals recovered from trainer_state.json: {len(all_evals)}")

    # The run that produced this checkpoint may have used different settings
    # than Config's defaults (for example --epochs 1). Take the real values
    # from the saved state so the report describes what actually happened
    # rather than what the defaults say.
    actual_epochs = state.get("num_train_epochs")
    if actual_epochs and actual_epochs != cfg.NUM_EPOCHS:
        print(f"NOTE: the run used {actual_epochs} epoch(s), not the default "
              f"{cfg.NUM_EPOCHS}. Reporting the value actually used.")
        cfg.NUM_EPOCHS = int(actual_epochs)

    actual_batch = state.get("train_batch_size")
    if actual_batch and actual_batch != cfg.BATCH_SIZE:
        print(f"NOTE: the run used batch size {actual_batch}, not {cfg.BATCH_SIZE}.")
        cfg.BATCH_SIZE = int(actual_batch)

    # --- 1. Save the model properly (the step the crash skipped) ------------
    banner("1. SAVING MODEL AND TOKENIZER")
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model = AutoModelForSequenceClassification.from_pretrained(checkpoint)
    try:
        tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    except Exception:
        # Older checkpoints may not carry tokenizer files; fall back to the base.
        print(f"  tokenizer not in checkpoint, loading {cfg.MODEL_NAME}")
        tokenizer = AutoTokenizer.from_pretrained(cfg.MODEL_NAME)

    # Make sure the label mapping is correct regardless of what was saved.
    model.config.id2label = ID2LABEL
    model.config.label2id = LABEL2ID

    os.makedirs(MODEL_DIR, exist_ok=True)
    model.save_pretrained(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    print(f"  saved to {MODEL_DIR}")

    # --- 2. Rebuild the split (deterministic, identical files) --------------
    banner("2. REBUILDING THE SPLIT (deterministic, seed %d)" % cfg.RANDOM_SEED)
    df, problems = load_and_verify(INPUT_CSV)
    if problems:
        sys.exit("; ".join(problems))
    train_df, val_df, test_df, split_info = run_split(cfg, df=df)

    # --- 3. Test-set inference (evaluation only, no training) ---------------
    banner("3. TEST SET EVALUATION (inference only - no training)")
    device_type, device_info = detect_device()
    print(f"Device: {device_type}")
    print(f"Evaluating {len(test_df):,} test emails. On CPU this takes a while.")

    # A minimal, inference-only TrainingArguments. The full training config is
    # not reused here: load_best_model_at_end and the eval/save strategies all
    # assume a training loop with datasets attached, and none of that applies
    # when the only job is a forward pass over the test set.
    import dataclasses

    from transformers import Trainer, TrainingArguments

    available = {f.name for f in dataclasses.fields(TrainingArguments)}
    infer_kwargs = {
        "output_dir": CHECKPOINT_DIR,
        "per_device_eval_batch_size": cfg.BATCH_SIZE * 2,
        "dataloader_num_workers": cfg.DATALOADER_WORKERS,
        "report_to": "none",
        "seed": cfg.RANDOM_SEED,
        "fp16": cfg.FP16 and device_type == "cuda",
    }
    args = TrainingArguments(**{k: v for k, v in infer_kwargs.items() if k in available})
    trainer = Trainer(model=model, args=args, compute_metrics=compute_metrics)

    test_ds = EmailDataset(test_df["text"], test_df["label"], tokenizer, cfg.MAX_LENGTH)
    metrics, report_text, matrix, y_true, y_pred, phishing_prob = evaluate_on_test(
        trainer, test_df, test_ds, cfg
    )
    print(report_text)

    # --- 4. Reports ---------------------------------------------------------
    banner("4. WRITING REPORTS")
    save_confusion_matrix(matrix, CONFUSION_PNG)
    print(f"  {CONFUSION_PNG}")

    error_stats = error_analysis(test_df, y_true, y_pred, phishing_prob, cfg)
    print(f"  {MISCLASSIFIED_CSV}")

    token_stats = report_truncation(tokenizer, list(train_df["text"]), cfg, sample_size=500)

    versions = collect_versions()
    write_reports(cfg, device_type, device_info, split_info, token_stats,
                  val_metrics, metrics, report_text, matrix, error_stats,
                  None, versions, duration_minutes=0.0)
    print(f"  {REPORT_TXT}")
    print(f"  {METRICS_JSON}")
    print(f"  {TRAINING_SUMMARY}")

    # --- 5. Save the model info sidecar with real metrics -------------------
    metadata = {
        "model_name": cfg.MODEL_NAME,
        "task": "binary phishing email classification",
        "id2label": ID2LABEL,
        "label2id": LABEL2ID,
        "max_length": cfg.MAX_LENGTH,
        "truncation": f"head (first {cfg.MAX_LENGTH} tokens)",
        "positive_class": POSITIVE_CLASS,
        "recovered_from_checkpoint": os.path.basename(checkpoint),
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "validation_metrics": val_metrics,
        "test_metrics": metrics,
    }
    with open(os.path.join(MODEL_DIR, "phishing_model_info.json"), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    banner("FINALIZE COMPLETE")
    print(f"Model   : {MODEL_DIR}")
    print(f"Reports : {REPORTS_DIR}")
    print("The model was NOT retrained; the completed run's best checkpoint was used.")

    return metrics


def verify_saved_model(cfg):
    """Load the saved model back from disk and run one prediction.

    This proves the artefact is self-contained and usable without retraining.
    """
    banner("VERIFYING THE SAVED MODEL LOADS")

    if not os.path.isdir(MODEL_DIR):
        sys.exit(f"Nothing saved at {MODEL_DIR}. Run --finalize first.")

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    print(f"Loading from: {MODEL_DIR}")
    print("Files:", sorted(os.listdir(MODEL_DIR)))

    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()

    print(f"  tokenizer : {type(tokenizer).__name__} (vocab {tokenizer.vocab_size:,})")
    print(f"  model     : {type(model).__name__} "
          f"({sum(p.numel() for p in model.parameters()):,} params)")
    print(f"  id2label  : {model.config.id2label}")

    samples = [
        ("phishing-style", "URGENT: Your account has been suspended. Verify your "
                           "identity now at http://paypa1-secure.com/login or it "
                           "will be closed permanently."),
        ("legitimate-style", "Hi Sam, thanks for sending the Q3 doc. I've added "
                             "comments on the timeline. Can we discuss on Thursday?"),
    ]

    print()
    for name, text in samples:
        encoded = tokenizer(text, truncation=True, max_length=cfg.MAX_LENGTH,
                            padding=True, return_tensors="pt")
        with torch.no_grad():
            logits = model(**encoded).logits
        probabilities = torch.softmax(logits, dim=-1)[0]
        predicted = int(torch.argmax(probabilities))
        print(f"  {name:<18} -> {ID2LABEL[predicted]:<11} "
              f"P(phishing)={float(probabilities[1]):.4f}")

    print()
    print("RESULT: PASS - the saved model loads and predicts without retraining.")
    return True


def check_trainer_init(cfg):
    """Prove TrainingArguments and Trainer construct on this exact install.

    Builds a deliberately tiny BERT from a local config rather than downloading
    bert-base-uncased, so the check is fast and works offline. It exercises the
    same code path the real run uses: the same TrainingArguments builder, the
    same Trainer builder, the same callbacks.

    Nothing is trained and nothing is saved outside a temporary directory.
    """
    import shutil
    import tempfile

    banner("TRAINER INITIALISATION CHECK")

    try:
        import torch
        import transformers
        from transformers import BertConfig, BertForSequenceClassification
    except ImportError as error:
        sys.exit(f"Cannot run the check: {error}")

    print(f"torch        : {torch.__version__}")
    print(f"transformers : {transformers.__version__}")
    device_type, _ = detect_device()
    print(f"device       : {device_type}")
    print()

    # 1. TrainingArguments with the real configuration.
    print("1. Building TrainingArguments with the real config")
    temp_dir = tempfile.mkdtemp(prefix="phishing_trainer_check_")
    global CHECKPOINT_DIR
    real_checkpoint_dir = CHECKPOINT_DIR
    CHECKPOINT_DIR = temp_dir

    try:
        args, steps = build_training_arguments(cfg, device_type, n_train=52_420)
        print("   TrainingArguments constructed OK")

        # 2. A small model, built locally - no network access required.
        print()
        print("2. Building a tiny local BERT (no download)")
        tiny_config = BertConfig(
            vocab_size=1000, hidden_size=32, num_hidden_layers=2,
            num_attention_heads=2, intermediate_size=64, max_position_embeddings=64,
            num_labels=2, id2label=ID2LABEL, label2id=LABEL2ID,
        )
        tiny_model = BertForSequenceClassification(tiny_config)
        print(f"   tiny model OK ({sum(p.numel() for p in tiny_model.parameters()):,} params)")

        # 3. A dummy dataset shaped exactly like EmailDataset's output.
        print()
        print("3. Building dummy datasets")

        class _DummyDataset:
            def __init__(self, n):
                self.n = n

            def __len__(self):
                return self.n

            def __getitem__(self, index):
                return {
                    "input_ids": torch.randint(0, 999, (16,)),
                    "attention_mask": torch.ones(16, dtype=torch.long),
                    "labels": torch.tensor(index % 2, dtype=torch.long),
                }

        train_ds, val_ds = _DummyDataset(16), _DummyDataset(8)
        print("   datasets OK")

        # 4. The Trainer itself, with the real callbacks.
        print()
        print("4. Building Trainer (with EarlyStoppingCallback)")
        trainer = build_trainer(tiny_model, None, train_ds, val_ds, args, cfg)
        print(f"   Trainer constructed OK ({type(trainer).__name__})")

        # 5. compute_metrics, which also has to survive version changes.
        print()
        print("5. Checking compute_metrics")
        fake_logits = np.array([[2.0, -1.0], [-1.0, 2.0], [0.5, 0.4], [-2.0, 1.0]])
        fake_labels = np.array([0, 1, 0, 1])
        metrics = compute_metrics((fake_logits, fake_labels))
        print("   " + "  ".join(f"{k}={v:.3f}" for k, v in metrics.items()))

        print()
        print("RESULT: PASS - the training pipeline initialises on this install.")
        print("        No training was started and no model was downloaded.")
        return True

    finally:
        CHECKPOINT_DIR = real_checkpoint_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


def preflight(cfg):
    """Everything that must pass before a long training run starts."""
    banner("PREFLIGHT CHECKS")

    print("1. DATASET")
    df, problems = load_and_verify(INPUT_CSV)

    print()
    print("2. PACKAGES")
    versions, missing, blocking = check_packages()

    print()
    print("3. HARDWARE")
    device_type, device_info = detect_device()
    print(f"  Device: {device_type}")
    for key, value in device_info.items():
        print(f"    {key}: {value}")

    print()
    print("4. PLANNED CONFIGURATION")
    for key, value in asdict(cfg).items():
        print(f"  {key:<24}: {value}")

    n_train = int(len(df) * cfg.TRAIN_RATIO)
    print()
    print("5. RUNTIME ESTIMATE (rough order of magnitude)")
    for estimate in estimate_runtime(device_type, n_train, cfg) or []:
        print(f"  {estimate['device']:<22}: ~{estimate['hours_per_epoch']} h/epoch, "
              f"~{estimate['total_hours']} h for {cfg.NUM_EPOCHS} epochs")

    print()
    print("6. VERDICT")
    if problems:
        print("  DATASET PROBLEMS:")
        for problem in problems:
            print(f"    - {problem}")
    if blocking:
        print(f"  BLOCKED - missing required packages: {', '.join(blocking)}")
        print("    Training cannot run until these are installed:")
        print("      # CUDA 12.1 build (use this if you have an NVIDIA GPU)")
        print("      pip install torch --index-url https://download.pytorch.org/whl/cu121")
        print("      # or the CPU-only build")
        print("      pip install torch")
        print("      pip install transformers accelerate")
    if not problems and not blocking:
        print("  PASS - ready to train")
    elif not problems:
        print("  Dataset is fine; only the package installs are outstanding.")

    return df, problems, blocking, device_type, device_info, versions


def main():
    parser = argparse.ArgumentParser(description="Fine-tune BERT for phishing detection")
    parser.add_argument("--preflight", action="store_true",
                        help="run checks only, do not split or train")
    parser.add_argument("--split-only", action="store_true",
                        help="write train/validation/test.csv, do not train")
    parser.add_argument("--check-trainer", action="store_true",
                        help="verify TrainingArguments and Trainer build on this "
                             "Transformers version; no download, no training")
    parser.add_argument("--finalize", action="store_true",
                        help="recover a completed run: save the best checkpoint, "
                             "re-run test inference and write all reports. "
                             "Does NOT retrain.")
    parser.add_argument("--verify-model", action="store_true",
                        help="load models/phishing_bert/ and run a sample prediction")
    parser.add_argument("--epochs", type=int, help="override NUM_EPOCHS")
    parser.add_argument("--batch-size", type=int, help="override BATCH_SIZE")
    parser.add_argument("--max-length", type=int, help="override MAX_LENGTH")
    parser.add_argument("--model-name", type=str, help="override MODEL_NAME")
    args = parser.parse_args()

    cfg = Config()
    if args.epochs:
        cfg.NUM_EPOCHS = args.epochs
    if args.batch_size:
        cfg.BATCH_SIZE = args.batch_size
    if args.max_length:
        cfg.MAX_LENGTH = args.max_length
    if args.model_name:
        cfg.MODEL_NAME = args.model_name

    set_seeds(cfg.RANDOM_SEED)

    # Runs on its own: no dataset needed, no download, no training.
    if args.check_trainer:
        check_trainer_init(cfg)
        return

    if args.verify_model:
        verify_saved_model(cfg)
        return

    # Recovery path for a run that trained successfully but crashed afterwards.
    if args.finalize:
        finalize_run(cfg)
        verify_saved_model(cfg)
        return

    banner("AI EMAIL THREAT DETECTION AGENT - PHISHING BERT TRAINING")
    print(f"Started      : {datetime.now().isoformat(timespec='seconds')}")
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Seed         : {cfg.RANDOM_SEED}")

    df, problems, blocking, device_type, device_info, versions = preflight(cfg)

    # STOP rather than guess, exactly as the brief requires.
    if problems:
        sys.exit("\nSTOPPED: dataset verification failed. Nothing was trained.")

    if args.preflight:
        print("\nPreflight only. Nothing else was run.")
        return

    # ---- Phase 1: split ----
    train_df, val_df, test_df, split_info = run_split(cfg, df=df)

    if args.split_only:
        print("\nSplit complete. Training skipped (--split-only).")
        return

    if blocking:
        sys.exit(
            f"\nSTOPPED: required packages missing ({', '.join(blocking)}). "
            "The split files were written; install the packages and re-run to train."
        )

    # ---- Phases 2-8 ----
    # Every output directory is created before the expensive work begins, so a
    # missing folder can never destroy a finished training run again.
    ensure_directories()

    started = datetime.now()

    banner("PHASE 2  TOKENIZER")
    tokenizer = build_tokenizer(cfg)
    token_stats = report_truncation(tokenizer, list(train_df["text"]), cfg)

    banner("PHASE 3  MODEL")
    print(f"Device: {device_type}")
    model = build_model(cfg)

    train_ds = EmailDataset(train_df["text"], train_df["label"], tokenizer, cfg.MAX_LENGTH)
    val_ds = EmailDataset(val_df["text"], val_df["label"], tokenizer, cfg.MAX_LENGTH)
    test_ds = EmailDataset(test_df["text"], test_df["label"], tokenizer, cfg.MAX_LENGTH)

    banner("PHASE 4-5  FINE-TUNING AND VALIDATION")
    trainer, _ = train_model(model, tokenizer, train_ds, val_ds, cfg, device_type)

    val_metrics = trainer.evaluate(eval_dataset=val_ds)
    print()
    print("Final validation metrics:")
    for key, value in val_metrics.items():
        if isinstance(value, float):
            print(f"  {key:<28}: {value:.4f}")

    banner("PHASE 6  FINAL TEST EVALUATION")
    metrics, report_text, matrix, y_true, y_pred, phishing_prob = evaluate_on_test(
        trainer, test_df, test_ds, cfg
    )
    print(report_text)
    save_confusion_matrix(matrix, CONFUSION_PNG)

    banner("PHASE 7  ERROR ANALYSIS")
    error_stats = error_analysis(test_df, y_true, y_pred, phishing_prob, cfg)
    print(f"Misclassified total : {error_stats['total_misclassified']:,}")
    print(f"  false negatives   : {error_stats['false_negatives']:,}  (phishing missed)")
    print(f"  false positives   : {error_stats['false_positives']:,}  (legitimate blocked)")
    print(f"Saved sample        : {error_stats['saved_to_csv']} rows -> {MISCLASSIFIED_CSV}")

    banner("PHASE 8  SAVING MODEL")
    save_model(trainer, tokenizer, cfg, metrics)

    duration = (datetime.now() - started).total_seconds() / 60
    versions = collect_versions()
    write_reports(cfg, device_type, device_info, split_info, token_stats,
                  val_metrics, metrics, report_text, matrix, error_stats,
                  None, versions, duration)

    banner("DONE")
    print(f"Duration: {duration:.1f} minutes")
    print(f"Model   : {MODEL_DIR}")
    print(f"Reports : {REPORTS_DIR}")


if __name__ == "__main__":
    main()
