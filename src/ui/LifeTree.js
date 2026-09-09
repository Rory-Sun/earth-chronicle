// 生命之树: a zoomable, time-synced phylogeny drawn in SVG. The x axis shares the deep-time timeline mapping,
// so the tree "grows" as the timeline is dragged: lineages appear when they originate, labels ride the
// time cursor, extinct branches stop with a †.
import { LIFE_NODES, LIFE_BY_ID, LIFE_GROUPS } from '../data/life.js';
import { yearsToSlider } from './Timeline.js';
import { formatYears } from '../data/eras.js';

const NS = 'http://www.w3.org/2000/svg';
const ROW = 26;          // px per leaf row (in tree units)
const PAD_L = 40, PAD_R = 230, PAD_T = 34, PAD_B = 20;
const LABEL_MAX = 0.985; // slider fraction where the "today" edge sits

function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

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

  // ---------- layout: leaves in DFS order define rows, internal y = mean of children
  layout() {
    const children = {};
    for (const n of LIFE_NODES) { children[n.id] = children[n.id] || []; if (n.parent) (children[n.parent] = children[n.parent] || []).push(n); }
    this.children = children;
    let row = 0;
    const visit = (n) => {
      const kids = children[n.id] || [];
      if (!kids.length) { n.row = row++; return; }
      // put extinct side branches first so surviving lineages run along the bottom of each clade
      for (const k of kids) visit(k);
      n.row = kids.reduce((s, k) => s + k.row, 0) / kids.length;
    };
    visit(LIFE_BY_ID.luca);
    // internal nodes: sit midway between first and last child, nudged if that lands on a descendant's row
    const fix = (n) => {
      const kids = children[n.id] || [];
      if (!kids.length) return;
      for (const k of kids) fix(k);
      let r = (kids[0].row + kids[kids.length - 1].row) / 2;
      const taken = new Set(LIFE_NODES.filter((m) => !(children[m.id] || []).length).map((m) => m.row));
      if (taken.has(r)) r += 0.5;
      n.row = r;
      n.isInternal = true;
      n.lastBranch = Math.min(...kids.map((k) => k.start)); // youngest divergence (Ma)
    };
    fix(LIFE_BY_ID.luca);
    this.rows = row;
    this.width = 1400;
    this.height = PAD_T + PAD_B + this.rows * ROW;
    for (const n of LIFE_NODES) { n.x0 = this.xOf(n.start); n.xEnd = this.xOf(n.end); n.xLast = n.isInternal ? this.xOf(n.lastBranch) : n.xEnd; n.y = PAD_T + n.row * ROW + ROW / 2; }
  }

  xOf(ma) { return PAD_L + (this.width - PAD_L - PAD_R) * Math.min(LABEL_MAX, yearsToSlider('deep', ma * 1e6)) / LABEL_MAX; }

  // ---------- build static SVG
  build() {
    const svg = this.svg;
    svg.innerHTML = '';
    svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
    const defs = el('defs', {}, svg);
    const glow = el('filter', { id: 'life-glow', x: '-50%', y: '-50%', width: '200%', height: '200%' }, defs);
    el('feGaussianBlur', { stdDeviation: 2.2, result: 'b' }, glow);
    const merge = el('feMerge', {}, glow); el('feMergeNode', { in: 'b' }, merge); el('feMergeNode', { in: 'SourceGraphic' }, merge);
    this.view = el('g', { class: 'life-view' }, svg);
    // era shading columns
    const eras = [[4540, 4000, '冥古宙'], [4000, 2500, '太古宙'], [2500, 541, '元古宙'], [541, 252, '古生代'], [252, 66, '中生代'], [66, 0, '新生代']];
    const bands = el('g', { class: 'life-bands' }, this.view);
    eras.forEach(([a, b, name], i) => {
      const x0 = this.xOf(a), x1 = this.xOf(b);
      el('rect', { x: x0, y: 0, width: x1 - x0, height: this.height, fill: i % 2 ? 'rgba(120,150,210,0.045)' : 'rgba(0,0,0,0)' }, bands);
      const t = el('text', { x: (x0 + x1) / 2, y: 18, class: 'life-era' }, bands); t.textContent = name;
    });
    // tick lines
    for (const ma of [4000, 3000, 2000, 1000, 541, 250, 66, 2.6]) {
      const x = this.xOf(ma);
      el('line', { x1: x, y1: PAD_T - 6, x2: x, y2: this.height, class: 'life-tick' }, bands);
      const t = el('text', { x: x + 3, y: this.height - 6, class: 'life-tick-label' }, bands); t.textContent = ma >= 1000 ? `${ma / 1000} Ga` : ma < 10 ? `${ma} Ma` : `${ma} Ma`;
    }
    this.cursor = el('line', { class: 'life-cursor', y1: 0, y2: this.height }, this.view);
    this.cursorLabel = el('text', { class: 'life-cursor-label', y: this.height - 6 }, this.view);
    // nodes
    this.items = {};
    const links = el('g', { class: 'life-links' }, this.view);
    const lines = el('g', { class: 'life-lines' }, this.view);
    const labels = el('g', { class: 'life-labels' }, this.view);
    for (const n of LIFE_NODES) {
      const color = LIFE_GROUPS[n.group].color;
      const it = { n };
      if (n.parent) it.link = el('path', { class: 'life-link', stroke: color }, links);
      it.line = el('line', { class: 'life-line', stroke: color, y1: n.y, y2: n.y }, lines);
      it.hit = el('line', { class: 'life-hit', y1: n.y, y2: n.y, 'data-id': n.id }, lines);
      it.dot = el('circle', { class: 'life-dot' + (n.isInternal ? ' node' : ''), r: n.isInternal ? 2.4 : 3.2, cy: n.y, fill: color }, labels);
      it.label = el('text', { class: 'life-label' + (n.extinct ? ' extinct' : '') + (n.isInternal ? ' clade' : ''), y: n.isInternal ? n.y - 6 : n.y + 4, 'data-id': n.id }, labels);
      it.label.textContent = n.isInternal ? n.name : `${n.icon} ${n.name}`;
      if (n.isInternal) { it.label.setAttribute('x', n.x0 + 5); it.dot.setAttribute('cx', n.x0); }
      this.items[n.id] = it;
    }
    this.svg.addEventListener('click', (e) => {
      const id = e.target.getAttribute && e.target.getAttribute('data-id');
      if (id) this.select(id);
    });
    this.fit();
    this.setTime(this.years);
  }

  // ---------- time update
  setTime(years) {
    this.years = years;
    const tMa = years / 1e6;
    const xt = this.xOf(tMa);
    this.cursor.setAttribute('x1', xt); this.cursor.setAttribute('x2', xt);
    this.cursorLabel.setAttribute('x', xt + 6);
    this.cursorLabel.textContent = formatYears(years);
    let alive = 0, gone = 0, born = 0;
    for (const n of LIFE_NODES) {
      const it = this.items[n.id];
      const exists = n.start >= tMa;               // has originated by time t
      const dead = n.extinct && n.end > tMa;       // already extinct at time t
      const show = exists;
      it.line.style.display = it.hit.style.display = it.dot.style.display = it.label.style.display = show ? '' : 'none';
      if (it.link) it.link.style.display = show ? '' : 'none';
      if (!show) continue;
      born++;
      const xEnd = n.isInternal ? Math.min(n.xLast, xt) : dead ? n.xEnd : xt;
      it.line.setAttribute('x1', n.x0); it.line.setAttribute('x2', Math.max(n.x0, xEnd));
      it.hit.setAttribute('x1', n.x0); it.hit.setAttribute('x2', Math.max(n.x0 + 6, xEnd));
      it.line.classList.toggle('dead', dead);
      if (!n.isInternal) {
        it.dot.setAttribute('cx', xEnd);
        it.dot.classList.toggle('dead', dead);
        it.label.setAttribute('x', xEnd + 8);
        it.label.classList.toggle('dead', dead);
      }
      if (dead) gone++; else alive++;
      if (it.link) {
        const p = LIFE_BY_ID[n.parent];
        it.link.setAttribute('d', `M ${n.x0} ${p.y} V ${n.y}`);
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

  // ---------- zoom & pan (viewBox based)
  fit() {
    const box = this.svg.getBoundingClientRect();
    if (!box.width) return;
    this.viewW = box.width; this.viewH = box.height;
    this.minZoom = 1; // zoom 1 shows the whole tree height
    const fitWidth = (this.height * (box.width / box.height)) / this.width;
    if (!this.fitted) { this.zoom = Math.max(1, Math.min(fitWidth, 2.4)); this.panX = 0; this.panY = 0; this.fitted = true; }
    this.zoom = Math.max(this.zoom, this.minZoom);
    this.applyView();
  }
  applyView() {
    // viewBox width/height in tree units; keep the aspect of the element
    const aspect = this.viewW / this.viewH;
    const vh = this.height / this.zoom;
    const vw = vh * aspect;
    const maxPanX = Math.max(0, this.width - vw), maxPanY = Math.max(0, this.height - vh);
    this.panX = Math.min(maxPanX, Math.max(Math.min(0, this.width - vw), this.panX));
    this.panY = Math.min(maxPanY, Math.max(0, this.panY));
    this.svg.setAttribute('viewBox', `${this.panX} ${this.panY} ${vw} ${vh}`);
    this.svg.style.setProperty('--life-scale', String(vh / this.viewH));
  }
  bindInteraction() {
    const svg = this.svg;
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const before = this.toTree(e.clientX - rect.left, e.clientY - rect.top);
      this.zoom = Math.min(6, Math.max(this.minZoom, this.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      this.applyView();
      const after = this.toTree(e.clientX - rect.left, e.clientY - rect.top);
      this.panX += before.x - after.x; this.panY += before.y - after.y;
      this.applyView();
    }, { passive: false });
    let drag = null;
    svg.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, px: this.panX, py: this.panY }; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const s = parseFloat(svg.style.getPropertyValue('--life-scale')) || 1;
      this.panX = drag.px - (e.clientX - drag.x) * s; this.panY = drag.py - (e.clientY - drag.y) * s;
      this.applyView();
    });
    svg.addEventListener('pointerup', () => { drag = null; });
    svg.addEventListener('pointercancel', () => { drag = null; });
    svg.addEventListener('dblclick', () => { this.zoom = this.minZoom; this.panX = 0; this.panY = 0; this.applyView(); });
  }
  toTree(px, py) {
    const s = parseFloat(this.svg.style.getPropertyValue('--life-scale')) || 1;
    return { x: this.panX + px * s, y: this.panY + py * s };
  }

  renderLegend() {
    const lg = document.getElementById('life-legend');
    if (!lg) return;
    lg.innerHTML = Object.values(LIFE_GROUPS).map((g) => `<span><i style="background:${g.color}"></i>${g.name}</span>`).join('') + '<span><i class="dead"></i>已灭绝 †</span>';
  }

  setVisible(v) { this.root.hidden = !v; if (v) requestAnimationFrame(() => this.fit()); }
}
