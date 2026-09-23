"""One-shot restructure: move backend code under backend/.

    src/      ->  backend/src/
    tests/    ->  backend/tests/
    requirements.txt -> backend/requirements.txt  (backend deps only)

and then repair everything the move breaks:

  * imports          from src.x        ->  from backend.src.x
  * project root     brittle "../.." arithmetic -> marker-based lookup
  * requirements     split into backend deps

WHY A SCRIPT RATHER THAN HAND EDITS
-----------------------------------
Moving a package changes the import path of every module in it and the depth
of every relative path calculation inside it. Doing that by hand across ~20
files is where restructures usually break. This does it uniformly and can be
re-run safely.

SAFETY
------
  * dry run by default - shows the plan, changes nothing
  * refuses to run on a dirty git tree unless --force
  * uses `git mv` when available so history is preserved
  * idempotent - a second run detects the work is already done

USAGE
-----
    python scripts/restructure_to_backend.py            # preview
    python scripts/restructure_to_backend.py --apply    # do it

Afterwards:
    python -m pytest backend/tests -q
    python -m backend.src.main
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"

# --------------------------------------------------------------------------
# What goes where, and why
# --------------------------------------------------------------------------
#
# backend/  = application runtime. Everything reachable from the FastAPI app.
# scripts/  = dataset preparation, training, evaluation and CLI utilities.
#
# The dependency direction is one-way: scripts may import backend, backend
# never imports scripts. That is why src/data/preprocess.py is classified as
# BACKEND despite living under data/ - api/text_cleaning.py imports clean_text
# from it on every request, so it is runtime code. It is renamed to
# backend/src/preprocessing.py to make that unambiguous.

# (source, destination) relative to the project root. Explicit per file rather
# than moving whole directories, because the runtime/pipeline split does not
# follow the existing folder boundaries.
FILE_MOVES = [
    # ---- backend runtime ----
    ("src/main.py", "backend/src/main.py"),
    ("src/api/app.py", "backend/src/api/app.py"),
    ("src/api/schemas.py", "backend/src/api/schemas.py"),
    ("src/api/text_cleaning.py", "backend/src/api/text_cleaning.py"),
    ("src/services/email_threat_service.py",
     "backend/src/services/email_threat_service.py"),
    ("src/models/spam_detector.py", "backend/src/models/spam_detector.py"),
    ("src/models/phishing_detector.py", "backend/src/models/phishing_detector.py"),
    ("src/storage/message_store.py", "backend/src/storage/message_store.py"),
    ("src/quarantine/store.py", "backend/src/quarantine/store.py"),
    # Runtime text cleaner, renamed out of data/ to stop it reading as a script.
    ("src/data/preprocess.py", "backend/src/preprocessing.py"),

    # ---- tests ----
    ("tests/conftest.py", "backend/tests/conftest.py"),
    ("tests/test_api.py", "backend/tests/test_api.py"),
    ("tests/test_message_store.py", "backend/tests/test_message_store.py"),

    # ---- ML pipeline: phishing ----
    ("src/data/build_phishing_dataset.py", "scripts/build_phishing_dataset.py"),
    ("src/data/preprocess_phishing.py", "scripts/preprocess_phishing.py"),
    ("src/models/train_phishing_bert.py", "scripts/train_phishing_bert.py"),
    ("src/models/predict_phishing.py", "scripts/predict_phishing.py"),

    # ---- ML pipeline: spam. Renamed, because "train.py" and "predict.py"
    #      are ambiguous once both pipelines share one directory. ----
    ("src/data/process_dataset.py", "scripts/process_spam_dataset.py"),
    ("src/data/load_data.py", "scripts/load_data.py"),
    ("src/features/vectorizer.py", "scripts/build_spam_vectorizer.py"),
    ("src/models/build_model.py", "scripts/build_spam_model.py"),
    ("src/models/train.py", "scripts/train_spam_model.py"),
    ("src/models/evaluate.py", "scripts/evaluate_spam_model.py"),
    ("src/models/predict.py", "scripts/predict_spam_cli.py"),

    # Root main.py only calls process_dataset(). It is a dataset builder, not
    # an application entry point - and leaving it named main.py alongside the
    # real entry point at backend/src/main.py would be actively misleading.
    ("main.py", "scripts/build_spam_dataset.py"),
]

# Files deleted rather than moved.
#
# src/api/.gitignore duplicates four rules already in the root .gitignore
# (.venv/, __pycache__/, *.pyc, .env) and adds a fifth - "quarantine/" - that
# targets src/api/quarantine/, a directory that has never existed. Quarantine
# data lives in data/quarantine/. Carrying it into backend/ would preserve
# dead configuration, so it is removed.
FILE_DELETES = [
    "src/api/.gitignore",
]

# Old module path -> new module path. Applied longest-first so that
# src.data.preprocess is rewritten before src.data.
IMPORT_MAP = {
    "src.api.app": "backend.src.api.app",
    "src.api.schemas": "backend.src.api.schemas",
    "src.api.text_cleaning": "backend.src.api.text_cleaning",
    "src.services.email_threat_service": "backend.src.services.email_threat_service",
    "src.services": "backend.src.services",
    "src.models.spam_detector": "backend.src.models.spam_detector",
    "src.models.phishing_detector": "backend.src.models.phishing_detector",
    "src.storage.message_store": "backend.src.storage.message_store",
    "src.storage": "backend.src.storage",
    "src.quarantine.store": "backend.src.quarantine.store",
    "src.quarantine": "backend.src.quarantine",

    # runtime cleaner, renamed
    "src.data.preprocess": "backend.src.preprocessing",

    # pipeline scripts, renamed and relocated
    "src.data.process_dataset": "scripts.process_spam_dataset",
    "src.data.build_phishing_dataset": "scripts.build_phishing_dataset",
    "src.data.preprocess_phishing": "scripts.preprocess_phishing",
    "src.data.load_data": "scripts.load_data",
    "src.features.vectorizer": "scripts.build_spam_vectorizer",
    "src.models.build_model": "scripts.build_spam_model",
    "src.models.train": "scripts.train_spam_model",
    "src.models.evaluate": "scripts.evaluate_spam_model",
    "src.models.predict_phishing": "scripts.predict_phishing",
    "src.models.predict": "scripts.predict_spam_cli",
}

# Scripts are launched directly (python scripts/train_phishing_bert.py), so
# sys.path[0] is scripts/ rather than the project root and `import backend...`
# would fail. This prelude fixes that without requiring -m.
SCRIPT_BOOTSTRAP = '''import sys
from pathlib import Path

# Allow `python scripts/<name>.py` from anywhere: put the project root on the
# import path so `backend.*` and sibling scripts resolve.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
'''

# Backend runtime + test dependencies. Everything else in the old
# requirements.txt belongs to the ML training pipeline and stays at the root.
BACKEND_REQUIREMENTS = """# Backend runtime and test dependencies.
#
# The ML training pipeline has its own requirements at the project root
# (pandas, spacy, matplotlib, and so on). Only what the API actually imports
# at runtime is listed here.

# --- API ---
fastapi
uvicorn
pydantic

# --- spam detector: CountVectorizer + Naive Bayes ---
scikit-learn
joblib
numpy

# --- phishing detector: fine-tuned BERT ---
torch
transformers

# --- text cleaning used by the spam pipeline ---
spacy
regex

# --- tests ---
pytest
httpx
"""

# A single, depth-independent way to find the project root. Generated into
# backend/src/paths.py and imported by every module that needs a path.
PATHS_MODULE = '''"""Project path resolution.

Every module that needs models/, data/ or reports/ imports from here rather
than computing "../.." itself. Relative-depth arithmetic silently breaks the
moment a file moves; searching upward for known marker directories does not.
"""

from pathlib import Path

# Directories that only exist at the project root.
_MARKERS = ("models", "data")


def _find_project_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if all((candidate / marker).is_dir() for marker in _MARKERS):
            return candidate
    # Fall back to the repository layout: backend/src/paths.py -> root.
    return here.parents[2]


PROJECT_ROOT: Path = _find_project_root()

MODELS_DIR: Path = PROJECT_ROOT / "models"
DATA_DIR: Path = PROJECT_ROOT / "data"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"

SPAM_MODEL_PATH: Path = MODELS_DIR / "spam_model.pkl"
VECTORIZER_PATH: Path = MODELS_DIR / "count_vectorizer.pkl"
PHISHING_MODEL_DIR: Path = MODELS_DIR / "phishing_bert"

__all__ = [
    "PROJECT_ROOT", "MODELS_DIR", "DATA_DIR", "REPORTS_DIR",
    "SPAM_MODEL_PATH", "VECTORIZER_PATH", "PHISHING_MODEL_DIR",
]
'''

# The exact PROJECT_ROOT idiom used across the codebase today.
OLD_ROOT_PATTERNS = [
    re.compile(
        r'PROJECT_ROOT\s*=\s*os\.path\.abspath\(\s*os\.path\.join\('
        r'\s*os\.path\.dirname\(__file__\)\s*,\s*"\.\."\s*,\s*"\.\."\s*\)\s*\)'
    ),
    re.compile(
        r'PROJECT_ROOT\s*=\s*os\.path\.abspath\(\s*os\.path\.join\('
        r'\s*os\.path\.dirname\(__file__\)\s*,\s*"\.\."\s*\)\s*\)'
    ),
]

# Built from IMPORT_MAP, longest module path first so that a prefix never
# shadows a more specific entry.
IMPORT_PATTERNS = [
    (re.compile(rf'(?<![\w.]){re.escape(old)}(?![\w])'), new)
    for old, new in sorted(IMPORT_MAP.items(), key=lambda kv: -len(kv[0]))
]


def log(message):
    print(f"  {message}")


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=False,
    )


def git_available():
    return shutil.which("git") is not None and (PROJECT_ROOT / ".git").is_dir()


def tree_is_clean():
    if not git_available():
        return True
    result = git("status", "--porcelain")
    return result.returncode == 0 and not result.stdout.strip()


def already_restructured():
    return (BACKEND / "src" / "api" / "app.py").exists()


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def move_files(apply):
    backend_count = script_count = 0

    for source_rel, dest_rel in FILE_MOVES:
        source = PROJECT_ROOT / source_rel
        dest = PROJECT_ROOT / dest_rel

        if not source.exists():
            log(f"skip   {source_rel} (not present)")
            continue
        if dest.exists():
            log(f"skip   {source_rel} -> {dest_rel} (destination exists)")
            continue

        marker = "" if Path(source_rel).name == Path(dest_rel).name else "   [renamed]"
        log(f"move   {source_rel:<42} -> {dest_rel}{marker}")

        if dest_rel.startswith("backend/"):
            backend_count += 1
        else:
            script_count += 1

        if not apply:
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        if git_available():
            result = git("mv", source_rel, dest_rel)
            if result.returncode != 0:
                log(f"       git mv failed, falling back: {result.stderr.strip()}")
                shutil.move(str(source), str(dest))
        else:
            shutil.move(str(source), str(dest))

    log(f"       {backend_count} file(s) -> backend/, {script_count} -> scripts/")


def delete_files(apply):
    """Remove files that are redundant after the restructure."""
    for relative in FILE_DELETES:
        path = PROJECT_ROOT / relative
        if not path.exists():
            log(f"skip   {relative} (already gone)")
            continue

        log(f"DELETE {relative}   (redundant + stale rule)")
        if not apply:
            continue

        if git_available():
            result = git("rm", "-f", "--quiet", relative)
            if result.returncode != 0:
                path.unlink(missing_ok=True)
        else:
            path.unlink(missing_ok=True)


def remove_empty_source_dirs(apply):
    """Clean up src/ and tests/ once every file inside them has been relocated.

    In dry run the files have not moved yet, so anything the plan covers is
    subtracted before deciding what would genuinely be left behind.
    """
    planned = {source for source, _ in FILE_MOVES} | set(FILE_DELETES)

    for name in ("src", "tests"):
        directory = PROJECT_ROOT / name
        if not directory.exists():
            continue

        leftovers = [
            p for p in directory.rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.relative_to(PROJECT_ROOT).as_posix() not in planned
        ]
        if leftovers:
            log(f"keep   {directory.name}/ ({len(leftovers)} unmapped file(s) remain)")
            for path in leftovers[:10]:
                log(f"         ! {path.relative_to(PROJECT_ROOT)}")
            continue

        log(f"remove {directory.name}/ (now empty)")
        if apply:
            shutil.rmtree(directory, ignore_errors=True)


def move_requirements(apply):
    root_requirements = PROJECT_ROOT / "requirements.txt"
    backend_requirements = BACKEND / "requirements.txt"

    log(f"write  backend/requirements.txt (backend deps only)")
    if apply:
        backend_requirements.parent.mkdir(parents=True, exist_ok=True)
        backend_requirements.write_text(BACKEND_REQUIREMENTS, encoding="utf-8")

    if root_requirements.exists():
        log("keep   requirements.txt at root (ML training pipeline deps)")


def write_paths_module(apply):
    target = BACKEND / "src" / "paths.py"
    log("write  backend/src/paths.py (marker-based project root)")
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(PATHS_MODULE, encoding="utf-8")


# This script documents the very patterns it rewrites, so running it over
# itself would corrupt its own docstring. It is excluded explicitly.
SELF = Path(__file__).resolve()

# conftest.py bootstraps sys.path so that `backend` becomes importable at all.
# Rewriting its PROJECT_ROOT to import from backend.src.paths would create a
# chicken-and-egg problem: the import would run before the path it depends on
# had been registered. Its imports are still rewritten; only the PROJECT_ROOT
# line is left alone.
NO_ROOT_REWRITE = {"conftest.py"}


def python_files(moved):
    """Python files to rewrite.

    Before the move they still live at src/ and tests/; afterwards they are
    under backend/. Dry run therefore scans the pre-move locations so the
    preview reflects the same set of files that --apply will touch.
    """
    bases = (
        [BACKEND, PROJECT_ROOT / "scripts"] if moved
        else [PROJECT_ROOT / "src", PROJECT_ROOT / "tests", PROJECT_ROOT / "scripts"]
    )

    for base in bases:
        if base.exists():
            for path in base.rglob("*.py"):
                if path.resolve() != SELF:
                    yield path

    root_main = PROJECT_ROOT / "main.py"
    if root_main.exists():
        yield root_main


def plan_rewrite(source, allow_root_rewrite=True):
    """Return (updated_text, list_of_change_descriptions)."""
    updated = source
    changes = []

    for pattern, replacement in IMPORT_PATTERNS:
        hits = len(pattern.findall(updated))
        if hits:
            changes.append(f"{hits} import(s) -> {replacement.strip()}…")
            updated = pattern.sub(replacement, updated)

    if not allow_root_rewrite:
        return updated, changes

    for pattern in OLD_ROOT_PATTERNS:
        if pattern.search(updated):
            updated = pattern.sub("PROJECT_ROOT = str(_PROJECT_ROOT)", updated)
            changes.append("PROJECT_ROOT -> backend.src.paths (marker-based)")
            if "from backend.src.paths import PROJECT_ROOT as _PROJECT_ROOT" not in updated:
                updated = _insert_paths_import(updated)

    return updated, changes


def rewrite_file(path, apply):
    original = path.read_text(encoding="utf-8")
    updated, changes = plan_rewrite(
        original, allow_root_rewrite=path.name not in NO_ROOT_REWRITE
    )

    if updated == original:
        return False

    relative = path.relative_to(PROJECT_ROOT)
    log(f"edit   {relative}")
    for change in changes:
        log(f"         - {change}")

    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def _insert_paths_import(source):
    """Add the paths import after the last top-level import line."""
    lines = source.splitlines(keepends=True)
    insert_at = 0
    for index, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            insert_at = index + 1
    lines.insert(
        insert_at,
        "from backend.src.paths import PROJECT_ROOT as _PROJECT_ROOT\n",
    )
    return "".join(lines)


PACKAGE_DIRS = [
    "backend", "backend/src", "backend/src/api", "backend/src/models",
    "backend/src/services", "backend/src/storage", "backend/src/quarantine",
    "scripts",
]


def ensure_packages(apply):
    """Make backend/* and scripts/ importable as packages.

    scripts/ needs __init__.py too, because pipeline scripts import each other
    (train_spam_model imports build_spam_model) via `scripts.<name>`.
    """
    for relative in PACKAGE_DIRS:
        init = PROJECT_ROOT / relative / "__init__.py"
        if init.exists():
            continue
        log(f"write  {relative}/__init__.py")
        if apply:
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_text("", encoding="utf-8")


def add_script_bootstrap(apply):
    """Prepend the sys.path prelude to every relocated pipeline script.

    Without it `python scripts/train_phishing_bert.py` cannot import backend.*
    because sys.path[0] is scripts/, not the project root.
    """
    targets = [
        dest for _, dest in FILE_MOVES
        if dest.startswith("scripts/") and dest.endswith(".py")
    ]

    for relative in targets:
        path = PROJECT_ROOT / relative
        log(f"bootstrap  {relative}")

        if not apply or not path.exists():
            continue

        source = path.read_text(encoding="utf-8")
        if "_ROOT = Path(__file__).resolve().parents[1]" in source:
            continue

        # Insert after the module docstring so it stays the first statement.
        lines = source.splitlines(keepends=True)
        insert_at = 0
        if lines and lines[0].lstrip().startswith(('"""', "'''")):
            quote = lines[0].lstrip()[:3]
            if lines[0].count(quote) >= 2:
                insert_at = 1
            else:
                for index in range(1, len(lines)):
                    if quote in lines[index]:
                        insert_at = index + 1
                        break

        lines.insert(insert_at, "\n" + SCRIPT_BOOTSTRAP)
        path.write_text("".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually perform the restructure")
    parser.add_argument("--force", action="store_true",
                        help="proceed even if the git tree is dirty")
    args = parser.parse_args()

    print("=" * 68)
    print("RESTRUCTURE: backend code -> backend/")
    print("=" * 68)
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Mode         : {'APPLY' if args.apply else 'DRY RUN (nothing will change)'}")
    print(f"Git          : {'available' if git_available() else 'not a git repo'}")
    print()

    if already_restructured():
        print("backend/src/api/app.py already exists - nothing to do.")
        return 0

    if args.apply and not args.force and not tree_is_clean():
        print("ABORTED: the git tree has uncommitted changes.")
        print("Commit or stash first so the move can be reverted if needed,")
        print("or re-run with --force.")
        return 1

    print("File moves:")
    move_files(args.apply)
    print()
    print("Deletions:")
    delete_files(args.apply)
    print()
    print("Supporting changes:")
    remove_empty_source_dirs(args.apply)
    move_requirements(args.apply)
    ensure_packages(args.apply)
    write_paths_module(args.apply)
    print()
    print("Script bootstrap (enables `python scripts/<name>.py`):")
    add_script_bootstrap(args.apply)

    print()
    print("Imports and path handling"
          f"{'' if args.apply else ' (preview — scanned at current locations)'}:")
    changed = sum(
        1 for path in sorted(python_files(moved=args.apply))
        if rewrite_file(path, args.apply)
    )
    print(f"  {changed} file(s) {'updated' if args.apply else 'would be updated'}")

    print()
    print("=" * 68)
    if args.apply:
        print("DONE. Now verify, in this order:")
        print("  python -m pytest backend/tests -q")
        print("  python -m backend.src.main")
        print("  cd frontend && npm run build")
        print()
        print("If anything is wrong:  git reset --hard")
    else:
        print("Dry run only. Re-run with --apply to perform the restructure.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
