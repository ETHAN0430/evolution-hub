# -*- coding: utf-8 -*-
"""Install helper for the Hermes HY Memory plugin.

Why this exists
---------------
Hermes (>=0.16) discovers *memory* providers ONLY by scanning directories:
  1. bundled   ``<hermes>/plugins/memory/<name>/``
  2. user      ``$HERMES_HOME/plugins/<name>/``   (default ``~/.hermes/plugins``)

It does NOT activate memory providers via pip ``hermes_agent.plugins`` entry
points — such plugins are coerced to ``kind="exclusive"`` and skipped by the
general loader, and the memory category's own scan never looks at entry points.
(Verified against Hermes 0.16.0 source + live ``hermes memory status``.)

So a working install needs BOTH:
  (a) the ``hy-memory`` SDK + this package importable by the *Python that Hermes
      actually runs* (its own venv, which usually does not include system
      site-packages), and
  (b) a directory (or symlink) at ``~/.hermes/plugins/hy-memory/``.

This module provides the pure, testable pieces; the CLI glue lives in
``cli.py`` ``_cmd_install``.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Hermes venv / python detection
# ---------------------------------------------------------------------------

# Matches the exec line in the bash shim Hermes installs, e.g.
#   exec "/usr/local/lib/hermes-agent/venv/bin/hermes" "$@"
_EXEC_RE = re.compile(r"""exec\s+["']?(?P<path>[^"'\s]+/bin/[^"'\s]+)""")


def _python_for_launcher(launcher: Path) -> Optional[Path]:
    """Given a path to a `hermes` launcher, return the python next to it.

    Handles two launcher shapes:
      - python console script: shebang ``#!/.../venv/bin/python`` → use that.
      - bash shim: ``exec "/.../venv/bin/hermes"`` → derive sibling python.
    Returns None if nothing usable is found.
    """
    try:
        text = launcher.read_text(errors="replace")
    except Exception:
        return None

    lines = text.splitlines()

    # 1) python console script — first line is a python shebang
    if lines and lines[0].startswith("#!"):
        shebang = lines[0][2:].strip().split()[0] if len(lines[0]) > 2 else ""
        if shebang and "python" in os.path.basename(shebang):
            p = Path(shebang)
            if p.exists():
                return p

    # 2) bash shim — find an exec'd path inside a */bin/ dir, take sibling python
    for line in lines:
        m = _EXEC_RE.search(line)
        if m:
            exec_path = Path(m.group("path"))
            cand = _sibling_python(exec_path.parent)
            if cand:
                return cand
    return None


def _sibling_python(bindir: Path) -> Optional[Path]:
    """Return the python executable inside *bindir*, if any."""
    for name in ("python3", "python"):
        cand = bindir / name
        if cand.exists():
            return cand
    return None


def detect_hermes_python(explicit: Optional[str] = None) -> Optional[Path]:
    """Best-effort: locate the Python interpreter Hermes runs under.

    Resolution order:
      1. *explicit* arg / ``HERMES_PYTHON`` env (if it exists),
      2. follow the ``hermes`` launcher on PATH (shim or console script),
      3. None (caller should ask the user).
    """
    # 1) explicit
    cand = explicit or os.environ.get("HERMES_PYTHON")
    if cand:
        p = Path(cand)
        if p.exists():
            return p

    # 2) follow the `hermes` launcher
    hermes = shutil.which("hermes")
    if hermes:
        launcher = Path(hermes)
        py = _python_for_launcher(launcher)
        if py:
            return py
        # launcher resolves (via symlink) into a venv bin dir? try sibling
        real = launcher.resolve()
        sib = _sibling_python(real.parent)
        if sib:
            return sib

    return None


# ---------------------------------------------------------------------------
# Plugins dir / symlink
# ---------------------------------------------------------------------------

def default_user_plugins_dir() -> Path:
    """``$HERMES_HOME/plugins`` (default ``~/.hermes/plugins``)."""
    home = os.environ.get("HERMES_HOME")
    base = Path(home) if home else (Path(os.path.expanduser("~")) / ".hermes")
    return base / "plugins"


def plugin_link_path() -> Path:
    """Target location Hermes scans: ``<plugins>/hy-memory``."""
    return default_user_plugins_dir() / "hy-memory"


def package_source_dir(python: Optional[Path] = None) -> Path:
    """Directory of the installed ``hy_memory_hermes`` package.

    If *python* is given, ask THAT interpreter where the package lives (so we
    symlink the copy inside Hermes' venv, not our own). Otherwise fall back to
    this process's own package location.
    """
    if python is not None:
        import subprocess
        out = subprocess.run(
            [str(python), "-c",
             "import hy_memory_hermes, os; print(os.path.dirname(hy_memory_hermes.__file__))"],
            capture_output=True, text=True,
        )
        path = out.stdout.strip()
        if out.returncode == 0 and path:
            return Path(path)
        raise RuntimeError(
            f"hy_memory_hermes is not importable by {python}.\n"
            f"{out.stderr.strip()}"
        )
    # our own location
    here = Path(__file__).resolve().parent
    return here


def link_plugin(source_dir: Path, link_path: Optional[Path] = None,
                *, force: bool = True) -> Path:
    """Create/refresh the symlink ``<plugins>/hy-memory`` → *source_dir*.

    Returns the link path. Idempotent: if it already points at *source_dir*
    nothing changes. With *force*, replaces a wrong/stale link or directory.
    """
    link = link_path or plugin_link_path()
    link.parent.mkdir(parents=True, exist_ok=True)

    if link.is_symlink():
        try:
            if link.resolve() == source_dir.resolve():
                return link  # already correct
        except OSError:
            pass  # dangling symlink → fall through to replace
        if force:
            link.unlink()
        else:
            raise FileExistsError(f"{link} already exists (use force=True)")
    elif link.exists():
        # a real directory/file is in the way
        if not force:
            raise FileExistsError(f"{link} already exists (use force=True)")
        if link.is_dir():
            shutil.rmtree(link)
        else:
            link.unlink()

    link.symlink_to(source_dir, target_is_directory=True)
    return link


# ---------------------------------------------------------------------------
# SDK importability check
# ---------------------------------------------------------------------------

def sdk_importable(python: Path) -> bool:
    """True if `import hy_memory` works under *python*."""
    import subprocess
    out = subprocess.run(
        [str(python), "-c", "import hy_memory"],
        capture_output=True, text=True,
    )
    return out.returncode == 0


def plugin_version(python: Path) -> Optional[str]:
    """Return the installed `hermes-hy-memory` version under *python*, or None.

    Uses `python -I` (isolated) so a stray `*.egg-info` in the current working
    directory can't shadow the venv's real dist-info — otherwise the version we
    read (to decide whether to upgrade) could be wrong. `-I` still resolves the
    interpreter's own site-packages, which is exactly what we want to inspect.
    """
    return _dist_version(python, "hermes-hy-memory")


def sdk_version(python: Path) -> Optional[str]:
    """Return the installed `hy-memory` SDK version under *python*, or None."""
    return _dist_version(python, "hy-memory")


def _dist_version(python: Path, dist: str) -> Optional[str]:
    import subprocess
    out = subprocess.run(
        [str(python), "-I", "-c",
         f"import importlib.metadata as m; print(m.version('{dist}'))"],
        capture_output=True, text=True,
    )
    v = out.stdout.strip()
    return v if (out.returncode == 0 and v) else None


def this_version() -> Optional[str]:
    """Version of the currently-running plugin package (for compare/upgrade)."""
    try:
        import importlib.metadata as m
        return m.version("hermes-hy-memory")
    except Exception:
        # fall back to __init__ __version__
        try:
            from . import __version__  # type: ignore
            return __version__
        except Exception:
            return None


def install_into(python: Path, *, upgrade: bool = False) -> List[str]:
    """Install/upgrade `hermes-hy-memory` (+ the `hy-memory` SDK) into *python*.

    Prefers `uv pip` (Hermes venvs created by uv often lack pip), falls back
    to `python -m pip`. Returns the command that was run (for logging).
    Raises RuntimeError on failure.

    NOTE: we list BOTH packages explicitly. `-U hermes-hy-memory` alone upgrades
    only the named package — pip/uv will leave an already-"good enough"
    dependency (the `hy-memory` SDK) untouched even when a newer release exists.
    Since the plugin and SDK ship fixes together, the SDK must upgrade too.
    """
    import subprocess
    # plugin first (so its dependency floor is considered), SDK second
    pkgs = ["hermes-hy-memory", "hy-memory"]
    flags = ["-U"] if upgrade else []

    uv = shutil.which("uv")
    attempts: List[List[str]] = []
    if uv:
        attempts.append([uv, "pip", "install", "--python", str(python), *flags, *pkgs])
    attempts.append([str(python), "-m", "pip", "install", *flags, *pkgs])

    last_err = ""
    for cmd in attempts:
        out = subprocess.run(cmd, capture_output=True, text=True)
        if out.returncode == 0:
            return cmd
        last_err = (out.stderr or out.stdout or "").strip()
    raise RuntimeError(f"install failed (last: {last_err[:500]})")
