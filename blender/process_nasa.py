"""Convert NASA Visible Earth source imagery into web-ready WebP textures.
Run: blender --background --python blender/process_nasa.py
Inputs (public domain, NASA Visible Earth) in public/textures/nasa/:
  world.topo.bathy.200408.3x21600x10800.png  (Blue Marble NG, Aug 2004, topo+bathy)  [fallback: 5400x2700 jpg]
  BlackMarble_2016_3km.jpg                   (Black Marble 2016 night lights, 13500x6750)
  cloud_combined_8192.tif                    (Blue Marble cloud cover, 8192x4096)      [fallback: 2048 jpg]
Outputs: nasa_color_8k.webp, nasa_color_4k.webp, nasa_lights_4k.webp, nasa_clouds_4k.webp
"""
import bpy, os, sys, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'public', 'textures', 'nasa')
OUT = os.path.join(ROOT, 'public', 'textures')
t0 = time.time()
def log(*a): print(f'[nasa {time.time()-t0:6.1f}s]', *a, flush=True)

def load_scaled(path, w, h):
    """Load an image, let Blender pre-scale it to (w,h) (keeps RAM low), return HxWx3 float top-down in 0..1."""
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = 'Non-Color'  # raw bytes in, raw bytes out
    sw, sh = img.size
    log('loaded', os.path.basename(path), sw, sh)
    if sw < w * 0.9:
        raise RuntimeError(f'{path} looks truncated/too small: {sw}x{sh}')
    if (sw, sh) != (w, h):
        img.scale(w, h)
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    arr = px.reshape(h, w, 4)[::-1, :, :3].copy()
    bpy.data.images.remove(img)
    return arr

def box2(arr):
    """2x area downsample."""
    h, w = arr.shape[:2]
    return arr.reshape(h // 2, 2, w // 2, 2, -1).mean(axis=(1, 3))

def save_webp(path, arr, quality=90, srgb=True):
    h, w = arr.shape[:2]
    name = '__tmp_webp'
    if name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[name])
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=False)
    img.colorspace_settings.name = 'sRGB' if srgb else 'Non-Color'
    px = np.empty((h, w, 4), np.float32)
    px[..., :3] = np.clip(arr[::-1], 0, 1)
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
    log('wrote', os.path.basename(path), f'{os.path.getsize(path)/1e6:.1f} MB')

# ---- Blue Marble colour
try:
    color8 = load_scaled(os.path.join(SRC, 'world.topo.bathy.200408.3x21600x10800.png'), 8192, 4096)
except Exception as e:
    log('21600 source unusable:', e, '-> using 5400x2700 jpg')
    color8 = load_scaled(os.path.join(SRC, 'world.topo.bathy.200408.3x5400x2700.jpg'), 5400, 2700)
    # upsample to 8192 is pointless; only write 4K
    img = None
if color8.shape[1] == 8192:
    save_webp(os.path.join(OUT, 'nasa_color_8k.webp'), color8, 88, True)
    color4 = box2(color8)
else:
    # resample 5400 -> 4096 via Blender scale
    tmp = bpy.data.images.new('__c', 5400, 2700, alpha=False, float_buffer=False)
    tmp.colorspace_settings.name = 'Non-Color'
    px = np.empty((2700, 5400, 4), np.float32); px[..., :3] = color8[::-1]; px[..., 3] = 1
    tmp.pixels.foreach_set(px.ravel()); tmp.scale(4096, 2048)
    px = np.empty(4096 * 2048 * 4, np.float32); tmp.pixels.foreach_get(px)
    color4 = px.reshape(2048, 4096, 4)[::-1, :, :3].copy(); bpy.data.images.remove(tmp)
save_webp(os.path.join(OUT, 'nasa_color_4k.webp'), color4, 90, True)
del color8

# ---- Black Marble lights (keep colour: sodium orange vs LED white)
lights8 = load_scaled(os.path.join(SRC, 'BlackMarble_2016_3km.jpg'), 8192, 4096)
lights4 = box2(lights8)
del lights8
# lift faint lights a little so small towns survive compression
lights4 = np.clip(lights4 * 1.15, 0, 1)
save_webp(os.path.join(OUT, 'nasa_lights_4k.webp'), lights4, 85, True)

# ---- clouds
try:
    clouds8 = load_scaled(os.path.join(SRC, 'cloud_combined_8192.tif'), 8192, 4096)
    clouds4 = box2(clouds8); del clouds8
except Exception as e:
    log('8192 clouds unusable:', e, '-> using 2048 jpg')
    clouds4 = load_scaled(os.path.join(SRC, 'cloud_combined_2048.jpg'), 2048, 1024)
save_webp(os.path.join(OUT, 'nasa_clouds_4k.webp'), clouds4, 85, False)
log('done')
