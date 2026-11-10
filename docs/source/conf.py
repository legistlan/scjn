# Configuration file for the Sphinx documentation builder.
#
# For a full list of options see:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup ---------------------------------------------------------
#
# scjn is installed editable by the builds that render these docs
# (website.yml, test.yml) rather than reached via sys.path manipulation
# here, so conf.py only needs to import the already-installed package to read
# its __version__.

import scjn

# -- Project information -------------------------------------------------

project = "scjn"
copyright = "2026, legistlan"
author = "legistlan"

# The repository is the package, so there is a single version here -- kept as
# the same |scjn_version| substitution the page used while it was one page
# of the LegalIA monorepo's site.
rst_epilog = f"""
.. |scjn_version| replace:: {scjn.__version__}
"""

# -- General configuration ------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.doctest",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

source_suffix = ".rst"
master_doc = "index"
language = "en"
exclude_patterns = []

pygments_style = "sphinx"
highlight_language = "python"
# Docstrings quote JSON shapes and outline marker lines in plain literal
# blocks, which are not Python: Pygments falls back to plain text, and the
# strict build (`-n -W`) must not fail on that fallback.
suppress_warnings = ["misc.highlighting_failure"]
autodoc_member_order = "bysource"
autodoc_class_signature = "separated"
add_function_parentheses = False
add_module_names = False

# -- Options for HTML output ----------------------------------------------

html_theme = "furo"
htmlhelp_basename = "scjndoc"
