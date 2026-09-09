// Personal site: starfield background, scroll reveal, and a data-driven product showcase with on-demand embeds.
import { PRODUCTS } from './products.js';

import './stars.js';

// ---- products (data-driven)
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function posterHTML(p) {
  if (p.poster) return `<img class="demo-poster" src="${esc(p.poster)}" alt="${esc(p.title)} 预览" />`;
  return `<div class="demo-poster placeholder" style="--accent:${esc(p.accent || '#3d8ee6')}"><span class="ph-emoji">${p.emoji || '✦'}</span><span class="ph-title">${esc(p.title)}</span></div>`;
}
function showcaseHTML(p, i) {
  const tags = (p.tags || []).map((t) => `<span class="pill">${esc(t)}</span>`).join('');
  const feats = (p.features || []).map((f) => `<li><span class="feature-icon">${f.icon || '✦'}</span><b>${esc(f.title)}</b><span>${esc(f.text)}</span></li>`).join('');
  // a url starting with '#' is a placeholder: the project is not published yet
  const placeholder = !p.url || p.url.startsWith('#');
  const embedBtn = p.embed
    ? `<button class="btn primary big" data-launch="${esc(p.id)}">▶ 启动交互演示</button><div class="demo-hint">在本页内直接运行 · 建议使用桌面浏览器</div>`
    : placeholder
      ? `<span class="btn ghost big disabled">在线演示即将上线</span><div class="demo-hint">项目已完成，正在准备公网部署</div>`
      : `<a class="btn primary big" href="${esc(p.url)}" target="_blank" rel="noopener">打开项目 ↗</a>`;
  const openLink = placeholder ? '' : `<a class="btn primary" href="${esc(p.url)}" target="_blank" rel="noopener">打开完整版 ↗</a>`;
  const fullLink = placeholder ? '' : `<a class="demo-fullscreen" href="${esc(p.url)}" target="_blank" rel="noopener" title="在新标签页打开完整版">全屏打开 ↗</a>`;
  return `
  <article class="showcase reveal" id="${esc(p.id)}" style="--accent:${esc(p.accent || '#3d8ee6')}">
    <header class="showcase-head">
      <div>
        <div class="eyebrow">${String(i + 1).padStart(2, '0')} · ${esc(p.kicker || '')}</div>
        <h3>${esc(p.title)}</h3>
        ${p.subtitle ? `<div class="showcase-sub">${esc(p.subtitle)}</div>` : ''}
      </div>
      <div class="product-actions">${openLink}</div>
    </header>
    <p class="showcase-desc">${esc(p.desc)}</p>
    <div class="demo-frame" data-frame="${esc(p.id)}">
      ${posterHTML(p)}
      <div class="demo-overlay">${embedBtn}</div>
      ${fullLink}
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
