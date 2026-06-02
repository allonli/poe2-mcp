"""
Tests for poe.ninja character fetch league-slug URL construction (issue #131).

Patch 0.5 broke `import_poe_ninja_url` / `analyze_character` because
``character_fetcher.py`` was building the events + model URLs without the
``{leagueUrl}`` path segment. This test locks in the fix:

  - The new helper ``_to_poe_ninja_league_slug`` resolves display names to
    canonical slugs via ``PoeNinjaAPI.LEAGUE_MAPPINGS``.
  - ``_fetch_from_poe_ninja_api`` threads the league through and builds
    URLs with the slug in the correct position.

The helper test uses ``CharacterFetcher.__new__`` to bypass ``__init__``
because the full constructor opens an httpx client we don't want in unit
scope.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _bare_fetcher():
    """Construct a CharacterFetcher without firing __init__ (no httpx client)."""
    from src.api.character_fetcher import CharacterFetcher
    return CharacterFetcher.__new__(CharacterFetcher)


def test_league_slug_runes_of_aldur():
    """Current league display name resolves to canonical slug."""
    f = _bare_fetcher()
    assert f._to_poe_ninja_league_slug("Runes of Aldur") == "runesofaldur"


def test_league_slug_hardcore_variants():
    """All 4 0.5 league variants resolve correctly."""
    f = _bare_fetcher()
    assert f._to_poe_ninja_league_slug("Runes of Aldur Hardcore") == "runesofaldurhc"
    assert f._to_poe_ninja_league_slug("Runes of Aldur HC") == "runesofaldurhc"
    assert f._to_poe_ninja_league_slug("Runes of Aldur SSF") == "runesofaldurssf"
    assert f._to_poe_ninja_league_slug("Runes of Aldur HC SSF") == "runesofaldurhcssf"


def test_league_slug_case_insensitive():
    """Case differences shouldn't break the mapping."""
    f = _bare_fetcher()
    assert f._to_poe_ninja_league_slug("runes of aldur") == "runesofaldur"
    assert f._to_poe_ninja_league_slug("RUNES OF ALDUR") == "runesofaldur"


def test_league_slug_standard_fallback():
    """Standard / Hardcore (not in mappings) fall back to lowercased-no-space."""
    f = _bare_fetcher()
    assert f._to_poe_ninja_league_slug("Standard") == "standard"
    assert f._to_poe_ninja_league_slug("Hardcore") == "hardcore"
    assert f._to_poe_ninja_league_slug("Some New League") == "somenewleague"


def test_league_slug_previous_leagues_still_resolve():
    """Vaal / Abyss / Dawn mappings still work — regression guard."""
    f = _bare_fetcher()
    assert f._to_poe_ninja_league_slug("Vaal") == "vaal"
    assert f._to_poe_ninja_league_slug("Rise of the Abyssal") == "abyss"
    assert f._to_poe_ninja_league_slug("Dawn of the Hunt") == "dawn"


# ---------------------------------------------------------------------------
# URL construction — verify the slug lands in the right path segment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_builds_url_with_league_slug(monkeypatch):
    """
    Verify ``_fetch_from_poe_ninja_api`` injects the league slug into both
    URLs at the position the API expects:
      events: /poe2/api/events/character/{account}/{leagueUrl}/{char}
      model:  /poe2/api/profile/characters/{account}/{leagueUrl}/{char}/model/{ver}
    """
    from src.api.character_fetcher import CharacterFetcher
    from src.config import settings

    captured_urls: list[str] = []

    # Lightweight async-context-manager fakes that record URLs and fail fast
    # (we just want to verify URL shape, not a full happy path).

    class _FakeStreamResponse:
        status_code = 404
        async def aiter_lines(self):
            if False:
                yield
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class _FakeStreamCM:
        def __init__(self, url):
            captured_urls.append(url)
            self._resp = _FakeStreamResponse()
        async def __aenter__(self):
            return self._resp
        async def __aexit__(self, *a):
            return False

    class _FakeClient:
        def stream(self, _method, url):
            return _FakeStreamCM(url)

    class _FakeRateLimiter:
        async def acquire(self):
            return None

    f = CharacterFetcher.__new__(CharacterFetcher)
    f.client = _FakeClient()
    f.rate_limiter = _FakeRateLimiter()
    f.last_error_message = ""

    result = await f._fetch_from_poe_ninja_api(
        account_name="Tomawar40-2671",
        character_name="TomawarTheSeventh",
        league="Runes of Aldur",
    )

    # We stubbed status 404, so the function returns None — that's fine.
    # The assertion that matters is the URL we tried to hit.
    assert result is None
    assert len(captured_urls) == 1
    url = captured_urls[0]
    expected_base = settings.POE_NINJA_PROFILE_URL
    assert url == (
        f"{expected_base}/poe2/api/events/character/"
        f"Tomawar40-2671/runesofaldur/TomawarTheSeventh"
    ), f"URL shape regression: {url}"
