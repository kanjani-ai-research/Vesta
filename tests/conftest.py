"""Keep the tests out of the user's store.

Every test that built a graph wrote into `~/.vesta`, so a run left a record for
each temporary repository it created — eight of them named `proj`, which made
resolving a project by name ambiguous for a reason that had nothing to do with
the user's projects.
"""

from __future__ import annotations

import pytest

from vesta.home import keep_in


@pytest.fixture(autouse=True)
def elsewhere(tmp_path_factory):
    """Point everything Vesta keeps at a directory this run owns."""
    keep_in(tmp_path_factory.mktemp("vesta-home"))
    yield
    keep_in(None)
