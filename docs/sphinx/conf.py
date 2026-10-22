"""Sphinx configuration for Vesta.

Thin wrapper over the shared ``deloitte_sphinx`` config so this repo inherits
the org-wide universal look & feel. Only repo-specific values live here.
"""

import os
import sys

# Prefer the vendored fallback copy so docs build without a network install.
sys.path.insert(0, os.path.abspath("_ext"))

from deloitte_sphinx import setup_config  # noqa: E402

globals().update(
    setup_config(
        project="Vesta",
        release="0.8.5",
    )
)
