# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Path setup --------------------------------------------------------------
sys.path.insert(0, os.path.abspath(".."))

# Read version without triggering the full package import chain
_init_path = os.path.join(os.path.dirname(__file__), "..", "eventforge", "__init__.py")
_ver_ns: dict = {}
with open(_init_path) as _f:
    for _line in _f:
        if _line.startswith("__version__"):
            exec(_line, _ver_ns)
            break
__version__ = _ver_ns.get("__version__", "0.0.0")

# -- Project information -----------------------------------------------------

project = "eventforge"
copyright = "2024, Adnan Harun Dogan"
author = "Adnan Harun Dogan"
release = __version__
version = __version__

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- MyST options ------------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

# -- Options for autodoc -----------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

autodoc_typehints = "description"

# -- Options for Napoleon ----------------------------------------------------

napoleon_google_docstrings = True
napoleon_numpy_docstrings = True
napoleon_include_init_with_doc = True

# -- Options for intersphinx -------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
}

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = []
html_title = f"eventforge {version}"
