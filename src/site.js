// Personal site: starfield background, scroll reveal, and a data-driven product showcase with on-demand embeds.
import { PRODUCTS } from './products.js';

// ---- starfield
const canvas = document.getElementById('stars');
const ctx = canvas.getContext('2d');
let stars = [];
function resize() {
  canvas.width = window.innerWidth * Math.min(devicePixelRatio, 2);
  canvas.height = window.innerHeight * Math.min(devicePixelRatio, 2);
  const n = Math.round((canvas.width * canvas.height) / 9000);
  stars = Array.from({ length: n }, () => ({
    x: Math.random() * canvas.width, y: Math.random() * canvas.height,
    r: Math.random() * 1.4 + 0.3, a: Math.random() * Math.PI * 2, s: 0.4 + Math.random() * 1.2,
    c: Math.random() < 0.15 ? '255,214,170' : Math.random() < 0.3 ? '190,215,255' : '235,240,255',
  }));
}
resize();
window.addEventListener('resize', resize);
let t = 0;
function draw() {
  t += 0.016;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const g = ctx.createRadialGradient(canvas.width * 0.7, canvas.height * 0.2, 0, canvas.width * 0.7, canvas.height * 0.2, canvas.width * 0.8);
  g.addColorStop(0, 'rgba(30,60,120,0.35)');
  g.addColorStop(1, 'rgba(4,7,15,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const s of stars) {
    const tw = 0.55 + 0.45 * Math.sin(t * s.s + s.a);
    ctx.fillStyle = `rgba(${s.c},${(0.35 + 0.65 * tw).toFixed(2)})`;
    ctx.beginPath(); ctx.arc(s.x, s.y, s.r * (0.8 + 0.4 * tw), 0, Math.PI * 2); ctx.fill();
  }
  requestAnimationFrame(draw);
}
draw();


// ---- products (data-driven)
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function posterHTML(p) {
  if (p.poster) return `<img class="demo-poster" src="${esc(p.poster)}" alt="${esc(p.title)} 预览" />`;
  return `<div class="demo-poster placeholder" style="--accent:${esc(p.accent || '#3d8ee6')}"><span class="ph-emoji">${p.emoji || '✦'}</span><span class="ph-title">${esc(p.title)}</span></div>`;
}
function showcaseHTML(p, i) {
  const tags = (p.tags || []).map((t) => `<span class="pill">${esc(t)}</span>`).join('');
  const feats = (p.features || []).map((f) => `<li><span class="feature-icon">${f.icon || '✦'}</span><b>${esc(f.title)}</b><span>${esc(f.text)}</span></li>`).join('');
  const embedBtn = p.embed
    ? `<button class="btn primary big" data-launch="${esc(p.id)}">▶ 启动交互演示</button><div class="demo-hint">在本页内直接运行 · 建议使用桌面浏览器</div>`
    : `<a class="btn primary big" href="${esc(p.url)}" target="_blank" rel="noopener">打开项目 ↗</a>`;
  return `
  <article class="showcase reveal" id="${esc(p.id)}" style="--accent:${esc(p.accent || '#3d8ee6')}">
    <header class="showcase-head">
      <div>
        <div class="eyebrow">${String(i + 1).padStart(2, '0')} · ${esc(p.kicker || '')}</div>
        <h3>${esc(p.title)}</h3>
        ${p.subtitle ? `<div class="showcase-sub">${esc(p.subtitle)}</div>` : ''}
      </div>
      <div class="product-actions">
        <a class="btn primary" href="${esc(p.url)}" target="_blank" rel="noopener">打开完整版 ↗</a>
      </div>
    </header>
    <p class="showcase-desc">${esc(p.desc)}</p>
    <div class="demo-frame" data-frame="${esc(p.id)}">
      ${posterHTML(p)}
      <div class="demo-overlay">${embedBtn}</div>
      <a class="demo-fullscreen" href="${esc(p.url)}" target="_blank" rel="noopener" title="在新标签页打开完整版">全屏打开 ↗</a>
    </div>
    <div class="product-meta"><div class="pill-row">${tags}</div></div>
    ${feats ? `<ul class="feature-list">${feats}</ul>` : ''}
  </article>`;
}
function soonHTML(p) {
  return `<article class="card soon reveal" style="--accent:${esc(p.accent || '#3d8ee6')}"><div class="card-thumb placeholder"><span>${p.emoji || '✦'}</span></div><div class="card-body"><div class="eyebrow">${esc(p.kicker || '研发中')}</div><h3>${esc(p.title)}</h3><p>${esc(p.desc)}</p></div></article>`;
}
const live = PRODUCTS.filter((p) => p.status !== 'soon');
const soon = PRODUCTS.filter((p) => p.status === 'soon');
document.getElementById('product-list').innerHTML = live.map(showcaseHTML).join('');
document.getElementById('product-soon').innerHTML = soon.map(soonHTML).join('');
document.getElementById('product-tabs').innerHTML = live.map((p) => `<a href="#${esc(p.id)}">${esc(p.title)}</a>`).join('') + (soon.length ? `<span class="tab-soon">+ ${soon.length} 个研发中</span>` : '');

function launchDemo(id) {
  const p = PRODUCTS.find((x) => x.id === id);
  const frame = document.querySelector(`[data-frame="${id}"]`);
  if (!p || !frame || frame.classList.contains('live')) return;
  const iframe = document.createElement('iframe');
  iframe.src = p.embed;
  iframe.title = p.title;
  iframe.allow = 'fullscreen; autoplay';
  frame.appendChild(iframe);
  frame.classList.add('live');
  frame.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
document.querySelectorAll('[data-launch]').forEach((b) => b.addEventListener('click', () => launchDemo(b.dataset.launch)));
if (location.hash.startsWith('#demo-')) launchDemo(location.hash.slice(6));

// ---- scroll reveal (after products are rendered)
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
}, { threshold: 0.12 });
document.querySelectorAll('.reveal').forEach((el) => io.observe(el));
