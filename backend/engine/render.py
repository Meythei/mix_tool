"""Mixdown engine: turns a Project document into a single stereo buffer.

Everything is rendered offline (not realtime): clips are loaded, time-stretched
/ pitch-shifted / resampled to the project sample rate, summed per deck with
automation-driven gain / filter / reverb-send, routed through an optional
A/B crossfader bus, and finally combined with a shared reverb return.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np
import librosa
import soundfile as sf

from models import Project, Deck, Clip
from engine.envelope import sample_envelope, times_for_range
from engine.effects import apply_dj_filter, apply_three_band_eq, process_reverb

_clip_cache: dict = {}


def _cache_key(clip: Clip, native_sr: int, rate: float):
    try:
        mtime = os.path.getmtime(clip.source_path)
    except OSError:
        mtime = 0
    return (
        clip.source_path, mtime,
        round(clip.source_offset, 3), round(clip.source_length, 3),
        round(rate, 4), round(clip.pitch_semitones, 2), clip.reverse, native_sr,
    )


def _apply_fade(seg: np.ndarray, seconds: float, sr: int, fade_in: bool) -> np.ndarray:
    if seconds <= 0 or seg.shape[1] == 0:
        return seg
    n = seg.shape[1]
    fade_len = min(int(seconds * sr), n)
    if fade_len <= 0:
        return seg
    seg = seg.copy()
    ramp = np.linspace(0.0, 1.0, fade_len)
    if fade_in:
        seg[:, :fade_len] *= ramp
    else:
        seg[:, n - fade_len :] *= ramp[::-1]
    return seg


def _stretch_and_pitch(seg: np.ndarray, rate: float, pitch: float, native_sr: int) -> np.ndarray:
    channels = []
    for ch in range(seg.shape[0]):
        chan = seg[ch].astype(np.float32)
        if abs(rate - 1.0) > 1e-4:
            chan = librosa.effects.time_stretch(chan, rate=rate)
        if abs(pitch) > 1e-4:
            chan = librosa.effects.pitch_shift(chan, sr=native_sr, n_steps=pitch)
        channels.append(chan)
    n = min(len(c) for c in channels) if channels else 0
    return np.vstack([c[:n] for c in channels]).astype(np.float64) if n else np.zeros((seg.shape[0], 0))


def _prepare_clip_audio(clip: Clip, deck: Deck, project: Project, warnings: List[str]) -> Optional[np.ndarray]:
    try:
        y, native_sr = sf.read(clip.source_path, dtype="float64", always_2d=True)
        y = y.T  # (channels, frames)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"{clip.label or clip.source_path}: failed to load ({exc})")
        return None

    if y.shape[0] == 1:
        y = np.vstack([y[0], y[0]])
    elif y.shape[0] > 2:
        y = y[:2]

    offset_samp = max(0, min(int(clip.source_offset * native_sr), y.shape[1]))
    length_samp = max(0, int(clip.source_length * native_sr))
    end_samp = max(offset_samp, min(offset_samp + length_samp, y.shape[1]))
    seg = y[:, offset_samp:end_samp]
    if seg.shape[1] == 0:
        warnings.append(f"{clip.label or clip.source_path}: empty segment (check offset/length)")
        return None

    if clip.reverse:
        seg = seg[:, ::-1].copy()

    rate = 1.0
    if deck.sync:
        if clip.source_bpm and clip.source_bpm > 0 and project.master_bpm > 0:
            rate = project.master_bpm / clip.source_bpm
        else:
            warnings.append(f"{clip.label or clip.source_path}: no BPM known, playing unsynced")

    key = _cache_key(clip, native_sr, rate)
    cached = _clip_cache.get(key)
    if cached is not None:
        unit = cached
    else:
        unit = _stretch_and_pitch(seg, rate, clip.pitch_semitones, native_sr)
        _clip_cache[key] = unit

    if unit.shape[1] == 0:
        return None

    sr = project.sample_rate
    if native_sr != sr:
        unit = librosa.resample(unit, orig_sr=native_sr, target_sr=sr, axis=1)

    unit = unit * clip.gain

    seam = min(0.003, unit.shape[1] / sr / 4)
    unit = _apply_fade(unit, seam, sr, fade_in=True)
    unit = _apply_fade(unit, seam, sr, fade_in=False)

    loop_count = max(1, min(int(clip.loop_count), 256))
    seg_out = np.tile(unit, (1, loop_count)) if loop_count > 1 else unit

    seg_out = _apply_fade(seg_out, clip.fade_in, sr, fade_in=True)
    seg_out = _apply_fade(seg_out, clip.fade_out, sr, fade_in=False)
    return seg_out


def _add_at(dest: np.ndarray, src: np.ndarray, start_time_sec: float, sr: int) -> None:
    start = int(round(start_time_sec * sr))
    n_dest = dest.shape[1]
    n_src = src.shape[1]
    src_from = 0
    if start < 0:
        src_from = -start
        start = 0
    if src_from >= n_src or start >= n_dest:
        return
    length = min(n_src - src_from, n_dest - start)
    if length <= 0:
        return
    dest[:, start : start + length] += src[:, src_from : src_from + length]


def _apply_choke_groups(resolved: dict, project: Project, sr: int) -> None:
    """Shot decks sharing a choke_group are monophonic: a new hit cuts off
    whatever is still ringing out from an earlier hit in the same group,
    whether that hit was on this deck or another one in the group."""
    groups: dict = {}
    for deck in project.decks:
        if deck.choke_group is None:
            continue
        for i, (start_t, audio) in enumerate(resolved.get(deck.id, [])):
            groups.setdefault(deck.choke_group, []).append([deck.id, i, start_t, audio])

    for records in groups.values():
        records.sort(key=lambda r: r[2])
        for a in range(len(records) - 1):
            deck_id, idx, start_t, audio = records[a]
            next_start = records[a + 1][2]
            end_t = start_t + audio.shape[1] / sr
            if next_start < end_t - 1e-6:
                keep_samples = max(0, int(round((next_start - start_t) * sr)))
                fade = min(int(0.015 * sr), keep_samples)
                trimmed = audio[:, :keep_samples].copy()
                if fade > 0:
                    trimmed[:, keep_samples - fade :] *= np.linspace(1.0, 0.0, fade)
                records[a][3] = trimmed
                resolved[deck_id][idx] = (start_t, trimmed)


def _crossfader_gain(deck: Deck, project: Project, t_arr: np.ndarray) -> np.ndarray:
    if deck.bus == "M":
        return np.ones_like(t_arr)
    xf = sample_envelope(project.crossfader.automation, project.crossfader.value, t_arr)
    xf = np.clip(xf, 0.0, 1.0)
    if project.crossfader.curve == "equal_power":
        a_gain = np.cos(xf * np.pi / 2)
        b_gain = np.sin(xf * np.pi / 2)
    else:
        a_gain = 1.0 - xf
        b_gain = xf
    return a_gain if deck.bus == "A" else b_gain


def render_project(
    project: Project,
    t_start: float = 0.0,
    t_end: Optional[float] = None,
    max_duration: Optional[float] = 600.0,
) -> Tuple[np.ndarray, int, List[str]]:
    sr = project.sample_rate
    warnings: List[str] = []

    resolved = {}
    total_end = 0.0
    for deck in project.decks:
        deck_clips = []
        for clip in deck.clips:
            audio = _prepare_clip_audio(clip, deck, project, warnings)
            if audio is None:
                continue
            deck_clips.append((clip.timeline_start, audio))
            total_end = max(total_end, clip.timeline_start + audio.shape[1] / sr)
        resolved[deck.id] = deck_clips

    _apply_choke_groups(resolved, project, sr)

    if t_end is not None:
        total_end = min(total_end, t_end)
    if max_duration:
        total_end = min(total_end, t_start + max_duration)
    total_end = max(total_end, t_start + 0.05)

    n_total = int(round((total_end - t_start) * sr))
    master = np.zeros((2, n_total))
    reverb_bus = np.zeros((2, n_total))

    any_solo = any(d.solo for d in project.decks)
    t_arr = times_for_range(t_start, n_total, sr)

    for deck in project.decks:
        if deck.mute or (any_solo and not deck.solo):
            continue
        deck_buf = np.zeros((2, n_total))
        for start_t, audio in resolved[deck.id]:
            _add_at(deck_buf, audio, start_t - t_start, sr)
        if not np.any(deck_buf):
            continue

        eq_low_env = sample_envelope(deck.automation.eq_low, deck.eq_low, t_arr)
        eq_mid_env = sample_envelope(deck.automation.eq_mid, deck.eq_mid, t_arr)
        eq_high_env = sample_envelope(deck.automation.eq_high, deck.eq_high, t_arr)
        if (np.any(np.abs(eq_low_env - 1.0) > 1e-3) or np.any(np.abs(eq_mid_env - 1.0) > 1e-3)
                or np.any(np.abs(eq_high_env - 1.0) > 1e-3)):
            deck_buf = apply_three_band_eq(deck_buf, eq_low_env, eq_mid_env, eq_high_env, sr)

        filter_env = sample_envelope(deck.automation.filter, deck.filter, t_arr)
        if np.any(np.abs(filter_env) > 1e-3):
            deck_buf = apply_dj_filter(deck_buf, filter_env, sr)

        gain_env = sample_envelope(deck.automation.gain, deck.gain, t_arr)
        deck_buf = deck_buf * gain_env

        send_env = sample_envelope(deck.automation.reverb_send, deck.reverb_send, t_arr)
        if np.any(send_env > 1e-4):
            reverb_bus += deck_buf * send_env

        bus_gain = _crossfader_gain(deck, project, t_arr)
        master += deck_buf * bus_gain

    if np.any(reverb_bus):
        wet = process_reverb(
            reverb_bus, sr,
            project.reverb.room_size, project.reverb.damping, project.reverb.width,
            project.reverb.pre_delay_ms, project.reverb.return_gain,
        )
        master += wet

    master_gain_env = sample_envelope(project.master.automation, project.master.gain, t_arr)
    master = master * master_gain_env

    peak = float(np.max(np.abs(master))) if master.size else 0.0
    if peak > 0.98:
        master = master * (0.98 / peak)
        warnings.append(f"master peak was {peak:.2f}x full scale; auto-trimmed to avoid clipping")

    return master, sr, warnings


def render_to_wav(project: Project, out_path: str, **kwargs) -> dict:
    master, sr, warnings = render_project(project, **kwargs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sf.write(out_path, master.T, sr, subtype="PCM_24")
    return {
        "path": out_path,
        "duration": master.shape[1] / sr if sr else 0,
        "sample_rate": sr,
        "warnings": warnings,
    }
