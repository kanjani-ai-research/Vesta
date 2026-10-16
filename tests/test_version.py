"""One version, held in every place it is written.

0.7.0 shipped with the package and manifest still saying 0.6.2, and
`__version__` said 0.1.0 for seven releases. Each reader believed the one it
saw.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from vesta.version import places, set_version, tag, tag_shape

HERE = Path(__file__).resolve().parent.parent


def _project(at: Path, version="1.2.3", changelog="## Unreleased\n\nthings\n\n## 1.2.2\n\nolder\n") -> Path:
    at.mkdir(exist_ok=True)
    (at / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n', encoding="utf-8")
    (at / ".claude-plugin").mkdir()
    (at / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "x", "version": version}, indent=2), encoding="utf-8")
    (at / "x").mkdir()
    (at / "x" / "__init__.py").write_text(f'"""x."""\n\n__version__ = "{version}"\n', encoding="utf-8")
    (at / "CHANGELOG.md").write_text("# Changelog\n\n" + changelog, encoding="utf-8")
    return at


def test_every_place_is_found(tmp_path):
    found = places(_project(tmp_path / "p"))
    assert [p.where for p in found.places] == [
        "pyproject.toml", ".claude-plugin/plugin.json", "x/__init__.py", "CHANGELOG.md",
    ]
    assert found.version == "1.2.3"
    assert found.agree  # an Unreleased heading does not disagree


def test_a_disagreement_is_named(tmp_path):
    root = _project(tmp_path / "p")
    (root / "x" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    found = places(root)
    assert not found.agree and found.version == ""
    assert "DISAGREE: 0.1.0, 1.2.3" in found.describe()


def test_a_changelog_headed_with_another_version_disagrees(tmp_path):
    root = _project(tmp_path / "p", changelog="## 1.2.2\n\nolder\n")
    found = places(root)
    assert found.version == "1.2.3" and not found.agree
    assert "changelog" in found.describe()


def test_setting_writes_every_place_and_renames_unreleased(tmp_path):
    root = _project(tmp_path / "p")
    changed = set_version(root, "1.3.0")
    assert sorted(changed) == sorted(["pyproject.toml", ".claude-plugin/plugin.json", "x/__init__.py", "CHANGELOG.md"])
    found = places(root)
    assert found.agree and found.version == "1.3.0"
    assert json.loads((root / ".claude-plugin" / "plugin.json").read_text())["version"] == "1.3.0"
    assert (root / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## 1.3.0\n\nthings")
    assert set_version(root, "1.3.0") == []


def test_setting_opens_a_changelog_heading_when_there_is_none_to_rename(tmp_path):
    root = _project(tmp_path / "p", changelog="## 1.2.3\n\ncurrent\n")
    set_version(root, "1.3.0")
    text = (root / "CHANGELOG.md").read_text()
    assert text.startswith("# Changelog\n\n## 1.3.0\n\n## 1.2.3\n")


def test_a_malformed_version_is_refused_before_anything_is_written(tmp_path):
    root = _project(tmp_path / "p")
    with pytest.raises(ValueError):
        set_version(root, "one-point-three")
    assert places(root).version == "1.2.3"


def test_a_project_with_no_version_says_so(tmp_path):
    (tmp_path / "empty").mkdir()
    assert "no place" in places(tmp_path / "empty").describe()
    with pytest.raises(ValueError):
        set_version(tmp_path / "empty", "1.0.0")


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=True).stdout.strip()


def test_tagging_follows_the_repositorys_own_shape(tmp_path):
    root = _project(tmp_path / "p")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one")
    assert tag_shape(root) == "v{version}"
    _git(root, "tag", "proj--v1.2.2")
    assert tag_shape(root) == "proj--v{version}"
    assert tag(root, "1.2.3") == "proj--v1.2.3"
    assert "proj--v1.2.3" in _git(root, "tag", "--list")
    with pytest.raises(ValueError):
        tag(root, "1.2.3")


def test_tagging_refuses_uncommitted_versioned_files(tmp_path):
    root = _project(tmp_path / "p")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one")
    set_version(root, "1.3.0")
    with pytest.raises(ValueError) as caught:
        tag(root, "1.3.0")
    assert "not committed" in str(caught.value)


def test_this_repository_agrees_with_itself():
    found = places(HERE)
    assert found.agree, found.describe()
    import vesta

    assert found.version == vesta.__version__


def test_the_cli_reports_and_sets(tmp_path, capsys):
    import vesta.cli as cli

    root = _project(tmp_path / "p")
    assert cli.main(["version", str(root)]) == 0
    assert "agreed: 1.2.3" in capsys.readouterr().out
    assert cli.main(["version", str(root), "--set", "1.4.0"]) == 0
    out = capsys.readouterr().out
    assert "1.4.0" in out and "CHANGELOG.md" in out
    (root / "x" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    assert cli.main(["version", str(root)]) == 1
    assert "DISAGREE" in capsys.readouterr().out
