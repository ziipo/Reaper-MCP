"""Tool-layer tests against the FakeLua responder."""

import math

import pytest

from reaper_mcp import tools


def test_db_amp_roundtrip():
    for db in (-12.0, -6.0, 0.0, 3.0):
        assert math.isclose(tools.amp_to_db(tools.db_to_amp(db)), db, abs_tol=1e-6)
    assert tools.db_to_amp(0.0) == 1.0


def test_add_and_list_tracks(bridge):
    assert tools.list_tracks(bridge) == []
    tools.add_track(bridge, "Chords")
    tools.add_track(bridge, "Bass")
    tl = tools.list_tracks(bridge)
    assert [t["name"] for t in tl] == ["Chords", "Bass"]
    assert tl[0]["index"] == 0 and tl[0]["volume_db"] == 0.0 and tl[0]["muted"] is False


def test_set_name_volume_mute(bridge):
    tools.add_track(bridge, "X")
    tools.set_track_name(bridge, 0, "Kick")
    assert tools.get_track_name(bridge, 0) == "Kick"
    tools.set_track_volume(bridge, 0, -6.0)
    tools.set_track_mute(bridge, 0, True)
    t = tools.list_tracks(bridge)[0]
    assert math.isclose(t["volume_db"], -6.0, abs_tol=0.1)
    assert t["muted"] is True


def test_delete_track(bridge):
    for n in ("A", "B", "C"):
        tools.add_track(bridge, n)
    tools.delete_track(bridge, 1)  # remove "B"
    assert [t["name"] for t in tools.list_tracks(bridge)] == ["A", "C"]


def test_delete_track_bad_index(bridge):
    tools.add_track(bridge, "A")
    with pytest.raises(ValueError):
        tools.delete_track(bridge, 5)


def test_delete_all_tracks(bridge):
    for n in ("A", "B"):
        tools.add_track(bridge, n)
    res = tools.delete_all_tracks(bridge)
    assert res["deleted"] == 2
    assert tools.list_tracks(bridge) == []


def test_transport(bridge):
    assert tools.get_play_state(bridge)["state"] == "stopped"
    tools.transport_play(bridge)
    assert tools.get_play_state(bridge)["state"] == "playing"
    tools.transport_stop(bridge)
    assert tools.get_play_state(bridge)["state"] == "stopped"


def test_set_tempo(bridge):
    assert tools.set_tempo(bridge, 72)["bpm"] == 72


def test_add_fx(bridge):
    tools.add_track(bridge, "Synth")
    res = tools.add_fx(bridge, 0, "ReaSynth")
    assert res["fx_index"] == 0 and res["fx_name"] == "ReaSynth"


def test_add_midi_clip(bridge):
    tools.add_track(bridge, "Chords")
    notes = [
        {"start_qn": 0.0, "end_qn": 1.0, "pitch": 60},
        {"start_qn": 1.0, "end_qn": 2.0, "pitch": 64, "vel": 70},
    ]
    res = tools.add_midi_clip(bridge, 0, 0.0, 4.0, notes)
    assert res["notes"] == 2 and res["item_index"] == 0


def test_render_mp3_returns_path(bridge, tmp_path):
    res = tools.render_mp3(bridge, str(tmp_path), "t999_out.mp3", 5.0)
    assert res["path"].endswith("t999_out.mp3")


def test_call_reascript_passthrough(bridge):
    assert tools.call_reascript(bridge, "GetAppVersion") == ["fake/test"]
    assert tools.call_reascript(bridge, "CountTracks", [0]) == [0]
