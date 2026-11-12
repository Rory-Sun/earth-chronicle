import * as THREE from 'three';

/**
 * Screen-space HTML labels attached to 3D anchor points.
 * Labels are hidden behind the body they sit on, and never overlap each other: when two collide the one
 * that was already showing (then the one facing the camera more) keeps its place and the other fades out.
 */
export class Labels {
  constructor(camera, { getCenter = null } = {}) {
    this.camera = camera;
    this.getCenter = getCenter;
    this.root = document.getElementById('labels');
    this.items = [];
    this._v = new THREE.Vector3();
    this._n = new THREE.Vector3();
    this._c = new THREE.Vector3();
    this._p = new THREE.Vector3();
  }

  clear() {
    for (const it of this.items) it.el.remove();
    this.items = [];
  }

  /** object: Object3D whose world position is used; getPos(): optional function returning a world Vector3 */
  add(text, object, { cls = '', getPos = null } = {}) {
    const el = document.createElement('div');
    el.className = 'label ' + cls;
    el.innerHTML = `<span class="dot"></span>${text}`;
    el.style.opacity = '0';
    this.root.appendChild(el);
    const item = { el, object, getPos, visible: true, text, shown: false, w: 0, h: 0, x: 0, y: 0, facing: 0, on: false };
    this.items.push(item);
    return item;
  }

  update(width, height, enabled = true) {
    const cam = this.camera;
    const candidates = [];
    for (const it of this.items) {
      it.on = false;
      if (!enabled || !it.visible || (it.object && !it.object.visible)) continue;
      const p = it.getPos ? it.getPos(this._v) : it.object.getWorldPosition(this._v);
      // occlusion by the body the label sits on: visible only if the surface point faces the camera
      const c = this.getCenter ? this.getCenter() : null;
      this._n.copy(p); if (c) this._n.sub(c); this._n.normalize();
      const facing = this._n.dot(this._c.copy(cam.position).sub(p).normalize());
      if (facing < 0.1) continue;
      const proj = this._p.copy(p).project(cam);
      if (proj.z > 1 || Math.abs(proj.x) > 1.05 || Math.abs(proj.y) > 1.05) continue;
      it.x = (proj.x * 0.5 + 0.5) * width;
      it.y = (-proj.y * 0.5 + 0.5) * height;
      it.facing = facing;
      if (!it.w) { it.w = it.el.offsetWidth; it.h = it.el.offsetHeight || 18; }
      candidates.push(it);
    }
    // greedy placement: labels already on screen keep priority (no flicker), then the ones facing us most
    candidates.sort((a, b) => (b.shown - a.shown) || (b.facing - a.facing));
    const placed = [];
    for (const it of candidates) {
      const x0 = it.x - 6, x1 = it.x + it.w + 6, y0 = it.y - it.h / 2 - 3, y1 = it.y + it.h / 2 + 3;
      let hit = false;
      for (const r of placed) { if (x0 < r[1] && x1 > r[0] && y0 < r[3] && y1 > r[2]) { hit = true; break; } }
      if (hit) continue;
      placed.push([x0, x1, y0, y1]);
      it.on = true;
    }
    for (const it of this.items) {
      if (it.on) {
        it.el.style.transform = `translate(${(it.x - 2.5).toFixed(1)}px, ${it.y.toFixed(1)}px) translateY(-50%)`;
        it.el.style.opacity = String(Math.min(1, (it.facing - 0.1) * 4));
      } else if (it.shown) it.el.style.opacity = '0';
      it.shown = it.on;
    }
  }
}
