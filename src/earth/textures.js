// Streaming texture loader.
//
// GitHub Pages reaches most visitors here at about 50 KB/s, so every megabyte in front of the first frame is
// twenty seconds of loading bar. Each texture therefore comes in levels: a small one that is enough for the
// opening view (the globe is ~600 px across there, so a 4K map is sampled from its 2K mip level anyway) and the
// full-size one, which arrives in the background and replaces it without a visible step. Only the first
// level of what the opening view needs is downloaded before the loader finishes.
//
// A "slot" is one texture binding (a uniform or a material map). Jobs are ordered by priority; prioritize()
// lets the app pull forward what the user is about to look at (the Moon, the satellite imagery, close-ups).
import * as THREE from 'three';

const TEX_BASE = import.meta.env.BASE_URL + 'textures/';
const BITMAP_OPTS = { imageOrientation: 'flipY', premultiplyAlpha: 'none', colorSpaceConversion: 'none' };

// Download order of everything that is not needed for the first frame (smaller = sooner). The app pulls a
// group forward when the user heads for it (Earth.hint, App.setMode).
export const PRIORITY = { realLite: 10, moonLite: 20, earthFull: 30, moonFull: 40, realFull: 50, extra: 60 };

/**
 * How much to download, from the page URL:
 *   ?lq     stay on the first-paint textures
 *   ?embed  (small iframe on the home page) full-size maps only when the user zooms in or opens the Moon
 * `eager` = fetch the full-size maps in the background without being asked.
 */
export function streamFlags() {
  const params = new URLSearchParams(location.search);
  const lq = params.has('lq'), embed = params.has('embed');
  return { lq, embed, hq: !lq && params.has('hq'), eager: !lq && !embed };
}

// createImageBitmap decodes off the main thread, so a 4K map arriving mid-session does not freeze a frame the
// way an <img> does (it is decoded synchronously inside texImage2D). The options are needed for correct data
// (no colour management on masks, rows flipped the way TextureLoader does); browsers that ignore them would
// show the planet upside down, so test once and fall back to <img> there.
let bitmapOk = null;
function canUseBitmaps() {
  if (bitmapOk) return bitmapOk;
  bitmapOk = (async () => {
    try {
      if (typeof createImageBitmap !== 'function' || typeof ImageData !== 'function') return false;
      const src = new ImageData(new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255]), 1, 2); // red over blue
      const bmp = await createImageBitmap(src, BITMAP_OPTS);
      const c = document.createElement('canvas');
      c.width = 1; c.height = 2;
      const ctx = c.getContext('2d');
      ctx.drawImage(bmp, 0, 0);
      const top = ctx.getImageData(0, 0, 1, 1).data;
      return top[2] > 200 && top[0] < 50; // flipped: blue on top
    } catch (e) { return false; }
  })();
  return bitmapOk;
}

function applyOptions(tex, { srgb = false, anisotropy = 1, mipmaps = true, repeatX = false } = {}) {
  tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  tex.wrapS = repeatX ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.anisotropy = anisotropy;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = mipmaps ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter;
  tex.generateMipmaps = mipmaps;
  return tex;
}

/** 1x1 stand-in bound until the first level of a slot arrives (never visible: the loader waits for those levels). */
export function placeholderTexture(r, g, b, opts = {}) {
  const tex = new THREE.DataTexture(new Uint8Array([r, g, b, 255]), 1, 1, THREE.RGBAFormat);
  applyOptions(tex, { ...opts, mipmaps: false, anisotropy: 1 });
  tex.needsUpdate = true;
  return tex;
}

/** A texture three.js uploads in one go on first use. Fine behind the loader; a ~0.2 s hitch (0.8 s at 8K) mid-session. */
function wholeTexture(bmp, opts) {
  const tex = new THREE.Texture(bmp);
  tex.flipY = false; // already flipped while decoding
  tex.onUpdate = () => { if (bmp.close) bmp.close(); tex.onUpdate = null; }; // the GPU has it now: free ~32 MB per 4K map
  tex.needsUpdate = true;
  return applyOptions(tex, opts);
}

// About one megapixel per frame: ~12 ms on an integrated GPU, so a map arriving mid-session costs no visible frame.
const STRIP_PIXELS = 1 << 20;

/**
 * Uploads a decoded bitmap into its own WebGL texture a strip per frame (StripUpload.step), then hands it to
 * three.js as an ExternalTexture. Same storage format, sampler state and mipmaps as three.js would have set up.
 */
class StripUpload {
  constructor(renderer, bmp, opts) {
    const gl = renderer.getContext(), state = renderer.state;
    const { srgb = false, anisotropy = 1, mipmaps = true, repeatX = false } = opts;
    this.renderer = renderer; this.bmp = bmp; this.mipmaps = mipmaps;
    this.w = bmp.width; this.h = bmp.height; this.y = 0;
    this.rows = Math.max(16, Math.floor(STRIP_PIXELS / this.w));
    const T = gl.TEXTURE_2D;
    this.glTex = gl.createTexture();
    state.bindTexture(T, this.glTex);
    gl.texStorage2D(T, mipmaps ? Math.floor(Math.log2(Math.max(this.w, this.h))) + 1 : 1, srgb ? gl.SRGB8_ALPHA8 : gl.RGBA8, this.w, this.h);
    gl.texParameteri(T, gl.TEXTURE_WRAP_S, repeatX ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(T, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(T, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(T, gl.TEXTURE_MIN_FILTER, mipmaps ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    const ext = mipmaps && anisotropy > 1 ? renderer.extensions.get('EXT_texture_filter_anisotropic') : null;
    if (ext) gl.texParameterf(T, ext.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(anisotropy, renderer.capabilities.getMaxAnisotropy()));
    const glTex = this.glTex;
    this.texture = applyOptions(new THREE.ExternalTexture(glTex), opts);
    this.texture.flipY = false;
    this.texture.userData.release = () => gl.deleteTexture(glTex); // three.js does not own an external texture
    this.done = new Promise((resolve) => { this.resolve = resolve; });
  }

  /** Upload the next strip. Returns true once the texture is complete. */
  step() {
    const gl = this.renderer.getContext(), state = this.renderer.state, T = gl.TEXTURE_2D;
    const rows = Math.min(this.rows, this.h - this.y);
    state.bindTexture(T, this.glTex);
    state.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    state.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    state.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    state.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
    state.pixelStorei(gl.UNPACK_SKIP_ROWS, this.y); // WebGL2: selects the source rows of an image as well
    gl.texSubImage2D(T, 0, 0, this.y, this.w, rows, gl.RGBA, gl.UNSIGNED_BYTE, this.bmp);
    state.pixelStorei(gl.UNPACK_SKIP_ROWS, 0);
    this.y += rows;
    if (this.y < this.h) return false;
    if (this.mipmaps) gl.generateMipmap(T);
    if (this.bmp.close) this.bmp.close();
    this.resolve(this.texture);
    return true;
  }
}

function disposeTexture(tex) {
  tex.dispose();
  if (tex.userData.release) tex.userData.release();
}

export class TextureStream {
  constructor(renderer, { concurrency = 2 } = {}) {
    this.renderer = renderer;
    this.concurrency = concurrency;
    this.slots = new Map();
    this.queue = [];      // waiting jobs
    this.active = new Set();
    this.uploads = [];    // strip uploads in progress, one strip per tick()
    this.started = false;
    this.idleWaiters = [];
    this.seq = 0;
  }

  /**
   * @param key slot name
   * @param def { group, opts, apply(tex, level), levels: [{ file, priority, hold, tag }] }
   *   levels go from smallest to largest; a held level stays out of the queue until prioritize() releases it.
   */
  add(key, def) {
    const slot = { key, group: def.group, opts: def.opts || {}, apply: def.apply, level: -1, texture: null, jobs: [] };
    def.levels.forEach((lv, level) => {
      if (!lv) return;
      const job = { slot, level, file: lv.file, priority: lv.priority ?? 50, hold: !!lv.hold, tag: lv.tag || null, seq: this.seq++, state: 'waiting', promise: null };
      slot.jobs.push(job);
      this.queue.push(job);
    });
    this.slots.set(key, slot);
    return slot;
  }

  /**
   * Download these levels now, ahead of the queue. `wanted` is a list of [slotKey, level]; a slot without that
   * level gives its nearest one. Resolves when all of them are applied; rejects if one cannot be loaded.
   */
  require(wanted, onProgress) {
    const jobs = [];
    for (const [key, level] of wanted) {
      const slot = this.slots.get(key);
      const job = slot && (slot.jobs.find((j) => j.level >= level) || slot.jobs[slot.jobs.length - 1]);
      if (job && !jobs.includes(job)) jobs.push(job);
    }
    let done = 0;
    return Promise.all(jobs.map((job) => this.run(job, true).then(() => { done++; if (onProgress) onProgress(done, jobs.length, job.file); })));
  }

  /** Begin streaming everything that is not held, most urgent first. */
  start() { this.started = true; this.pump(); }

  /** Move the waiting levels of a group that carry `tag` ('lite' | 'full' | '8k') to the front, releasing held ones. */
  prioritize(group, tag) {
    let changed = false;
    for (const job of this.queue) {
      if (job.slot.group !== group || job.tag !== tag || job.boosted) continue;
      job.boosted = true; job.priority -= 100; job.hold = false; changed = true;
    }
    if (changed) this.pump();
  }

  /** Call once per rendered frame: uploads one strip of a texture that arrived in the background. */
  tick() {
    const up = this.uploads[0];
    if (!up) return;
    let finished;
    try { finished = up.step(); } catch (e) { console.warn('strip upload failed', e); finished = true; up.resolve(null); }
    if (finished) this.uploads.shift();
  }

  /** The decoded image of a slot's current texture while it has not been uploaded yet (null afterwards). */
  sourceImage(key) {
    const tex = this.slots.get(key)?.texture;
    const image = tex && tex.image;
    return image && image.width ? { image, flipped: tex.flipY === false } : null;
  }

  /** Resolves once nothing is downloading and nothing releasable is waiting. */
  whenIdle() {
    if (this.isIdle()) return Promise.resolve();
    return new Promise((resolve) => this.idleWaiters.push(resolve));
  }

  isIdle() { return this.active.size === 0 && (!this.started || !this.queue.some((j) => !j.hold)); }

  pump() {
    if (!this.started) return;
    while (this.active.size < this.concurrency) {
      let best = null;
      for (const job of this.queue) {
        if (job.hold) continue;
        if (!best || job.priority < best.priority || (job.priority === best.priority && job.seq < best.seq)) best = job;
      }
      if (!best) break;
      this.run(best, false).catch(() => {}); // a background failure only costs sharpness and is already reported
    }
    if (this.isIdle()) { const w = this.idleWaiters; this.idleWaiters = []; w.forEach((f) => f()); }
  }

  async load(file, opts, critical) {
    let tex = null;
    if (await canUseBitmaps()) {
      const res = await fetch(TEX_BASE + file);
      if (!res.ok) throw new Error(`${file}: HTTP ${res.status}`);
      const bmp = await createImageBitmap(await res.blob(), BITMAP_OPTS);
      const size = [bmp.width, bmp.height];
      if (!critical) {
        // mid-session: spread the upload over several frames
        try {
          const up = new StripUpload(this.renderer, bmp, opts);
          this.uploads.push(up);
          tex = await up.done;
        } catch (e) { console.warn('strip upload unavailable', e); }
      }
      if (!tex) tex = wholeTexture(bmp, opts);
      tex.userData.size = size;
    } else {
      tex = applyOptions(await new THREE.TextureLoader().loadAsync(TEX_BASE + file), opts);
      tex.userData.size = [tex.image.width, tex.image.height];
    }
    tex.userData.file = file;
    return tex;
  }

  run(job, critical) {
    if (job.promise) return job.promise;
    const i = this.queue.indexOf(job);
    if (i >= 0) this.queue.splice(i, 1);
    const slot = job.slot;
    // a larger level is already showing: nothing to gain from this one
    if (slot.level > job.level) { job.state = 'skipped'; return (job.promise = Promise.resolve()); }
    job.state = 'loading';
    this.active.add(job);
    const attempt = (n) => this.load(job.file, slot.opts, critical).catch((err) => {
      if (n > 0) return new Promise((r) => setTimeout(r, 1500)).then(() => attempt(n - 1));
      throw err;
    });
    job.promise = attempt(critical ? 2 : 1).then((tex) => {
      if (slot.level > job.level) { disposeTexture(tex); job.state = 'skipped'; return; }
      const old = slot.texture;
      slot.texture = tex; slot.level = job.level;
      slot.apply(tex, job.level);
      if (old) disposeTexture(old);
      job.state = 'done';
    }, (err) => {
      job.state = 'failed';
      console.warn('texture failed', job.file, err);
      if (critical) throw err;
    }).finally(() => { this.active.delete(job); this.pump(); });
    return job.promise;
  }
}
