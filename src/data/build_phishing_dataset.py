"""Consolidate the seven raw phishing corpora into one BERT-ready dataset.

Reads the datasets in data/raw/, maps each one's own schema onto a standard
``text, label`` pair, drops unusable and duplicate records, then samples a
balanced subset and writes data/raw/phishing_combined.csv.

Deliberately NOT done here (later stages own these):
    no text cleaning, no tokenisation, no embeddings, no vectorisation,
    no train/test split, no model training.

The ``text`` column keeps the original casing, punctuation and stop words,
because that is what a BERT WordPiece tokeniser expects. Normalisation is used
only to build duplicate-detection keys, never to rewrite what gets saved.

Run from the project root:

    python -m src.data.build_phishing_dataset
"""

import hashlib
import os
import re
import sys

import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
OUTPUT_PATH = os.path.join(RAW_DIR, "phishing_combined.csv")

TARGET_ROWS = 70_000
RANDOM_SEED = 42

# Minimum words for a record to be worth training on.
MIN_WORDS = 5
# Length of the normalised prefix used for near-duplicate detection. Spam
# corpora are full of template variants that differ only in a trailing tracking
# token, so a prefix key catches far more real duplicates than exact matching.
NEAR_DUP_PREFIX = 200

# Each source declares its own column names and label meaning. Nothing is
# assumed to be shared between files.
#
#   subject_col / body_col / text_col : where the email content lives
#   label_col                         : the phishing indicator
#   label_map                         : that file's label values -> 1 phishing, 0 legitimate
#   priority                          : lower wins when the same email appears
#                                       in several files; smaller and more
#                                       specialised corpora are kept so the
#                                       final mix stays diverse
SOURCES = [
    {
        "name": "Nazario",
        "file": "Nazario.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 1,
    },
    {
        "name": "Nigerian_Fraud",
        "file": "Nigerian_Fraud.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 2,
    },
    {
        "name": "Ling",
        "file": "Ling.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 3,
    },
    {
        "name": "SpamAssassin",
        "file": "SpamAssasin.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 4,
    },
    {
        "name": "CEAS_08",
        "file": "CEAS_08.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 5,
    },
    {
        "name": "Enron",
        "file": "Enron.csv",
        "subject_col": "subject",
        "body_col": "body",
        "label_col": "label",
        "label_map": {0: 0, 1: 1},
        "priority": 6,
    },
]

# phishing_email.csv is excluded from the consolidated output. It is a derived
# file, not an independent corpus:
#   * its 82,486 rows equal the sum of the six source files exactly
#   * its label totals (42,891 / 39,595) equal their sum exactly
#   * its only text column is already lowercased, stripped of punctuation and
#     stripped of stop words, which destroys the casing, punctuation and
#     function words BERT relies on
# It is still counted and reported below so the audit trail is complete.
DERIVED_SOURCE = {
    "name": "phishing_email",
    "file": "phishing_email.csv",
    "text_col": "text_combined",
    "label_col": "label",
}

# Mail-system artefacts that are not emails at all.
ARTEFACT_PATTERNS = [
    "internal format of your mail folder",
    "folder internal data",
]

_ws_re = re.compile(r"\s+")
_non_alnum_re = re.compile(r"[^a-z0-9 ]")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def normalise_for_key(text):
    """Lowercase, strip punctuation and collapse whitespace.

    Used ONLY to build duplicate-detection keys. The saved text is untouched.
    """
    lowered = str(text).lower()
    lowered = _non_alnum_re.sub(" ", lowered)
    return _ws_re.sub(" ", lowered).strip()


def hash_key(value):
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def build_text(subject, body):
    """Join subject and body without altering either.

    A plain blank-line join is used rather than a "Subject:" prefix: several
    files have rows with no subject, and a prefix that appears only on some
    rows would leak dataset provenance into the text as a spurious feature.
    """
    subject = "" if subject is None else str(subject).strip()
    body = "" if body is None else str(body).strip()

    if subject.lower() in ("nan", "none"):
        subject = ""
    if body.lower() in ("nan", "none"):
        body = ""

    if subject and body:
        return f"{subject}\n\n{body}"
    return subject or body


def quality_tier(df):
    """0 = best. Used to prefer richer examples when sampling.

    Tier 0 is a substantial body with a real subject line, tier 1 is a decent
    body, tier 2 is everything else that still passed the validity checks.
    """
    tier = pd.Series(2, index=df.index, dtype=int)
    tier[df["word_count"] >= 10] = 1
    tier[(df["word_count"] >= 20) & df["has_subject"].fillna(False)] = 0
    return tier


def allocate(quota, available):
    """Spread ``quota`` across strata as evenly as their sizes allow.

    Smallest strata are served first and taken whole, so niche corpora survive
    instead of being swamped by the two large ones.
    """
    allocation = {key: 0 for key in available}
    remaining = quota
    pending = sorted(available, key=lambda k: available[k])

    while pending and remaining > 0:
        fair_share = remaining // len(pending)
        if fair_share == 0:
            for key in pending[: remaining]:
                allocation[key] += 1
            remaining = 0
            break

        key = pending.pop(0)
        take = min(available[key], fair_share)
        allocation[key] = take
        remaining -= take

    return allocation


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def load_sources(report):
    frames = []

    for source in SOURCES:
        path = os.path.join(RAW_DIR, source["file"])
        if not os.path.exists(path):
            print(f"  ! missing file, skipped: {source['file']}")
            continue

        df = pd.read_csv(path, low_memory=False)
        found = len(df)

        subjects = df.get(source["subject_col"], pd.Series([""] * found))
        bodies = df[source["body_col"]]

        text = [build_text(s, b) for s, b in zip(subjects, bodies)]

        clean_subject = (
            subjects.fillna("").astype(str).str.strip().str.lower()
        )
        has_subject = ~clean_subject.isin(["", "nan", "none"])

        raw_labels = df[source["label_col"]]
        unmapped = set(raw_labels.dropna().unique()) - set(source["label_map"])
        if unmapped:
            raise ValueError(
                f"{source['name']}: unexpected label values {sorted(unmapped)}"
            )

        frame = pd.DataFrame(
            {
                "text": text,
                "label": raw_labels.map(source["label_map"]).astype("Int64"),
                "source": source["name"],
                "priority": source["priority"],
                "has_subject": has_subject.to_numpy(),
            }
        )

        report[source["name"]] = {"found": found}
        frames.append(frame)

    return pd.concat(frames, ignore_index=True)


def drop_invalid(df, report):
    before = len(df)

    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)

    stripped = df["text"].str.strip()
    df = df[stripped != ""].copy()

    df["word_count"] = df["text"].str.split().str.len().fillna(0).astype(int)
    df = df[df["word_count"] >= MIN_WORDS].copy()

    # Must contain some actual letters, not only digits and symbols.
    df = df[df["text"].str.contains(r"[A-Za-z]{3,}", regex=True, na=False)].copy()

    artefact = pd.Series(False, index=df.index)
    for pattern in ARTEFACT_PATTERNS:
        artefact |= df["text"].str.contains(pattern, case=False, regex=False, na=False)
    df = df[~artefact].copy()

    report["invalid_removed"] = before - len(df)
    return df


def deduplicate(df, report):
    before = len(df)

    df["_norm"] = df["text"].map(normalise_for_key)
    df["_exact"] = df["_norm"].map(hash_key)
    df["_near"] = df["_norm"].str[:NEAR_DUP_PREFIX].map(hash_key)

    # Lower priority number wins, so specialised corpora keep their copy.
    df = df.sort_values(["priority", "word_count"], ascending=[True, False])

    df = df.drop_duplicates(subset="_exact", keep="first")
    after_exact = len(df)

    df = df.drop_duplicates(subset="_near", keep="first")
    after_near = len(df)

    report["duplicates_exact"] = before - after_exact
    report["duplicates_near"] = after_exact - after_near
    report["duplicates_total"] = before - after_near

    return df.drop(columns=["_norm", "_exact", "_near"])


def sample_balanced(df, report):
    df = df.copy()
    df["tier"] = quality_tier(df)

    per_class = TARGET_ROWS // 2
    picked = []

    for label in (1, 0):
        pool = df[df["label"] == label]
        available = pool.groupby("source").size().to_dict()
        allocation = allocate(min(per_class, len(pool)), available)

        for source, take in allocation.items():
            if take <= 0:
                continue
            stratum = pool[pool["source"] == source].sample(
                frac=1.0, random_state=RANDOM_SEED
            )
            # Best-quality tiers first, shuffled inside each tier so we are not
            # simply taking the longest or the first rows.
            stratum = stratum.sort_values("tier", kind="stable")
            picked.append(stratum.head(take))

        report.setdefault("allocation", {})[label] = allocation

    return pd.concat(picked, ignore_index=True)


def main():
    if not os.path.isdir(RAW_DIR):
        sys.exit(f"data/raw not found at {RAW_DIR}")

    report = {}

    print("=" * 72)
    print("STEP 1  Loading source datasets")
    print("=" * 72)
    combined = load_sources(report)
    print(f"  loaded {len(combined):,} rows from {len(report)} datasets")

    # Count the derived file for the audit trail without merging it.
    derived_path = os.path.join(RAW_DIR, DERIVED_SOURCE["file"])
    if os.path.exists(derived_path):
        derived_rows = sum(1 for _ in open(derived_path, encoding="utf-8", errors="ignore")) - 1
        report["derived_rows"] = derived_rows

    print()
    print("=" * 72)
    print("STEP 2  Removing invalid and unusable records")
    print("=" * 72)
    usable_before = combined.groupby("source").size().to_dict()
    combined = drop_invalid(combined, report)
    usable_after = combined.groupby("source").size().to_dict()
    for name in report:
        if isinstance(report[name], dict) and "found" in report[name]:
            report[name]["usable"] = usable_after.get(name, 0)
    print(f"  removed {report['invalid_removed']:,} invalid or unusable rows")

    print()
    print("=" * 72)
    print("STEP 3  Removing duplicates")
    print("=" * 72)
    combined = deduplicate(combined, report)
    print(f"  exact duplicates removed : {report['duplicates_exact']:,}")
    print(f"  near duplicates removed  : {report['duplicates_near']:,}")
    print(f"  pool after deduplication : {len(combined):,}")

    report["pool_phishing"] = int((combined["label"] == 1).sum())
    report["pool_legitimate"] = int((combined["label"] == 0).sum())

    print()
    print("=" * 72)
    print("STEP 4  Sampling a balanced subset")
    print("=" * 72)
    final = sample_balanced(combined, report)
    final = final.sample(frac=1.0, random_state=RANDOM_SEED).reset_index(drop=True)
    print(f"  selected {len(final):,} rows")

    out = final[["text", "label"]]
    out.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")

    report["final"] = final
    report["output_path"] = OUTPUT_PATH
    print_summary(report, usable_before)

    return report


def print_summary(report, usable_before):
    final = report["final"]

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print()
    print(f"{'Dataset':<18}{'Found':>10}{'Usable':>10}{'Kept':>10}{'Phish':>9}{'Legit':>9}")
    print("-" * 72)

    kept = final.groupby("source").size().to_dict()
    kept_phish = final[final["label"] == 1].groupby("source").size().to_dict()
    kept_legit = final[final["label"] == 0].groupby("source").size().to_dict()

    total_found = 0
    for source in SOURCES:
        name = source["name"]
        if name not in report:
            continue
        found = report[name]["found"]
        usable = report[name].get("usable", 0)
        total_found += found
        print(
            f"{name:<18}{found:>10,}{usable:>10,}{kept.get(name, 0):>10,}"
            f"{kept_phish.get(name, 0):>9,}{kept_legit.get(name, 0):>9,}"
        )

    if "derived_rows" in report:
        print(
            f"{DERIVED_SOURCE['name']:<18}{report['derived_rows']:>10,}"
            f"{'excluded':>10}{0:>10,}{'-':>9}{'-':>9}"
        )

    print("-" * 72)
    print(f"{'TOTAL (6 sources)':<18}{total_found:>10,}{'':>10}{len(final):>10,}")

    print()
    print("Record accounting")
    print(f"  invalid / empty records removed : {report['invalid_removed']:,}")
    print(f"  exact duplicates removed        : {report['duplicates_exact']:,}")
    print(f"  near duplicates removed         : {report['duplicates_near']:,}")
    print(f"  total duplicates removed        : {report['duplicates_total']:,}")

    print()
    print("Pool available after cleaning")
    print(f"  phishing   : {report['pool_phishing']:,}")
    print(f"  legitimate : {report['pool_legitimate']:,}")

    phishing = int((final["label"] == 1).sum())
    legitimate = int((final["label"] == 0).sum())

    print()
    print("Final dataset")
    print(f"  phishing records   (label 1) : {phishing:,}")
    print(f"  legitimate records (label 0) : {legitimate:,}")
    print(f"  final record count           : {len(final):,}")
    print(
        f"  class distribution           : "
        f"{phishing / len(final):.1%} phishing / {legitimate / len(final):.1%} legitimate"
    )

    words = final["text"].str.split().str.len()
    print()
    print("Text length (words)")
    print(
        f"  min {int(words.min())}  median {int(words.median())}  "
        f"mean {int(words.mean())}  p95 {int(words.quantile(.95))}  max {int(words.max())}"
    )

    print()
    print(f"Written to: {report['output_path']}")


if __name__ == "__main__":
    main()
