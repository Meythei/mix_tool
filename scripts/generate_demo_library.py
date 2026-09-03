"""Synthesizes a small set of royalty-free demo loops/one-shots so the app has
something to mix on first run. Everything here is generated from scratch with
numpy (kicks, hats, tones, noise) -- no external audio material involved.

Run once: `python scripts/generate_demo_library.py`
"""
import os
import numpy as np
import soundfile as sf

SR = 44100
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "data", "sample_library")


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) if x.size else 0
    return x * (peak / m) if m > 0 else x


def kick(dur=0.16):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    freq = 150 * np.exp(-t * 18) + 45
    phase = 2 * np.pi * np.cumsum(freq) / SR
    sig = np.sin(phase)
    env = np.exp(-t * 13)
    click = np.exp(-t * 300) * 0.3
    return sig * env + click * env


def hihat(dur=0.045, closed=True):
    n = int(SR * dur)
    noise = np.random.randn(n)
    sig = np.diff(noise, prepend=0.0)
    decay = 45 if closed else 8
    env = np.exp(-np.linspace(0, dur, n) * decay)
    return sig * env * 0.45


def clap(dur=0.2):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    noise = np.random.randn(n)
    bursts = sum(np.exp(-np.abs(t - off) * 90) for off in (0.0, 0.012, 0.024))
    env = bursts * np.exp(-t * 10)
    return noise * env * 0.5


def make_beat_loop(bpm, bars=8):
    beat_dur = 60.0 / bpm
    bar_dur = beat_dur * 4
    total = bar_dur * bars
    n = int(SR * total)
    buf = np.zeros(n)

    def place(sig, t_sec):
        i = int(t_sec * SR)
        j = min(n, i + len(sig))
        if i < n:
            buf[i:j] += sig[: j - i]

    k = kick()
    hc = hihat(closed=True)
    ho = hihat(closed=False)
    cl = clap()

    for bar in range(bars):
        bar_t = bar * bar_dur
        for beat in range(4):
            place(k, bar_t + beat * beat_dur)
        for eighth in range(8):
            place(ho if eighth % 4 == 2 else hc, bar_t + eighth * beat_dur / 2)
        place(cl, bar_t + 1 * beat_dur)
        place(cl, bar_t + 3 * beat_dur)

    return _norm(buf)


def _tone(freqs_amp, t, shape="sine"):
    sig = np.zeros_like(t)
    for freq, amp in freqs_amp:
        if shape == "saw":
            phase = (t * freq) % 1.0
            osc = 2 * phase - 1
        else:
            osc = np.sin(2 * np.pi * freq * t)
        sig += osc * amp
    return sig


def make_bassline(bpm, bars=8, root=55.0):
    beat_dur = 60.0 / bpm
    step_dur = beat_dur / 2  # 8th notes
    pattern = [1, 0, 1, 1, 0, 1, 0, 1]  # scale degree gate per 8th (within a beat*4 bar treated cyclically)
    semis = [0, 0, 3, 0, 0, 5, 0, 3]
    n_total = int(SR * beat_dur * 4 * bars)
    buf = np.zeros(n_total)
    step_n = int(SR * step_dur * 0.92)
    t_step = np.arange(step_n) / SR
    env = np.exp(-t_step * 7)
    idx = 0
    steps_per_bar = 8
    total_steps = steps_per_bar * bars
    for s in range(total_steps):
        gate = pattern[s % len(pattern)]
        if gate:
            freq = root * (2 ** (semis[s % len(semis)] / 12))
            osc = _tone([(freq, 0.6), (freq * 2, 0.15)], t_step, shape="saw")
            sig = osc * env
            i = int(s * step_dur * SR)
            j = min(n_total, i + step_n)
            buf[i:j] += sig[: j - i]
    return _norm(buf, peak=0.85)


def make_pad(bpm, bars=4, chord=(220.0, 261.63, 329.63)):
    beat_dur = 60.0 / bpm
    dur = beat_dur * 4 * bars
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    sig = np.zeros_like(t)
    for f in chord:
        sig += np.sin(2 * np.pi * f * t) * 0.25
        sig += np.sin(2 * np.pi * (f * 2.003) * t) * 0.08  # gentle detune shimmer
    lfo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.1 * t)
    fade = np.ones_like(t)
    fade_n = int(SR * 1.5)
    fade[:fade_n] = np.linspace(0, 1, fade_n)
    fade[-fade_n:] = np.linspace(1, 0, fade_n)
    return _norm(sig * lfo * fade, peak=0.8)


def shot_airhorn(dur=0.9):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    vibrato = 1 + 0.01 * np.sin(2 * np.pi * 6 * t)
    freq = 370 * vibrato
    phase = (np.cumsum(freq) / SR) % 1.0
    saw = 2 * phase - 1
    env = np.ones_like(t)
    a, r = int(SR * 0.015), int(SR * 0.15)
    env[:a] = np.linspace(0, 1, a)
    env[-r:] = np.linspace(1, 0, r)
    return _norm(saw * env)


def shot_riser(dur=2.0):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    freq = np.linspace(200, 3500, n)
    phase = np.cumsum(freq) / SR
    sig = np.sin(2 * np.pi * phase)
    noise = np.random.randn(n) * 0.3
    env = np.linspace(0.05, 1.0, n) ** 1.5
    return _norm((sig * 0.7 + noise) * env)


def shot_impact(dur=1.2):
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    boom = np.sin(2 * np.pi * (60 * np.exp(-t * 2)) * t) * np.exp(-t * 3)
    noise = np.random.randn(n) * np.exp(-t * 25)
    return _norm(boom * 0.8 + noise * 0.6)


def shot_stab(dur=0.5):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    chord = [261.63, 311.13, 392.00, 466.16]  # Cm7-ish stab
    sig = _tone([(f, 0.22) for f in chord], t, shape="saw")
    env = np.exp(-t * 6)
    a = int(SR * 0.005)
    env[:a] *= np.linspace(0, 1, a)
    return _norm(sig * env)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    tracks = [
        ("Demo Beat 120.wav", make_beat_loop(120, bars=8)),
        ("Demo Beat 128.wav", make_beat_loop(128, bars=8)),
        ("Demo Bassline 124.wav", make_bassline(124, bars=8)),
        ("Demo Pad 100.wav", make_pad(100, bars=4)),
        ("Shot Airhorn.wav", shot_airhorn()),
        ("Shot Riser.wav", shot_riser()),
        ("Shot Impact.wav", shot_impact()),
        ("Shot Synth Stab.wav", shot_stab()),
    ]
    for name, audio in tracks:
        path = os.path.join(OUT_DIR, name)
        sf.write(path, audio.astype(np.float32), SR, subtype="PCM_16")
        print("wrote", path)


if __name__ == "__main__":
    main()
