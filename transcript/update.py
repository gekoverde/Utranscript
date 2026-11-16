"""Updating Transcript to the latest commit of its GitHub repository: ``transcript --update``.

The version number does not change with every commit, so ``pipx upgrade`` and
``pip install --upgrade`` would keep the installed copy: pip only reinstalls a package from git
when its version is different. The update therefore forces the reinstallation of this package,
and nothing else, inside the environment it runs from. That keeps the same Python, and leaves
alone the ``transcript`` launcher that pipx or uv copied next to the other commands, which on
Windows cannot be replaced while it is running.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import site
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from rich.markup import escape

from . import tools
from .i18n import t
from .ui import console, err_console

REPO = "https://github.com/gekoverde/Utranscript.git"
DIST = "transcript-cli"
PACKAGE_DIR = Path(__file__).resolve().parent


class UpdateError(Exception):
    """The update could not be done. The message is shown to the user."""


@dataclass
class Installed:
    """How the running copy was installed."""

    kind: str  # "git", "folder" (a local folder or a wheel), "source" (a development copy) or "unknown"
    commit: str | None = None  # the git commit, when it was installed from git
    path: Path | None = None  # the folder of a development copy
    dist: importlib.metadata.Distribution | None = None


def installed() -> Installed:
    try:
        dist = importlib.metadata.distribution(DIST)
    except importlib.metadata.PackageNotFoundError:
        return Installed("source", path=PACKAGE_DIR.parent)  # run from a folder without installing it
    try:
        origin = json.loads(dist.read_text("direct_url.json") or "{}")
    except (OSError, ValueError):
        origin = {}
    if not isinstance(origin, dict):
        origin = {}
    dir_info = origin.get("dir_info") or {}
    if dir_info.get("editable"):
        return Installed("source", path=_folder(origin.get("url")) or PACKAGE_DIR.parent, dist=dist)
    if not _runs_from(dist):  # another copy of the package is installed, but this one runs from a folder
        return Installed("source", path=PACKAGE_DIR.parent, dist=dist)
    vcs = origin.get("vcs_info") or {}
    commit = vcs.get("commit_id")
    if vcs.get("vcs") == "git" and isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit):
        return Installed("git", commit=commit, dist=dist)
    return Installed("folder" if origin else "unknown", dist=dist)


def _folder(url: object) -> Path | None:
    if not isinstance(url, str) or not url.startswith("file:"):
        return None
    return Path(url2pathname(urlparse(url).path))


def _runs_from(dist: importlib.metadata.Distribution) -> bool:
    try:
        return Path(str(dist.locate_file("transcript/__init__.py"))).resolve() == PACKAGE_DIR / "__init__.py"
    except (OSError, ValueError):
        return False


def short(commit: str | None) -> str:
    return commit[:7] if commit else t("update.unknown")


def installed_commit() -> str | None:
    """The commit of the running copy, if it was installed from git (for ``--version``)."""
    try:
        return installed().commit
    except Exception:
        return None


def latest_commit() -> str:
    """The latest commit of the repository's default branch."""
    git = tools.which("git")
    if not git:
        raise UpdateError(t("update.no_git"))
    try:
        result = tools.run([git, "ls-remote", REPO, "HEAD"], timeout=60, env=_quiet_env())
    except tools.ConversionError as exc:
        raise UpdateError(t("update.offline", error=exc)) from exc
    match = re.search(r"^([0-9a-f]{40})\s+HEAD$", result.stdout, re.MULTILINE)
    if not match:
        raise UpdateError(t("update.offline", error=tools.tail(result.stdout)))
    return match.group(1)


def installed_extras(dist: importlib.metadata.Distribution | None) -> list[str]:
    """The optional extras (speech, svg, raw) whose packages are all installed: they are kept."""
    needed: dict[str, list[str]] = {}
    for requirement in (dist.requires if dist else None) or []:
        extra = re.search(r"""extra\s*==\s*["']([^"']+)["']""", requirement)
        name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        if extra and name:
            needed.setdefault(extra.group(1), []).append(name.group(1))
    return sorted(
        extra
        for extra, names in needed.items()
        if all(_canonical(n) != DIST for n in names) and all(_is_installed(n) for n in names)
    )


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_installed(name: str) -> bool:
    try:
        importlib.metadata.distribution(name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def spec(commit: str, extras: Sequence[str] = ()) -> str:
    names = f"[{','.join(extras)}]" if extras else ""
    return f"{DIST}{names} @ git+{REPO}@{commit}"


def commands(commit: str, info: Installed) -> list[list[str]]:
    """The commands that install ``commit`` in the environment of the running copy."""
    requirement = spec(commit, installed_extras(info.dist))
    uv = tools.which("uv")
    if _has_pip():  # a venv, a plain pip installation, or pipx with pip
        pip = [sys.executable, "-m", "pip"]
    elif uv:  # 'uv tool' and pipx with uv create environments without pip
        return [[uv, "pip", "install", "--python", sys.executable, "--reinstall-package", DIST, requirement]]
    elif _base_has_pip():  # the pip of the Python the environment was made from, working on this one
        pip = [sys._base_executable, "-m", "pip", "--python", sys.executable]
    else:
        raise UpdateError(t("update.no_installer"))
    pip += ["install", "--disable-pip-version-check", "--no-input"]
    if _in_user_site():
        pip.append("--user")
    return [
        # First the dependencies a new version may need (pip leaves the package itself alone, as
        # its version is the same): if this fails, nothing has changed yet.
        [*pip, requirement],
        # Then the code of Transcript only.
        [*pip, "--force-reinstall", "--no-deps", requirement],
    ]


def _has_pip() -> bool:
    return importlib.util.find_spec("pip") is not None


def _base_has_pip() -> bool:
    """Whether the base Python of this environment has a pip with ``--python`` (pip 22.3 or later)."""
    base = getattr(sys, "_base_executable", None)
    # Outside a virtual environment the base Python is this one, which has no pip.
    if sys.prefix == sys.base_prefix or not base or not os.path.isfile(base):
        return False
    check = "import pip, sys; sys.exit(tuple(int(n) for n in pip.__version__.split('.')[:2]) < (22, 3))"
    try:
        tools.run([base, "-c", check], timeout=60)
        return True
    except (tools.ConversionError, ValueError):
        return False


def _in_user_site() -> bool:
    if not site.ENABLE_USER_SITE:
        return False
    try:
        user_site = Path(site.getusersitepackages()).resolve()
        return user_site in PACKAGE_DIR.parents
    except (OSError, ValueError):
        return False


def manual_command() -> str:
    """What the user can run by hand, in the way Transcript was installed."""
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    prefix = Path(sys.prefix)
    if (prefix / "pipx_metadata.json").is_file():
        return f"pipx install --force --python {python} git+{REPO}"
    if (prefix / "uv-receipt.toml").is_file():
        return f"uv tool install --force --python {python} git+{REPO}"
    return f'"{sys.executable}" -m pip install --force-reinstall "{DIST} @ git+{REPO}"'


def _quiet_env() -> dict[str, str]:
    """No prompts (a password for git, a question from pip) and output pip can always encode."""
    return {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONIOENCODING": "utf-8",
    }


def run_update(verbose: bool = False) -> int:
    """Install the latest commit from GitHub. Returns the exit code."""
    info = installed()
    if info.kind == "source":
        _note(t("update.source", path=info.path))
        return 1
    try:
        with console.status(t("update.checking")):
            latest = latest_commit()
        if info.commit == latest:
            console.print(f"[bold green]✔[/bold green] {escape(t('update.latest', commit=short(latest)))}")
            return 0
        steps = commands(latest, info)
        with console.status(t("update.running", old=short(info.commit), new=short(latest))):
            for command in steps:
                tools.run(command, timeout=1800, env=_quiet_env(), verbose=verbose, log=_log)
    except (UpdateError, tools.ConversionError) as exc:
        _error(t("update.failed", error=exc))
        _note(t("update.manual", command=manual_command()))
        return 1
    # The code on disk is the new version from here on: only print and exit.
    console.print(f"[bold green]✔[/bold green] {escape(t('update.done', commit=short(latest)))}")
    return 0


def _log(message: str) -> None:
    console.print(message, style="dim", markup=False, highlight=False, soft_wrap=True)


def _error(message: str) -> None:
    err_console.print(f"[bold red]✘[/bold red] {escape(message)}", highlight=False, soft_wrap=True)


def _note(message: str) -> None:
    err_console.print(f"[yellow]![/yellow] {escape(message)}", highlight=False, soft_wrap=True)
