"""Lightweight helpers for launch.py.

Lives in its own module so the launcher's testable logic doesn't drag
launch.py's import-time side effects (Windows stdout wrap, deferred src/
imports) into the test runner. Pattern documented in
docs/TESTING.md / PR #123-#124.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

# Sentinel "no-op" sinks let callers (and tests) skip print routing entirely.
_NoOp = Callable[[str], None]


def _noop(_text: str) -> None:
    pass


def check_code_freshness(
    print_success: _NoOp = _noop,
    print_warning: _NoOp = _noop,
    print_info: _NoOp = _noop,
) -> None:
    """Check whether the local code is up to date with origin/main.

    Two behavior modes via env vars:
      - POE2_MCP_NO_CODE_CHECK=1   skip entirely
      - POE2_MCP_AUTO_UPDATE=1     fast-forward merge if possible (Option B)
      - default                    notify-only (Option A)

    Failure is always non-fatal: this function never raises. Auto-update is
    conservative: skipped if not on main, working tree is dirty, or
    origin/main has diverged from local.

    print_success / print_warning / print_info default to no-ops so tests
    can call this without wiring colorized output. launch.py passes its own
    print helpers.
    """
    if os.environ.get('POE2_MCP_NO_CODE_CHECK') == '1':
        print_info("Code freshness check disabled (POE2_MCP_NO_CODE_CHECK=1)")
        return

    git = shutil.which('git')
    if not git:
        print_warning("git not in PATH; skipping code freshness check")
        return

    def _git(*args, timeout=10):
        return subprocess.run(
            [git, *args],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

    # Are we in a git checkout at all?
    try:
        repo_root = _git('rev-parse', '--show-toplevel').stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        print_info("Not running from a git checkout; skipping code freshness check")
        return

    # On which branch?
    try:
        branch = _git('-C', repo_root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_warning("Could not determine current branch; skipping code freshness check")
        return

    if branch != 'main':
        print_info(f"On branch '{branch}' (not main); skipping code freshness check")
        return

    # Fetch latest from origin/main (network-bound).
    try:
        _git('-C', repo_root, 'fetch', '--quiet', 'origin', 'main', timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_warning("Could not fetch from origin (offline?); skipping code freshness check")
        return

    # Compare local HEAD to origin/main.
    try:
        local_head = _git('-C', repo_root, 'rev-parse', 'HEAD').stdout.strip()
        remote_head = _git('-C', repo_root, 'rev-parse', 'origin/main').stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_warning("Could not compare to origin/main; skipping code freshness check")
        return

    if local_head == remote_head:
        print_success("Code is up to date with origin/main")
        return

    # How many commits behind?
    try:
        behind = _git(
            '-C', repo_root, 'rev-list', '--count', f'{local_head}..{remote_head}'
        ).stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        behind = '?'

    auto_update = os.environ.get('POE2_MCP_AUTO_UPDATE') == '1'

    if not auto_update:
        # Option A: notify only.
        print_warning(
            f"Code is {behind} commit(s) behind origin/main. Run 'git pull' to update."
        )
        print_info("Set POE2_MCP_AUTO_UPDATE=1 to enable automatic fast-forward updates.")
        return

    # Option B: auto fast-forward — only if working tree is clean.
    try:
        dirty = _git('-C', repo_root, 'status', '--porcelain').stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print_warning("Could not check working tree status; skipping auto-update")
        return

    if dirty:
        print_warning(
            f"Working tree has uncommitted changes; skipping auto-update ({behind} commit(s) behind)"
        )
        return

    try:
        _git('-C', repo_root, 'merge', '--ff-only', 'origin/main', timeout=30)
        print_success(f"Code updated: fast-forwarded {behind} commit(s) from origin/main")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print_warning(
            f"Auto fast-forward failed ({type(e).__name__}); continuing with current code"
        )
