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


# ── A push carries the tag, or does not happen ──────────────────────────────


def _repo_with_remote(tmp_path):
    root = _project(tmp_path / "p", changelog="## 1.2.3\n\ncurrent\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "one")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(root, "remote", "add", "origin", str(remote))
    return root, remote


def _refs(root, branch="main"):
    sha = _git(root, "rev-parse", branch)
    return f"refs/heads/{branch} {sha} refs/heads/{branch} {'0' * 40}\n"


def test_tags_are_annotated_and_a_lightweight_one_is_remade_in_place(tmp_path):
    from vesta.version import _is_annotated

    root, _ = _repo_with_remote(tmp_path)
    _git(root, "tag", "v1.2.3")
    at = _git(root, "rev-parse", "v1.2.3^{commit}")
    assert _is_annotated(root, "v1.2.3") is False
    assert tag(root, "1.2.3") == "v1.2.3"
    assert _is_annotated(root, "v1.2.3") is True
    assert _git(root, "rev-parse", "v1.2.3^{commit}") == at
    with pytest.raises(ValueError):
        tag(root, "1.2.3")


def test_a_branch_push_without_the_tag_is_refused_with_the_fix(tmp_path):
    from vesta.version import before_push

    root, _ = _repo_with_remote(tmp_path)
    ok, said = before_push(root, "origin", _refs(root))
    assert not ok and "has no tag (v1.2.3)" in said and "vesta version --tag" in said

    _git(root, "tag", "v1.2.3")
    ok, said = before_push(root, "origin", _refs(root))
    assert not ok and "lightweight" in said

    tag(root, "1.2.3")
    ok, said = before_push(root, "origin", _refs(root))
    assert not ok and "followTags" in said

    _git(root, "config", "--local", "push.followTags", "true")
    ok, said = before_push(root, "origin", _refs(root))
    assert ok and "v1.2.3 rides along" in said


def test_pushes_that_are_not_a_branch_are_none_of_its_business(tmp_path):
    from vesta.version import before_push

    root, _ = _repo_with_remote(tmp_path)
    assert before_push(root, "origin", "")[0]
    assert before_push(root, "origin", f"refs/tags/v1 {'a' * 40} refs/tags/v1 {'0' * 40}\n")[0]
    assert before_push(root, "origin", f"(delete) {'0' * 40} refs/heads/main {'b' * 40}\n")[0]


def test_a_disagreeing_version_is_not_pushed(tmp_path):
    from vesta.version import before_push

    root, _ = _repo_with_remote(tmp_path)
    (root / "x" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    ok, said = before_push(root, "origin", _refs(root))
    assert not ok and "not the same everywhere" in said


def test_a_tag_on_a_commit_not_being_pushed_is_refused_unless_the_remote_has_it(tmp_path):
    from vesta.version import before_push

    root, remote = _repo_with_remote(tmp_path)
    tag(root, "1.2.3")
    _git(root, "config", "--local", "push.followTags", "true")
    _git(root, "checkout", "-q", "--orphan", "other")
    (root / "README").write_text("x", encoding="utf-8")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "two")
    # `other` does not reach the tagged commit; the pushed version files are the same.
    ok, said = before_push(root, "origin", _refs(root, "other"))
    assert not ok and "not in what is being pushed" in said
    _git(root, "push", "-q", "origin", "v1.2.3")
    ok, _ = before_push(root, "origin", _refs(root, "other"))
    assert ok


def test_the_guard_is_private_and_git_actually_refuses(tmp_path):
    from vesta.version import guard

    root, remote = _repo_with_remote(tmp_path)
    done = guard(root)
    assert any("pre-push" in line for line in done)
    assert _git(root, "config", "--get", "push.followTags") == "true"
    assert not (root / "pre-push").exists()
    hook = root / ".git" / "hooks" / "pre-push"
    assert hook.is_file() and "vesta" in hook.read_text()
    assert "pre-push" not in _git(root, "status", "--porcelain")

    pushed = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(root), capture_output=True, text=True)
    assert pushed.returncode != 0
    assert "has no tag" in pushed.stdout + pushed.stderr
    assert "main" not in subprocess.run(["git", "branch"], cwd=str(remote), capture_output=True, text=True).stdout

    tag(root, "1.2.3")
    pushed = subprocess.run(["git", "push", "-q", "origin", "main"], cwd=str(root), capture_output=True, text=True)
    assert pushed.returncode == 0, pushed.stderr
    on_remote = subprocess.run(["git", "tag"], cwd=str(remote), capture_output=True, text=True).stdout
    assert "v1.2.3" in on_remote

    # Installing again replaces ours; a foreign hook is left alone.
    guard(root)
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        guard(root)
