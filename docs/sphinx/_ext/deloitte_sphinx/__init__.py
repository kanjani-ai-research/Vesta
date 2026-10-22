"""Shared Sphinx configuration for Deloitte documentation repositories.

Provides a single, universal look & feel (furo theme + MyST + autodoc) so every
repo's docs render identically. Per-repo ``conf.py`` files import this module and
override only repo-specific values (``project``, ``release``, source path).

Usage in a repo's ``docs/sphinx/conf.py``::

    from deloitte_sphinx import setup_config
    globals().update(setup_config(project="my-repo", release="1.0.0"))

The function returns a dict of Sphinx config variables. This keeps per-repo
config to a few lines and lets the whole org restyle from one place.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

__version__ = "0.1.0"

# Universal copyright line for all docs.
ORG_COPYRIGHT = "Deloitte USA"

# Extension set shared by every repo.
DEFAULT_EXTENSIONS: List[str] = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
    "sphinx.ext.coverage",
    "myst_parser",
    "sphinxcontrib.mermaid",
    # Developer-experience add-ons.
    "sphinx_copybutton",   # copy button on code blocks
    "sphinx_design",       # grids, cards, tabs (works with MyST + furo)
]

# Common optional/runtime deps mocked so autodoc works without a full install.
DEFAULT_MOCK_IMPORTS: List[str] = [
    "nicegui", "authlib", "httpx", "boto3", "botocore",
    "starlette", "fastapi", "pydantic", "pydantic_settings", "jwt", "jose",
    "fastmcp", "mcp", "opentelemetry", "yaml", "redis",
    "pandas", "numpy", "aiohttp", "sqlalchemy",
    # Sibling internal packages imported by ai-*/guard-* engines at runtime;
    # mocked so autodoc import does not fail or emit bootstrap warnings.
    "guard_core", "guard_dal_client", "guard_config", "guard_auth",
    "guard_entitlement", "guard_engine_client", "guard_core_ui",
    "guard_core_aiap", "guard_wizardry",
]


def setup_config(
    *,
    project: str,
    release: str = "0.1.0",
    author: str = ORG_COPYRIGHT,
    copyright_year: str = "2026",
    src_paths: Optional[List[str]] = None,
    extra_extensions: Optional[List[str]] = None,
    extra_mock_imports: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return a dict of Sphinx config variables with the shared look & feel.

    Args:
        project: Repo / project name (also used as the HTML title).
        release: Version string shown in the docs.
        author: Author line. Defaults to the org copyright holder.
        copyright_year: Year used in the copyright string.
        src_paths: Paths (relative to the conf.py dir) to add to sys.path so
            autodoc can import the package. Defaults to common layouts.
        extra_extensions: Repo-specific Sphinx extensions to append.
        extra_mock_imports: Repo-specific modules to mock for autodoc.

    Returns:
        A dict intended to be merged into the conf.py module globals.
    """
    # Make autodoc able to import the package under documentation.
    if src_paths is None:
        src_paths = ["../../src", "../..", "../../.."]
    conf_dir = os.getcwd()
    for rel in src_paths:
        abspath = os.path.abspath(os.path.join(conf_dir, rel))
        if abspath not in sys.path:
            sys.path.insert(0, abspath)

    extensions = list(DEFAULT_EXTENSIONS)
    if extra_extensions:
        extensions += [e for e in extra_extensions if e not in extensions]

    mock_imports = list(DEFAULT_MOCK_IMPORTS)
    if extra_mock_imports:
        mock_imports += [m for m in extra_mock_imports if m not in mock_imports]

    return {
        # -- Project information ------------------------------------------
        "project": project,
        "author": author,
        "copyright": f"{copyright_year}, {author}",
        "release": release,
        "version": release,
        # -- General configuration ----------------------------------------
        "extensions": extensions,
        "autosummary_generate": True,
        "templates_path": ["_templates"],
        # Built-in autodoc: move type hints into the parameter descriptions
        # (same effect as sphinx-autodoc-typehints, but no brittle add-on that
        # couples to Sphinx internals).
        "autodoc_typehints": "description",
        "autodoc_typehints_description_target": "documented_params",
        # sphinx-copybutton: strip prompts so copied code is runnable.
        "copybutton_prompt_text": r">>> |\.\.\. |\$ ",
        "copybutton_prompt_is_regexp": True,
        "napoleon_google_docstring": True,
        "napoleon_numpy_docstring": False,
        "napoleon_include_init_with_doc": True,
        "autodoc_default_options": {
            "members": True,
            "undoc-members": True,
            "show-inheritance": True,
            "member-order": "bysource",
        },
        "autodoc_mock_imports": mock_imports,
        "source_suffix": {".rst": "restructuredtext", ".md": "markdown"},
        "myst_enable_extensions": ["colon_fence", "deflist"],
        # Render ```mermaid fenced code blocks in Markdown as diagrams.
        "myst_fence_as_directive": ["mermaid"],
        "exclude_patterns": ["_build", "Thumbs.db", ".DS_Store"],
        "intersphinx_mapping": {
            "python": ("https://docs.python.org/3", None),
        },
        "suppress_warnings": ["autodoc.import"],
        # -- HTML output / universal look & feel --------------------------
        "html_theme": "furo",
        "html_title": project,
        "html_static_path": ["_static"],
        "html_css_files": ["deloitte.css"],
        "html_theme_options": {
            "sidebar_hide_name": False,
            "navigation_with_keys": True,
        },
    }
