"""
Earth Chronicle - Blender modelling & texture bake pipeline.

Run (headless):
  blender --background --python blender/build_earth.py -- [--quick] [--skip-render] [--res 8192] [--only albedo,clouds]

What it does
  1. Builds a procedural Earth material (Cycles nodes) driven by hint maps made by tools/build-data.mjs
     (coastline mask, relief, aridity, moisture, ice, shelves, city lights).
  2. Bakes a complete texture set (albedo, height, normal, masks, night lights, clouds) via a UV bake plane.
  3. Models the Moon procedurally (maria + multi-scale craters) and bakes its textures.
  4. Assembles a real 3D scene (Earth with displacement, clouds, atmosphere, Moon, Sun, camera, stars),
     saves blender/output/earth_chronicle.blend, exports public/models/earth.glb + moon.glb, renders previews.
"""
import bpy
import os
import sys
import math
import time
import struct
import zlib
import numpy as np
from mathutils import Vector

# ------------------------------------------------------------------------------------------------ setup
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR = os.path.join(ROOT, 'blender', 'input')
OUT_DIR = os.path.join(ROOT, 'blender', 'output')
PREVIEW_DIR = os.path.join(OUT_DIR, 'preview')
TEX_DIR = os.path.join(ROOT, 'public', 'textures')
MODEL_DIR = os.path.join(ROOT, 'public', 'models')
RENDER_DIR = os.path.join(ROOT, 'blender', 'renders')
for d in (OUT_DIR, PREVIEW_DIR, TEX_DIR, MODEL_DIR, RENDER_DIR):
    os.makedirs(d, exist_ok=True)

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
QUICK = '--quick' in argv
SKIP_RENDER = '--skip-render' in argv


def arg_str(name, default):
    if name in argv:
        return argv[argv.index(name) + 1]
    return default


RES = int(arg_str('--res', 2048 if QUICK else 8192))   # master resolution (albedo / height / normal)
RES_MID = min(RES, 4096)                                # masks, lights, clouds
MOON_RES = 1024 if QUICK else 2048
BAKE_SAMPLES = 1 if QUICK else 2
ONLY = [s for s in arg_str('--only', '').split(',') if s]
T0 = time.time()


def log(*a):
    print(f'[earth {time.time() - T0:7.1f}s]', *a, flush=True)


# ------------------------------------------------------------------------------------------------ PNG writer (no color management surprises)
def write_png(path, arr):
    """arr: uint8/uint16 array HxW (gray) or HxWxC (C=1..4), top-down rows."""
    if arr.ndim == 2:
        arr = arr[:, :, None]
    h, w, c = arr.shape
    bitdepth = 16 if arr.dtype == np.uint16 else 8
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    data = arr.astype('>u2' if bitdepth == 16 else np.uint8).tobytes()
    row_bytes = w * c * (bitdepth // 8)
    raw = bytearray()
    for y in range(h):
        raw += b'\x00' + data[y * row_bytes:(y + 1) * row_bytes]

    def chunk(tag, payload):
        return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, bitdepth, ctype, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def to_u8(arr):
    return np.clip(np.round(arr * 255), 0, 255).astype(np.uint8)


def save_webp(path, arr_float, quality=90, srgb=True):
    """arr_float: HxWx3 float (0..1), top-down. Uses a byte image so no view transform is applied."""
    h, w = arr_float.shape[:2]
    name = '__tmp_webp'
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=False)
    img.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
    px = np.empty((h, w, 4), np.float32)
    px[..., :3] = np.clip(arr_float[::-1], 0, 1)
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.file_format = 'WEBP'
    img.filepath_raw = path
    try:
        img.save(filepath=path, quality=quality)
    except TypeError:
        bpy.context.scene.render.image_settings.quality = quality
        img.save()
    bpy.data.images.remove(img)


def linear_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def downscale(arr, factor):
    """Box downscale HxW(xC) by integer factor."""
    factor = int(factor)
    if factor <= 1:
        return arr
    h, w = arr.shape[:2]
    h2, w2 = h // factor, w // factor
    a = arr[:h2 * factor, :w2 * factor]
    if arr.ndim == 2:
        return a.reshape(h2, factor, w2, factor).mean(axis=(1, 3))
    return a.reshape(h2, factor, w2, factor, arr.shape[2]).mean(axis=(1, 3))


def gray3(a):
    return np.repeat(a[..., None], 3, axis=2)


# ------------------------------------------------------------------------------------------------ node builder
class NB:
    def __init__(self, tree):
        self.t = tree
        self.count = 0

    def node(self, typ, **props):
        nd = self.t.nodes.new(typ)
        for k, v in props.items():
            setattr(nd, k, v)
        self.count += 1
        nd.location = ((self.count % 40) * 220, -(self.count // 40) * 300)
        return nd

    def link(self, src, dst):
        if isinstance(src, bpy.types.NodeSocket):
            self.t.links.new(src, dst)
        else:
            dst.default_value = src

    def math(self, op, a, b=None, c=None, clamp=False):
        nd = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        self.link(a, nd.inputs[0])
        if b is not None:
            self.link(b, nd.inputs[1])
        if c is not None:
            self.link(c, nd.inputs[2])
        return nd.outputs[0]

    def add(self, a, b): return self.math('ADD', a, b)
    def sub(self, a, b): return self.math('SUBTRACT', a, b)
    def mul(self, a, b): return self.math('MULTIPLY', a, b)
    def div(self, a, b): return self.math('DIVIDE', a, b)
    def mad(self, a, b, c): return self.math('MULTIPLY_ADD', a, b, c)
    def pow(self, a, b): return self.math('POWER', a, b)
    def sqrt(self, a): return self.math('SQRT', a)
    def absf(self, a): return self.math('ABSOLUTE', a)
    def maxf(self, a, b): return self.math('MAXIMUM', a, b)
    def minf(self, a, b): return self.math('MINIMUM', a, b)
    def gt(self, a, b): return self.math('GREATER_THAN', a, b)
    def sin(self, a): return self.math('SINE', a)
    def cos(self, a): return self.math('COSINE', a)
    def clamp01(self, a): return self.math('ADD', a, 0.0, clamp=True)

    def clamp(self, a, lo, hi):
        nd = self.node('ShaderNodeClamp')
        self.link(a, nd.inputs['Value']); self.link(lo, nd.inputs['Min']); self.link(hi, nd.inputs['Max'])
        return nd.outputs[0]

    def smoothstep(self, x, e0, e1):
        nd = self.node('ShaderNodeMapRange', interpolation_type='SMOOTHSTEP', clamp=True)
        self.link(x, nd.inputs['Value']); self.link(e0, nd.inputs['From Min']); self.link(e1, nd.inputs['From Max'])
        nd.inputs['To Min'].default_value = 0.0; nd.inputs['To Max'].default_value = 1.0
        return nd.outputs['Result']

    def mixf(self, a, b, t):
        nd = self.node('ShaderNodeMix', data_type='FLOAT', clamp_factor=True)
        self.link(t, nd.inputs[0]); self.link(a, nd.inputs[2]); self.link(b, nd.inputs[3])
        return nd.outputs[0]

    def mixc(self, a, b, t):
        nd = self.node('ShaderNodeMix', data_type='RGBA', clamp_factor=True)
        self.link(t, nd.inputs[0])
        for val, sock in ((a, nd.inputs[6]), (b, nd.inputs[7])):
            if isinstance(val, bpy.types.NodeSocket):
                self.t.links.new(val, sock)
            else:
                sock.default_value = (*val, 1.0) if len(val) == 3 else val
        return nd.outputs[2]

    def ramp(self, x, stops, interp='LINEAR'):
        """stops: list of (pos, value) where value is float or (r,g,b)."""
        nd = self.node('ShaderNodeValToRGB')
        cr = nd.color_ramp
        cr.interpolation = interp
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, val) in zip(cr.elements, stops):
            el.position = pos
            if isinstance(val, (int, float)):
                el.color = (val, val, val, 1.0)
            else:
                el.color = (*val, 1.0)
        self.link(x, nd.inputs['Fac'])
        return nd.outputs['Color']

    def rampf(self, x, stops, interp='LINEAR'):
        return self.sep(self.ramp(x, stops, interp))[0]

    def noise(self, vec, scale, detail=4.0, rough=0.5, lac=2.0, dist=0.0, ntype='FBM'):
        nd = self.node('ShaderNodeTexNoise')
        nd.noise_dimensions = '3D'
        try:
            nd.noise_type = ntype
        except Exception:
            pass
        try:
            nd.normalize = True
        except Exception:
            pass
        self.t.links.new(vec, nd.inputs['Vector'])
        for name, val in (('Scale', scale), ('Detail', detail), ('Roughness', rough), ('Lacunarity', lac), ('Distortion', dist)):
            if name in nd.inputs:
                nd.inputs[name].default_value = val
        return nd.outputs['Fac'], nd.outputs['Color']

    def voronoi(self, vec, scale, feature='F1', randomness=1.0):
        nd = self.node('ShaderNodeTexVoronoi')
        nd.voronoi_dimensions = '3D'
        nd.feature = feature
        nd.distance = 'EUCLIDEAN'
        self.t.links.new(vec, nd.inputs['Vector'])
        nd.inputs['Scale'].default_value = scale
        nd.inputs['Randomness'].default_value = randomness
        return nd

    def image(self, img, vec, interp='Linear'):
        nd = self.node('ShaderNodeTexImage', interpolation=interp, extension='REPEAT')
        nd.image = img
        self.t.links.new(vec, nd.inputs['Vector'])
        return nd.outputs['Color'], nd.outputs['Alpha']

    def sep(self, color):
        nd = self.node('ShaderNodeSeparateColor')
        self.link(color, nd.inputs['Color'])
        return nd.outputs['Red'], nd.outputs['Green'], nd.outputs['Blue']

    def comb(self, r, g, b):
        nd = self.node('ShaderNodeCombineColor')
        self.link(r, nd.inputs['Red']); self.link(g, nd.inputs['Green']); self.link(b, nd.inputs['Blue'])
        return nd.outputs['Color']

    def xyz(self, x, y, z):
        nd = self.node('ShaderNodeCombineXYZ')
        self.link(x, nd.inputs['X']); self.link(y, nd.inputs['Y']); self.link(z, nd.inputs['Z'])
        return nd.outputs['Vector']

    def sepxyz(self, v):
        nd = self.node('ShaderNodeSeparateXYZ')
        self.link(v, nd.inputs['Vector'])
        return nd.outputs['X'], nd.outputs['Y'], nd.outputs['Z']

    def vmath(self, op, a, b=None, scale=None):
        nd = self.node('ShaderNodeVectorMath', operation=op)
        self.link(a, nd.inputs[0])
        if b is not None:
            self.link(b, nd.inputs[1])
        if scale is not None:
            self.link(scale, nd.inputs['Scale'])
        return nd.outputs[0]

    def vscale(self, v, s): return self.vmath('SCALE', v, scale=s)
    def vadd(self, a, b): return self.vmath('ADD', a, b)

    def scale_color(self, color, k):
        """color * k (k float socket or number) via Mix multiply."""
        nd = self.node('ShaderNodeMix', data_type='RGBA', blend_type='MULTIPLY', clamp_factor=True)
        nd.inputs[0].default_value = 1.0
        self.link(color, nd.inputs[6])
        if isinstance(k, bpy.types.NodeSocket):
            self.t.links.new(self.comb(k, k, k), nd.inputs[7])
        else:
            nd.inputs[7].default_value = (k, k, k, 1.0)
        return nd.outputs[2]


def load_image(fname, colorspace='Non-Color'):
    img = bpy.data.images.load(os.path.join(IN_DIR, fname), check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


# ------------------------------------------------------------------------------------------------ sphere coordinates from UV (seamless bake domain)
def sphere_from_uv(nb, uv):
    u, v, _ = nb.sepxyz(uv)
    lon = nb.mul(nb.sub(u, 0.5), 2 * math.pi)     # -pi..pi, 0 at Greenwich (+X)
    lat = nb.mul(nb.sub(v, 0.5), math.pi)         # -pi/2..pi/2
    cl = nb.cos(lat)
    P = nb.xyz(nb.mul(cl, nb.cos(lon)), nb.mul(cl, nb.sin(lon)), nb.sin(lat))
    lat_deg = nb.mul(lat, 180 / math.pi)
    return P, lat_deg, lon


# ------------------------------------------------------------------------------------------------ EARTH generator
def build_earth_generator(nb, uv):
    P, lat_deg, lon = sphere_from_uv(nb, uv)
    abs_lat = nb.absf(lat_deg)

    img_land = load_image('landmask.png')
    img_geo = load_image('geo.png')
    img_blur = load_image('landblur.png')
    img_wide = load_image('landblur_wide.png')
    img_shelf = load_image('shelf.png')
    img_lights = load_image('lights.png')

    land = nb.sep(nb.image(img_land, uv, 'Linear')[0])[0]
    geo_c = nb.image(img_geo, uv, 'Cubic')
    relief, arid_hint, moist = nb.sep(geo_c[0])
    ice_hint = geo_c[1]
    lblur = nb.sep(nb.image(img_blur, uv, 'Cubic')[0])[0]
    lwide = nb.sep(nb.image(img_wide, uv, 'Cubic')[0])[0]
    shelf_hint = nb.sep(nb.image(img_shelf, uv, 'Cubic')[0])[0]
    lights_hint = nb.sep(nb.image(img_lights, uv, 'Cubic')[0])[0]

    # ---- terrain noise fields (3D, seamless) ----
    n_cont, _ = nb.noise(P, 3.0, 8, 0.55)                       # continental undulation
    n_hills, _ = nb.noise(P, 11.0, 7, 0.52)                     # hills
    n_ridge, _ = nb.noise(P, 16.0, 8, 0.62, 2.2, ntype='RIDGED_MULTIFRACTAL')
    n_ridge2, _ = nb.noise(P, 55.0, 6, 0.58, 2.1, ntype='RIDGED_MULTIFRACTAL')
    n_fine, _ = nb.noise(P, 180.0, 4, 0.5)
    n_var, _ = nb.noise(P, 6.0, 5, 0.5)
    n_var2, _ = nb.noise(P, 21.0, 4, 0.5)
    n_ocean, _ = nb.noise(P, 4.0, 6, 0.5)

    # ---- noise-broken aridity (hides the elliptical hint shapes) ----
    arid = nb.clamp01(nb.add(nb.mul(arid_hint, nb.add(0.55, nb.mul(n_var2, 0.9))), nb.mul(nb.sqrt(arid_hint), nb.mul(nb.sub(n_hills, 0.5), 0.5))))

    # ---- land height (km) ----
    ridged = nb.add(nb.mul(n_ridge, 0.6), nb.mul(n_ridge2, 0.4))
    relief_shaped = nb.pow(nb.maxf(relief, 0.0), 1.15)
    mountains = nb.mul(relief_shaped, nb.add(2.6, nb.mul(ridged, 6.2)))         # up to ~8.8 km
    plains = nb.add(0.02, nb.add(nb.mul(n_hills, 0.30), nb.mul(n_cont, 0.22)))  # 0.02..0.54 km
    plains = nb.add(plains, nb.mul(n_fine, 0.05))
    coast_taper = nb.add(0.35, nb.mul(0.65, nb.smoothstep(lblur, 0.05, 0.7)))
    ice_dome = nb.mul(ice_hint, nb.add(1.0, nb.mul(lwide, 1.6)))
    h_land = nb.add(nb.mul(nb.add(plains, mountains), coast_taper), ice_dome)

    # ---- ocean depth (km, negative) ----
    coastal = nb.smoothstep(lblur, 0.25, 0.85)
    shelf_strength = nb.clamp01(nb.add(shelf_hint, nb.mul(coastal, 0.8)))
    deep = nb.add(3.6, nb.mul(n_ocean, 1.6))
    n_shelf, _ = nb.noise(P, 30.0, 4, 0.5)
    shallow = nb.add(nb.add(0.015, nb.mul(0.09, nb.sub(1.0, coastal))), nb.mul(n_shelf, 0.05))
    depth = nb.mixf(deep, shallow, nb.smoothstep(shelf_strength, 0.0, 0.9))
    h_ocean = nb.mul(depth, -1.0)

    h_km = nb.mixf(h_ocean, h_land, land)

    # encoded height for web: e = 0.5 + 0.5*sign(h)*sqrt(min(|h|/9,1))
    sgn = nb.sub(nb.mul(nb.gt(h_km, 0.0), 2.0), 1.0)
    mag = nb.sqrt(nb.minf(nb.div(nb.absf(h_km), 9.0), 1.0))
    h_enc = nb.add(0.5, nb.mul(0.5, nb.mul(sgn, mag)))
    # visible-surface height (ocean flat at 0) for displacement / normals: max(h,0)/9
    h_surf = nb.div(nb.maxf(h_km, 0.0), 9.0)

    # ---- climate ----
    lat01 = nb.div(abs_lat, 90.0)
    temp = nb.clamp(nb.sub(nb.sub(1.12, nb.mul(lat01, 1.25)), nb.mul(nb.maxf(h_land, 0.0), 0.11)), 0.0, 1.0)
    base_moist = nb.rampf(lat01, [(0.0, 0.82), (0.12, 0.72), (0.24, 0.30), (0.34, 0.34), (0.5, 0.62), (0.68, 0.58), (0.85, 0.42), (1.0, 0.3)])
    moisture = nb.add(base_moist, nb.mul(moist, 0.55))
    moisture = nb.sub(moisture, nb.mul(arid, 0.95))
    moisture = nb.add(moisture, nb.mul(nb.sub(n_var, 0.5), 0.22))
    moisture = nb.add(moisture, nb.mul(nb.sub(1.0, lblur), 0.12))
    moisture = nb.clamp01(moisture)

    # ---- biome colours (linear albedo) ----
    dry_col = nb.ramp(temp, [(0.0, (0.34, 0.31, 0.27)), (0.35, (0.44, 0.39, 0.28)), (0.6, (0.52, 0.45, 0.28)), (1.0, (0.64, 0.52, 0.33))])
    wet_col = nb.ramp(temp, [(0.0, (0.26, 0.27, 0.20)), (0.3, (0.09, 0.15, 0.09)), (0.6, (0.10, 0.19, 0.07)), (1.0, (0.05, 0.13, 0.045))])
    veg = nb.smoothstep(moisture, 0.18, 0.72)
    biome = nb.mixc(dry_col, wet_col, veg)
    # desert sand & dunes
    dunes, _ = nb.noise(P, 90.0, 5, 0.6, 2.0, ntype='RIDGED_MULTIFRACTAL')
    sand = nb.ramp(nb.add(nb.mul(n_var, 0.6), nb.mul(dunes, 0.4)), [(0.0, (0.60, 0.46, 0.28)), (0.5, (0.72, 0.58, 0.38)), (1.0, (0.82, 0.70, 0.50))])
    sandiness = nb.mul(nb.smoothstep(arid, 0.5, 0.95), nb.smoothstep(temp, 0.4, 0.8))
    biome = nb.mixc(biome, sand, sandiness)
    # variation
    variation = nb.add(0.80, nb.mul(0.40, nb.add(nb.mul(n_hills, 0.5), nb.mul(n_fine, 0.5))))
    biome = nb.scale_color(biome, variation)
    # rock at altitude
    rock = nb.ramp(n_fine, [(0.0, (0.30, 0.27, 0.25)), (1.0, (0.46, 0.42, 0.38))])
    rockiness = nb.smoothstep(h_land, 1.3, 3.6)
    biome = nb.mixc(biome, rock, nb.mul(rockiness, 0.85))
    # snow line & ice sheets
    snowline = nb.sub(5.4, nb.mul(nb.pow(lat01, 1.4), 5.0))
    snow = nb.smoothstep(h_land, nb.sub(snowline, 0.5), nb.add(snowline, 0.4))
    polar_ice = nb.smoothstep(nb.add(abs_lat, nb.mul(nb.sub(n_var, 0.5), 6.0)), 70.0, 82.0)
    ice = nb.maxf(nb.maxf(snow, ice_hint), nb.mul(polar_ice, nb.smoothstep(land, 0.3, 0.9)))
    ice_col = nb.ramp(n_hills, [(0.0, (0.80, 0.83, 0.88)), (1.0, (0.93, 0.95, 0.98))])
    land_col = nb.mixc(biome, ice_col, ice)

    # ---- ocean colour ----
    deep_col = (0.010, 0.036, 0.11)
    shelf_col = (0.022, 0.10, 0.20)
    shelf_vis = nb.clamp01(nb.add(nb.mul(coastal, 0.55), nb.mul(nb.smoothstep(shelf_hint, 0.15, 0.9), 0.32)))
    ocean_col = nb.mixc(deep_col, shelf_col, shelf_vis)
    # sea ice near the poles with a noisy edge
    lat_jit = nb.add(abs_lat, nb.mul(nb.sub(n_var, 0.5), 7.0))
    sea_ice_n = nb.smoothstep(lat_jit, 79.0, 86.0)
    sea_ice_s = nb.mul(nb.smoothstep(nb.mul(nb.add(lat_deg, nb.mul(nb.sub(n_var, 0.5), 7.0)), -1.0), 67.0, 74.0), 1.0)
    sea_ice_all = nb.mul(nb.maxf(sea_ice_n, sea_ice_s), nb.sub(1.0, land))
    ocean_col = nb.mixc(ocean_col, (0.86, 0.90, 0.95), nb.mul(sea_ice_all, 0.9))

    albedo = nb.mixc(ocean_col, land_col, land)

    # ---- masks ----
    veg_amount = nb.mul(nb.mul(veg, land), nb.sub(1.0, ice))
    masks_a = nb.comb(land, veg_amount, nb.mul(arid, land))
    roughness = nb.mixf(nb.mixf(0.12, 0.42, sea_ice_all), nb.mixf(0.9, 0.55, ice), land)
    masks_b = nb.comb(nb.maxf(nb.mul(ice, land), sea_ice_all), shelf_strength, roughness)

    # ---- night lights ----
    n_city, _ = nb.noise(P, 420.0, 3, 0.55)
    lights = nb.mul(nb.mul(lights_hint, nb.add(0.5, nb.mul(n_city, 0.7))), land)

    # ---- clouds ----
    _, warp_c = nb.noise(P, 2.0, 3, 0.5)
    warp = nb.vscale(nb.vmath('SUBTRACT', warp_c, (0.5, 0.5, 0.5)), 0.9)
    Pw = nb.vadd(P, warp)
    c_base, _ = nb.noise(Pw, 4.5, 8, 0.60)
    c_mid, _ = nb.noise(P, 11.0, 6, 0.55)
    c_hi, _ = nb.noise(P, 30.0, 4, 0.5)
    field = nb.add(nb.add(nb.mul(c_base, 0.66), nb.mul(c_mid, 0.24)), nb.mul(c_hi, 0.10))
    cover = nb.rampf(lat01, [(0.0, 0.70), (0.09, 0.62), (0.24, 0.28), (0.33, 0.32), (0.5, 0.58), (0.62, 0.68), (0.78, 0.60), (1.0, 0.50)])
    cover = nb.mul(cover, nb.sub(1.0, nb.mul(arid, 0.6)))
    thr = nb.sub(0.585, nb.mul(cover, 0.25))
    clouds = nb.smoothstep(field, thr, nb.add(thr, 0.22))
    # wispy high clouds add-in
    wisps = nb.mul(nb.smoothstep(c_hi, 0.66, 0.85), 0.35)
    clouds = nb.clamp01(nb.add(clouds, nb.mul(wisps, nb.smoothstep(field, nb.sub(thr, 0.08), thr))))

    return {
        'albedo': albedo, 'height_enc': h_enc, 'height_surf': h_surf,
        'masks_a': masks_a, 'masks_b': masks_b, 'lights': lights, 'clouds': clouds,
    }


# ------------------------------------------------------------------------------------------------ MOON generator
def build_moon_generator(nb, uv):
    P, lat_deg, lon = sphere_from_uv(nb, uv)
    n_mare, _ = nb.noise(P, 1.6, 5, 0.55)
    n_fine, _ = nb.noise(P, 40.0, 6, 0.55)
    n_var, _ = nb.noise(P, 8.0, 4, 0.5)
    mare = nb.smoothstep(n_mare, 0.50, 0.60)
    # maria mostly on the near side (+X faces Earth in the web scene)
    px, py, pz = nb.sepxyz(P)
    near = nb.smoothstep(px, -0.2, 0.6)
    mare = nb.mul(mare, near)

    height = nb.mul(nb.sub(n_var, 0.5), 0.15)
    height = nb.sub(height, nb.mul(mare, 0.35))
    bright = nb.add(0.0, 0.0)
    for scale, depth, keep in ((5.0, 0.55, 0.55), (11.0, 0.35, 0.5), (26.0, 0.2, 0.45), (60.0, 0.09, 0.4), (150.0, 0.04, 0.35)):
        vo = nb.voronoi(P, scale)
        d = vo.outputs['Distance']
        rnd = nb.sep(vo.outputs['Color'])[0]
        exists = nb.gt(rnd, 1.0 - keep)
        # fewer craters on the (younger) maria for the small scales
        if scale >= 26.0:
            exists = nb.mul(exists, nb.sub(1.0, nb.mul(mare, 0.6)))
        radius = nb.add(0.30, nb.mul(nb.sep(vo.outputs['Color'])[1], 0.22))
        bowl = nb.sub(1.0, nb.smoothstep(d, 0.0, radius))
        rim = nb.mul(nb.smoothstep(d, nb.mul(radius, 0.75), radius), nb.sub(1.0, nb.smoothstep(d, radius, nb.mul(radius, 1.35))))
        crater = nb.mul(exists, nb.add(nb.mul(bowl, -depth), nb.mul(rim, depth * 0.55)))
        height = nb.add(height, crater)
        bright = nb.add(bright, nb.mul(exists, nb.mul(rim, depth * 0.8)))
    height = nb.add(height, nb.mul(nb.sub(n_fine, 0.5), 0.05))

    highland = nb.ramp(n_fine, [(0.0, (0.40, 0.39, 0.37)), (1.0, (0.55, 0.54, 0.51))])
    mare_col = nb.ramp(n_var, [(0.0, (0.16, 0.16, 0.17)), (1.0, (0.24, 0.24, 0.24))])
    col = nb.mixc(highland, mare_col, mare)
    col = nb.mixc(col, (0.68, 0.67, 0.64), nb.clamp01(bright))
    col = nb.scale_color(col, nb.add(0.85, nb.mul(n_var, 0.3)))
    h01 = nb.clamp01(nb.add(0.5, height))
    return {'albedo': col, 'height': h01}


# ------------------------------------------------------------------------------------------------ bake plane + baking
def make_bake_plane(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name='UVMap')
    for loop, (u, v) in zip(mesh.loops, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        uv.data[loop.index].uv = (u, v)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    mat = bpy.data.materials.new(name + 'Mat')
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    obj.data.materials.append(mat)
    return obj, mat


def prepare_bake_material(mat, generator_fn):
    tree = mat.node_tree
    nb = NB(tree)
    out = nb.node('ShaderNodeOutputMaterial', name='Material Output')
    emit = nb.node('ShaderNodeEmission', name='BakeEmit')
    emit.inputs['Strength'].default_value = 1.0
    tree.links.new(emit.outputs[0], out.inputs['Surface'])
    nb.node('ShaderNodeTexImage', name='BakeTarget')
    texco = nb.node('ShaderNodeTexCoord')
    return generator_fn(nb, texco.outputs['UV'])


def bake_emit(plane, mat, socket, w, h, label):
    scene = bpy.context.scene
    tree = mat.node_tree
    emit = tree.nodes['BakeEmit']
    for l in list(emit.inputs['Color'].links):
        tree.links.remove(l)
    tree.links.new(socket, emit.inputs['Color'])
    img = bpy.data.images.new('__bake_' + label, w, h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    target = tree.nodes['BakeTarget']
    target.image = img
    tree.nodes.active = target
    for o in scene.objects:
        o.select_set(False)
    plane.select_set(True)
    bpy.context.view_layer.objects.active = plane
    t = time.time()
    bpy.ops.object.bake(type='EMIT', margin=0, use_clear=True, target='IMAGE_TEXTURES')
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape(h, w, 4)[::-1, :, :3].copy()  # top-down, RGB
    bpy.data.images.remove(img)
    log(f'baked {label} {w}x{h} in {time.time() - t:.1f}s')
    return arr


def height_to_normal(h_km, radius_km, strength):
    """h_km: HxW height in km (top-down). Returns HxWx3 float normal (tangent space, +X east, +Y north)."""
    H, W = h_km.shape
    lat = np.linspace(90 - 90 / H, -90 + 90 / H, H)
    dx = (2 * np.pi * radius_km / W) * np.maximum(np.cos(np.radians(lat)), 0.03)
    dy = np.pi * radius_km / H
    dhdx = (np.roll(h_km, -1, axis=1) - np.roll(h_km, 1, axis=1)) / (2 * dx[:, None])
    dhdy = (np.roll(h_km, 1, axis=0) - np.roll(h_km, -1, axis=0)) / (2 * dy)
    nx = -dhdx * strength
    ny = -dhdy * strength
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    n = np.stack([nx * inv, ny * inv, inv], axis=-1)
    return n * 0.5 + 0.5


# ------------------------------------------------------------------------------------------------ sphere mesh with clean equirectangular UVs
def make_sphere(name, segments, rings, radius):
    verts = [(0.0, 0.0, radius)]
    for i in range(1, rings):
        lat = math.pi / 2 - math.pi * i / rings
        cl = math.cos(lat)
        for j in range(segments):
            lon = -math.pi + 2 * math.pi * j / segments
            verts.append((radius * cl * math.cos(lon), radius * cl * math.sin(lon), radius * math.sin(lat)))
    verts.append((0.0, 0.0, -radius))
    south = len(verts) - 1
    faces = []
    uvs = []

    def ring_index(i, j):
        return 1 + (i - 1) * segments + (j % segments)

    def uv_of(i, j):
        return (j / segments, 1.0 - i / rings)
    for j in range(segments):
        faces.append((0, ring_index(1, j), ring_index(1, j + 1)))
        uvs.append(((j + 0.5) / segments, 1.0, *uv_of(1, j), *uv_of(1, j + 1)))
    for i in range(1, rings - 1):
        for j in range(segments):
            faces.append((ring_index(i, j), ring_index(i + 1, j), ring_index(i + 1, j + 1), ring_index(i, j + 1)))
            uvs.append((*uv_of(i, j), *uv_of(i + 1, j), *uv_of(i + 1, j + 1), *uv_of(i, j + 1)))
    for j in range(segments):
        faces.append((ring_index(rings - 1, j), south, ring_index(rings - 1, j + 1)))
        uvs.append((*uv_of(rings - 1, j), (j + 0.5) / segments, 0.0, *uv_of(rings - 1, j + 1)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    uv_layer = mesh.uv_layers.new(name='UVMap')
    li = 0
    for f, fuv in zip(mesh.polygons, uvs):
        n = len(f.vertices)
        us = [fuv[2 * k] for k in range(n)]
        if max(us) - min(us) > 0.5:  # seam face: wrap
            us = [u + 1.0 if u < 0.5 else u for u in us]
        for k in range(n):
            uv_layer.data[li].uv = (us[k], fuv[2 * k + 1])
            li += 1
    mesh.shade_smooth()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def img_from_array(name, arr_float_rgb, srgb):
    h, w = arr_float_rgb.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=False)
    img.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
    px = np.empty((h, w, 4), np.float32)
    px[..., :3] = np.clip(arr_float_rgb[::-1], 0, 1)
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


def img_from_gray16(name, arr01):
    h, w = arr01.shape
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    px = np.empty((h, w, 4), np.float32)
    px[..., 0] = px[..., 1] = px[..., 2] = np.clip(arr01[::-1], 0, 1)
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


def look_at(obj, target=(0, 0, 0)):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


# ================================================================================================ MAIN
def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = BAKE_SAMPLES
    scene.cycles.use_denoising = False
    scene.render.bake.use_clear = True
    scene.render.bake.margin = 0
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    log(f'Blender {bpy.app.version_string}  RES={RES}  QUICK={QUICK}  ONLY={ONLY}')

    plane, mat = make_bake_plane('EarthBake')
    outs = prepare_bake_material(mat, build_earth_generator)

    # -------------------------------------------------------------- quick look mode: bake selected maps, save previews, exit
    if ONLY:
        for name in ONLY:
            if name in ('moon_albedo', 'moon_height'):
                mplane, mmat = make_bake_plane('MoonBake')
                mouts = prepare_bake_material(mmat, build_moon_generator)
                arr = bake_emit(mplane, mmat, mouts[name.split('_')[1]], RES, RES // 2, name)
            else:
                arr = bake_emit(plane, mat, outs[name], RES, RES // 2, name)
            if name in ('albedo', 'moon_albedo'):
                arr = linear_to_srgb(arr)
            prev = downscale(arr, max(1, RES // 2048))
            write_png(os.path.join(PREVIEW_DIR, f'only_{name}.png'), to_u8(prev))
            log('preview ->', os.path.join(PREVIEW_DIR, f'only_{name}.png'))
        log('ONLY DONE')
        return

    # -------------------------------------------------------------- Earth bakes
    albedo = bake_emit(plane, mat, outs['albedo'], RES, RES // 2, 'earth_albedo')
    if RES >= 8192:
        save_webp(os.path.join(TEX_DIR, 'earth_color_8k.webp'), linear_to_srgb(albedo), 90, srgb=True)
        save_webp(os.path.join(TEX_DIR, 'earth_color.webp'), linear_to_srgb(downscale(albedo, 2)), 92, srgb=True)
    else:
        save_webp(os.path.join(TEX_DIR, 'earth_color.webp'), linear_to_srgb(albedo), 92, srgb=True)
    write_png(os.path.join(PREVIEW_DIR, 'earth_color.png'), to_u8(linear_to_srgb(downscale(albedo, max(1, RES // 2048)))))
    albedo_2k = downscale(albedo, RES // 2048)
    del albedo

    surf = bake_emit(plane, mat, outs['height_surf'], RES, RES // 2, 'earth_height_surf')[..., 0]
    write_png(os.path.join(OUT_DIR, 'earth_height16.png'), np.clip(surf * 65535, 0, 65535).astype(np.uint16))
    normal = height_to_normal(surf * 9.0, 6371.0, 22.0)  # exaggerated relief for legibility at globe scale
    if RES >= 8192:
        save_webp(os.path.join(TEX_DIR, 'earth_normal_8k.webp'), normal, 94, srgb=False)
        save_webp(os.path.join(TEX_DIR, 'earth_normal.webp'), downscale(normal, 2), 95, srgb=False)
    else:
        save_webp(os.path.join(TEX_DIR, 'earth_normal.webp'), normal, 95, srgb=False)
    write_png(os.path.join(PREVIEW_DIR, 'earth_normal.png'), to_u8(downscale(normal, max(1, RES // 2048))))
    normal_2k = downscale(normal, RES // 2048)
    surf_4k = downscale(surf, RES // 4096) if RES > 4096 else surf
    del normal, surf

    henc = bake_emit(plane, mat, outs['height_enc'], RES, RES // 2, 'earth_height_enc')[..., 0]
    henc_web = downscale(henc, RES // 4096) if RES > 4096 else henc
    write_png(os.path.join(TEX_DIR, 'earth_height.png'), to_u8(henc_web))
    del henc, henc_web

    masks_a = bake_emit(plane, mat, outs['masks_a'], RES_MID, RES_MID // 2, 'earth_masks_a')
    masks_b = bake_emit(plane, mat, outs['masks_b'], RES_MID, RES_MID // 2, 'earth_masks_b')
    write_png(os.path.join(TEX_DIR, 'earth_masks_a.png'), to_u8(masks_a))
    write_png(os.path.join(TEX_DIR, 'earth_masks_b.png'), to_u8(masks_b))
    rough_2k = downscale(masks_b[..., 2], RES_MID // 2048)
    del masks_a, masks_b

    lights = bake_emit(plane, mat, outs['lights'], RES_MID, RES_MID // 2, 'earth_lights')[..., 0]
    save_webp(os.path.join(TEX_DIR, 'earth_lights.webp'), gray3(lights), 88, srgb=False)
    lights_2k = downscale(lights, RES_MID // 2048)
    del lights

    clouds = bake_emit(plane, mat, outs['clouds'], RES_MID, RES_MID // 2, 'earth_clouds')[..., 0]
    save_webp(os.path.join(TEX_DIR, 'earth_clouds.webp'), gray3(clouds), 88, srgb=False)
    write_png(os.path.join(PREVIEW_DIR, 'earth_clouds.png'), to_u8(downscale(clouds, max(1, RES_MID // 2048))))
    clouds_2k = downscale(clouds, RES_MID // 2048)
    del clouds

    # -------------------------------------------------------------- Moon bakes
    mplane, mmat = make_bake_plane('MoonBake')
    mouts = prepare_bake_material(mmat, build_moon_generator)
    moon_alb = bake_emit(mplane, mmat, mouts['albedo'], MOON_RES, MOON_RES // 2, 'moon_albedo')
    moon_h = bake_emit(mplane, mmat, mouts['height'], MOON_RES, MOON_RES // 2, 'moon_height')[..., 0]
    moon_normal = height_to_normal((moon_h - 0.5) * 12.0, 1737.0, 6.0)
    save_webp(os.path.join(TEX_DIR, 'moon_color.webp'), linear_to_srgb(moon_alb), 90, srgb=True)
    save_webp(os.path.join(TEX_DIR, 'moon_normal.webp'), moon_normal, 92, srgb=False)
    write_png(os.path.join(PREVIEW_DIR, 'moon_color.png'), to_u8(linear_to_srgb(downscale(moon_alb, max(1, MOON_RES // 1024)))))

    for o in (plane, mplane):
        bpy.data.objects.remove(o, do_unlink=True)

    # -------------------------------------------------------------- Scene assembly
    log('assembling scene')
    earth = make_sphere('Earth', 720 if not QUICK else 256, 360 if not QUICK else 128, 1.0)
    img_col = img_from_array('EarthColor2K', linear_to_srgb(albedo_2k), True)
    img_nrm = img_from_array('EarthNormal2K', normal_2k, False)
    img_rgh = img_from_array('EarthRough2K', gray3(rough_2k), False)
    img_lig = img_from_array('EarthLights2K', gray3(lights_2k), False)
    img_h16 = img_from_gray16('EarthHeight16', surf_4k)

    emat = bpy.data.materials.new('EarthSurface')
    emat.use_nodes = True
    tree = emat.node_tree
    tree.nodes.clear()
    nb = NB(tree)
    out = nb.node('ShaderNodeOutputMaterial')
    bsdf = nb.node('ShaderNodeBsdfPrincipled')
    tree.links.new(bsdf.outputs[0], out.inputs['Surface'])
    tc = nb.node('ShaderNodeTexCoord')
    c_col, _ = nb.image(img_col, tc.outputs['UV'], 'Linear')
    tree.links.new(c_col, bsdf.inputs['Base Color'])
    c_rgh, _ = nb.image(img_rgh, tc.outputs['UV'], 'Linear')
    tree.links.new(c_rgh, bsdf.inputs['Roughness'])
    c_nrm, _ = nb.image(img_nrm, tc.outputs['UV'], 'Linear')
    nmap = nb.node('ShaderNodeNormalMap')
    nmap.inputs['Strength'].default_value = 1.0
    tree.links.new(c_nrm, nmap.inputs['Color'])
    tree.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    c_lig, _ = nb.image(img_lig, tc.outputs['UV'], 'Linear')
    tree.links.new(c_lig, bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 0.35
    earth.data.materials.append(emat)

    # displacement from baked surface height (real relief in the Blender scene / exported mesh)
    htex = bpy.data.textures.new('EarthHeightTex', 'IMAGE')
    htex.image = img_h16
    disp = earth.modifiers.new('Relief', 'DISPLACE')
    disp.texture = htex
    disp.texture_coords = 'UV'
    disp.mid_level = 0.0
    disp.strength = 0.012          # 9 km full range -> ~8.5x exaggeration

    # clouds (preview only)
    clouds_obj = make_sphere('Clouds', 256, 128, 1.012)
    img_cld = img_from_array('EarthClouds2K', gray3(clouds_2k), False)
    cmat = bpy.data.materials.new('Clouds')
    cmat.use_nodes = True
    ct = cmat.node_tree
    ct.nodes.clear()
    nbc = NB(ct)
    cout = nbc.node('ShaderNodeOutputMaterial')
    mix = nbc.node('ShaderNodeMixShader')
    transp = nbc.node('ShaderNodeBsdfTransparent')
    diff = nbc.node('ShaderNodeBsdfDiffuse')
    diff.inputs['Color'].default_value = (0.95, 0.95, 0.97, 1)
    ctc = nbc.node('ShaderNodeTexCoord')
    cc, _ = nbc.image(img_cld, ctc.outputs['UV'], 'Linear')
    ct.links.new(nbc.sep(cc)[0], mix.inputs['Fac'])
    ct.links.new(transp.outputs[0], mix.inputs[1])
    ct.links.new(diff.outputs[0], mix.inputs[2])
    ct.links.new(mix.outputs[0], cout.inputs['Surface'])
    try:
        cmat.surface_render_method = 'BLENDED'
    except Exception:
        pass
    clouds_obj.data.materials.append(cmat)

    # atmosphere shell (preview only)
    atmo = make_sphere('Atmosphere', 128, 64, 1.035)
    amat = bpy.data.materials.new('Atmosphere')
    amat.use_nodes = True
    at = amat.node_tree
    at.nodes.clear()
    nba = NB(at)
    aout = nba.node('ShaderNodeOutputMaterial')
    amix = nba.node('ShaderNodeMixShader')
    atr = nba.node('ShaderNodeBsdfTransparent')
    aem = nba.node('ShaderNodeEmission')
    aem.inputs['Color'].default_value = (0.35, 0.6, 1.0, 1)
    aem.inputs['Strength'].default_value = 2.5
    lw = nba.node('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.35
    fac = nba.pow(lw.outputs['Facing'], 3.0)
    at.links.new(fac, amix.inputs['Fac'])
    at.links.new(atr.outputs[0], amix.inputs[1])
    at.links.new(aem.outputs[0], amix.inputs[2])
    at.links.new(amix.outputs[0], aout.inputs['Surface'])
    try:
        amat.surface_render_method = 'BLENDED'
    except Exception:
        pass
    atmo.data.materials.append(amat)
    amat.use_backface_culling = True

    # Moon
    moon = make_sphere('Moon', 256, 128, 0.2727)
    moon.location = (0.0, -6.5, 1.2)
    img_mcol = img_from_array('MoonColor', linear_to_srgb(moon_alb), True)
    img_mnrm = img_from_array('MoonNormal', moon_normal, False)
    mmat2 = bpy.data.materials.new('MoonSurface')
    mmat2.use_nodes = True
    mt = mmat2.node_tree
    mt.nodes.clear()
    nbm = NB(mt)
    mout = nbm.node('ShaderNodeOutputMaterial')
    mbsdf = nbm.node('ShaderNodeBsdfPrincipled')
    mbsdf.inputs['Roughness'].default_value = 0.95
    mt.links.new(mbsdf.outputs[0], mout.inputs['Surface'])
    mtc = nbm.node('ShaderNodeTexCoord')
    mc, _ = nbm.image(img_mcol, mtc.outputs['UV'])
    mt.links.new(mc, mbsdf.inputs['Base Color'])
    mn, _ = nbm.image(img_mnrm, mtc.outputs['UV'])
    mnmap = nbm.node('ShaderNodeNormalMap')
    mt.links.new(mn, mnmap.inputs['Color'])
    mt.links.new(mnmap.outputs['Normal'], mbsdf.inputs['Normal'])
    moon.data.materials.append(mmat2)

    # Sun
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 4.0
    sun_data.angle = math.radians(0.53)
    sun = bpy.data.objects.new('Sun', sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(62), math.radians(-18), math.radians(35))

    # Camera
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens = 55
    cam = bpy.data.objects.new('Camera', cam_data)
    scene.collection.objects.link(cam)
    cam.location = (3.3, -2.6, 1.4)
    look_at(cam)
    scene.camera = cam

    # World: near-black with faint stars
    world = bpy.data.worlds.new('Space')
    scene.world = world
    world.use_nodes = True
    wt = world.node_tree
    wt.nodes.clear()
    nbw = NB(wt)
    wout = nbw.node('ShaderNodeOutputWorld')
    bg = nbw.node('ShaderNodeBackground')
    wtc = nbw.node('ShaderNodeTexCoord')
    starn, _ = nbw.noise(wtc.outputs['Generated'], 900.0, 1, 0.5)
    stars = nbw.mul(nbw.pow(starn, 60.0), 40.0)
    starcol = nbw.comb(stars, stars, nbw.mul(stars, 1.15))
    wt.links.new(starcol, bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
    wt.links.new(bg.outputs[0], wout.inputs['Surface'])

    # -------------------------------------------------------------- exports
    blend_path = os.path.join(OUT_DIR, 'earth_chronicle.blend')
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    log('saved', blend_path)

    def export_glb(objs, path):
        for o in scene.objects:
            o.select_set(False)
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        kwargs = dict(filepath=path, export_format='GLB', use_selection=True, export_apply=True,
                      export_yup=True, export_normals=True, export_texcoords=True, export_materials='EXPORT')
        try:
            bpy.ops.export_scene.gltf(**kwargs, export_image_format='WEBP', export_image_quality=85)
        except TypeError:
            bpy.ops.export_scene.gltf(**kwargs)
        log('exported', path, f'{os.path.getsize(path) / 1e6:.1f} MB')

    moon_loc = tuple(moon.location)
    moon.location = (0, 0, 0)
    export_glb([earth], os.path.join(MODEL_DIR, 'earth.glb'))
    export_glb([moon], os.path.join(MODEL_DIR, 'moon.glb'))
    moon.location = moon_loc

    # -------------------------------------------------------------- preview render
    if not SKIP_RENDER:
        scene.render.resolution_x = 1600
        scene.render.resolution_y = 900
        scene.render.resolution_percentage = 100
        scene.cycles.samples = 24 if QUICK else 64
        scene.cycles.use_denoising = True
        scene.view_settings.view_transform = 'AgX'
        scene.view_settings.look = 'AgX - Medium High Contrast'
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = os.path.join(RENDER_DIR, 'earth_preview.png')
        t = time.time()
        bpy.ops.render.render(write_still=True)
        log(f'rendered preview in {time.time() - t:.1f}s ->', scene.render.filepath)
        sun.rotation_euler = (math.radians(62), math.radians(-18), math.radians(215))
        cam.location = (2.4, -1.6, 0.9)
        look_at(cam)
        scene.render.filepath = os.path.join(RENDER_DIR, 'earth_night.png')
        bpy.ops.render.render(write_still=True)
        log('rendered night preview')
    log('ALL DONE')


main()
