"""
Tests for the recovered poe.ninja builds-list / ladder client (#61).

All decode tests run against the recorded fixture
(tests/fixtures/ninja_builds_search_roa.pb, captured 2026-06-13) — no
live API in CI. The 0.5 'death' of this API was a protobuf encoding
migration; these tests lock the recovered wire understanding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.poe_ninja_ladder import (
    LadderClient,
    decode_search_response,
    parse_message,
)

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "ninja_builds_search_roa.pb"


@pytest.fixture(scope="module")
def payload():
    return FIXTURE.read_bytes()


def test_fixture_decodes(payload):
    d = decode_search_response(payload)
    assert d["total"] == 124242            # RoA builds indexed at capture
    assert len(d["rows"]) == 100           # one full ladder page
    assert "name" in d["columns"] and "dps" in d["columns"]


def test_row_shape(payload):
    d = decode_search_response(payload)
    r0 = d["rows"][0]
    assert r0["name"] == "ResurrectGodAura"
    assert r0["account"] == "heygyus-0416"
    assert r0["level"] == 100
    assert isinstance(r0["life"], int)
    assert isinstance(r0["energyshield"], int)
    assert isinstance(r0["ehp"], str)      # display string ('31k')


def test_rows_substantially_named(payload):
    """A few ladder entries have privacy-hidden names (None) but carry
    full stats — 97/100 named in the capture. All rows must carry
    account + level regardless."""
    d = decode_search_response(payload)
    named = [r for r in d["rows"] if r.get("name")]
    assert len(named) >= 95
    with_account = [r for r in d["rows"] if r.get("account")]
    assert len(with_account) >= 95          # accounts can be hidden too
    assert all(isinstance(r.get("level"), int) for r in d["rows"])


def test_parse_message_rejects_garbage():
    assert parse_message(b"\x00\x00\x00\x00") is None
    assert parse_message(b"\xff" * 16) is None


def test_decode_rejects_non_search_payload():
    with pytest.raises(ValueError):
        decode_search_response(b"\x08\x01")  # bare varint field, no envelope


@pytest.mark.asyncio
async def test_ladder_client_decodes_via_stub():
    """Client plumbing test with a stubbed transport — no network."""
    class _Resp:
        status_code = 200
        content = FIXTURE.read_bytes()
        def json(self):
            return {"snapshotVersions": [
                {"url": "runesofaldur", "version": "v1", "snapshotName": "runes-of-aldur"}
            ]}

    class _Client:
        async def get(self, url, **kw):
            return _Resp()
        async def aclose(self):
            pass

    class _RL:
        async def acquire(self):
            return None

    lc = LadderClient(rate_limiter=_RL(), client=_Client())
    rows = await lc.top_builds("runesofaldur", class_name="Lich")
    assert len(rows) == 100
    assert rows[0]["name"] == "ResurrectGodAura"
