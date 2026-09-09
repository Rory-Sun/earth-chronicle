import * as THREE from 'three';

/** Screen-space HTML labels attached to 3D anchor points (hidden when behind the globe). */
export class Labels {
  constructor(camera, { getCenter = null, radius = 1 } = {}) {
    this.camera = camera;
    this.getCenter = getCenter;
    this.root = document.getElementById('labels');
    this.items = [];
    this._v = new THREE.Vector3();
    this._n = new THREE.Vector3();
  }

  clear() {
    for (const it of this.items) it.el.remove();
    this.items = [];
  }

  /** anchor: Object3D whose world position is used; getPos(): optional function returning world Vector3 */
  add(text, object, { cls = '', getPos = null, minAge = 0 } = {}) {
    const el = document.createElement('div');
    el.className = 'label ' + cls;
    el.innerHTML = `<span class="dot"></span>${text}`;
    el.style.opacity = '0';
    this.root.appendChild(el);
    const item = { el, object, getPos, visible: true, text };
    this.items.push(item);
    return item;
  }

  update(width, height, enabled = true) {
    const cam = this.camera;
    for (const it of this.items) {
      if (!enabled || !it.visible || (it.object && !it.object.visible)) { it.el.style.opacity = '0'; continue; }
      const p = it.getPos ? it.getPos(this._v) : it.object.getWorldPosition(this._v);
      // occlusion by the body the label sits on: visible if the surface point faces the camera
      const c = this.getCenter ? this.getCenter() : null;
      this._n.copy(p); if (c) this._n.sub(c); this._n.normalize();
      const toCam = cam.position.clone().sub(p).normalize();
      const facing = this._n.dot(toCam);
      if (facing < 0.08) { it.el.style.opacity = '0'; continue; }
      const proj = p.clone().project(cam);
      if (proj.z > 1) { it.el.style.opacity = '0'; continue; }
      const x = (proj.x * 0.5 + 0.5) * width, y = (-proj.y * 0.5 + 0.5) * height;
      it.el.style.transform = `translate(${x.toFixed(1)}px, ${(y - 14).toFixed(1)}px) translate(-50%, -50%)`;
      it.el.style.opacity = String(Math.min(1, (facing - 0.08) * 4));
    }
  }
}
