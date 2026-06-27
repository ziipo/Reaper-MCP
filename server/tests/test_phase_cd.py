"""Phase C (FX/automation/sends) + Phase D (render/project) tests."""

import pytest

from reaper_mcp import tools


def _track(bridge, name="T"):
    tools.add_track(bridge, name)


# -- Phase C: FX --------------------------------------------------------------


def test_list_fx_params(bridge):
    _track(bridge)
    params = tools.list_fx_params(bridge, 0, 0)
    assert params and params[0]["name"] == "Gain-Band 2"


def test_set_fx_param_by_name(bridge):
    _track(bridge)
    res = tools.set_fx_param(bridge, 0, 0, "Gain-Band 2", 0.42)
    assert res["param_name"] == "Gain-Band 2"
    assert res["value"] == "-1.5"


def test_set_fx_param_no_match(bridge):
    _track(bridge)
    with pytest.raises(RuntimeError):
        tools.set_fx_param(bridge, 0, 0, "nomatch", 0.5)


def test_fx_enabled_and_delete(bridge):
    _track(bridge)
    assert tools.set_fx_enabled(bridge, 0, 0, False)["enabled"] is False
    assert tools.delete_fx(bridge, 0, 0)["deleted"] is True


# -- Phase C: envelopes -------------------------------------------------------


def test_write_read_envelope(bridge):
    _track(bridge)
    spec = ["track", "Volume"]
    pts = [{"time": 0.0, "value": 0.0}, {"time": 2.0, "value": 1.0}]
    assert tools.write_envelope(bridge, 0, spec, pts)["points_written"] == 2
    back = tools.read_envelope(bridge, 0, spec)
    assert [p["value"] for p in back] == [0.0, 1.0]


def test_fx_envelope_spec(bridge):
    _track(bridge)
    spec = ["fx", 0, "Gain-Band 2"]
    pts = [{"time": 0.0, "value": 0.5}, {"time": 4.0, "value": 0.3}]
    assert tools.write_envelope(bridge, 0, spec, pts)["points_written"] == 2


# -- Phase C: sends -----------------------------------------------------------


def test_sends_lifecycle(bridge):
    tools.add_track(bridge, "Src")
    tools.add_track(bridge, "Dest")
    res = tools.add_send(bridge, 0, 1)
    assert res["send_index"] == 0
    sends = tools.list_sends(bridge, 0)
    assert sends[0]["name"] == "Dest"
    tools.set_send_value(bridge, 0, 0, "D_VOL", 0.5)
    assert tools.list_sends(bridge, 0)[0]["volume"] == 0.5
    tools.remove_send(bridge, 0, 0)
    assert tools.list_sends(bridge, 0) == []


# -- Phase D: render / project ------------------------------------------------


def test_render_returns_exists(bridge, tmp_path):
    res = tools.render(bridge, str(tmp_path), "t999.wav", 5.0, "wav")
    assert res["path"].endswith("t999.wav")
    assert res["exists"] is True


def test_project_info(bridge):
    info = tools.project_info(bridge)
    assert "name" in info and "change_count" in info


def test_save_project(bridge):
    res = tools.save_project(bridge)
    assert res["name"] == "proj"


def test_new_and_open_project(bridge):
    assert tools.new_project(bridge)["new_project"] is True
    assert tools.open_project(bridge, "/tmp/x.rpp")["opened"] == "opened"
