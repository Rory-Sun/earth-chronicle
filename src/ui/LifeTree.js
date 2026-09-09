// 生命之树: a radial, time-synced phylogeny drawn in SVG.
// Radius = time (the same non-linear mapping as the deep-time slider), so the tree grows outward from the
// last common ancestor at the centre to today's lineages on the rim. The current time is a glowing ring:
// lineages appear when they originate, their tips ride the ring, extinct branches stop with a †.
import { LIFE_NODES, LIFE_BY_ID, LIFE_GROUPS } from '../data/life.js';
import { yearsToSlider } from './Timeline.js';
import { formatYears } from '../data/eras.js';

const NS = 'http://www.w3.org/2000/svg';
const S = 1280;                 // tree space is S x S units
const CX = S / 2, CY = S / 2;
const R0 = 26;                  // radius of the root (LUCA)
const R_MAX = S / 2 - 150;      // radius of "today"; the margin holds the tip labels
const LABEL_MAX = 0.985;        // slider fraction where the "today" edge sits
const SWEEP = 344;              // degrees of circle used by the leaves (gap at the top for the era labels)
const A_START = -90 + (360 - SWEEP) / 2; // first leaf angle (degrees, clockwise from +x in screen space)

function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const rad = (deg) => (deg * Math.PI) / 180;
const px = (r, a) => CX + r * Math.cos(rad(a));
const py = (r, a) => CY + r * Math.sin(rad(a));
const fmt = (v) => (Math.round(v * 100) / 100).toString();

export class LifeTree {
  constructor({ onJump }) {
    this.root = document.getElementById('life');
    this.svg = document.getElementById('life-svg');
    this.card = document.getElementById('life-card');
    this.stats = document.getElementById('life-stats');
    this.onJump = onJump;
    this.years = 4540e6;
    this.zoom = 1; this.panX = 0; this.panY = 0;
    this.selected = null;
    this.layout();
    this.build();
    this.bindInteraction();
    this.renderLegend();
    window.addEventListener('resize', () => this.fit());
  }

  // ---------- layout: leaves in DFS order share the circle; internal angle = midpoint of first/last child
  layout() {
    const children = {};
    for (const n of LIFE_NODES) { children[n.id] = children[n.id] || []; if (n.parent) (children[n.parent] = children[n.parent] || []).push(n); }
    this.children = children;
    const leaves = [];
    const visit = (n) => {
      const kids = children[n.id] || [];
      if (!kids.length) { leaves.push(n); return; }
      for (const k of kids) visit(k);
    };
    visit(LIFE_BY_ID.luca);
    const step = SWEEP / Math.max(1, leaves.length - 1);
    leaves.forEach((n, i) => { n.angle = A_START + i * step; n.isInternal = false; });
    const fix = (n) => {
      const kids = children[n.id] || [];
      if (!kids.length) return;
      for (const k of kids) fix(k);
      n.angle = (kids[0].angle + kids[kids.length - 1].angle) / 2;
      n.isInternal = true;
      n.lastBranch = Math.min(...kids.map((k) => k.start)); // youngest divergence (Ma)
    };
    fix(LIFE_BY_ID.luca);
    for (const n of LIFE_NODES) {
      n.r0 = this.rOf(n.start);
      n.rEnd = this.rOf(n.end);
      n.rLast = n.isInternal ? this.rOf(n.lastBranch) : n.rEnd;
    }
  }

  /** radius for a time (Ma), following the deep-time slider mapping so Phanerozoic gets most of the radius */
  rOf(ma) { return R0 + (R_MAX - R0) * Math.min(LABEL_MAX, yearsToSlider('deep', ma * 1e6)) / LABEL_MAX; }

  // ---------- build static SVG
  build() {
    const svg = this.svg;
    svg.innerHTML = '';
    svg.setAttribute('viewBox', `0 0 ${S} ${S}`);
    const defs = el('defs', {}, svg);
    const glow = el('filter', { id: 'life-glow', x: '-50%', y: '-50%', width: '200%', height: '200%' }, defs);
    el('feGaussianBlur', { stdDeviation: 2.2, result: 'b' }, glow);
    const merge = el('feMerge', {}, glow); el('feMergeNode', { in: 'b' }, merge); el('feMergeNode', { in: 'SourceGraphic' }, merge);
    const ringGlow = el('filter', { id: 'life-ring-glow', x: '-20%', y: '-20%', width: '140%', height: '140%' }, defs);
    el('feGaussianBlur', { stdDeviation: 4, result: 'b' }, ringGlow);
    const m2 = el('feMerge', {}, ringGlow); el('feMergeNode', { in: 'b' }, m2); el('feMergeNode', { in: 'SourceGraphic' }, m2);
    const grad = el('radialGradient', { id: 'life-core', cx: '50%', cy: '50%', r: '50%' }, defs);
    el('stop', { offset: '0%', 'stop-color': 'rgba(255,200,120,0.55)' }, grad);
    el('stop', { offset: '100%', 'stop-color': 'rgba(255,200,120,0)' }, grad);

    this.view = el('g', { class: 'life-view' }, svg);
    // era rings (annuli) + labels along the top gap
    const eras = [[4540, 4000, '冥古宙'], [4000, 2500, '太古宙'], [2500, 541, '元古宙'], [541, 252, '古生代'], [252, 66, '中生代'], [66, 0, '新生代']];
    const bands = el('g', { class: 'life-bands' }, this.view);
    eras.forEach(([a, b, name], i) => {
      const r0 = Math.max(R0, this.rOf(a)), r1 = this.rOf(b);
      el('circle', { cx: CX, cy: CY, r: (r0 + r1) / 2, fill: 'none', stroke: i % 2 ? 'rgba(120,150,210,0.05)' : 'rgba(120,150,210,0.0)', 'stroke-width': Math.max(0, r1 - r0) }, bands);
      el('circle', { cx: CX, cy: CY, r: r1, class: 'life-tick' }, bands);
      const t = el('text', { x: CX, y: CY - (r0 + r1) / 2 + 4, class: 'life-era' }, bands); t.textContent = name;
      const tk = el('text', { x: CX + 6, y: CY - r1 - 3, class: 'life-tick-label' }, bands);
      tk.textContent = b === 0 ? '今天' : b >= 1000 ? `${b / 1000} Ga` : `${b} Ma`;
    });
    el('circle', { cx: CX, cy: CY, r: R0 * 2.6, fill: 'url(#life-core)' }, bands);

    // current-time ring
    this.cursor = el('circle', { class: 'life-cursor', cx: CX, cy: CY, r: R0, fill: 'none' }, this.view);
    this.cursorLabel = el('text', { class: 'life-cursor-label', x: CX, 'text-anchor': 'middle' }, this.view);

    // nodes
    this.items = {};
    const links = el('g', { class: 'life-links' }, this.view);
    const lines = el('g', { class: 'life-lines' }, this.view);
    const labels = el('g', { class: 'life-labels' }, this.view);
    for (const n of LIFE_NODES) {
      const color = LIFE_GROUPS[n.group].color;
      const it = { n };
      if (n.parent) it.link = el('path', { class: 'life-link', stroke: color, fill: 'none' }, links);
      it.line = el('line', { class: 'life-line', stroke: color }, lines);
      it.hit = el('line', { class: 'life-hit', 'data-id': n.id }, lines);
      it.dot = el('circle', { class: 'life-dot' + (n.isInternal ? ' node' : ''), r: n.isInternal ? 2.2 : 3.4, fill: color }, labels);
      it.label = el('text', { class: 'life-label' + (n.extinct ? ' extinct' : '') + (n.isInternal ? ' clade' : ''), 'data-id': n.id }, labels);
      it.label.textContent = n.isInternal ? n.name : `${n.icon} ${n.name}`;
      this.items[n.id] = it;
    }
    this.svg.addEventListener('click', (e) => {
      const id = e.target.getAttribute && e.target.getAttribute('data-id');
      if (id) this.select(id);
    });
    this.fit();
    this.setTime(this.years);
  }

  /** place a radial text at (r, angle): reads outward on the right half, flipped on the left half */
  placeLabel(text, r, angle, inward = false) {
    const a = ((angle % 360) + 360) % 360;
    const left = a > 90 && a < 270;
    const x = px(r, angle), y = py(r, angle);
    text.setAttribute('x', fmt(x)); text.setAttribute('y', fmt(y));
    text.setAttribute('transform', `rotate(${fmt(left ? angle + 180 : angle)} ${fmt(x)} ${fmt(y)})`);
    // outward labels start at the tip; inward (clade) labels end before the node
    const anchorStart = !left !== inward;
    text.setAttribute('text-anchor', anchorStart ? 'start' : 'end');
    text.setAttribute('dy', '0.35em');
  }

  // ---------- time update
  setTime(years) {
    this.years = years;
    const tMa = years / 1e6;
    const rt = this.rOf(tMa);
    this.cursor.setAttribute('r', fmt(rt));
    this.cursorLabel.setAttribute('y', fmt(CY - rt - 10));
    this.cursorLabel.textContent = formatYears(years);
    let alive = 0, gone = 0;
    for (const n of LIFE_NODES) {
      const it = this.items[n.id];
      const exists = n.start >= tMa;               // has originated by time t
      const dead = n.extinct && n.end > tMa;       // already extinct at time t
      const show = exists;
      it.line.style.display = it.hit.style.display = it.dot.style.display = it.label.style.display = show ? '' : 'none';
      if (it.link) it.link.style.display = show ? '' : 'none';
      if (!show) continue;
      const rEnd = n.isInternal ? Math.min(n.rLast, rt) : dead ? n.rEnd : rt;
      const a = n.angle;
      const rA = n.r0, rB = Math.max(n.r0, rEnd);
      it.line.setAttribute('x1', fmt(px(rA, a))); it.line.setAttribute('y1', fmt(py(rA, a)));
      it.line.setAttribute('x2', fmt(px(rB, a))); it.line.setAttribute('y2', fmt(py(rB, a)));
      it.hit.setAttribute('x1', fmt(px(rA, a))); it.hit.setAttribute('y1', fmt(py(rA, a)));
      it.hit.setAttribute('x2', fmt(px(Math.max(rA + 6, rB), a))); it.hit.setAttribute('y2', fmt(py(Math.max(rA + 6, rB), a)));
      it.line.classList.toggle('dead', dead);
      if (n.isInternal) {
        it.dot.setAttribute('cx', fmt(px(rA, a))); it.dot.setAttribute('cy', fmt(py(rA, a)));
        this.placeLabel(it.label, rA - 6, a, true);
      } else {
        it.dot.setAttribute('cx', fmt(px(rB, a))); it.dot.setAttribute('cy', fmt(py(rB, a)));
        it.dot.classList.toggle('dead', dead);
        this.placeLabel(it.label, rB + 9, a, false);
        it.label.classList.toggle('dead', dead);
      }
      if (dead) gone++; else alive++;
      if (it.link) {
        // arc at the divergence radius from the parent's angle to this lineage's angle
        const p = LIFE_BY_ID[n.parent];
        const r = n.r0;
        const sweep = n.angle > p.angle ? 1 : 0;
        it.link.setAttribute('d', `M ${fmt(px(r, p.angle))} ${fmt(py(r, p.angle))} A ${fmt(r)} ${fmt(r)} 0 0 ${sweep} ${fmt(px(r, n.angle))} ${fmt(py(r, n.angle))}`);
      }
    }
    this.stats.innerHTML = `<b>${alive}</b> 个谱系存在 · <b>${gone}</b> 个已灭绝 · 共 ${LIFE_NODES.length} 个节点`;
    if (this.selected) this.renderCard(this.selected);
  }

  // ---------- selection card
  select(id) {
    this.selected = id;
    for (const k of Object.keys(this.items)) this.items[k].label.classList.toggle('selected', k === id);
    this.renderCard(id);
  }
  renderCard(id) {
    const n = LIFE_BY_ID[id];
    if (!n) return;
    const tMa = this.years / 1e6;
    const state = n.start < tMa ? `尚未出现（起源于 ${formatYears(n.start * 1e6)}）` : n.extinct && n.end > tMa ? `已灭绝（${formatYears(n.end * 1e6)}）` : '存在于当前时刻';
    const lineage = [];
    for (let p = n; p; p = p.parent ? LIFE_BY_ID[p.parent] : null) lineage.unshift(p.name);
    this.card.hidden = false;
    this.card.innerHTML = `
      <button class="life-card-close" aria-label="关闭">✕</button>
      <div class="eyebrow" style="color:${LIFE_GROUPS[n.group].color}">${LIFE_GROUPS[n.group].name}</div>
      <h3>${n.icon} ${n.name}</h3>
      <div class="life-latin">${n.latin}</div>
      <div class="life-time">起源约 ${formatYears(n.start * 1e6)}${n.extinct ? ` · 灭绝约 ${formatYears(n.end * 1e6)}` : ' · 现存'}</div>
      <p>${n.desc}</p>
      <div class="life-lineage">${lineage.join(' › ')}</div>
      <div class="life-state">${state}</div>
      <div class="life-card-actions"><button class="btn-jump" data-years="${n.start * 1e6}">▶ 跳到它的起源</button>${n.extinct ? `<button class="btn-jump ghost" data-years="${n.end * 1e6}">跳到灭绝</button>` : ''}</div>`;
    this.card.querySelector('.life-card-close').onclick = () => { this.card.hidden = true; this.selected = null; for (const k of Object.keys(this.items)) this.items[k].label.classList.remove('selected'); };
    this.card.querySelectorAll('.btn-jump').forEach((b) => b.addEventListener('click', () => this.onJump(parseFloat(b.dataset.years))));
  }

  // ---------- zoom & pan (viewBox based; zoom 1 = the whole circle fits)
  fit() {
    const box = this.svg.getBoundingClientRect();
    if (!box.width) return;
    this.viewW = box.width; this.viewH = box.height;
    this.minZoom = 0.9;
    if (!this.fitted) { this.zoom = 1; this.panX = 0; this.panY = 0; this.fitted = true; }
    this.applyView();
  }
  applyView() {
    const aspect = this.viewW / this.viewH;
    let vw, vh;
    if (aspect >= 1) { vh = S / this.zoom; vw = vh * aspect; } else { vw = S / this.zoom; vh = vw / aspect; }
    // pan is an offset from the centred view; keep the circle at least partly on screen
    const maxPan = S * 0.6;
    this.panX = Math.max(-maxPan, Math.min(maxPan, this.panX));
    this.panY = Math.max(-maxPan, Math.min(maxPan, this.panY));
    const x0 = CX - vw / 2 + this.panX, y0 = CY - vh / 2 + this.panY;
    this.svg.setAttribute('viewBox', `${fmt(x0)} ${fmt(y0)} ${fmt(vw)} ${fmt(vh)}`);
    this.scale = vh / this.viewH; // tree units per CSS pixel
    this.svg.style.setProperty('--life-scale', String(this.scale));
    // clade (internal) labels only become readable when zoomed in
    this.svg.classList.toggle('show-clades', this.zoom >= 1.7);
  }
  bindInteraction() {
    const svg = this.svg;
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const before = this.toTree(e.clientX - rect.left, e.clientY - rect.top);
      this.zoom = Math.min(8, Math.max(this.minZoom, this.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      this.applyView();
      const after = this.toTree(e.clientX - rect.left, e.clientY - rect.top);
      this.panX += before.x - after.x; this.panY += before.y - after.y;
      this.applyView();
    }, { passive: false });
    let drag = null;
    svg.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, px: this.panX, py: this.panY }; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener('pointermove', (e) => {
      if (!drag) return;
      this.panX = drag.px - (e.clientX - drag.x) * this.scale; this.panY = drag.py - (e.clientY - drag.y) * this.scale;
      this.applyView();
    });
    svg.addEventListener('pointerup', () => { drag = null; });
    svg.addEventListener('pointercancel', () => { drag = null; });
    svg.addEventListener('dblclick', () => { this.zoom = 1; this.panX = 0; this.panY = 0; this.applyView(); });
  }
  toTree(cssX, cssY) {
    const vb = this.svg.getAttribute('viewBox').split(' ').map(parseFloat);
    return { x: vb[0] + cssX * this.scale, y: vb[1] + cssY * this.scale };
  }

  renderLegend() {
    const lg = document.getElementById('life-legend');
    if (!lg) return;
    lg.innerHTML = Object.values(LIFE_GROUPS).map((g) => `<span><i style="background:${g.color}"></i>${g.name}</span>`).join('') + '<span><i class="dead"></i>已灭绝 †</span>';
  }

  setVisible(v) { this.root.hidden = !v; if (v) requestAnimationFrame(() => this.fit()); }
}
