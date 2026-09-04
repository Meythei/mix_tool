"""Data schema for a DJ Mix Studio project.

Everything is plain, JSON-serializable pydantic models. The frontend owns a
mirror of this shape in JS and PUTs the whole project document back on every
meaningful edit; the backend just validates, persists and renders it.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class AutomationPoint(BaseModel):
    time: float = 0.0          # seconds, absolute timeline position
    value: float = 0.0


# A parameter is either a constant (the "base" scalar on the deck/master) or,
# once the user has written points onto its lane, a time-varying envelope.
Automation = List[AutomationPoint]


class Clip(BaseModel):
    id: str
    source_path: str
    label: str = ""
    timeline_start: float = 0.0     # seconds, absolute timeline position
    source_offset: float = 0.0      # seconds into the source file
    source_length: float = 4.0      # seconds of source material used
    source_bpm: Optional[float] = None   # snapshot from the library at drop-time, used for sync
    loop_count: int = 1             # repeat the (stretched) unit N times back-to-back
    gain: float = 1.0               # clip trim, linear
    fade_in: float = 0.005          # seconds
    fade_out: float = 0.005         # seconds
    pitch_semitones: float = 0.0
    reverse: bool = False


class DeckAutomation(BaseModel):
    gain: Automation = Field(default_factory=list)
    filter: Automation = Field(default_factory=list)
    reverb_send: Automation = Field(default_factory=list)


class Deck(BaseModel):
    id: str
    name: str
    type: Literal["track", "shot"] = "track"
    sync: bool = True               # time-stretch clips to master_bpm
    gain: float = 1.0                # base fader, used where automation has no points
    filter: float = 0.0              # -1 (low-pass, dark) .. 0 (bypass) .. 1 (high-pass, thin)
    reverb_send: float = 0.0         # 0..1 base aux send
    bus: Literal["A", "B", "M"] = "M"   # crossfader routing; M bypasses the crossfader
    mute: bool = False
    solo: bool = False
    choke_group: Optional[int] = None   # shot decks: same group steals voice from itself
    color: str = "#4f8cff"
    automation: DeckAutomation = Field(default_factory=DeckAutomation)
    clips: List[Clip] = Field(default_factory=list)


class MasterBus(BaseModel):
    gain: float = 1.0
    automation: Automation = Field(default_factory=list)


class CrossfaderBus(BaseModel):
    value: float = 0.5              # 0 = full A, 1 = full B (used when automation is empty)
    automation: Automation = Field(default_factory=list)
    curve: Literal["linear", "equal_power"] = "equal_power"


class ReverbSettings(BaseModel):
    room_size: float = 0.5          # 0..1
    damping: float = 0.5            # 0..1
    width: float = 1.0              # 0..1 stereo spread
    pre_delay_ms: float = 20.0
    return_gain: float = 1.0        # trim on the reverb bus return


class Project(BaseModel):
    name: str = "Untitled Mix"
    master_bpm: float = 128.0
    sample_rate: int = 44100
    master: MasterBus = Field(default_factory=MasterBus)
    crossfader: CrossfaderBus = Field(default_factory=CrossfaderBus)
    reverb: ReverbSettings = Field(default_factory=ReverbSettings)
    decks: List[Deck] = Field(default_factory=list)


class RenderRequest(BaseModel):
    project: Optional[Project] = None
    start: float = 0.0
    end: Optional[float] = None
    max_duration: Optional[float] = 600.0


# ---- library metadata: hot cues + crates. Kept separate from the analysis
# cache (library_cache.json) because it's user-authored, not derived from the
# audio file, and must survive a re-scan/re-analyze of the same path.

class LibraryCue(BaseModel):
    index: int              # pad position, 1-8 (rekordbox-style hot cues)
    time: float = 0.0
    label: str = ""


class LibraryTrackMeta(BaseModel):
    cues: List[LibraryCue] = Field(default_factory=list)


class LibraryCrate(BaseModel):
    id: str
    name: str
    paths: List[str] = Field(default_factory=list)


class LibraryMeta(BaseModel):
    tracks: Dict[str, LibraryTrackMeta] = Field(default_factory=dict)
    crates: List[LibraryCrate] = Field(default_factory=list)
