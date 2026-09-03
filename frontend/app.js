const DECK_COLORS = ['#B8C4FF', '#FFB2BE', '#9BE3AE', '#F0C05A', '#7FD8E8', '#D6B3FF', '#C9DE7C', '#FF9E80'];
const M3 = { onSurfaceVariant: '#C8C5D0', outline: '#8F8C97', outlineVariant: '#46454E', error: '#FFB4AB', primary: '#B8C4FF' };

const state = {
  project: null,
  library: [],
  libraryByPath: new Map(),
  armedLibraryPath: null,
  selection: null,
  pxPerSecond: 40,
  snap: true,
  playhead: 0,
  expandedAutomation: {},
  timelineWidthPx: 800,
  deckCanvases: {},
  audition: { path: null, entry: null },
};

// ---------------------------------------------------------------- utils --

function uid() { return crypto.randomUUID ? crypto.randomUUID() : 'id-' + Math.random().toString(36).slice(2) + Date.now(); }
function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }
function basename(p) { return String(p || '').split(/[\\/]/).pop(); }
function escapeHtml(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function escapeAttr(s) { return escapeHtml(s); }

function formatTime(sec) {
  sec = Math.max(0, sec || 0);
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

// Camelot wheel color: hue walks the 12 positions of the wheel, major (B)
// keys a touch brighter than their relative minor (A) so the two read as a
// pair at a glance -- same idea as rekordbox's key-colored waveforms.
function camelotColor(code) {
  if (!code) return null;
  const num = parseInt(code, 10);
  if (!num) return null;
  const hue = ((num - 1) / 12) * 360;
  const light = code.endsWith('B') ? 72 : 60;
  return `hsl(${hue.toFixed(0)}, 62%, ${light}%)`;
}

// Harmonic compatibility 0..1 between two Camelot codes (same code, adjacent
// number on the same ring, or the relative major/minor all mix cleanly).
function camelotCompat(a, b) {
  if (!a || !b) return 0.3;
  const na = parseInt(a, 10), nb = parseInt(b, 10);
  const la = a.slice(-1), lb = b.slice(-1);
  if (Number.isNaN(na) || Number.isNaN(nb)) return 0.3;
  if (a === b) return 1.0;
  if (na === nb && la !== lb) return 0.85;
  const diff = Math.min(Math.abs(na - nb), 12 - Math.abs(na - nb));
  if (diff === 1 && la === lb) return 0.75;
  if (diff === 1 && la !== lb) return 0.5;
  return 0.15;
}

// BPM compatibility 0..1: closeness to the same tempo scores highest, exact
// half/double time next (a common DJ trick), other simple ratios a little.
function bpmCompat(ref, cand) {
  if (!ref || !cand) return 0.3;
  const ratios = [[1, 1], [2, 0.85], [0.5, 0.85], [4 / 3, 0.5], [3 / 4, 0.5]];
  let best = 0;
  for (const [r, weight] of ratios) {
    const target = ref * r;
    const pct = Math.abs(cand - target) / target;
    const s = Math.max(0, 1 - pct / 0.08) * weight;
    if (s > best) best = s;
  }
  return best;
}

let _toastTimer = null;
function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show' + (isError ? ' error' : '');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = ''; }, 3500);
}
function setStatus(msg) { document.getElementById('renderStatus').textContent = msg; }

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}
async function apiPut(path, body) {
  const res = await fetch(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

let _syncTimer = null;
function scheduleSync() {
  pushHistoryIfChanged();
  if (_syncTimer) clearTimeout(_syncTimer);
  _syncTimer = setTimeout(() => { apiPut('/api/project', state.project).catch(err => console.warn('sync failed', err)); }, 500);
}

async function syncProjectNow() {
  if (_syncTimer) { clearTimeout(_syncTimer); _syncTimer = null; }
  try { await apiPut('/api/project', state.project); } catch (err) { console.warn('sync failed', err); }
}

// -------------------------------------------------------------- history --
// Ableton-style undo/redo: every meaningful commit funnels through
// scheduleSync() already (drag mouseup, control 'change' events, add/remove
// actions), so hooking the snapshot there gives one undo step per gesture
// without touching every mutation call site individually.

const history = { stack: [], redo: [], last: null, suspend: false };

function historySnapshotString() { return JSON.stringify(state.project); }

function initHistory() {
  history.stack = [];
  history.redo = [];
  history.last = state.project ? historySnapshotString() : null;
  updateHistoryButtons();
}

function pushHistoryIfChanged() {
  if (history.suspend || !state.project) return;
  const cur = historySnapshotString();
  if (history.last === null) { history.last = cur; return; }
  if (cur === history.last) return;
  history.stack.push(history.last);
  if (history.stack.length > 100) history.stack.shift();
  history.redo = [];
  history.last = cur;
  updateHistoryButtons();
}

function updateHistoryButtons() {
  const u = document.getElementById('btnUndo'), r = document.getElementById('btnRedo');
  if (u) u.disabled = history.stack.length === 0;
  if (r) r.disabled = history.redo.length === 0;
}

function undo() {
  if (!history.stack.length) return;
  const cur = historySnapshotString();
  const prev = history.stack.pop();
  history.redo.push(cur);
  history.last = prev;
  history.suspend = true;
  loadProjectIntoUI(JSON.parse(prev));
  history.suspend = false;
  updateHistoryButtons();
  syncProjectNow();
  toast('Undo');
}

function redo() {
  if (!history.redo.length) return;
  const cur = historySnapshotString();
  const next = history.redo.pop();
  history.stack.push(cur);
  history.last = next;
  history.suspend = true;
  loadProjectIntoUI(JSON.parse(next));
  history.suspend = false;
  updateHistoryButtons();
  syncProjectNow();
  toast('Redo');
}

let _redrawScheduled = false;
function requestRedraw() {
  if (_redrawScheduled) return;
  _redrawScheduled = true;
  requestAnimationFrame(() => { _redrawScheduled = false; redrawAll(); });
}

// ------------------------------------------------------------- geometry --

function estimateClipDuration(clip, deck, project) {
  let rate = 1;
  if (deck.sync && clip.source_bpm && project.master_bpm) rate = project.master_bpm / clip.source_bpm;
  if (!rate || rate <= 0) rate = 1;
  const unit = clip.source_length / rate;
  return unit * Math.max(1, clip.loop_count | 0);
}

function computeTimelineSeconds(project) {
  let end = 30;
  for (const deck of project.decks) {
    for (const clip of deck.clips) end = Math.max(end, clip.timeline_start + estimateClipDuration(clip, deck, project));
    for (const param of ['gain', 'filter', 'reverb_send']) {
      for (const p of deck.automation[param]) end = Math.max(end, p.time);
    }
  }
  for (const p of project.master.automation) end = Math.max(end, p.time);
  for (const p of project.crossfader.automation) end = Math.max(end, p.time);
  return end + 8;
}

function maybeSnapTime(t) {
  if (!state.snap) return Math.max(0, t);
  const bpm = (state.project && state.project.master_bpm) || 120;
  const grid = (60 / bpm) / 4;
  return Math.max(0, Math.round(t / grid) * grid);
}

function valueToY(value, min, max, cssH) { return cssH - ((value - min) / (max - min)) * cssH; }
function yToValue(y, min, max, cssH) { return min + (1 - y / cssH) * (max - min); }

function setupCanvasDPI(canvas, cssW, cssH) {
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = cssW + 'px';
  canvas.style.height = cssH + 'px';
  canvas.width = Math.max(1, Math.round(cssW * dpr));
  canvas.height = Math.max(1, Math.round(cssH * dpr));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function roundRect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawBeatGrid(ctx, w, h) {
  const bpm = (state.project && state.project.master_bpm) || 120;
  const secPerBeat = 60 / bpm;
  const maxT = w / state.pxPerSecond;
  let i = 0;
  for (let t = 0; t < maxT; t += secPerBeat, i++) {
    const x = Math.round(t * state.pxPerSecond) + 0.5;
    ctx.strokeStyle = (i % 4 === 0) ? 'rgba(200,197,208,0.16)' : 'rgba(200,197,208,0.06)';
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
}

function drawPlayhead(ctx, h) {
  if (state.playhead == null) return;
  const x = state.playhead * state.pxPerSecond + 0.5;
  ctx.strokeStyle = M3.error;
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
}

// ---------------------------------------------------------------- ruler --

function drawRuler(w) {
  const canvas = document.getElementById('rulerCanvas');
  const h = 28;
  const ctx = setupCanvasDPI(canvas, w, h);
  ctx.clearRect(0, 0, w, h);
  drawBeatGrid(ctx, w, h);

  const bpm = (state.project && state.project.master_bpm) || 120;
  const secPerBar = (60 / bpm) * 4;
  ctx.fillStyle = M3.onSurfaceVariant;
  ctx.font = '600 10px Roboto, sans-serif';
  let bar = 0;
  for (let t = 0; t < w / state.pxPerSecond; t += secPerBar, bar++) {
    ctx.fillText(String(bar + 1), t * state.pxPerSecond + 3, 11);
  }
  const step = state.pxPerSecond > 60 ? 5 : state.pxPerSecond > 20 ? 10 : 30;
  ctx.fillStyle = M3.outline;
  ctx.font = '10px "Roboto Mono", monospace';
  for (let t = 0; t < w / state.pxPerSecond; t += step) {
    ctx.fillText(formatTime(t), t * state.pxPerSecond + 3, 24);
  }
  drawPlayhead(ctx, h);
}

// ------------------------------------------------------------ clip lane --

function drawMiniWave(ctx, entry, clip, x, y, w, h, color) {
  const peaks = entry && entry.peaks;
  if (!peaks || !peaks.length || !entry.duration) return;
  const startFrac = clamp((clip.source_offset || 0) / entry.duration, 0, 1);
  const lenFrac = clamp((clip.source_length || 0) / entry.duration, 0, 1 - startFrac);
  const i0 = Math.floor(startFrac * peaks.length);
  const i1 = Math.max(i0 + 1, Math.floor((startFrac + lenFrac) * peaks.length));
  const slice = peaks.slice(i0, i1);
  if (!slice.length) return;
  const loopCount = Math.max(1, clip.loop_count | 0);
  const unitW = w / loopCount;
  const mid = y + h / 2;
  ctx.fillStyle = color + '99';
  for (let rep = 0; rep < loopCount; rep++) {
    const baseX = x + rep * unitW;
    const pw = Math.max(1, unitW / slice.length);
    for (let i = 0; i < slice.length; i++) {
      const px = baseX + (i / slice.length) * unitW;
      const [mn, mx] = slice[i];
      const y0 = mid - mx * (h / 2);
      const y1 = mid - mn * (h / 2);
      ctx.fillRect(px, y0, pw, Math.max(1, y1 - y0));
    }
  }
}

function drawClipLane(canvas, deck, refs, w, h) {
  const ctx = setupCanvasDPI(canvas, w, h);
  ctx.clearRect(0, 0, w, h);
  drawBeatGrid(ctx, w, h);

  refs.clipBoxes = [];
  for (const clip of deck.clips) {
    const dur = estimateClipDuration(clip, deck, state.project);
    const x = clip.timeline_start * state.pxPerSecond;
    const cw = Math.max(4, dur * state.pxPerSecond);
    const selected = state.selection && state.selection.type === 'clip' && state.selection.clip === clip;

    ctx.fillStyle = deck.color + (selected ? '70' : '3d');
    roundRect(ctx, x, 3, cw, h - 6, 8); ctx.fill();
    ctx.strokeStyle = selected ? '#ffffff' : deck.color;
    ctx.lineWidth = selected ? 2 : 1.3;
    roundRect(ctx, x, 3, cw, h - 6, 8); ctx.stroke();

    const entry = state.libraryByPath.get(clip.source_path);
    if (cw > 14) drawMiniWave(ctx, entry, clip, x + 2, 3, cw - 4, h - 6, deck.color);

    const label = clip.label || basename(clip.source_path);
    ctx.font = '600 10px Roboto, sans-serif';
    const tw = Math.min(cw - 6, ctx.measureText(label).width + 10);
    if (tw > 6) {
      ctx.fillStyle = 'rgba(12,12,17,0.72)';
      roundRect(ctx, x + 2, h - 16, tw, 13, 6); ctx.fill();
      ctx.fillStyle = '#f2f1f5';
      ctx.save();
      ctx.beginPath(); ctx.rect(x + 2, h - 16, tw, 13); ctx.clip();
      ctx.fillText(label, x + 6, h - 6);
      ctx.restore();
    }

    refs.clipBoxes.push({ clip, x0: x, x1: x + cw });
  }
  drawPlayhead(ctx, h);
}

function placeClipFromLibrary(deck, entry, startTime) {
  const defaultLen = Math.min(entry.duration || 4, deck.type === 'shot' ? (entry.duration || 1) : 60);
  const clip = {
    id: uid(), source_path: entry.path, label: basename(entry.filename || entry.path).replace(/\.[^.]+$/, ''),
    timeline_start: Math.max(0, startTime), source_offset: 0, source_length: defaultLen,
    source_bpm: entry.bpm || null, loop_count: 1, gain: 1, fade_in: 0.005, fade_out: 0.005,
    pitch_semitones: 0, reverse: false,
  };
  deck.clips.push(clip);
  state.selection = { type: 'clip', clip, deck };
  requestRedraw(); renderInspector(); scheduleSync();
}

function wireClipCanvas(canvas, deck, refs) {
  let mode = null;
  let dragClip = null;
  let startMouseX = 0, startVal = 0;

  canvas.addEventListener('mousedown', e => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const hit = (refs.clipBoxes || []).find(b => mx >= b.x0 && mx <= b.x1);
    if (hit) {
      state.selection = { type: 'clip', clip: hit.clip, deck };
      if (hit.x1 - mx < 10) { mode = 'resize'; dragClip = hit.clip; startMouseX = mx; startVal = hit.clip.source_length; }
      else { mode = 'move'; dragClip = hit.clip; startMouseX = mx; startVal = hit.clip.timeline_start; }
    } else if (state.armedLibraryPath) {
      const entry = state.libraryByPath.get(state.armedLibraryPath);
      if (entry) placeClipFromLibrary(deck, entry, maybeSnapTime(mx / state.pxPerSecond));
      return;
    } else {
      state.selection = null;
      state.playhead = maybeSnapTime(mx / state.pxPerSecond);
    }
    requestRedraw(); renderInspector();
  });

  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    if (!mode) {
      const hit = (refs.clipBoxes || []).find(b => mx >= b.x0 && mx <= b.x1);
      canvas.style.cursor = hit ? (hit.x1 - mx < 10 ? 'ew-resize' : 'grab') : (state.armedLibraryPath ? 'copy' : 'crosshair');
      return;
    }
    const dt = (mx - startMouseX) / state.pxPerSecond;
    if (mode === 'move') {
      dragClip.timeline_start = Math.max(0, maybeSnapTime(startVal + dt));
    } else {
      let rate = 1;
      if (deck.sync && dragClip.source_bpm && state.project.master_bpm) rate = state.project.master_bpm / dragClip.source_bpm;
      dragClip.source_length = Math.max(0.05, startVal + dt * rate);
    }
    requestRedraw(); renderInspector();
  });

  window.addEventListener('mouseup', () => { if (mode) { mode = null; dragClip = null; scheduleSync(); } });

  canvas.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  canvas.addEventListener('dragenter', () => canvas.closest('.deck-row').classList.add('dragover'));
  canvas.addEventListener('dragleave', () => canvas.closest('.deck-row').classList.remove('dragover'));
  canvas.addEventListener('drop', e => {
    e.preventDefault();
    canvas.closest('.deck-row').classList.remove('dragover');
    const path = e.dataTransfer.getData('text/plain');
    const entry = state.libraryByPath.get(path);
    if (!entry) return;
    const rect = canvas.getBoundingClientRect();
    placeClipFromLibrary(deck, entry, maybeSnapTime((e.clientX - rect.left) / state.pxPerSecond));
  });
}

// -------------------------------------------------------- automation lanes --

function laneSpec(param, deck) {
  if (param === 'gain') return { points: deck.automation.gain, base: deck.gain, min: 0, max: 1.5, color: deck.color, ref: 1.0, label: `${deck.name} · Gain` };
  if (param === 'filter') return { points: deck.automation.filter, base: deck.filter, min: -1, max: 1, color: deck.color, ref: 0.0, label: `${deck.name} · Filter` };
  return { points: deck.automation.reverb_send, base: deck.reverb_send, min: 0, max: 1, color: deck.color, ref: 0.0, label: `${deck.name} · Send` };
}

function drawLane(canvas, spec, w, h) {
  const ctx = setupCanvasDPI(canvas, w, h);
  ctx.clearRect(0, 0, w, h);
  drawBeatGrid(ctx, w, h);

  const refY = valueToY(spec.ref, spec.min, spec.max, h);
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.beginPath(); ctx.moveTo(0, refY); ctx.lineTo(w, refY); ctx.stroke();

  const pts = spec.points.slice().sort((a, b) => a.time - b.time);
  if (pts.length === 0) {
    const y = valueToY(spec.base, spec.min, spec.max, h);
    ctx.strokeStyle = spec.color + 'a0';
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    ctx.setLineDash([]);
  } else {
    const mapped = pts.map(p => ({ x: p.time * state.pxPerSecond, y: valueToY(p.value, spec.min, spec.max, h), p }));
    ctx.strokeStyle = spec.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, mapped[0].y);
    for (const m of mapped) ctx.lineTo(m.x, m.y);
    ctx.lineTo(w, mapped[mapped.length - 1].y);
    ctx.stroke();

    for (const m of mapped) {
      const selected = state.selection && state.selection.type === 'point' && state.selection.pointRef === m.p;
      ctx.beginPath();
      ctx.arc(m.x, m.y, selected ? 6 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = selected ? '#ffffff' : spec.color;
      ctx.fill();
      if (selected) { ctx.lineWidth = 2; ctx.strokeStyle = spec.color; ctx.stroke(); }
    }
  }
  drawPlayhead(ctx, h);
}

function wireLane(canvas, getSpec, onChange) {
  let dragging = null;
  canvas.addEventListener('mousedown', e => {
    const spec = getSpec();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top, h = rect.height;
    let hit = null;
    for (const p of spec.points) {
      const x = p.time * state.pxPerSecond, y = valueToY(p.value, spec.min, spec.max, h);
      if (Math.hypot(x - mx, y - my) <= 8) { hit = p; break; }
    }
    if (hit) {
      dragging = hit;
    } else {
      const t = maybeSnapTime(mx / state.pxPerSecond);
      const v = clamp(yToValue(my, spec.min, spec.max, h), spec.min, spec.max);
      const np = { time: Math.max(0, t), value: v };
      spec.points.push(np);
      dragging = np;
    }
    state.selection = { type: 'point', pointRef: dragging, points: spec.points, label: spec.label };
    onChange();
  });
  canvas.addEventListener('mousemove', e => {
    if (!dragging) return;
    const spec = getSpec();
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    dragging.time = Math.max(0, maybeSnapTime(mx / state.pxPerSecond));
    dragging.value = clamp(yToValue(my, spec.min, spec.max, rect.height), spec.min, spec.max);
    onChange();
  });
  window.addEventListener('mouseup', () => { if (dragging) { dragging = null; scheduleSync(); } });
}

function toggleAutomationLane(deckId, param) {
  const set = state.expandedAutomation[deckId] || (state.expandedAutomation[deckId] = new Set());
  if (set.has(param)) set.delete(param); else set.add(param);
  rebuildDeckDOM();
}

// ------------------------------------------------------------- deck rows --

function deckHeaderHTML(deck) {
  const isShot = deck.type === 'shot';
  return `
  <div class="deck-name-row">
    <span class="deck-color-dot" style="background:${deck.color}"></span>
    <input class="deck-name" data-field="name" value="${escapeAttr(deck.name)}" spellcheck="false">
    <span class="deck-type-badge ${deck.type}">${deck.type}</span>
    <button class="mini-btn remove" data-action="remove" title="Remove deck">✕</button>
  </div>
  <div class="deck-btn-row">
    <button class="mini-btn mute ${deck.mute ? 'active' : ''}" data-action="mute">MUTE</button>
    <button class="mini-btn solo ${deck.solo ? 'active' : ''}" data-action="solo">SOLO</button>
    ${!isShot ? `<button class="mini-btn sync ${deck.sync ? 'active' : ''}" data-action="sync" title="Time-stretch clips to master BPM">SYNC</button>` : ''}
    <select class="deck-bus-select" data-field="bus" title="Crossfader bus routing">
      <option value="M" ${deck.bus === 'M' ? 'selected' : ''}>Bus: M</option>
      <option value="A" ${deck.bus === 'A' ? 'selected' : ''}>Bus: A</option>
      <option value="B" ${deck.bus === 'B' ? 'selected' : ''}>Bus: B</option>
    </select>
  </div>
  ${isShot ? `<div class="deck-btn-row"><label class="choke-field">Choke grp <input type="number" data-field="choke_group" value="${deck.choke_group ?? ''}" placeholder="–" title="Decks sharing a choke group cut each other off"></label></div>` : ''}
  <div class="knob-row" data-param="gain">
    <span>Gain</span>
    <input type="range" min="0" max="1.5" step="0.01" data-field="gain" value="${deck.gain}">
    <input type="number" min="0" max="1.5" step="0.01" data-field="gain" value="${deck.gain}">
    <button class="autobtn ${deck.automation.gain.length ? 'has-points' : ''}" data-toggle="gain" title="Show automation lane · right-click clears it"></button>
  </div>
  <div class="knob-row" data-param="filter">
    <span>Filter</span>
    <input type="range" min="-1" max="1" step="0.01" data-field="filter" value="${deck.filter}">
    <input type="number" min="-1" max="1" step="0.01" data-field="filter" value="${deck.filter}">
    <button class="autobtn ${deck.automation.filter.length ? 'has-points' : ''}" data-toggle="filter" title="Show automation lane · right-click clears it"></button>
  </div>
  <div class="knob-row" data-param="reverb_send">
    <span>Send</span>
    <input type="range" min="0" max="1" step="0.01" data-field="reverb_send" value="${deck.reverb_send}">
    <input type="number" min="0" max="1" step="0.01" data-field="reverb_send" value="${deck.reverb_send}">
    <button class="autobtn ${deck.automation.reverb_send.length ? 'has-points' : ''}" data-toggle="reverb_send" title="Show automation lane · right-click clears it"></button>
  </div>`;
}

function wireDeckRow(headerEl, deck) {
  headerEl.querySelectorAll('[data-field]').forEach(el => {
    const field = el.dataset.field;
    const apply = () => {
      if (field === 'name') deck.name = el.value;
      else if (field === 'bus') deck.bus = el.value;
      else if (field === 'choke_group') deck.choke_group = el.value === '' ? null : (parseInt(el.value, 10) || 0);
      else {
        const v = parseFloat(el.value);
        if (!Number.isNaN(v)) {
          deck[field] = v;
          headerEl.querySelectorAll(`[data-field="${field}"]`).forEach(other => { if (other !== el) other.value = String(v); });
        }
      }
      requestRedraw();
    };
    el.addEventListener('input', apply);
    el.addEventListener('change', () => { apply(); scheduleSync(); });
  });

  headerEl.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      if (action === 'mute') deck.mute = !deck.mute;
      else if (action === 'solo') deck.solo = !deck.solo;
      else if (action === 'sync') deck.sync = !deck.sync;
      else if (action === 'remove') {
        if (confirm(`Remove deck "${deck.name}"?`)) removeDeck(deck.id);
        return;
      }
      rebuildDeckDOM(); scheduleSync();
    });
  });

  headerEl.querySelectorAll('[data-toggle]').forEach(btn => {
    btn.addEventListener('click', () => toggleAutomationLane(deck.id, btn.dataset.toggle));
    btn.addEventListener('contextmenu', e => {
      e.preventDefault();
      const param = btn.dataset.toggle;
      if (confirm(`Clear all "${param}" automation points on ${deck.name}?`)) {
        deck.automation[param].length = 0;
        if (state.selection && state.selection.type === 'point' && state.selection.points === deck.automation[param]) state.selection = null;
        rebuildDeckDOM(); renderInspector(); scheduleSync();
      }
    });
  });
}

function rebuildDeckDOM() {
  const container = document.getElementById('decksContainer');
  container.innerHTML = '';
  state.deckCanvases = {};
  const onLaneChange = () => { requestRedraw(); renderInspector(); };

  for (const deck of state.project.decks) {
    const row = document.createElement('div');
    row.className = 'deck-row';

    const header = document.createElement('div');
    header.className = 'deck-header';
    header.innerHTML = deckHeaderHTML(deck);
    row.appendChild(header);

    const lanesWrap = document.createElement('div');
    lanesWrap.className = 'deck-lanes';
    const clipCanvas = document.createElement('canvas');
    clipCanvas.className = 'clip-lane-canvas';
    lanesWrap.appendChild(clipCanvas);

    const refs = { clip: clipCanvas, automation: {}, clipBoxes: [] };
    state.deckCanvases[deck.id] = refs;

    const expanded = state.expandedAutomation[deck.id] || new Set();
    for (const param of ['gain', 'filter', 'reverb_send']) {
      if (!expanded.has(param)) continue;
      const c = document.createElement('canvas');
      c.className = 'automation-canvas';
      c.dataset.param = param;
      lanesWrap.appendChild(c);
      refs.automation[param] = c;
      wireLane(c, () => laneSpec(param, deck), onLaneChange);
    }

    row.appendChild(lanesWrap);
    container.appendChild(row);

    wireDeckRow(header, deck);
    wireClipCanvas(clipCanvas, deck, refs);
  }
  requestRedraw();
}

function addDeck(type) {
  const color = DECK_COLORS[state.project.decks.length % DECK_COLORS.length];
  const n = state.project.decks.filter(d => d.type === type).length + 1;
  const deck = {
    id: uid(), name: type === 'shot' ? `Shots ${n}` : `Deck ${n}`, type,
    sync: type === 'track', gain: 1, filter: 0, reverb_send: 0, bus: 'M',
    mute: false, solo: false, choke_group: type === 'shot' ? 1 : null, color,
    automation: { gain: [], filter: [], reverb_send: [] }, clips: [],
  };
  state.project.decks.push(deck);
  state.expandedAutomation[deck.id] = new Set(type === 'track' ? ['gain'] : []);
  rebuildDeckDOM(); scheduleSync();
}

function removeDeck(deckId) {
  state.project.decks = state.project.decks.filter(d => d.id !== deckId);
  delete state.expandedAutomation[deckId];
  if (state.selection && state.selection.deck && state.selection.deck.id === deckId) state.selection = null;
  rebuildDeckDOM(); renderInspector(); scheduleSync();
}

// -------------------------------------------------------------- redraw --

function redrawAll() {
  if (!state.project) return;
  const seconds = computeTimelineSeconds(state.project);
  state.timelineWidthPx = Math.max(seconds * state.pxPerSecond, 600);
  const w = state.timelineWidthPx;

  drawRuler(w);

  for (const deck of state.project.decks) {
    const refs = state.deckCanvases[deck.id];
    if (!refs) continue;
    drawClipLane(refs.clip, deck, refs, w, 64);
    for (const [param, canvas] of Object.entries(refs.automation)) {
      drawLane(canvas, laneSpec(param, deck), w, 44);
    }
  }

  drawLane(document.getElementById('crossfaderCanvas'),
    { points: state.project.crossfader.automation, base: state.project.crossfader.value, min: 0, max: 1, color: M3.onSurfaceVariant, ref: 0.5 }, w, 44);
  drawLane(document.getElementById('masterCanvas'),
    { points: state.project.master.automation, base: state.project.master.gain, min: 0, max: 1.5, color: M3.onSurfaceVariant, ref: 1.0 }, w, 44);
}

// -------------------------------------------------------------- library --

function renderLibrary() {
  const listEl = document.getElementById('libraryList');
  listEl.innerHTML = '';
  for (const entry of state.library) {
    const isAuditioning = state.audition.path === entry.path;
    const isPlaying = isAuditioning && !auditionAudio.paused;
    const div = document.createElement('div');
    div.className = 'library-item'
      + (state.armedLibraryPath === entry.path ? ' armed' : '')
      + (entry.error ? ' error' : '')
      + (isAuditioning ? ' auditioning' : '');
    div.draggable = true;
    if (entry.error) div.title = 'Analysis failed: ' + entry.error;
    const bpmText = entry.bpm ? entry.bpm.toFixed(1) : '--';
    const camelotChip = entry.camelot
      ? `<span class="li-chip camelot" style="background:${camelotColor(entry.camelot)}">${escapeHtml(entry.camelot)}</span>` : '';
    div.innerHTML = `
      <div class="li-name">${escapeHtml(entry.filename)}</div>
      <div class="li-meta">
        <span class="li-chip bpm">${bpmText} BPM</span>
        ${camelotChip}
        ${entry.key ? `<span class="li-chip">${escapeHtml(entry.key)}</span>` : ''}
        ${entry.duration != null ? `<span class="li-chip">${formatTime(entry.duration)}</span>` : ''}
      </div>
      <canvas class="li-wave" width="220" height="22"></canvas>
      <button class="li-audition-btn${isPlaying ? ' playing' : ''}" title="試聴 (Preview)">
        <svg viewBox="0 0 24 24">${isPlaying ? '<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>' : '<path d="M8 5v14l11-7z"/>'}</svg>
      </button>`;
    listEl.appendChild(div);

    const waveCanvas = div.querySelector('.li-wave');
    if (entry.peaks && entry.peaks.length) {
      const ctx = waveCanvas.getContext('2d');
      const w = 220, h = 22, mid = h / 2;
      ctx.fillStyle = M3.primary + '99';
      const pw = Math.max(1, w / entry.peaks.length);
      entry.peaks.forEach((pk, i) => {
        const [mn, mx] = pk;
        const x = (i / entry.peaks.length) * w;
        ctx.fillRect(x, mid - mx * mid, pw, Math.max(1, (mx - mn) * mid));
      });
    }
    div.addEventListener('click', () => {
      state.armedLibraryPath = (state.armedLibraryPath === entry.path) ? null : entry.path;
      renderLibrary();
      if (!document.getElementById('suggestPanel').hidden) showSuggestions();
    });
    div.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', entry.path);
      e.dataTransfer.effectAllowed = 'copy';
    });

    div.querySelector('.li-audition-btn').addEventListener('click', e => {
      e.stopPropagation();
      toggleAuditionPlay(entry);
    });
    waveCanvas.addEventListener('click', e => {
      e.stopPropagation();
      if (!entry.duration) { toggleAuditionPlay(entry); return; }
      if (state.audition.path !== entry.path) openAudition(entry);
      const rect = waveCanvas.getBoundingClientRect();
      const frac = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      auditionAudio.currentTime = frac * entry.duration;
      auditionAudio.play().catch(() => {});
    });
  }
}

// ---------------------------------------------------------- audition player --
// A quick-preview player + rekordbox-style hot cues for library items,
// independent of the full-mix Preview/Export render (which stays offline).

const auditionAudio = document.getElementById('auditionAudio');
let _auditionRedrawScheduled = false;

function requestAuditionRedraw() {
  if (_auditionRedrawScheduled) return;
  _auditionRedrawScheduled = true;
  requestAnimationFrame(() => { _auditionRedrawScheduled = false; drawAuditionWave(); });
}

function updateAuditionPlayIcon() {
  const btn = document.getElementById('auditionPlay');
  if (!btn) return;
  btn.innerHTML = auditionAudio.paused
    ? '<svg viewBox="0 0 24 24" class="btn-icon"><path d="M8 5v14l11-7z"/></svg>'
    : '<svg viewBox="0 0 24 24" class="btn-icon"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
}

function openAudition(entry) {
  if (!entry) return;
  state.audition.path = entry.path;
  state.audition.entry = entry;
  document.getElementById('auditionBar').hidden = false;
  document.getElementById('auditionName').textContent = entry.filename;
  auditionAudio.src = `/api/library/audio?path=${encodeURIComponent(entry.path)}`;
  auditionAudio.currentTime = 0;
  auditionAudio.play().catch(() => {});
  renderCuePads();
  renderLibrary();
  requestAuditionRedraw();
}

function closeAudition() {
  auditionAudio.pause();
  auditionAudio.removeAttribute('src');
  auditionAudio.load();
  state.audition.path = null;
  state.audition.entry = null;
  document.getElementById('auditionBar').hidden = true;
  renderLibrary();
}

function toggleAuditionPlay(entry) {
  if (state.audition.path === entry.path) {
    if (auditionAudio.paused) auditionAudio.play().catch(() => {}); else auditionAudio.pause();
  } else {
    openAudition(entry);
  }
}

function drawAuditionWave() {
  const canvas = document.getElementById('auditionWave');
  const entry = state.audition.entry;
  if (!canvas) return;
  const cssW = canvas.clientWidth || 260, h = 46;
  const ctx = setupCanvasDPI(canvas, cssW, h);
  ctx.clearRect(0, 0, cssW, h);
  if (!entry) return;
  const mid = h / 2;
  if (entry.peaks && entry.peaks.length) {
    ctx.fillStyle = M3.primary + 'b0';
    const pw = Math.max(1, cssW / entry.peaks.length);
    entry.peaks.forEach((pk, i) => {
      const [mn, mx] = pk;
      const x = (i / entry.peaks.length) * cssW;
      ctx.fillRect(x, mid - mx * mid * 0.92, pw, Math.max(1, (mx - mn) * mid * 0.92));
    });
  }
  const dur = entry.duration || auditionAudio.duration || 0;
  if (dur > 0) {
    (entry.cues || []).forEach((cue, i) => {
      if (!cue) return;
      const x = clamp((cue.time / dur) * cssW, 0, cssW) + 0.5;
      ctx.strokeStyle = '#F0C05A';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      ctx.fillStyle = '#F0C05A';
      ctx.font = '700 9px Roboto, sans-serif';
      ctx.fillText(String(i + 1), x + 2, 9);
    });
    const cx = clamp((auditionAudio.currentTime / dur) * cssW, 0, cssW) + 0.5;
    ctx.strokeStyle = M3.error;
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  }
}

function renderCuePads() {
  const wrap = document.getElementById('cuePads');
  if (!wrap) return;
  wrap.innerHTML = '';
  const entry = state.audition.entry;
  const cues = (entry && entry.cues) || [];
  for (let i = 0; i < 4; i++) {
    const cue = cues[i];
    const btn = document.createElement('button');
    btn.className = 'cue-pad' + (cue ? ' set' : '');
    btn.textContent = cue ? `${i + 1} · ${formatTime(cue.time)}` : String(i + 1);
    btn.title = cue ? 'Click: jump · Shift+click: clear' : 'Click: set a cue here';
    btn.addEventListener('click', e => { if (e.shiftKey) clearCue(i); else useCue(i); });
    wrap.appendChild(btn);
  }
}

function useCue(i) {
  const entry = state.audition.entry;
  if (!entry) return;
  const cues = entry.cues ? entry.cues.slice() : [];
  if (cues[i]) {
    auditionAudio.currentTime = cues[i].time;
    auditionAudio.play().catch(() => {});
  } else {
    cues[i] = { time: auditionAudio.currentTime || 0, label: String(i + 1) };
    saveCues(entry, cues);
  }
}

function clearCue(i) {
  const entry = state.audition.entry;
  if (!entry || !entry.cues || !entry.cues[i]) return;
  const cues = entry.cues.slice();
  cues[i] = null;
  saveCues(entry, cues);
}

async function saveCues(entry, cues) {
  entry.cues = cues;
  renderCuePads();
  requestAuditionRedraw();
  try {
    await apiPost('/api/library/cues', { path: entry.path, cues });
  } catch (err) {
    toast('Cue save failed: ' + err.message, true);
  }
}

function wireAudition() {
  auditionAudio.addEventListener('timeupdate', () => {
    const el = document.getElementById('auditionCur');
    if (el) el.textContent = formatTime(auditionAudio.currentTime);
    requestAuditionRedraw();
  });
  auditionAudio.addEventListener('loadedmetadata', () => {
    const el = document.getElementById('auditionDur');
    if (el) el.textContent = formatTime(auditionAudio.duration);
    requestAuditionRedraw();
  });
  auditionAudio.addEventListener('play', () => { updateAuditionPlayIcon(); renderLibrary(); });
  auditionAudio.addEventListener('pause', () => { updateAuditionPlayIcon(); renderLibrary(); });
  auditionAudio.addEventListener('ended', () => { updateAuditionPlayIcon(); renderLibrary(); });

  document.getElementById('auditionPlay').addEventListener('click', () => {
    if (!state.audition.entry) return;
    if (auditionAudio.paused) auditionAudio.play().catch(() => {}); else auditionAudio.pause();
  });
  document.getElementById('auditionClose').addEventListener('click', closeAudition);
  document.getElementById('auditionWave').addEventListener('click', e => {
    const entry = state.audition.entry;
    const dur = entry && (entry.duration || auditionAudio.duration);
    if (!dur) return;
    const rect = e.target.getBoundingClientRect();
    const frac = clamp((e.clientX - rect.left) / rect.width, 0, 1);
    auditionAudio.currentTime = frac * dur;
  });
  window.addEventListener('resize', requestAuditionRedraw);
}

// ------------------------------------------------------- AI mix assistant --
// A small local, rule-based recommendation engine (Camelot harmonic distance
// + BPM compatibility over the already-analyzed library) -- no cloud calls,
// runs entirely on-device against data already sitting in the browser.

function pickSuggestReference() {
  if (state.armedLibraryPath) return state.libraryByPath.get(state.armedLibraryPath);
  if (state.selection && state.selection.type === 'clip') return state.libraryByPath.get(state.selection.clip.source_path);
  if (state.audition.entry) return state.audition.entry;
  return null;
}

function showSuggestions() {
  const ref = pickSuggestReference();
  const panel = document.getElementById('suggestPanel');
  if (!ref) {
    toast('基準にする曲をアーム(クリック)するか、クリップを選択してください', true);
    panel.hidden = true;
    return;
  }
  const scored = state.library
    .filter(e => e.path !== ref.path && !e.error)
    .map(e => ({ entry: e, score: camelotCompat(ref.camelot, e.camelot) * 0.55 + bpmCompat(ref.bpm, e.bpm) * 0.45 }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 8);

  panel.innerHTML = `<div class="suggest-panel-title">${escapeHtml(ref.filename)} と合う曲</div>`;
  if (!scored.length) {
    panel.innerHTML += `<div class="suggest-empty">比較できる曲がライブラリにありません</div>`;
  } else {
    for (const { entry, score } of scored) {
      const row = document.createElement('div');
      row.className = 'suggest-item';
      const pct = Math.round(clamp(score, 0, 1) * 100);
      row.innerHTML = `
        <span class="li-chip camelot" style="background:${camelotColor(entry.camelot) || 'var(--m3-surface-container-highest)'}">${escapeHtml(entry.camelot || '?')}</span>
        <span class="suggest-name">${escapeHtml(entry.filename)}</span>
        <span class="li-chip bpm">${entry.bpm ? entry.bpm.toFixed(1) : '--'}</span>
        <span class="suggest-score"><i style="width:${pct}%"></i></span>`;
      row.addEventListener('click', () => {
        state.armedLibraryPath = entry.path;
        renderLibrary();
        toast('Armed: ' + entry.filename);
      });
      panel.appendChild(row);
    }
  }
  panel.hidden = false;
}

async function scanLibrary() {
  const folder = document.getElementById('scanFolder').value.trim();
  if (!folder) { toast('フォルダパスを入力してください', true); return; }
  setStatus('Scanning…');
  document.getElementById('btnScan').disabled = true;
  try {
    const entries = await apiPost('/api/library/scan', { folder });
    state.library = entries;
    state.libraryByPath = new Map(entries.map(e => [e.path, e]));
    renderLibrary();
    toast(`Library: ${entries.length} files`);
  } catch (err) {
    toast('Scan failed: ' + err.message, true);
  } finally {
    setStatus(''); document.getElementById('btnScan').disabled = false;
  }
}

async function refreshLibraryFromCache(retry = 0) {
  try {
    const entries = await apiGet('/api/library');
    state.library = entries;
    state.libraryByPath = new Map(entries.map(e => [e.path, e]));
    renderLibrary();
    if (entries.length === 0 && retry < 8) setTimeout(() => refreshLibraryFromCache(retry + 1), 4000);
  } catch { /* backend still warming up */ }
}

// ------------------------------------------------------------ inspector --

function renderInspector() {
  const el = document.getElementById('inspectorContent');
  const sel = state.selection;
  if (!sel) {
    el.innerHTML = `<div class="inspector-empty">クリップ・オートメーションポイント・デッキを選択すると詳細と数値入力がここに出ます。</div>`;
    return;
  }

  if (sel.type === 'clip') {
    const c = sel.clip, deck = sel.deck;
    const dur = estimateClipDuration(c, deck, state.project);
    const syncNote = deck.sync && c.source_bpm ? ` (synced ${c.source_bpm}→${state.project.master_bpm} BPM)` : (deck.sync ? ' (BPM不明: unsynced)' : '');
    el.innerHTML = `
      <div class="inspector-block">
        <h4>CLIP · ${escapeHtml(deck.name)}</h4>
        <div class="insp-row"><label>Label</label><input type="text" id="fLabel" value="${escapeAttr(c.label)}"></div>
        <div class="insp-row"><label>Start (s)</label><input type="number" step="0.01" id="fStart" value="${c.timeline_start.toFixed(3)}"></div>
        <div class="insp-row"><label>Src offset (s)</label><input type="number" step="0.01" min="0" id="fOffset" value="${c.source_offset.toFixed(3)}"></div>
        <div class="insp-row"><label>Src length (s)</label><input type="number" step="0.01" min="0.05" id="fLength" value="${c.source_length.toFixed(3)}"></div>
        <div class="insp-row"><label>Loop count</label><input type="number" step="1" min="1" max="256" id="fLoop" value="${c.loop_count}"></div>
        <div class="insp-row"><label>Gain (trim)</label><input type="number" step="0.01" min="0" max="4" id="fGain" value="${c.gain}"></div>
        <div class="insp-row"><label>Fade in (s)</label><input type="number" step="0.001" min="0" id="fFadeIn" value="${c.fade_in}"></div>
        <div class="insp-row"><label>Fade out (s)</label><input type="number" step="0.001" min="0" id="fFadeOut" value="${c.fade_out}"></div>
        <div class="insp-row"><label>Pitch (semi)</label><input type="number" step="0.1" id="fPitch" value="${c.pitch_semitones}"></div>
        <div class="insp-row"><label>Source BPM</label><input type="number" step="0.01" id="fSrcBpm" value="${c.source_bpm ?? ''}" placeholder="unknown"></div>
        <div class="insp-row"><label>Reverse</label><input type="checkbox" id="fReverse" ${c.reverse ? 'checked' : ''}></div>
        <div class="insp-row" style="color:var(--m3-outline);font-size:10.5px;">≈ ${dur.toFixed(2)}s on timeline${syncNote}</div>
        <div class="insp-actions"><button class="btn small danger" id="fDelete">Delete Clip</button></div>
      </div>`;
    const on = (id, cb) => document.getElementById(id).addEventListener('input', cb);
    on('fLabel', e => { c.label = e.target.value; requestRedraw(); });
    on('fStart', e => { c.timeline_start = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    on('fOffset', e => { c.source_offset = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    on('fLength', e => { c.source_length = Math.max(0.05, parseFloat(e.target.value) || 0.05); requestRedraw(); });
    on('fLoop', e => { c.loop_count = Math.max(1, Math.min(256, parseInt(e.target.value, 10) || 1)); requestRedraw(); });
    on('fGain', e => { c.gain = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    on('fFadeIn', e => { c.fade_in = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    on('fFadeOut', e => { c.fade_out = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    on('fPitch', e => { c.pitch_semitones = parseFloat(e.target.value) || 0; requestRedraw(); });
    on('fSrcBpm', e => { c.source_bpm = e.target.value === '' ? null : (parseFloat(e.target.value) || null); requestRedraw(); });
    on('fReverse', e => { c.reverse = e.target.checked; requestRedraw(); });
    el.querySelectorAll('input').forEach(inp => inp.addEventListener('change', scheduleSync));
    document.getElementById('fDelete').addEventListener('click', () => {
      deck.clips = deck.clips.filter(x => x !== c);
      state.selection = null;
      rebuildDeckDOM(); renderInspector(); scheduleSync();
    });
  } else if (sel.type === 'point') {
    const p = sel.pointRef;
    el.innerHTML = `
      <div class="inspector-block">
        <h4>AUTOMATION POINT</h4>
        <div class="insp-row"><label>Lane</label><span>${escapeHtml(sel.label || '')}</span></div>
        <div class="insp-row"><label>Time (s)</label><input type="number" step="0.01" min="0" id="fPtTime" value="${p.time.toFixed(3)}"></div>
        <div class="insp-row"><label>Value</label><input type="number" step="0.01" id="fPtValue" value="${p.value.toFixed(3)}"></div>
        <div class="insp-actions"><button class="btn small danger" id="fPtDelete">Delete Point</button></div>
      </div>`;
    document.getElementById('fPtTime').addEventListener('input', e => { p.time = Math.max(0, parseFloat(e.target.value) || 0); requestRedraw(); });
    document.getElementById('fPtValue').addEventListener('input', e => { p.value = parseFloat(e.target.value) || 0; requestRedraw(); });
    el.querySelectorAll('input').forEach(inp => inp.addEventListener('change', scheduleSync));
    document.getElementById('fPtDelete').addEventListener('click', () => {
      const idx = sel.points.indexOf(p);
      if (idx >= 0) sel.points.splice(idx, 1);
      state.selection = null;
      requestRedraw(); renderInspector(); scheduleSync();
    });
  }
}

function deleteSelectedViaKey() {
  const sel = state.selection;
  if (!sel) return;
  if (sel.type === 'clip') {
    sel.deck.clips = sel.deck.clips.filter(x => x !== sel.clip);
    state.selection = null;
    rebuildDeckDOM(); renderInspector(); scheduleSync();
  } else if (sel.type === 'point') {
    const idx = sel.points.indexOf(sel.pointRef);
    if (idx >= 0) sel.points.splice(idx, 1);
    state.selection = null;
    requestRedraw(); renderInspector(); scheduleSync();
  }
}

// -------------------------------------------------------------- project --

function emptyProjectFallback() {
  return {
    name: 'Untitled Mix', master_bpm: 128, sample_rate: 44100,
    master: { gain: 1, automation: [] },
    crossfader: { value: 0.5, automation: [], curve: 'equal_power' },
    reverb: { room_size: 0.5, damping: 0.5, width: 1, pre_delay_ms: 20, return_gain: 1 },
    decks: [],
  };
}

function loadProjectIntoUI(project) {
  state.project = project;
  state.selection = null;
  state.armedLibraryPath = null;
  state.expandedAutomation = {};
  for (const deck of project.decks) state.expandedAutomation[deck.id] = new Set(deck.type === 'track' ? ['gain'] : []);

  document.getElementById('projectName').value = project.name;
  document.getElementById('masterBpm').value = project.master_bpm;
  document.getElementById('crossfaderValue').value = project.crossfader.value;
  document.getElementById('masterGain').value = project.master.gain;
  document.getElementById('revRoom').value = project.reverb.room_size;
  document.getElementById('revDamp').value = project.reverb.damping;
  document.getElementById('revWidth').value = project.reverb.width;
  document.getElementById('revPreDelay').value = project.reverb.pre_delay_ms;
  document.getElementById('revReturn').value = project.reverb.return_gain;

  rebuildDeckDOM();
  renderInspector();
}

async function doSave() {
  state.project.name = document.getElementById('projectName').value.trim() || 'Untitled Mix';
  try {
    const res = await apiPost('/api/projects/save', { project: state.project });
    toast('Saved: ' + res.filename);
    refreshProjectList();
  } catch (err) { toast('Save failed: ' + err.message, true); }
}

async function refreshProjectList() {
  try {
    const list = await apiGet('/api/projects');
    const sel = document.getElementById('projectList');
    sel.innerHTML = '<option value="">Load project…</option>' + list.map(p => `<option value="${escapeAttr(p.file)}">${escapeHtml(p.name)} (${p.deck_count} decks)</option>`).join('');
  } catch { /* ignore */ }
}

async function doLoad(filename) {
  if (!filename) return;
  try {
    const project = await apiPost(`/api/projects/${encodeURIComponent(filename)}/load`, {});
    loadProjectIntoUI(project);
    initHistory();
    toast('Loaded ' + project.name);
  } catch (err) { toast('Load failed: ' + err.message, true); }
}

async function doNew() {
  if (!confirm('現在のプロジェクトの未保存の変更は失われます。新規作成しますか？')) return;
  const project = await apiPost('/api/project/new', {});
  loadProjectIntoUI(project);
  initHistory();
}

// ----------------------------------------------------------- transport --

async function doPreview() {
  setStatus('Rendering preview…');
  document.getElementById('btnPreview').disabled = true;
  try {
    const res = await apiPost('/api/preview', { project: state.project, start: 0, end: null, max_duration: 180 });
    const audio = document.getElementById('previewAudio');
    audio.src = res.url;
    audio.play().catch(() => {});
    setStatus(`OK (${formatTime(res.duration)})`);
    if (res.warnings && res.warnings.length) toast(res.warnings.join(' / '));
  } catch (err) {
    toast('Preview failed: ' + err.message, true); setStatus('');
  } finally {
    document.getElementById('btnPreview').disabled = false;
  }
}

async function doExport() {
  setStatus('Exporting…');
  document.getElementById('btnExport').disabled = true;
  try {
    const res = await apiPost('/api/export', { project: state.project, start: 0, end: null, max_duration: null });
    setStatus(`Exported (${formatTime(res.duration)})`);
    toast('Export complete: ' + res.filename);
    const a = document.createElement('a');
    a.href = res.url; a.download = res.filename;
    document.body.appendChild(a); a.click(); a.remove();
    if (res.warnings && res.warnings.length) toast(res.warnings.join(' / '));
  } catch (err) {
    toast('Export failed: ' + err.message, true);
  } finally {
    setStatus(''); document.getElementById('btnExport').disabled = false;
  }
}

// --------------------------------------------------------------- init --

function wireStaticControls() {
  const onLaneChange = () => { requestRedraw(); renderInspector(); };
  wireLane(document.getElementById('crossfaderCanvas'),
    () => ({ points: state.project.crossfader.automation, base: state.project.crossfader.value, min: 0, max: 1, color: M3.onSurfaceVariant, ref: 0.5, label: 'Crossfader' }),
    onLaneChange);
  wireLane(document.getElementById('masterCanvas'),
    () => ({ points: state.project.master.automation, base: state.project.master.gain, min: 0, max: 1.5, color: M3.onSurfaceVariant, ref: 1.0, label: 'Master Gain' }),
    onLaneChange);

  document.getElementById('rulerCanvas').addEventListener('mousedown', e => {
    const rect = e.target.getBoundingClientRect();
    state.playhead = Math.max(0, maybeSnapTime((e.clientX - rect.left) / state.pxPerSecond));
    requestRedraw();
  });

  document.getElementById('masterBpm').addEventListener('input', e => { state.project.master_bpm = parseFloat(e.target.value) || 120; requestRedraw(); });
  document.getElementById('masterBpm').addEventListener('change', scheduleSync);
  document.getElementById('crossfaderValue').addEventListener('input', e => { state.project.crossfader.value = parseFloat(e.target.value); requestRedraw(); });
  document.getElementById('crossfaderValue').addEventListener('change', scheduleSync);
  document.getElementById('masterGain').addEventListener('input', e => { state.project.master.gain = parseFloat(e.target.value); requestRedraw(); });
  document.getElementById('masterGain').addEventListener('change', scheduleSync);

  const reverbSync = () => {
    state.project.reverb.room_size = parseFloat(document.getElementById('revRoom').value);
    state.project.reverb.damping = parseFloat(document.getElementById('revDamp').value);
    state.project.reverb.width = parseFloat(document.getElementById('revWidth').value);
    state.project.reverb.pre_delay_ms = parseFloat(document.getElementById('revPreDelay').value) || 0;
    state.project.reverb.return_gain = parseFloat(document.getElementById('revReturn').value);
  };
  ['revRoom', 'revDamp', 'revWidth', 'revPreDelay', 'revReturn'].forEach(id => {
    document.getElementById(id).addEventListener('input', reverbSync);
    document.getElementById(id).addEventListener('change', scheduleSync);
  });

  document.getElementById('btnScan').addEventListener('click', scanLibrary);
  document.getElementById('btnPreview').addEventListener('click', doPreview);
  document.getElementById('btnExport').addEventListener('click', doExport);
  document.getElementById('btnSave').addEventListener('click', doSave);
  document.getElementById('btnNewProject').addEventListener('click', doNew);
  document.getElementById('projectList').addEventListener('change', e => doLoad(e.target.value));
  document.getElementById('btnAddTrackDeck').addEventListener('click', () => addDeck('track'));
  document.getElementById('btnAddShotDeck').addEventListener('click', () => addDeck('shot'));
  document.getElementById('zoomIn').addEventListener('click', () => { state.pxPerSecond = clamp(state.pxPerSecond * 1.4, 6, 400); requestRedraw(); });
  document.getElementById('zoomOut').addEventListener('click', () => { state.pxPerSecond = clamp(state.pxPerSecond / 1.4, 6, 400); requestRedraw(); });
  document.getElementById('snapToggle').addEventListener('change', e => { state.snap = e.target.checked; });

  document.getElementById('btnUndo').addEventListener('click', undo);
  document.getElementById('btnRedo').addEventListener('click', redo);
  document.getElementById('btnSuggest').addEventListener('click', showSuggestions);
  wireAudition();

  window.addEventListener('keydown', e => {
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
      e.preventDefault(); redo();
    } else if (e.key === 'Delete' || e.key === 'Backspace') { if (state.selection) { deleteSelectedViaKey(); e.preventDefault(); } }
    else if (e.key === 'Escape') { state.armedLibraryPath = null; state.selection = null; renderLibrary(); requestRedraw(); renderInspector(); }
    else if (state.audition.entry && /^[1-4]$/.test(e.key)) {
      const i = parseInt(e.key, 10) - 1;
      if (e.shiftKey) clearCue(i); else useCue(i);
      e.preventDefault();
    } else if (state.audition.entry && e.code === 'Space') {
      if (auditionAudio.paused) auditionAudio.play().catch(() => {}); else auditionAudio.pause();
      e.preventDefault();
    }
  });
}

async function init() {
  wireStaticControls();
  try {
    const project = await apiGet('/api/project');
    loadProjectIntoUI(project);
  } catch (err) {
    toast('Backend not reachable: ' + err.message, true);
    loadProjectIntoUI(emptyProjectFallback());
  }
  initHistory();
  refreshLibraryFromCache();
  refreshProjectList();
}

init();
