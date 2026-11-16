"""``transcript --update`` and the menu of ``transcript`` without a file. Nothing here uses the network."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys

import pytest

from transcript import cli, tools, update

OLD = "a" * 40
NEW = "b" * 40


class FakeDist:
    def __init__(self, direct_url=None, requires=None, location=None):
        self._direct_url = direct_url
        self.requires = requires
        self._location = location or update.PACKAGE_DIR.parent

    def read_text(self, name):
        if name == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None

    def locate_file(self, path):
        return self._location / path


@pytest.fixture
def dist(monkeypatch):
    """Make ``transcript-cli`` look installed with the given direct_url.json."""

    def install(direct_url=None, requires=None, location=None):
        fake = FakeDist(direct_url, requires, location)
        real = importlib.metadata.distribution
        monkeypatch.setattr(importlib.metadata, "distribution", lambda name: fake if name == update.DIST else real(name))
        return fake

    return install


def from_git(commit=OLD):
    return {"url": update.REPO, "vcs_info": {"vcs": "git", "commit_id": commit}}


# what is installed --------------------------------------------------------------------------


def test_installed_from_git(dist):
    dist(from_git())
    info = update.installed()
    assert (info.kind, info.commit) == ("git", OLD)
    assert update.installed_commit() == OLD


def test_editable_install_is_a_development_copy(dist, tmp_path):
    dist({"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    info = update.installed()
    assert (info.kind, info.path) == ("source", tmp_path)


def test_folder_and_unknown_installs(dist, tmp_path):
    dist({"url": tmp_path.as_uri(), "dir_info": {}})
    assert (update.installed().kind, update.installed().commit) == ("folder", None)
    dist(None)  # installed from a wheel: no direct_url.json
    assert update.installed().kind == "unknown"


def test_running_from_another_folder_is_a_development_copy(dist, tmp_path):
    dist(from_git(), location=tmp_path)  # the installed copy is not the one running
    assert update.installed().kind == "source"


def test_not_installed_is_a_development_copy(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", missing)
    assert update.installed().kind == "source"
    assert update.installed_commit() is None


def test_extras_whose_packages_are_installed_are_kept(dist, monkeypatch):
    fake = dist(
        from_git(),
        requires=[
            "rich>=13.0",
            'faster-whisper>=1.0; extra == "speech"',
            'cairosvg>=2.7; extra == "svg"',
            'rawpy>=0.19; extra == "raw"',
            'transcript-cli[raw,speech,svg]; extra == "all"',
        ],
    )
    present = {"faster-whisper", "rawpy"}
    monkeypatch.setattr(update, "_is_installed", lambda name: name in present)
    assert update.installed_extras(fake) == ["raw", "speech"]
    assert update.installed_extras(None) == []


# the commands ---------------------------------------------------------------------------


def test_latest_commit_reads_ls_remote(monkeypatch):
    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"], seen["env"] = cmd, kwargs["env"]
        return subprocess.CompletedProcess(cmd, 0, f"{NEW}\tHEAD\n", "")

    monkeypatch.setattr(tools, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    monkeypatch.setattr(tools, "run", run)
    assert update.latest_commit() == NEW
    assert seen["cmd"] == ["/usr/bin/git", "ls-remote", update.REPO, "HEAD"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_latest_commit_without_git_or_network(monkeypatch):
    monkeypatch.setattr(tools, "which", lambda name: None)
    with pytest.raises(update.UpdateError, match="Git is needed"):
        update.latest_commit()

    def offline(cmd, **kwargs):
        raise tools.ConversionError("git failed: Could not resolve host: github.com")

    monkeypatch.setattr(tools, "which", lambda name: "git")
    monkeypatch.setattr(tools, "run", offline)
    with pytest.raises(update.UpdateError, match="could not reach GitHub.*resolve host"):
        update.latest_commit()


def test_pip_installs_the_dependencies_first_then_only_transcript(dist, monkeypatch):
    fake = dist(from_git(), requires=['rawpy; extra == "raw"'])
    monkeypatch.setattr(update, "_has_pip", lambda: True)
    monkeypatch.setattr(update, "_is_installed", lambda name: True)
    monkeypatch.setattr(update, "_in_user_site", lambda: False)
    first, second = update.commands(NEW, update.Installed("git", OLD, dist=fake))
    spec = f"transcript-cli[raw] @ git+{update.REPO}@{NEW}"
    pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    assert first == [*pip, spec]
    assert second == [*pip, "--force-reinstall", "--no-deps", spec]

    monkeypatch.setattr(update, "_in_user_site", lambda: True)
    assert all("--user" in command for command in update.commands(NEW, update.Installed("git", OLD, dist=fake)))


def test_uv_tool_environment_without_pip(dist, monkeypatch):
    fake = dist(from_git())
    monkeypatch.setattr(update, "_has_pip", lambda: False)
    monkeypatch.setattr(tools, "which", lambda name: "/bin/uv" if name == "uv" else None)
    (command,) = update.commands(NEW, update.Installed("git", OLD, dist=fake))
    assert command == [
        "/bin/uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "--reinstall-package",
        "transcript-cli",
        f"transcript-cli @ git+{update.REPO}@{NEW}",
    ]


def test_pip_of_the_base_python_when_the_environment_has_none(dist, monkeypatch):
    fake = dist(from_git())
    monkeypatch.setattr(update, "_has_pip", lambda: False)
    monkeypatch.setattr(tools, "which", lambda name: None)
    monkeypatch.setattr(update, "_in_user_site", lambda: False)
    monkeypatch.setattr(sys, "_base_executable", "/base/python", raising=False)
    monkeypatch.setattr(update, "_base_has_pip", lambda: True)
    first, second = update.commands(NEW, update.Installed("git", OLD, dist=fake))
    assert first[:5] == ["/base/python", "-m", "pip", "--python", sys.executable]
    assert second[-3:] == ["--force-reinstall", "--no-deps", f"transcript-cli @ git+{update.REPO}@{NEW}"]

    monkeypatch.setattr(update, "_base_has_pip", lambda: False)
    with pytest.raises(update.UpdateError, match="neither pip nor uv"):
        update.commands(NEW, update.Installed("git", OLD, dist=fake))


def test_manual_command_follows_the_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert update.manual_command().endswith(f'-m pip install --force-reinstall "transcript-cli @ git+{update.REPO}"')
    (tmp_path / "uv-receipt.toml").write_text("")
    assert update.manual_command() == f"uv tool install --force --python {version} git+{update.REPO}"
    (tmp_path / "pipx_metadata.json").write_text("{}")
    assert update.manual_command() == f"pipx install --force --python {version} git+{update.REPO}"


# run_update --------------------------------------------------------------------------------


@pytest.fixture
def ran(monkeypatch):
    """The install commands run_update runs (none really run)."""
    commands = []
    monkeypatch.setattr(update, "latest_commit", lambda: NEW)
    monkeypatch.setattr(update, "commands", lambda commit, info: [["install", commit]])
    monkeypatch.setattr(tools, "run", lambda cmd, **kwargs: commands.append(cmd))
    return commands


def test_update_installs_the_latest_commit(dist, ran, capsys):
    dist(from_git(OLD))
    assert update.run_update() == 0
    assert ran == [["install", NEW]]
    assert "Transcript updated to bbbbbbb" in capsys.readouterr().out


def test_up_to_date_installs_nothing(dist, ran, capsys):
    dist(from_git(NEW))
    assert update.run_update() == 0
    assert ran == []
    assert "already have the latest version (bbbbbbb)" in capsys.readouterr().out


def test_development_copy_is_left_alone(dist, ran, capsys, tmp_path):
    dist({"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    assert update.run_update() == 1
    assert ran == []
    assert "git pull" in capsys.readouterr().err


def test_failed_update_says_what_to_run(dist, monkeypatch, capsys):
    dist(from_git(OLD))
    monkeypatch.setattr(update, "latest_commit", lambda: NEW)
    monkeypatch.setattr(update, "commands", lambda commit, info: [["install"]])

    def fail(cmd, **kwargs):
        raise tools.ConversionError("python failed: No matching distribution found for rich>=99")

    monkeypatch.setattr(tools, "run", fail)
    assert update.run_update() == 1
    err = capsys.readouterr().err
    assert "The update failed: python failed: No matching distribution found for rich>=99" in err
    assert "by hand with:" in err


# the command line --------------------------------------------------------------------------


def test_update_option(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "run_update", lambda verbose=False: calls.append(verbose) or 0)
    assert cli.main(["--update", "-v"]) == 0
    assert calls == [True]


def test_version_shows_the_commit(dist, capsys):
    dist(from_git(OLD))
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.strip() == "transcript 0.1.0 (aaaaaaa)"


@pytest.mark.parametrize("action", ["update", "formats", "doctor", "help"])
def test_menu_without_a_file(monkeypatch, capsys, action):
    called = []
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    monkeypatch.setattr(cli, "choose_action", lambda: action)
    monkeypatch.setattr(update, "run_update", lambda verbose=False: called.append("update") or 0)
    monkeypatch.setattr(cli, "list_formats", lambda: called.append("formats") or 0)
    monkeypatch.setattr(cli, "doctor", lambda: called.append("doctor") or 0)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "to convert a file: transcript FILE" in out
    if action == "help":
        assert "usage: transcript" in out
    else:
        assert called == [action]


def test_menu_without_a_file_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    monkeypatch.setattr(cli, "choose_action", lambda: None)
    assert cli.main([]) == 130
    assert "Cancelled." in capsys.readouterr().err


def test_main_menu_lists_every_action(monkeypatch):
    questionary = pytest.importorskip("questionary")
    seen = {}

    class Question:
        def ask(self, kbi_msg=""):
            return "doctor"

    def select(message, choices, **kwargs):
        seen["message"], seen["choices"] = message, choices
        return Question()

    monkeypatch.setattr(questionary, "select", select)
    from transcript.ui import choose_action

    assert choose_action() == "doctor"
    assert seen["message"] == "What do you want to do?"
    assert [(c.title, c.value) for c in seen["choices"]] == [
        ("Update Transcript from GitHub", "update"),
        ("See the supported formats", "formats"),
        ("See the conversion engines", "doctor"),
        ("Help", "help"),
    ]
