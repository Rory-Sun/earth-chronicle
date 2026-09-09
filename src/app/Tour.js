// Guided tour: chapter-driven camera flights + timeline sweeps with auto-advance.
import * as THREE from 'three';
import { lonLatToVec3 } from '../earth/Plates.js';
import { CHAPTERS, ACTS } from '../data/tour.js';

const FLY_SECONDS = 2.6;
const ease = (u) => u * u * (3 - 2 * u);

export class Tour {
  constructor(app) {
    this.app = app;
    this.active = false;
    this.playing = true;
    this.speed = 1;
    this.index = -1;
    this.t = 0;
    this.root = document.getElementById('tour');
    const $ = (id) => document.getElementById(id);
    this.els = { kicker: $('tour-kicker'), count: $('tour-count'), title: $('tour-title'), text: $('tour-text'), act: $('tour-act'), bar: $('tour-bar'), chips: $('tour-chips'), play: $('tour-play'), speed: $('tour-speed'), card: this.root.querySelector('.tour-card') };
    $('tour-prev').addEventListener('click', () => this.go(this.index - 1));
    $('tour-next').addEventListener('click', () => this.go(this.index + 1));
    this.els.play.addEventListener('click', () => this.togglePlay());
    this.els.speed.addEventListener('click', () => { this.speed = this.speed === 1 ? 2 : this.speed === 2 ? 0.5 : 1; this.els.speed.textContent = `${this.speed}×`; });
    $('tour-exit').addEventListener('click', () => this.stop());
    $('tour-clear').addEventListener('click', () => document.body.classList.add('clear'));
    $('clear-exit').addEventListener('click', () => document.body.classList.remove('clear'));
    this.buildChips();
    window.addEventListener('keydown', (e) => {
      if (!this.active || (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'))) return;
      if (e.code === 'ArrowRight') { e.preventDefault(); this.go(this.index + 1); }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); this.go(this.index - 1); }
      else if (e.code === 'Space') { e.preventDefault(); this.togglePlay(); }
      else if (e.code === 'Escape') { if (document.body.classList.contains('clear')) document.body.classList.remove('clear'); else this.stop(); }
    });
  }

  buildChips() {
    this.els.chips.innerHTML = '';
    let lastAct = -1;
    CHAPTERS.forEach((c, i) => {
      if (c.act !== lastAct) {
        lastAct = c.act;
        const sep = document.createElement('span');
        sep.className = 'tour-sep';
        sep.textContent = ['Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ'][c.act];
        sep.title = ACTS[c.act];
        this.els.chips.appendChild(sep);
      }
      const b = document.createElement('button');
      b.className = 'tour-chip';
      b.textContent = String(i + 1).padStart(2, '0');
      b.title = c.kicker;
      b.addEventListener('click', () => this.go(i));
      this.els.chips.appendChild(b);
    });
  }

  start(i = 0) {
    const app = this.app;
    this.active = true;
    this.playing = true;
    document.body.classList.add('tour');
    document.body.classList.remove('clear');
    this.root.hidden = false;
    app.timeline.playing = false;
    app.timeline.playBtn.textContent = '▶';
    app.earth.group.rotation.y = 0;
    this.go(i);
  }

  stop() {
    this.active = false;
    document.body.classList.remove('tour', 'clear');
    this.root.hidden = true;
    this.app.flyTo = null;
    this.app.idleTimer = 6;
    this.app.setSunTarget(null);
    // leave the timeline where the tour ended; the standard panels take over
    this.app.info.currentId = null;
    this.app.onTime(this.app.timeline.years, false);
  }

  togglePlay() {
    this.playing = !this.playing;
    this.els.play.textContent = this.playing ? '❚❚  暂停导览' : '▶  继续导览';
  }

  chapterDir(ch) {
    if (ch.view === 'night') return this.app.sunDir.clone().negate().normalize();
    // moon views are relative to the Moon: 'near' puts the camera between Earth and Moon, 'far' behind the Moon looking back at Earth
    if (ch.view === 'moon-near') return this.app.moon.position.clone().negate().normalize();
    if (ch.view === 'moon-far') return this.app.moon.position.clone().normalize().add(new THREE.Vector3(0, 0.8, 0)).normalize();
    return lonLatToVec3(ch.view[0], ch.view[1]).normalize();
  }

  go(i) {
    if (i < 0) i = 0;
    if (i >= CHAPTERS.length) { i = CHAPTERS.length - 1; this.playing = false; this.els.play.textContent = '↺  重新开始'; this.els.play.onclick = null; }
    const ch = CHAPTERS[i];
    const app = this.app;
    this.index = i;
    this.t = 0;
    if (this.playing) this.els.play.textContent = '❚❚  暂停导览';
    if (app.mode !== ch.mode) app.setMode(ch.mode);
    app.earth.group.rotation.y = 0;
    app.timeline.setYears(ch.from);
    const dist = typeof ch.view === 'string' ? ch.dist : ch.view[2];
    const dir = this.chapterDir(ch);
    app.flyToDir(dir, dist, FLY_SECONDS);
    // light the hemisphere we are looking at: sun sits up-right of the camera, so relief and terminator stay visible
    if (ch.view === 'night') app.setSunTarget(null);
    else if (ch.view === 'moon-far') app.setSunTarget(dir.clone().multiplyScalar(-0.2).add(new THREE.Vector3(0, 0.6, 0)).add(this.app.moon.position.clone().normalize().multiplyScalar(-0.9)).normalize());
    else {
      const up = new THREE.Vector3(0, 1, 0);
      const right = new THREE.Vector3().crossVectors(dir, up).normalize();
      if (right.lengthSq() < 1e-6) right.set(1, 0, 0);
      const sun = dir.clone().multiplyScalar(0.72).addScaledVector(right, -0.55).addScaledVector(up, 0.35).normalize();
      app.setSunTarget(sun);
    }
    // text
    const card = this.els.card;
    card.classList.remove('swap'); void card.offsetWidth; card.classList.add('swap');
    this.els.kicker.textContent = ch.kicker;
    this.els.count.textContent = `${String(i + 1).padStart(2, '0')} / ${CHAPTERS.length}`;
    this.els.title.innerHTML = ch.title.split('\n').map((s) => `<span>${s}</span>`).join('<br>');
    this.els.text.textContent = ch.text;
    this.els.act.textContent = ACTS[ch.act];
    this.els.chips.querySelectorAll('.tour-chip').forEach((b, k) => { b.classList.toggle('active', k === i); b.classList.toggle('done', k < i); });
    const active = this.els.chips.querySelector('.tour-chip.active');
    if (active) active.scrollIntoView({ block: 'nearest', inline: 'center' });
    this.els.bar.style.width = '0%';
  }

  restart() { this.els.play.textContent = '❚❚  暂停导览'; this.playing = true; this.go(0); }

  tick(dt) {
    if (!this.active || this.index < 0) return;
    const ch = CHAPTERS[this.index];
    const total = ch.dur + ch.hold;
    if (this.els.play.textContent.startsWith('↺')) {
      // finished state: clicking the main button restarts
      this.els.play.onclick = () => { this.els.play.onclick = null; this.restart(); };
      return;
    }
    if (!this.playing) return;
    this.t += dt * this.speed;
    const u = Math.min(1, this.t / Math.max(0.001, ch.dur));
    if (ch.dur > 0) {
      const years = ch.from + (ch.to - ch.from) * ease(u);
      this.app.timeline.setYears(years);
    }
    this.els.bar.style.width = `${Math.min(100, (this.t / total) * 100).toFixed(1)}%`;
    if (this.t >= total) {
      if (this.index + 1 < CHAPTERS.length) this.go(this.index + 1);
      else { this.playing = false; this.els.play.textContent = '↺  重新开始'; }
    }
  }
}
