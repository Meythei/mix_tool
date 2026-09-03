"""Quick end-to-end sanity check of analysis + render engine, no server involved."""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "backend"))

from analysis import analyze_file
from models import Project, Deck, Clip, AutomationPoint
from engine.render import render_to_wav

LIB = os.path.join(BASE, "backend", "data", "sample_library")

print("== analysis ==")
files = {}
for fname in os.listdir(LIB):
    path = os.path.join(LIB, fname)
    t0 = time.time()
    result = analyze_file(path)
    files[fname] = result
    print(f"{fname:28s} bpm={result.get('bpm')!s:8s} key={result.get('key')!s:10s} dur={result.get('duration')!s:6s} ({time.time()-t0:.1f}s)")

beat = os.path.join(LIB, "Demo Beat 128.wav")
bass = os.path.join(LIB, "Demo Bassline 124.wav")
pad = os.path.join(LIB, "Demo Pad 100.wav")
airhorn = os.path.join(LIB, "Shot Airhorn.wav")
stab = os.path.join(LIB, "Shot Synth Stab.wav")

project = Project(
    name="Smoke Test Mix",
    master_bpm=126.0,
    decks=[
        Deck(
            id="a", name="Deck A", type="track", bus="A", sync=True,
            automation={"gain": [AutomationPoint(time=0, value=0.0), AutomationPoint(time=1.5, value=1.0),
                                  AutomationPoint(time=8, value=1.0), AutomationPoint(time=10, value=0.0)]},
            reverb_send=0.15,
            clips=[Clip(id="c1", source_path=beat, source_offset=0, source_length=10,
                        source_bpm=files["Demo Beat 128.wav"].get("bpm"), timeline_start=0.0, label="beat")],
        ),
        Deck(
            id="b", name="Deck B", type="track", bus="B", sync=True, filter=-0.4,
            automation={"gain": [AutomationPoint(time=6, value=0.0), AutomationPoint(time=10, value=1.0)]},
            clips=[Clip(id="c2", source_path=bass, source_offset=0, source_length=10,
                        source_bpm=files["Demo Bassline 124.wav"].get("bpm"), timeline_start=2.0, label="bass")],
        ),
        Deck(
            id="c", name="Pad", type="track", bus="M", sync=True, reverb_send=0.35, gain=0.7,
            clips=[Clip(id="c3", source_path=pad, source_offset=0, source_length=8,
                        source_bpm=files["Demo Pad 100.wav"].get("bpm"), timeline_start=0.0, label="pad")],
        ),
        Deck(
            id="d", name="Shots", type="shot", sync=False, bus="M", reverb_send=0.2,
            clips=[
                Clip(id="s1", source_path=airhorn, source_offset=0, source_length=1.0, timeline_start=4.0, label="horn"),
                Clip(id="s2", source_path=stab, source_offset=0, source_length=0.6, timeline_start=9.0, label="stab"),
            ],
        ),
    ],
    crossfader={"value": 0.5, "automation": [AutomationPoint(time=0, value=0.0), AutomationPoint(time=10, value=1.0)]},
)
project.reverb.room_size = 0.6
project.reverb.damping = 0.4

out = os.path.join(BASE, "backend", "data", "exports", "smoke_test.wav")
print("\n== rendering ==")
t0 = time.time()
result = render_to_wav(project, out, t_start=0.0, t_end=None, max_duration=60.0)
print(f"rendered in {time.time()-t0:.2f}s ->", result)
