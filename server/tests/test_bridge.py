"""Transport-layer tests for ReaperBridge against the FakeLua responder."""

import time

import pytest

from reaper_mcp.bridge import BridgeError, Call, ReaperBridge


def test_single_call(bridge):
    assert bridge.call("GetPlayState") == [0]


def test_multi_return(bridge, fake_reaper):
    fake_reaper.tracks.append({"name": "Drums", "vol": 1.0, "mute": 0.0,
                               "items": [], "fx": []})
    res = bridge.call("GetSetMediaTrackInfo_String", 0, "P_NAME", "", False)
    assert res == [True, "Drums"]


def test_batch(bridge):
    results = bridge.call_many([Call("CountTracks", [0]), Call("GetPlayState", [])])
    assert results == [[0], [0]]


def test_error_propagation(bridge):
    with pytest.raises(BridgeError) as ei:
        bridge.call("NoSuchFunction")
    assert "NoSuchFunction" in str(ei.value)


def test_down_detection(tmp_path):
    # bridge dir with no heartbeat at all
    bdir = tmp_path / "empty"
    bdir.mkdir()
    b = ReaperBridge(bridge_dir=bdir, timeout=0.5)
    with pytest.raises(BridgeError) as ei:
        b.call("GetPlayState")
    assert "not running" in str(ei.value).lower()


def test_timeout_and_no_orphan(tmp_path):
    # A bridge dir with a fresh heartbeat but no responder: passes the liveness
    # check, then times out waiting for a response.
    bdir = tmp_path / "stalled"
    bdir.mkdir()
    (bdir / "heartbeat").write_text(str(time.time()))
    b = ReaperBridge(bridge_dir=bdir, timeout=0.4)
    with pytest.raises(BridgeError) as ei:
        b.call("GetPlayState")
    assert "timed out" in str(ei.value).lower()
    # the orphaned request must be cleaned up
    assert not list(bdir.glob("*.req.json"))
