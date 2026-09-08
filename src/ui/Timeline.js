// Timeline UI: piecewise mapping between slider position [0,1] and years before present.
import { ERAS, EVENTS, formatYears } from '../data/eras.js';

const Ma = 1e6, ka = 1e3;

export const SCALES = {
  // [sliderFraction, yearsBP] anchors (fraction ascending, years descending)
  deep: [[0, 4540 * Ma], [0.16, 2500 * Ma], [0.32, 541 * Ma], [0.62, 66 * Ma], [0.80, 2.58 * Ma], [0.90, 300 * ka], [0.96, 12 * ka], [1, 0]],
  human: [[0, 300 * ka], [0.22, 100 * ka], [0.45, 45 * ka], [0.62, 15 * ka], [0.78, 5 * ka], [0.9, 500], [1, 0]],
  now: [[0, 0], [1, 0]],
};

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
  constructor({ onChange, onPlayToggle }) {
    this.mode = 'deep';
    this.slider = document.getElementById('tl-slider');
    this.readout = document.getElementById('tl-readout');
    this.erasEl = document.getElementById('tl-eras');
    this.eventsEl = document.getElementById('tl-events');
    this.playBtn = document.getElementById('tl-play');
    this.onChange = onChange;
    this.playing = false;
    this.speed = 1;
    this.value = 0;
    this.slider.addEventListener('input', () => { this.value = this.slider.value / 10000; this.emit(true); });
    this.playBtn.addEventListener('click', () => this.togglePlay());
    document.querySelectorAll('.speed-btn').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('.speed-btn').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      this.speed = parseFloat(b.dataset.speed);
    }));
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
    this.mode = mode;
    this.value = mode === 'now' ? 1 : 0;
    this.slider.value = Math.round(this.value * 10000);
    this.buildEras();
    this.emit(false);
  }

  setYears(y, silent = false) {
    this.value = yearsToSlider(this.mode, y);
    this.slider.value = Math.round(this.value * 10000);
    if (!silent) this.emit(false);
  }

  step(d) { this.value = Math.min(1, Math.max(0, this.value + d)); this.slider.value = Math.round(this.value * 10000); this.emit(true); }

  togglePlay() {
    if (this.mode === 'now') return;
    this.playing = !this.playing;
    this.playBtn.textContent = this.playing ? '❚❚' : '▶';
  }

  /** advance while playing; dt seconds */
  tick(dt) {
    if (!this.playing) return;
    const duration = this.mode === 'deep' ? 150 : 90; // seconds for a full sweep at 1x
    this.value += dt * this.speed / duration;
    if (this.value >= 1) { this.value = 1; this.playing = false; this.playBtn.textContent = '▶'; }
    this.slider.value = Math.round(this.value * 10000);
    this.emit(true);
  }

  emit(fromUser) {
    this.readout.textContent = formatYears(this.years);
    if (this.onChange) this.onChange(this.years, fromUser);
  }

  buildEras() {
    this.erasEl.innerHTML = '';
    this.eventsEl.innerHTML = '';
    if (this.mode === 'now') { this.erasEl.style.display = 'none'; this.eventsEl.style.display = 'none'; return; }
    this.erasEl.style.display = 'flex';
    this.eventsEl.style.display = 'block';
    if (this.mode === 'deep') {
      for (const e of ERAS) {
        const a = yearsToSlider('deep', e.start), b = yearsToSlider('deep', e.end);
        const w = (b - a) * 100;
        if (w <= 0.01) continue;
        const div = document.createElement('div');
        div.className = 'tl-era';
        div.style.width = w + '%';
        div.style.background = e.color + 'aa';
        div.textContent = w > 3.2 ? e.short : '';
        div.title = `${e.eon} · ${e.name}`;
        div.addEventListener('click', () => this.setYears(e.start * 0.999));
        this.erasEl.appendChild(div);
      }
      for (const ev of EVENTS) {
        const x = yearsToSlider('deep', ev.t) * 100;
        const m = document.createElement('div');
        m.className = 'tl-event';
        m.style.left = x + '%';
        m.dataset.label = `${ev.name} · ${formatYears(ev.t)}`;
        m.addEventListener('click', () => this.setYears(ev.t));
        this.eventsEl.appendChild(m);
      }
    } else if (this.mode === 'human') {
      const bands = [
        [300 * ka, 130 * ka, '#7a5a3a', '非洲起源'], [130 * ka, 70 * ka, '#8a6a3a', '早期扩散'], [70 * ka, 45 * ka, '#a07a40', '走出非洲'],
        [45 * ka, 20 * ka, '#6a7ea0', '欧亚 · 大洋洲'], [20 * ka, 11.7 * ka, '#89a8c8', '冰盛期 · 美洲'], [11.7 * ka, 5 * ka, '#7ea070', '农业起源'],
        [5 * ka, 1000, '#b09a60', '文明 · 远洋'], [1000, 0, '#d0b060', '全球化'],
      ];
      for (const [s, e, c, n] of bands) {
        const a = yearsToSlider('human', s), b = yearsToSlider('human', e);
        const div = document.createElement('div');
        div.className = 'tl-era';
        div.style.width = (b - a) * 100 + '%';
        div.style.background = c + 'aa';
        div.textContent = n;
        div.addEventListener('click', () => this.setYears(s * 0.999));
        this.erasEl.appendChild(div);
      }
    }
  }
}
