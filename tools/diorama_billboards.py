# -*- coding: utf-8 -*-
"""
把 Poly Haven 树木/灌木模型渲染成网页用的"多角度公告牌"图集：每个变体 8 个方位 × 2 个俯仰角共 16 张小图，
拼成 4×4 的图集（带透明通道，均匀天光下渲染，光照留给网页里的实时灯光）。网页里每棵树是一张始终朝向镜头的面片，
按镜头相对树的方位和俯仰选图，并在相邻角度之间过渡——转动视角时不会像交叉卡片那样露出"十字板"。

用法：blender --background --python tools/diorama_billboards.py -- [--out public/dioramas/trees] [--samples 24] [--only tree_0,pine_1]
输出：<out>/<kind>_<i>_bb.png（之后用 tools/optimize_web_assets.py 转 WebP），并在 <out>/trees.json 的每个变体里写入 bb 字段。

约定：模型归一化为高 1、底面在 z = 0、水平居中。第 k 个方位的相机位于 (sin az·cos el, −cos az·cos el, sin el)，az = k·45°；
图集里第 t = ring·8 + k 张小图位于第 t % 4 列、第 t // 4 行（行从图片底部数起，与贴图 UV 一致）。
"""
import bpy, os, sys, json, math, tempfile
import numpy as np
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
MODELS = os.path.join(ROOT, "assets", "polyhaven", "models")
OUT = os.path.abspath(arg("--out", os.path.join(ROOT, "public", "dioramas", "trees")))
SAMPLES = int(arg("--samples", 24))
ONLY = set(arg("--only", "").split(",")) - {""}
TMP = tempfile.mkdtemp(prefix="bb_tiles_")
RINGS = (15.0, 55.0)      # 两个俯仰角（度）
NAZ = 8

VARIANTS = [
    ("tree", 0, "island_tree_01", "island_tree_01_LOD1"),
    ("tree", 1, "island_tree_02", "island_tree_02_LOD1"),
    ("tree", 2, "island_tree_03", "island_tree_03_LOD1"),
    ("willow", 0, "tree_small_02", "tree_small_02_LOD1"),
    ("pine", 0, "fir_sapling_medium", "fir_sapling_medium_a_LOD1"),
    ("pine", 1, "fir_sapling_medium", "fir_sapling_medium_b_LOD1"),
    ("pine", 2, "fir_sapling_medium", "fir_sapling_medium_c_LOD1"),
    ("bush", 0, "shrub_01", "shrub_01_a_LOD1"),
    ("bush", 1, "shrub_01", "shrub_01_b_LOD1"),
    ("bush", 2, "shrub_03", "shrub_03_a_LOD1"),
    ("bush", 3, "shrub_03", "shrub_03_b_LOD1"),
]

def is_leaf_mat(name):
    n = name.lower()
    return ('leaves' in n or 'twigs' in n or 'shrub' in n
            or ('branches' in n and ('island_tree' in n or 'tree_small' in n)))

def rebuild_leaf(mat):
    """与 diorama_impostors.py 相同：贴图颜色与明亮绿色混合 + alpha 镂空。"""
    nt = mat.node_tree
    imgs = [n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image]
    diff = next((n for n in imgs if 'diff' in n.image.name.lower()), None)
    alpha = next((n for n in imgs if 'alpha' in n.image.name.lower() or 'mask' in n.image.name.lower()), None)
    if diff is None:
        return
    diff.image.colorspace_settings.name = 'sRGB'
    if alpha is not None:
        alpha.image.colorspace_settings.name = 'Non-Color'
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
        or next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None) or nt.nodes.new("ShaderNodeOutputMaterial")
    for l in [l for l in nt.links if l.to_node == out]:
        nt.links.remove(l)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    p.inputs["Roughness"].default_value = 0.8
    if "Specular IOR Level" in p.inputs:
        p.inputs["Specular IOR Level"].default_value = 0.2
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = 'RGBA'; mix.blend_type = 'MIX'
    if 'fir' in mat.name or 'twigs' in mat.name:
        green, fac = (0.30, 0.60, 0.20), 0.65
    elif 'tree_small' in mat.name:
        green, fac = (0.44, 0.62, 0.22), 0.55
    else:
        green, fac = (0.27, 0.54, 0.19), 0.55
    mix.inputs["Factor"].default_value = fac
    mix.inputs[7].default_value = (*green, 1)
    nt.links.new(diff.outputs["Color"], mix.inputs[6])
    nt.links.new(mix.outputs[2], p.inputs["Base Color"])
    nt.links.new(alpha.outputs["Color"] if alpha is not None else diff.outputs["Alpha"], p.inputs["Alpha"])
    nt.links.new(p.outputs["BSDF"], out.inputs["Surface"])

def setup_world():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("W"); scene.world = world; world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (1, 1, 1, 1)
    bg.inputs["Strength"].default_value = 1.0
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.transparent_max_bounces = 48
    scene.render.film_transparent = True
    scene.render.use_persistent_data = True          # 同一棵树连渲 16 张，保留加速结构
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0

meta_path = os.path.join(OUT, "trees.json")
meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
for (kind, idx, file, obname) in VARIANTS:
    key = f"{kind}_{idx}"
    if ONLY and key not in ONLY:
        continue
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world()
    scene = bpy.context.scene
    path = os.path.join(MODELS, file, file + ".blend")
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [obname]
    ob = dst.objects[0]
    scene.collection.objects.link(ob)
    for m in ob.data.materials:
        if m and is_leaf_mat(m.name):
            rebuild_leaf(m)
    xs = [v.co.x for v in ob.data.vertices]; ys = [v.co.y for v in ob.data.vertices]; zs = [v.co.z for v in ob.data.vertices]
    k = 1.0 / (max(zs) - min(zs))
    ob.scale = (k, k, k)
    ob.location = (-(max(xs) + min(xs)) / 2 * k, -(max(ys) + min(ys)) / 2 * k, -min(zs) * k)
    width = max((max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k)
    # 面片边长：能装下任一视角下的投影（高 1、宽 width 的包围柱）
    size = 1.04 * max(width, *(math.cos(math.radians(e)) + width * math.sin(math.radians(e)) for e in RINGS))
    tile = 96 if kind == "bush" else 192
    cd = bpy.data.cameras.new("BBCam"); cd.type = 'ORTHO'; cd.ortho_scale = size; cd.clip_end = 100
    cam = bpy.data.objects.new("BBCam", cd); scene.collection.objects.link(cam); scene.camera = cam
    scene.render.resolution_x = scene.render.resolution_y = tile
    scene.render.resolution_percentage = 100
    centre = mathutils.Vector((0.0, 0.0, 0.5))
    atlas = np.zeros((tile * 4, tile * 4, 4), np.float32)
    for r, el in enumerate(RINGS):
        for a in range(NAZ):
            az, e = math.radians(a * 360.0 / NAZ), math.radians(el)
            d = mathutils.Vector((math.sin(az) * math.cos(e), -math.cos(az) * math.cos(e), math.sin(e)))
            cam.location = centre + d * 20.0
            cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
            fp = os.path.join(TMP, f"{key}_{r}_{a}.png")
            scene.render.filepath = fp
            bpy.ops.render.render(write_still=True)
            im = bpy.data.images.load(fp)
            px = np.array(im.pixels[:], dtype=np.float32).reshape(tile, tile, 4)
            bpy.data.images.remove(im)
            t = r * NAZ + a
            col, row = t % 4, t // 4
            atlas[row * tile:(row + 1) * tile, col * tile:(col + 1) * tile] = px
    out_im = bpy.data.images.new(key + "_bb", tile * 4, tile * 4, alpha=True)
    out_im.pixels = atlas.ravel().tolist()
    out_im.filepath_raw = os.path.join(OUT, key + "_bb.png")
    out_im.file_format = 'PNG'
    out_im.save()
    meta.setdefault(key, {"kind": kind, "idx": idx, "src": file + "/" + obname})
    meta[key]["bb"] = {"tile": tile, "size": round(size, 4), "cz": 0.5, "rings": list(RINGS), "naz": NAZ}
    print(f"[bb] {key}: width={width:.2f} size={size:.2f} tile={tile}")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
print("[bb] done")
