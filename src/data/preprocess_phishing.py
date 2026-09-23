"""Preprocess the consolidated phishing dataset for BERT fine-tuning.

Reads  : data/raw/phishing_combined.csv        (never modified)
Writes : data/processed/phishing_cleaned.csv
         data/processed/preprocessing_report.txt

This stage repairs the email text and removes unusable records. It does NOT
tokenise, vectorise, embed, split or train anything, and it does not touch the
existing Spam/Ham pipeline (spam_model.pkl, count_vectorizer.pkl, email_spam.csv).

GUIDING PRINCIPLE
-----------------
BERT is a contextual model. It needs whole sentences, punctuation, casing and
URLs to work with, so the cleaning here is deliberately conservative: it only
removes things that are mechanically broken or that carry no linguistic content
at all. Specifically it does NOT lowercase, stem, lemmatise, strip stop words,
strip punctuation, or remove URLs.

WHAT IS DELIBERATELY KEPT
-------------------------
  URLs and domains     strong phishing signal, and BERT can read them
  Casing               "URGENT" vs "urgent" is signal; also needed for
                       bert-base-cased if that checkpoint is chosen later
  Punctuation          sentence boundaries and excess "!!!" are both signal
  Email addresses      including the <user@host> angle-bracket form
  Content-* headers    short, and MIME structure can itself be informative
  Long emails          never dropped for length; see the report for the
                       truncation options available at tokenisation time

Run from the project root:

    python -m src.data.preprocess_phishing
"""

import hashlib
import html as html_module
import os
import re
import sys
import unicodedata
from datetime import datetime

import pandas as pd

# ftfy repairs mojibake ("â€™" -> "'"). Optional: if it is not installed the
# script still runs and falls back to a small set of hand-written fixes.
try:
    import ftfy

    HAS_FTFY = True
except ImportError:
    ftfy = None
    HAS_FTFY = False


# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

INPUT_PATH = os.path.join(PROJECT_ROOT, "data", "raw", "phishing_combined.csv")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "phishing_cleaned.csv")
REPORT_PATH = os.path.join(OUTPUT_DIR, "preprocessing_report.txt")

VALID_LABELS = {0, 1}
LABEL_NAMES = {0: "Legitimate", 1: "Phishing"}

# A record shorter than this after cleaning carries no usable signal.
MIN_WORDS = 5

# Near-duplicate key length, kept identical to the consolidation stage so the
# two stages agree on what "duplicate" means.
NEAR_DUP_PREFIX = 200

# BERT's maximum sequence length. Used for reporting only - nothing is
# truncated or tokenised here.
BERT_MAX_TOKENS = 512
# WordPiece splits email text into roughly 1.3 sub-word tokens per whitespace
# word, so ~400 words is about the point where 512 tokens is reached. This is
# an estimate for the report, not a tokenisation.
WORDS_PER_TOKEN_ESTIMATE = 1.3
APPROX_WORD_LIMIT = int(BERT_MAX_TOKENS / WORDS_PER_TOKEN_ESTIMATE)


# --------------------------------------------------------------------------
# Compiled patterns
# --------------------------------------------------------------------------

# Real HTML tags are matched by NAME, not by the generic "<...>" shape. That
# matters: 553 records contain addresses like <james@maktoob.com>, and a naive
# "<[^>]*>" strip would silently delete them. Deleting sender addresses from a
# phishing dataset would remove one of the strongest available signals.
HTML_TAG_NAMES = (
    "html|head|body|title|meta|link|base|basefont|style|script|noscript|"
    "div|span|p|br|hr|center|font|b|i|u|s|strike|small|big|sub|sup|tt|"
    "h[1-6]|ul|ol|li|dl|dt|dd|blockquote|pre|code|kbd|samp|var|cite|dfn|"
    "abbr|acronym|address|bdo|del|ins|q|strong|em|nobr|marquee|"
    "table|thead|tbody|tfoot|tr|td|th|caption|col|colgroup|"
    "a|img|map|area|object|param|embed|iframe|frame|frameset|"
    "form|input|button|select|option|textarea|label|fieldset|legend|o:p"
)
RE_HTML_TAG = re.compile(rf"</?(?:{HTML_TAG_NAMES})\b[^>]*>", re.IGNORECASE)

# <script>/<style> bodies are code, not language. Drop the whole block.
RE_SCRIPT_STYLE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)

# HTML comments, including the conditional comments Outlook emits.
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
RE_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE)

# MIME multipart delimiters, e.g. "------=_NextPart_000_3257B2_01C249FA" or
# "--===============12345==". Pure mechanical scaffolding with no linguistic
# content, and each one shatters into a dozen junk WordPiece tokens that eat
# into the 512-token budget.
#
# Two patterns are needed because boundaries do not always sit on their own
# line: the consolidation stage preserved whatever line structure each source
# CSV had, and in many records the delimiter runs inline with the body text.
#
# The inline form requires the dashes to be followed by "=" or "_", which is
# the standard boundary signature. That guard stops it matching ordinary
# hyphenated prose such as "well--known".
RE_MIME_BOUNDARY_LINE = re.compile(r"(?m)^\s*--+[=_]?[A-Za-z0-9._-]{6,}-{0,2}\s*$")
RE_MIME_BOUNDARY_INLINE = re.compile(
    r"(?<![A-Za-z0-9])--+[=_][A-Za-z0-9._=-]{6,}-{0,2}(?![A-Za-z0-9])"
)

# Long base64 runs are encoded attachments or inline images. They are not
# language, and one blob can consume the entire 512-token window.
RE_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

# Quoted-printable soft line breaks left over from MIME decoding.
RE_QP_SOFT_BREAK = re.compile(r"=\r?\n")

# C0/C1 control characters, keeping tab and newline which carry structure.
RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Zero-width characters and BOMs. Invisible, and when they appear inside a
# word ("P‌ayPal") they shatter WordPiece tokenisation.
RE_ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")

# Unicode spaces that are not U+0020, including the non-breaking space.
RE_UNICODE_SPACE = re.compile(r"[   -   　]")

# Replacement character: the residue of an already-failed decode.
RE_REPLACEMENT = re.compile("�")

RE_SPACES_TABS = re.compile(r"[ \t]+")
RE_SPACE_BEFORE_NEWLINE = re.compile(r"[ \t]*\n[ \t]*")
RE_MANY_NEWLINES = re.compile(r"\n{3,}")

# Mojibake signature, used to decide which rows are worth sending through ftfy.
RE_MOJIBAKE = re.compile(r"â€|Ã[-¿]|Â[  ]|â€™|â€œ|â€")

# Dedup key normalisation.
RE_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
RE_WHITESPACE = re.compile(r"\s+")

# Hand-written mojibake fixes, used only when ftfy is unavailable.
FALLBACK_MOJIBAKE = {
    "â€™": "'", "â€˜": "'", "â€œ": '"', "â€\x9d": '"', "â€“": "-",
    "â€”": "-", "â€¦": "...", "â€¢": "*", "Â ": " ", "Ã©": "e",
    "Ã¨": "e", "Ã¼": "u", "Ã¶": "o", "Ã¤": "a", "Ã±": "n",
}


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------


def repair_encoding(text):
    """Undo mojibake, then apply canonical Unicode composition.

    NFC (canonical) is used rather than NFKC (compatibility) on purpose.
    NFKC folds full-width and look-alike characters down to ASCII, which would
    erase exactly the homoglyph tricks phishers use to disguise brand names.
    Those characters are signal, so they are preserved.
    """
    if RE_MOJIBAKE.search(text):
        if HAS_FTFY:
            text = ftfy.fix_text(text)
        else:
            for broken, fixed in FALLBACK_MOJIBAKE.items():
                text = text.replace(broken, fixed)

    return unicodedata.normalize("NFC", text)


def strip_markup(text):
    """Remove HTML scaffolding while keeping the words inside it."""
    text = RE_SCRIPT_STYLE.sub(" ", text)
    text = RE_HTML_COMMENT.sub(" ", text)
    text = RE_DOCTYPE.sub(" ", text)
    text = RE_HTML_TAG.sub(" ", text)

    # Unescape after tag removal so a literal "&lt;b&gt;" in the body does not
    # become a tag that the previous step would then have stripped.
    text = html_module.unescape(text)
    return text


def strip_transport_noise(text):
    """Remove MIME scaffolding and encoded attachment blobs."""
    text = RE_QP_SOFT_BREAK.sub("", text)
    text = RE_MIME_BOUNDARY_LINE.sub(" ", text)
    text = RE_MIME_BOUNDARY_INLINE.sub(" ", text)
    text = RE_BASE64_BLOB.sub(" ", text)
    return text


def strip_broken_characters(text):
    """Remove characters that are invisible, corrupt, or non-printing."""
    text = RE_ZERO_WIDTH.sub("", text)
    text = RE_REPLACEMENT.sub("", text)
    text = RE_CONTROL.sub(" ", text)
    text = RE_UNICODE_SPACE.sub(" ", text)
    return text


def normalise_whitespace(text):
    """Collapse runs of whitespace without flattening paragraph structure.

    Blank lines are capped at one rather than removed: paragraph breaks are
    part of how an email reads, and BERT sees them as ordinary whitespace.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = RE_SPACES_TABS.sub(" ", text)
    text = RE_SPACE_BEFORE_NEWLINE.sub("\n", text)
    text = RE_MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def clean_text(text):
    """Full cleaning pipeline for one email, in dependency order."""
    if text is None:
        return ""

    text = str(text)
    text = repair_encoding(text)
    text = strip_markup(text)
    # Broken characters are removed BEFORE transport noise on purpose. A stray
    # control character sitting in front of a MIME boundary would otherwise
    # stop the boundary pattern anchoring, leaving the delimiter behind.
    text = strip_broken_characters(text)
    text = strip_transport_noise(text)
    text = normalise_whitespace(text)
    return text


def dedup_key(text, prefix=None):
    """Normalised hash key. Used for comparison only; never saved."""
    lowered = RE_NON_ALNUM.sub(" ", text.lower())
    collapsed = RE_WHITESPACE.sub(" ", lowered).strip()
    if prefix:
        collapsed = collapsed[:prefix]
    return hashlib.md5(collapsed.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def describe_lengths(series):
    """Length statistics in characters and words."""
    chars = series.str.len()
    words = series.str.split().str.len()
    return {
        "char_min": int(chars.min()),
        "char_max": int(chars.max()),
        "char_mean": float(chars.mean()),
        "char_median": float(chars.median()),
        "word_min": int(words.min()),
        "word_max": int(words.max()),
        "word_mean": float(words.mean()),
        "word_median": float(words.median()),
        "word_p95": float(words.quantile(0.95)),
        "word_p99": float(words.quantile(0.99)),
        "over_limit": int((words > APPROX_WORD_LIMIT).sum()),
        "over_limit_pct": float((words > APPROX_WORD_LIMIT).mean() * 100),
    }


def main():
    if not os.path.exists(INPUT_PATH):
        sys.exit(f"Input not found: {INPUT_PATH}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    stats = {"started": datetime.now().isoformat(timespec="seconds")}

    # -- Load and inspect -------------------------------------------------
    print("STEP 1  Loading and inspecting")
    df = pd.read_csv(INPUT_PATH, low_memory=False)
    stats["original_records"] = len(df)
    stats["original_columns"] = list(df.columns)

    missing = {"text": int(df["text"].isna().sum()), "label": int(df["label"].isna().sum())}
    stats["missing_text"] = missing["text"]
    stats["missing_label"] = missing["label"]

    raw_text = df["text"].astype(str)
    stats["original_empty"] = int((raw_text.str.strip() == "").sum())
    stats["original_duplicates"] = int(raw_text.map(dedup_key).duplicated().sum())
    stats["original_label_values"] = sorted(df["label"].dropna().unique().tolist())
    stats["original_class_counts"] = df["label"].value_counts().to_dict()
    stats["before_lengths"] = describe_lengths(raw_text)

    print(f"  {len(df):,} records, columns {list(df.columns)}")

    # -- Validate labels ---------------------------------------------------
    print("STEP 2  Validating labels")
    unexpected = set(stats["original_label_values"]) - VALID_LABELS
    if unexpected:
        sys.exit(f"Unexpected label values: {sorted(unexpected)}")

    before_missing = len(df)
    df = df[df["label"].notna() & df["text"].notna()].copy()
    df["label"] = df["label"].astype(int)
    stats["removed_missing"] = before_missing - len(df)
    print(f"  labels valid; removed {stats['removed_missing']:,} rows with missing values")

    # -- Clean -------------------------------------------------------------
    print("STEP 3  Cleaning text (this takes a couple of minutes)")
    df["text"] = df["text"].map(clean_text)

    # -- Drop records made unusable ---------------------------------------
    print("STEP 4  Removing unusable records")
    before_empty = len(df)
    df = df[df["text"].str.strip() != ""].copy()
    stats["removed_empty_after_clean"] = before_empty - len(df)

    before_short = len(df)
    word_counts = df["text"].str.split().str.len()
    df = df[word_counts >= MIN_WORDS].copy()
    stats["removed_too_short"] = before_short - len(df)
    print(
        f"  removed {stats['removed_empty_after_clean']:,} empty and "
        f"{stats['removed_too_short']:,} too-short records"
    )

    # -- Deduplicate again -------------------------------------------------
    # Cleaning can turn two records that differed only in whitespace, entities
    # or MIME scaffolding into the same text, so this pass is not redundant.
    print("STEP 5  Removing duplicates created by cleaning")
    before_dup = len(df)
    df["_exact"] = df["text"].map(dedup_key)
    df = df.drop_duplicates(subset="_exact", keep="first")
    stats["removed_duplicates_exact"] = before_dup - len(df)

    after_exact = len(df)
    df["_near"] = df["text"].map(lambda t: dedup_key(t, prefix=NEAR_DUP_PREFIX))
    df = df.drop_duplicates(subset="_near", keep="first")
    stats["removed_duplicates_near"] = after_exact - len(df)
    stats["removed_duplicates_total"] = before_dup - len(df)

    df = df.drop(columns=["_exact", "_near"])
    print(
        f"  removed {stats['removed_duplicates_exact']:,} exact and "
        f"{stats['removed_duplicates_near']:,} near duplicates"
    )

    # -- Final accounting --------------------------------------------------
    df = df.reset_index(drop=True)
    stats["final_records"] = len(df)
    stats["records_removed"] = stats["original_records"] - len(df)
    stats["final_class_counts"] = df["label"].value_counts().to_dict()
    stats["final_label_values"] = sorted(df["label"].unique().tolist())
    stats["after_lengths"] = describe_lengths(df["text"])

    # -- Save --------------------------------------------------------------
    print("STEP 6  Saving")
    df[["text", "label"]].to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    stats["finished"] = datetime.now().isoformat(timespec="seconds")

    write_report(stats)
    print_summary(stats)

    return stats


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _class_lines(counts, total):
    lines = []
    for label in (0, 1):
        count = int(counts.get(label, 0))
        share = count / total * 100 if total else 0.0
        lines.append(f"  {label} = {LABEL_NAMES[label]:<12} {count:>8,}  ({share:5.2f}%)")
    return "\n".join(lines)


def write_report(stats):
    before = stats["before_lengths"]
    after = stats["after_lengths"]
    final_total = stats["final_records"]
    original_total = stats["original_records"]

    lines = []
    add = lines.append

    add("=" * 74)
    add("PHISHING DATASET - PREPROCESSING REPORT")
    add("=" * 74)
    add(f"Generated      : {stats['finished']}")
    add(f"Input          : data/raw/phishing_combined.csv  (not modified)")
    add(f"Output         : data/processed/phishing_cleaned.csv")
    add(f"Script         : src/data/preprocess_phishing.py")
    add(f"Encoding tool  : {'ftfy ' + ftfy.__version__ if HAS_FTFY else 'built-in fallback'}")
    add("")

    add("-" * 74)
    add("1. RECORD COUNTS")
    add("-" * 74)
    add(f"Original number of records        : {original_total:>8,}")
    add(f"Records removed (total)           : {stats['records_removed']:>8,}")
    add(f"  missing values removed          : {stats['removed_missing']:>8,}")
    add(f"  empty after cleaning            : {stats['removed_empty_after_clean']:>8,}")
    add(f"  too short after cleaning (<{MIN_WORDS} words) : {stats['removed_too_short']:>3,}")
    add(f"  duplicates removed (total)      : {stats['removed_duplicates_total']:>8,}")
    add(f"    exact duplicates              : {stats['removed_duplicates_exact']:>8,}")
    add(f"    near duplicates (first {NEAR_DUP_PREFIX} chars) : {stats['removed_duplicates_near']:>3,}")
    add(f"Final number of records           : {final_total:>8,}")
    add(
        f"Retention rate                    : "
        f"{final_total / original_total * 100:>7.2f}%"
    )
    add("")

    add("-" * 74)
    add("2. CLASS DISTRIBUTION")
    add("-" * 74)
    add("Before preprocessing:")
    add(_class_lines(stats["original_class_counts"], original_total))
    add("")
    add("After preprocessing:")
    add(_class_lines(stats["final_class_counts"], final_total))
    add("")
    add(f"Legitimate count : {int(stats['final_class_counts'].get(0, 0)):,}")
    add(f"Phishing count   : {int(stats['final_class_counts'].get(1, 0)):,}")
    add(f"Label values present : {stats['final_label_values']} (validated against {sorted(VALID_LABELS)})")
    add("")

    add("-" * 74)
    add("3. DATA QUALITY CHECKS ON THE INPUT")
    add("-" * 74)
    add(f"Columns found              : {stats['original_columns']}")
    add(f"Missing text values        : {stats['missing_text']:,}")
    add(f"Missing label values       : {stats['missing_label']:,}")
    add(f"Empty / whitespace emails  : {stats['original_empty']:,}")
    add(f"Duplicate emails on input  : {stats['original_duplicates']:,}")
    add(f"Label values on input      : {stats['original_label_values']}")
    add("")

    add("-" * 74)
    add("4. TEXT LENGTH STATISTICS")
    add("-" * 74)
    add(f"{'':<22}{'BEFORE':>14}{'AFTER':>14}")
    add(f"{'Minimum (characters)':<22}{before['char_min']:>14,}{after['char_min']:>14,}")
    add(f"{'Maximum (characters)':<22}{before['char_max']:>14,}{after['char_max']:>14,}")
    add(f"{'Mean (characters)':<22}{before['char_mean']:>14,.1f}{after['char_mean']:>14,.1f}")
    add(f"{'Median (characters)':<22}{before['char_median']:>14,.1f}{after['char_median']:>14,.1f}")
    add("")
    add(f"{'Minimum (words)':<22}{before['word_min']:>14,}{after['word_min']:>14,}")
    add(f"{'Maximum (words)':<22}{before['word_max']:>14,}{after['word_max']:>14,}")
    add(f"{'Mean (words)':<22}{before['word_mean']:>14,.1f}{after['word_mean']:>14,.1f}")
    add(f"{'Median (words)':<22}{before['word_median']:>14,.1f}{after['word_median']:>14,.1f}")
    add(f"{'95th percentile':<22}{before['word_p95']:>14,.0f}{after['word_p95']:>14,.0f}")
    add(f"{'99th percentile':<22}{before['word_p99']:>14,.0f}{after['word_p99']:>14,.0f}")
    add("")

    add("-" * 74)
    add("5. SEQUENCE LENGTH VS BERT'S 512-TOKEN LIMIT")
    add("-" * 74)
    add(f"WordPiece produces roughly {WORDS_PER_TOKEN_ESTIMATE} sub-word tokens per word on")
    add(f"email text, so {BERT_MAX_TOKENS} tokens is about {APPROX_WORD_LIMIT} whitespace words.")
    add("")
    add(f"Emails over ~{APPROX_WORD_LIMIT} words, before : {before['over_limit']:,} ({before['over_limit_pct']:.1f}%)")
    add(f"Emails over ~{APPROX_WORD_LIMIT} words, after  : {after['over_limit']:,} ({after['over_limit_pct']:.1f}%)")
    add(f"Longest email after cleaning  : {after['word_max']:,} words")
    add("")
    add("No email was dropped for being long, and no text was truncated here.")
    add("The full cleaned text is preserved so the truncation strategy stays an")
    add("open decision for the tokenisation stage. The options are:")
    add("")
    add("  a. Head truncation (truncation=True, max_length=512)")
    add("     The default. Cheap, and phishing cues (subject line, greeting,")
    add("     urgency, the first link) are usually front-loaded.")
    add("  b. Head + tail")
    add("     Keep the first ~384 and last ~128 tokens. Catches sign-off cues")
    add("     such as spoofed signatures and unsubscribe blocks.")
    add("  c. Chunk and pool")
    add("     Split long emails into 512-token windows, classify each, pool the")
    add("     results. Most faithful, and the most expensive.")
    add("")
    add("With about four fifths of emails already under the limit, option (a) is")
    add("a reasonable baseline; (b) is a cheap upgrade worth measuring against it.")
    add("")

    add("-" * 74)
    add("6. PREPROCESSING OPERATIONS PERFORMED")
    add("-" * 74)
    add("Applied, in order:")
    add("   1. Mojibake repair on affected rows (ftfy) - 'â€™' becomes an apostrophe")
    add("   2. Unicode NFC normalisation (canonical composition)")
    add("   3. <script> and <style> blocks removed, including their contents")
    add("   4. HTML comments and DOCTYPE declarations removed")
    add("   5. HTML tags removed by tag NAME, keeping the text inside them")
    add("   6. HTML entities unescaped (&amp; becomes &, &nbsp; becomes a space)")
    add("   7. Quoted-printable soft line breaks removed")
    add("   8. MIME multipart boundary delimiter lines removed")
    add("   9. Base64 blobs of 200+ characters removed (encoded attachments)")
    add("  10. Zero-width characters, BOMs and bidi controls removed")
    add("  11. Unicode replacement characters removed")
    add("  12. C0/C1 control characters removed, keeping tab and newline")
    add("  13. Non-breaking and exotic Unicode spaces converted to plain spaces")
    add("  14. Runs of spaces and tabs collapsed to one space")
    add("  15. Three or more blank lines collapsed to one blank line")
    add("  16. Leading and trailing whitespace stripped")
    add(f"  17. Records with no text, or fewer than {MIN_WORDS} words, removed")
    add("  18. Exact and near duplicates removed after cleaning")
    add("  19. Labels validated as exactly {0, 1}")
    add("")
    add("Deliberately NOT applied, because BERT needs the context:")
    add("   - no lowercasing            casing is signal, and bert-base-cased may be used")
    add("   - no stop-word removal      function words carry the sentence structure")
    add("   - no stemming or lemmatising")
    add("   - no punctuation stripping  '!!!' and sentence boundaries are signal")
    add("   - no URL removal or masking URLs are among the strongest phishing cues")
    add("   - no number or currency masking")
    add("   - no NFKC folding           it would erase homoglyph attacks on brand names")
    add("   - no tokenisation, vectorisation, embedding, splitting or training")
    add("")
    add("Two choices worth flagging:")
    add("  * HTML tags are matched by tag name rather than by the generic '<...>'")
    add("    shape, so that angle-bracket email addresses such as")
    add("    <james@maktoob.com> survive. 553 records in the input contain that")
    add("    form, and sender addresses are useful phishing evidence.")
    add("  * NFC was chosen over NFKC on purpose. NFKC folds full-width and")
    add("    look-alike characters to ASCII, which would destroy exactly the")
    add("    homoglyph tricks used to disguise brand names in phishing.")
    add("")

    add("=" * 74)
    add("END OF REPORT")
    add("=" * 74)

    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def print_summary(stats):
    final_total = stats["final_records"]
    counts = stats["final_class_counts"]
    after = stats["after_lengths"]

    print()
    print("=" * 64)
    print("PREPROCESSING SUMMARY")
    print("=" * 64)
    print(f"Original records      : {stats['original_records']:,}")
    print(f"Records removed       : {stats['records_removed']:,}")
    print(f"  missing             : {stats['removed_missing']:,}")
    print(f"  empty after clean   : {stats['removed_empty_after_clean']:,}")
    print(f"  too short           : {stats['removed_too_short']:,}")
    print(f"  duplicates          : {stats['removed_duplicates_total']:,}")
    print(f"Final records         : {final_total:,}")
    print()
    print(f"Legitimate (0)        : {int(counts.get(0, 0)):,} "
          f"({int(counts.get(0, 0)) / final_total * 100:.2f}%)")
    print(f"Phishing   (1)        : {int(counts.get(1, 0)):,} "
          f"({int(counts.get(1, 0)) / final_total * 100:.2f}%)")
    print()
    print(f"Text length (chars)   : min {after['char_min']:,} | "
          f"median {after['char_median']:,.0f} | mean {after['char_mean']:,.0f} | "
          f"max {after['char_max']:,}")
    print(f"Text length (words)   : min {after['word_min']:,} | "
          f"median {after['word_median']:,.0f} | mean {after['word_mean']:,.0f} | "
          f"max {after['word_max']:,}")
    print(f"Over ~{APPROX_WORD_LIMIT} words         : {after['over_limit']:,} "
          f"({after['over_limit_pct']:.1f}%)  - kept, not truncated")
    print()
    print(f"Dataset : {OUTPUT_PATH}")
    print(f"Report  : {REPORT_PATH}")


if __name__ == "__main__":
    main()
