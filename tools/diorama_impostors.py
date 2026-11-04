# -*- coding: utf-8 -*-
"""
把 Poly Haven 树木/灌木模型渲染成网页用的"卡片树"贴图（impostor）：每个变体一张正视图（512×1024）
和一张俯视图（512×512），带透明通道，均匀天光下渲染（光照留给网页里的实时灯光）。

用法：blender --background --python tools/diorama_impostors.py -- [--out public/dioramas/trees] [--samples 32]
输出：<out>/<kind>_<i>_front.png、<out>/<kind>_<i>_top.png、<out>/trees.json
"""
import bpy, os, sys, json, math

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    return argv[argv.index(name) + 1] if name in argv else default
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
MODELS = os.path.join(ROOT, "assets", "polyhaven", "models")
OUT = os.path.abspath(arg("--out", os.path.join(ROOT, "public", "dioramas", "trees")))
SAMPLES = int(arg("--samples", 32))
os.makedirs(OUT, exist_ok=True)

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
    """与 build_west_lake.py 里 tint_leaf_material 相同的思路：贴图颜色与明亮绿色混合 + alpha 镂空。"""
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
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0

def render(path, loc, rot, ortho, rx, ry):
    scene = bpy.context.scene
    cam = bpy.data.objects.get("ImpCam")
    if cam is None:
        cd = bpy.data.cameras.new("ImpCam"); cd.type = 'ORTHO'
        cam = bpy.data.objects.new("ImpCam", cd); scene.collection.objects.link(cam)
        scene.camera = cam
    cam.data.ortho_scale = ortho
    cam.data.clip_end = 100
    cam.location = loc
    cam.rotation_euler = rot
    scene.render.resolution_x, scene.render.resolution_y = rx, ry
    scene.render.resolution_percentage = 100
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)

meta = {}
for (kind, idx, file, obname) in VARIANTS:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world()
    path = os.path.join(MODELS, file, file + ".blend")
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [obname]
    ob = dst.objects[0]
    bpy.context.scene.collection.objects.link(ob)
    for m in ob.data.materials:
        if m and is_leaf_mat(m.name):
            rebuild_leaf(m)
    xs = [v.co.x for v in ob.data.vertices]; ys = [v.co.y for v in ob.data.vertices]; zs = [v.co.z for v in ob.data.vertices]
    h = max(zs) - min(zs)
    k = 1.0 / h
    ob.scale = (k, k, k)
    ob.location = (-(max(xs) + min(xs)) / 2 * k, -(max(ys) + min(ys)) / 2 * k, -min(zs) * k)
    wx, wy = (max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k
    width = max(wx, wy)
    key = f"{kind}_{idx}"
    # 正视图：从 -y 看向 +y，画幅高 1.05，宽按比例（输出 512×1024，ortho_scale 作用于长边＝高）
    front_h = 1.05
    front_w = front_h / 2
    if width > front_w:
        front_h = width * 2 * 1.02
        front_w = front_h / 2
    render(os.path.join(OUT, key + "_front.png"), (0, -20, 0.5), (math.radians(90), 0, 0), front_h, 512, 1024)
    # 俯视图
    top_s = width * 1.05
    render(os.path.join(OUT, key + "_top.png"), (0, 0, 20), (0, 0, 0), top_s, 512, 512)
    meta[key] = {"kind": kind, "idx": idx, "src": file + "/" + obname, "front_h": round(front_h, 4), "front_w": round(front_w, 4),
                 "top": round(top_s, 4), "width": round(width, 4)}
    print(f"[imp] {key}: width={width:.2f} front_h={front_h:.2f} top={top_s:.2f}")
with open(os.path.join(OUT, "trees.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print("[imp] done:", list(meta.keys()))