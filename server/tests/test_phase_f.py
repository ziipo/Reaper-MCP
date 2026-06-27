"""Phase F: music theory + composition helpers."""

import pytest

from reaper_mcp import music, tools


# -- pure theory --------------------------------------------------------------


def test_note_to_midi():
    assert music.note_to_midi("C4") == 60
    assert music.note_to_midi("A4") == 69
    assert music.note_to_midi("F#3") == 54
    assert music.note_to_midi("Bb5") == 82
    assert music.note_to_midi("C-1") == 0


def test_note_to_midi_bad():
    with pytest.raises(ValueError):
        music.note_to_midi("H4")


def test_chord_notes():
    assert music.chord_notes("D", "min", 4) == [62, 65, 69]
    assert music.chord_notes("C", "maj7", 4) == [60, 64, 67, 71]


def test_chord_inversion():
    base = music.chord_notes("C", "maj", 4)          # 60 64 67
    inv1 = music.chord_notes("C", "maj", 4, inversion=1)
    assert inv1 == [64, 67, 72]


def test_scale_notes():
    assert music.scale_notes("A", "minor", 1, 4) == [69, 71, 72, 74, 76, 77, 79, 81]


def test_scale_unknown():
    with pytest.raises(ValueError):
        music.scale_notes("C", "nope")


def test_progression_diatonic():
    prog = music.progression("D", "minor", ["i", "iv", "v", "VI"], 4, seventh=True)
    assert prog[0] == [62, 65, 69, 72]   # Dm7
    assert len(prog) == 4 and all(len(c) == 4 for c in prog)


def test_swing_delays_offbeats():
    notes = [{"start_qn": 0.0, "end_qn": 0.5, "pitch": 60},
             {"start_qn": 0.5, "end_qn": 1.0, "pitch": 62}]
    sw = music.swing(notes, amount=0.5, grid_qn=0.5)
    assert sw[0]["start_qn"] == 0.0           # on-beat unchanged
    assert sw[1]["start_qn"] > 0.5            # off-beat pushed later


def test_humanize_is_deterministic_with_seed():
    notes = [{"start_qn": 0.0, "end_qn": 1.0, "pitch": 60, "vel": 80}]
    a = music.humanize(notes, seed=1)
    b = music.humanize(notes, seed=1)
    assert a == b


# -- composition tools (through the fake bridge) ------------------------------


def test_add_chord_progression(bridge):
    tools.add_track(bridge, "Keys")
    res = tools.add_chord_progression(bridge, 0, "D", "minor",
                                      ["i", "iv", "v", "VI"], seventh=True)
    # 4 chords * 4 notes = 16 notes in one clip
    assert res["notes"] == 16


def test_add_scale_run(bridge):
    tools.add_track(bridge, "Run")
    res = tools.add_scale_run(bridge, 0, "C", "major", octaves=1)
    assert res["notes"] == 8  # 7 scale notes + octave cap


def test_get_scale_and_chord_no_bridge():
    assert tools.get_scale("C", "major")["pitches"][0] == 60
    assert tools.get_chord("A", "min", octave=3)["pitches"] == [57, 60, 64]
