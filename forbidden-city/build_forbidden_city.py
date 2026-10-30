# -*- coding: utf-8 -*-
"""
故宫微缩立体模型（沙盘）— 过程化生成 + Cycles 渲染（Blender 5.x, headless）

用法：
  "D:/install/blender/blender.exe" --background --python forbidden-city/build_forbidden_city.py -- \
      [--pct 100] [--samples 128] [--out forbidden-city/output/forbidden_city/forbidden_city.png] [--save]

单位：1 个 Blender 单位 ≈ 10 米。y 轴正方向为北（中轴线），x 轴正方向为东。
"""
import bpy, math, random, sys, time, os
import mathutils

# ----------------------------------------------------------------------------- 参数
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def arg(name, default):
    if name in argv:
        return argv[argv.index(name) + 1]
    return default
PCT = int(arg("--pct", 100))
SAMPLES = int(arg("--samples", 128))
HERE = os.path.dirname(os.path.abspath(__file__))
TEX_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "textures_cc0"))   # ambientCG CC0 贴图（各沙盘共用），见该目录 README.md
OUT = os.path.abspath(arg("--out", os.path.join(HERE, "output", "forbidden_city", "forbidden_city.png")))
SAVE_BLEND = "--save" in argv
random.seed(11)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = bpy.data.collections.new("ForbiddenCity")
scene.collection.children.link(COL)

# ----------------------------------------------------------------------------- 材质
def principled(name, color, rough=0.6, metal=0.0, coat=0.0, spec=0.5, bevel=0.035):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = coat
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    if bevel > 0:
        bv = m.node_tree.nodes.new("ShaderNodeBevel")
        bv.name = "EdgeBevel"
        bv.samples = 4
        bv.inputs["Radius"].default_value = bevel
        m.node_tree.links.new(bv.outputs["Normal"], bsdf.inputs["Normal"])
    return m

import glob as _glob

def tex_image(folder, kind, noncolor=True):
    """加载 textures_cc0/<folder>/*_<kind>.jpg。"""
    path = _glob.glob(os.path.join(TEX_DIR, folder, f"*_{kind}.jpg"))[0]
    im = bpy.data.images.load(path, check_existing=True)
    if noncolor:
        im.colorspace_settings.name = 'Non-Color'
    return im

def tex_node(nt, folder, kind, scale, coord, noncolor=True, box=True):
    """图像纹理节点：coord 为 'Object'（盒式投影）或 'UV'。"""
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = tex_image(folder, kind, noncolor)
    t.projection = 'BOX' if (box and coord == 'Object') else 'FLAT'
    t.projection_blend = 0.3
    tc = nt.nodes.get("TexCoordShared") or nt.nodes.new("ShaderNodeTexCoord")
    tc.name = "TexCoordShared"
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs[coord], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    return t

def tex_bump(nt, disp_node, strength, distance):
    """位移贴图 -> Bump（串联 Bevel 法线）-> BSDF Normal。"""
    pbs = nt.nodes["Principled BSDF"]
    bn = nt.nodes.new("ShaderNodeBump")
    bn.inputs["Strength"].default_value = strength
    bn.inputs["Distance"].default_value = distance
    nt.links.new(disp_node.outputs["Color"], bn.inputs["Height"])
    if base_normal(nt):
        nt.links.new(base_normal(nt), bn.inputs["Normal"])
    nt.links.new(bn.outputs["Normal"], pbs.inputs["Normal"])
    return bn

def map_range(nt, socket, lo, hi):
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = lo
    mr.inputs["To Max"].default_value = hi
    nt.links.new(socket, mr.inputs["Value"])
    return mr.outputs["Result"]

def mul_color(nt, a, b, fac=1.0):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = 'RGBA'; m.blend_type = 'MULTIPLY'
    m.inputs["Factor"].default_value = fac
    nt.links.new(a, m.inputs[6]); nt.links.new(b, m.inputs[7])
    return m.outputs[2]

def base_normal(nt):
    """材质里若有 Bevel 节点则返回其法线输出，供 Bump 串联。"""
    n = nt.nodes.get("EdgeBevel")
    return n.outputs["Normal"] if n else None

def noise_mix(mat, c1, c2, scale, detail=4.0, bump=0.0, coord="Object"):
    nt = mat.node_tree
    p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = (*c1, 1)
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = (*c2, 1)
    nt.links.new(tc.outputs[coord], n.inputs["Vector"])
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], p.inputs["Base Color"])
    if bump > 0:
        bn = nt.nodes.new("ShaderNodeBump")
        bn.inputs["Strength"].default_value = bump
        nt.links.new(n.outputs["Fac"], bn.inputs["Height"])
        if base_normal(nt):
            nt.links.new(base_normal(nt), bn.inputs["Normal"])
        nt.links.new(bn.outputs["Normal"], p.inputs["Normal"])
    return mat

def tile_material(name, c1, c2, rough=0.3, coat=0.5):
    """琉璃瓦：RoofingTiles014A 的位移/粗糙度提供筒瓦起伏，颜色按 c1~c2 染色；屋面 UV 让瓦垄顺坡。"""
    m = principled(name, c1, rough=rough, coat=coat)
    nt = m.node_tree
    pbs = nt.nodes["Principled BSDF"]
    SC = 0.38
    col = tex_node(nt, "RoofingTiles014A", "Color", SC, 'UV', noncolor=False)
    disp = tex_node(nt, "RoofingTiles014A", "Displacement", SC, 'UV')
    rgh = tex_node(nt, "RoofingTiles014A", "Roughness", SC, 'UV')
    ao = tex_node(nt, "RoofingTiles014A", "AmbientOcclusion", SC, 'UV')
    # 贴图明暗（去色）× 噪波染色
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    nt.links.new(col.outputs["Color"], bw.inputs["Color"])
    shade = map_range(nt, bw.outputs["Val"], 0.7, 1.3)
    tc = nt.nodes["TexCoordShared"]
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 5.0; nz.inputs["Detail"].default_value = 4.0
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.3; ramp.color_ramp.elements[0].color = (*c1, 1)
    ramp.color_ramp.elements[1].position = 0.7; ramp.color_ramp.elements[1].color = (*c2, 1)
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    c = mul_color(nt, ramp.outputs["Color"], shade)
    c = mul_color(nt, c, ao.outputs["Color"], 0.6)
    nt.links.new(c, pbs.inputs["Base Color"])
    nt.links.new(map_range(nt, rgh.outputs["Color"], rough * 0.6, rough * 1.5), pbs.inputs["Roughness"])
    tex_bump(nt, disp, 1.0, 0.1)
    return m

GOLD = tile_material("GlazedGold", (1.0, 0.60, 0.07), (1.0, 0.80, 0.20), rough=0.25, coat=0.6)
GREEN_TILE = tile_material("GlazedGreen", (0.10, 0.32, 0.20), (0.16, 0.42, 0.26))
BLACK_TILE = tile_material("GlazedBlack", (0.05, 0.07, 0.09), (0.09, 0.11, 0.14))
GREY_TILE = tile_material("GreyTile", (0.25, 0.26, 0.28), (0.37, 0.38, 0.40), rough=0.7, coat=0.0)
RED = principled("PalaceRedWall", (0.66, 0.12, 0.07), rough=0.8)
noise_mix(RED, (0.58, 0.10, 0.06), (0.72, 0.15, 0.08), 3.0)
BODY = principled("HallBody", (0.52, 0.08, 0.05), rough=0.75)
COLUMN = principled("Column", (0.66, 0.11, 0.06), rough=0.55, coat=0.2)
LATTICE = principled("DoorLattice", (0.45, 0.26, 0.07), rough=0.45, coat=0.2)
EAVE = principled("EaveTeal", (0.07, 0.24, 0.30), rough=0.55)
TRIM = principled("GoldTrim", (0.85, 0.62, 0.18), rough=0.35, metal=0.6)
RIDGE = principled("Ridge", (0.26, 0.19, 0.11), rough=0.5)
MARBLE = principled("WhiteMarble", (0.74, 0.71, 0.64), rough=0.5)
nt = MARBLE.node_tree
_c = tex_node(nt, "Marble020", "Color", 0.5, 'Object', noncolor=False)
_r = tex_node(nt, "Marble020", "Roughness", 0.5, 'Object')
_d = tex_node(nt, "Marble020", "Displacement", 0.5, 'Object')
_white = nt.nodes.new("ShaderNodeMix"); _white.data_type = 'RGBA'; _white.blend_type = 'MIX'
_white.inputs["Factor"].default_value = 0.55
_white.inputs[7].default_value = (0.93, 0.92, 0.88, 1)
nt.links.new(_c.outputs["Color"], _white.inputs[6])
_tint = nt.nodes.new("ShaderNodeRGB"); _tint.outputs[0].default_value = (1.12, 1.1, 1.06, 1)
nt.links.new(mul_color(nt, _white.outputs[2], _tint.outputs[0]), nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.35, 0.7), nt.nodes["Principled BSDF"].inputs["Roughness"])
tex_bump(nt, _d, 0.4, 0.02)
TRUNK = principled("Trunk", (0.22, 0.14, 0.08), rough=0.9)
ROCK = principled("GardenRock", (0.38, 0.36, 0.32), rough=0.9, bevel=0.08)
noise_mix(ROCK, (0.30, 0.28, 0.25), (0.48, 0.46, 0.42), 3.0, bump=0.8)
FINIAL = principled("Finial", (1.0, 0.78, 0.25), rough=0.25, metal=1.0)
WATER = principled("Water", (0.07, 0.20, 0.22), rough=0.04, spec=0.9, bevel=0)
GRASS = principled("Grass", (0.33, 0.44, 0.17), rough=0.95, bevel=0)
nt = GRASS.node_tree
_c = tex_node(nt, "Grass004", "Color", 0.8, 'Object', noncolor=False)
_d = tex_node(nt, "Grass004", "Displacement", 0.8, 'Object')
_gn = nt.nodes.new("ShaderNodeTexNoise"); _gn.inputs["Scale"].default_value = 0.35; _gn.inputs["Detail"].default_value = 3.0
nt.links.new(nt.nodes["TexCoordShared"].outputs["Object"], _gn.inputs["Vector"])
_gr = nt.nodes.new("ShaderNodeValToRGB")
_gr.color_ramp.elements[0].color = (0.70, 0.78, 0.50, 1)
_gr.color_ramp.elements[1].color = (1.05, 1.0, 0.85, 1)
nt.links.new(_gn.outputs["Fac"], _gr.inputs["Fac"])
nt.links.new(mul_color(nt, _c.outputs["Color"], _gr.outputs["Color"]), nt.nodes["Principled BSDF"].inputs["Base Color"])
tex_bump(nt, _d, 1.0, 0.06)
DIRT = principled("Dirt", (0.40, 0.33, 0.22), rough=0.95)

STONE = principled("StonePaving", (0.56, 0.53, 0.48), rough=0.9)
nt = STONE.node_tree
_c = tex_node(nt, "PavingStones128", "Color", 0.7, 'Object', noncolor=False)
_r = tex_node(nt, "PavingStones128", "Roughness", 0.7, 'Object')
_d = tex_node(nt, "PavingStones128", "Displacement", 0.7, 'Object')
_a = tex_node(nt, "PavingStones128", "AmbientOcclusion", 0.7, 'Object')
tc = nt.nodes["TexCoordShared"]
# 大块区域的随机灰阶色差
vor = nt.nodes.new("ShaderNodeTexVoronoi")
vor.inputs["Scale"].default_value = 0.45
vor.inputs["Randomness"].default_value = 0.6
nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
vbw = nt.nodes.new("ShaderNodeRGBToBW"); nt.links.new(vor.outputs["Color"], vbw.inputs["Color"])
_col = mul_color(nt, _c.outputs["Color"], map_range(nt, vbw.outputs["Val"], 0.85, 1.12))
_col = mul_color(nt, _col, _a.outputs["Color"], 0.7)
# 墙根 / 台基脚的接触阴影
ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
ao.inputs["Distance"].default_value = 1.2
ao.samples = 4
_col = mul_color(nt, _col, ao.outputs["Color"], 0.5)
_tint = nt.nodes.new("ShaderNodeRGB"); _tint.outputs[0].default_value = (1.12, 1.10, 1.06, 1)
_col = mul_color(nt, _col, _tint.outputs[0])
nt.links.new(_col, nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.6, 0.95), nt.nodes["Principled BSDF"].inputs["Roughness"])
tex_bump(nt, _d, 0.7, 0.04)

LEAF = principled("Leaf", (0.20, 0.38, 0.16), rough=0.9, bevel=0)
if "Subsurface Weight" in LEAF.node_tree.nodes["Principled BSDF"].inputs:
    LEAF.node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.15
    LEAF.node_tree.nodes["Principled BSDF"].inputs["Subsurface Radius"].default_value = (0.3, 0.5, 0.1)
nt = LEAF.node_tree
oi = nt.nodes.new("ShaderNodeObjectInfo")
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.08, 0.24, 0.07, 1)
ramp.color_ramp.elements[1].color = (0.34, 0.48, 0.14, 1)
n2 = nt.nodes.new("ShaderNodeTexNoise")
n2.inputs["Scale"].default_value = 28.0
n2.inputs["Detail"].default_value = 6.0
bn = nt.nodes.new("ShaderNodeBump")
bn.inputs["Strength"].default_value = 0.9
bn.inputs["Distance"].default_value = 0.08
nt.links.new(oi.outputs["Random"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(n2.outputs["Fac"], bn.inputs["Height"])
nt.links.new(bn.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])

# 地形切面：Rock051 层状岩贴图 + 高度分层染色 + 裂缝凹凸
EARTH = principled("EarthCut", (0.40, 0.29, 0.19), rough=0.95, bevel=0)
nt = EARTH.node_tree
p = nt.nodes["Principled BSDF"]
_c = tex_node(nt, "Rock051", "Color", 0.14, 'Object', noncolor=False)
_r = tex_node(nt, "Rock051", "Roughness", 0.14, 'Object')
_d = tex_node(nt, "Rock051", "Displacement", 0.14, 'Object')
tc = nt.nodes["TexCoordShared"]
wave = nt.nodes.new("ShaderNodeTexWave")
wave.wave_type = 'BANDS'
wave.bands_direction = 'Z'
wave.inputs["Scale"].default_value = 0.45
wave.inputs["Distortion"].default_value = 4.0
wave.inputs["Detail"].default_value = 3.0
wave.inputs["Detail Scale"].default_value = 1.5
nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].position = 0.15
ramp.color_ramp.elements[0].color = (1.9, 1.4, 0.95, 1)
ramp.color_ramp.elements[1].position = 0.85
ramp.color_ramp.elements[1].color = (3.4, 3.0, 2.4, 1)
e = ramp.color_ramp.elements.new(0.5); e.color = (2.8, 2.3, 1.7, 1)
nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
_col = mul_color(nt, _c.outputs["Color"], ramp.outputs["Color"])
nt.links.new(_col, p.inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.7, 1.0), p.inputs["Roughness"])
bn = tex_bump(nt, _d, 1.2, 0.5)
# 大尺度裂缝（Voronoi 边缘）
cr = nt.nodes.new("ShaderNodeTexVoronoi")
cr.feature = 'DISTANCE_TO_EDGE'
cr.inputs["Scale"].default_value = 0.35
nt.links.new(tc.outputs["Object"], cr.inputs["Vector"])
crr = nt.nodes.new("ShaderNodeValToRGB")
crr.color_ramp.elements[0].position = 0.0
crr.color_ramp.elements[1].position = 0.12
crb = nt.nodes.new("ShaderNodeBump")
crb.inputs["Strength"].default_value = 0.8
crb.inputs["Distance"].default_value = 0.8
nt.links.new(cr.outputs["Distance"], crr.inputs["Fac"])
nt.links.new(crr.outputs["Color"], crb.inputs["Height"])
nt.links.new(crb.outputs["Normal"], bn.inputs["Normal"])

# ----------------------------------------------------------------------------- 网格构建器
class B:
    def __init__(self, name):
        self.name, self.v, self.f, self.m, self.mats = name, [], [], [], []
        self.uv = []   # 每面的 [(u, v), ...] 或 None
    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)
    def add(self, verts, faces, mat, uvs=None):
        off = len(self.v)
        self.v.extend(verts)
        self.f.extend(tuple(i + off for i in f) for f in faces)
        self.m.extend([self.mi(mat)] * len(faces))
        self.uv.extend(uvs if uvs is not None else [None] * len(faces))
    def build(self, loc=(0, 0, 0), rot=0.0, smooth=False):
        me = bpy.data.meshes.new(self.name)
        me.from_pydata(self.v, [], self.f)
        for mat in self.mats:
            me.materials.append(mat)
        for poly, mi in zip(me.polygons, self.m):
            poly.material_index = mi
        if smooth:
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        if any(u is not None for u in self.uv):
            uvl = me.uv_layers.new(name="UVMap")
            data = uvl.data
            for poly, fuv in zip(me.polygons, self.uv):
                if fuv is None:
                    for li in poly.loop_indices:
                        co = me.vertices[me.loops[li].vertex_index].co
                        data[li].uv = (co.x, co.y)
                else:
                    for k, li in enumerate(poly.loop_indices):
                        data[li].uv = fuv[k]
        me.update()
        ob = bpy.data.objects.new(self.name, me)
        ob.location = loc
        ob.rotation_euler = (0, 0, rot)
        COL.objects.link(ob)
        return ob

def box_geo(cx, cy, z0, w, d, h):
    hw, hd, z1 = w / 2, d / 2, z0 + h
    v = [(cx - hw, cy - hd, z0), (cx + hw, cy - hd, z0), (cx + hw, cy + hd, z0), (cx - hw, cy + hd, z0),
         (cx - hw, cy - hd, z1), (cx + hw, cy - hd, z1), (cx + hw, cy + hd, z1), (cx - hw, cy + hd, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f

def box(b, cx, cy, z0, w, d, h, mat):
    v, f = box_geo(cx, cy, z0, w, d, h)
    b.add(v, f, mat)

def prism(b, cx, cy, z0, r, h, mat, n=8):
    v = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z0) for i in range(n)]
    v += [(x, y, z0 + h) for (x, y, _) in v]
    f = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    f.append(tuple(range(n, 2 * n)))
    f.append(tuple(reversed(range(n))))
    b.add(v, f, mat)

def rod(b, p0, p1, t, mat, lift=0.0):
    """两点之间的细方杆（垂脊）。"""
    p0, p1 = mathutils.Vector(p0), mathutils.Vector(p1)
    d = (p1 - p0).normalized()
    up = mathutils.Vector((0, 0, 1))
    side = d.cross(up)
    if side.length < 1e-4:
        side = mathutils.Vector((1, 0, 0))
    side.normalize()
    nrm = side.cross(d).normalized()
    if nrm.z < 0:
        nrm = -nrm
    v = []
    for p in (p0, p1):
        base = p + nrm * lift
        v += [tuple(base - side * t), tuple(base + side * t), tuple(base + side * t + nrm * t * 1.6),
              tuple(base - side * t + nrm * t * 1.6)]
    f = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    b.add(v, f, mat)

def _face_uv(verts, face):
    """屋面 UV：u 沿檐口方向（按法线自动取 x 或 y），v 为顺坡高度。"""
    a, b2, c = (mathutils.Vector(verts[i]) for i in face[:3])
    nrm = (b2 - a).cross(c - a)
    use_y = abs(nrm.x) > abs(nrm.y)
    return [((verts[i][1] if use_y else verts[i][0]), verts[i][2] * 1.7) for i in face]

def _roof_shell(b, outer, upper, faces, mat, t=0.13):
    top = outer + upper
    bot = [(x, y, z - t) for (x, y, z) in top]
    n = len(top)
    fs = list(faces)
    fs += [tuple(n + i for i in reversed(f)) for f in faces]
    for i in range(8):
        j = (i + 1) % 8
        fs.append((i, n + i, n + j, j))
    allv = top + bot
    b.add(allv, fs, mat, uvs=[_face_uv(allv, f) for f in fs])

def eave_loop(w, d, z, curl):
    hw, hd = w / 2, d / 2
    return [(-hw, -hd, z + curl), (0, -hd, z), (hw, -hd, z + curl), (hw, 0, z),
            (hw, hd, z + curl), (0, hd, z), (-hw, hd, z + curl), (-hw, 0, z)]

def hip_roof(b, cx, cy, z, w, d, h, mat=GOLD, ridge=0.55, curl=0.16, ridge_beam=True):
    outer = [(x + cx, y + cy, zz) for (x, y, zz) in eave_loop(w, d, z, curl)]
    rw = w / 2 * ridge
    upper = [(cx - rw, cy, z + h), (cx + rw, cy, z + h)]
    faces = [(0, 1, 8), (1, 2, 9), (2, 3, 9), (3, 4, 9), (4, 5, 9), (5, 6, 8), (6, 7, 8), (7, 0, 8)]
    if rw > 1e-6:
        faces += [(1, 9, 8), (5, 8, 9)]
    _roof_shell(b, outer, upper, faces, mat)
    rt = 0.045 + 0.01 * h
    for ci, ri in ((0, 0), (6, 0), (2, 1), (4, 1)):
        rod(b, outer[ci], upper[ri], rt, RIDGE, lift=0.01)
    if ridge_beam:
        if rw > 1e-6:
            box(b, cx, cy, z + h - 0.06, rw * 2 + 0.25, 0.2, 0.2, RIDGE)
            box(b, cx - rw - 0.1, cy, z + h + 0.1, 0.22, 0.22, 0.22, RIDGE)
            box(b, cx + rw + 0.1, cy, z + h + 0.1, 0.22, 0.22, 0.22, RIDGE)
        else:
            box(b, cx, cy, z + h - 0.05, 0.3, 0.3, 0.3, RIDGE)
            prism(b, cx, cy, z + h + 0.2, 0.12, 0.35, FINIAL)

def skirt_roof(b, cx, cy, z, w, d, inset, rise, mat=GOLD, curl=0.16):
    outer = [(x + cx, y + cy, zz) for (x, y, zz) in eave_loop(w, d, z, curl)]
    wi, di = w / 2 - inset, d / 2 - inset
    upper = [(cx - wi, cy - di, z + rise), (cx + wi, cy - di, z + rise),
             (cx + wi, cy + di, z + rise), (cx - wi, cy + di, z + rise)]
    faces = [(0, 1, 8), (1, 2, 9), (1, 9, 8), (2, 3, 9), (3, 4, 10), (3, 10, 9),
             (4, 5, 10), (5, 6, 11), (5, 11, 10), (6, 7, 11), (7, 0, 8), (7, 8, 11)]
    _roof_shell(b, outer, upper, faces, mat)
    for ci, ui in ((0, 0), (2, 1), (4, 2), (6, 3)):
        rod(b, outer[ci], upper[ui], 0.045, RIDGE, lift=0.01)

def balustrade(b, pts, z, step=0.75, skip=None, closed=True):
    n = len(pts)
    segs = range(n) if closed else range(n - 1)
    for i in segs:
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        k = max(1, int(L / step))
        for j in range(k + 1):
            t = j / k
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if skip and skip(x, y):
                continue
            box(b, x, y, z, 0.11, 0.11, 0.34, MARBLE)
            box(b, x, y, z + 0.34, 0.15, 0.15, 0.08, MARBLE)
        if x0 == x1:
            box(b, x0, (y0 + y1) / 2, z + 0.16, 0.06, L, 0.1, MARBLE)
        else:
            box(b, (x0 + x1) / 2, y0, z + 0.16, L, 0.06, 0.1, MARBLE)

def stairs(b, cx, cy, z0, w, h, steps=4, dir=-1):
    for i in range(steps):
        hh = h * (steps - i) / steps
        box(b, cx, cy + dir * (0.28 * i + 0.14), z0, w, 0.3, hh, MARBLE)

FLOOR = 0.3
HS, HZ = 1.7, 1.85   # 宫殿平面 / 高度放大系数

def hall(b, cx, cy, w, d, body_h, double=False, plat_h=0.35, plat_pad=0.5, roof_h=None,
         roof_mat=GOLD, pyramid=False, stair=True, z0=FLOOR, wall_mat=BODY, ridge=0.55, rail=None):
    w, d, body_h = w * HS, d * HS, body_h * HZ
    if roof_h is not None:
        roof_h *= HZ
    if rail is None:
        rail = plat_h >= 0.3
    z = z0
    if plat_h > 0:
        pw, pd = w + 2 * plat_pad, d + 2 * plat_pad
        box(b, cx, cy, z, pw, pd, plat_h, MARBLE)
        if stair:
            stairs(b, cx, cy - pd / 2, z, min(w * 0.4, 3.0), plat_h, steps=3 if plat_h < 0.4 else 4)
        if rail:
            sw = min(w * 0.4, 3.0) / 2 + 0.1
            balustrade(b, [(cx - pw / 2, cy - pd / 2), (cx + pw / 2, cy - pd / 2), (cx + pw / 2, cy + pd / 2),
                           (cx - pw / 2, cy + pd / 2)], z + plat_h,
                       skip=(lambda x, y: abs(x - cx) < sw and abs(y - (cy - pd / 2)) < 0.05) if stair else None)
        z += plat_h
    over = 0.4 + 0.12 * body_h
    if roof_h is None:
        roof_h = 0.42 * d + 0.3
    if pyramid:
        ridge = 0.0

    def body(z, w, d, h):
        inset = 0.26
        box(b, cx, cy, z, w - 0.2, d - 2 * inset, h, wall_mat)
        n = max(3, int(round(w / 0.95)) + 1)
        r = 0.07 + 0.012 * h
        for i in range(n):
            x = cx - w / 2 + 0.18 + (w - 0.36) * i / (n - 1)
            prism(b, x, cy - d / 2 + 0.1, z, r, h, COLUMN)
            prism(b, x, cy + d / 2 - 0.1, z, r, h, COLUMN)
        box(b, cx, cy - d / 2 + inset - 0.03, z + 0.1, w - 0.7, 0.06, h * 0.72, LATTICE)
        box(b, cx, cy + d / 2 - inset + 0.03, z + 0.1, w - 0.7, 0.06, h * 0.72, LATTICE)
        box(b, cx, cy, z + h - 0.2, w + 0.1, d + 0.1, 0.1, TRIM)
        box(b, cx, cy, z + h - 0.1, w + 0.16, d + 0.16, 0.18, EAVE)

    if double:
        h1 = body_h * 0.55
        body(z, w, d, h1)
        skirt_roof(b, cx, cy, z + h1 + 0.08, w + 2 * over, d + 2 * over, inset=over + 0.5, rise=0.48, mat=roof_mat)
        z2 = z + h1 + 0.56
        w2, d2 = w - 1.0, d - 1.0
        h2 = body_h * 0.45
        body(z2 - 0.08, w2, d2, h2 + 0.08)
        hip_roof(b, cx, cy, z2 + h2 + 0.08, w2 + 2 * over, d2 + 2 * over, roof_h, roof_mat, ridge=ridge)
    else:
        body(z, w, d, body_h)
        hip_roof(b, cx, cy, z + body_h + 0.08, w + 2 * over, d + 2 * over, roof_h, roof_mat, ridge=ridge)

def pavilion(b, cx, cy, size, body_h, z0=FLOOR, double=True, roof_mat=GOLD, plat_h=0.2):
    hall(b, cx, cy, size, size, body_h, double=double, plat_h=plat_h, plat_pad=0.25, pyramid=True,
         roof_h=size * 0.6, roof_mat=roof_mat, stair=False, z0=z0, rail=False)

def wall(b, x0, y0, x1, y1, h=0.7, t=0.45, z0=FLOOR, cap=GOLD):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = abs(x1 - x0) + t if x0 != x1 else t
    d = abs(y1 - y0) + t if y0 != y1 else t
    box(b, cx, cy, z0, w, d, h, RED)
    box(b, cx, cy, z0 + h, w + 0.16, d + 0.16, 0.1, cap)
    box(b, cx, cy, z0 + h + 0.1, w + 0.04, d + 0.04, 0.06, RIDGE)

def wall_ring(b, x0, y0, x1, y1, h=0.7, t=0.45, z0=FLOOR, gate=True):
    wall(b, x0, y0, x1, y0, h, t, z0); wall(b, x0, y1, x1, y1, h, t, z0)
    wall(b, x0, y0, x0, y1, h, t, z0); wall(b, x1, y0, x1, y1, h, t, z0)
    if gate:
        cx = (x0 + x1) / 2
        hall(b, cx, y0, 1.3, 0.75, 0.5, plat_h=0.0, roof_h=0.5, stair=False, z0=z0)

TREES = []   # (x, y, scale, z0)

def compound(b, cx, cy, w, d, hall_w, hall_d, hall_h, roof_mat=GOLD, z0=FLOOR, side=True, double=False, trees=True):
    wall_ring(b, cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2, z0=z0)
    hall(b, cx, cy + d * 0.2, hall_w, hall_d, hall_h, plat_h=0.2, plat_pad=0.35, roof_mat=roof_mat, z0=z0, double=double)
    if side:
        hall(b, cx - w / 2 + 0.95, cy - d * 0.1, 0.8, hall_w * 0.5, hall_h * 0.7, plat_h=0.1, plat_pad=0.15,
             roof_mat=roof_mat, stair=False, z0=z0, roof_h=0.45)
        hall(b, cx + w / 2 - 0.95, cy - d * 0.1, 0.8, hall_w * 0.5, hall_h * 0.7, plat_h=0.1, plat_pad=0.15,
             roof_mat=roof_mat, stair=False, z0=z0, roof_h=0.45)
    if trees and random.random() < 0.7:
        TREES.append((cx + random.uniform(-1.2, 1.2), cy - d * 0.3 + random.uniform(-0.3, 0.3), random.uniform(0.6, 0.8), z0))

def corridor(b, cx, cy, w, d, roof_mat=GOLD, z0=FLOOR, h=0.5):
    hall(b, cx, cy, w, d, h, plat_h=0.12, plat_pad=0.2, roof_h=0.42 * min(w, d) + 0.2, roof_mat=roof_mat,
         stair=False, z0=z0, rail=False)

def gate_tower(b, cx, cy, w, d, h_base, hall_w, hall_d, hall_h, double=True, z0=FLOOR):
    box(b, cx, cy, z0, w, d, 0.2, GREY_TILE)
    box(b, cx, cy, z0 + 0.2, w, d, h_base - 0.2, RED)
    box(b, cx, cy, z0 + h_base, w + 0.2, d + 0.2, 0.14, GREY_TILE)
    box(b, cx, cy, z0, 1.1, d + 0.2, 0.95, RIDGE)
    balustrade(b, [(cx - w / 2 - 0.05, cy - d / 2 - 0.05), (cx + w / 2 + 0.05, cy - d / 2 - 0.05),
                   (cx + w / 2 + 0.05, cy + d / 2 + 0.05), (cx - w / 2 - 0.05, cy + d / 2 + 0.05)], z0 + h_base + 0.14, step=0.9)
    hall(b, cx, cy, hall_w, hall_d, hall_h, double=double, plat_h=0.12, plat_pad=0.3, stair=False,
         z0=z0 + h_base + 0.14, rail=False)

def icosphere(cx, cy, cz, r, sub=2, squash=0.85):
    t = (1 + 5 ** 0.5) / 2
    v = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
         (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    f = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
         (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
         (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    def norm(p):
        l = math.sqrt(sum(c * c for c in p)); return tuple(c / l for c in p)
    v = [norm(p) for p in v]
    for _ in range(sub):
        cache, nf = {}, []
        def mid(a, b2):
            k = (min(a, b2), max(a, b2))
            if k not in cache:
                v.append(norm(tuple((v[a][i] + v[b2][i]) / 2 for i in range(3)))); cache[k] = len(v) - 1
            return cache[k]
        for a, b2, c in f:
            ab, bc, ca = mid(a, b2), mid(b2, c), mid(c, a)
            nf += [(a, ab, ca), (b2, bc, ab), (c, ca, bc), (ab, bc, ca)]
        f = nf
    out = [(x * r * random.uniform(0.9, 1.08) + cx, y * r * random.uniform(0.9, 1.08) + cy,
            z * r * squash * random.uniform(0.92, 1.08) + cz) for (x, y, z) in v]
    return out, f

def tree_obj(x, y, s=1.0, z0=FLOOR):
    b = B("Tree")
    th = random.uniform(0.35, 0.55) * s
    prism(b, x, y, z0, 0.07 * s, th + 0.45 * s, TRUNK, n=6)
    # 主冠 + 若干小叶团，平滑着色后呈柔和的树冠轮廓
    R = random.uniform(0.48, 0.62) * s
    v, f = icosphere(x, y, z0 + th + 0.5 * s, R * 0.85, sub=2, squash=0.8)
    b.add(v, f, LEAF)
    n = random.choice([7, 8, 10])
    for i in range(n):
        a = random.uniform(0, 2 * math.pi)
        rr = random.uniform(0.2, 0.55) * s
        r = random.uniform(0.2, 0.34) * s
        v, f = icosphere(x + rr * math.cos(a), y + rr * math.sin(a), z0 + th + random.uniform(0.2, 0.75) * s + r * 0.5, r, sub=2)
        b.add(v, f, LEAF)
    return b.build(smooth=True)

def bush(b, x, y, s=0.5, z0=FLOOR):
    for i in range(3):
        v, f = icosphere(x + random.uniform(-0.2, 0.2) * s, y + random.uniform(-0.2, 0.2) * s, z0 + 0.15 * s,
                         random.uniform(0.2, 0.32) * s, sub=1, squash=0.7)
        b.add(v, f, LEAF)

def tree_patch(x0, y0, x1, y1, n, s=(0.8, 1.2), z0=FLOOR):
    for _ in range(n):
        TREES.append((random.uniform(x0, x1), random.uniform(y0, y1), random.uniform(*s), z0))

# ----------------------------------------------------------------------------- 尺寸
WX, WS, WN = 37.5, -48.0, 48.0
MOAT_IN = (-39.5, -57.5, 39.5, 49.8)     # 筒子河内沿
MOAT_OUT = (-43.0, -61.0, 43.0, 53.3)    # 筒子河外沿
ISL = (-48.0, -66.0, 48.0, 82.0)         # 岛屿顶面范围（含城外绿地与景山）
HILL_C = (0.0, 67.0)                      # 景山中心

def hill_z(x, y):
    """景山高度场：五峰一字排开。"""
    hx, hy = x - HILL_C[0], y - HILL_C[1]
    z = 0.0
    for (px, H, rx, ry) in ((0, 7.5, 9.0, 8.5), (-6.0, 5.2, 7.0, 7.0), (6.0, 5.2, 7.0, 7.0), (-12.0, 3.4, 6.0, 6.0), (12.0, 3.4, 6.0, 6.0)):
        r2 = ((hx - px) / rx) ** 2 + (hy / ry) ** 2
        if r2 < 1:
            z = max(z, H * (1 - r2) ** 1.1)
    return z

# ----------------------------------------------------------------------------- 地形岛屿（厚重的岩层切面）
def island():
    b = B("Island")
    x0, y0, x1, y1 = ISL
    cx, cy, hw, hd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    N = 180
    ph = [random.uniform(0, 6.28) for _ in range(5)]
    def profile(a):
        return (0.5 * math.sin(3 * a + ph[0]) + 0.3 * math.sin(7 * a + ph[1]) + 0.22 * math.sin(13 * a + ph[2])
                + 0.14 * math.sin(23 * a + ph[3]) + 0.1 * math.sin(41 * a + ph[4]))
    def base_xy(a):
        c, s = math.cos(a), math.sin(a)
        e = 0.18
        return math.copysign(abs(c) ** e, c) * hw, math.copysign(abs(s) ** e, s) * hd
    def ring(scale, z, amp, jitter, zj):
        pts = []
        for i in range(N):
            a = 2 * math.pi * i / N
            x, y = base_xy(a)
            w = scale * (1 + amp * profile(a)) + random.uniform(-jitter, jitter)
            pts.append((cx + x * w, cy + y * w, z + random.uniform(-zj, zj)))
        return pts
    top = []
    for i in range(N):
        a = 2 * math.pi * i / N
        x, y = base_xy(a)
        w = 1.0 + 0.02 * (profile(a) + 1.3)
        top.append((cx + x * w, cy + y * w, 0.0))
    rings = [top,
             ring(1.0, -2.2, 0.03, 0.012, 0.4), ring(0.995, -5.5, 0.05, 0.02, 0.7), ring(0.985, -9.5, 0.065, 0.025, 0.8),
             ring(0.965, -13.5, 0.075, 0.03, 0.8), ring(0.93, -17.5, 0.085, 0.03, 0.8), ring(0.87, -21.0, 0.095, 0.03, 0.8),
             ring(0.76, -24.0, 0.1, 0.03, 0.6), ring(0.55, -26.5, 0.1, 0.03, 0.4), ring(0.3, -28.0, 0.1, 0.02, 0.3)]
    v, f = [], []
    for r in rings:
        v.extend(r)
    R = len(rings)
    for k in range(R - 1):
        for i in range(N):
            j = (i + 1) % N
            f.append((k * N + i, k * N + j, (k + 1) * N + j, (k + 1) * N + i))
    v.append((cx, cy, -29.0)); apex = len(v) - 1
    for i in range(N):
        j = (i + 1) % N
        f.append(((R - 1) * N + j, (R - 1) * N + i, apex))
    b.add(v, f, EARTH)
    b.add(list(top), [tuple(reversed(range(N)))], GRASS)
    return b.build()

def jingshan():
    """景山：五峰土山 + 五亭 + 树木。"""
    b = B("Jingshan")
    X0, X1, Y0, Y1 = -19.0, 19.0, HILL_C[1] - 9.5, HILL_C[1] + 9.5
    nx, ny = 76, 38
    verts = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            x = X0 + (X1 - X0) * i / nx
            y = Y0 + (Y1 - Y0) * j / ny
            z = hill_z(x, y)
            if z > 0.05:
                z += random.uniform(-0.12, 0.12) + 0.2 * math.sin(x * 1.7) * math.sin(y * 2.3) * min(1, z)
            verts.append((x, y, max(z, 0.0) + 0.14))
    faces = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    hb = B("JingshanHill")
    hb.add(verts, faces, GRASS)
    hb.build(smooth=True)
    box(b, (X0 + X1) / 2, (Y0 + Y1) / 2, 0.0, X1 - X0 + 3.4, Y1 - Y0 + 2.8, 0.06, STONE)
    # 山脚围墙 + 南门
    wall_ring(b, X0 - 1.5, Y0 - 1.2, X1 + 1.5, Y1 + 1.2, h=0.6, z0=0.0, gate=True)
    # 五亭
    peaks = ((0, 7.5), (-6.0, 5.2), (6.0, 5.2), (-12.0, 3.4), (12.0, 3.4))
    for k, (px, H) in enumerate(peaks):
        zt = hill_z(HILL_C[0] + px, HILL_C[1])
        zt += 0.14
        box(b, HILL_C[0] + px, HILL_C[1], zt - 0.3, 2.6, 2.6, 0.45, MARBLE)
        if k == 0:
            pavilion(b, HILL_C[0] + px, HILL_C[1], 1.6, 1.0, z0=zt + 0.15, plat_h=0.0)
        else:
            pavilion(b, HILL_C[0] + px, HILL_C[1], 1.2, 0.8, z0=zt + 0.15, plat_h=0.0, double=(k < 3))
    # 山脚寿皇殿（北）与绮望楼（南）
    hall(b, 0, Y1 - 2.0, 3.0, 1.5, 0.95, plat_h=0.25, plat_pad=0.35, roof_h=0.9, z0=0.0)
    hall(b, 0, Y0 + 2.2, 2.6, 1.2, 0.8, plat_h=0.2, plat_pad=0.3, roof_h=0.75, z0=0.0)
    b.build()
    n = 0
    while n < 110:
        x, y = random.uniform(X0, X1), random.uniform(Y0, Y1)
        z = hill_z(x, y)
        if z < 0.05 and random.random() < 0.6:
            continue
        if any(abs(x - (HILL_C[0] + px)) < 1.8 and abs(y - HILL_C[1]) < 1.8 for (px, H) in peaks):
            continue
        TREES.append((x, y, random.uniform(0.6, 1.0), z + 0.1))
        n += 1

def ground():
    b = B("Ground")
    x0, y0, x1, y1 = MOAT_IN
    box(b, (x0 + x1) / 2, (y0 + y1) / 2, 0.0, x1 - x0, y1 - y0, FLOOR, STONE)       # 城内石板台地
    X0, Y0, X1, Y1 = MOAT_OUT
    box(b, (X0 + X1) / 2, (Y0 + Y1) / 2, 0.0, X1 - X0, Y1 - Y0, 0.14, WATER)       # 筒子河
    # 河外石岸
    for (a, bb, c, d) in [(X0 - 1.0, Y0 - 1.0, X1 + 1.0, Y0), (X0 - 1.0, Y1, X1 + 1.0, Y1 + 1.0),
                          (X0 - 1.0, Y0, X0, Y1), (X1, Y0, X1 + 1.0, Y1)]:
        box(b, (a + c) / 2, (bb + d) / 2, 0.0, c - a, d - bb, 0.26, STONE)
    for (a, bb, c, d) in [(x0 - 0.3, y0 - 0.3, x1 + 0.3, y0), (x0 - 0.3, y1, x1 + 0.3, y1 + 0.3),
                          (x0 - 0.3, y0, x0, y1), (x1, y0, x1 + 0.3, y1)]:
        box(b, (a + c) / 2, (bb + d) / 2, 0.0, c - a, d - bb, 0.34, MARBLE)
    # 南面御桥 + 御道
    box(b, 0, (Y0 + y0) / 2, 0.0, 3.6, y0 - Y0 + 1.2, 0.36, MARBLE)
    balustrade(b, [(-1.8, Y0 - 0.5), (-1.8, y0 + 0.5)], 0.36, step=0.5, closed=False)
    balustrade(b, [(1.8, Y0 - 0.5), (1.8, y0 + 0.5)], 0.36, step=0.5, closed=False)
    box(b, 0, (Y0 - 1.0 + ISL[1] + 1.5) / 2, 0.0, 16.0, Y0 - 1.0 - ISL[1] - 1.5, 0.26, STONE)   # 桥南广场
    box(b, 0, (Y0 - 1.0 + ISL[1] + 1.5) / 2, 0.26, 2.4, Y0 - 1.0 - ISL[1] - 1.5, 0.02, MARBLE)
    box(b, 0, (WS + y0) / 2, FLOOR, 2.6, WS - y0, 0.02, MARBLE)                     # 午门前御道
    box(b, 0, -14.0, FLOOR, 2.4, 66.0, 0.02, MARBLE)                                 # 城内中轴御路
    # 北面御桥到景山
    box(b, 0, (Y1 + y1) / 2, 0.0, 3.0, Y1 - y1 + 1.2, 0.36, MARBLE)
    box(b, 0, (Y1 + 1.0 + HILL_C[1] - 11.0) / 2, 0.0, 2.2, HILL_C[1] - 11.0 - Y1 - 1.0, 0.08, STONE)
    # 东西环路
    for (cx, cy, w, d) in ((X1 + 2.6, 0, 1.2, Y1 - Y0 + 6), (X0 - 2.6, 0, 1.2, Y1 - Y0 + 6)):
        box(b, cx, cy, 0.0, w, d, 0.06, DIRT)
    return b.build()

# ----------------------------------------------------------------------------- 城墙 / 城门 / 角楼
def city_wall():
    b = B("CityWall")
    H, T = 1.15, 1.0
    for (x0, y0, x1, y1) in [(-WX, WS, WX, WS), (-WX, WN, WX, WN), (-WX, WS, -WX, WN), (WX, WS, WX, WN)]:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = abs(x1 - x0) + T if x0 != x1 else T
        d = abs(y1 - y0) + T if y0 != y1 else T
        box(b, cx, cy, FLOOR, w + 0.3, d + 0.3, 0.18, GREY_TILE)
        box(b, cx, cy, FLOOR + 0.18, w, d, H - 0.18, RED)
        box(b, cx, cy, FLOOR + H, w + 0.2, d + 0.2, 0.08, GREY_TILE)
        if x0 != x1:
            for xx in range(int(x0) + 1, int(x1), 2):
                box(b, xx, cy + 0.45, FLOOR + H + 0.08, 1.0, 0.16, 0.24, GREY_TILE)
                box(b, xx, cy - 0.45, FLOOR + H + 0.08, 1.0, 0.16, 0.24, GREY_TILE)
        else:
            for yy in range(int(y0) + 1, int(y1), 2):
                box(b, cx + 0.45, yy, FLOOR + H + 0.08, 0.16, 1.0, 0.24, GREY_TILE)
                box(b, cx - 0.45, yy, FLOOR + H + 0.08, 0.16, 1.0, 0.24, GREY_TILE)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * WX, (WS if sy < 0 else WN)
            z = FLOOR + H + 0.08
            box(b, cx, cy, FLOOR, 3.2, 3.2, H + 0.08, RED)
            box(b, cx, cy, z, 3.5, 3.5, 0.12, MARBLE)
            z += 0.12
            balustrade(b, [(cx - 1.7, cy - 1.7), (cx + 1.7, cy - 1.7), (cx + 1.7, cy + 1.7), (cx - 1.7, cy + 1.7)], z, step=0.6)
            box(b, cx, cy, z, 2.4, 2.4, 0.7, BODY)
            for i in range(5):
                for (px, py) in ((cx - 1.2 + 0.6 * i, cy - 1.2), (cx - 1.2 + 0.6 * i, cy + 1.2),
                                 (cx - 1.2, cy - 1.2 + 0.6 * i), (cx + 1.2, cy - 1.2 + 0.6 * i)):
                    prism(b, px, py, z, 0.07, 0.7, COLUMN)
            box(b, cx, cy, z + 0.55, 2.55, 2.55, 0.15, EAVE)
            skirt_roof(b, cx, cy, z + 0.75, 3.7, 3.7, inset=0.95, rise=0.4)
            z += 1.15
            box(b, cx, cy, z - 0.05, 1.7, 1.7, 0.65, BODY)
            box(b, cx, cy, z + 0.45, 1.85, 1.85, 0.15, EAVE)
            skirt_roof(b, cx, cy, z + 0.65, 2.9, 2.9, inset=0.85, rise=0.35)
            z += 1.0
            box(b, cx, cy, z - 0.05, 1.1, 1.1, 0.55, BODY)
            box(b, cx, cy, z + 0.35, 1.25, 1.25, 0.15, EAVE)
            hip_roof(b, cx, cy, z + 0.5, 2.4, 1.4, 0.9, ridge=0.3, ridge_beam=False)
            hip_roof(b, cx, cy, z + 0.5, 1.4, 2.4, 0.9, ridge=0.3, ridge_beam=False)
            box(b, cx, cy, z + 1.3, 0.3, 0.3, 0.25, RIDGE)
            prism(b, cx, cy, z + 1.5, 0.12, 0.45, FINIAL)
    b.build()

    g = B("Meridian")
    gate_tower(g, 0, WS - 0.6, 13.0, 3.0, 1.5, 7.2, 2.0, 1.4, double=True)
    for sx in (-1, 1):
        box(g, sx * 5.6, WS - 4.6, FLOOR, 2.4, 8.0, 0.2, GREY_TILE)
        box(g, sx * 5.6, WS - 4.6, FLOOR + 0.2, 2.4, 8.0, 1.3, RED)
        box(g, sx * 5.6, WS - 4.6, FLOOR + 1.5, 2.6, 8.2, 0.14, GREY_TILE)
        corridor(g, sx * 5.6, WS - 4.4, 0.8, 2.8, z0=FLOOR + 1.64, h=0.4)
        pavilion(g, sx * 5.6, WS - 7.9, 1.5, 0.8, z0=FLOOR + 1.64, plat_h=0.1)
        pavilion(g, sx * 5.6, WS - 1.3, 1.5, 0.8, z0=FLOOR + 1.64, plat_h=0.1)
    g.build()
    g = B("Gates")
    gate_tower(g, 0, WN + 0.2, 8.5, 2.8, 1.45, 5.2, 1.9, 1.3)
    gate_tower(g, WX + 0.2, -32.0, 2.8, 6.5, 1.45, 1.8, 4.2, 1.2)
    gate_tower(g, -WX - 0.2, -32.0, 2.8, 6.5, 1.45, 1.8, 4.2, 1.2)
    g.build()

# ----------------------------------------------------------------------------- 中轴线
def central_axis():
    b = B("Axis")
    rv, rf, bv, bf = [], [], [], []
    M = 48
    def yc_of(x):
        return -35.5 - 3.0 * math.cos(math.pi * x / 30)
    for i in range(M + 1):
        x = -15 + 30 * i / M
        yc = yc_of(x)
        hw = 1.1
        rv += [(x, yc - hw, FLOOR + 0.03), (x, yc + hw, FLOOR + 0.03)]
        bv += [(x, yc - hw, FLOOR + 0.16), (x, yc + hw, FLOOR + 0.16)]
        bv += [(x, yc - hw - 0.14, FLOOR + 0.16), (x, yc + hw + 0.14, FLOOR + 0.16)]
        bv += [(x, yc - hw - 0.14, FLOOR), (x, yc + hw + 0.14, FLOOR)]
        bv += [(x, yc - hw, FLOOR), (x, yc + hw, FLOOR)]
    for i in range(M):
        rf.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
        k = 8 * i
        bf.append((k, k + 8, k + 10, k + 2)); bf.append((k + 1, k + 3, k + 11, k + 9))
        bf.append((k + 2, k + 10, k + 12, k + 4)); bf.append((k + 3, k + 5, k + 13, k + 11))
        bf.append((k, k + 6, k + 14, k + 8)); bf.append((k + 1, k + 9, k + 15, k + 7))
    b.add(bv, bf, MARBLE)
    b.add(rv, rf, WATER)
    for x in (-7.5, -3.75, 0, 3.75, 7.5):
        yc = yc_of(x)
        wid = 1.3 if x == 0 else 0.95
        box(b, x, yc, FLOOR, wid, 3.4, 0.4, MARBLE)
        box(b, x, yc, FLOOR + 0.4, wid, 1.2, 0.08, MARBLE)
        balustrade(b, [(x - wid / 2, yc - 1.7), (x - wid / 2, yc + 1.7)], FLOOR + 0.4, step=0.45, closed=False)
        balustrade(b, [(x + wid / 2, yc - 1.7), (x + wid / 2, yc + 1.7)], FLOOR + 0.4, step=0.45, closed=False)
    hall(b, 0, -29.5, 6.0, 2.3, 1.25, plat_h=0.6, plat_pad=0.75, roof_h=1.35)
    hall(b, -10.5, -29.5, 2.2, 1.3, 0.8, plat_h=0.3, plat_pad=0.4, roof_h=0.8)
    hall(b, 10.5, -29.5, 2.2, 1.3, 0.8, plat_h=0.3, plat_pad=0.4, roof_h=0.8)
    for sx in (-1, 1):
        corridor(b, sx * 18.5, -38.5, 1.3, 15.0)
        hall(b, sx * 18.5, -38.5, 1.5, 2.6, 0.9, plat_h=0.3, plat_pad=0.3, stair=False, roof_h=0.9)
        wall(b, sx * 18.5, -46.6, sx * 18.5, -45.3)
        wall(b, sx * 8.0, -29.5, sx * 18.5, -29.5)
    blocks = [(-13, -12.5, 13, 0.0), (-8.0, 0.0, 8.0, 7.5), (-12.5, 7.5, 12.5, 16.0)]
    TH = 0.45
    for tier in range(3):
        pad = 1.3 - 0.55 * tier
        z = FLOOR + TH * tier
        for (x0, y0, x1, y1) in blocks:
            dy = 2 * pad if (y0 == -12.5 or y1 == 16.0) else 0.0
            box(b, (x0 + x1) / 2, (y0 + y1) / 2, z, (x1 - x0) + 2 * pad, (y1 - y0) + dy, TH, MARBLE)
        p = pad + 0.02
        outline = [(-13 - p, -12.5 - p), (13 + p, -12.5 - p), (13 + p, 0), (8 + p, 0), (8 + p, 7.5), (12.5 + p, 7.5),
                   (12.5 + p, 16 + p), (-12.5 - p, 16 + p), (-12.5 - p, 7.5), (-8 - p, 7.5), (-8 - p, 0), (-13 - p, 0)]
        balustrade(b, outline, z + TH, step=0.7,
                   skip=lambda x, y, p=p: abs(x) < 2.0 and (abs(y - (-12.5 - p)) < 0.05 or abs(y - (16 + p)) < 0.05))
        stairs(b, 0, -12.5 - pad, z, 3.8, TH, steps=5, dir=-1)
        stairs(b, 0, 16.0 + pad, z, 3.0, TH, steps=5, dir=1)
    ZT = FLOOR + 3 * TH
    hall(b, 0, -6.5, 6.4, 3.7, 1.7, double=True, plat_h=0.35, plat_pad=0.6, roof_h=1.65, z0=ZT)
    hall(b, 0, 3.8, 2.6, 2.6, 1.1, plat_h=0.2, plat_pad=0.3, pyramid=True, roof_h=1.3, z0=ZT, stair=False)
    hall(b, 0, 11.7, 5.0, 2.9, 1.5, double=True, plat_h=0.35, plat_pad=0.5, roof_h=1.4, z0=ZT)
    for sx in (-1, 1):
        hall(b, sx * 19.5, -7.5, 1.8, 4.4, 1.25, double=True, plat_h=0.35, plat_pad=0.35, stair=False, roof_h=1.0)
        corridor(b, sx * 21.0, -20.0, 1.3, 17.0)
        corridor(b, sx * 21.0, 7.0, 1.3, 18.0)
        hall(b, sx * 21.0, -27.5, 1.6, 1.8, 0.8, plat_h=0.2, plat_pad=0.3, stair=False, roof_h=0.8)
        hall(b, sx * 9.5, 18.3, 1.8, 1.3, 0.8, plat_h=0.25, plat_pad=0.3, roof_h=0.8)
        corridor(b, sx * 15.0, 18.3, 8.0, 1.1)
    hall(b, 0, 18.3, 3.4, 1.5, 1.0, plat_h=0.45, plat_pad=0.5, roof_h=1.0)
    box(b, 0, 28.0, FLOOR, 11.0, 17.0, 0.5, MARBLE)
    box(b, 0, 28.0, FLOOR, 4.6, 19.0, 0.5, MARBLE)
    balustrade(b, [(-5.5, 19.5), (-2.3, 19.5), (-2.3, 18.5), (2.3, 18.5), (2.3, 19.5), (5.5, 19.5), (5.5, 36.5), (2.3, 36.5),
                   (2.3, 37.5), (-2.3, 37.5), (-2.3, 36.5), (-5.5, 36.5)], FLOOR + 0.5, step=0.7,
               skip=lambda x, y: abs(x) < 1.0 and (abs(y - 18.5) < 0.05 or abs(y - 37.5) < 0.05))
    stairs(b, 0, 18.5, FLOOR, 2.4, 0.5, steps=4, dir=-1)
    ZH = FLOOR + 0.5
    hall(b, 0, 23.5, 4.4, 2.5, 1.3, double=True, plat_h=0.2, plat_pad=0.4, roof_h=1.25, z0=ZH)
    hall(b, 0, 28.5, 1.9, 1.9, 0.85, plat_h=0.1, plat_pad=0.25, pyramid=True, roof_h=1.0, z0=ZH, stair=False)
    hall(b, 0, 33.2, 4.4, 2.3, 1.25, double=True, plat_h=0.2, plat_pad=0.4, roof_h=1.2, z0=ZH)
    for sx in (-1, 1):
        corridor(b, sx * 9.0, 28.0, 1.1, 17.0)
        hall(b, sx * 4.3, 23.5, 1.2, 1.1, 0.65, plat_h=0.1, plat_pad=0.2, stair=False, roof_h=0.55, z0=ZH)
    wall(b, -9.0, 37.8, 9.0, 37.8)
    hall(b, 0, 37.8, 2.4, 1.0, 0.75, plat_h=0.2, plat_pad=0.3, roof_h=0.75)
    hall(b, 0, 42.6, 2.8, 1.8, 1.0, plat_h=0.35, plat_pad=0.45, roof_h=1.0)
    wall_ring(b, -3.2, 40.3, 3.2, 45.4, h=0.5, gate=False)
    for sx in (-1, 1):
        pavilion(b, sx * 8.5, 41.5, 1.4, 0.85, plat_h=0.25)
        hall(b, sx * 12.0, 44.8, 2.0, 1.2, 0.75, plat_h=0.2, plat_pad=0.3, stair=False, roof_h=0.75)
    rv, rf = icosphere(10.0, 45.3, FLOOR + 0.3, 1.9, sub=1, squash=0.75)
    rv = [(x, y, max(z, FLOOR)) for (x, y, z) in rv]
    b.add(rv, rf, ROCK)
    pavilion(b, 10.0, 45.3, 0.9, 0.55, z0=FLOOR + 1.6, plat_h=0.08, double=False)
    for _ in range(14):
        bush(b, random.uniform(-13, 13), random.uniform(39.5, 46.5), random.uniform(0.5, 0.8))
    b.build()
    tree_patch(-13.5, 39.3, -4.0, 46.6, 18, (0.7, 1.05))
    tree_patch(4.0, 39.3, 13.5, 46.6, 15, (0.7, 1.05))
    for x in (-5.8, 5.8):
        TREES.append((x, 40.0, 1.1, FLOOR)); TREES.append((x, 44.6, 1.0, FLOOR))

# ----------------------------------------------------------------------------- 东西两翼
def wings():
    b = B("Wings")
    for sx in (-1, 1):
        xa, xb = (sx * 30.0, sx * 16.0) if sx < 0 else (16.0, 30.0)
        wall_ring(b, xa, -28.5, xb, -14.5)
        hall(b, sx * 23.0, -23.5, 3.4, 1.9, 1.05, plat_h=0.35, plat_pad=0.45, roof_h=1.0)
        hall(b, sx * 23.0, -18.8, 2.8, 1.5, 0.85, plat_h=0.25, plat_pad=0.35, roof_h=0.85)
        hall(b, sx * 23.0, -26.8, 1.6, 0.8, 0.55, plat_h=0.1, plat_pad=0.2, roof_h=0.5)
        if sx > 0:
            wall_ring(b, 16.0, -14.5, 30.0, -7.0, gate=False)
            hall(b, 23.0, -10.5, 3.2, 1.7, 1.15, plat_h=0.3, plat_pad=0.4, roof_mat=BLACK_TILE, roof_h=1.0, double=True)
            tree_patch(17.5, -14.0, 28.5, -8.0, 7, (0.6, 0.9))
        else:
            tree_patch(-29.5, -13.5, -16.5, -7.5, 9, (0.6, 0.95))
        for cx in (12.8, 19.2):
            for cy in (22.5, 28.7, 34.9):
                compound(b, sx * cx, cy, 5.8, 5.9, 2.4, 1.35, 0.72)
        if sx < 0:
            wall_ring(b, -18.0, 13.5, -11.0, 20.5)
            hall(b, -14.5, 17.8, 2.8, 1.4, 0.95, plat_h=0.25, plat_pad=0.35, roof_h=0.9)
            wall_ring(b, -24.0, 36.5, -15.0, 46.5, gate=False)
            hall(b, -19.5, 44.0, 2.0, 1.2, 0.8, plat_h=0.2, plat_pad=0.3, roof_h=0.8)
            pavilion(b, -19.5, 39.5, 1.2, 0.75)
            tree_patch(-23.5, 37.0, -15.5, 46.0, 12, (0.6, 1.0))
        else:
            wall_ring(b, 11.0, 12.0, 18.0, 20.5)
            hall(b, 14.5, 17.0, 3.0, 1.7, 1.1, plat_h=0.3, plat_pad=0.4, roof_h=1.0)
            wall_ring(b, 11.0, 2.5, 18.0, 11.5)
            hall(b, 14.5, 7.5, 2.6, 1.4, 0.9, plat_h=0.2, plat_pad=0.35, roof_h=0.85)
            wall_ring(b, 18.5, 2.5, 24.0, 11.5, gate=False)
            hall(b, 21.2, 7.5, 2.2, 1.2, 0.8, plat_h=0.2, plat_pad=0.3, roof_h=0.75)
    wall_ring(b, 25.0, -11.0, 36.0, 44.0, h=0.8, gate=False)
    hall(b, 30.5, -8.5, 2.4, 1.1, 0.8, plat_h=0.2, plat_pad=0.3, roof_h=0.8)
    hall(b, 30.5, -3.0, 2.6, 1.1, 0.8, plat_h=0.2, plat_pad=0.3, roof_h=0.8)
    box(b, 30.5, 6.5, FLOOR, 9.0, 12.0, 0.45, MARBLE)
    hall(b, 30.5, 3.5, 4.0, 2.3, 1.3, double=True, plat_h=0.2, plat_pad=0.4, roof_h=1.2, z0=FLOOR + 0.45)
    hall(b, 30.5, 9.5, 3.6, 1.9, 1.1, plat_h=0.15, plat_pad=0.35, roof_h=1.0, z0=FLOOR + 0.45)
    for cy in (16.0, 22.0, 28.0):
        hall(b, 30.5, cy, 3.4, 1.7, 0.9, plat_h=0.2, plat_pad=0.35, roof_h=0.9)
        corridor(b, 26.5, cy, 0.9, 5.0); corridor(b, 34.5, cy, 0.9, 5.0)
    wall(b, 25.0, 13.0, 36.0, 13.0)
    hall(b, 33.2, 36.0, 2.4, 1.9, 1.6, double=True, plat_h=0.25, plat_pad=0.35, roof_h=1.0)
    hall(b, 33.2, 39.8, 2.2, 1.1, 0.75, plat_h=0.15, plat_pad=0.3, roof_h=0.7)
    pavilion(b, 27.5, 36.5, 1.2, 0.75)
    tree_patch(26.0, 32.0, 31.5, 43.0, 12, (0.6, 1.0))
    wall_ring(b, -33.5, 7.0, -21.5, 18.0, h=0.8)
    hall(b, -27.5, 13.0, 4.4, 2.3, 1.3, double=True, plat_h=0.3, plat_pad=0.45, roof_h=1.2)
    hall(b, -27.5, 8.5, 2.2, 1.0, 0.75, plat_h=0.2, plat_pad=0.3, roof_h=0.7)
    wall_ring(b, -33.5, -4.0, -21.5, 7.0, h=0.6, gate=False)
    tree_patch(-32.5, -3.0, -22.5, 6.0, 16, (0.6, 1.0))
    pavilion(b, -27.5, 1.5, 1.3, 0.75)
    wall_ring(b, -33.5, 18.0, -24.5, 27.0)
    hall(b, -29.0, 23.0, 3.2, 1.7, 1.0, plat_h=0.25, plat_pad=0.35, roof_h=0.9)
    wall_ring(b, -33.5, 27.0, -24.5, 36.0)
    hall(b, -29.0, 32.0, 2.8, 1.5, 0.9, plat_h=0.2, plat_pad=0.35, roof_h=0.85)
    wall_ring(b, -33.5, 36.0, -24.5, 44.0, gate=False)
    hall(b, -29.0, 40.5, 2.6, 1.4, 0.9, plat_h=0.2, plat_pad=0.35, roof_h=0.85)
    tree_patch(-33.0, 37.0, -25.0, 43.5, 8, (0.6, 0.9))
    hall(b, -20.8, 27.5, 1.9, 1.5, 1.0, plat_h=0.2, plat_pad=0.3, roof_h=0.5, double=True, stair=False)
    box(b, -20.8, 27.5, FLOOR + 2.3, 1.3, 1.1, 0.8, BODY)
    box(b, -20.8, 27.5, FLOOR + 2.95, 1.45, 1.25, 0.15, EAVE)
    hip_roof(b, -20.8, 27.5, FLOOR + 3.15, 2.3, 2.1, 0.9, ridge=0.0)
    for sx in (-1, 1):
        for cy in range(-44, 44, 4):
            corridor(b, sx * 35.9, cy + 1.0, 1.1, 3.0, roof_mat=GREY_TILE, h=0.4)
        for cy in (-40.5, -36.5):
            corridor(b, sx * 31.5, cy, 3.8, 1.1, roof_mat=GREY_TILE, h=0.4)
            corridor(b, sx * 25.5, cy, 3.8, 1.1, roof_mat=GREY_TILE, h=0.4)
        for cy in (-44.8, -41.3):
            corridor(b, sx * 13.0, cy, 5.5, 1.1, roof_mat=GREY_TILE, h=0.4)
        for cx in (12.0, 17.0, 22.0):
            corridor(b, sx * cx, 40.0, 2.8, 1.0, roof_mat=GREY_TILE, h=0.4)
            corridor(b, sx * cx, 44.0, 2.8, 1.0, roof_mat=GREY_TILE, h=0.4)
    b.build()

def outside_greenery():
    x0, y0, x1, y1 = ISL
    X0, Y0, X1, Y1 = MOAT_OUT
    b = B("Bushes")
    def ok(x, y):
        if X0 - 1.0 < x < X1 + 1.0 and Y0 - 1.0 < y < Y1 + 1.0:
            return False
        if abs(x) < 8.5 and y < Y0:            # 桥南广场
            return False
        if abs(x) < 21.0 and y > HILL_C[1] - 11.5:   # 景山范围
            return False
        if abs(x) < 1.5 and y > Y1:            # 北面御道
            return False
        return True
    n = 0
    while n < 260:
        x, y = random.uniform(x0 + 1.0, x1 - 1.0), random.uniform(y0 + 1.0, y1 - 1.0)
        if not ok(x, y):
            continue
        TREES.append((x, y, random.uniform(0.75, 1.3), 0.0))
        n += 1
    for _ in range(160):
        x, y = random.uniform(x0 + 0.6, x1 - 0.6), random.uniform(y0 + 0.6, y1 - 0.6)
        if ok(x, y):
            bush(b, x, y, random.uniform(0.5, 0.9), z0=0.0)
    for y in range(int(Y0) - 4, int(y0) + 3, -3):
        for sx in (-1, 1):
            TREES.append((sx * 9.5 + random.uniform(-0.3, 0.3), y + random.uniform(-0.4, 0.4), random.uniform(0.9, 1.2), 0.0))
    b.build()

# ----------------------------------------------------------------------------- 相机 / 灯光 / 世界
def setup_camera_lights():
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 48
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("Camera", cam_data)
    COL.objects.link(cam)
    target = (0.0, 0.0, -8.0)
    az = math.radians(33)
    dist = 212.0
    pitch = math.radians(37)
    hx, hy = math.sin(az), -math.cos(az)
    cam.location = (target[0] + hx * dist * math.cos(pitch), target[1] + hy * dist * math.cos(pitch),
                    target[2] + dist * math.sin(pitch))
    direction = mathutils.Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    focus = bpy.data.objects.new("Focus", None)
    focus.location = (0, -6.0, 2.5)
    COL.objects.link(focus)
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = focus
    cam_data.dof.aperture_fstop = 1.0

    sun_data = bpy.data.lights.new("Sun", 'SUN')
    sun_data.energy = 2.5
    sun_data.color = (1.0, 0.91, 0.76)
    sun_data.angle = math.radians(2.2)
    sun = bpy.data.objects.new("Sun", sun_data)
    COL.objects.link(sun)
    sun.rotation_euler = mathutils.Euler((math.radians(58), 0, math.radians(312)), 'XYZ')  # 西南偏南、仰角 32°

    if "--sunonly" in argv:
        sun_data.energy = 1.6
    if "--nosun" in argv:
        sun_data.energy = 0.0
    fill_data = bpy.data.lights.new("Fill", 'AREA')
    fill_data.energy = 600
    fill_data.size = 140
    fill_data.color = (0.80, 0.88, 1.0)
    fill = bpy.data.objects.new("Fill", fill_data)
    COL.objects.link(fill)
    fill.location = (-140, 60, 130)
    d = mathutils.Vector((0, 0, 0)) - fill.location
    fill.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    if "--sunonly" in argv:
        fill_data.energy = 0.0

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.82, 0.88, 1.0, 1)
    bg.inputs["Strength"].default_value = 0.03 if "--sunonly" in argv else 0.3

    # 米色纯净背景：只对相机可见、不参与照明的自发光背板
    bd = principled("Backdrop", (1, 1, 1), rough=1.0, bevel=0)
    nt = bd.node_tree
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    grad = nt.nodes.new("ShaderNodeTexGradient")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(90))
    mp.inputs["Scale"].default_value = (1.0 / 900.0, 1, 1)
    mp.inputs["Location"].default_value = (0.55, 0, 0)
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.90, 0.85, 0.72, 1)
    ramp.color_ramp.elements[1].color = (0.94, 0.90, 0.79, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    me = bpy.data.meshes.new("Backdrop")
    S = 1600.0
    me.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    me.materials.append(bd)
    plane = bpy.data.objects.new("Backdrop", me)
    COL.objects.link(plane)
    view_dir = (mathutils.Vector(target) - cam.location).normalized()
    plane.location = cam.location + view_dir * 700.0
    plane.rotation_euler = view_dir.to_track_quat('Z', 'Y').to_euler()
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow"):
        if hasattr(plane, attr):
            setattr(plane, attr, False)

def setup_render():
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 3
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.render.resolution_x = 2048
    scene.render.resolution_y = 1792
    scene.render.resolution_percentage = PCT
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.filepath = OUT
    scene.render.use_persistent_data = True
    vs = scene.view_settings
    vs.view_transform = 'Standard'
    vs.look = 'None'
    vs.exposure = 0.2
    scene.render.filter_size = 1.6
    vs.gamma = 1.0
    print(f"[fc] view={vs.view_transform} look={vs.look} exposure={vs.exposure}")
    scene.render.film_transparent = False
    if "--border" in argv:
        i = argv.index("--border")
        x0, y0, x1, y1 = (float(v) for v in argv[i + 1:i + 5])
        scene.render.use_border = True
        scene.render.use_crop_to_border = True
        scene.render.border_min_x, scene.render.border_min_y = x0, y0
        scene.render.border_max_x, scene.render.border_max_y = x1, y1

# ----------------------------------------------------------------------------- 执行
t0 = time.time()
island()
ground()
city_wall()
central_axis()
wings()
jingshan()
outside_greenery()
for (x, y, s, z0) in TREES:
    tree_obj(x, y, s, z0)
setup_camera_lights()
setup_render()
print(f"[fc] scene built in {time.time() - t0:.1f}s, objects={len(COL.objects)}, trees={len(TREES)}")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
if SAVE_BLEND:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.splitext(OUT)[0] + ".blend")
t1 = time.time()
bpy.ops.render.render(write_still=True)
print(f"[fc] rendered {OUT} in {time.time() - t1:.1f}s ({PCT}% / {SAMPLES} spp)")
