"""Music-theory helpers (Phase F): names → MIDI pitches, scales, chords,
progressions, and humanize/swing. Pure functions with no Reaper dependency, so
they're trivially testable; the tools layer turns their output into notes.

MIDI note numbers: C4 = 60 (Reaper/Cockos convention). Octave n's C = 12*(n+1).
"""

from __future__ import annotations

import random

# Pitch class for each note name.
NOTE_TO_PC = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4,
    "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11, "CB": 11,
}

# Scale interval patterns (semitones from the root).
SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],          # natural minor
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "major_pentatonic": [0, 2, 4, 7, 9],
    "blues": [0, 3, 5, 6, 7, 10],
    "chromatic": list(range(12)),
}

# Chord interval patterns (semitones from the root).
CHORDS = {
    "maj": [0, 4, 7], "min": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8],
    "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10], "7": [0, 4, 7, 10],
    "dim7": [0, 3, 6, 9], "m7b5": [0, 3, 6, 10], "minMaj7": [0, 3, 7, 11],
    "maj9": [0, 4, 7, 11, 14], "min9": [0, 3, 7, 10, 14], "9": [0, 4, 7, 10, 14],
    "add9": [0, 4, 7, 14], "sus2": [0, 2, 7], "sus4": [0, 5, 7],
    "6": [0, 4, 7, 9], "min6": [0, 3, 7, 9],
}

# Roman-numeral degrees → (scale-degree index, default chord quality by scale).
ROMAN = {
    "I": 0, "II": 1, "III": 2, "IV": 3, "V": 4, "VI": 5, "VII": 6,
    "i": 0, "ii": 1, "iii": 2, "iv": 3, "v": 4, "vi": 5, "vii": 6,
}


def note_to_midi(name: str) -> int:
    """Parse a note name like 'C4', 'F#3', 'Bb5' into a MIDI number (C4=60)."""
    s = name.strip()
    # split trailing octave (may be negative)
    i = len(s)
    while i > 0 and (s[i - 1].isdigit() or s[i - 1] == "-"):
        i -= 1
    pc_part, oct_part = s[:i].upper(), s[i:]
    if pc_part not in NOTE_TO_PC:
        raise ValueError(f"bad note name: {name!r}")
    octave = int(oct_part) if oct_part else 4
    return 12 * (octave + 1) + NOTE_TO_PC[pc_part]


def scale_notes(root: str, scale: str, octaves: int = 1, start_octave: int = 4) -> list[int]:
    """Return MIDI pitches for a scale across `octaves`, starting at `start_octave`."""
    scale = scale.lower()
    if scale not in SCALES:
        raise ValueError(f"unknown scale: {scale!r}; known: {sorted(SCALES)}")
    root_pc = NOTE_TO_PC[root.strip().upper()]
    base = 12 * (start_octave + 1) + root_pc
    out = []
    for o in range(octaves):
        for iv in SCALES[scale]:
            out.append(base + 12 * o + iv)
    out.append(base + 12 * octaves)  # cap with the octave
    return out


def chord_notes(root: str, quality: str = "maj", octave: int = 4,
                inversion: int = 0) -> list[int]:
    """Return MIDI pitches for a chord. `inversion` rotates the lowest notes up."""
    quality = quality if quality in CHORDS else quality.lower()
    if quality not in CHORDS:
        raise ValueError(f"unknown chord quality: {quality!r}; known: {sorted(CHORDS)}")
    base = note_to_midi(f"{root}{octave}")
    notes = [base + iv for iv in CHORDS[quality]]
    for _ in range(inversion % max(len(notes), 1)):
        notes = notes[1:] + [notes[0] + 12]
    return notes


def progression(root: str, scale: str, romans: list[str], octave: int = 4,
                seventh: bool = False) -> list[list[int]]:
    """Build diatonic chords for a list of roman numerals in a key.

    Each roman numeral picks a scale degree; the chord is built by stacking
    thirds within the scale (so quality follows the key). Lowercase vs uppercase
    is accepted but quality is derived diatonically, not from the case.
    """
    scale = scale.lower()
    if scale not in SCALES:
        raise ValueError(f"unknown scale: {scale!r}")
    degrees = SCALES[scale]
    n = len(degrees)
    root_pc = NOTE_TO_PC[root.strip().upper()]
    base = 12 * (octave + 1) + root_pc

    def degree_pitch(deg_index: int) -> int:
        octs, idx = divmod(deg_index, n)
        return base + 12 * octs + degrees[idx]

    chords = []
    for r in romans:
        key = r.strip().rstrip("o°+").lstrip("#b")
        if key not in ROMAN:
            raise ValueError(f"bad roman numeral: {r!r}")
        d = ROMAN[key]
        steps = [0, 2, 4] + ([6] if seventh else [])
        chords.append([degree_pitch(d + s) for s in steps])
    return chords


def make_notes(pitches_per_step: list[list[int]], step_qn: float = 4.0,
               dur_qn: float | None = None, start_qn: float = 0.0,
               vel: int = 80) -> list[dict]:
    """Lay a sequence of chords/notes onto a timeline, one group per step.

    pitches_per_step: list of pitch-lists (a chord per step). step_qn is the gap
    between steps (default a bar of 4/4). Returns add_midi_clip-style note dicts.
    """
    if dur_qn is None:
        dur_qn = step_qn
    notes = []
    for i, pitches in enumerate(pitches_per_step):
        t = start_qn + i * step_qn
        for p in pitches:
            notes.append({"start_qn": t, "end_qn": t + dur_qn, "pitch": p, "vel": vel})
    return notes


def humanize(notes: list[dict], timing_qn: float = 0.02, vel_amount: int = 12,
             seed: int | None = None) -> list[dict]:
    """Add subtle random timing/velocity variation so parts feel less robotic."""
    rng = random.Random(seed)
    out = []
    for n in notes:
        jitter = rng.uniform(-timing_qn, timing_qn)
        dv = rng.randint(-vel_amount, vel_amount)
        s = max(0.0, n["start_qn"] + jitter)
        e = max(s + 0.01, n["end_qn"] + jitter)
        out.append({**n, "start_qn": s, "end_qn": e,
                    "vel": max(1, min(127, int(n.get("vel", 80)) + dv))})
    return out


def swing(notes: list[dict], amount: float = 0.5, grid_qn: float = 0.5) -> list[dict]:
    """Apply swing by delaying off-grid (odd) subdivisions.

    `amount` 0..1 (0.5 ≈ triplet feel). `grid_qn` is the subdivision (0.5 = 8ths).
    A note landing on an odd grid slot is pushed later by up to grid_qn*amount/2.
    """
    out = []
    push = grid_qn * amount * 0.5
    for n in notes:
        slot = round(n["start_qn"] / grid_qn)
        delay = push if slot % 2 == 1 else 0.0
        out.append({**n, "start_qn": n["start_qn"] + delay,
                    "end_qn": n["end_qn"] + delay})
    return out
