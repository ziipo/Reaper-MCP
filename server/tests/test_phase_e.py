"""Phase E: robustness & safety — clamps, error taxonomy, watchdog."""

import time

import pytest

from reaper_mcp import server, tools
from reaper_mcp.bridge import BridgeFrozenError, ReaperBridge


# -- value clamping ----------------------------------------------------------


def test_pan_clamps_small_overshoot(bridge):
    tools.add_track(bridge, "T")
    # 1.0001 is float slop -> silently clamped to 1.0
    res = tools.set_track_pan(bridge, 0, 1.0001)
    assert res["pan"] == 1.0


def test_pan_rejects_gross_out_of_range(bridge):
    tools.add_track(bridge, "T")
    with pytest.raises(ValueError):
        tools.set_track_pan(bridge, 0, 5.0)


def test_fx_param_clamps(bridge):
    tools.add_track(bridge, "T")
    # within slop -> clamped
    tools.set_fx_param(bridge, 0, 0, "Gain-Band 2", 1.0001)
    with pytest.raises(ValueError):
        tools.set_fx_param(bridge, 0, 0, "Gain-Band 2", 3.0)


# -- error taxonomy ----------------------------------------------------------


def test_classify_codes():
    assert server._classify("no track at index 9") == "NOT_FOUND"
    assert server._classify("pan=5 is out of range [-1, 1]") == "INVALID_ARG"
    assert server._classify("heartbeat is stale; dialog") == "BRIDGE_FROZEN"
    assert server._classify("Reaper bridge is not running") == "BRIDGE_DOWN"
    assert server._classify("Timed out after 5s") == "TIMEOUT"
    assert server._classify("project is untitled") == "NEEDS_PATH"
    assert server._classify("something weird") == "REAPER_ERROR"


# -- dialog watchdog ---------------------------------------------------------


def test_watchdog_detects_frozen_bridge(tmp_path):
    """If the heartbeat mtime is stale while awaiting a response (no responder),
    the watchdog raises BridgeFrozenError instead of waiting out the full timeout.
    """
    import os
    import uuid

    bdir = tmp_path / "frozen"
    bdir.mkdir()
    hb = bdir / "heartbeat"
    hb.write_text("x")
    # Make the heartbeat's mtime old (freshness is judged by mtime, not content).
    old = time.time() - 100
    os.utime(hb, (old, old))

    b = ReaperBridge(bridge_dir=bdir, timeout=5.0)
    rid = uuid.uuid4().hex
    b._write_request_atomic(rid, {"id": rid, "calls": []})

    t0 = time.time()
    with pytest.raises(BridgeFrozenError):
        b._await_response(rid)
    # should fail fast (watchdog), well before the 5s timeout
    assert time.time() - t0 < 1.0
