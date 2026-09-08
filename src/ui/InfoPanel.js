import { eraAt, formatYears } from '../data/eras.js';

export class InfoPanel {
  constructor() {
    this.el = document.getElementById('info');
    this.eon = document.getElementById('info-eon');
    this.title = document.getElementById('info-title');
    this.time = document.getElementById('info-time');
    this.desc = document.getElementById('info-desc');
    this.facts = document.getElementById('info-facts');
    this.stats = document.getElementById('info-stats');
    this.currentId = null;
    this.toast = document.createElement('div');
    this.toast.id = 'toast';
    document.body.appendChild(this.toast);
    this.toastTimer = null;
  }

  showEra(yearsBP) {
    const e = eraAt(yearsBP);
    this.time.textContent = formatYears(yearsBP);
    if (e.id === this.currentId) return;
    this.currentId = e.id;
    this.render({ eon: e.eon, title: e.name, desc: e.desc, facts: e.facts, stats: e.stats });
  }

  render({ eon, title, desc, facts = [], stats = {} }) {
    this.eon.textContent = eon;
    this.title.textContent = title;
    this.desc.textContent = desc;
    this.facts.innerHTML = facts.map((f) => `<li>${f}</li>`).join('');
    this.stats.innerHTML = Object.entries(stats).map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
    this.el.classList.remove('hidden');
    this.el.style.animation = 'none';
    // restart fade animation
    void this.el.offsetWidth;
    this.el.style.animation = '';
  }

  setCustom(id, data) {
    if (id === this.currentId) { if (data.time) this.time.textContent = data.time; return; }
    this.currentId = id;
    this.render(data);
    if (data.time) this.time.textContent = data.time;
  }

  updateStats(stats) {
    const cells = this.stats.querySelectorAll('.stat');
    const entries = Object.entries(stats);
    entries.forEach(([k, v], i) => { if (cells[i]) cells[i].querySelector('.v').textContent = v; });
  }

  showToast(text) {
    this.toast.textContent = text;
    this.toast.classList.add('show');
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast.classList.remove('show'), 3200);
  }
}
