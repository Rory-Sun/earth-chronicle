import { App } from './app/App.js';

if (new URLSearchParams(location.search).has('embed')) document.body.classList.add('embed');
const app = new App(document.getElementById('scene'));
window.earthApp = app;
app.start().catch((err) => {
  console.error(err);
  const s = document.getElementById('loader-status');
  if (s) s.textContent = '加载失败：' + (err && err.message ? err.message : err);
});
