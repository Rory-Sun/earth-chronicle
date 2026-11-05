import { startDiorama } from './Viewer.js';

const id = document.body.dataset.scene;
const el = (s) => document.querySelector(s);
let wantAuto = true;
const ui = {
  setTitle: (t) => { el('#title').textContent = t; document.title = t + ' · 微缩沙盘'; },
  status: (t) => { el('#loader-status').textContent = t; },
  progress: (f) => { el('#loader-fill').style.width = Math.round(Math.min(1, f) * 100) + '%'; },
  ready: () => { el('#loader').classList.add('hide'); setTimeout(() => el('#loader').remove(), 700); },
  autoRotateWanted: () => wantAuto,
  tier: (t) => { const b = el('#btn-quality'); if (b) b.textContent = '画质 ' + ({ high: '高', mid: '中', low: '低' }[t] || t); },
};
startDiorama(id, ui).then((app) => {
  window.__diorama = app;
  const btn = el('#btn-rotate');
  btn.addEventListener('click', () => { wantAuto = !wantAuto; app.setAutoRotate(wantAuto); btn.classList.toggle('off', !wantAuto); });
  el('#btn-quality').addEventListener('click', () => { const order = ['low', 'mid', 'high']; app.setTier(order[(order.indexOf(app.getTier()) + 1) % 3]); });
  let sky = false; const skyBtn = el('#btn-sky');
  skyBtn.addEventListener('click', () => { sky = !sky; app.setSky(sky); skyBtn.textContent = sky ? '背景 天空' : '背景 纯净'; });
  let dof = 1; const dofBtn = el('#btn-dof');
  dofBtn.addEventListener('click', () => { dof = dof === 1 ? 2 : (dof === 2 ? 0 : 1); app.setDof(dof); dofBtn.textContent = '景深 ' + ['关', '中', '强'][dof]; });
  el('#btn-full').addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen?.(); });
}).catch((e) => { console.error(e); ui.status('加载失败：' + (e.message || e)); });