#!/usr/bin/env python3
"""
Generate Sphinx documentation for the stella project.
Run this script from the repo root.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Paths
REPO_ROOT = Path(__file__).resolve().parent
DOCS_DIR = REPO_ROOT / "docs"
STELLA_DIR = REPO_ROOT / "stella"

# Ensure package is importable
sys.path.insert(0, str(REPO_ROOT))

def main():
    # Make sure docs directory exists
    DOCS_DIR.mkdir(exist_ok=True)

    # Clean old API docs
    api_dir = DOCS_DIR / "api"
    if api_dir.exists():
        shutil.rmtree(api_dir)

    # Auto-generate reStructuredText from docstrings
    subprocess.run([
        "sphinx-apidoc",
        "-o", str(api_dir),
        str(STELLA_DIR)
    ], check=True)

    # Build HTML docs
    subprocess.run([
        "sphinx-build",
        "-b", "html",
        str(DOCS_DIR),
        str(DOCS_DIR / "_build" / "html")
    ], check=True)

    print(f"Documentation built at: {DOCS_DIR / '_build' / 'html' / 'index.html'}")

if __name__ == "__main__":
    main()
