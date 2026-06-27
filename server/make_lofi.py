"""Compose a basic LoFi loop in the running Reaper project and render it to MP3.

Layout (already created): track 0 Chords (ReaSynth+ReaEQ), 1 Bass (ReaSynth),
2 Drums (ReaSynth). This fills them with MIDI and renders.

Key: D minor, 72 BPM, 4 bars. Progression: Dm9 - Gm9 - Cmaj7 - A7(b9)-ish,
a lazy ii-style loop. Quarter-note positions; 4/4 so a bar = 4 QN.
"""

from pathlib import Path

from reaper_mcp import tools
from reaper_mcp.bridge import ReaperBridge


def note(start_qn, dur_qn, pitch, vel=80, chan=0):
    return {
        "start_qn": start_qn,
        "end_qn": start_qn + dur_qn,
        "pitch": pitch,
        "vel": vel,
        "chan": chan,
    }


# MIDI pitch helpers (C4 = 60)
D3, F3, A3, C4, E4, G4 = 50, 53, 57, 60, 64, 67
D4, F4, A4 = 62, 65, 69
# chord tones per bar (root, then a soft 7th/9th voicing in the mid register)
CHORDS = [
    # bar 0: Dm9  -> D F A C E
    [D4, F4, A4, C4 + 12 - 12, E4],
    # bar 1: Gm9  -> G Bb D F A
    [55, 58, 62, 65, 69],
    # bar 2: Cmaj7 -> C E G B
    [60, 64, 67, 71],
    # bar 3: A7b9 -> A C# G Bb
    [57, 61, 67, 70],
]
BASS_ROOTS = [D3, 43, 48, 45]  # D, G, C, A in the low register
BAR = 4.0  # quarter notes per bar


def build_chords():
    notes = []
    for bar, tones in enumerate(CHORDS):
        base = bar * BAR
        # Lay the chord as a soft held pad on beat 1, plus a gentle stab on beat 3.
        for t in tones:
            notes.append(note(base + 0.0, 3.5, t, vel=64))
            notes.append(note(base + 2.0, 1.5, t, vel=52))
    return notes


def build_bass():
    notes = []
    for bar, root in enumerate(BASS_ROOTS):
        base = bar * BAR
        # Simple lazy bass: root on 1, root on 2.5, fifth on 4.
        notes.append(note(base + 0.0, 1.5, root, vel=92))
        notes.append(note(base + 2.5, 1.0, root, vel=80))
        notes.append(note(base + 3.5, 0.5, root + 7, vel=78))
    return notes


def build_drums():
    # ReaSynth is monophonic-ish per note; emulate a kit with pitched hits:
    # kick = low C (36), snare = D (38), hat = F#5 (78). Classic boom-bap feel.
    KICK, SNARE, HAT = 36, 38, 78
    notes = []
    for bar in range(4):
        base = bar * BAR
        # kick on 1 and the "and" of 2 (lazy)
        notes.append(note(base + 0.0, 0.25, KICK, vel=110))
        notes.append(note(base + 2.5, 0.25, KICK, vel=96))
        # snare (backbeat) on 2 and 4
        notes.append(note(base + 1.0, 0.25, SNARE, vel=100))
        notes.append(note(base + 3.0, 0.25, SNARE, vel=100))
        # hats on every off-beat eighth, softly
        q = base
        for i in range(8):
            notes.append(note(q + i * 0.5, 0.2, HAT, vel=48 + (8 if i % 2 else 0)))
    return notes


def main():
    b = ReaperBridge()

    print("tempo:", tools.set_tempo(b, 72))

    print("chords:", tools.add_midi_clip(b, 0, 0.0, 16.0, build_chords()))
    print("bass:", tools.add_midi_clip(b, 1, 0.0, 16.0, build_bass()))
    print("drums:", tools.add_midi_clip(b, 2, 0.0, 16.0, build_drums()))

    # Soften: pull chords + drums down a touch for that mellow balance.
    tools.set_track_volume(b, 0, -3.0)
    tools.set_track_volume(b, 2, -5.0)

    # 4 bars at 72 BPM: 4 bars * 4 beats * (60/72) s/beat = 13.333 s. Add tail.
    length = 4 * 4 * (60.0 / 72.0)
    out_dir = str(Path("/Users/kenburleson/Projects/reaperTest/testProjects").resolve())
    print(f"length: {length:.2f}s -> rendering to {out_dir}")
    print("render:", tools.render_mp3(b, out_dir, "lofi_test.mp3", length + 1.0))


if __name__ == "__main__":
    main()
