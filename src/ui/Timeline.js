// Timeline UI: piecewise mapping between slider position [0,1] and years before present.
// The track is a quiet, single-hue era band; only the era under the playhead takes its own colour.
import { ERAS, EVENTS, formatYears } from '../data/eras.js';
import { MOON_ERAS, MOON_EVENTS } from '../data/moon.js';

const Ma = 1e6, ka = 1e3;

export const SCALES = {
  // [sliderFraction, yearsBP] anchors (fraction ascending, years descending)
  deep: [[0, 4540 * Ma], [0.16, 2500 * Ma], [0.32, 541 * Ma], [0.62, 66 * Ma], [0.80, 2.58 * Ma], [0.90, 300 * ka], [0.96, 12 * ka], [1, 0]],
  human: [[0, 300 * ka], [0.22, 100 * ka], [0.45, 45 * ka], [0.62, 15 * ka], [0.78, 5 * ka], [0.9, 500], [1, 0]],
  now: [[0, 0], [1, 0]],
  // the Moon's eventful history is its first billion years and the last seven decades: give both room
  moon: [[0, 4540 * Ma], [0.05, 4510 * Ma], [0.21, 4350 * Ma], [0.34, 4100 * Ma], [0.49, 3800 * Ma], [0.66, 3100 * Ma], [0.76, 800 * Ma], [0.86, 70], [1, 0]],
};
SCALES.life = SCALES.deep;

// where each mode opens the first time: never on an empty picture
const START = { deep: 0, human: 0, now: 1, moon: 0.075, life: 1 };

const HUMAN_BANDS = [
  [300 * ka, 130 * ka, '#b98a5a', '非洲起源'], [130 * ka, 70 * ka, '#c49a55', '早期扩散'], [70 * ka, 45 * ka, '#d4a558', '走出非洲'],
  [45 * ka, 20 * ka, '#8fa8d8', '欧亚 · 大洋洲'], [20 * ka, 11.7 * ka, '#a9c8e6', '冰盛期 · 美洲'], [11.7 * ka, 5 * ka, '#9cc98a', '农业起源'],
  [5 * ka, 1000, '#d8bf78', '文明 · 远洋'], [1000, 0, '#f0cf7a', '全球化'],
];

export function sliderToYears(mode, s) {
  const a = SCALES[mode];
  for (let i = 0; i + 1 < a.length; i++) {
    if (s <= a[i + 1][0]) {
      const f = (s - a[i][0]) / (a[i + 1][0] - a[i][0] || 1);
      return a[i][1] + (a[i + 1][1] - a[i][1]) * f;
    }
  }
  return 0;
}
export function yearsToSlider(mode, y) {
  const a = SCALES[mode];
  if (y >= a[0][1]) return 0;
  for (let i = 0; i + 1 < a.length; i++) {
    if (y >= a[i + 1][1]) {
      const f = (a[i][1] - y) / (a[i][1] - a[i + 1][1] || 1);
      return a[i][0] + (a[i + 1][0] - a[i][0]) * f;
    }
  }
  return 1;
}

export class Timeline {
  constructor({ onChange }) {
    this.mode = null;
    this.root = document.getElementById('timeline');
    this.slider = document.getElementById('tl-slider');
    this.readout = document.getElementById('tl-readout');
    this.erasEl = document.getElementById('tl-eras');
    this.eventsEl = document.getElementById('tl-events');
    this.playBtn = document.getElementById('tl-play');
    this.speedBtn = document.getElementById('tl-speed');
    this.onChange = onChange;
    this.playing = false;
    this.speed = 1;
    this.value = 0;
    this.saved = {};
    this.bands = [];
    this.marks = [];
    this.slider.addEventListener('input', () => { this.value = this.slider.value / 10000; this.emit(true); });
    this.playBtn.addEventListener('click', () => this.togglePlay());
    this.speedBtn.addEventListener('click', () => {
      this.speed = this.speed === 1 ? 3 : this.speed === 3 ? 0.5 : 1;
      this.speedBtn.textContent = `${this.speed}×`;
    });
    window.addEventListener('keydown', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      if (document.body.classList.contains('tour')) return;
      if (e.code === 'Space') { e.preventDefault(); this.togglePlay(); }
      if (e.code === 'ArrowRight') this.step(0.004);
      if (e.code === 'ArrowLeft') this.step(-0.004);
    });
    this.setMode('deep');
  }

  get years() { return sliderToYears(this.mode, this.value); }

  setMode(mode) {
    if (this.mode) this.saved[this.mode] = this.value; // come back to where you left
    this.mode = mode;
    this.setPlaying(false);
    this.value = mode === 'now' ? 1 : (this.saved[mode] ?? START[mode] ?? 0);
    this.slider.value = Math.round(this.value * 10000);
    this.buildEras();
    this.emit(false);
  }

  setYears(y, silent = false) {
    this.value = yearsToSlider(this.mode, y);
    this.slider.value = Math.round(this.value * 10000);
    if (!silent) this.emit(false);
    else this.markCurrent();
  }

  step(d) { this.value = Math.min(1, Math.max(0, this.value + d)); this.slider.value = Math.round(this.value * 10000); this.emit(true); }

  setPlaying(on) {
    this.playing = on;
    this.playBtn.textContent = on ? '❚❚' : '▶';
    this.playBtn.classList.toggle('playing', on);
  }

  togglePlay() {
    if (this.mode === 'now') return;
    if (!this.playing && this.value >= 0.999) { this.value = 0; this.slider.value = 0; this.emit(true); } // replay from the start
    this.setPlaying(!this.playing);
  }

  /** advance while playing; dt seconds */
  tick(dt) {
    if (!this.playing) return;
    const duration = this.mode === 'human' ? 90 : this.mode === 'moon' ? 110 : 150; // seconds for a full sweep at 1x
    this.value += dt * this.speed / duration;
    if (this.value >= 1) { this.value = 1; this.setPlaying(false); }
    this.slider.value = Math.round(this.value * 10000);
    this.emit(true);
  }

  emit(fromUser) {
    this.readout.textContent = formatYears(this.years);
    this.markCurrent();
    if (this.onChange) this.onChange(this.years, fromUser);
  }

  /** light up the band under the playhead and dim the events still in the future */
  markCurrent() {
    const y = this.years;
    for (const b of this.bands) {
      const current = (y <= b.start && y > b.end) || (b.end === 0 && y <= 0);
      b.el.classList.toggle('current', current);
      b.el.classList.toggle('past', !current && y <= b.end);
    }
    for (const m of this.marks) m.el.classList.toggle('passed', y <= m.t);
    this.root.style.setProperty('--tl-pos', (this.value * 100).toFixed(2) + '%');
  }

  buildEras() {
    this.erasEl.innerHTML = '';
    this.eventsEl.innerHTML = '';
    this.bands = [];
    this.marks = [];
    if (this.mode === 'now') return;
    const scale = this.mode;
    let eras, events = [];
    if (this.mode === 'human') eras = HUMAN_BANDS.map(([start, end, color, short]) => ({ start, end, color, short, title: short }));
    else if (this.mode === 'moon') { eras = MOON_ERAS.map((e) => ({ ...e, title: `${e.eon} · ${e.name}` })); events = MOON_EVENTS; }
    else { eras = ERAS.map((e) => ({ ...e, title: `${e.eon} · ${e.name}` })); events = EVENTS; }
    for (const e of eras) {
      const a = yearsToSlider(scale, e.start), b = yearsToSlider(scale, e.end);
      const w = (b - a) * 100;
      if (w <= 0.01) continue;
      const div = document.createElement('div');
      div.className = 'tl-era';
      div.style.width = w + '%';
      div.style.setProperty('--c', e.color);
      div.title = e.title;
      div.innerHTML = `<i></i><span${w > 3.4 ? '' : ' class="tight"'}>${e.short}</span>`;
      div.addEventListener('click', () => this.setYears(e.start * 0.999));
      this.erasEl.appendChild(div);
      this.bands.push({ start: e.start, end: e.end, el: div });
    }
    for (const ev of events) {
      const m = document.createElement('div');
      m.className = 'tl-event';
      m.style.left = yearsToSlider(scale, ev.t) * 100 + '%';
      m.dataset.label = `${ev.name} · ${formatYears(ev.t)}`;
      m.addEventListener('click', () => this.setYears(ev.t));
      this.eventsEl.appendChild(m);
      this.marks.push({ t: ev.t, el: m });
    }
  }
}
