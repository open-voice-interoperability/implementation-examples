# Configuration file for the Sphinx documentation builder.

import os
import sys
from datetime import datetime
from pathlib import Path

# -- Path setup --------------------------------------------------------------

# Add project root so Sphinx can find stella2
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# -- Project information -----------------------------------------------------

project = "stella2"
author = "Your Name"
copyright = f"{datetime.now().year}, {author}"
release = "0.1.0"

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",      # Extracts documentation from docstrings
    "sphinx.ext.napoleon",     # Google/NumPy style docstrings
    "sphinx.ext.viewcode",     # Links to source code
    "sphinx.ext.todo",         # Support for TODOs in docs
]

# Napoleon settings (for Google/NumPy docstring parsing)
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output -------------------------------------------------

html_theme = "alabaster"
html_static_path = ["_static"]

# -- Autodoc settings --------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"

# -- TODO extension ----------------------------------------------------------
todo_include_todos = True
