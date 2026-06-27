"""Phase A (object model) + Phase B (editing) tests against the FakeLua responder."""

import pytest

from reaper_mcp import tools


def _setup_three(bridge):
    for n in ("Chords", "Bass", "Drums"):
        tools.add_track(bridge, n)


# -- Phase A ----------------------------------------------------------------


def test_describe_project(bridge):
    _setup_three(bridge)
    desc = tools.describe_project(bridge)
    assert desc["track_count"] == 3
    assert [t["name"] for t in desc["tracks"]] == ["Chords", "Bass", "Drums"]
    # every track carries a stable GUID
    assert all(t["guid"].startswith("{") for t in desc["tracks"])


def test_guid_survives_reorder(bridge):
    _setup_three(bridge)
    bass_guid = tools.get_track_guid(bridge, 1)
    # move Bass (index 1) to the front
    tools.move_track(bridge, bass_guid, 0)
    desc = tools.describe_project(bridge, include_items=False, include_fx=False)
    # the GUID still resolves to the (now relocated) Bass track
    assert desc["tracks"][0]["guid"] == bass_guid
    assert desc["tracks"][0]["name"] == "Bass"


def test_addressing_by_guid(bridge):
    _setup_three(bridge)
    guid = tools.get_track_guid(bridge, 2)
    tools.set_track_pan(bridge, guid, -0.5)
    desc = tools.describe_project(bridge, include_items=False, include_fx=False)
    assert desc["tracks"][2]["pan"] == -0.5


# -- Phase B: track editing -------------------------------------------------


def test_track_pan_solo_arm(bridge):
    tools.add_track(bridge, "X")
    tools.set_track_pan(bridge, 0, 0.25)
    tools.set_track_solo(bridge, 0, True)
    tools.set_track_arm(bridge, 0, True)
    desc = tools.describe_project(bridge, include_items=False, include_fx=False)
    t = desc["tracks"][0]
    assert t["pan"] == 0.25 and t["soloed"] is True and t["armed"] is True


def test_set_track_color(bridge):
    tools.add_track(bridge, "X")
    res = tools.set_track_color(bridge, 0, 230, 140, 40)
    assert res["rgb"] == [230, 140, 40]


# -- Phase B: items ---------------------------------------------------------


def test_item_bounds_and_delete(bridge):
    tools.add_track(bridge, "T")
    tools.add_midi_clip(bridge, 0, 0.0, 4.0, [{"start_qn": 0, "end_qn": 1, "pitch": 60}])
    res = tools.set_item_bounds(bridge, 0, 0, position=1.0, length=2.0)
    assert res["length"] == 2.0
    tools.delete_item(bridge, 0, 0)
    desc = tools.describe_project(bridge, include_fx=False)
    assert desc["tracks"][0]["item_count"] == 0


def test_move_item_to_track(bridge):
    tools.add_track(bridge, "A")
    tools.add_track(bridge, "B")
    tools.add_midi_clip(bridge, 0, 0.0, 4.0, [{"start_qn": 0, "end_qn": 1, "pitch": 60}])
    tools.move_item_to_track(bridge, 0, 0, 1)
    desc = tools.describe_project(bridge, include_fx=False)
    assert desc["tracks"][0]["item_count"] == 0
    assert desc["tracks"][1]["item_count"] == 1


# -- Phase B: MIDI ----------------------------------------------------------


def test_midi_read_edit_delete(bridge):
    tools.add_track(bridge, "M")
    tools.add_midi_clip(bridge, 0, 0.0, 4.0, [
        {"start_qn": 0, "end_qn": 1, "pitch": 60},
        {"start_qn": 1, "end_qn": 2, "pitch": 64},
    ])
    notes = tools.get_notes(bridge, 0, 0)
    assert [n["pitch"] for n in notes] == [60, 64]

    tools.set_note(bridge, 0, 0, 0, {"pitch": 72})
    assert tools.get_notes(bridge, 0, 0)[0]["pitch"] == 72

    tools.add_notes(bridge, 0, 0, [{"start_qn": 2, "end_qn": 3, "pitch": 67}])
    assert len(tools.get_notes(bridge, 0, 0)) == 3

    tools.delete_note(bridge, 0, 0, 0)
    assert len(tools.get_notes(bridge, 0, 0)) == 2


# -- Phase B: markers -------------------------------------------------------


def test_markers(bridge):
    tools.add_marker(bridge, 0.0, "Intro")
    r = tools.add_marker(bridge, 4.0, "Loop", is_region=True, region_end=8.0)
    ms = tools.list_markers(bridge)
    assert len(ms) == 2
    assert {m["name"] for m in ms} == {"Intro", "Loop"}
    tools.delete_marker(bridge, r["index"], is_region=True)
    assert len(tools.list_markers(bridge)) == 1


def test_set_cursor(bridge):
    assert tools.set_cursor(bridge, 5.5)["cursor"] == 5.5
