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
def _kept_away_from_home(tmp_path_factory):
    """Point everything Vesta keeps at a directory this test owns.

    Named with a leading underscore so no test file can shadow it by accident:
    a fixture of the same name defined in a test module wins over this one, and
    the test then runs against the user's real store — writing into it, and
    reading every project they have ever prepared. That happened once and the
    symptom was a test finding twenty-four projects where it made one.
    """
    keep_in(tmp_path_factory.mktemp("vesta-home"))
    yield
    keep_in(None)


@pytest.fixture(autouse=True)
def _never_the_real_home(_kept_away_from_home):
    """Refuse to run a test that is somehow pointed at the real store."""
    from vesta.home import VESTA_HOME, home

    if home() == VESTA_HOME:
        raise RuntimeError(
            "a test is pointed at the real ~/.vesta — check for a fixture "
            "shadowing _kept_away_from_home"
        )
    yield
