# -*- coding: utf-8 -*-
"""
武汉黄鹤楼微缩立体模型（沙盘）— 过程化生成 + Cycles 渲染（Blender 5.x, headless）

用法：
  "D:/install/blender/blender.exe" --background --python yellow-crane/build_yellow_crane.py -- \
      [--pct 100] [--samples 128] [--out yellow-crane/output/yellow_crane/yellow_crane.png] [--save] [--nomist]
      [--sunonly] [--border x0 y0 x1 y1]

单位：1 个 Blender 单位 ≈ 12 米。y 轴正方向为北，x 轴正方向为东。江面 z = 0。
"""
import bpy, math, random, sys, time, os
import glob as _glob
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
TEX_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "textures_cc0"))   # ambientCG CC0 贴图（各沙盘共用）
OUT = os.path.abspath(arg("--out", os.path.join(HERE, "output", "yellow_crane", "yellow_crane.png")))
SAVE_BLEND = "--save" in argv
NOMIST = "--nomist" in argv
WEB = "--export-glb" in argv          # 网页导出模式：树木只记录实例数据，不加载模型
PLANTS = []                           # [kind, variant, x, y, z, height, rot]
random.seed(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = bpy.data.collections.new("YellowCrane")
scene.collection.children.link(COL)

# ----------------------------------------------------------------------------- 材质工具
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

def tex_image(folder, kind, noncolor=True):
    path = _glob.glob(os.path.join(TEX_DIR, folder, f"*_{kind}.jpg"))[0]
    im = bpy.data.images.load(path, check_existing=True)
    if noncolor:
        im.colorspace_settings.name = 'Non-Color'
    return im

def texcoord(nt):
    tc = nt.nodes.get("TexCoordShared") or nt.nodes.new("ShaderNodeTexCoord")
    tc.name = "TexCoordShared"
    return tc

def tex_node(nt, folder, kind, scale, coord, noncolor=True, box=True):
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = tex_image(folder, kind, noncolor)
    t.projection = 'BOX' if (box and coord == 'Object') else 'FLAT'
    t.projection_blend = 0.3
    tc = texcoord(nt)
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs[coord], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
    return t

def base_normal(nt):
    n = nt.nodes.get("EdgeBevel")
    return n.outputs["Normal"] if n else None

def bump_node(nt, height_socket, strength, distance, prev_normal=None):
    """Bump 节点；prev_normal 为上一级法线（串联），否则接 Bevel 法线。"""
    bn = nt.nodes.new("ShaderNodeBump")
    bn.inputs["Strength"].default_value = strength
    bn.inputs["Distance"].default_value = distance
    nt.links.new(height_socket, bn.inputs["Height"])
    src = prev_normal if prev_normal is not None else base_normal(nt)
    if src is not None:
        nt.links.new(src, bn.inputs["Normal"])
    return bn

def tex_bump(nt, disp_node, strength, distance, prev_normal=None):
    pbs = nt.nodes["Principled BSDF"]
    bn = bump_node(nt, disp_node.outputs["Color"], strength, distance, prev_normal)
    nt.links.new(bn.outputs["Normal"], pbs.inputs["Normal"])
    return bn

def map_range(nt, socket, lo, hi, fmin=0.0, fmax=1.0):
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = fmin
    mr.inputs["From Max"].default_value = fmax
    mr.inputs["To Min"].default_value = lo
    mr.inputs["To Max"].default_value = hi
    nt.links.new(socket, mr.inputs["Value"])
    return mr.outputs["Result"]

def mix_rgb(nt, a, b, fac=1.0, blend='MULTIPLY'):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = 'RGBA'; m.blend_type = blend
    if isinstance(fac, (int, float)):
        m.inputs["Factor"].default_value = fac
    else:
        nt.links.new(fac, m.inputs["Factor"])
    nt.links.new(a, m.inputs[6]); nt.links.new(b, m.inputs[7])
    return m.outputs[2]

def mul_color(nt, a, b, fac=1.0):
    return mix_rgb(nt, a, b, fac, 'MULTIPLY')

def rgb(nt, c):
    n = nt.nodes.new("ShaderNodeRGB")
    n.outputs[0].default_value = (*c, 1)
    return n.outputs[0]

def noise(nt, scale, detail=4.0, coord="Object", distortion=0.0):
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    if "Distortion" in n.inputs:
        n.inputs["Distortion"].default_value = distortion
    nt.links.new(texcoord(nt).outputs[coord], n.inputs["Vector"])
    return n

def ramp(nt, stops):
    """stops: [(pos, (r,g,b)), ...]"""
    r = nt.nodes.new("ShaderNodeValToRGB")
    cr = r.color_ramp
    cr.elements[0].position = stops[0][0]; cr.elements[0].color = (*stops[0][1], 1)
    cr.elements[1].position = stops[-1][0]; cr.elements[1].color = (*stops[-1][1], 1)
    for pos, c in stops[1:-1]:
        e = cr.elements.new(pos); e.color = (*c, 1)
    return r

def noise_mix(mat, c1, c2, scale, detail=4.0, bump=0.0, coord="Object"):
    nt = mat.node_tree
    p = nt.nodes["Principled BSDF"]
    n = noise(nt, scale, detail, coord)
    r = ramp(nt, [(0.3, c1), (0.7, c2)])
    nt.links.new(n.outputs["Fac"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], p.inputs["Base Color"])
    if bump > 0:
        bn = bump_node(nt, n.outputs["Fac"], bump, 0.1)
        nt.links.new(bn.outputs["Normal"], p.inputs["Normal"])
    return mat

def tile_material(name, c1, c2, rough=0.3, coat=0.5, sc=0.38):
    """瓦顶：RoofingTiles014A 位移/粗糙度提供筒瓦起伏，颜色按 c1~c2 染色；屋面 UV 让瓦垄顺坡。"""
    m = principled(name, c1, rough=rough, coat=coat)
    nt = m.node_tree
    pbs = nt.nodes["Principled BSDF"]
    col = tex_node(nt, "RoofingTiles014A", "Color", sc, 'UV', noncolor=False)
    disp = tex_node(nt, "RoofingTiles014A", "Displacement", sc, 'UV')
    rgh = tex_node(nt, "RoofingTiles014A", "Roughness", sc, 'UV')
    ao = tex_node(nt, "RoofingTiles014A", "AmbientOcclusion", sc, 'UV')
    bw = nt.nodes.new("ShaderNodeRGBToBW")
    nt.links.new(col.outputs["Color"], bw.inputs["Color"])
    shade = map_range(nt, bw.outputs["Val"], 0.7, 1.3)
    nz = noise(nt, 5.0, 4.0)
    r = ramp(nt, [(0.3, c1), (0.7, c2)])
    nt.links.new(nz.outputs["Fac"], r.inputs["Fac"])
    c = mul_color(nt, r.outputs["Color"], shade)
    c = mul_color(nt, c, ao.outputs["Color"], 0.6)
    nt.links.new(c, pbs.inputs["Base Color"])
    nt.links.new(map_range(nt, rgh.outputs["Color"], rough * 0.6, rough * 1.5), pbs.inputs["Roughness"])
    tex_bump(nt, disp, 1.0, 0.1)
    return m

def leaf_material(name, c1, c2, sss=0.12, bump=0.9):
    m = principled(name, c1, rough=0.9, bevel=0)
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    if sss > 0 and "Subsurface Weight" in p.inputs:
        p.inputs["Subsurface Weight"].default_value = sss
        p.inputs["Subsurface Radius"].default_value = (0.3, 0.5, 0.1)
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    r = ramp(nt, [(0.0, c1), (1.0, c2)])
    nt.links.new(oi.outputs["Random"], r.inputs["Fac"])
    nt.links.new(r.outputs["Color"], p.inputs["Base Color"])
    n2 = noise(nt, 28.0, 6.0)
    bn = bump_node(nt, n2.outputs["Fac"], bump, 0.08)
    nt.links.new(bn.outputs["Normal"], p.inputs["Normal"])
    return m

# ----------------------------------------------------------------------------- 材质
# 粉墙黛瓦：江南建筑
DARK_TILE = tile_material("DaiWa", (0.15, 0.16, 0.18), (0.27, 0.28, 0.30), rough=0.55, coat=0.15)
BRONZE_TILE = tile_material("BronzeTile", (0.30, 0.23, 0.13), (0.44, 0.35, 0.20), rough=0.45, coat=0.3)
WHITE_WALL = noise_mix(principled("FenQiang", (0.86, 0.85, 0.79), rough=0.85), (0.78, 0.77, 0.71), (0.90, 0.89, 0.84), 3.0, bump=0.15)
YELLOW_WALL = noise_mix(principled("HuangQiang", (0.80, 0.56, 0.20), rough=0.85), (0.72, 0.48, 0.16), (0.88, 0.66, 0.28), 3.0, bump=0.15)
RED_WALL = noise_mix(principled("ZhuQiang", (0.55, 0.12, 0.08), rough=0.8), (0.48, 0.10, 0.07), (0.62, 0.16, 0.10), 3.0)
WOOD = principled("Wood", (0.30, 0.17, 0.09), rough=0.55, coat=0.15)
COLUMN = principled("Column", (0.42, 0.11, 0.07), rough=0.5, coat=0.2)
LATTICE = principled("Lattice", (0.22, 0.13, 0.07), rough=0.5)
RIDGE = principled("Ridge", (0.11, 0.11, 0.12), rough=0.6)
FINIAL = principled("Finial", (1.0, 0.78, 0.25), rough=0.25, metal=1.0)
GRANITE = noise_mix(principled("Granite", (0.50, 0.50, 0.47), rough=0.8, bevel=0.05), (0.42, 0.42, 0.40), (0.60, 0.60, 0.57), 40.0, detail=6.0, bump=0.3)
BRICK = noise_mix(principled("Brick", (0.46, 0.28, 0.17), rough=0.85), (0.40, 0.24, 0.14), (0.54, 0.34, 0.21), 12.0, bump=0.2)
GREYBRICK = noise_mix(principled("GreyBrick", (0.40, 0.37, 0.33), rough=0.9), (0.34, 0.31, 0.28), (0.47, 0.44, 0.39), 12.0, bump=0.2)
TRUNK = principled("Trunk", (0.22, 0.14, 0.08), rough=0.9)
BOAT_WOOD = principled("BoatWood", (0.36, 0.22, 0.12), rough=0.5, coat=0.2)
BOAT_DECK = principled("BoatDeck", (0.58, 0.46, 0.30), rough=0.6)
BOAT_RED = principled("BoatRed", (0.55, 0.14, 0.10), rough=0.5, coat=0.2)

LEAF = leaf_material("Leaf", (0.13, 0.33, 0.12), (0.30, 0.48, 0.18), sss=0)
WILLOW = leaf_material("WillowLeaf", (0.38, 0.55, 0.19), (0.58, 0.70, 0.30), sss=0)
PINE = leaf_material("PineLeaf", (0.08, 0.24, 0.16), (0.20, 0.40, 0.26), sss=0)
PEACH = leaf_material("PeachBlossom", (0.92, 0.50, 0.58), (0.98, 0.74, 0.80), sss=0)
LOTUS_LEAF = leaf_material("LotusLeaf", (0.16, 0.40, 0.20), (0.27, 0.52, 0.27), sss=0, bump=0.4)
LOTUS_FLOWER = principled("LotusFlower", (0.98, 0.78, 0.85), rough=0.7, bevel=0)

# 青石板路（PavingStones128）
STONE = principled("StonePaving", (0.56, 0.55, 0.52), rough=0.9)
nt = STONE.node_tree
_c = tex_node(nt, "PavingStones128", "Color", 0.7, 'Object', noncolor=False)
_r = tex_node(nt, "PavingStones128", "Roughness", 0.7, 'Object')
_d = tex_node(nt, "PavingStones128", "Displacement", 0.7, 'Object')
_a = tex_node(nt, "PavingStones128", "AmbientOcclusion", 0.7, 'Object')
_col = mul_color(nt, _c.outputs["Color"], _a.outputs["Color"], 0.6)
_col = mul_color(nt, _col, rgb(nt, (1.05, 1.05, 1.02)))
nt.links.new(_col, nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.6, 0.95), nt.nodes["Principled BSDF"].inputs["Roughness"])
tex_bump(nt, _d, 0.7, 0.04)

# 草地（堤岸、岛上）
LAWN = principled("Lawn", (0.33, 0.46, 0.17), rough=0.95, bevel=0)
nt = LAWN.node_tree
_c = tex_node(nt, "Grass004", "Color", 0.9, 'Object', noncolor=False)
_d = tex_node(nt, "Grass004", "Displacement", 0.9, 'Object')
_n = noise(nt, 0.3, 3.0)
_rp = ramp(nt, [(0.3, (0.82, 0.80, 0.50)), (0.7, (1.05, 0.98, 0.72))])
nt.links.new(_n.outputs["Fac"], _rp.inputs["Fac"])
nt.links.new(mul_color(nt, _c.outputs["Color"], _rp.outputs["Color"]), nt.nodes["Principled BSDF"].inputs["Base Color"])
tex_bump(nt, _d, 0.9, 0.06)

# 地形：低处草地贴图，高处青绿山体（按高度渐变）、陡坡露岩
TERRAIN = principled("Terrain", (0.35, 0.48, 0.22), rough=0.95, bevel=0)
nt = TERRAIN.node_tree
_p = nt.nodes["Principled BSDF"]
_gc = tex_node(nt, "Grass004", "Color", 0.8, 'Object', noncolor=False)
_gd = tex_node(nt, "Grass004", "Displacement", 0.8, 'Object')
_sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(texcoord(nt).outputs["Object"], _sep.inputs["Vector"])
_n1 = noise(nt, 0.35, 3.0)
_lawn_tint = ramp(nt, [(0.3, (0.86, 0.84, 0.54)), (0.7, (1.08, 1.02, 0.76))])
nt.links.new(_n1.outputs["Fac"], _lawn_tint.inputs["Fac"])
_grass_col = mul_color(nt, _gc.outputs["Color"], _lawn_tint.outputs["Color"])
_hr = ramp(nt, [(0.0, (0.20, 0.30, 0.14)), (0.4, (0.18, 0.28, 0.15)), (1.0, (0.20, 0.27, 0.16))])
nt.links.new(map_range(nt, _sep.outputs["Z"], 0.0, 1.0, 1.5, 22.0), _hr.inputs["Fac"])
_mn = noise(nt, 0.25, 5.0)
_mount_col = mul_color(nt, _hr.outputs["Color"], map_range(nt, _mn.outputs["Fac"], 0.72, 1.22))
_geo = nt.nodes.new("ShaderNodeNewGeometry")
_nsep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(_geo.outputs["Normal"], _nsep.inputs["Vector"])
_slope = map_range(nt, _nsep.outputs["Z"], 1.0, 0.0, 0.22, 0.45)
_rock_col = mul_color(nt, rgb(nt, (0.40, 0.40, 0.37)), map_range(nt, _mn.outputs["Fac"], 0.8, 1.15))
_mcol = mix_rgb(nt, _mount_col, _rock_col, _slope, 'MIX')
_zf = map_range(nt, _sep.outputs["Z"], 0.0, 1.0, 0.9, 3.4)
_fac = mix_rgb(nt, _grass_col, _mcol, _zf, 'MIX')
nt.links.new(_fac, _p.inputs["Base Color"])
_mbump = noise(nt, 1.2, 6.0)
_bn2 = bump_node(nt, _mbump.outputs["Fac"], 0.45, 0.6)
tex_bump(nt, _gd, 0.6, 0.06, prev_normal=_bn2.outputs["Normal"])

# 湖床：浅处沙色，深处墨绿
LAKEBED = principled("LakeBed", (0.30, 0.42, 0.30), rough=0.9, bevel=0)
nt = LAKEBED.node_tree
_sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(texcoord(nt).outputs["Object"], _sep.inputs["Vector"])
_br = ramp(nt, [(0.0, (0.22, 0.17, 0.11)), (0.6, (0.34, 0.27, 0.18)), (1.0, (0.44, 0.37, 0.26))])
nt.links.new(map_range(nt, _sep.outputs["Z"], 0.0, 1.0, -1.8, -0.1), _br.inputs["Fac"])
_bn = noise(nt, 0.5, 4.0)
nt.links.new(mul_color(nt, _br.outputs["Color"], map_range(nt, _bn.outputs["Fac"], 0.8, 1.15)), nt.nodes["Principled BSDF"].inputs["Base Color"])
_bd = tex_node(nt, "Grass004", "Displacement", 0.6, 'Object')
tex_bump(nt, _bd, 0.5, 0.08)

# 湖水：透射 + 多层波纹；阴影光线按透明处理（否则湖底一片死黑）
WATER = principled("RiverWater", (0.56, 0.47, 0.32), rough=0.035, spec=0.6, bevel=0)
nt = WATER.node_tree
_p = nt.nodes["Principled BSDF"]
if "Transmission Weight" in _p.inputs:
    _p.inputs["Transmission Weight"].default_value = 0.55
_p.inputs["IOR"].default_value = 1.33
_w1 = noise(nt, 0.9, 5.0, distortion=0.4)
_b1 = bump_node(nt, _w1.outputs["Fac"], 0.16, 0.25)
_w2 = noise(nt, 7.0, 3.0)
_b2 = bump_node(nt, _w2.outputs["Fac"], 0.05, 0.05, prev_normal=_b1.outputs["Normal"])
_wave = nt.nodes.new("ShaderNodeTexWave")
_wave.wave_type = 'BANDS'; _wave.bands_direction = 'DIAGONAL'
_wave.inputs["Scale"].default_value = 0.3
_wave.inputs["Distortion"].default_value = 7.0
_wave.inputs["Detail"].default_value = 2.0
nt.links.new(texcoord(nt).outputs["Object"], _wave.inputs["Vector"])
_b3 = bump_node(nt, _wave.outputs["Fac"], 0.10, 0.15, prev_normal=_b2.outputs["Normal"])
nt.links.new(_b3.outputs["Normal"], _p.inputs["Normal"])
_lp = nt.nodes.new("ShaderNodeLightPath")
_tr = nt.nodes.new("ShaderNodeBsdfTransparent")
_tr.inputs["Color"].default_value = (0.85, 0.95, 0.92, 1)
_mix = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(_lp.outputs["Is Shadow Ray"], _mix.inputs[0])
nt.links.new(_p.outputs["BSDF"], _mix.inputs[1])
nt.links.new(_tr.outputs["BSDF"], _mix.inputs[2])
nt.links.new(_mix.outputs["Shader"], nt.nodes["Material Output"].inputs["Surface"])

# 地形切面：Rock051 层状岩 + 高度分层染色 + 裂缝
EARTH = principled("EarthCut", (0.40, 0.29, 0.19), rough=0.95, bevel=0)
nt = EARTH.node_tree
_p = nt.nodes["Principled BSDF"]
_c = tex_node(nt, "Rock051", "Color", 0.14, 'Object', noncolor=False)
_r = tex_node(nt, "Rock051", "Roughness", 0.14, 'Object')
_d = tex_node(nt, "Rock051", "Displacement", 0.14, 'Object')
_wv = nt.nodes.new("ShaderNodeTexWave")
_wv.wave_type = 'BANDS'; _wv.bands_direction = 'Z'
_wv.inputs["Scale"].default_value = 0.4
_wv.inputs["Distortion"].default_value = 4.0
_wv.inputs["Detail"].default_value = 3.0
nt.links.new(texcoord(nt).outputs["Object"], _wv.inputs["Vector"])
_er = ramp(nt, [(0.15, (1.7, 1.45, 1.1)), (0.5, (2.6, 2.3, 1.8)), (0.85, (3.2, 2.9, 2.4))])
nt.links.new(_wv.outputs["Fac"], _er.inputs["Fac"])
nt.links.new(mul_color(nt, _c.outputs["Color"], _er.outputs["Color"]), _p.inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.7, 1.0), _p.inputs["Roughness"])
_cr = nt.nodes.new("ShaderNodeTexVoronoi")
_cr.feature = 'DISTANCE_TO_EDGE'
_cr.inputs["Scale"].default_value = 0.3
nt.links.new(texcoord(nt).outputs["Object"], _cr.inputs["Vector"])
_crr = ramp(nt, [(0.0, (0, 0, 0)), (0.12, (1, 1, 1))])
nt.links.new(_cr.outputs["Distance"], _crr.inputs["Fac"])
_cb = bump_node(nt, _crr.outputs["Color"], 0.8, 0.8)
tex_bump(nt, _d, 1.2, 0.5, prev_normal=_cb.outputs["Normal"])
# 远景空气透视：按视距把表面向雾色混合（只对相机光线生效，比体积雾便宜得多）
def add_fog(mat, near=240.0, far=460.0, maxf=0.12, color=(0.92, 0.88, 0.78)):
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) or nt.nodes.get("Material Output")
    if out is None:
        return
    link = next((l for l in nt.links if l.to_node == out and l.to_socket.name == "Surface"), None)
    if link is None:
        return
    src = link.from_socket
    nt.links.remove(link)
    cam = nt.nodes.new("ShaderNodeCameraData")
    fac = map_range(nt, cam.outputs["View Distance"], 0.0, maxf, near, far)
    lp = nt.nodes.new("ShaderNodeLightPath")
    mul = nt.nodes.new("ShaderNodeMath"); mul.operation = 'MULTIPLY'
    nt.links.new(fac, mul.inputs[0]); nt.links.new(lp.outputs["Is Camera Ray"], mul.inputs[1])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = 0.75
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(mul.outputs[0], mx.inputs[0])
    nt.links.new(src, mx.inputs[1])
    nt.links.new(em.outputs["Emission"], mx.inputs[2])
    nt.links.new(mx.outputs["Shader"], out.inputs["Surface"])

for _m in list(bpy.data.materials):
    add_fog(_m)

# ----------------------------------------------------------------------------- 网格构建器
class MeshB:
    def __init__(self, name):
        self.name, self.v, self.f, self.m, self.mats = name, [], [], [], []
        self.uv = []
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
B = MeshB

def box_geo(cx, cy, z0, w, d, h):
    hw, hd, z1 = w / 2, d / 2, z0 + h
    v = [(cx - hw, cy - hd, z0), (cx + hw, cy - hd, z0), (cx + hw, cy + hd, z0), (cx - hw, cy + hd, z0),
         (cx - hw, cy - hd, z1), (cx + hw, cy - hd, z1), (cx + hw, cy + hd, z1), (cx - hw, cy + hd, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f

def box(b, cx, cy, z0, w, d, h, mat):
    v, f = box_geo(cx, cy, z0, w, d, h)
    b.add(v, f, mat)

def rbox(b, cx, cy, z0, w, d, h, mat, ang):
    """绕 (cx, cy) 旋转 ang 的长方体。"""
    v, f = box_geo(0, 0, z0, w, d, h)
    c, s = math.cos(ang), math.sin(ang)
    v = [(cx + x * c - y * s, cy + x * s + y * c, z) for (x, y, z) in v]
    b.add(v, f, mat)

def prism(b, cx, cy, z0, r, h, mat, n=8, phase=0.0):
    v = [(cx + r * math.cos(2 * math.pi * i / n + phase), cy + r * math.sin(2 * math.pi * i / n + phase), z0) for i in range(n)]
    v += [(x, y, z0 + h) for (x, y, _) in v]
    f = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    f.append(tuple(range(n, 2 * n)))
    f.append(tuple(reversed(range(n))))
    b.add(v, f, mat)

def _face_uv(verts, face):
    a, b2, c = (mathutils.Vector(verts[i]) for i in face[:3])
    nv = (b2 - a).cross(c - a)
    use_y = abs(nv.x) > abs(nv.y)
    return [((verts[i][1] if use_y else verts[i][0]), verts[i][2] * 1.7) for i in face]

def cone(b, cx, cy, z0, r0, r1, h, mat, n=8, phase=0.0, uv=True):
    """圆台（r0 底半径，r1 顶半径）。"""
    v = [(cx + r0 * math.cos(2 * math.pi * i / n + phase), cy + r0 * math.sin(2 * math.pi * i / n + phase), z0) for i in range(n)]
    v += [(cx + r1 * math.cos(2 * math.pi * i / n + phase), cy + r1 * math.sin(2 * math.pi * i / n + phase), z0 + h) for i in range(n)]
    f = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    f.append(tuple(range(n, 2 * n)))
    f.append(tuple(reversed(range(n))))
    b.add(v, f, mat, uvs=[_face_uv(v, ff) for ff in f] if uv else None)

def rod(b, p0, p1, t, mat, lift=0.0):
    p0, p1 = mathutils.Vector(p0), mathutils.Vector(p1)
    d = (p1 - p0).normalized()
    up = mathutils.Vector((0, 0, 1))
    side = d.cross(up)
    if side.length < 1e-4:
        side = mathutils.Vector((1, 0, 0))
    side.normalize()
    nv = side.cross(d).normalized()
    if nv.z < 0:
        nv = -nv
    v = []
    for p in (p0, p1):
        base = p + nv * lift
        v += [tuple(base - side * t), tuple(base + side * t), tuple(base + side * t + nv * (t * 1.6)),
              tuple(base - side * t + nv * (t * 1.6))]
    f = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    b.add(v, f, mat)

def disc(b, cx, cy, z, r, mat, n=9, tilt=(0.0, 0.0), dip=0.0):
    v = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n),
          z + tilt[0] * r * math.cos(2 * math.pi * i / n) + tilt[1] * r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    v.append((cx, cy, z - dip))
    f = [(i, (i + 1) % n, n) for i in range(n)]
    b.add(v, f, mat)

def _shell(b, top, faces, loop_n, mat, t=0.12):
    """把屋面（顶点列表 top，前 loop_n 个为檐口环）加厚成壳体。"""
    bot = [(x, y, z - t) for (x, y, z) in top]
    n = len(top)
    fs = list(faces)
    fs += [tuple(n + i for i in reversed(f)) for f in faces]
    for i in range(loop_n):
        j = (i + 1) % loop_n
        fs.append((i, n + i, n + j, j))
    allv = top + bot
    b.add(allv, fs, mat, uvs=[_face_uv(allv, f) for f in fs])

def eave_loop(w, d, z, curl):
    hw, hd = w / 2, d / 2
    return [(-hw, -hd, z + curl), (0, -hd, z), (hw, -hd, z + curl), (hw, 0, z),
            (hw, hd, z + curl), (0, hd, z), (-hw, hd, z + curl), (-hw, 0, z)]

def hip_roof(b, cx, cy, z, w, d, h, mat=DARK_TILE, ridge=0.6, curl=0.18, ridge_beam=True):
    outer = [(x + cx, y + cy, zz) for (x, y, zz) in eave_loop(w, d, z, curl)]
    rw = w / 2 * ridge
    upper = [(cx - rw, cy, z + h), (cx + rw, cy, z + h)]
    faces = [(0, 1, 8), (1, 2, 9), (2, 3, 9), (3, 4, 9), (4, 5, 9), (5, 6, 8), (6, 7, 8), (7, 0, 8)]
    if rw > 1e-6:
        faces += [(1, 9, 8), (5, 8, 9)]
    _shell(b, outer + upper, faces, 8, mat)
    rt = 0.04 + 0.01 * h
    for ci, ui in ((0, 0), (6, 0), (2, 1), (4, 1)):
        rod(b, outer[ci], upper[ui], rt, RIDGE, lift=0.01)
    if ridge_beam:
        if rw > 1e-6:
            box(b, cx, cy, z + h - 0.05, rw * 2 + 0.2, 0.16, 0.16, RIDGE)
            box(b, cx - rw - 0.08, cy, z + h + 0.08, 0.18, 0.18, 0.2, RIDGE)
            box(b, cx + rw + 0.08, cy, z + h + 0.08, 0.18, 0.18, 0.2, RIDGE)
        else:
            prism(b, cx, cy, z + h - 0.05, 0.12, 0.45, FINIAL, n=6)

def skirt_roof(b, cx, cy, z, w, d, inset, rise, mat=DARK_TILE, curl=0.18):
    outer = [(x + cx, y + cy, zz) for (x, y, zz) in eave_loop(w, d, z, curl)]
    wi, di = w / 2 - inset, d / 2 - inset
    upper = [(cx - wi, cy - di, z + rise), (cx + wi, cy - di, z + rise),
             (cx + wi, cy + di, z + rise), (cx - wi, cy + di, z + rise)]
    faces = [(0, 1, 8), (1, 2, 9), (1, 9, 8), (2, 3, 9), (3, 4, 10), (3, 10, 9),
             (4, 5, 10), (5, 6, 11), (5, 11, 10), (6, 7, 11), (7, 0, 8), (7, 8, 11)]
    _shell(b, outer + upper, faces, 8, mat)
    for ci, ui in ((0, 0), (2, 1), (4, 2), (6, 3)):
        rod(b, outer[ci], upper[ui], 0.04, RIDGE, lift=0.01)

def poly_roof(b, cx, cy, z, r, h, n, mat=DARK_TILE, curl=0.16, finial=True, phase=0.0):
    """n 角攒尖顶：檐角翘起，中间下垂，顶上宝顶。"""
    pts = []
    for i in range(n):
        a0 = 2 * math.pi * i / n + phase
        a1 = 2 * math.pi * (i + 0.5) / n + phase
        pts.append((cx + r * math.cos(a0), cy + r * math.sin(a0), z + curl))
        rin = r * math.cos(math.pi / n)
        pts.append((cx + rin * math.cos(a1), cy + rin * math.sin(a1), z))
    m = 2 * n
    top = pts + [(cx, cy, z + h)]
    faces = [(i, (i + 1) % m, m) for i in range(m)]
    _shell(b, top, faces, m, mat)
    for i in range(n):
        rod(b, pts[2 * i], (cx, cy, z + h), 0.035, RIDGE, lift=0.01)
    if finial:
        prism(b, cx, cy, z + h - 0.05, 0.1, 0.4, FINIAL, n=6)

def rail(b, pts, z, step=0.7, closed=True, mat=GRANITE, post=0.28):
    n = len(pts)
    segs = range(n) if closed else range(n - 1)
    for i in segs:
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        k = max(1, int(L / step))
        for j in range(k + 1):
            t = j / k
            box(b, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z, 0.09, 0.09, post, mat)
        rod(b, (x0, y0, z + post * 0.75), (x1, y1, z + post * 0.75), 0.035, mat)

def stairs(b, cx, cy, z0, w, h, steps=3, dir=-1):
    for i in range(steps):
        hh = h * (steps - i) / steps
        box(b, cx, cy + dir * (0.22 * i + 0.11), z0, w, 0.24, hh, GRANITE)
# ----------------------------------------------------------------------------- 噪声 / 地形函数
_PTAB = list(range(256)); random.shuffle(_PTAB); _PTAB = _PTAB + _PTAB
def _h(i, j):
    return _PTAB[(_PTAB[i & 255] + j) & 255] / 255.0
def vnoise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi
    u, v = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b2, c, d = _h(xi, yi), _h(xi + 1, yi), _h(xi, yi + 1), _h(xi + 1, yi + 1)
    return (a * (1 - u) + b2 * u) * (1 - v) + (c * (1 - u) + d * u) * v
def fbm(x, y, octaves=4):
    s, amp, f, total = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        s += amp * vnoise(x * f, y * f); total += amp
        amp *= 0.5; f *= 2.0
    return s / total
def smooth01(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)
def smin(a, b, k=7.0):
    return -k * math.log(math.exp(-a / k) + math.exp(-b / k))
def dang(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi

# 长江：河道中心线（西南 → 东北，微弯），半宽 RIVER_HW；lake_depth 名字沿用（>0 在水中）
RIVER = [(-52.0, -110.0), (-42.0, -62.0), (-30.0, -24.0), (-16.0, 12.0), (-4.0, 48.0), (6.0, 110.0)]
RIVER_HW = 21.0
def _seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(px - (ax + vx * t), py - (ay + vy * t))
def river_dist(x, y):
    return min(_seg_dist(x, y, RIVER[i][0], RIVER[i][1], RIVER[i + 1][0], RIVER[i + 1][1]) for i in range(len(RIVER) - 1))
def lake_depth(x, y):
    hw = RIVER_HW * (1 + 0.08 * math.sin(y * 0.05 + 1.0))
    return hw - river_dist(x, y)

# 山体：(cx, cy, H, rx, ry, rot)
HILLS = [(32, -2, 16.0, 50, 13, 0.08), (22, -6, 4.0, 14, 9, 0.0),          # 蛇山（黄鹤楼所在的长岭）
         (68, 4, 4.5, 16, 8, 0.15),
         (-78, 12, 5.0, 20, 9, 0.35),         # 龟山（对岸）
         (-94, 40, 11, 22, 30, 0.2), (-98, -40, 9, 20, 30, 0.0),   # 远山（被岛缘切开）
         (76, 58, 8, 26, 18, 0.3), (70, -68, 6, 26, 14, 0.2), (-66, 72, 7, 24, 12, 0.1)]
PLATEAUS = [(12.0, -8.0, 22.0, 9.6)]          # 黄鹤楼台地：(cx, cy, r, z)

def hill_h(x, y):
    acc = 0.0
    for (cx, cy, H, rx, ry, rot) in HILLS:
        c, s = math.cos(rot), math.sin(rot)
        ux, uy = (x - cx) * c + (y - cy) * s, -(x - cx) * s + (y - cy) * c
        e = (ux / rx) ** 2 + (uy / ry) ** 2
        if e < 1:
            acc += (H * (1 - e) ** 1.35) ** 4
    if acc <= 0:
        return 0.0
    z = acc ** 0.25
    z *= 0.78 + 0.45 * fbm(x * 0.07 + 3, y * 0.07 + 9, 4)
    z += min(z, 3.0) * 0.35 * (fbm(x * 0.22 + 7, y * 0.22, 3) - 0.5)
    return max(0.0, z)

def terrain(x, y):
    d = lake_depth(x, y)
    bed = -0.45 - 1.8 * smooth01(d / 8.0) + 0.15 * (fbm(x * 0.15, y * 0.15, 3) - 0.5)
    land = 0.30 + 0.5 * fbm(x * 0.05 + 1, y * 0.05 + 5, 3) * smooth01(-d / 5.0)
    land += 0.35 * smooth01((-d - 1.0) / 4.0) * (1 - smooth01((-d - 8.0) / 10.0))   # 江堤
    land += hill_h(x, y) * smooth01(-d / 4.0)
    for (cx, cy, r, zf) in PLATEAUS:
        w = smooth01((r - math.hypot(x - cx, y - cy)) / 10.0)
        if w > 0:
            land = land * (1 - w) + max(land, zf) * w
    if d > 1.0:
        return bed, 'water'
    if d < -1.0:
        return land, 'land'
    t = smooth01((d + 1.0) / 2.0)   # 岸线过渡
    return land * (1 - t) + (-0.2) * t, ('water' if d > 0.3 else 'land')

def ground(x, y):
    return terrain(x, y)[0]

# ----------------------------------------------------------------------------- 岛屿地形 + 切面 + 江面
ISL = (-104.0, -84.0, 86.0, 80.0)
E_SUP = 0.6
def isl_rho(x, y):
    x0, y0, x1, y1 = ISL
    cx, cy, hw, hd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    return ((abs(x - cx) / hw) ** (2 / E_SUP) + (abs(y - cy) / hd) ** (2 / E_SUP)) ** (E_SUP / 2), cx, cy

def _clipped_grid(x0, y0, x1, y1, step, zfn, rho_max=1.0):
    """按岛轮廓裁剪的规则网格：轮廓外的顶点拉回边界。返回 (verts, kinds, faces)。"""
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    verts, kinds, inside = [], [], []
    for j in range(ny):
        for i in range(nx):
            x, y = x0 + i * step, y0 + j * step
            rho, cx, cy = isl_rho(x, y)
            ins = rho <= rho_max
            if not ins:
                x, y = cx + (x - cx) / rho * rho_max, cy + (y - cy) / rho * rho_max
            z, k = zfn(x, y)
            verts.append((x, y, z)); kinds.append(k); inside.append(ins)
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; bq = a + 1; c = a + nx + 1; d = a + nx
            if inside[a] or inside[bq] or inside[c] or inside[d]:
                faces.append((a, bq, c, d))
    return verts, kinds, faces

def island():
    t0 = time.time()
    b = B("Island")
    x0, y0, x1, y1 = ISL
    verts, kinds, faces = _clipped_grid(x0, y0, x1, y1, 0.5, terrain)
    off = len(b.v)
    b.v.extend(verts)
    for f in faces:
        m = LAKEBED if any(kinds[q] == 'water' for q in f) else TERRAIN
        b.f.append(tuple(i + off for i in f)); b.m.append(b.mi(m)); b.uv.append(None)
    # 切面环
    cx, cy, hw, hd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    N = 360
    ph = [random.uniform(0, 6.28) for _ in range(5)]
    def profile(a):
        return (0.5 * math.sin(3 * a + ph[0]) + 0.3 * math.sin(7 * a + ph[1]) + 0.22 * math.sin(13 * a + ph[2])
                + 0.14 * math.sin(23 * a + ph[3]) + 0.1 * math.sin(41 * a + ph[4]))
    def base_xy(a):
        c, s = math.cos(a), math.sin(a)
        return math.copysign(abs(c) ** E_SUP, c) * hw, math.copysign(abs(s) ** E_SUP, s) * hd
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
        top.append((cx + x, cy + y, ground(cx + x, cy + y) + 0.02))
    rings = [top, ring(1.0, -3.0, 0.03, 0.012, 0.4), ring(0.995, -6.5, 0.05, 0.02, 0.7), ring(0.985, -11.0, 0.065, 0.025, 0.8),
             ring(0.965, -15.5, 0.075, 0.03, 0.8), ring(0.93, -20.0, 0.085, 0.03, 0.8), ring(0.87, -24.0, 0.095, 0.03, 0.8),
             ring(0.76, -27.5, 0.1, 0.03, 0.6), ring(0.55, -30.5, 0.1, 0.03, 0.4), ring(0.3, -32.5, 0.1, 0.02, 0.3)]
    v, f = [], []
    for r in rings:
        v.extend(r)
    R = len(rings)
    for k in range(R - 1):
        for i in range(N):
            j = (i + 1) % N
            f.append((k * N + i, k * N + j, (k + 1) * N + j, (k + 1) * N + i))
    v.append((cx, cy, -33.5)); apex = len(v) - 1
    for i in range(N):
        j = (i + 1) % N
        f.append(((R - 1) * N + j, (R - 1) * N + i, apex))
    b.add(v, f, EARTH)
    ob = b.build(smooth=True)
    me = ob.data
    earth_idx = me.materials.find(EARTH.name)
    for poly in me.polygons:
        if poly.material_index == earth_idx:
            poly.use_smooth = False
    # 江面：按岛轮廓裁剪的网格（河道两端延伸到岛缘切面）
    w = B("Water")
    wv, _, wf = _clipped_grid(-82.0, -100.0, 46.0, 100.0, 2.0, lambda x, y: (0.0, 'w'), rho_max=0.995)
    w.add(wv, wf, WATER)
    w.build()
    print(f"[yc] island grid faces={len(faces)} in {time.time() - t0:.1f}s")


# ----------------------------------------------------------------------------- 植被（实例化）
KEEP = []   # (x, y, r) 禁止种树的区域
def keep(x, y, r):
    KEEP.append((x, y, r))
def blocked(x, y):
    return any(math.hypot(x - kx, y - ky) < kr for (kx, ky, kr) in KEEP)

def icosphere(cx, cy, cz, r, sub=2, squash=0.85, jit=0.08):
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
    out = [(x * r * random.uniform(1 - jit, 1 + jit) + cx, y * r * random.uniform(1 - jit, 1 + jit) + cy,
            z * r * squash * random.uniform(1 - jit, 1 + jit) + cz) for (x, y, z) in v]
    return out, f

def mesh_round_tree():
    b = B("TreeV")
    th = random.uniform(0.5, 0.7)
    prism(b, 0, 0, -0.1, 0.09, th + 0.6, TRUNK, n=6)
    R = random.uniform(0.55, 0.7)
    v, f = icosphere(0, 0, th + 0.65, R * 0.9, sub=2, squash=0.8)
    b.add(v, f, LEAF)
    for i in range(random.choice([7, 8, 10])):
        a = random.uniform(0, 2 * math.pi)
        rr = random.uniform(0.25, 0.6)
        r = random.uniform(0.25, 0.4)
        v, f = icosphere(rr * math.cos(a), rr * math.sin(a), th + random.uniform(0.3, 0.95) + r * 0.4, r, sub=2)
        b.add(v, f, LEAF)
    return b.build(smooth=True)

def mesh_willow():
    b = B("WillowV")
    lean = random.uniform(-0.08, 0.08)
    prism(b, 0, 0, -0.1, 0.07, 0.75, TRUNK, n=6)
    v, f = icosphere(lean, 0, 1.15, 0.52, sub=2, squash=1.15)
    b.add(v, f, WILLOW)
    for i in range(random.choice([9, 10, 12])):
        a = 2 * math.pi * i / 10 + random.uniform(-0.2, 0.2)
        r0 = random.uniform(0.38, 0.5)
        top = (lean + r0 * math.cos(a), r0 * math.sin(a), random.uniform(1.0, 1.25))
        bot = (lean + (r0 + 0.12) * math.cos(a), (r0 + 0.12) * math.sin(a), random.uniform(0.15, 0.45))
        n = 5
        vv = [(top[0] + 0.11 * math.cos(2 * math.pi * k / n), top[1] + 0.11 * math.sin(2 * math.pi * k / n), top[2]) for k in range(n)]
        vv += [(bot[0] + 0.03 * math.cos(2 * math.pi * k / n), bot[1] + 0.03 * math.sin(2 * math.pi * k / n), bot[2]) for k in range(n)]
        ff = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)] + [tuple(range(n, 2 * n)), tuple(reversed(range(n)))]
        b.add(vv, ff, WILLOW)
    return b.build(smooth=True)

def mesh_pine():
    b = B("PineV")
    prism(b, 0, 0, -0.1, 0.07, 0.6, TRUNK, n=5)
    z, r = 0.35, random.uniform(0.42, 0.52)
    for i in range(3):
        cone(b, 0, 0, z, r, r * 0.18, 0.55 - 0.05 * i, PINE, n=7, phase=random.uniform(0, 1), uv=False)
        z += 0.32; r *= 0.74
    return b.build(smooth=True)

def mesh_peach():
    b = B("PeachV")
    prism(b, 0, 0, -0.1, 0.06, 0.6, TRUNK, n=5)
    v, f = icosphere(0, 0, 0.85, 0.42, sub=2, squash=0.85)
    b.add(v, f, PEACH)
    for i in range(5):
        a = random.uniform(0, 2 * math.pi)
        v, f = icosphere(0.3 * math.cos(a), 0.3 * math.sin(a), random.uniform(0.7, 1.0), random.uniform(0.2, 0.3), sub=1)
        b.add(v, f, PEACH)
    return b.build(smooth=True)

def mesh_bush():
    b = B("BushV")
    for i in range(3):
        v, f = icosphere(random.uniform(-0.15, 0.15), random.uniform(-0.15, 0.15), 0.12, random.uniform(0.2, 0.3), sub=1, squash=0.7)
        b.add(v, f, LEAF)
    return b.build(smooth=True)

# 树木模型库：Poly Haven CC0 扫描模型（assets/polyhaven/models/，见 README），按种类归一化高度后实例化
VARIANTS = {}      # kind -> [(mesh, height, zmin)]
TREE_H = {"tree": 1.6, "willow": 1.45, "pine": 2.2, "peach": 1.1, "bush": 0.42, "maple": 1.4, "ginkgo": 1.6}
PH_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "polyhaven", "models"))
LIB_TREES = {
    "tree": [("island_tree_01", "island_tree_01_LOD1"), ("island_tree_02", "island_tree_02_LOD1"), ("island_tree_03", "island_tree_03_LOD1")],
    "willow": [("tree_small_02", "tree_small_02_LOD1")],
    "pine": [("fir_sapling_medium", "fir_sapling_medium_a_LOD1"), ("fir_sapling_medium", "fir_sapling_medium_b_LOD1"),
             ("fir_sapling_medium", "fir_sapling_medium_c_LOD1")],
    "peach": [("tree_small_02", "tree_small_02_LOD1")],
    "bush": [("shrub_01", "shrub_01_a_LOD1"), ("shrub_01", "shrub_01_b_LOD1"), ("shrub_03", "shrub_03_a_LOD1"), ("shrub_03", "shrub_03_b_LOD1")],
    "maple": [("island_tree_02", "island_tree_02_LOD1"), ("island_tree_03", "island_tree_03_LOD1")],
    "ginkgo": [("island_tree_01", "island_tree_01_LOD1"), ("island_tree_02", "island_tree_02_LOD1")],
}
TINTS = {"peach": ((0.96, 0.62, 0.72), 0.7), "maple": ((0.74, 0.16, 0.08), 0.78), "ginkgo": ((0.96, 0.72, 0.16), 0.8)}
_LOADED = {}
def load_lib_mesh(file, obname):
    key = (file, obname)
    if key in _LOADED:
        return _LOADED[key]
    path = os.path.join(PH_DIR, file, file + ".blend")
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [obname]
    ob = dst.objects[0]
    me = ob.data
    zs = [v.co.z for v in me.vertices]
    res = (me, max(zs) - min(zs), min(zs))
    bpy.data.objects.remove(ob)
    _LOADED[key] = res
    return res

def tint_leaf_material(mat, pink=False, tint=None):
    """把素材库的叶片材质重建成简单的 Principled：贴图颜色 + alpha 镂空 + 逐棵随机色相/明度。
    原材质带半透明叠加（Translucent/节点组），大片 LOD 叶片卡在阳光下会发白。"""
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
        p.inputs["Specular IOR Level"].default_value = 0.25
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    hs = nt.nodes.new("ShaderNodeHueSaturation")
    nt.links.new(map_range(nt, oi.outputs["Random"], 0.47, 0.53), hs.inputs["Hue"])
    nt.links.new(map_range(nt, oi.outputs["Random"], 0.9, 1.25), hs.inputs["Value"])
    nt.links.new(diff.outputs["Color"], hs.inputs["Color"])
    col = hs.outputs["Color"]
    # 扫描贴图的叶色反照率很低，远景会成一团黑；与明亮的绿色混合后才有阳光下的林冠感
    if tint is not None:
        col = mix_rgb(nt, col, rgb(nt, tint[0]), tint[1], 'MIX')
    elif pink:
        col = mix_rgb(nt, col, rgb(nt, (0.96, 0.62, 0.72)), 0.7, 'MIX')
    elif 'fir' in mat.name or 'twigs' in mat.name:
        col = mix_rgb(nt, col, rgb(nt, (0.30, 0.60, 0.20)), 0.65, 'MIX')
    elif 'tree_small' in mat.name:
        col = mix_rgb(nt, col, rgb(nt, (0.44, 0.62, 0.22)), 0.55, 'MIX')
    else:
        col = mix_rgb(nt, col, rgb(nt, (0.27, 0.54, 0.19)), 0.55, 'MIX')
    nt.links.new(col, p.inputs["Base Color"])
    nt.links.new(alpha.outputs["Color"] if alpha is not None else diff.outputs["Alpha"], p.inputs["Alpha"])
    nt.links.new(p.outputs["BSDF"], out.inputs["Surface"])

def is_leaf_mat(name):
    n = name.lower()
    return ('leaves' in n or 'twigs' in n or 'shrub' in n
            or ('branches' in n and ('island_tree' in n or 'tree_small' in n)))

def make_variants():
    if WEB:
        for kind, items in LIB_TREES.items():
            VARIANTS[kind] = [(None, 1.0, 0.0)] * len(items)
        return
    for kind, items in LIB_TREES.items():
        lst = []
        for (file, obname) in items:
            me, h, z0 = load_lib_mesh(file, obname)
            if kind in TINTS:
                me = me.copy()
                for i, m in enumerate(me.materials):
                    if m and is_leaf_mat(m.name):
                        m2 = m.copy(); tint_leaf_material(m2, tint=TINTS[kind]); add_fog(m2); me.materials[i] = m2
            lst.append((me, h, z0))
        VARIANTS[kind] = lst
    done = set()
    for kind, lst in VARIANTS.items():
        for (me, h, z0) in lst:
            for m in me.materials:
                if m and m.name not in done:
                    done.add(m.name)
                    if kind not in TINTS and is_leaf_mat(m.name):
                        tint_leaf_material(m)
                    add_fog(m)
    print("[yc] tree library:", {k: [(round(h, 2)) for (_, h, _) in v] for k, v in VARIANTS.items()})

N_PLANTS = 0
def plant(kind, x, y, s=1.0, z=None):
    global N_PLANTS
    if isl_rho(x, y)[0] > 0.975:   # 岛缘之外不种树（避免悬空）
        return None
    if z is None:
        z = ground(x, y) - 0.03
    if WEB:
        hh = s * TREE_H[kind] * random.uniform(0.9, 1.1)
        PLANTS.append([kind, random.randrange(len(LIB_TREES[kind])), round(x, 2), round(y, 2), round(z + 0.03, 2), round(hh, 2), round(random.uniform(0, 6.28), 2)])
        N_PLANTS += 1
        return None
    me, h, z0 = random.choice(VARIANTS[kind])
    k = s * TREE_H[kind] / h
    ob = bpy.data.objects.new(kind, me)
    ob.scale = (k * random.uniform(0.9, 1.1), k * random.uniform(0.9, 1.1), k)
    ob.location = (x, y, z - z0 * k)
    ob.rotation_euler = (0, 0, random.uniform(0, 6.28))
    COL.objects.link(ob)
    N_PLANTS += 1
    return ob

def lotus_patch(cx, cy, R, n, b=None):
    own = b is None
    if own:
        b = B("Lotus")
    for _ in range(n):
        a, rr = random.uniform(0, 6.28), R * math.sqrt(random.random())
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        if lake_depth(x, y) < 0.8 and island_z(x, y) != (-0.45, 'water'):
            continue
        z = 0.03 + random.random() ** 2 * 0.22
        disc(b, x, y, z, random.uniform(0.3, 0.5), LOTUS_LEAF, n=9,
             tilt=(random.uniform(-0.3, 0.3), random.uniform(-0.3, 0.3)), dip=0.04)
        if z > 0.1:
            prism(b, x, y, 0.0, 0.025, z, TRUNK, n=4)
        if random.random() < 0.1:
            prism(b, x + 0.15, y, 0.0, 0.02, 0.4, TRUNK, n=4)
            v, f = icosphere(x + 0.15, y, 0.45, 0.11, sub=1, squash=1.3)
            b.add(v, f, LOTUS_FLOWER)
    if own:
        b.build(smooth=True)

# ----------------------------------------------------------------------------- 堤 / 桥
def polyline(pts):
    seg, acc = [], 0.0
    for i in range(len(pts) - 1):
        L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        seg.append((acc, L)); acc += L
    def P(s):
        s = max(0.0, min(acc, s))
        for i, (s0, L) in enumerate(seg):
            if s <= s0 + L or i == len(seg) - 1:
                t = (s - s0) / L
                (xa, ya), (xb, yb) = pts[i], pts[i + 1]
                return xa + (xb - xa) * t, ya + (yb - ya) * t, (xb - xa) / L, (yb - ya) / L
    return P, acc

def dike(b, P, sa, sb, width, zt, path=True, path_mat=STONE):
    n = max(1, int((sb - sa) / 1.0))
    ss = [sa + (sb - sa) * i / n for i in range(n + 1)]
    hw, pw = width / 2, width * 0.22
    rows = []
    for s in ss:
        x, y, dx, dy = P(s)
        nx, ny = -dy, dx
        rows.append([(x + nx * (hw + 1.0), y + ny * (hw + 1.0), -0.9), (x + nx * hw, y + ny * hw, zt),
                     (x + nx * pw, y + ny * pw, zt), (x - nx * pw, y - ny * pw, zt),
                     (x - nx * hw, y - ny * hw, zt), (x - nx * (hw + 1.0), y - ny * (hw + 1.0), -0.9)])
    verts = [p for r in rows for p in r]
    k = 6
    for i in range(len(rows) - 1):
        o, q = i * k, (i + 1) * k
        b.add(verts, [(o + 0, o + 1, q + 1, q + 0)], GRANITE)
        b.add(verts, [(o + 1, o + 2, q + 2, q + 1)], LAWN)
        b.add(verts, [(o + 2, o + 3, q + 3, q + 2)], path_mat if path else LAWN)
        b.add(verts, [(o + 3, o + 4, q + 4, q + 3)], LAWN)
        b.add(verts, [(o + 4, o + 5, q + 5, q + 4)], GRANITE)
    b.add(verts, [(0, 1, 2, 3, 4, 5)], GRANITE)
    o = (len(rows) - 1) * k
    b.add(verts, [(o + 5, o + 4, o + 3, o + 2, o + 1, o + 0)], GRANITE)

def arch_bridge(b, p0, p1, w, zt, rise, big=False):
    x0, y0 = p0; x1, y1 = p1
    L = math.hypot(x1 - x0, y1 - y0)
    dx, dy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -dy, dx
    M = 18
    rows, tops = [], []
    for i in range(M + 1):
        t = i / M
        u = 2 * t - 1
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        ztop = zt + rise * (1 - u * u) ** 1.1
        k = 0.8
        if abs(u) < k:
            zbot = -0.45 + (ztop - 0.38 + 0.45) * math.sqrt(1 - (u / k) ** 2)
        else:
            zbot = -0.9
        hw = w / 2
        rows.append([(x + nx * hw, y + ny * hw, ztop), (x - nx * hw, y - ny * hw, ztop),
                     (x - nx * hw, y - ny * hw, zbot), (x + nx * hw, y + ny * hw, zbot)])
        tops.append(((x + nx * (hw - 0.08), y + ny * (hw - 0.08), ztop), (x - nx * (hw - 0.08), y - ny * (hw - 0.08), ztop)))
    verts = [p for r in rows for p in r]
    for i in range(M):
        o, q = i * 4, (i + 1) * 4
        b.add(verts, [(o + 0, o + 1, q + 1, q + 0)], STONE)
        b.add(verts, [(o + 1, o + 2, q + 2, q + 1)], GRANITE)
        b.add(verts, [(o + 2, o + 3, q + 3, q + 2)], GRANITE)
        b.add(verts, [(o + 3, o + 0, q + 0, q + 3)], GRANITE)
    b.add(verts, [(0, 3, 2, 1)], GRANITE)
    o = M * 4
    b.add(verts, [(o + 0, o + 1, o + 2, o + 3)], GRANITE)
    post = 0.3 if big else 0.24
    for side in (0, 1):
        pts = [tops[i][side] for i in range(0, M + 1, 2)]
        for p in pts:
            box(b, p[0], p[1], p[2], 0.09, 0.09, post, GRANITE)
        for i in range(len(pts) - 1):
            rod(b, (pts[i][0], pts[i][1], pts[i][2] + post * 0.75), (pts[i + 1][0], pts[i + 1][1], pts[i + 1][2] + post * 0.75), 0.035, GRANITE)

def causeway(name, pts, width, bridges, zt=0.36, tree_step=3.2, willow_s=(1.5, 1.9), peach=True):
    P, L = polyline(pts)
    b = B(name)
    cuts = sorted(bridges)
    spans, s = [], 0.0
    for (s0, s1, rise) in cuts:
        spans.append((s, s0)); s = s1
    spans.append((s, L))
    for (sa, sb) in spans:
        if sb - sa > 0.5:
            dike(b, P, sa, sb, width, zt)
    for (s0, s1, rise) in cuts:
        xa, ya, _, _ = P(s0 - 0.3); xb, yb, _, _ = P(s1 + 0.3)
        arch_bridge(b, (xa, ya), (xb, yb), width * 0.8, zt, rise, big=rise > 1.0)
        keep((xa + xb) / 2, (ya + yb) / 2, (s1 - s0) / 2 + 1.5)
    b.build()
    s, k = 1.6, 0
    while s < L - 1.0:
        in_gap = any(s0 - 1.2 < s < s1 + 1.2 for (s0, s1, _) in cuts)
        if not in_gap:
            x, y, dx, dy = P(s)
            nx, ny = -dy, dx
            side = 1 if k % 2 == 0 else -1
            off = width / 2 - 0.3
            if peach and k % 3 == 1:
                plant("peach", x + nx * off * side, y + ny * off * side, random.uniform(1.1, 1.4), z=zt - 0.05)
            else:
                plant("willow", x + nx * off * side, y + ny * off * side, random.uniform(*willow_s), z=zt - 0.05)
            if random.random() < 0.35:
                plant("bush", x - nx * off * side, y - ny * off * side, random.uniform(0.7, 1.0), z=zt - 0.05)
        s += tree_step * random.uniform(0.8, 1.2); k += 1
    return P, L

def zigzag(b, pts, w=0.45, z=0.28):
    """九曲桥：折线石板桥。"""
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if abs(x1 - x0) > abs(y1 - y0):
            box(b, cx, cy, z, abs(x1 - x0) + w, w, 0.08, STONE)
        else:
            box(b, cx, cy, z, w, abs(y1 - y0) + w, 0.08, STONE)
        box(b, x0, y0, z - 0.6, 0.18, 0.18, 0.6, GRANITE)
    for (x, y) in pts:
        box(b, x, y, z + 0.08, 0.07, 0.07, 0.18, GRANITE)

# ----------------------------------------------------------------------------- 江南建筑
def base_z(cx, cy, w, d):
    return max(ground(cx + sx * w / 2, cy + sy * d / 2) for sx in (-1, 1) for sy in (-1, 1)) - 0.06

BS = 1.4   # 建筑整体放大系数（沙盘比例下让楼阁读得清）

def hall_jn(b, cx, cy, w, d, h, roof=DARK_TILE, wall=WHITE_WALL, double=False, z0=None, plat=0.14,
            roof_h=None, stair=False, ridge=0.6, plat_mat=GRANITE, col_mat=COLUMN):
    w, d, h = w * BS, d * BS, h * BS
    if z0 is None:
        z0 = base_z(cx, cy, w + 0.6, d + 0.6)
    keep(cx, cy, max(w, d) * 0.7 + 0.5)
    z = z0
    pw, pd = w + 0.5, d + 0.5
    box(b, cx, cy, z - 0.5, pw, pd, plat + 0.5, plat_mat)
    if stair:
        stairs(b, cx, cy - pd / 2, z, min(w * 0.4, 1.6), plat)
    z += plat
    over = 0.35 + 0.1 * h
    if roof_h is None:
        roof_h = 0.42 * d + 0.25
    def body(z, w, d, h):
        box(b, cx, cy, z, w - 0.16, d - 0.44, h, wall)
        n = max(3, int(round(w / 0.85)) + 1)
        r = 0.055 + 0.012 * h
        for i in range(n):
            x = cx - w / 2 + 0.14 + (w - 0.28) * i / (n - 1)
            prism(b, x, cy - d / 2 + 0.08, z, r, h, col_mat, n=6)
            prism(b, x, cy + d / 2 - 0.08, z, r, h, col_mat, n=6)
        box(b, cx, cy - d / 2 + 0.2, z + 0.08, w - 0.55, 0.05, h * 0.7, LATTICE)
        box(b, cx, cy + d / 2 - 0.2, z + 0.08, w - 0.55, 0.05, h * 0.7, LATTICE)
        box(b, cx, cy, z + h - 0.12, w + 0.12, d + 0.12, 0.15, WOOD)
    if double:
        h1 = h * 0.55
        body(z, w, d, h1)
        skirt_roof(b, cx, cy, z + h1 + 0.06, w + 2 * over, d + 2 * over, inset=over + 0.45, rise=0.42, mat=roof)
        z2 = z + h1 + 0.48
        w2, d2 = w - 0.9, d - 0.9
        h2 = h * 0.5
        body(z2 - 0.06, w2, d2, h2 + 0.06)
        hip_roof(b, cx, cy, z2 + h2 + 0.06, w2 + 2 * over, d2 + 2 * over, roof_h, roof, ridge=ridge)
    else:
        body(z, w, d, h)
        hip_roof(b, cx, cy, z + h + 0.06, w + 2 * over, d + 2 * over, roof_h, roof, ridge=ridge)
    return z0

def pavilion_jn(b, cx, cy, r, h, n=6, z0=None, double=False, roof=DARK_TILE, plat=0.18, phase=0.0):
    r, h = r * BS, h * BS
    if z0 is None:
        z0 = base_z(cx, cy, r * 2, r * 2)
    keep(cx, cy, r + 0.8)
    prism(b, cx, cy, z0 - 0.5, r + 0.4, plat + 0.5, GRANITE, n=n, phase=phase)
    z = z0 + plat
    for i in range(n):
        a = 2 * math.pi * i / n + phase
        prism(b, cx + r * 0.9 * math.cos(a), cy + r * 0.9 * math.sin(a), z, 0.06, h, COLUMN, n=6)
    prism(b, cx, cy, z, r * 0.92, 0.22, LATTICE, n=n, phase=phase)   # 美人靠
    prism(b, cx, cy, z + h - 0.12, r * 1.02, 0.14, WOOD, n=n, phase=phase)
    if double:
        cone(b, cx, cy, z + h, r + 0.6, r * 0.55, 0.32, roof, n=n, phase=phase)
        prism(b, cx, cy, z + h + 0.3, r * 0.5, h * 0.45, WHITE_WALL, n=n, phase=phase)
        poly_roof(b, cx, cy, z + h + 0.3 + h * 0.45, r * 0.78, h * 0.6, n, roof)
    else:
        poly_roof(b, cx, cy, z + h, r + 0.55, h * 0.8, n, roof)
    return z0

def pagoda(b, cx, cy, z0, stories, r0, sh, shrink=0.9, body=BRICK, roof=BRONZE_TILE, eave=0.7, slim=False):
    keep(cx, cy, r0 + 3)
    prism(b, cx, cy, z0 - 0.6, r0 + 1.4, 1.0, GRANITE, n=8)
    rail(b, [(cx + (r0 + 1.3) * math.cos(2 * math.pi * i / 8), cy + (r0 + 1.3) * math.sin(2 * math.pi * i / 8)) for i in range(8)],
         z0 + 0.4, step=0.6)
    z, r = z0 + 0.4, r0
    for i in range(stories):
        prism(b, cx, cy, z, r, sh, body, n=8)
        if not slim:
            prism(b, cx, cy, z + 0.04, r + 0.3, 0.07, WOOD, n=8)
            for k in range(8):
                a = 2 * math.pi * k / 8
                box(b, cx + (r + 0.28) * math.cos(a), cy + (r + 0.28) * math.sin(a), z + 0.11, 0.06, 0.06, 0.2, WOOD)
            for k in range(8):
                a = 2 * math.pi * (k + 0.5) / 8
                box(b, cx + (r - 0.02) * math.cos(a), cy + (r - 0.02) * math.sin(a), z + 0.25, 0.22, 0.22, sh * 0.5, LATTICE)
        cone(b, cx, cy, z + sh - 0.06, r + eave, r * 0.8, 0.34, roof, n=8)
        for k in range(8):
            a = 2 * math.pi * k / 8
            rod(b, (cx + (r + eave) * math.cos(a), cy + (r + eave) * math.sin(a), z + sh - 0.06),
                (cx + r * 0.8 * math.cos(a), cy + r * 0.8 * math.sin(a), z + sh + 0.28), 0.03, RIDGE, lift=0.01)
        z += sh + 0.26
        r *= shrink
    poly_roof(b, cx, cy, z - 0.02, r + eave * 0.95, r * 1.1 + 0.5, 8, roof, finial=False)
    zt = z - 0.02 + r * 1.1 + 0.5
    prism(b, cx, cy, zt - 0.1, 0.12, 1.2, FINIAL, n=6)
    for k in range(4):
        prism(b, cx, cy, zt + 0.15 + k * 0.25, 0.22 - 0.03 * k, 0.06, FINIAL, n=8)

def house(x, y, w, d, h, ang, wall=WHITE_WALL):
    if isl_rho(x, y)[0] > 0.93:   # 岛缘之外不建房
        return
    b = B("House")
    z0 = ground(x, y) - 0.05
    box(b, 0, 0, z0 - 0.3, w + 0.2, d + 0.2, 0.3 + 0.08, GRANITE)
    box(b, 0, 0, z0 + 0.08, w, d, h, wall)
    box(b, 0, -d / 2 + 0.005, z0 + 0.2, w * 0.7, 0.03, h * 0.6, LATTICE)
    hip_roof(b, 0, 0, z0 + 0.08 + h, w + 0.5, d + 0.5, 0.36 * d + 0.15, DARK_TILE, ridge=0.7, curl=0.1)
    b.build(loc=(x, y, 0), rot=ang)
    keep(x, y, max(w, d) * 0.7)

def compound(b, cx, cy, w, d, wall_mat, nh=3, roof=DARK_TILE, z0=None, gate=True):
    if z0 is None:
        z0 = base_z(cx, cy, w, d)
    keep(cx, cy, max(w, d) * 0.72)
    for (x0, y0, x1, y1) in ((cx - w / 2, cy - d / 2, cx + w / 2, cy - d / 2), (cx - w / 2, cy + d / 2, cx + w / 2, cy + d / 2),
                             (cx - w / 2, cy - d / 2, cx - w / 2, cy + d / 2), (cx + w / 2, cy - d / 2, cx + w / 2, cy + d / 2)):
        ww = abs(x1 - x0) + 0.3 if x0 != x1 else 0.3
        dd = abs(y1 - y0) + 0.3 if y0 != y1 else 0.3
        box(b, (x0 + x1) / 2, (y0 + y1) / 2, z0 - 0.3, ww, dd, 0.3 + 0.7, wall_mat)
        box(b, (x0 + x1) / 2, (y0 + y1) / 2, z0 + 0.7, ww + 0.14, dd + 0.14, 0.1, DARK_TILE)
    if gate:
        hall_jn(b, cx, cy - d / 2, min(2.4, w * 0.4), 1.2, 0.9, roof=roof, wall=wall_mat, z0=z0, plat=0.1)
    for i in range(nh):
        t = (i + 0.5) / nh
        hw = min(w - 1.6, 2.6 + 1.0 * i)
        hall_jn(b, cx, cy - d / 2 + d * t + 0.3, hw, 1.6 + 0.3 * i, 1.0 + 0.25 * i, roof=roof, wall=wall_mat,
                z0=z0, double=(i == nh - 1), stair=True)
    for sx in (-1, 1):
        hall_jn(b, cx + sx * (w / 2 - 1.1), cy, 1.4, min(d * 0.45, 5.0), 0.8, roof=roof, wall=wall_mat, z0=z0, plat=0.08, ridge=0.8)
    return z0

def stone_lantern(b, x, y):
    """三潭印月的石塔。"""
    prism(b, x, y, -0.6, 0.38, 0.9, GRANITE, n=8)
    v, f = icosphere(x, y, 0.75, 0.42, sub=1, squash=1.0, jit=0.0)
    b.add(v, f, GRANITE)
    cone(b, x, y, 1.1, 0.5, 0.1, 0.4, GRANITE, n=8, uv=False)
    prism(b, x, y, 1.45, 0.06, 0.3, GRANITE, n=6)

def boat(x, y, ang, L, W, canopy=True):
    b = B("Boat")
    M = 10
    rows = []
    for i in range(M + 1):
        t = i / M
        xx = (t - 0.5) * L
        hw = max(0.06, W * 0.5 * math.sin(math.pi * t) ** 0.6)
        zt = 0.17 + 0.09 * (2 * t - 1) ** 2
        rows.append([(xx, -hw, zt), (xx, hw, zt), (xx, hw * 0.8, -0.14), (xx, -hw * 0.8, -0.14)])
    verts = [p for r in rows for p in r]
    for i in range(M):
        o, q = i * 4, (i + 1) * 4
        b.add(verts, [(o + 0, o + 1, q + 1, q + 0)], BOAT_DECK)
        b.add(verts, [(o + 1, o + 2, q + 2, q + 1)], BOAT_RED if canopy else BOAT_WOOD)
        b.add(verts, [(o + 2, o + 3, q + 3, q + 2)], BOAT_WOOD)
        b.add(verts, [(o + 3, o + 0, q + 0, q + 3)], BOAT_RED if canopy else BOAT_WOOD)
    if canopy:
        box(b, 0, 0, 0.2, L * 0.5, W * 0.72, 0.42, LATTICE)
        for sx in (-1, 1):
            for sy in (-1, 1):
                prism(b, sx * L * 0.3, sy * W * 0.38, 0.2, 0.03, 0.5, COLUMN, n=5)
        hip_roof(b, 0, 0, 0.7, L * 0.68, W * 1.05, 0.26, DARK_TILE, ridge=0.6, curl=0.1)
    else:
        box(b, 0, 0, 0.17, L * 0.28, W * 0.6, 0.18, BOAT_WOOD)
    b.build(loc=(x, y, 0), rot=ang)
# ----------------------------------------------------------------------------- 黄鹤楼 / 长江大桥 / 电视塔 / 江船
GOLD = tile_material("GlazedGold", (1.0, 0.62, 0.08), (1.0, 0.82, 0.24), rough=0.25, coat=0.6)
STEEL = principled("Steel", (0.42, 0.46, 0.50), rough=0.45, metal=0.5)
EAVE = principled("EaveTeal", (0.07, 0.24, 0.30), rough=0.55)
TRIM = principled("GoldTrim", (0.85, 0.62, 0.18), rough=0.35, metal=0.6)
CONCRETE = principled("Concrete", (0.62, 0.62, 0.60), rough=0.85)
ASPHALT = principled("Asphalt", (0.30, 0.30, 0.29), rough=0.95)
WHITE_HULL = principled("WhiteHull", (0.92, 0.92, 0.90), rough=0.4, coat=0.2)
RED_BRICK = noise_mix(principled("RedBrick", (0.52, 0.20, 0.14), rough=0.85), (0.46, 0.17, 0.12), (0.60, 0.26, 0.18), 14.0, bump=0.2)
GLASS = principled("Glass", (0.30, 0.40, 0.50), rough=0.15, metal=0.6, spec=0.8)
FACADE = noise_mix(principled("Facade", (0.78, 0.76, 0.72), rough=0.7), (0.70, 0.68, 0.64), (0.86, 0.84, 0.80), 6.0)
FACADE2 = principled("Facade2", (0.86, 0.80, 0.68), rough=0.7)
for _m in (GOLD, STEEL, EAVE, TRIM, CONCRETE, WHITE_HULL, ASPHALT, RED_BRICK, GLASS, FACADE, FACADE2):
    add_fog(_m)

def gable(b, cx, cy, z, w, d, h, ang, mat=GOLD, curl=0.3, t=0.12):
    """歇山式小顶（抱厦 / 翘角）：脊沿本地 x 轴，前坡朝本地 +y（外侧），绕 (cx, cy) 转 ang。"""
    c, s = math.cos(ang), math.sin(ang)
    def T(x, y, zz):
        return (cx + x * c - y * s, cy + x * s + y * c, zz)
    hw, hd = w / 2, d / 2
    top = [T(-hw, hd, z + curl), T(hw, hd, z + curl), T(hw, -hd, z + curl * 0.3), T(-hw, -hd, z + curl * 0.3),
           T(-hw * 0.55, 0, z + h), T(hw * 0.55, 0, z + h)]
    faces = [(0, 1, 5, 4), (2, 3, 4, 5), (1, 2, 5), (3, 0, 4)]
    _shell(b, top, faces, 4, mat, t)
    rod(b, top[4], top[5], 0.04, RIDGE, lift=0.01)
    for (ci, ri) in ((0, 4), (1, 5)):
        rod(b, top[ci], top[ri], 0.035, RIDGE, lift=0.01)

def crane_tower(b, cx, cy, z0, stories=5, w=13.0, story_h=1.9, roof=GOLD, platform=True):
    """黄鹤楼：层层平座朱栏、每面三翘角（主檐四角 + 中间抱厦两角）、顶层攒尖宝顶。"""
    keep(cx, cy, w + (7 if platform else 2))
    z = z0
    if platform:
        for (pw, ph) in ((w + 14, 1.0), (w + 9, 0.9), (w + 4.5, 0.8)):
            box(b, cx, cy, z - 0.4, pw, pw, ph + 0.4, GRANITE)
            rail(b, [(cx - pw / 2, cy - pw / 2), (cx + pw / 2, cy - pw / 2), (cx + pw / 2, cy + pw / 2), (cx - pw / 2, cy + pw / 2)],
                 z + ph, step=0.6, mat=WHITE_WALL, post=0.3)
            for sy in (-1, 1):
                stairs(b, cx, cy + sy * (pw / 2), z, 3.2, ph, steps=4, dir=sy)
            z += ph
    for i in range(stories):
        last = i == stories - 1
        box(b, cx, cy, z, w + 1.6, w + 1.6, 0.22, WOOD)                      # 平座
        hwp = w / 2 + 0.7
        rail(b, [(cx - hwp, cy - hwp), (cx + hwp, cy - hwp), (cx + hwp, cy + hwp), (cx - hwp, cy + hwp)],
             z + 0.22, step=0.45, mat=COLUMN, post=0.32)                        # 朱红栏杆
        zb = z + 0.22
        box(b, cx, cy, zb, w - 0.5, w - 0.5, story_h, LATTICE)                  # 格扇墙
        n = max(4, int(round(w / 1.1)) + 1)
        for k in range(n):
            t = -w / 2 + 0.25 + (w - 0.5) * k / (n - 1)
            for (px, py) in ((cx + t, cy - w / 2 + 0.2), (cx + t, cy + w / 2 - 0.2), (cx - w / 2 + 0.2, cy + t), (cx + w / 2 - 0.2, cy + t)):
                prism(b, px, py, zb, 0.09, story_h, COLUMN, n=6)              # 朱红柱
        box(b, cx, cy, zb + story_h - 0.16, w + 0.5, w + 0.5, 0.2, EAVE)       # 檐枋（青绿彩画）
        box(b, cx, cy, zb + story_h - 0.28, w + 0.3, w + 0.3, 0.1, TRIM)
        rz = zb + story_h
        sides = ((0, 1, 0.0), (0, -1, math.pi), (1, 0, -math.pi / 2), (-1, 0, math.pi / 2))
        if not last:
            skirt_roof(b, cx, cy, rz, w + 3.0, w + 3.0, inset=2.0, rise=0.8, mat=roof, curl=0.5)
            for (dx, dy, ang) in sides:
                gable(b, cx + dx * (w / 2 + 0.9), cy + dy * (w / 2 + 0.9), rz + 0.12, w * 0.42, 2.6, 0.85, ang, roof, curl=0.4)
            z = rz + 0.75
            w -= 1.0
        else:
            r = (w + 3.0) / 2 * math.sqrt(2)
            hh = w * 0.42 + 1.2
            poly_roof(b, cx, cy, rz, r, hh, 4, roof, curl=0.6, finial=False, phase=math.pi / 4)
            for (dx, dy, ang) in sides:
                gable(b, cx + dx * (w / 2 + 0.9), cy + dy * (w / 2 + 0.9), rz + 0.12, w * 0.4, 2.6, 0.85, ang, roof, curl=0.4)
            zt = rz + hh
            prism(b, cx, cy, zt - 0.1, 0.24, 0.5, FINIAL, n=8)
            for k in range(3):
                prism(b, cx, cy, zt + 0.4 + k * 0.45, 0.44 - 0.1 * k, 0.12, FINIAL, n=8)
            prism(b, cx, cy, zt + 0.4, 0.08, 2.0, FINIAL, n=6)
    return z

def bridge_ramp(b, P, s0, s1, z0, z1, W):
    """引桥：沿 P(s) 的坡道，顶面渐变高度，两侧挡墙埋入地面。"""
    n = max(2, int(abs(s1 - s0) / 2.0))
    rows = []
    for k in range(n + 1):
        t = k / n
        s = s0 + (s1 - s0) * t
        z = z0 + (z1 - z0) * t
        x, y, _ = P(s, 0.0, 0.0)
        xl, yl, _ = P(s, W / 2, 0.0); xr, yr, _ = P(s, -W / 2, 0.0)
        rows.append([(xl, yl, z), (xr, yr, z), (xr, yr, -1.0), (xl, yl, -1.0)])
    verts = [p for r in rows for p in r]
    for i in range(len(rows) - 1):
        o, q = i * 4, (i + 1) * 4
        b.add(verts, [(o + 0, o + 1, q + 1, q + 0)], ASPHALT)
        b.add(verts, [(o + 1, o + 2, q + 2, q + 1)], GRANITE)
        b.add(verts, [(o + 3, o + 0, q + 0, q + 3)], GRANITE)

def yangtze_bridge(b, p0, p1, deck_z=3.4, piers=7, ramp_len=26.0):
    """武汉长江大桥：双层钢桁架（上公路、下铁路）、石墩、两端桥头堡与引桥。p0 东岸端，p1 西岸端。"""
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    dx, dy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -dy, dx
    ang = math.atan2(dy, dx)
    def P(s, off=0.0, z=0.0):
        return (x0 + dx * s + nx * off, y0 + dy * s + ny * off, z)
    W = 3.4
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rbox(b, cx, cy, deck_z, L, W, 0.28, ASPHALT, ang)                  # 上层公路桥面
    rbox(b, cx, cy, deck_z - 1.7, L, W - 0.6, 0.22, STEEL, ang)        # 下层铁路桥面
    top = deck_z + 0.28 + 1.5
    step = 2.6
    n = int(L / step)
    for side in (-1, 1):
        off = side * (W / 2 - 0.1)
        rod(b, P(0, off, top), P(L, off, top), 0.06, STEEL)
        rod(b, P(0, side * W / 2, deck_z + 0.28 + 0.35), P(L, side * W / 2, deck_z + 0.28 + 0.35), 0.03, STEEL)
        for k in range(n + 1):
            s = min(L, k * step)
            rod(b, P(s, off, deck_z - 1.7), P(s, off, top), 0.05, STEEL)
            if k < n:
                s2 = min(L, (k + 1) * step)
                rod(b, P(s, off, deck_z - 1.7), P(s2, off, top), 0.04, STEEL)
    for k in range(n + 1):
        s = min(L, k * step)
        rod(b, P(s, -W / 2 + 0.1, top), P(s, W / 2 - 0.1, top), 0.04, STEEL)
    for k in range(1, piers + 1):
        s = L * k / (piers + 1)
        x, y, _ = P(s)
        rbox(b, x, y, -2.4, 2.2, W + 1.4, deck_z - 1.7 + 2.4, GRANITE, ang)
        rbox(b, x, y, -2.6, 3.2, W + 2.8, 1.6, GRANITE, ang)
        keep(x, y, 3.5)
    for (s, sgn) in ((0.0, -1), (L, 1)):
        for side in (-1, 1):
            xx, yy, _ = P(s + sgn * 1.4, side * (W / 2 + 1.1))
            zz = ground(xx, yy) - 0.4
            rbox(b, xx, yy, zz, 2.2, 2.2, deck_z + 0.28 + 2.4 - zz, GRANITE, ang)
            hip_roof(b, xx, yy, deck_z + 0.28 + 2.4, 2.8, 2.8, 0.9, DARK_TILE, ridge=0.0, curl=0.15)
        bridge_ramp(b, P, s, s + sgn * ramp_len, deck_z + 0.28, ground(*P(s + sgn * ramp_len)[:2]) + 0.1, W)
        for q in range(0, int(ramp_len) + 1, 3):
            xq, yq, _ = P(s + sgn * q); keep(xq, yq, 3.0)
    for q in range(0, int(L), 4):
        xq, yq, _ = P(q); keep(xq, yq, 2.8)

def tv_tower(b, cx, cy, z0):
    """龟山电视塔。"""
    keep(cx, cy, 3.5)
    prism(b, cx, cy, z0 - 0.5, 1.7, 1.2, CONCRETE, n=10)
    cone(b, cx, cy, z0 + 0.7, 1.2, 0.55, 3.5, CONCRETE, n=12, uv=False)
    prism(b, cx, cy, z0 + 4.2, 0.5, 8.0, CONCRETE, n=12)
    cone(b, cx, cy, z0 + 11.6, 0.5, 1.8, 0.9, CONCRETE, n=12, uv=False)
    prism(b, cx, cy, z0 + 12.5, 2.0, 1.2, WHITE_WALL, n=12)
    prism(b, cx, cy, z0 + 13.7, 1.3, 0.4, CONCRETE, n=12)
    prism(b, cx, cy, z0 + 14.1, 0.14, 5.0, STEEL, n=6)

def tower_block(b, cx, cy, w, d, floors, ang=0.0, glassy=False, z0=None):
    """现代楼房：逐层窗带（玻璃 + 外墙），顶部女儿墙与设备间。"""
    if z0 is None:
        z0 = max(ground(cx + sx * w / 2, cy + sy * d / 2) for sx in (-1, 1) for sy in (-1, 1)) - 0.1
    fh = 0.62
    rbox(b, cx, cy, z0 - 0.3, w + 0.8, d + 0.8, 0.35, CONCRETE, ang)
    wall = FACADE2 if random.random() < 0.3 else FACADE
    if glassy:
        rbox(b, cx, cy, z0, w, d, floors * fh, GLASS, ang)
        for k in range(floors):
            rbox(b, cx, cy, z0 + k * fh + fh - 0.08, w + 0.06, d + 0.06, 0.08, CONCRETE, ang)
    else:
        rbox(b, cx, cy, z0, w, d, floors * fh, wall, ang)
        for k in range(floors):
            rbox(b, cx, cy, z0 + k * fh + 0.18, w + 0.05, d + 0.05, 0.26, GLASS, ang)
    zt = z0 + floors * fh
    rbox(b, cx, cy, zt, w + 0.1, d + 0.1, 0.12, CONCRETE, ang)
    rbox(b, cx + w * 0.2, cy, zt + 0.12, w * 0.3, d * 0.4, 0.5, CONCRETE, ang)
    keep(cx, cy, max(w, d) * 0.8)

def city(x0s, y0s, x1s, y1s, floors=(5, 14), glassy=0.35, bw=14.0, bd=12.0, street=2.6, density=0.9):
    """现代城区：沥青街道网格 + 每个街区一块铺装地块 + 1~3 栋楼 + 行道树。"""
    b = B("City")
    x = x0s
    while x + bw < x1s:
        y = y0s
        while y + bd < y1s:
            cx, cy = x + bw / 2, y + bd / 2
            if (lake_depth(cx, cy) < -6 and ground(cx, cy) < 2.0 and not blocked(cx, cy)
                    and isl_rho(cx, cy)[0] < 0.93 and random.random() < density):
                gz = max(ground(cx + sx * bw / 2, cy + sy * bd / 2) for sx in (-1, 1) for sy in (-1, 1))
                box(b, cx, cy, gz - 0.35, bw + street, bd + street, 0.4, ASPHALT)       # 街区（含道路）
                box(b, cx, cy, gz + 0.05, bw - 0.8, bd - 0.8, 0.06, STONE)              # 地块铺装
                keep(cx, cy, max(bw, bd) * 0.75)
                for i in range(random.randint(1, 3)):
                    w, d = random.uniform(2.8, 4.8), random.uniform(2.4, 3.8)
                    bx = cx + random.uniform(-bw / 2 + w / 2 + 0.6, bw / 2 - w / 2 - 0.6)
                    by = cy + random.uniform(-bd / 2 + d / 2 + 0.6, bd / 2 - d / 2 - 0.6)
                    tower_block(b, bx, by, w, d, random.randint(*floors), 0.0, glassy=random.random() < glassy, z0=gz + 0.11)
                for i in range(2):
                    plant("ginkgo" if random.random() < 0.5 else "tree", cx + random.uniform(-bw / 2, bw / 2), cy + random.uniform(-bd / 2, bd / 2), random.uniform(1.0, 1.4), z=gz + 0.1)
            y += bd + street
        x += bw + street
    b.build()

def hull(b, L, W, zt, side_mat, deck_mat, flat=False):
    M = 10
    rows = []
    for i in range(M + 1):
        t = i / M
        xx = (t - 0.5) * L
        hw = max(0.06, W * 0.5 * (math.sin(math.pi * t) ** (0.35 if flat else 0.6)))
        z = zt + (0.04 if flat else 0.09) * (2 * t - 1) ** 2
        rows.append([(xx, -hw, z), (xx, hw, z), (xx, hw * 0.85, -0.2), (xx, -hw * 0.85, -0.2)])
    verts = [p for r in rows for p in r]
    for i in range(M):
        o, q = i * 4, (i + 1) * 4
        b.add(verts, [(o + 0, o + 1, q + 1, q + 0)], deck_mat)
        b.add(verts, [(o + 1, o + 2, q + 2, q + 1)], side_mat)
        b.add(verts, [(o + 2, o + 3, q + 3, q + 2)], side_mat)
        b.add(verts, [(o + 3, o + 0, q + 0, q + 3)], side_mat)

def barge(x, y, ang, L=6.5, W=1.8):
    b = B("Barge")
    hull(b, L, W, 0.22, RIDGE, BOAT_DECK, flat=True)
    box(b, 0.3, 0, 0.22, L * 0.55, W * 0.72, 0.38, BOAT_WOOD)               # 货舱
    box(b, -L * 0.38, 0, 0.22, 1.0, W * 0.7, 0.65, WHITE_WALL)             # 驾驶楼
    box(b, -L * 0.38, 0, 0.87, 0.6, W * 0.5, 0.12, RIDGE)
    b.build(loc=(x, y, 0), rot=ang)

def cruise(x, y, ang, L=8.5, W=2.3):
    b = B("Cruise")
    hull(b, L, W, 0.3, WHITE_HULL, BOAT_DECK)
    box(b, 0.2, 0, 0.3, L * 0.68, W * 0.86, 0.6, WHITE_HULL)
    box(b, 0.2, 0, 0.42, L * 0.68 + 0.04, W * 0.86 + 0.04, 0.18, LATTICE)   # 一层舷窗
    box(b, 0.5, 0, 0.9, L * 0.5, W * 0.72, 0.5, WHITE_HULL)
    box(b, 0.5, 0, 1.0, L * 0.5 + 0.04, W * 0.72 + 0.04, 0.16, LATTICE)
    box(b, 1.2, 0, 1.4, L * 0.22, W * 0.55, 0.35, WHITE_HULL)
    prism(b, -L * 0.15, 0, 1.4, 0.18, 0.7, BOAT_RED, n=8)
    b.build(loc=(x, y, 0), rot=ang)

def path(b, pts, w=0.9, mat=STONE, lift=0.03):
    P, L = polyline(pts)
    s = 0.0
    while s < L:
        x, y, dx, dy = P(s)
        rbox(b, x, y, ground(x, y) + lift - 0.05, 1.6, w, 0.06, mat, math.atan2(dy, dx))
        s += 1.4

# ----------------------------------------------------------------------------- 场景布置
def build_scene():
    make_variants()
    island()
    P_r, L_r = polyline(RIVER)
    TX, TY = 12.0, -6.0
    TZ = ground(TX, TY)

    # ---- 黄鹤楼：台地、三层石台、五层楼阁
    b = B("CraneTower")
    crane_tower(b, TX, TY, TZ)
    b.build()

    # ---- 公园：广场、牌坊、碑廊、亭台、白云阁、鹅池、千禧钟、山径
    b = B("Park")
    box(b, TX, TY, TZ - 0.15, 31.0, 31.0, 0.17, STONE)                                 # 台地石板广场
    rbox(b, TX, TY - 19.0, TZ - 0.12, 14.0, 6.0, 0.18, STONE, 0)                    # 南广场
    hall_jn(b, TX, TY - 21.5, 3.6, 0.8, 1.1, roof=GOLD, wall=COLUMN, z0=TZ, plat=0.1, ridge=0.85)   # 牌坊
    hall_jn(b, TX, TY - 27.5, 3.0, 0.7, 1.0, roof=GOLD, wall=COLUMN, plat=0.1, ridge=0.85)        # 第二道牌坊
    for sx in (-1, 1):
        hall_jn(b, TX + sx * 9.5, TY - 16.0, 1.6, 5.5, 0.8, roof=DARK_TILE, wall=RED_WALL, z0=TZ, plat=0.08, ridge=0.9)   # 碑廊（朱红）
    pavilion_jn(b, TX + 9.0, TY + 8.5, 1.2, 0.95, n=6, z0=TZ, roof=GOLD)                   # 千禧钟亭
    pavilion_jn(b, TX - 9.0, TY + 8.0, 1.0, 0.9, n=4, roof=GOLD)                           # 词亭
    hall_jn(b, TX, TY + 11.5, 4.2, 2.0, 1.0, roof=GOLD, double=True, stair=True)           # 后殿
    bz = crane_tower(b, 44.0, -2.0, ground(44.0, -2.0), stories=3, w=6.5, story_h=1.3, platform=False)   # 白云阁
    pavilion_jn(b, 30.0, -12.0, 1.1, 0.9, n=6, roof=GOLD)
    pavilion_jn(b, 56.0, 3.0, 1.0, 0.85, n=6)
    pavilion_jn(b, 22.0, 6.0, 1.0, 0.85, n=8, roof=GOLD)
    hall_jn(b, 34.0, 6.5, 3.2, 1.8, 0.9, wall=RED_WALL)
    hall_jn(b, 50.0, -8.0, 3.0, 1.6, 0.9, double=True, wall=RED_WALL)
    # 辛亥革命武昌起义纪念馆（红楼）：山脚的红砖院落
    compound(b, 30.0, -34.0, 11.0, 7.0, RED_BRICK, nh=1, roof=DARK_TILE)
    # 鹅池
    pz = base_z(30.0, -18.0, 7, 7)
    prism(b, 30.0, -18.0, pz - 0.4, 3.0, 0.5, GRANITE, n=24)
    prism(b, 30.0, -18.0, pz + 0.11, 2.7, 0.04, WATER, n=24)
    keep(30.0, -18.0, 3.6)
    for k in range(8):
        a = 2 * math.pi * k / 8
        plant("bush", 30.0 + 3.6 * math.cos(a), -18.0 + 3.6 * math.sin(a), random.uniform(1.0, 1.5))
    pavilion_jn(b, 33.8, -18.0, 0.9, 0.8, n=6, roof=GOLD)
    # 山径与台阶
    path(b, [(TX, TY - 24.0), (TX - 3.0, TY - 30.0), (TX - 9.0, TY - 34.0), (TX - 14.0, TY - 40.0)])
    path(b, [(TX + 7.0, TY - 19.0), (TX + 16.0, TY - 16.0), (TX + 24.0, TY - 10.0), (TX + 32.0, TY - 4.0), (TX + 32.0, 0.0)])
    path(b, [(TX - 7.0, TY - 19.0), (TX - 14.0, TY - 14.0), (TX - 18.0, TY - 6.0), (TX - 14.0, TY + 4.0), (TX - 6.0, TY + 10.0)])
    path(b, [(TX, TY + 14.0), (TX + 2.0, TY + 20.0), (TX + 8.0, TY + 26.0)])
    b.build()
    for k in range(28):
        a = 2 * math.pi * k / 28
        rr = 16.2 + random.uniform(-0.6, 0.6)
        x, y = TX + rr * math.cos(a), TY + rr * math.sin(a)
        if not blocked(x, y):
            plant("pine" if k % 3 else "tree", x, y, random.uniform(1.5, 2.1))
    for i in range(110):
        x, y = random.uniform(-6, 64), random.uniform(-24, 14)
        if not blocked(x, y) and lake_depth(x, y) < -3:
            plant(random.choice(["pine", "pine", "tree", "maple", "ginkgo", "peach"]), x, y, random.uniform(1.3, 1.9))

    # ---- 武汉长江大桥 + 对岸龟山、电视塔、晴川阁
    b = B("Bridge")
    yangtze_bridge(b, (-2.0, -31.0), (-66.0, -6.0))
    b.build()
    b = B("WestBank")
    tv_tower(b, -78.0, 12.0, ground(-78.0, 12.0))
    hall_jn(b, -56.0, 12.0, 3.6, 2.0, 1.1, roof=DARK_TILE, double=True, stair=True)     # 晴川阁
    pavilion_jn(b, -62.0, 20.0, 1.0, 0.85, n=6)
    hall_jn(b, -70.0, 24.0, 3.0, 1.6, 0.9)
    b.build()

    # ---- 滨江大道与江滩：沿两岸的道路、垂柳、草坡
    b = B("Roads")
    for side in (1, -1):
        s = 10.0
        while s < L_r - 10.0:
            x, y, dx, dy = P_r(s)
            nx, ny = -dy, dx
            off = side * (RIVER_HW * (1 + 0.08 * math.sin(y * 0.05 + 1.0)) + 4.5)
            rx, ry = x + nx * off, y + ny * off
            if isl_rho(rx, ry)[0] < 0.97 and ground(rx, ry) < 2.0 and not blocked(rx, ry):
                rbox(b, rx, ry, ground(rx, ry) - 0.02, 2.4, 1.8, 0.05, ASPHALT, math.atan2(dy, dx))
            s += 2.0
    # 老城街道（近岸南北两片）
    for (x0s, y0s, x1s, y1s) in ((-6, -70, 62, -30), (-2, 18, 62, 78)):
        for yy in range(int(y0s) + 6, int(y1s) - 4, 12):
            rbox(b, (x0s + x1s) / 2, yy, 0.27, x1s - x0s, 1.6, 0.05, STONE, 0)
        for xx in range(int(x0s) + 8, int(x1s) - 4, 16):
            rbox(b, xx, (y0s + y1s) / 2, 0.27, 1.6, y1s - y0s, 0.05, STONE, 0)
    b.build()
    for s in [i * 2.2 for i in range(int(L_r / 2.2))]:
        x, y, dx, dy = P_r(s)
        nx, ny = -dy, dx
        for side in (1, -1):
            off = side * (RIVER_HW * (1 + 0.08 * math.sin(y * 0.05 + 1.0)) + random.uniform(1.2, 2.6))
            tx, ty = x + nx * off, y + ny * off
            if isl_rho(tx, ty)[0] < 0.975 and ground(tx, ty) < 1.5 and not blocked(tx, ty) and random.random() < 0.8:
                plant("willow" if random.random() < 0.7 else "tree", tx, ty, random.uniform(1.4, 1.9))

    # ---- 近岸老城（武昌）与对岸（汉阳）的粉墙黛瓦
    def town(x0s, y0s, x1s, y1s, bw=11.0, bd=9.0, street=2.2, density=0.85):
        """街区式老城：街道网格、每个街区一块铺地与沿街对齐的房屋，偶有院落与行道树。"""
        bb = B("Town")
        x = x0s
        while x + bw < x1s:
            y = y0s
            while y + bd < y1s:
                cx, cy = x + bw / 2, y + bd / 2
                ok = (lake_depth(cx, cy) < -4 and ground(cx, cy) < 1.6 and isl_rho(cx, cy)[0] < 0.94
                      and not blocked(cx, cy) and random.random() < density)
                if ok:
                    gz = max(ground(cx + sx * bw / 2, cy + sy * bd / 2) for sx in (-1, 1) for sy in (-1, 1))
                    box(bb, cx, cy, gz - 0.35, bw + street * 0.8, bd + street * 0.8, 0.42, STONE)   # 街区铺地（含街道）
                    keep(cx, cy, max(bw, bd) * 0.75)
                    if random.random() < 0.12:
                        hall_jn(bb, cx, cy, random.uniform(3.2, 4.2), random.uniform(2.0, 2.6), 1.15, z0=gz + 0.07, double=random.random() < 0.5, stair=True)
                    else:
                        # 沿街两排房屋 + 中间院落树
                        for row, sy in ((0, -1), (1, 1)):
                            n = random.randint(3, 4)
                            for k in range(n):
                                w = bw / n - 0.5
                                hx = x + w / 2 + 0.25 + k * (bw / n)
                                hy = cy + sy * (bd / 2 - 1.3)
                                hh = random.uniform(0.7, 1.15)
                                house(hx, hy, w, random.uniform(1.8, 2.3), hh, 0.0 if random.random() < 0.85 else math.pi / 2)
                        if random.random() < 0.7:
                            plant(random.choice(["tree", "tree", "willow"]), cx + random.uniform(-2, 2), cy + random.uniform(-0.8, 0.8), random.uniform(1.1, 1.6), z=gz + 0.07)
                    if random.random() < 0.5:
                        plant("tree", x + bw + street / 2, y + random.uniform(1, bd - 1), random.uniform(1.0, 1.4))
                y += bd + street
            x += bw + street
        bb.build()
    town(-6, -56, 44, -28)
    town(-2, 16, 44, 44)
    town(-92, -40, -62, 50, density=0.6)
    city(6, -80, 70, -58)                      # 武昌南侧高楼
    city(46, -58, 72, -22)
    city(6, 46, 70, 76)                         # 北侧
    city(46, 16, 72, 46)
    city(-102, -72, -64, -42, floors=(4, 10))   # 汉阳
    city(-102, 50, -62, 72, floors=(4, 10))
    for i in range(520):
        x, y = random.uniform(-100, 62), random.uniform(-72, 72)
        if lake_depth(x, y) < -3 and ground(x, y) < 1.6 and not blocked(x, y) and isl_rho(x, y)[0] < 0.96:
            plant(random.choice(["tree", "tree", "willow", "bush", "ginkgo", "maple"]), x, y, random.uniform(1.2, 1.8))

    # ---- 江上船只：沿河道中心线
    for (s, off, kind, flip) in ((22, -4, 'barge', 0), (36, 6, 'barge', 1), (58, -7, 'cruise', 0), (74, 3, 'barge', 1),
                                 (96, -5, 'barge', 0), (118, 7, 'cruise', 1), (134, -3, 'barge', 0), (150, 5, 'barge', 1),
                                 (44, 11, 'small', 0), (86, -12, 'small', 1), (110, 12, 'small', 0), (164, -9, 'small', 1), (30, 13, 'small', 0)):
        x, y, dx, dy = P_r(s)
        nx, ny = -dy, dx
        px, py = x + nx * off, y + ny * off
        ang = math.atan2(dy, dx) + (math.pi if flip else 0) + random.uniform(-0.08, 0.08)
        if kind == 'barge':
            barge(px, py, ang)
        elif kind == 'cruise':
            cruise(px, py, ang)
        else:
            boat(px, py, ang, 1.8, 0.7, canopy=False)

    # ---- 山林（蛇山、龟山、远山）
    x0, y0, x1, y1 = ISL
    cnt = 0
    y = y0 + 1.0
    while y < y1 - 1.0:
        x = x0 + 1.0
        while x < x1 - 1.0:
            xx, yy = x + random.uniform(-0.5, 0.5), y + random.uniform(-0.5, 0.5)
            rho, _, _ = isl_rho(xx, yy)
            if rho < 0.985:
                z, k = terrain(xx, yy)
                if k == 'land' and 1.2 < z < 40.0 and not blocked(xx, yy):
                    zx = ground(xx + 0.6, yy) - ground(xx - 0.6, yy)
                    zy = ground(xx, yy + 0.6) - ground(xx, yy - 0.6)
                    slope = math.hypot(zx, zy) / 1.2
                    dens = 0.85 + 0.3 * (fbm(xx * 0.1 + 2, yy * 0.1 + 4, 3) - 0.5)
                    if slope < 2.2 and random.random() < dens:
                        rr = random.random()
                        kind = "maple" if rr < 0.07 else ("ginkgo" if rr < 0.12 else ("pine" if (z > 4 or rr < 0.65) else "tree"))
                        plant(kind, xx, yy, random.uniform(1.0, 1.6) * (1.0 if z < 10 else 0.85))
                        cnt += 1
            x += 0.9
        y += 0.9
    # 平地散树与灌木
    for i in range(900):
        x, y = random.uniform(x0, x1), random.uniform(y0, y1)
        rho, _, _ = isl_rho(x, y)
        if rho > 0.97 or blocked(x, y):
            continue
        z, k = terrain(x, y)
        if k == 'land' and z < 1.2 and lake_depth(x, y) < -2 and random.random() < 0.6:
            plant(random.choice(["tree", "willow", "bush"]), x, y, random.uniform(1.2, 1.7))
    for i in range(1800):
        x, y = random.uniform(x0, x1), random.uniform(y0, y1)
        if isl_rho(x, y)[0] > 0.97 or blocked(x, y):
            continue
        z, k = terrain(x, y)
        if k == 'land' and z < 9.0 and -16 < lake_depth(x, y) < -0.8 and random.random() < 0.7:
            plant("bush", x, y, random.uniform(0.9, 1.6))
    print(f"[yc] hill trees={cnt}, plants total={N_PLANTS}")


# ----------------------------------------------------------------------------- 相机 / 灯光 / 雾 / 背景
def setup_camera_lights():
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 45
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("Camera", cam_data)
    COL.objects.link(cam)
    target = (-4.0, -9.0, 0.0)
    az = math.radians(36)
    dist = 232.0
    pitch = math.radians(36)
    hx, hy = math.sin(az), -math.cos(az)
    cam.location = (target[0] + hx * dist * math.cos(pitch), target[1] + hy * dist * math.cos(pitch),
                    target[2] + dist * math.sin(pitch))
    direction = mathutils.Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    focus = bpy.data.objects.new("Focus", None)
    focus.location = (0.0, -6.0, 0.5)
    COL.objects.link(focus)
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = focus
    cam_data.dof.aperture_fstop = 1.1

    # 晨光：东北偏东、仰角 26°，偏暖
    sun_data = bpy.data.lights.new("Sun", 'SUN')
    sun_data.energy = 3.8
    sun_data.color = (1.0, 0.87, 0.68)
    sun_data.angle = math.radians(2.5)
    sun = bpy.data.objects.new("Sun", sun_data)
    COL.objects.link(sun)
    sun.rotation_euler = mathutils.Euler((math.radians(65), 0, math.radians(318)), 'XYZ')   # 西南方低角度金色阳光
    if "--sunonly" in argv:
        sun_data.energy = 1.6
    fill_data = bpy.data.lights.new("Fill", 'AREA')
    fill_data.energy = 250
    fill_data.size = 220
    fill_data.color = (0.78, 0.88, 1.0)
    fill = bpy.data.objects.new("Fill", fill_data)
    COL.objects.link(fill)
    fill.location = (-220, 60, 180)
    d = mathutils.Vector((0, 0, 0)) - fill.location
    fill.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    if "--sunonly" in argv:
        fill_data.energy = 0.0

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    bg = wnt.nodes["Background"]
    hdr = os.path.normpath(os.path.join(HERE, "..", "assets", "polyhaven", "hdris", "belfast_sunset_puresky_2k.hdr"))
    if os.path.exists(hdr) and "--nohdri" not in argv:
        # HDRI 天空提供环境光与水面倒影；把 HDRI 里的太阳转到主光方向（东北偏东，方位 28°）
        img = bpy.data.images.load(hdr, check_existing=True)
        u = hdri_sun_u(img)
        rot = (360.0 * u - 225.0) if u is not None else 0.0
        env = wnt.nodes.new("ShaderNodeTexEnvironment")
        env.image = img
        wtc = wnt.nodes.new("ShaderNodeTexCoord")
        wmp = wnt.nodes.new("ShaderNodeMapping")
        wmp.inputs["Rotation"].default_value = (0, 0, math.radians(rot))
        wnt.links.new(wtc.outputs["Generated"], wmp.inputs["Vector"])
        wnt.links.new(wmp.outputs["Vector"], env.inputs["Vector"])
        wnt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.03 if "--sunonly" in argv else 0.3
        print(f"[yc] hdri sun u={u} rot={rot:.1f}")
    else:
        bg.inputs["Color"].default_value = (0.80, 0.87, 0.95, 1)
        bg.inputs["Strength"].default_value = 0.03 if "--sunonly" in argv else 0.2

    # 纯净背景：只对相机可见的自发光背板（冷调浅灰绿渐变）
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
    rp = ramp(nt, [(0.0, (0.90, 0.85, 0.72)), (1.0, (0.94, 0.90, 0.79))])
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], rp.inputs["Fac"])
    nt.links.new(rp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    me = bpy.data.meshes.new("Backdrop")
    S = 1800.0
    me.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    me.materials.append(bd)
    plane = bpy.data.objects.new("Backdrop", me)
    COL.objects.link(plane)
    view_dir = (mathutils.Vector(target) - cam.location).normalized()
    plane.location = cam.location + view_dir * 800.0
    plane.rotation_euler = view_dir.to_track_quat('Z', 'Y').to_euler()
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow"):   # 倒影由 HDRI 天空提供
        if hasattr(plane, attr):
            setattr(plane, attr, False)

def hdri_sun_u(img):
    """在等距柱状 HDRI 里找最亮像素的 u 坐标（0..1），用于对齐太阳方位。"""
    try:
        import numpy as np
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
        lum = px[:, :, 0] * 0.3 + px[:, :, 1] * 0.59 + px[:, :, 2] * 0.11
        j, i = np.unravel_index(int(np.argmax(lum)), lum.shape)
        return i / w
    except Exception as e:
        print("[yc] hdri sun search failed:", e)
        return None

def volume_box(name, x0, y0, z0, x1, y1, z1, density, color, aniso, gradient=None, noise_scale=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != 'OUTPUT_MATERIAL':
            nt.nodes.remove(n)
    out = nt.nodes["Material Output"]
    sc = nt.nodes.new("ShaderNodeVolumeScatter")
    sc.inputs["Color"].default_value = (*color, 1)
    sc.inputs["Anisotropy"].default_value = aniso
    if gradient is not None:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
        dens = map_range(nt, sep.outputs["Z"], density, 0.0, gradient[0], gradient[1])
        if noise_scale > 0:
            nz = nt.nodes.new("ShaderNodeTexNoise")
            nz.inputs["Scale"].default_value = noise_scale
            nz.inputs["Detail"].default_value = 2.0
            nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
            mul = nt.nodes.new("ShaderNodeMath"); mul.operation = 'MULTIPLY'
            nt.links.new(dens, mul.inputs[0])
            nt.links.new(map_range(nt, nz.outputs["Fac"], 0.3, 1.5), mul.inputs[1])
            dens = mul.outputs[0]
        nt.links.new(dens, sc.inputs["Density"])
    else:
        sc.inputs["Density"].default_value = density
    nt.links.new(sc.outputs["Volume"], out.inputs["Volume"])
    v, f = box_geo((x0 + x1) / 2, (y0 + y1) / 2, z0, x1 - x0, y1 - y0, z1 - z0)
    me = bpy.data.meshes.new(name)
    me.from_pydata(v, [], f)
    me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    COL.objects.link(ob)
    if hasattr(ob, "visible_shadow"):
        ob.visible_shadow = False
    return ob

def setup_mist():
    if NOMIST:
        return
    x0, y0, x1, y1 = ISL
    # 湖面薄雾：贴水低雾，随高度消散，带斑块（远景空气透视改在材质里按视距混色，见 add_fog）
    volume_box("RiverMist", -84, -100, -0.6, 48, 100, 1.5, 0.014, (0.95, 0.92, 0.85), 0.4, gradient=(-0.6, 1.5), noise_scale=0.035)

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
    scene.cycles.transmission_bounces = 4
    scene.cycles.volume_bounces = 0
    scene.cycles.volume_step_rate = 4.0
    scene.cycles.volume_max_steps = 48
    scene.cycles.transparent_max_bounces = 24   # 密林里 alpha 叶片层数多，太低会把树冠和树下算成黑色
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
    vs.view_transform = 'Standard'   # AgX/Filmic 会把浅色背景板压灰、绿色变闷
    vs.look = 'None'
    vs.exposure = 0.1
    vs.gamma = 1.0
    scene.render.filter_size = 1.6
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
build_scene()
setup_camera_lights()
print(f"[yc] scene built in {time.time() - t0:.1f}s, objects={len(COL.objects)}")
if WEB:
    # 网页版：导出 glb + scene.json（见 tools/diorama_export.py）；树木为实例数据，网页里用卡片树
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "tools")))
    import diorama_export as de
    def _vcol(mn, ob, co, nrm):
        if mn not in ("Terrain", "LakeBed", "EarthCut"):
            return None
        if co is None:
            return (1, 1, 1)
        if mn == "EarthCut":
            return de.strata(co.z)
        if mn == "LakeBed":
            return de.ramp([(0.0, (0.05, 0.20, 0.15)), (0.6, (0.20, 0.42, 0.28)), (1.0, (0.60, 0.60, 0.44))], (co.z + 1.8) / 1.7)
        f = de.smooth01((co.z - 0.9) / 2.5)
        hi = (0.42, 0.50, 0.40) if nrm.z < 0.45 else (0.45, 0.62, 0.42)
        lo = (1.0, 1.0, 0.85)
        return tuple(lo[i] + (hi[i] - lo[i]) * f for i in range(3))
    de.export_scene(arg("--export-glb", os.path.join(HERE, "web")), {"Backdrop", "Haze", "RiverMist"}, _vcol, uv_scale=1.0, extra={
        "title": "武汉黄鹤楼", "unit_m": 12,
        "camera": {"target": [-4, -9, 0], "az": 36, "dist": 232, "pitch": 36, "lens": 45, "min_dist": 50, "max_dist": 520},
        "sun": {"euler_deg": [65, 0, 318], "color": [1.0, 0.86, 0.66], "strength": 3.6},
        "backdrop": [[0.90, 0.85, 0.72], [0.94, 0.90, 0.79]],
        "water": ["RiverWater"], "bounds": list(ISL), "shadow_half": 115, "fog": [0.92, 0.88, 0.78],
        "hdri": "belfast_sunset_puresky_1k.hdr",
        "plants": PLANTS, "plant_kinds": {k: len(v) for k, v in LIB_TREES.items()},
        "plant_src": {"peach": "willow", "maple": "tree", "ginkgo": "tree"},
        "plant_tint": {"peach": "rgba(245,150,175,0.72)", "maple": "rgba(190,40,25,0.8)", "ginkgo": "rgba(240,185,50,0.82)"}})
    print(f"[yc] web export done in {time.time() - t0:.1f}s, plants={len(PLANTS)}")
else:
    setup_mist()
    setup_render()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if SAVE_BLEND:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.splitext(OUT)[0] + ".blend")
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[yc] rendered {OUT} in {time.time() - t1:.1f}s ({PCT}% / {SAMPLES} spp)")