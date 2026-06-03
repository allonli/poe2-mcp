"""Tests for src.launcher_helpers.check_code_freshness (the launcher's
self-update logic).

We test the early-exit guards and a smoke run in this repo. The
network-bound paths (fetch / fast-forward merge) need a live git remote
to exercise end-to-end and are intentionally out of scope here — manual
verification gates those.

Imports src.launcher_helpers directly (light-module pattern) to avoid
launch.py's import-time sys.stdout wrap, which interacts badly with
pytest capture across tests.
"""
from __future__ import annotations

import shutil as _shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _capture_sink():
    """Return (sink_fn, captured_list) for asserting on routed messages."""
    captured: list[str] = []
    return (lambda text: captured.append(text), captured)


def test_env_var_skip_short_circuits_before_git(monkeypatch):
    """POE2_MCP_NO_CODE_CHECK=1 must bail before any git work happens.

    Regression guard: if a future refactor reorders the env-var check below
    the shutil.which lookup, this test catches it.
    """
    from src.launcher_helpers import check_code_freshness

    monkeypatch.setenv('POE2_MCP_NO_CODE_CHECK', '1')
    which_calls: list[str] = []
    monkeypatch.setattr(
        _shutil, 'which', lambda name: which_calls.append(name) or None
    )

    info, info_msgs = _capture_sink()
    check_code_freshness(print_info=info)  # must not raise

    assert which_calls == [], (
        f'shutil.which should not be called when env-skip is active; got {which_calls}'
    )
    assert any('POE2_MCP_NO_CODE_CHECK=1' in m for m in info_msgs), info_msgs


def test_git_missing_bails_with_warning(monkeypatch, tmp_path):
    """If git is not on PATH, the function must warn and return — never crash."""
    from src.launcher_helpers import check_code_freshness

    monkeypatch.delenv('POE2_MCP_NO_CODE_CHECK', raising=False)
    monkeypatch.delenv('POE2_MCP_AUTO_UPDATE', raising=False)

    which_calls: list[str] = []
    def _no_git(name):
        which_calls.append(name)
        return None
    monkeypatch.setattr(_shutil, 'which', _no_git)
    monkeypatch.chdir(tmp_path)

    warn, warn_msgs = _capture_sink()
    check_code_freshness(print_warning=warn)  # must not raise

    assert 'git' in which_calls, 'should have looked up git on PATH'
    assert any('git not in PATH' in m for m in warn_msgs), warn_msgs


def test_no_git_repo_bails_gracefully(monkeypatch, tmp_path):
    """In a directory that's not a git checkout, function returns cleanly."""
    from src.launcher_helpers import check_code_freshness

    monkeypatch.delenv('POE2_MCP_NO_CODE_CHECK', raising=False)
    monkeypatch.delenv('POE2_MCP_AUTO_UPDATE', raising=False)
    monkeypatch.chdir(tmp_path)

    info, info_msgs = _capture_sink()
    warn, warn_msgs = _capture_sink()
    check_code_freshness(print_info=info, print_warning=warn)  # must not raise

    # One of the two paths fired: either "not in a git checkout" or "git not
    # in PATH" (depending on CI environment). Both are acceptable graceful
    # exits — what matters is that the function returned without raising.
    all_msgs = info_msgs + warn_msgs
    assert any(
        'git checkout' in m or 'git not in PATH' in m for m in all_msgs
    ), all_msgs


def test_runs_to_completion_in_this_repo(monkeypatch):
    """Smoke test: real call from the repo root, expect no exception.

    Path taken depends on current branch and origin reachability. The
    contract under test is: function NEVER raises, regardless of state.
    """
    from src.launcher_helpers import check_code_freshness

    monkeypatch.delenv('POE2_MCP_NO_CODE_CHECK', raising=False)
    monkeypatch.delenv('POE2_MCP_AUTO_UPDATE', raising=False)

    check_code_freshness()  # default no-op sinks; just verify no raise
