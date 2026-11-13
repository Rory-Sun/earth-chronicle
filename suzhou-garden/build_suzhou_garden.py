# -*- coding: utf-8 -*-
"""
苏州古典园林微缩立体景观（沙盘）— 过程化生成 + Cycles 渲染（Blender 5.x, headless）

用法：
  "D:/install/blender/blender.exe" --background --python suzhou-garden/build_suzhou_garden.py -- \
      [--pct 100] [--samples 64] [--out suzhou-garden/output/suzhou_garden/suzhou_garden.png] [--save]
      [--border x0 y0 x1 y1] [--export-glb public/dioramas/suzhou-garden]

单位：1 个 Blender 单位 = 1 米。y 轴正方向为北，x 轴正方向为东。池水水面 z = 0，庭院地面 z = 0.45。
布局以网师园为蓝本：池居中，四面厅在北岸，曲廊与六角亭在西岸，太湖石假山在西南，水阁在南岸，
东侧为门厅—大厅—内厅—后楼一路住宅院落，东北角是开月洞门的书斋小院。
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
SAMPLES = int(arg("--samples", 64))
HERE = os.path.dirname(os.path.abspath(__file__))
TEX_DIR = os.path.normpath(os.path.join(HERE, "..", "assets", "textures_cc0"))   # ambientCG CC0 贴图（各沙盘共用）
OUT = os.path.abspath(arg("--out", os.path.join(HERE, "output", "suzhou_garden", "suzhou_garden.png")))
SAVE_BLEND = "--save" in argv
WEB = "--export-glb" in argv          # 网页导出模式：树木只记录实例数据，不加载模型
PLANTS = []                           # [kind, variant, x, y, z, height, rot]
INST = {}                             # 网页版实例：库物体名 -> [[x, y, z, sx, sy, sz, rx, ry, rz], ...]
def _lib(me):
    """网页导出时把被多处复用的网格作为一个库物体导出一次，各处只记位置。"""
    name = "Lib_" + me.name
    if name not in INST:
        INST[name] = []
        ob = bpy.data.objects.new(name, me)
        COL.objects.link(ob)
    return INST[name]
random.seed(11)
ru = random.uniform

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = bpy.data.collections.new("SuzhouGarden")
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

# 远景空气透视：按视距把表面向雾色混合（只对相机光线生效，比体积雾便宜得多）
def add_fog(mat, near=250.0, far=480.0, maxf=0.12, color=(0.84, 0.92, 0.96)):
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


def noise_mapped(nt, scale_vec, nscale=1.0, detail=3.0, distortion=0.0):
    """按轴向不同比例取样的噪波（竖向雨痕、横向水渍）。"""
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = scale_vec
    nt.links.new(texcoord(nt).outputs["Object"], mp.inputs["Vector"])
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = nscale
    n.inputs["Detail"].default_value = detail
    if "Distortion" in n.inputs:
        n.inputs["Distortion"].default_value = distortion
    nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    return n

def clampv(sock):
    sock.node.clamp = True
    return sock

GZ = 0.45   # 庭院地面高程（水面 z = 0）

# ----------------------------------------------------------------------------- 材质
# 黛瓦：屋面底瓦用贴图，筒瓦垄是真几何
DARK_TILE = tile_material("DaiWa", (0.105, 0.11, 0.12), (0.20, 0.21, 0.22), rough=0.6, coat=0.05, sc=0.55)
_bv = DARK_TILE.node_tree.nodes.get("EdgeBevel")      # 屋面面积大，倒角着色很耗时；瓦垄已是真几何，去掉
if _bv is not None:
    DARK_TILE.node_tree.nodes.remove(_bv)
TILE_ROW = noise_mix(principled("WaLong", (0.12, 0.125, 0.135), rough=0.55, bevel=0), (0.085, 0.09, 0.10), (0.20, 0.21, 0.22), 2.6, detail=4.0)
RIDGE = noise_mix(principled("WuJi", (0.10, 0.10, 0.11), rough=0.65, bevel=0.02), (0.08, 0.08, 0.09), (0.16, 0.16, 0.17), 3.0)
# 粉墙：白灰墙面，檐下有竖向雨痕，墙脚返潮发青
WHITE_WALL = principled("FenQiang", (0.86, 0.85, 0.81), rough=0.9, bevel=0)
nt = WHITE_WALL.node_tree
_p = nt.nodes["Principled BSDF"]
_sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(texcoord(nt).outputs["Object"], _sep.inputs["Vector"])
_n0 = noise(nt, 0.7, 3.0)
_col = mul_color(nt, rgb(nt, (0.86, 0.85, 0.81)), map_range(nt, _n0.outputs["Fac"], 0.93, 1.04))
_st = noise_mapped(nt, (2.4, 2.4, 0.16), detail=3.0)
_pt = noise(nt, 0.22, 2.0)
_sf = nt.nodes.new("ShaderNodeMath"); _sf.operation = 'MULTIPLY'
nt.links.new(clampv(map_range(nt, _st.outputs["Fac"], 0.0, 1.0, 0.50, 0.72)), _sf.inputs[0])
nt.links.new(clampv(map_range(nt, _pt.outputs["Fac"], 0.0, 0.75, 0.40, 0.62)), _sf.inputs[1])
_col = mix_rgb(nt, _col, rgb(nt, (0.60, 0.61, 0.57)), _sf.outputs[0], 'MIX')
_dn = noise(nt, 1.6, 3.0)
_df = nt.nodes.new("ShaderNodeMath"); _df.operation = 'MULTIPLY'
nt.links.new(clampv(map_range(nt, _sep.outputs["Z"], 1.0, 0.0, GZ + 0.05, GZ + 1.0)), _df.inputs[0])
nt.links.new(clampv(map_range(nt, _dn.outputs["Fac"], 0.25, 1.0, 0.30, 0.65)), _df.inputs[1])
_col = mix_rgb(nt, _col, rgb(nt, (0.44, 0.47, 0.38)), _df.outputs[0], 'MIX')
nt.links.new(_col, _p.inputs["Base Color"])
_wb = bump_node(nt, _n0.outputs["Fac"], 0.25, 0.02)
nt.links.new(_wb.outputs["Normal"], _p.inputs["Normal"])

WOOD = principled("LiKeMu", (0.20, 0.095, 0.055), rough=0.5, coat=0.15)        # 栗壳色木作
LATTICE = principled("ChuangGe", (0.14, 0.07, 0.042), rough=0.55, bevel=0)      # 窗格、挂落
GLASS_DARK = principled("ChuangAn", (0.030, 0.027, 0.025), rough=0.12, spec=0.6, bevel=0)
GRANITE = noise_mix(principled("JinShanShi", (0.56, 0.55, 0.51), rough=0.85, bevel=0.03), (0.47, 0.46, 0.42), (0.64, 0.63, 0.59), 2.5, detail=5.0, bump=0.25)
SLAB = noise_mix(principled("ShiBan", (0.48, 0.48, 0.45), rough=0.9, bevel=0.03), (0.38, 0.39, 0.36), (0.57, 0.57, 0.53), 1.6, detail=5.0, bump=0.3)
GREYBRICK = noise_mix(principled("QingZhuan", (0.30, 0.31, 0.31), rough=0.85, bevel=0.02), (0.24, 0.25, 0.25), (0.37, 0.38, 0.38), 4.0, bump=0.2)
POT = principled("TaoPen", (0.34, 0.19, 0.12), rough=0.7)
# 方砖铺地
PAVE = principled("FangZhuan", (0.50, 0.50, 0.48), rough=0.9, bevel=0)
nt = PAVE.node_tree
_c = tex_node(nt, "PavingStones128", "Color", 0.42, 'Object', noncolor=False)
_r = tex_node(nt, "PavingStones128", "Roughness", 0.42, 'Object')
_d = tex_node(nt, "PavingStones128", "Displacement", 0.42, 'Object')
_a = tex_node(nt, "PavingStones128", "AmbientOcclusion", 0.42, 'Object')
_pn = noise(nt, 0.5, 3.0)
_col = mul_color(nt, _c.outputs["Color"], _a.outputs["Color"], 0.7)
_col = mul_color(nt, _col, mul_color(nt, rgb(nt, (0.86, 0.88, 0.86)), map_range(nt, _pn.outputs["Fac"], 0.78, 1.12)))
_mossf = clampv(map_range(nt, noise(nt, 0.9, 4.0).outputs["Fac"], 0.0, 0.45, 0.56, 0.72))     # 砖缝青苔斑
_col = mix_rgb(nt, _col, rgb(nt, (0.20, 0.27, 0.13)), _mossf, 'MIX')
nt.links.new(_col, nt.nodes["Principled BSDF"].inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.65, 0.95), nt.nodes["Principled BSDF"].inputs["Roughness"])
tex_bump(nt, _d, 0.8, 0.03)
# 街巷条石
STREET = principled("JieShi", (0.50, 0.50, 0.47), rough=0.9, bevel=0)
nt = STREET.node_tree
_c = tex_node(nt, "PavingStones128", "Color", 0.36, 'Object', noncolor=False)
_d = tex_node(nt, "PavingStones128", "Displacement", 0.36, 'Object')
_a = tex_node(nt, "PavingStones128", "AmbientOcclusion", 0.36, 'Object')
_col = mul_color(nt, _c.outputs["Color"], _a.outputs["Color"], 0.8)
_col = mul_color(nt, _col, mul_color(nt, rgb(nt, (0.80, 0.80, 0.77)), map_range(nt, noise(nt, 0.25, 4.0, distortion=0.6).outputs["Fac"], 0.72, 1.16)))
nt.links.new(_col, nt.nodes["Principled BSDF"].inputs["Base Color"])
tex_bump(nt, _d, 1.0, 0.05)
# 花街铺地：卵石
PEBBLE = principled("HuaJie", (0.48, 0.46, 0.41), rough=0.8, bevel=0)
nt = PEBBLE.node_tree
_v = nt.nodes.new("ShaderNodeTexVoronoi")
_v.inputs["Scale"].default_value = 14.0
nt.links.new(texcoord(nt).outputs["Object"], _v.inputs["Vector"])
_vr = ramp(nt, [(0.0, (0.30, 0.29, 0.27)), (0.35, (0.55, 0.52, 0.45)), (0.7, (0.44, 0.36, 0.28)), (1.0, (0.66, 0.64, 0.58))])
_vs = nt.nodes.new("ShaderNodeSeparateColor")
nt.links.new(_v.outputs["Color"], _vs.inputs["Color"])
nt.links.new(_vs.outputs[0], _vr.inputs["Fac"])
_ve = clampv(map_range(nt, _v.outputs["Distance"], 1.0, 0.45, 0.25, 0.60))
nt.links.new(mul_color(nt, _vr.outputs["Color"], _ve), nt.nodes["Principled BSDF"].inputs["Base Color"])
_vb = bump_node(nt, _v.outputs["Distance"], -0.8, 0.02)
nt.links.new(_vb.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])
# 苔地：泥土上成片的青苔与地被，不是草坪
TERRAIN = principled("TaiDi", (0.20, 0.26, 0.12), rough=0.95, bevel=0)
nt = TERRAIN.node_tree
_p = nt.nodes["Principled BSDF"]
_gc = tex_node(nt, "Grass004", "Color", 0.33, 'Object', noncolor=False)
_gd = tex_node(nt, "Grass004", "Displacement", 0.33, 'Object')
_moss = mul_color(nt, _gc.outputs["Color"], rgb(nt, (0.50, 0.57, 0.35)))
_mn = noise(nt, 0.55, 4.0, distortion=0.6)
_moss = mix_rgb(nt, _moss, rgb(nt, (0.17, 0.25, 0.10)), clampv(map_range(nt, _mn.outputs["Fac"], 0.0, 0.65, 0.44, 0.68)), 'MIX')
_sn = noise(nt, 0.20, 4.0, distortion=0.8)
_soil = mul_color(nt, rgb(nt, (0.19, 0.155, 0.11)), map_range(nt, noise(nt, 3.0, 4.0).outputs["Fac"], 0.75, 1.25))
_col = mix_rgb(nt, _moss, _soil, clampv(map_range(nt, _sn.outputs["Fac"], 0.0, 0.9, 0.46, 0.64)), 'MIX')
nt.links.new(_col, _p.inputs["Base Color"])
_tb = bump_node(nt, noise(nt, 2.4, 5.0).outputs["Fac"], 0.5, 0.06)
tex_bump(nt, _gd, 0.6, 0.03, prev_normal=_tb.outputs["Normal"])
# 池底
POND_BED = principled("ChiDi", (0.10, 0.13, 0.08), rough=0.9, bevel=0)
nt = POND_BED.node_tree
_sep = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(texcoord(nt).outputs["Object"], _sep.inputs["Vector"])
_br = ramp(nt, [(0.0, (0.035, 0.060, 0.040)), (0.6, (0.075, 0.115, 0.070)), (1.0, (0.24, 0.25, 0.17))])
nt.links.new(map_range(nt, _sep.outputs["Z"], 0.0, 1.0, -1.25, 0.0), _br.inputs["Fac"])
nt.links.new(mul_color(nt, _br.outputs["Color"], map_range(nt, noise(nt, 1.5, 4.0).outputs["Fac"], 0.8, 1.2)), nt.nodes["Principled BSDF"].inputs["Base Color"])
# 太湖石：浅灰带暖，孔洞与凹处发暗，顶面和背阴处生苔
TAIHU = principled("TaiHuShi", (0.60, 0.60, 0.57), rough=0.85, bevel=0)
nt = TAIHU.node_tree
_p = nt.nodes["Principled BSDF"]
_geo = nt.nodes.new("ShaderNodeNewGeometry")
_n1 = noise(nt, 2.0, 5.0, distortion=1.0)
_tr = ramp(nt, [(0.25, (0.33, 0.33, 0.32)), (0.55, (0.53, 0.53, 0.50)), (0.8, (0.67, 0.66, 0.62))])
nt.links.new(_n1.outputs["Fac"], _tr.inputs["Fac"])
_col = mul_color(nt, _tr.outputs["Color"], clampv(map_range(nt, _geo.outputs["Pointiness"], 0.22, 1.12, 0.43, 0.56)))
_ns = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(_geo.outputs["Normal"], _ns.inputs["Vector"])
_mf = nt.nodes.new("ShaderNodeMath"); _mf.operation = 'MULTIPLY'
nt.links.new(clampv(map_range(nt, _ns.outputs["Z"], 0.0, 1.0, 0.35, 0.85)), _mf.inputs[0])
nt.links.new(clampv(map_range(nt, noise(nt, 1.3, 4.0).outputs["Fac"], 0.0, 0.8, 0.42, 0.62)), _mf.inputs[1])
_col = mix_rgb(nt, _col, rgb(nt, (0.22, 0.29, 0.14)), _mf.outputs[0], 'MIX')
nt.links.new(_col, _p.inputs["Base Color"])
_tv = nt.nodes.new("ShaderNodeTexVoronoi")
_tv.inputs["Scale"].default_value = 5.0
nt.links.new(texcoord(nt).outputs["Object"], _tv.inputs["Vector"])
_tb1 = bump_node(nt, _tv.outputs["Distance"], 0.5, 0.08)
_tb2 = bump_node(nt, noise(nt, 11.0, 5.0).outputs["Fac"], 0.5, 0.04, prev_normal=_tb1.outputs["Normal"])
nt.links.new(_tb2.outputs["Normal"], _p.inputs["Normal"])
# 黄石：驳岸与叠石，赭黄带褐，块面分明
HUANGSHI = noise_mix(principled("HuangShi", (0.47, 0.39, 0.27), rough=0.9, bevel=0), (0.36, 0.29, 0.20), (0.58, 0.49, 0.34), 1.6, detail=5.0, bump=0.7)
nt = HUANGSHI.node_tree
_hg = nt.nodes.new("ShaderNodeNewGeometry")
_hs = nt.nodes.new("ShaderNodeSeparateXYZ")
nt.links.new(_hg.outputs["Normal"], _hs.inputs["Vector"])
_hl = next(l for l in nt.links if l.to_socket == nt.nodes["Principled BSDF"].inputs["Base Color"])
_hsrc = _hl.from_socket
_hm = nt.nodes.new("ShaderNodeMath"); _hm.operation = 'MULTIPLY'
nt.links.new(clampv(map_range(nt, _hs.outputs["Z"], 0.0, 1.0, 0.45, 0.9)), _hm.inputs[0])
nt.links.new(clampv(map_range(nt, noise(nt, 1.1, 4.0).outputs["Fac"], 0.0, 0.75, 0.45, 0.62)), _hm.inputs[1])
nt.links.new(mix_rgb(nt, _hsrc, rgb(nt, (0.20, 0.27, 0.12)), _hm.outputs[0], 'MIX'), nt.nodes["Principled BSDF"].inputs["Base Color"])
# 植物
BAMBOO_LEAF = leaf_material("ZhuYe", (0.15, 0.27, 0.10), (0.27, 0.40, 0.15), sss=0, bump=0.3)
BAMBOO_CULM = principled("ZhuGan", (0.40, 0.48, 0.20), rough=0.45, bevel=0)
BANANA = leaf_material("BaJiao", (0.18, 0.40, 0.13), (0.32, 0.54, 0.19), sss=0, bump=0.3)
PINE_PAD = leaf_material("SongZhen", (0.055, 0.14, 0.085), (0.11, 0.22, 0.115), sss=0, bump=1.0)       # 造型松的针叶云片
PINE_BARK = noise_mix(principled("SongPi", (0.20, 0.13, 0.09), rough=0.9, bevel=0), (0.13, 0.085, 0.06), (0.28, 0.19, 0.13), 6.0, detail=5.0, bump=0.8)
SHRUB = leaf_material("GuanMu", (0.10, 0.22, 0.075), (0.20, 0.35, 0.12), sss=0, bump=0.9)                # 修剪成球的灌木
AZALEA = [principled("DuJuanHong", (0.80, 0.26, 0.40), rough=0.7, bevel=0), principled("DuJuanBai", (0.90, 0.88, 0.82), rough=0.7, bevel=0)]
TUFT = leaf_material("YanJieCao", (0.07, 0.17, 0.06), (0.14, 0.27, 0.09), sss=0, bump=0.3)
LOTUS_LEAF = leaf_material("LotusLeaf", (0.14, 0.34, 0.16), (0.24, 0.46, 0.22), sss=0, bump=0.4)
LOTUS_FLOWER = principled("LotusFlower", (0.96, 0.72, 0.80), rough=0.7, bevel=0)
TRUNK = principled("Trunk", (0.16, 0.11, 0.07), rough=0.9, bevel=0)
BASKET = principled("ZhuKuang", (0.52, 0.40, 0.20), rough=0.8, bevel=0)
CANOPY = principled("WuPeng", (0.035, 0.033, 0.030), rough=0.6, bevel=0)              # 乌篷
DECK = principled("ChuanBan", (0.30, 0.20, 0.12), rough=0.7, bevel=0)
WATER_VAT = principled("GangShui", (0.05, 0.09, 0.06), rough=0.08, spec=0.8, bevel=0)
KOI = [principled("KoiR", (0.80, 0.20, 0.04), rough=0.4, bevel=0), principled("KoiW", (0.85, 0.82, 0.74), rough=0.4, bevel=0),
       principled("KoiY", (0.86, 0.52, 0.08), rough=0.4, bevel=0)]

# 池水：与西湖同一原理。水体色（平法线漫反射，不随波纹明暗，仍接收投影）之上叠加菲涅耳加权的镜面倒影，
# 波纹只扰动倒影。园池很小很静：波纹弱、倒影清楚，水色碧绿偏浊，近水面处略透（看得见游鱼和荷梗）。
WATER = principled("PondWater", (0.11, 0.19, 0.13), rough=0.03, spec=0.85, bevel=0)   # Principled 只留给网页导出读颜色
nt = WATER.node_tree
_out = nt.nodes["Material Output"]
for _l in [l for l in nt.links if l.to_node == _out]:
    nt.links.remove(_l)
def _mrc(sock, lo, hi, fmin=0.0, fmax=1.0):
    """带钳位的 Map Range（钳位只限制在目标范围内，所以阈值要放在 From 范围里）。"""
    s = map_range(nt, sock, lo, hi, fmin, fmax); s.node.clamp = True
    return s
def _math(op, a, b=None):
    n = nt.nodes.new("ShaderNodeMath"); n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            nt.links.new(v, n.inputs[i])
    return n.outputs[0]
_sa = nt.nodes.new("ShaderNodeAttribute"); _sa.attribute_name = "shore"
_sc = nt.nodes.new("ShaderNodeSeparateColor")
nt.links.new(_sa.outputs["Color"], _sc.inputs["Color"])
_sh, _deep = _sc.outputs[0], _sc.outputs[1]
_wp = noise(nt, 0.16, 3.0, distortion=0.6)                       # 几米尺度的平静 / 微皱斑块
_calm = _mrc(_wp.outputs["Fac"], 0.0, 1.0, 0.40, 0.58)
_ruf = _math('SUBTRACT', 1.0, _calm)
_w1 = noise(nt, 1.2, 3.0, distortion=0.5)
_b1 = bump_node(nt, _w1.outputs["Fac"], 0.04, 0.3)
_w2 = noise(nt, 6.0, 3.0, distortion=0.3)
_b2 = bump_node(nt, _w2.outputs["Fac"], 0.1, 0.06, prev_normal=_b1.outputs["Normal"])
nt.links.new(_mrc(_ruf, 0.015, 0.20), _b2.inputs["Strength"])
_nrm = _b2.outputs["Normal"]
_deepc = mix_rgb(nt, rgb(nt, (0.105, 0.185, 0.090)), rgb(nt, (0.048, 0.110, 0.062)), _deep, 'MIX')
_bodyc = mix_rgb(nt, _deepc, rgb(nt, (0.19, 0.23, 0.13)), _mrc(_sh, 0.0, 0.7), 'MIX')
_bodyc = mul_color(nt, _bodyc, map_range(nt, noise(nt, 0.35, 3.0, distortion=0.6).outputs["Fac"], 0.82, 1.18))
_body = nt.nodes.new("ShaderNodeBsdfDiffuse")
nt.links.new(_bodyc, _body.inputs["Color"])
_gl = nt.nodes.new("ShaderNodeBsdfGlossy")
_gl.inputs["Color"].default_value = (0.78, 0.97, 0.84, 1)
nt.links.new(_mrc(_ruf, 0.008, 0.07), _gl.inputs["Roughness"])
nt.links.new(_nrm, _gl.inputs["Normal"])
_fr = nt.nodes.new("ShaderNodeFresnel")
_fr.inputs["IOR"].default_value = 1.33
nt.links.new(_nrm, _fr.inputs["Normal"])
_REFL = (float(arg("--refl0", 0.36)), float(arg("--refl1", 0.85)))
_refl = _mrc(_fr.outputs["Fac"], _REFL[0], _REFL[1], 0.02, 0.30)
_surf = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(_refl, _surf.inputs[0]); nt.links.new(_body.outputs[0], _surf.inputs[1]); nt.links.new(_gl.outputs[0], _surf.inputs[2])
_tr = nt.nodes.new("ShaderNodeBsdfTransparent")
_tr.inputs["Color"].default_value = (0.74, 0.88, 0.76, 1)
_shal = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(_mrc(_sh, 0.22, 0.62, 0.25, 1.0), _shal.inputs[0])
nt.links.new(_surf.outputs[0], _shal.inputs[1]); nt.links.new(_tr.outputs[0], _shal.inputs[2])
_lp = nt.nodes.new("ShaderNodeLightPath")
_mix = nt.nodes.new("ShaderNodeMixShader")
nt.links.new(_lp.outputs["Is Shadow Ray"], _mix.inputs[0])
nt.links.new(_shal.outputs[0], _mix.inputs[1]); nt.links.new(_tr.outputs[0], _mix.inputs[2])
nt.links.new(_mix.outputs[0], _out.inputs["Surface"])

# 沙盘切面：Rock051 层状岩
EARTH = principled("EarthCut", (0.40, 0.29, 0.19), rough=0.95, bevel=0)
nt = EARTH.node_tree
_p = nt.nodes["Principled BSDF"]
_c = tex_node(nt, "Rock051", "Color", 0.30, 'Object', noncolor=False)
_r = tex_node(nt, "Rock051", "Roughness", 0.30, 'Object')
_d = tex_node(nt, "Rock051", "Displacement", 0.30, 'Object')
_wv = nt.nodes.new("ShaderNodeTexWave")
_wv.wave_type = 'BANDS'; _wv.bands_direction = 'Z'
_wv.inputs["Scale"].default_value = 0.9
_wv.inputs["Distortion"].default_value = 4.0
_wv.inputs["Detail"].default_value = 3.0
nt.links.new(texcoord(nt).outputs["Object"], _wv.inputs["Vector"])
_er = ramp(nt, [(0.15, (1.5, 1.28, 0.98)), (0.5, (2.3, 2.05, 1.6)), (0.85, (2.9, 2.6, 2.15))])
nt.links.new(_wv.outputs["Fac"], _er.inputs["Fac"])
nt.links.new(mul_color(nt, _c.outputs["Color"], _er.outputs["Color"]), _p.inputs["Base Color"])
nt.links.new(map_range(nt, _r.outputs["Color"], 0.7, 1.0), _p.inputs["Roughness"])
_cr = nt.nodes.new("ShaderNodeTexVoronoi")
_cr.feature = 'DISTANCE_TO_EDGE'
_cr.inputs["Scale"].default_value = 0.65
nt.links.new(texcoord(nt).outputs["Object"], _cr.inputs["Vector"])
_crr = ramp(nt, [(0.0, (0, 0, 0)), (0.12, (1, 1, 1))])
nt.links.new(_cr.outputs["Distance"], _crr.inputs["Fac"])
_cb = bump_node(nt, _crr.outputs["Color"], 0.8, 0.35)
tex_bump(nt, _d, 1.2, 0.22, prev_normal=_cb.outputs["Normal"])

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


# ----------------------------------------------------------------------------- 池塘 / 地形
PC = (-3.5, -2.5)   # 池心
def pond_r(a):
    ca, sa = math.cos(a), math.sin(a)
    n = 2.6
    r0 = (abs(ca / 15.0) ** n + abs(sa / 10.6) ** n) ** (-1.0 / n)
    return r0 * (1 + 0.09 * math.sin(2 * a + 0.6) + 0.07 * math.sin(3 * a + 2.1) + 0.045 * math.sin(5 * a + 0.9) + 0.03 * math.sin(8 * a + 1.7))
def _cap_sd(x, y, ax, ay, bx, by, ra, rb):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - ax - dx * t, y - ay - dy * t) - (ra + (rb - ra) * t)
ARMS = [(-13.5, 5.0, -19.5, 10.2, 2.0, 1.1),      # 西北水湾（小拱桥跨过）
        (8.5, -7.0, 15.0, -11.5, 3.2, 2.0)]       # 东南水湾
def pond_sd(x, y):
    """到池岸的带符号距离（池内为负）。"""
    dx, dy = x - PC[0], y - PC[1]
    sd = math.hypot(dx, dy) - pond_r(math.atan2(dy, dx))
    for arm in ARMS:
        sd = smin(sd, _cap_sd(x, y, *arm), 0.8)
    return sd

MOUNDS = [(-23.5, -18.5, 8.0, 2.4), (15.5, -15.0, 3.5, 0.5), (-12.5, 22.5, 3.5, 0.45)]   # 假山土丘与缓坡
def ground(x, y):
    z = GZ
    for (mx, my, mr, mh) in MOUNDS:
        d = math.hypot(x - mx, y - my) / mr
        if d < 1:
            z += mh * (1 - d * d) ** 2
    return z
CANAL = (-38.0, -32.9)    # 南面河道的 y 范围（东西向贯穿沙盘）
def canal_d(x, y):
    """到河道驳岸的距离（河道内为正）。"""
    return min(y - CANAL[0], CANAL[1] - y)
def terrain(x, y):
    if canal_d(x, y) > 0.15:
        return -0.9, 'water'
    sd = pond_sd(x, y)
    z = ground(x, y)
    if sd < 0.5:
        t = smooth01((0.5 - sd) / 1.9)
        z = z + (-1.25 - z) * t
    return z, ('water' if sd < 0.0 else 'land')

ISL = (-40.0, -46.5, 40.0, 33.0)
E_SUP = 0.35
def isl_rho(x, y):
    x0, y0, x1, y1 = ISL
    cx, cy, hw, hd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    n = 2.0 / E_SUP
    return (abs((x - cx) / hw) ** n + abs((y - cy) / hd) ** n) ** (1.0 / n), cx, cy

def island():
    t0 = time.time()
    b = B("Island")
    x0, y0, x1, y1 = ISL
    step = 0.6 if WEB else 0.4
    nx, ny = int(math.ceil((x1 - x0) / step)) + 1, int(math.ceil((y1 - y0) / step)) + 1
    sx, sy = (x1 - x0) / (nx - 1), (y1 - y0) / (ny - 1)
    verts, kinds, inside = [], [], []
    for j in range(ny):
        for i in range(nx):
            x, y = x0 + i * sx, y0 + j * sy
            rho, cx, cy = isl_rho(x, y)
            ins = rho <= 1.0
            if not ins:
                x, y = cx + (x - cx) / rho, cy + (y - cy) / rho
            z, k = terrain(x, y)
            verts.append((x, y, z)); kinds.append(k); inside.append(ins)
    faces, mats = [], []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; bq = a + 1; c = a + nx + 1; d = a + nx
            if not (inside[a] or inside[bq] or inside[c] or inside[d]):
                continue
            faces.append((a, bq, c, d))
            mats.append(POND_BED if any(kinds[q] == 'water' for q in (a, bq, c, d)) else TERRAIN)
    b.v.extend(verts)
    for f, m in zip(faces, mats):
        b.f.append(f); b.m.append(b.mi(m)); b.uv.append(None)
    # 切面环
    cx, cy, hw, hd = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    N = 300
    ph = [ru(0, 6.28) for _ in range(5)]
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
            w = scale * (1 + amp * profile(a)) + ru(-jitter, jitter)
            pts.append((cx + x * w, cy + y * w, z + ru(-zj, zj)))
        return pts
    top = []
    for i in range(N):
        a = 2 * math.pi * i / N
        x, y = base_xy(a)
        top.append((cx + x, cy + y, terrain(cx + x, cy + y)[0] + 0.02))      # 河道在沙盘边缘切出缺口
    rings = [top, ring(1.0, -1.4, 0.03, 0.012, 0.17), ring(0.995, -2.5, 0.05, 0.02, 0.3), ring(0.985, -4.4, 0.065, 0.025, 0.34),
             ring(0.965, -6.3, 0.075, 0.03, 0.34), ring(0.93, -8.2, 0.085, 0.03, 0.34), ring(0.87, -9.9, 0.095, 0.03, 0.34),
             ring(0.76, -11.3, 0.1, 0.03, 0.25), ring(0.55, -12.6, 0.1, 0.03, 0.17), ring(0.3, -13.4, 0.1, 0.02, 0.12)]
    v, f = [], []
    for r in rings:
        v.extend(r)
    R = len(rings)
    for k in range(R - 1):
        for i in range(N):
            j = (i + 1) % N
            f.append((k * N + i, k * N + j, (k + 1) * N + j, (k + 1) * N + i))
    v.append((cx, cy, -13.9)); apex = len(v) - 1
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
    print(f"[sz] island grid {nx}x{ny}, faces={len(faces)} in {time.time() - t0:.1f}s")

def pond_water():
    """池水网格（0.5 米），顶点属性 shore：R = 近岸程度，G = 水深程度。"""
    w = B("Water")
    x0, y0, x1, y1, step = -24.0, -15.5, 18.5, 13.0, 0.5
    nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
    verts, sh = [], []
    for j in range(ny):
        for i in range(nx):
            x, y = x0 + i * step, y0 + j * step
            sd = pond_sd(x, y)
            verts.append((x, y, 0.0))
            sh.append((sd, 1.0 - smooth01(-sd / 1.0), smooth01(-sd / 4.5)))
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; q = (a, a + 1, a + nx + 1, a + nx)
            if min(sh[k][0] for k in q) < 0.35:
                faces.append(q)
    # 河道水面：逐行按沙盘轮廓求出东西两端，裁剪在轮廓之内
    ix0, iy0, ix1, iy1 = ISL
    icx, icy, ihw, ihd = (ix0 + ix1) / 2, (iy0 + iy1) / 2, (ix1 - ix0) / 2, (iy1 - iy0) / 2
    en = 2.0 / E_SUP
    base = len(verts)
    for j in range(7):
        y = CANAL[0] + 0.25 + (CANAL[1] - CANAL[0] - 0.5) * j / 6
        xm = ihw * max(0.0, 0.994 ** en - abs((y - icy) / ihd) ** en) ** (1.0 / en)
        for i in range(81):
            x = icx - xm + 2 * xm * i / 80
            d = canal_d(x, y)
            verts.append((x, y, 0.0))
            sh.append((-d, 1.0 - smooth01(d / 0.8), smooth01(d / 2.4)))
    for j in range(6):
        for i in range(80):
            a = base + j * 81 + i
            faces.append((a, a + 1, a + 82, a + 81))
    w.add(verts, faces, WATER)
    ob = w.build()
    attr = ob.data.attributes.new(name="shore", type='FLOAT_COLOR', domain='POINT')
    for k, (_, s, dp) in enumerate(sh):
        attr.data[k].color = (s, dp, 0.0, 1.0)
    try:
        ob.data.attributes.active_color = attr
    except Exception:
        pass
    print(f"[sz] pond water faces={len(faces)}")

# ----------------------------------------------------------------------------- 占位登记（种植避让）
KEEP = []    # (x, y, r)
RECTS = []   # (x0, y0, x1, y1)
def keep(x, y, r):
    KEEP.append((x, y, r))
def keep_rect(x0, y0, x1, y1, pad=0.3):
    RECTS.append((min(x0, x1) - pad, min(y0, y1) - pad, max(x0, x1) + pad, max(y0, y1) + pad))
def blocked(x, y, k=1.0):
    for (x0, y0, x1, y1) in RECTS:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return any((x - kx) ** 2 + (y - ky) ** 2 < (kr * k) ** 2 for (kx, ky, kr) in KEEP)

# ----------------------------------------------------------------------------- 建筑构件
class Fr:
    """建筑局部坐标系：原点 (cx, cy)，绕 z 轴转 ang；局部 −y 为正面。"""
    def __init__(s, cx, cy, ang=0.0):
        s.cx, s.cy, s.a, s.c, s.s = cx, cy, ang, math.cos(ang), math.sin(ang)
    def p(s, x, y, z=None):
        X, Y = s.cx + x * s.c - y * s.s, s.cy + x * s.s + y * s.c
        return (X, Y) if z is None else (X, Y, z)
    def box(s, b, x, y, z0, w, d, h, mat):
        X, Y = s.p(x, y)
        rbox(b, X, Y, z0, w, d, h, mat, s.a)
    def col(s, b, x, y, z0, r, h, mat, n=10):
        X, Y = s.p(x, y)
        prism(b, X, Y, z0, r, h, mat, n=n)

def lerp2(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
def _unit(ax, ay):
    l = math.hypot(ax, ay) or 1.0
    return ax / l, ay / l
def offset_poly(pts, dist):
    """折线向左偏移 dist（负值向右），拐角斜接。"""
    n = len(pts); out = []
    for i in range(n):
        if i == 0:
            dx, dy = _unit(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
            out.append((pts[0][0] - dy * dist, pts[0][1] + dx * dist))
        elif i == n - 1:
            dx, dy = _unit(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            out.append((pts[i][0] - dy * dist, pts[i][1] + dx * dist))
        else:
            ax, ay = _unit(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            bx, by = _unit(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            mx, my = _unit(-ay - by, ax + bx)
            k = dist / max(0.35, mx * (-ay) + my * ax)
            out.append((pts[i][0] + mx * k, pts[i][1] + my * k))
    return out

def chain(b, pts, t, mat):
    for i in range(len(pts) - 1):
        rod(b, pts[i], pts[i + 1], t, mat)

def wall_piece(b, p0, p1, z0, h0, h1, t, mat):
    """一段直墙（顶面可倾斜：两端高度 h0、h1）。"""
    (ax, ay), (bx, by) = p0, p1
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-4:
        return
    nx, ny = -(by - ay) / L * t / 2, (bx - ax) / L * t / 2
    v = [(ax - nx, ay - ny, z0), (bx - nx, by - ny, z0), (bx + nx, by + ny, z0), (ax + nx, ay + ny, z0),
         (ax - nx, ay - ny, z0 + h0), (bx - nx, by - ny, z0 + h1), (bx + nx, by + ny, z0 + h1), (ax + nx, ay + ny, z0 + h0)]
    b.add(v, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], mat)

def wall_cap(b, p0, p1, z0c, z1c, t, ribs=True):
    """墙帽：双坡小瓦顶 + 压脊 + 瓦垄。"""
    (ax, ay), (bx, by) = p0, p1
    L = math.hypot(bx - ax, by - ay)
    if L < 1e-4:
        return
    half, rise = t / 2 + 0.17, 0.2
    nx, ny = -(by - ay) / L * half, (bx - ax) / L * half
    v = [(ax - nx, ay - ny, z0c), (ax + nx, ay + ny, z0c), (ax, ay, z0c + rise),
         (bx - nx, by - ny, z1c), (bx + nx, by + ny, z1c), (bx, by, z1c + rise)]
    b.add(v, [(0, 3, 5, 2), (1, 2, 5, 4), (0, 1, 4, 3), (0, 2, 1), (3, 4, 5)], DARK_TILE)
    rod(b, (ax, ay, z0c + rise - 0.02), (bx, by, z1c + rise - 0.02), 0.05, RIDGE)
    if ribs:
        m = max(1, int(L / 0.3))
        for k in range(m):
            s = (k + 0.5) / m
            cx, cy, cz = ax + (bx - ax) * s, ay + (by - ay) * s, z0c + (z1c - z0c) * s
            rod(b, (cx - nx, cy - ny, cz), (cx, cy, cz + rise), 0.03, TILE_ROW)
            rod(b, (cx + nx, cy + ny, cz), (cx, cy, cz + rise), 0.03, TILE_ROW)

def lattice_w(b, p0, p1, z0, z1, nx=3, nz=6, t=0.035, mat=None, frame=0.06, glass=0.0, depth=0.05):
    """一樘花格：边框 + 竖横棂条；glass ≠ 0 时在一侧（正值为行进方向左侧）加深色背板，读成窗内的暗。"""
    mat = mat or LATTICE
    (ax, ay), (bx, by) = p0, p1
    L = math.hypot(bx - ax, by - ay)
    if L < 0.05 or z1 - z0 < 0.05:
        return
    ang = math.atan2(by - ay, bx - ax); ux, uy = (bx - ax) / L, (by - ay) / L
    def bar(s, z, w, h, d=depth):
        rbox(b, ax + ux * s, ay + uy * s, z, w, d, h, mat, ang)
    bar(L / 2, z0, L, frame, depth + 0.02); bar(L / 2, z1 - frame, L, frame, depth + 0.02)
    bar(frame / 2, z0, frame, z1 - z0, depth + 0.02); bar(L - frame / 2, z0, frame, z1 - z0, depth + 0.02)
    for i in range(1, nx):
        bar(L * i / nx, z0, t, z1 - z0)
    for j in range(1, nz):
        bar(L / 2, z0 + (z1 - z0) * j / nz - t / 2, L, t)
    if glass:
        rbox(b, ax + ux * L / 2 - uy * glass, ay + uy * L / 2 + ux * glass, z0, L, 0.02, z1 - z0, GLASS_DARK, ang)

def tube(b, pts, side, r, mat, seg=4, cap=True, full=False):
    """沿折线的半圆筒（筒瓦垄）；side 为横向单位向量，pts[0] 是檐口端。"""
    if WEB and not full:
        seg = 2
        pts = [pts[0], pts[len(pts) // 2], pts[-1]] if len(pts) > 3 else pts
    sx, sy = side
    m = seg + 1
    v = []
    for (x, y, zz) in pts:
        for k in range(m):
            th = math.pi * k / seg
            v.append((x + sx * r * math.cos(th), y + sy * r * math.cos(th), zz + r * math.sin(th) * 1.15 + 0.012))
    f = []
    for i in range(len(pts) - 1):
        for k in range(seg):
            f.append((i * m + k, i * m + k + 1, (i + 1) * m + k + 1, (i + 1) * m + k))
    if cap:
        f.append(tuple(range(m)))
    b.add(v, f, mat)

def rcurve(t):
    """举折：檐口平缓、近脊陡峻。"""
    return 0.6 * t + 0.4 * t * t

N_ROWS = 0
def suzhou_roof(b, F, z, w, d, H, kind='xieshan', ov=0.85, ovx=None, lift=0.75, corner=2.6, rows=True, ridge=True):
    """苏式屋顶：kind = xieshan（歇山）/ hip（四坡，用作腰檐）/ gable（硬山）。脊沿局部 x 方向，要求 w ≥ d。
    屋面按举折曲线起坡，翼角起翘（lift）并外翘；筒瓦垄、正脊、戗脊、垂脊、嫩戗发戗的尖角都是几何。"""
    global N_ROWS
    a = w / 2 + (ov if ovx is None else ovx); bb = d / 2 + ov
    n = max(5, int(round(bb / 0.5))); s = bb / n
    g = max(2, int(round(0.5 * n))) * s if kind == 'xieshan' else None
    lifted = kind != 'gable' and lift > 0
    def P(xl, yl, mode):
        dx, dy = a - abs(xl), bb - abs(yl)
        dd = dy if mode == 'in' else min(dx, dy)
        zz = z + H * rcurve(max(0.0, min(1.0, dd / bb)))
        if lifted:
            t = max(0.0, 1 - dx / corner) * max(0.0, 1 - dy / corner)
            if t > 0:
                t2 = t * t
                zz += lift * t2
                xl += math.copysign(0.3 * lift * t2, xl); yl += math.copysign(0.3 * lift * t2, yl)
        return F.p(xl, yl, zz)
    # 网格线：四角用与进深相同的步长（戗脊正好落在格点对角线上），中段稀疏
    if kind == 'gable':
        m = max(2, int(round(2 * a / 1.6)))
        xs_ = [-a + 2 * a * i / m for i in range(m + 1)]
    else:
        xs_ = [-a + k * s for k in range(n + 1)]
        mid = a - bb
        if mid > 0.05:
            m = max(1, int(round(2 * mid / 1.4)))
            xs_ += [-mid + 2 * mid * j / m for j in range(1, m)]
            xs_ += [a - k * s for k in range(n, -1, -1)]
        else:
            xs_ += [a - k * s for k in range(n - 1, -1, -1)]
    ys_ = [-bb + k * s for k in range(2 * n + 1)]
    for i in range(len(xs_) - 1):
        for j in range(len(ys_) - 1):
            x0, x1, y0, y1 = xs_[i], xs_[i + 1], ys_[j], ys_[j + 1]
            xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
            dxc, dyc = a - abs(xc), bb - abs(yc)
            if kind == 'gable':
                mode = 'in'
            elif kind == 'xieshan':
                mode = 'hip' if min(dxc, dyc) < g else 'in'
            else:
                mode = 'hip'
            loc = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            v = [P(x, y, mode) for (x, y) in loc]
            front = mode == 'in' or dyc <= dxc
            uv = [((x, (bb - abs(y)) * 1.2) if front else (y, (a - abs(x)) * 1.2)) for (x, y) in loc]
            tris = [(0, 1, 2), (0, 2, 3)] if xc * yc > 0 else [(0, 1, 3), (1, 2, 3)]
            b.add(v, tris, DARK_TILE, uvs=[[uv[k] for k in tri] for tri in tris])
    # 檐口封檐
    for i in range(len(xs_) - 1):
        for sg in (-1, 1):
            p0, p1 = P(xs_[i], sg * bb, 'hip' if kind != 'gable' else 'in'), P(xs_[i + 1], sg * bb, 'hip' if kind != 'gable' else 'in')
            b.add([p0, p1, (p1[0], p1[1], p1[2] - 0.13), (p0[0], p0[1], p0[2] - 0.13)], [(0, 1, 2, 3)], RIDGE)
    if kind != 'gable':
        for j in range(len(ys_) - 1):
            for sg in (-1, 1):
                p0, p1 = P(sg * a, ys_[j], 'hip'), P(sg * a, ys_[j + 1], 'hip')
                b.add([p0, p1, (p1[0], p1[1], p1[2] - 0.13), (p0[0], p0[1], p0[2] - 0.13)], [(0, 1, 2, 3)], RIDGE)
    # 筒瓦垄
    if rows:
        rs = 0.27
        sx_ = (F.c, F.s); sy_ = (-F.s, F.c)
        nr = int(2 * a / rs)
        for k in range(nr):
            xr = -a + (2 * a) * (k + 0.5) / nr
            dx = a - abs(xr)
            if kind == 'hip':
                dend, mode = min(dx, bb), 'hip'
            elif kind == 'xieshan':
                dend, mode = (bb, 'in') if dx >= g else (dx, 'hip')
            else:
                dend, mode = bb, 'in'
            if dend < 0.25:
                continue
            K = max(2, int(dend / 0.6))
            for sg in (-1, 1):
                tube(b, [P(xr, sg * (bb - dend * q / K), mode) for q in range(K + 1)], sx_, 0.07, TILE_ROW)
                N_ROWS += 1
        if kind != 'gable':
            nr = int(2 * bb / rs)
            for k in range(nr):
                yr = -bb + (2 * bb) * (k + 0.5) / nr
                dy = bb - abs(yr)
                dend = dy if kind == 'hip' else min(dy, g)
                if dend < 0.25:
                    continue
                K = max(2, int(dend / 0.6))
                for sg in (-1, 1):
                    tube(b, [P(sg * (a - dend * q / K), yr, 'hip') for q in range(K + 1)], sy_, 0.07, TILE_ROW)
                    N_ROWS += 1
    if not ridge:
        return
    zt = z + H
    Lr = (a - bb) if kind == 'hip' else ((a - g) if kind == 'xieshan' else a - 0.05)
    if Lr > 0.3:
        # 正脊 + 两端起翘的纹头
        F.box(b, 0, 0, zt - 0.06, 2 * Lr, 0.24, 0.40, RIDGE)
        F.box(b, 0, 0, zt + 0.34, 2 * Lr + 0.12, 0.32, 0.07, RIDGE)
        for sg in (-1, 1):
            F.box(b, sg * (Lr + 0.16), 0, zt + 0.14, 0.46, 0.20, 0.30, RIDGE)
            F.box(b, sg * (Lr + 0.46), 0, zt + 0.36, 0.38, 0.16, 0.22, RIDGE)
            F.box(b, sg * (Lr + 0.68), 0, zt + 0.55, 0.26, 0.12, 0.16, RIDGE)
        F.box(b, 0, 0, zt + 0.41, 0.5, 0.2, 0.16, RIDGE)
    if kind in ('hip', 'xieshan'):
        tend = bb if kind == 'hip' else g
        for sxg in (-1, 1):
            for syg in (-1, 1):
                pts = [P(sxg * (a - tend * q / 7), syg * (bb - tend * q / 7), 'hip') for q in range(8)]
                chain(b, [(x, y, zz + 0.03) for (x, y, zz) in pts], 0.085, RIDGE)
                # 嫩戗发戗：角梁伸出檐角，向上挑起成尖
                cx_, cy_, cz_ = pts[0]
                ox, oy = F.p(sxg, syg); ox, oy = _unit(ox - F.cx, oy - F.cy)
                k = max(0.5, lift / 0.75)
                sp = [(cx_, cy_, cz_ + 0.05), (cx_ + ox * 0.24, cy_ + oy * 0.24, cz_ + 0.18 * k),
                      (cx_ + ox * 0.44, cy_ + oy * 0.44, cz_ + 0.44 * k), (cx_ + ox * 0.58, cy_ + oy * 0.58, cz_ + 0.80 * k)]
                rod(b, sp[0], sp[1], 0.075, RIDGE); rod(b, sp[1], sp[2], 0.055, RIDGE); rod(b, sp[2], sp[3], 0.035, RIDGE)
    if kind == 'xieshan':
        zr = z + H * rcurve(g / bb)
        for sxg in (-1, 1):
            xg = sxg * (a - g)
            for syg in (-1, 1):   # 垂脊
                pts = [P(xg, syg * (bb - g - (bb - g) * q / 6), 'in') for q in range(7)]
                chain(b, [(x, y, zz + 0.03) for (x, y, zz) in pts], 0.08, RIDGE)
            ys_g = [y for y in ys_ if abs(y) <= bb - g + 1e-6]   # 山花（粉白）
            for j in range(len(ys_g) - 1):
                ya, yb = ys_g[j], ys_g[j + 1]
                za, zb = z + H * rcurve((bb - abs(ya)) / bb), z + H * rcurve((bb - abs(yb)) / bb)
                xi = xg - sxg * 0.03
                b.add([F.p(xi, ya, zr - 0.05), F.p(xi, yb, zr - 0.05), F.p(xi, yb, zb), F.p(xi, ya, za)], [(0, 1, 2, 3)], WHITE_WALL)
    if kind == 'gable':
        for sxg in (-1, 1):
            for syg in (-1, 1):   # 山墙压顶
                pts = [P(sxg * (a - 0.06), syg * (bb - bb * q / 6), 'in') for q in range(7)]
                chain(b, [(x, y, zz + 0.02) for (x, y, zz) in pts], 0.10, RIDGE)

def pav_roof(b, cx, cy, z, R, H, n=6, phase=0.0, lift=1.0):
    """攒尖顶（六角 / 四角）：凹曲屋面、翼角高翘、宝顶。"""
    global N_ROWS
    C = [(cx + R * math.cos(2 * math.pi * i / n + phase), cy + R * math.sin(2 * math.pi * i / n + phase)) for i in range(n)]
    K, U = 7, 6
    def cv(t):
        return 0.40 * t + 0.60 * t * t
    for i in range(n):
        c0, c1 = C[i], C[(i + 1) % n]
        M = ((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2)
        W = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) / 2
        sd = _unit(c1[0] - c0[0], c1[1] - c0[1])
        up = (cx - M[0], cy - M[1]); ap = math.hypot(*up); un = (up[0] / ap, up[1] / ap)
        def S(q, t):
            hw = W * (1 - t)
            c3 = abs(q) ** 3 * (1 - t) ** 3
            fl = 0.28 * lift * c3
            x = M[0] + sd[0] * q * hw + up[0] * t - un[0] * fl + sd[0] * math.copysign(fl * 0.4, q)
            y = M[1] + sd[1] * q * hw + up[1] * t - un[1] * fl + sd[1] * math.copysign(fl * 0.4, q)
            return (x, y, z + H * cv(t) + lift * c3)
        for k in range(K):
            t0, t1 = k / K, (k + 1) / K
            for j in range(U):
                q0, q1 = -1 + 2 * j / U, -1 + 2 * (j + 1) / U
                if k == K - 1:
                    v = [S(q0, t0), S(q1, t0), S(0, 1.0)]
                    uv = [(q0 * W * (1 - t0), t0 * ap * 1.2), (q1 * W * (1 - t0), t0 * ap * 1.2), (0, ap * 1.2)]
                    b.add(v, [(0, 1, 2)], DARK_TILE, uvs=[uv])
                else:
                    v = [S(q0, t0), S(q1, t0), S(q1, t1), S(q0, t1)]
                    uv = [(q0 * W * (1 - t0), t0 * ap * 1.2), (q1 * W * (1 - t0), t0 * ap * 1.2),
                          (q1 * W * (1 - t1), t1 * ap * 1.2), (q0 * W * (1 - t1), t1 * ap * 1.2)]
                    tris = [(0, 1, 2), (0, 2, 3)] if (q0 + q1) > 0 else [(0, 1, 3), (1, 2, 3)]
                    b.add(v, tris, DARK_TILE, uvs=[[uv[m] for m in tri] for tri in tris])
            # 封檐
            if k == 0:
                for j in range(U):
                    q0, q1 = -1 + 2 * j / U, -1 + 2 * (j + 1) / U
                    p0, p1 = S(q0, 0), S(q1, 0)
                    b.add([p0, p1, (p1[0], p1[1], p1[2] - 0.12), (p0[0], p0[1], p0[2] - 0.12)], [(0, 1, 2, 3)], RIDGE)
        nr = int(2 * W / 0.27)
        for r in range(nr):
            qm = -W + 2 * W * (r + 0.5) / nr
            tend = 1 - abs(qm) / W - 0.03
            if tend < 0.08:
                continue
            kk = max(2, int(tend * K))
            pts = []
            for q in range(kk + 1):
                t = tend * q / kk
                pts.append(S(max(-1.0, min(1.0, qm / (W * (1 - t)))), t))
            tube(b, pts, sd, 0.065, TILE_ROW)
            N_ROWS += 1
    for i in range(n):   # 戗脊与翘角
        c = C[i]
        o = _unit(c[0] - cx, c[1] - cy)
        pts = []
        for q in range(9):
            t = q / 8
            fl = 0.28 * lift * (1 - t) ** 3 * 1.1
            pts.append((c[0] + (cx - c[0]) * t + o[0] * fl, c[1] + (cy - c[1]) * t + o[1] * fl, z + H * cv(t) + lift * (1 - t) ** 3 + 0.04))
        chain(b, pts, 0.08, RIDGE)
        p = pts[0]
        sp = [p, (p[0] + o[0] * 0.22, p[1] + o[1] * 0.22, p[2] + 0.2 * lift), (p[0] + o[0] * 0.40, p[1] + o[1] * 0.40, p[2] + 0.5 * lift),
              (p[0] + o[0] * 0.52, p[1] + o[1] * 0.52, p[2] + 0.9 * lift)]
        rod(b, sp[0], sp[1], 0.07, RIDGE); rod(b, sp[1], sp[2], 0.05, RIDGE); rod(b, sp[2], sp[3], 0.032, RIDGE)
    cone(b, cx, cy, z + H - 0.12, 0.30, 0.16, 0.30, RIDGE, n=10, uv=False)
    cone(b, cx, cy, z + H + 0.18, 0.13, 0.24, 0.22, RIDGE, n=10, uv=False)
    cone(b, cx, cy, z + H + 0.40, 0.24, 0.03, 0.42, RIDGE, n=10, uv=False)

def door_run(b, F, pa, pb, zf, hcol, inside=1):
    """一开间的长窗：下为裙板，上为花格，顶上横披窗。pa→pb 为局部坐标，室内在行进方向左侧（inside=1）。"""
    L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    nl = max(2, int(round(L / 0.72)))
    for j in range(nl):
        a_, c_ = lerp2(pa, pb, (j + 0.05) / nl), lerp2(pa, pb, (j + 0.95) / nl)
        wall_piece(b, F.p(*a_), F.p(*c_), zf, 0.72, 0.72, 0.06, WOOD)
        lattice_w(b, F.p(*a_), F.p(*c_), zf + 0.72, zf + hcol - 0.50, nx=3, nz=7, glass=0.05 * inside)
    lattice_w(b, F.p(*pa), F.p(*pb), zf + hcol - 0.46, zf + hcol - 0.06, nx=max(3, int(L / 0.42)), nz=2, glass=0.05 * inside)

def window_run(b, F, pa, pb, zf, hcol, inside=1, sill=0.95):
    """一开间的半窗：下为粉墙槛墙，上为花格窗。"""
    wall_piece(b, F.p(*pa), F.p(*pb), zf, sill, sill, 0.2, WHITE_WALL)
    L = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    nl = max(2, int(round(L / 0.8)))
    for j in range(nl):
        a_, c_ = lerp2(pa, pb, (j + 0.04) / nl), lerp2(pa, pb, (j + 0.96) / nl)
        lattice_w(b, F.p(*a_), F.p(*c_), zf + sill, zf + hcol - 0.12, nx=3, nz=5, glass=0.05 * inside)

def seat_rail(b, pa, pb, zf, back=True, out=1):
    """坐槛 + 美人靠（靠背向外倾，out=1 为行进方向右侧）。"""
    wall_piece(b, pa, pb, zf, 0.42, 0.42, 0.26, WOOD)
    if back:
        (ax, ay), (bx, by) = pa, pb
        L = math.hypot(bx - ax, by - ay)
        nx, ny = (by - ay) / L * out, -(bx - ax) / L * out
        o0, o1 = 0.13, 0.36
        rod(b, (ax + nx * o1, ay + ny * o1, zf + 0.82), (bx + nx * o1, by + ny * o1, zf + 0.82), 0.03, WOOD)
        m = max(2, int(L / 0.22))
        for k in range(m + 1):
            s = k / m
            x, y = ax + (bx - ax) * s, ay + (by - ay) * s
            rod(b, (x + nx * o0, y + ny * o0, zf + 0.42), (x + nx * o1, y + ny * o1, zf + 0.82), 0.014, WOOD)

def stone_rail(b, pts, z, h=0.55, mat=None):
    """石栏：望柱 + 栏板。"""
    mat = mat or GRANITE
    for i in range(len(pts) - 1):
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        L = math.hypot(bx - ax, by - ay)
        m = max(1, int(round(L / 1.5)))
        ang = math.atan2(by - ay, bx - ax)
        for k in range(0 if i == 0 else 1, m + 1):      # 转角处的望柱只放一根：两根重合会互相遮光，渲染成黑块
            s = k / m
            rbox(b, ax + (bx - ax) * s, ay + (by - ay) * s, z, 0.15, 0.15, h + 0.12, mat, ang)
        wall_piece(b, pts[i], pts[i + 1], z + 0.08, h - 0.16, h - 0.16, 0.07, mat)
        rod(b, (ax, ay, z + h - 0.06), (bx, by, z + h - 0.06), 0.05, mat)

def hall(name, cx, cy, w, d, ang=0.0, kind='xieshan', style='hall', hcol=3.3, floors=1, porch=1.3, plinth=0.4,
         z0=None, ov=0.9, lift=0.8, rh=None, steps=True):
    """厅堂 / 轩 / 水榭 / 楼。
    style: hall（前廊 + 长窗，三面粉墙）/ four（四面厅：周围廊，四面长窗）/ open（敞轩水榭：三面开敞设美人靠，背面粉墙开花窗）/
           gate（门厅：临街粉墙，正中石库门）/ stilt = open 且架于水上。"""
    b = B(name); F = Fr(cx, cy, ang)
    stilt = style == 'stilt'
    if stilt:
        style = 'open'
    z0 = ground(cx, cy) if z0 is None else z0
    zf = z0 + plinth
    if stilt:
        for i in range(4):
            for j in range(3):
                F.box(b, -w / 2 + 0.25 + (w - 0.5) * i / 3, -d / 2 + 0.25 + (d - 0.5) * j / 2, -1.2, 0.32, 0.32, zf + 1.0, GRANITE)
        F.box(b, 0, 0, zf - 0.22, w + 0.7, d + 0.7, 0.22, GRANITE)
    else:
        F.box(b, 0, 0, z0 - 0.4, w + 1.3, d + 1.3, plinth + 0.4, GRANITE)
        if steps:
            for k in range(2):
                F.box(b, 0, -(d / 2 + 0.65 + 0.16 + 0.32 * k), z0 - 0.4, 2.8, 0.32, 0.4 + plinth * (2 - k) / 3, GRANITE)
    nb = max(3, int(round(w / 3.3)) | 1)
    ns = max(1, int(round(d / 3.4)))
    xs = [-w / 2 + w * i / nb for i in range(nb + 1)]
    ys = [-d / 2 + d * i / ns for i in range(ns + 1)]
    yF, yB = -d / 2, d / 2
    H = hcol * floors + (0.45 if floors == 2 else 0.0)
    cr = 0.13
    def column(x, y, hh=None):
        F.col(b, x, y, zf, cr, H if hh is None else hh, WOOD)
        F.col(b, x, y, zf, cr + 0.07, 0.12, GRANITE, n=8)
    # 檐柱一圈
    for x in xs:
        column(x, yF); column(x, yB)
    for y in ys[1:-1]:
        column(-w / 2, y); column(w / 2, y)
    # 檐枋
    for y in (yF, yB):
        F.box(b, 0, y, zf + H - 0.30, w + 0.3, 0.16, 0.30, WOOD)
    for x in (-w / 2, w / 2):
        F.box(b, x, 0, zf + H - 0.30, 0.16, d + 0.3, 0.30, WOOD)
    def frieze(pa, pb, zt):   # 挂落
        lattice_w(b, F.p(*pa), F.p(*pb), zt - 0.74, zt - 0.32, nx=max(3, int(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) / 0.4)), nz=2, t=0.03, frame=0.04)
    t = 0.24
    if style == 'hall':
        yI = yF + porch
        F.box(b, 0, yB, zf, w, t, H, WHITE_WALL)
        for sg in (-1, 1):
            F.box(b, sg * w / 2, (yI + yB) / 2, zf, t, yB - yI, H, WHITE_WALL)
            # 山墙上的花窗（外侧）
            xo = sg * (w / 2 + t / 2 + 0.05)
            for fl in range(floors):
                zb = zf + fl * (hcol + 0.45)
                pa, pb = (xo, (yI + yB) / 2 - 0.75 * sg), (xo, (yI + yB) / 2 + 0.75 * sg)
                lattice_w(b, F.p(*pa), F.p(*pb), zb + 1.15, zb + 2.45, nx=4, nz=4, frame=0.09, glass=0.03, mat=GREYBRICK if fl == 0 else LATTICE)
        for i in range(nb):
            pa, pb = (xs[i] + cr, yI), (xs[i + 1] - cr, yI)
            door_run(b, F, pa, pb, zf, hcol)
            frieze((xs[i] + cr, yF), (xs[i + 1] - cr, yF), zf + hcol)
            if floors == 2:
                zu = zf + hcol + 0.45
                wall_piece(b, F.p(xs[i], yI), F.p(xs[i + 1], yI), zf + hcol - 0.05, 0.5, 0.5, 0.2, WHITE_WALL)
                window_run(b, F, pa, pb, zu, hcol, sill=0.9)
                # 二层前廊栏杆
                lattice_w(b, F.p(xs[i] + cr, yF), F.p(xs[i + 1] - cr, yF), zu, zu + 0.85, nx=6, nz=3, t=0.03, frame=0.05)
                frieze((xs[i] + cr, yF), (xs[i + 1] - cr, yF), zf + H)
        for x in xs[1:-1]:
            F.box(b, x, yI, zf, 0.14, 0.14, H, WOOD)
        if floors == 2:
            F.box(b, 0, (yF + yI) / 2, zf + hcol + 0.30, w, porch + 0.2, 0.15, WOOD)   # 楼板
    elif style == 'four':
        wi, di = w / 2 - porch, d / 2 - porch
        ring_ = [(-wi, -di), (wi, -di), (wi, di), (-wi, di)]
        nbi = max(3, int(round(2 * wi / 3.0)) | 1); nsi = max(1, int(round(2 * di / 3.0)))
        for e in range(4):
            pa, pb = ring_[e], ring_[(e + 1) % 4]
            m = nbi if e % 2 == 0 else nsi
            for k in range(m):
                a_, c_ = lerp2(pa, pb, k / m), lerp2(pa, pb, (k + 1) / m)
                X, Y = F.p(*a_); prism(b, X, Y, zf, 0.11, H, WOOD, n=8)
                door_run(b, F, lerp2(a_, c_, 0.04), lerp2(a_, c_, 0.96), zf, hcol)
        for i in range(nb):
            for y in (yF, yB):
                frieze((xs[i] + cr, y), (xs[i + 1] - cr, y), zf + H)
        for j in range(ns):
            for x in (-w / 2, w / 2):
                frieze((x, ys[j] + cr), (x, ys[j + 1] - cr), zf + H)
    elif style == 'open':
        F.box(b, 0, yB, zf, w, t, H, WHITE_WALL)
        # 背面粉墙外侧的大花窗
        for i in range(nb):
            xa, xb = xs[i] + 0.5, xs[i + 1] - 0.5
            lattice_w(b, F.p(xb, yB + t / 2 + 0.05), F.p(xa, yB + t / 2 + 0.05), zf + 1.05, zf + 2.35, nx=5, nz=4, frame=0.09, glass=0.03, mat=GREYBRICK)
        for i in range(nb):
            frieze((xs[i] + cr, yF), (xs[i + 1] - cr, yF), zf + H)
            if i != nb // 2:
                seat_rail(b, F.p(xs[i] + cr, yF), F.p(xs[i + 1] - cr, yF), zf, out=1)
        for j in range(ns):
            for sg in (-1, 1):
                x = sg * w / 2
                frieze((x, ys[j] + cr), (x, ys[j + 1] - cr), zf + H)
                pa, pb = F.p(x, ys[j] + cr), F.p(x, ys[j + 1] - cr)
                seat_rail(b, pa, pb, zf, out=-sg)
    elif style == 'gate':
        for (xa, xb) in ((-w / 2, -1.25), (1.25, w / 2)):
            F.box(b, (xa + xb) / 2, yF, zf, xb - xa, t, H, WHITE_WALL)
        F.box(b, 0, yF, zf + 2.9, 2.5, t, H - 2.9, WHITE_WALL)
        for sg in (-1, 1):   # 石库门框、抱鼓石
            F.box(b, sg * 1.25, yF - 0.02, zf, 0.3, t + 0.14, 3.0, GRANITE)
            F.col(b, sg * 1.7, yF - 0.45, zf - 0.1, 0.32, 0.55, GRANITE, n=14)
            F.box(b, sg * 1.7, yF - 0.45, zf - 0.3, 0.75, 0.6, 0.3, GRANITE)
        F.box(b, 0, yF - 0.02, zf + 2.75, 2.9, t + 0.14, 0.32, GRANITE)
        F.box(b, 0, yF - 0.2, zf + 3.05, 3.2, 0.55, 0.12, GREYBRICK)      # 门罩
        for sg in (-1, 1):   # 黑漆门扇
            F.box(b, sg * 0.56, yF + 0.02, zf, 1.08, 0.08, 2.75, LATTICE)
        for sg in (-1, 1):
            F.box(b, sg * w / 2, 0, zf, t, d, H, WHITE_WALL)
            xw = sg * (w / 4 + 0.6)   # 两侧高窗
            lattice_w(b, F.p(xw - 0.55, yF - t / 2 - 0.05), F.p(xw + 0.55, yF - t / 2 - 0.05), zf + 1.9, zf + 2.75, nx=4, nz=3, frame=0.09, glass=0.03, mat=GREYBRICK)
        for i in range(nb):   # 朝内院一面开敞：长窗
            door_run(b, F, (xs[i + 1] - cr, yB), (xs[i] + cr, yB), zf, hcol)
    # 硬山山墙：升到屋面
    zr = zf + H + 0.02
    if rh is None:
        rh = (0.62 if kind != 'gable' else 0.60) * (d / 2 + ov)
    if kind == 'gable':
        bb = d / 2 + ov
        for sg in (-1, 1):
            x = sg * w / 2
            if style not in ('hall', 'gate'):
                F.box(b, x, 0, zf, t, d, H, WHITE_WALL)
            if style == 'hall':
                F.box(b, x, (yF + yF + porch) / 2, zf, t, porch, H, WHITE_WALL)
            m = 10
            for k in range(m):
                ya, yb = -d / 2 - 0.25 + (d + 0.5) * k / m, -d / 2 - 0.25 + (d + 0.5) * (k + 1) / m
                za, zb = zr + rh * rcurve((bb - abs(ya)) / bb) - 0.03, zr + rh * rcurve((bb - abs(yb)) / bb) - 0.03
                for off in (-t / 2, t / 2):
                    b.add([F.p(x + off, ya, zf + H - 0.05), F.p(x + off, yb, zf + H - 0.05), F.p(x + off, yb, zb), F.p(x + off, ya, za)], [(0, 1, 2, 3)], WHITE_WALL)
        suzhou_roof(b, F, zr, w, d, rh, kind='gable', ov=ov, ovx=0.18, lift=0)
    else:
        suzhou_roof(b, F, zr, w, d, rh, kind=kind, ov=ov, lift=lift)
    if floors == 2:   # 腰檐
        if kind == 'gable':
            suzhou_roof(b, F, zf + hcol + 0.10, w, d + 0.1, 1.5, kind='gable', ov=1.05, ovx=0.0, lift=0, ridge=False)
        else:
            suzhou_roof(b, F, zf + hcol + 0.10, w + 0.1, d + 0.1, 1.5, kind='hip', ov=1.05, lift=0.5, ridge=False)
    ob = b.build()
    hw, hd = w / 2 + 0.9, d / 2 + 0.9
    cs = [F.p(sx * hw, sy * hd) for sx in (-1, 1) for sy in (-1, 1)]
    keep_rect(min(c[0] for c in cs), min(c[1] for c in cs), max(c[0] for c in cs), max(c[1] for c in cs), pad=0.1)
    return ob

def pavilion(name, cx, cy, R=2.2, n=6, phase=0.0, hcol=2.9, z0=None, plinth=0.35, open_sides=(), stilt=False, lift=1.1):
    """亭：台基、柱、坐槛美人靠、挂落、攒尖顶。"""
    b = B(name)
    z0 = ground(cx, cy) if z0 is None else z0
    zf = z0 + plinth
    zb = -1.2 if stilt else z0 - 0.4
    prism(b, cx, cy, zb, R + 0.55, zf - zb, GRANITE, n=n, phase=phase)
    C = [(cx + R * math.cos(2 * math.pi * i / n + phase), cy + R * math.sin(2 * math.pi * i / n + phase)) for i in range(n)]
    for (x, y) in C:
        prism(b, x, y, zf, 0.12, hcol, WOOD, n=10)
        prism(b, x, y, zf, 0.19, 0.12, GRANITE, n=8)
    for i in range(n):
        p0, p1 = C[i], C[(i + 1) % n]
        a_, c_ = lerp2(p0, p1, 0.07), lerp2(p0, p1, 0.93)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        rbox(b, (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, zf + hcol - 0.26, math.hypot(p1[0] - p0[0], p1[1] - p0[1]) + 0.2, 0.14, 0.26, WOOD, ang)
        lattice_w(b, a_, c_, zf + hcol - 0.68, zf + hcol - 0.28, nx=5, nz=2, t=0.03, frame=0.04)
        if i not in open_sides:
            seat_rail(b, a_, c_, zf, out=1)
    Rr = R + 0.95
    pav_roof(b, cx, cy, zf + hcol + 0.02, Rr, 0.92 * Rr * math.cos(math.pi / n) + 0.4, n=n, phase=phase, lift=lift)
    b.build()
    keep(cx, cy, R + 1.2)

def corridor(name, pts, w=1.5, hcol=2.5, rails=(1, -1), wall_side=0, z0=None, open_bays=()):
    """廊：沿折线，两坡小瓦顶；rails 指定哪一侧设坐槛（1 左 / −1 右），wall_side 一侧为粉墙。"""
    global N_ROWS
    b = B(name)
    zf = (GZ if z0 is None else z0) + 0.16
    ze, zr = zf + hcol, zf + hcol + 0.68
    ovh = w / 2 + 0.42
    Lp, Rp = offset_poly(pts, ovh), offset_poly(pts, -ovh)
    cl, cr_ = offset_poly(pts, w / 2), offset_poly(pts, -w / 2)
    fl, fr = offset_poly(pts, w / 2 + 0.18), offset_poly(pts, -(w / 2 + 0.18))
    for i in range(len(pts) - 1):
        # 台基
        q = [fl[i], fl[i + 1], fr[i + 1], fr[i]]
        v = [(x, y, zf - 0.5) for (x, y) in q] + [(x, y, zf) for (x, y) in q]
        b.add(v, [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)], GRANITE)
        keep_rect(min(p[0] for p in q), min(p[1] for p in q), max(p[0] for p in q), max(p[1] for p in q), pad=0.5)
        # 屋面
        Ls = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for (E, sg) in ((Lp, 1), (Rp, -1)):
            v = [(E[i][0], E[i][1], ze), (E[i + 1][0], E[i + 1][1], ze), (pts[i + 1][0], pts[i + 1][1], zr), (pts[i][0], pts[i][1], zr)]
            b.add(v, [(0, 1, 2, 3)], DARK_TILE, uvs=[[(0, 0), (Ls, 0), (Ls, 1.6), (0, 1.6)]])
            b.add([v[0], v[1], (v[1][0], v[1][1], ze - 0.1), (v[0][0], v[0][1], ze - 0.1)], [(0, 1, 2, 3)], RIDGE)
            m = max(1, int(Ls / 0.27))
            for k in range(m):
                s = (k + 0.5) / m
                e = lerp2(E[i], E[i + 1], s); c = lerp2(pts[i], pts[i + 1], s)
                rod(b, (e[0], e[1], ze), (c[0], c[1], zr), 0.055, TILE_ROW)
                N_ROWS += 1
        rod(b, (pts[i][0], pts[i][1], zr), (pts[i + 1][0], pts[i + 1][1], zr), 0.09, RIDGE)
        # 柱、枋、挂落、坐槛
        m = max(1, int(round(Ls / 2.3)))
        for (Cc, sg) in ((cl, 1), (cr_, -1)):
            if wall_side == sg:
                wall_piece(b, Cc[i], Cc[i + 1], zf - 0.5, hcol + 0.5, hcol + 0.5, 0.22, WHITE_WALL)
                continue
            for k in range(0 if i == 0 else 1, m + 1):   # 转角柱只放一根
                x, y = lerp2(Cc[i], Cc[i + 1], k / m)
                prism(b, x, y, zf, 0.09, hcol, WOOD, n=8)
            rod(b, (Cc[i][0], Cc[i][1], ze - 0.24), (Cc[i + 1][0], Cc[i + 1][1], ze - 0.24), 0.06, WOOD)
            for k in range(m):
                a_, c_ = lerp2(Cc[i], Cc[i + 1], (k + 0.06) / m), lerp2(Cc[i], Cc[i + 1], (k + 0.94) / m)
                lattice_w(b, a_, c_, ze - 0.62, ze - 0.26, nx=5, nz=2, t=0.025, frame=0.035)
                if sg in rails and (i, k, sg) not in open_bays:
                    wall_piece(b, a_, c_, zf, 0.40, 0.40, 0.22, WHITE_WALL)
                    wall_piece(b, a_, c_, zf + 0.40, 0.06, 0.06, 0.28, WOOD)
    b.build()

# 漏窗花格图案（单位正方形内的线段）
def _lw_pattern(kind):
    segs = []
    if kind == 0:      # 方格
        for k in (0.25, 0.5, 0.75):
            segs += [((k, 0), (k, 1)), ((0, k), (1, k))]
    elif kind == 1:    # 斜方格
        for k in (-0.5, 0.0, 0.5):
            for sgn in (1, -1):
                pts = []
                for t in (0.0, 1.0):
                    pts.append(t)
                x0, x1 = max(0.0, -k), min(1.0, 1 - k)
                if sgn == 1:
                    segs.append(((x0, x0 + k), (x1, x1 + k)))
                else:
                    segs.append(((x0, 1 - (x0 + k)), (x1, 1 - (x1 + k))))
    elif kind == 2:    # 套方
        for r in (0.32, 0.16):
            c0, c1 = 0.5 - r, 0.5 + r
            segs += [((c0, c0), (c1, c0)), ((c1, c0), (c1, c1)), ((c1, c1), (c0, c1)), ((c0, c1), (c0, c0))]
        segs += [((0.5, 0), (0.5, 0.18)), ((0.5, 0.82), (0.5, 1)), ((0, 0.5), (0.18, 0.5)), ((0.82, 0.5), (1, 0.5)),
                 ((0, 0), (0.18, 0.18)), ((1, 0), (0.82, 0.18)), ((1, 1), (0.82, 0.82)), ((0, 1), (0.18, 0.82))]
    else:              # 八角
        import math as _m
        P = [(0.5 + 0.34 * _m.cos(_m.pi / 8 + _m.pi / 4 * i), 0.5 + 0.34 * _m.sin(_m.pi / 8 + _m.pi / 4 * i)) for i in range(8)]
        segs += [(P[i], P[(i + 1) % 8]) for i in range(8)]
        segs += [((0.5, 0), (0.5, 0.16)), ((0.5, 0.84), (0.5, 1)), ((0, 0.5), (0.16, 0.5)), ((0.84, 0.5), (1, 0.5)),
                 ((0.5, 0.3), (0.5, 0.7)), ((0.3, 0.5), (0.7, 0.5))]
    return segs

def moon_piece(b, pa, pb, z0, h, t, R, mat):
    """带月洞门的一段墙：墙面是矩形挖去圆洞的环形面，洞口砌清水砖边。"""
    (ax, ay), (bx, by) = pa, pb
    L = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / L, (by - ay) / L
    nx, ny = -uy, ux
    zc = z0 + R + 0.14
    hw = L / 2
    angs = sorted(set([2 * math.pi * i / 48 for i in range(48)] +
                      [math.atan2(sz, sx) % (2 * math.pi) for sx in (-hw, hw) for sz in (z0 - zc, z0 + h - zc)]))
    def rect_pt(th):
        c, s = math.cos(th), math.sin(th)
        k = min(hw / abs(c) if abs(c) > 1e-9 else 1e9, ((z0 + h - zc) / s) if s > 1e-9 else (((z0 - zc) / s) if s < -1e-9 else 1e9))
        return c * k, s * k
    def P3(u, zz, off):
        return (ax + ux * (hw + u) + nx * off, ay + uy * (hw + u) + ny * off, zc + zz)
    N = len(angs)
    for off in (-t / 2, t / 2):
        v = []
        for th in angs:
            v.append(P3(R * math.cos(th), R * math.sin(th), off))
            ru_, rz_ = rect_pt(th)
            v.append(P3(ru_, rz_, off))
        f = [(2 * i, 2 * ((i + 1) % N), 2 * ((i + 1) % N) + 1, 2 * i + 1) for i in range(N)]
        b.add(v, f, mat)
    v = []
    for th in angs:   # 洞口内壁 + 砖边
        v.append(P3(R * math.cos(th), R * math.sin(th), -t / 2 - 0.03)); v.append(P3(R * math.cos(th), R * math.sin(th), t / 2 + 0.03))
    b.add(v, [(2 * i, 2 * i + 1, 2 * ((i + 1) % N) + 1, 2 * ((i + 1) % N)) for i in range(N)], GREYBRICK)
    for off in (-t / 2 - 0.03, t / 2 + 0.03):
        v = []
        for th in angs:
            v.append(P3(R * math.cos(th), R * math.sin(th), off)); v.append(P3((R + 0.16) * math.cos(th), (R + 0.16) * math.sin(th), off))
        b.add(v, [(2 * i, 2 * ((i + 1) % N), 2 * ((i + 1) % N) + 1, 2 * i + 1) for i in range(N)], GREYBRICK)

def garden_wall(name, pts, h=3.0, t=0.28, ops=None, wave=0.0, cap=True, mat=None):
    """园墙：粉墙 + 墙帽。ops = {段号: [(沿段距离, 'window'|'moon'|'door', 参数...)]}；wave > 0 为云墙（墙顶起伏）。"""
    mat = mat or WHITE_WALL
    b = B(name)
    ops = ops or {}
    S0 = 0.0
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
        z0 = GZ - 0.3
        def at(s):
            return (p0[0] + ux * s, p0[1] + uy * s)
        def hf(s):
            return h + 0.3 + (wave * math.sin(2 * math.pi * (S0 + s) / 7.0) if wave else 0.0)
        def plain(sa, sb):
            if sb - sa < 0.03:
                return
            m = max(1, int(math.ceil((sb - sa) / 0.6))) if wave else 1
            for k in range(m):
                s0, s1 = sa + (sb - sa) * k / m, sa + (sb - sa) * (k + 1) / m
                wall_piece(b, at(s0), at(s1), z0, hf(s0), hf(s1), t, mat)
                if cap:
                    wall_cap(b, at(s0), at(s1), z0 + hf(s0), z0 + hf(s1), t)
        cur = 0.0
        for op in sorted(ops.get(i, [])):
            s, kind = op[0], op[1]
            if kind == 'window':
                par = list(op[2:])
                pat = int(par[0]) if len(par) > 0 else 0
                ww = float(par[1]) if len(par) > 1 else 1.2
                wh = float(par[2]) if len(par) > 2 else 1.2
                sill = float(par[3]) if len(par) > 3 else 1.45
                sa, sb = s - ww / 2, s + ww / 2
                plain(cur, sa)
                zb = GZ + sill
                wall_piece(b, at(sa), at(sb), z0, zb - z0, zb - z0, t, mat)
                wall_piece(b, at(sa), at(sb), zb + wh, z0 + hf(sa) - zb - wh, z0 + hf(sb) - zb - wh, t, mat)
                if cap:
                    wall_cap(b, at(sa), at(sb), z0 + hf(sa), z0 + hf(sb), t)
                # 砖框
                ang = math.atan2(uy, ux)
                for (cs, cz, bw, bh) in ((s, zb - 0.05, ww + 0.2, 0.09), (s, zb + wh - 0.04, ww + 0.2, 0.09), (sa, zb, 0.09, wh), (sb, zb, 0.09, wh)):
                    cxy = at(cs)
                    rbox(b, cxy[0], cxy[1], cz, bw, t + 0.06, bh, GREYBRICK, ang)
                for (q0, q1) in _lw_pattern(pat):
                    a3, b3 = at(sa + q0[0] * ww), at(sa + q1[0] * ww)
                    rod(b, (a3[0], a3[1], zb + q0[1] * wh - 0.03), (b3[0], b3[1], zb + q1[1] * wh - 0.03), 0.035, RIDGE)
                cur = sb
            elif kind == 'moon':
                R = float(op[2]) if len(op) > 2 else 1.05
                sa, sb = s - R - 0.55, s + R + 0.55
                plain(cur, sa)
                moon_piece(b, at(sa), at(sb), GZ - 0.02, hf(s) - 0.28, t, R, mat)
                wall_piece(b, at(sa), at(sb), z0, 0.3, 0.3, t, mat)
                if cap:
                    wall_cap(b, at(sa), at(sb), z0 + hf(s), z0 + hf(s), t)
                cxy = at(s)
                rbox(b, cxy[0], cxy[1], GZ - 0.05, 1.5, t + 0.5, 0.12, GRANITE, math.atan2(uy, ux))   # 门槛石
                cur = sb
            elif kind == 'door':
                dw, dh = (float(op[2]) if len(op) > 2 else 1.15), (float(op[3]) if len(op) > 3 else 2.15)
                sa, sb = s - dw / 2, s + dw / 2
                plain(cur, sa)
                wall_piece(b, at(sa), at(sb), GZ + dh, z0 + hf(sa) - GZ - dh, z0 + hf(sb) - GZ - dh, t, mat)
                if cap:
                    wall_cap(b, at(sa), at(sb), z0 + hf(sa), z0 + hf(sb), t)
                ang = math.atan2(uy, ux)
                for cs in (sa, sb):
                    cxy = at(cs)
                    rbox(b, cxy[0], cxy[1], GZ - 0.05, 0.1, t + 0.06, dh + 0.1, GREYBRICK, ang)
                cxy = at(s)
                rbox(b, cxy[0], cxy[1], GZ + dh, dw + 0.2, t + 0.06, 0.1, GREYBRICK, ang)
                cur = sb
        plain(cur, L)
        S0 += L
    b.build()
    for i in range(len(pts) - 1):
        m = max(1, int(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) / 1.0))
        for k in range(m + 1):
            x, y = lerp2(pts[i], pts[i + 1], k / m)
            keep(x, y, 0.55)

def arch_bridge(name, p0, p1, w=1.6, rise=0.95):
    """小石拱桥：桥身一孔半圆拱，桥面起拱，两侧石栏板。"""
    b = B(name)
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    F = Fr((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    N = 16
    ra = L * 0.30
    zb = GZ - 0.02
    prof = []
    for i in range(N + 1):
        u = i / N; x = -L / 2 + L * u
        zt = zb + rise * (1 - (2 * u - 1) ** 2) ** 0.9
        zo = (-0.25 + math.sqrt(max(0.0, ra * ra - x * x)) * 1.05) if abs(x) < ra else -1.2
        prof.append((x, zt, min(zo, zt - 0.22)))
    for i in range(N):
        (xa, ta, ba), (xb, tb, bb_) = prof[i], prof[i + 1]
        v = [F.p(xa, -w / 2, ta), F.p(xa, w / 2, ta), F.p(xb, w / 2, tb), F.p(xb, -w / 2, tb),
             F.p(xa, -w / 2, ba), F.p(xa, w / 2, ba), F.p(xb, w / 2, bb_), F.p(xb, -w / 2, bb_)]
        b.add(v, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 4, 7, 3), (1, 2, 6, 5), (0, 1, 5, 4), (3, 7, 6, 2)], GRANITE)
        F.box(b, (xa + xb) / 2, 0, (ta + tb) / 2 - 0.02, (xb - xa) * 0.9, w - 0.36, 0.06, SLAB)     # 踏步
        for sg in (-1, 1):
            y = sg * (w / 2 - 0.09)
            zmin = min(ta, tb)
            wall_piece(b, F.p(xa, y), F.p(xb, y), zmin, ta + 0.42 - zmin, tb + 0.42 - zmin, 0.14, GRANITE)
    for sg in (-1, 1):
        for xe in (-L / 2, L / 2):
            F.box(b, xe, sg * (w / 2 - 0.09), zb - 0.1, 0.22, 0.22, 0.75, GRANITE)
    b.build()
    keep(F.cx, F.cy, L / 2 + 0.6); keep(p0[0], p0[1], 1.2); keep(p1[0], p1[1], 1.2)

def zigzag_bridge(name, pts, w=1.3):
    """曲桥：石板桥面贴水，折线转折，低栏。"""
    b = B(name)
    zt = GZ - 0.02
    Lp, Rp = offset_poly(pts, w / 2), offset_poly(pts, -w / 2)
    for i in range(len(pts) - 1):
        q = [Lp[i], Lp[i + 1], Rp[i + 1], Rp[i]]
        v = [(x, y, zt - 0.16) for (x, y) in q] + [(x, y, zt) for (x, y) in q]
        b.add(v, [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)], SLAB)
        Ls = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        m = max(1, int(round(Ls / 2.2)))
        for k in range(m + 1):
            x, y = lerp2(pts[i], pts[i + 1], k / m)
            if pond_sd(x, y) < 0.2:
                rbox(b, x, y, -1.2, w - 0.3, 0.34, zt - 0.16 + 1.2, GRANITE, math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0]) + math.pi / 2)
        keep(*lerp2(pts[i], pts[i + 1], 0.5), Ls / 2 + 0.3)
    li, ri = offset_poly(pts, w / 2 - 0.1), offset_poly(pts, -(w / 2 - 0.1))
    stone_rail(b, li, zt, h=0.42); stone_rail(b, ri, zt, h=0.42)
    b.build()

def step_path(b, pts, w=1.1, mat=None):
    """石板小径：不规则石板逐块铺出。"""
    mat = mat or SLAB
    P, L = polyline(pts)
    s = 0.0
    while s < L:
        ln = ru(0.55, 0.95)
        x, y, dx, dy = P(min(L, s + ln / 2))
        if pond_sd(x, y) > 0.3:
            # 每块石板高低略有参差：既像手工铺的，也保证小径交汇处的石板不会共面（共面会互相遮光，渲染成黑块）
            rbox(b, x + ru(-0.05, 0.05), y + ru(-0.05, 0.05), ground(x, y) - 0.12, ln - 0.06, w * ru(0.82, 1.05), 0.165 + ru(0.0, 0.035), mat, math.atan2(dy, dx) + ru(-0.06, 0.06))
            keep(x, y, w * 0.6)
        s += ln

def pebble_path(b, pts, w=1.3):
    """花街铺地：卵石路面 + 青砖镶边。"""
    Lp, Rp = offset_poly(pts, w / 2), offset_poly(pts, -w / 2)
    for i in range(len(pts) - 1):
        q = [Lp[i], Lp[i + 1], Rp[i + 1], Rp[i]]
        z = max(ground(*pts[i]), ground(*pts[i + 1])) + 0.035
        v = [(x, y, z - 0.2) for (x, y) in q] + [(x, y, z) for (x, y) in q]
        b.add(v, [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)], PEBBLE)
        rod(b, (Lp[i][0], Lp[i][1], z - 0.02), (Lp[i + 1][0], Lp[i + 1][1], z - 0.02), 0.05, GREYBRICK)
        rod(b, (Rp[i][0], Rp[i][1], z - 0.02), (Rp[i + 1][0], Rp[i + 1][1], z - 0.02), 0.05, GREYBRICK)
        m = max(1, int(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) / 0.8))
        for k in range(m + 1):
            keep(*lerp2(pts[i], pts[i + 1], k / m), w * 0.62)

N_PAVE = 0
def pave(b, x0, y0, x1, y1, mat=None, z=None):
    global N_PAVE
    mat = mat or PAVE
    z = GZ if z is None else z
    N_PAVE += 1                       # 每块铺地比上一块高 2 毫米：相叠时不会共面（共面会互相遮光，渲染成黑块）
    box(b, (x0 + x1) / 2, (y0 + y1) / 2, z - 0.25, abs(x1 - x0), abs(y1 - y0), 0.29 + 0.002 * N_PAVE, mat)
    keep_rect(x0, y0, x1, y1, pad=0.05)

# ----------------------------------------------------------------------------- 山石（融球体：正球堆叠成形，负球挖出孔洞）
ROCKS = {}   # kind -> [(mesh, height, zmin, radius)]
def make_rock(tag, seed, kind, res_k=1.0):
    rnd = random.Random(seed)
    mb = bpy.data.metaballs.new("MB" + tag)
    mb.resolution = (0.075 if kind != 'block' else 0.14) * res_k
    mb.render_resolution = mb.resolution
    mb.threshold = 0.6
    ob = bpy.data.objects.new("MBO" + tag, mb)
    COL.objects.link(ob)
    def el(x, y, z, r, sx=1.0, sy=1.0, sz=1.0, neg=False, stiff=2.0):
        e = mb.elements.new(type='ELLIPSOID' if not neg else 'BALL')
        e.co = (x, y, z); e.radius = r; e.stiffness = stiff
        if not neg:
            e.size_x, e.size_y, e.size_z = sx, sy, sz
        e.use_negative = neg
    if kind == 'taihu':        # 瘦、皱、漏、透：上大下小的竖向团块，周身孔洞
        z = 0.30; top = 0.0
        for k in range(rnd.randint(4, 6)):
            r = rnd.uniform(0.50, 0.80) * (0.85 + 0.08 * k)
            el(rnd.uniform(-0.28, 0.28), rnd.uniform(-0.22, 0.22), z, r, rnd.uniform(0.8, 1.15), rnd.uniform(0.6, 0.9), rnd.uniform(0.85, 1.2))
            top = z + r * 0.7
            z += r * rnd.uniform(0.50, 0.72)
        for k in range(rnd.randint(2, 3)):
            a = rnd.uniform(0, 6.28)
            el(0.5 * math.cos(a), 0.4 * math.sin(a), rnd.uniform(0.3, top * 0.8), rnd.uniform(0.35, 0.5))
        for k in range(rnd.randint(10, 14)):
            a = rnd.uniform(0, 6.28); d = rnd.uniform(0.12, 0.60)
            el(d * math.cos(a), d * 0.8 * math.sin(a), rnd.uniform(0.35, top), rnd.uniform(0.22, 0.40), neg=True)
        for k in range(rnd.randint(3, 5)):     # 表面的小瘤突
            a = rnd.uniform(0, 6.28)
            el(0.62 * math.cos(a), 0.5 * math.sin(a), rnd.uniform(0.4, top), rnd.uniform(0.2, 0.3))
    elif kind == 'peak':       # 立峰：高而瘦，孔洞更多
        z = 0.35; top = 0.0
        for k in range(rnd.randint(7, 9)):
            r = rnd.uniform(0.42, 0.66) * (0.9 + 0.05 * k if k < 5 else 1.0)
            el(rnd.uniform(-0.22, 0.22), rnd.uniform(-0.18, 0.18), z, r, rnd.uniform(0.8, 1.2), rnd.uniform(0.6, 0.85), rnd.uniform(0.9, 1.3))
            top = z + r * 0.7
            z += r * rnd.uniform(0.55, 0.75)
        for k in range(rnd.randint(9, 13)):
            a = rnd.uniform(0, 6.28); d = rnd.uniform(0.2, 0.55)
            el(d * math.cos(a), d * 0.8 * math.sin(a), rnd.uniform(0.4, top), rnd.uniform(0.22, 0.38), neg=True)
    else:                      # 黄石 / 驳岸石：敦实的块
        for k in range(rnd.randint(2, 3)):
            el(rnd.uniform(-0.35, 0.35), rnd.uniform(-0.3, 0.3), rnd.uniform(0.2, 0.45), rnd.uniform(0.55, 0.8), rnd.uniform(0.9, 1.4), rnd.uniform(0.8, 1.1), rnd.uniform(0.55, 0.8), stiff=3.0)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.metaballs.remove(mb)
    me.name = "Rock" + tag
    # 表面皱褶：沿法线按噪声起伏；黄石再做块面化（顶点吸附到粗格点）
    off = seed * 3.7
    for v in me.vertices:
        x, y, z = v.co
        nrm = v.normal
        dsp = (fbm(x * 2.3 + z * 1.6 + off, y * 2.3 - z * 1.1 + off, 3) - 0.5) * (0.26 if kind != 'block' else 0.12)
        dsp += (fbm(x * 7.0 + z * 4.0 + off, y * 7.0 - z * 3.0, 2) - 0.5) * 0.09
        v.co = (x + nrm.x * dsp, y + nrm.y * dsp, z + nrm.z * dsp)
        if kind == 'block':
            q = 0.22
            v.co = (v.co.x * 0.6 + round(v.co.x / q) * q * 0.4, v.co.y * 0.6 + round(v.co.y / q) * q * 0.4, v.co.z * 0.5 + round(v.co.z / q) * q * 0.5)
    me.polygons.foreach_set("use_smooth", [kind != 'block'] * len(me.polygons))
    me.materials.append(TAIHU if kind != 'block' else HUANGSHI)
    me.update()
    zs = [v.co.z for v in me.vertices]
    rad = max(math.hypot(v.co.x, v.co.y) for v in me.vertices)
    return (me, max(zs) - min(zs), min(zs), rad)

def make_rocks():
    t0 = time.time()
    for kind, n in (('taihu', 8), ('peak', 5), ('block', 6)):
        lst = []
        for i in range(n):
            r = make_rock(f"{kind}{chr(97 + i)}", 100 + i * 7 + len(kind), kind)
            if WEB:   # 网页版用粗一档的网格，但尺寸仍取精细网格的（两边布局才一致）
                lite = make_rock(f"{kind}{chr(97 + i)}w", 100 + i * 7 + len(kind), kind, res_k=1.5)
                bpy.data.meshes.remove(r[0])
                r = (lite[0], r[1], r[2], r[3])
            lst.append(r)
        ROCKS[kind] = lst
    print("[sz] rocks:", {k: [(round(h, 2), len(m.polygons)) for (m, h, _, _) in v] for k, v in ROCKS.items()}, f"in {time.time() - t0:.1f}s")

N_ROCKS = 0
def rock(kind, x, y, s=1.0, z=None, sink=0.12, rot=None, tilt=0.12, reg=True):
    global N_ROCKS
    me, h, zmin, rad = random.choice(ROCKS[kind])
    sc = (s * ru(0.85, 1.15), s * ru(0.85, 1.15), s * ru(0.9, 1.2))
    z = ground(x, y) if z is None else z
    loc = (x, y, z - zmin * s - sink * s)
    eul = (ru(-tilt, tilt), ru(-tilt, tilt), ru(0, 6.28) if rot is None else rot)
    if WEB:
        _lib(me).append([round(v, 3) for v in (*loc, *sc, *eul)])
        ob = None
    else:
        ob = bpy.data.objects.new("Rock", me)
        ob.scale = sc
        ob.location = loc
        ob.rotation_euler = eul
        COL.objects.link(ob)
    if reg:
        keep(x, y, rad * s * 0.75)
    N_ROCKS += 1
    return ob

# ----------------------------------------------------------------------------- 植物
VARIANTS = {}      # kind -> [(mesh, height, zmin)]
TREE_H = {"tree": 8.5, "willow": 6.5, "pine": 5.2, "peach": 3.2, "bush": 1.1, "maple": 4.4, "ginkgo": 10.5}   # 米
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
TINTS = {"peach": ((0.96, 0.62, 0.72), 0.7), "maple": ((0.62, 0.20, 0.08), 0.66), "ginkgo": ((0.84, 0.64, 0.17), 0.68)}
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
        col = mix_rgb(nt, col, rgb(nt, (0.24, 0.42, 0.27)), 0.65, 'MIX')
    elif 'tree_small' in mat.name:
        col = mix_rgb(nt, col, rgb(nt, (0.44, 0.62, 0.22)), 0.55, 'MIX')
    else:
        col = mix_rgb(nt, col, rgb(nt, (0.36, 0.48, 0.22)), 0.55, 'MIX')
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
    print("[sz] tree library:", {k: [(round(h, 2)) for (_, h, _) in v] for k, v in VARIANTS.items()})

N_PLANTS = 0
def plant(kind, x, y, s=1.0, z=None):
    global N_PLANTS
    if isl_rho(x, y)[0] > 0.975:   # 岛缘之外不种树（避免悬空）
        return None
    if z is None:
        z = ground(x, y) - 0.03
    if WEB:
        vi = random.randrange(len(LIB_TREES[kind]))       # 与成图分支消耗同样多的随机数：变体、两次缩放、一次朝向
        random.uniform(0.9, 1.1); random.uniform(0.9, 1.1)
        PLANTS.append([kind, vi, round(x, 2), round(y, 2), round(z + 0.03, 2), round(s * TREE_H[kind], 2), round(random.uniform(0, 6.28), 2)])
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



def mesh_bamboo(seed):
    """一丛竹：若干竹竿（略向外倾）+ 节间的小枝叶（披针形叶片）。"""
    rnd = random.Random(seed)
    b = B("BambooSrc")
    for c in range(rnd.randint(7, 11)):
        bx, by = rnd.uniform(-0.45, 0.45), rnd.uniform(-0.45, 0.45)
        h = rnd.uniform(5.2, 8.0); lean = rnd.uniform(0.03, 0.13); la = math.atan2(by, bx) + rnd.uniform(-0.8, 0.8)
        prev = (bx, by, 0.0)
        nseg = 9
        for k in range(1, nseg + 1):
            t = k / nseg; bend = lean * h * t * t
            p = (bx + math.cos(la) * bend, by + math.sin(la) * bend, h * t)
            rod(b, prev, p, 0.040 * (1 - 0.55 * t), BAMBOO_CULM)
            if t > 0.46:
                for q in range(rnd.randint(3, 5)):
                    ang = rnd.uniform(0, 6.28); L = rnd.uniform(0.5, 1.0) * (1.25 - 0.55 * t)
                    tip = (p[0] + math.cos(ang) * L, p[1] + math.sin(ang) * L, p[2] + rnd.uniform(-0.3, 0.15))
                    for l in range(rnd.randint(5, 8)):
                        u = rnd.uniform(0.3, 1.0)
                        bs = (p[0] + (tip[0] - p[0]) * u, p[1] + (tip[1] - p[1]) * u, p[2] + (tip[2] - p[2]) * u)
                        a2 = ang + rnd.uniform(-1.1, 1.1); ll = rnd.uniform(0.24, 0.40); wd = ll * 0.17; dr = rnd.uniform(0.04, 0.2)
                        dx, dy = math.cos(a2), math.sin(a2)
                        v = [bs, (bs[0] + dx * ll * 0.45 - dy * wd, bs[1] + dy * ll * 0.45 + dx * wd, bs[2] - dr * 0.3 + 0.02),
                             (bs[0] + dx * ll, bs[1] + dy * ll, bs[2] - dr),
                             (bs[0] + dx * ll * 0.45 + dy * wd, bs[1] + dy * ll * 0.45 - dx * wd, bs[2] - dr * 0.3 - 0.02)]
                        b.add(v, [(0, 1, 2, 3)], BAMBOO_LEAF)
            prev = p
    ob = b.build()
    me = ob.data
    bpy.data.objects.remove(ob)
    return me

def mesh_banana(seed):
    """芭蕉：粗茎 + 弧形下垂的大叶。"""
    rnd = random.Random(seed)
    b = B("BananaSrc")
    cone(b, 0, 0, 0, 0.16, 0.09, 1.5, BAMBOO_CULM, n=8, uv=False)
    for k in range(rnd.randint(6, 8)):
        ang = 6.28 * k / 7 + rnd.uniform(-0.3, 0.3)
        L = rnd.uniform(1.5, 2.2); wd = rnd.uniform(0.26, 0.36); el = rnd.uniform(0.5, 1.1)
        dx, dy = math.cos(ang), math.sin(ang)
        N = 7
        pts = []
        for i in range(N + 1):
            t = i / N
            r = L * (t * math.cos(el) + 0.25 * t * t * (1 - math.cos(el)))
            z = 1.35 + L * (t * math.sin(el) - 0.75 * t * t)
            wdt = wd * math.sin(math.pi * min(1.0, t * 0.92 + 0.08)) ** 0.7
            pts.append((r, z, wdt))
        for i in range(N):
            (r0, z0, w0), (r1, z1, w1) = pts[i], pts[i + 1]
            c0, c1 = (dx * r0, dy * r0, z0), (dx * r1, dy * r1, z1)
            for sg in (-1, 1):
                e0 = (c0[0] - dy * w0 * sg, c0[1] + dx * w0 * sg, z0 + 0.06)
                e1 = (c1[0] - dy * w1 * sg, c1[1] + dx * w1 * sg, z1 + 0.06)
                b.add([c0, c1, e1, e0], [(0, 1, 2, 3)], BANANA)
    ob = b.build()
    me = ob.data
    bpy.data.objects.remove(ob)
    return me

def mesh_gpine(seed):
    """造型松（黑松 / 罗汉松）：盘曲的树干，层层平展的针叶云片。"""
    rnd = random.Random(seed)
    b = B("PineSrc")
    h = rnd.uniform(4.2, 5.6)
    a0 = rnd.uniform(0, 6.28)
    pts = []
    for k in range(8):
        t = k / 7
        r = 0.55 * math.sin(t * math.pi * 1.3) * (0.6 + 0.6 * t)
        pts.append((r * math.cos(a0 + t * 2.2), r * math.sin(a0 + t * 2.2), h * t))
    for k in range(7):
        rod(b, pts[k], pts[k + 1], 0.16 * (1 - 0.72 * (k / 7)), PINE_BARK)
    def pad(cx, cy, cz, r):
        # 一片"云"由三团相叠的扁球组成，边缘起伏，不是一张光滑的圆盘
        for (ox, oy, k) in ((0.0, 0.0, 1.0), (rnd.uniform(0.4, 0.6), rnd.uniform(-0.3, 0.3), 0.62), (rnd.uniform(-0.6, -0.4), rnd.uniform(-0.3, 0.3), 0.58)):
            a = rnd.uniform(0, 6.28)
            dx, dy = ox * math.cos(a) - oy * math.sin(a), ox * math.sin(a) + oy * math.cos(a)
            v, f = icosphere(cx + dx * r, cy + dy * r, cz + rnd.uniform(-0.05, 0.08) * r, r * k, sub=2, squash=0.40, jit=0.17)
            b.add(v, f, PINE_PAD)
    n = rnd.randint(6, 8)
    for i in range(n):
        t = 0.36 + 0.60 * i / (n - 1)
        k = min(6, int(t * 7)); u = t * 7 - k
        base = tuple(pts[k][j] + (pts[k + 1][j] - pts[k][j]) * u for j in range(3))
        ang = a0 + i * 2.4 + rnd.uniform(-0.4, 0.4)
        L = rnd.uniform(1.0, 1.9) * (1.15 - 0.6 * t)
        tip = (base[0] + math.cos(ang) * L, base[1] + math.sin(ang) * L, base[2] + rnd.uniform(-0.1, 0.25))
        rod(b, base, tip, 0.05, PINE_BARK)
        pad(tip[0], tip[1], tip[2] + 0.12, rnd.uniform(0.75, 1.1) * (1.1 - 0.45 * t))
        if rnd.random() < 0.6:
            m = tuple((base[j] + tip[j]) / 2 for j in range(3))
            pad(m[0] + rnd.uniform(-0.2, 0.2), m[1] + rnd.uniform(-0.2, 0.2), m[2] + 0.15, rnd.uniform(0.5, 0.75))
    pad(pts[-1][0], pts[-1][1], h + 0.1, rnd.uniform(0.8, 1.0))
    ob = b.build(smooth=True)
    me = ob.data
    bpy.data.objects.remove(ob)
    return me

def mesh_shrub(seed, flower=None):
    """修剪成球的灌木丛（黄杨、杜鹃）：几个相叠的扁球，杜鹃在表面缀花。"""
    rnd = random.Random(seed)
    b = B("ShrubSrc")
    for k in range(rnd.randint(3, 5)):
        r = rnd.uniform(0.36, 0.68)
        cx, cy = rnd.uniform(-0.5, 0.5), rnd.uniform(-0.5, 0.5)
        v, f = icosphere(cx, cy, r * 0.5, r, sub=2, squash=0.78, jit=0.07)
        b.add(v, f, SHRUB)
        if flower is not None:
            for q in range(16):
                a, e = rnd.uniform(0, 6.28), rnd.uniform(0.25, 1.4)
                v, f = icosphere(cx + r * math.cos(e) * math.cos(a), cy + r * math.cos(e) * math.sin(a), r * 0.5 + r * 0.78 * math.sin(e), 0.055, sub=0, squash=0.8, jit=0.0)
                b.add(v, f, flower)
    ob = b.build(smooth=True)
    me = ob.data
    bpy.data.objects.remove(ob)
    return me

EXTRA = {}
def make_extra_plants():
    EXTRA["gpine"] = [mesh_gpine(71 + i) for i in range(3)]
    EXTRA["shrub"] = [mesh_shrub(81), mesh_shrub(82), mesh_shrub(83, AZALEA[0]), mesh_shrub(84), mesh_shrub(85, AZALEA[1])]
    EXTRA["bamboo"] = [mesh_bamboo(31 + i) for i in range(4)]
    EXTRA["banana"] = [mesh_banana(51 + i) for i in range(3)]
    for k, lst in EXTRA.items():
        for i, me in enumerate(lst):
            me.name = f"{k}{chr(97 + i)}"
def inst(kind, x, y, s=1.0, z=None):
    me = random.choice(EXTRA[kind])
    sc = (s * ru(0.9, 1.1), s * ru(0.9, 1.1), s * ru(0.9, 1.12))
    loc = (x, y, (ground(x, y) if z is None else z) - 0.03)
    rz = ru(0, 6.28)
    keep(x, y, 0.8 * s)
    if WEB:
        _lib(me).append([round(v, 3) for v in (*loc, *sc, 0.0, 0.0, rz)])
        return None
    ob = bpy.data.objects.new(kind, me)
    ob.scale = sc
    ob.location = loc
    ob.rotation_euler = (0, 0, rz)
    COL.objects.link(ob)
    return ob

def lotus_patch(b, cx, cy, R, n):
    k = 0
    for _ in range(n * 4):
        if k >= n:
            break
        a, r = ru(0, 6.28), R * math.sqrt(random.random())
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if pond_sd(x, y) > -0.5 or blocked(x, y):
            continue
        rr = ru(0.22, 0.42)
        if random.random() < 0.3:      # 挺水的荷叶
            zz = ru(0.25, 0.6)
            rod(b, (x, y, -0.2), (x, y, zz), 0.012, BAMBOO_CULM)
            disc(b, x, y, zz, rr * 1.15, LOTUS_LEAF, n=11, tilt=(ru(-0.25, 0.25), ru(-0.25, 0.25)), dip=0.08)
        else:
            disc(b, x, y, 0.012, rr, LOTUS_LEAF, n=11, tilt=(ru(-0.02, 0.02), ru(-0.02, 0.02)), dip=0.0)
        if random.random() < 0.12:
            zz = ru(0.3, 0.6)
            rod(b, (x + 0.15, y, -0.2), (x + 0.15, y, zz), 0.01, BAMBOO_CULM)
            v, f = icosphere(x + 0.15, y, zz + 0.07, 0.09, sub=1, squash=1.25)
            b.add(v, f, LOTUS_FLOWER)
        k += 1

def koi(b, x, y, ang, L=0.5):
    c, s = math.cos(ang), math.sin(ang)
    pr = [(-0.5, 0.0), (-0.3, 0.09), (0.0, 0.12), (0.28, 0.08), (0.5, 0.0), (0.28, -0.08), (0.0, -0.12), (-0.3, -0.09)]
    v = [(x + (px * c - py * s) * L, y + (px * s + py * c) * L, -0.05) for (px, py) in pr]
    tl = [(-0.5, 0.0), (-0.72, 0.11), (-0.66, 0.0), (-0.72, -0.11)]
    v += [(x + (px * c - py * s) * L, y + (px * s + py * c) * L, -0.05) for (px, py) in tl]
    b.add(v, [(0, 1, 2, 3, 4, 5, 6, 7), (8, 9, 10, 11)], random.choice(KOI))

def tuft(b, x, y, s=1.0):
    """沿阶草：一小丛向外披散的细叶。"""
    z = ground(x, y)
    for k in range(7):
        a = ru(0, 6.28); L = ru(0.18, 0.32) * s; hgt = ru(0.12, 0.26) * s
        dx, dy = math.cos(a), math.sin(a)
        v = [(x - dy * 0.025, y + dx * 0.025, z), (x + dy * 0.025, y - dx * 0.025, z),
             (x + dx * L * 0.6, y + dy * L * 0.6, z + hgt), (x + dx * L, y + dy * L, z + hgt * 0.55)]
        b.add(v, [(0, 1, 2), (1, 3, 2)], TUFT)

def potted(b, x, y, z=None, s=1.0):
    z = (GZ + 0.04) if z is None else z
    cone(b, x, y, z, 0.20 * s, 0.30 * s, 0.34 * s, POT, n=10, uv=False)
    plant("bush", x, y, ru(0.55, 0.8) * s, z=z + 0.30 * s)

def wupeng(b, x, y, ang, L=6.0):
    """乌篷船：两头尖的船身，中段一截黑篷，船尾一支橹。"""
    F = Fr(x, y, ang)
    prof = [(-0.50, 0.0), (-0.38, 0.30), (-0.12, 0.42), (0.18, 0.42), (0.40, 0.28), (0.50, 0.0)]
    ring_ = [(px * L, pw * 0.80) for (px, pw) in prof] + [(px * L, -pw * 0.80) for (px, pw) in reversed(prof[1:-1])]
    n = len(ring_)
    v = [F.p(px, py, 0.42) for (px, py) in ring_] + [F.p(px * 0.86, py * 0.6, -0.14) for (px, py) in ring_]
    b.add(v, [tuple(range(n))], DECK)
    b.add(v, [(i, n + i, n + (i + 1) % n, (i + 1) % n) for i in range(n)], LATTICE)
    sy = (-F.s, F.c)
    tube(b, [F.p(xx, 0.0, 0.38) for xx in (-1.25, -0.4, 0.45, 1.3)], sy, 0.68, CANOPY, seg=7, full=True)
    rod(b, F.p(-0.42 * L, 0.2, 0.5), F.p(-0.62 * L, 0.9, -0.1), 0.03, WOOD)
    for xx in (-0.30 * L, 0.30 * L):                                   # 横舱板
        F.box(b, xx, 0.0, 0.42, 0.16, 1.05, 0.05, WOOD)
    for (xx, yy) in ((0.30 * L + 0.35, 0.18), (0.30 * L + 0.72, -0.12), (-0.30 * L - 0.4, -0.15)):   # 竹筐
        X, Y = F.p(xx, yy)
        cone(b, X, Y, 0.43, 0.15, 0.20, 0.24, BASKET, n=10, uv=False)
    rod(b, F.p(-0.36 * L, -0.42, 0.50), F.p(0.44 * L, -0.36, 0.56), 0.022, BAMBOO_CULM)      # 竹篙

def row_house(name, cx, cy, w, d, h):
    """墙外的邻家民居：粉墙、硬山瓦顶，楼上开窗。只作背景。"""
    b = B(name); F = Fr(cx, cy, 0.0)
    t = 0.24
    F.box(b, 0, 0, GZ - 0.3, w, d, h + 0.3, WHITE_WALL)
    ov = 0.45; bb = d / 2 + ov; rh = 0.64 * bb; zr = GZ + h + 0.02
    for sg in (-1, 1):
        x = sg * (w / 2 - t / 2)
        m = 8
        for k in range(m):
            ya, yb = -d / 2 + d * k / m, -d / 2 + d * (k + 1) / m
            za, zb = zr + rh * rcurve((bb - abs(ya)) / bb) - 0.03, zr + rh * rcurve((bb - abs(yb)) / bb) - 0.03
            for off in (-t / 2, t / 2):
                b.add([F.p(x + off, ya, GZ + h - 0.05), F.p(x + off, yb, GZ + h - 0.05), F.p(x + off, yb, zb), F.p(x + off, ya, za)], [(0, 1, 2, 3)], WHITE_WALL)
    suzhou_roof(b, F, zr, w, d, rh, kind='gable', ov=ov, ovx=0.15, lift=0)
    nw = max(2, int(w / 2.7))
    for k in range(nw):
        xw = -w / 2 + w * (k + 0.5) / nw
        lattice_w(b, F.p(xw - 0.55, -d / 2 - 0.05), F.p(xw + 0.55, -d / 2 - 0.05), GZ + h - 1.75, GZ + h - 0.55, nx=3, nz=3, frame=0.08, glass=0.03)
    b.build()
    keep_rect(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2, pad=0.6)

def canal_scene():
    """南面临河：石驳岸、河埠头、石拱桥、乌篷船；对岸垂柳。"""
    b = B("Canal")
    top = GZ + 0.07
    for k in range(-40, 40):
        xs_ = k + 0.5
        for (yq, sg) in ((CANAL[1], 1), (CANAL[0], -1)):
            yc = yq + sg * 0.25
            if isl_rho(xs_, yc + sg * 0.4)[0] < 0.992:
                box(b, xs_, yc, -1.2, 1.0, 0.8, top + 1.2, GRANITE)                      # 驳岸条石
    for x0 in (-8.0, 24.5):                                                              # 河埠头：石阶伸入水中
        for k in range(5):
            box(b, x0, CANAL[1] - 0.26 - 0.32 * k, -1.2, 2.6, 0.32, 1.2 + GZ - 0.03 - 0.115 * (k + 1), SLAB)
    for (x, y, a) in ((-6.6, CANAL[1] - 2.3, 0.05), (17.0, -35.6, 3.2), (1.5, CANAL[0] + 1.2, 3.12)):
        wupeng(b, x, y, a)
    for x in (-33.0, -21.5, -1.5, 5.0, 19.0, 31.5):                                      # 临河系船石、石凳
        if isl_rho(x, -31.9)[0] < 0.97:
            box(b, x, -31.95, GZ, 1.5, 0.42, 0.42, GRANITE)
    for k in range(-36, 36):                                                             # 对岸沿河小巷
        xs_ = k + 0.5
        if isl_rho(xs_, -40.0)[0] < 0.975:
            box(b, xs_, (CANAL[0] - 0.55 - 40.0) / 2, GZ - 0.3, 1.0, 40.0 + CANAL[0] - 0.55, 0.33, STREET)
    b.build()
    # 对岸的临河民居：只在东西两头各放一组，中间留空，不挡住拱桥和河面
    for (hx, hw_, hd_, hh) in ((-24.6, 7.0, 4.4, 3.1), (-17.4, 6.4, 4.2, 5.2), (24.0, 8.0, 4.4, 5.2), (17.4, 4.6, 3.8, 2.9)):
        row_house("Riverside", hx, -40.15 - hd_ / 2, hw_, hd_, hh)
    arch_bridge("CanalBridge", (12.0, CANAL[1] + 0.9), (12.0, CANAL[0] - 0.9), w=2.4, rise=1.35)

# ----------------------------------------------------------------------------- 场景布置
X0, X1, Y0, Y1 = -34.0, 34.0, -27.0, 27.0     # 园墙范围
XP = 23.0                                     # 住宅与花园之间的界墙

def build_scene():
    island()
    pond_water()
    make_variants()
    make_rocks()
    make_extra_plants()

    # ---- 建筑
    RX, RW = 28.35, 10.7                       # 住宅一路的中线与面阔
    hall("MainHall", -4.0, 17.4, 13.6, 8.0, kind='xieshan', style='four', hcol=3.5, porch=1.35, lift=0.9)          # 四面厅（北岸主厅）
    hall("Tower", -23.0, 19.0, 9.0, 6.6, kind='xieshan', style='hall', floors=2, hcol=3.0, porch=1.15, lift=0.85)   # 楼
    hall("Study", 15.6, 22.0, 8.6, 5.4, kind='gable', style='hall', hcol=3.0, porch=1.1)                            # 书斋
    hall("WaterPav", -8.0, -14.0, 6.4, 4.4, ang=math.pi, kind='xieshan', style='stilt', hcol=2.9, plinth=0.3, z0=GZ, lift=0.9)   # 水阁
    hall("GateHall", RX, -23.6, RW, 6.0, kind='gable', style='gate', hcol=3.3, plinth=0.3)
    hall("GreatHall", RX, -9.5, RW, 8.2, kind='gable', style='hall', hcol=3.9, porch=1.5)
    hall("RearTower", RX, 14.6, RW, 6.8, kind='gable', style='hall', floors=2, hcol=3.0, porch=1.2)
    pavilion("MoonPav", -19.3, -2.6, R=2.2, n=6, phase=0.0, stilt=True, open_sides=(2, 3))                           # 西岸六角亭
    zt = ground(-23.5, -18.5)
    pavilion("HillPav", -23.5, -18.5, R=1.75, n=4, phase=math.pi / 4, z0=zt - 0.1, hcol=2.7, open_sides=(0,), lift=1.0)   # 假山顶方亭
    pavilion("EastPav", 14.9, -3.2, R=1.9, n=4, phase=math.pi / 4, hcol=2.8, open_sides=(0, 1), stilt=True)           # 东岸方亭

    # ---- 月台（主厅前临水平台）
    b = B("Terrace")
    tx0, tx1, ty0, ty1 = -10.8, 2.8, 7.6, 12.6
    box(b, (tx0 + tx1) / 2, (ty0 + ty1) / 2, -1.2, tx1 - tx0, ty1 - ty0, GZ + 0.2 + 1.2, GRANITE)
    box(b, (tx0 + tx1) / 2, (ty0 + ty1) / 2, GZ + 0.2, tx1 - tx0 - 0.5, ty1 - ty0 - 0.5, 0.04, PAVE)
    stone_rail(b, [(tx0 + 0.15, ty1 - 1.2), (tx0 + 0.15, ty0 + 0.15), (tx1 - 0.15, ty0 + 0.15), (tx1 - 0.15, ty1 - 1.2)], GZ + 0.2, h=0.6)
    b.build()
    keep_rect(tx0, ty0, tx1, ty1)

    # ---- 廊
    corridor("WestCorridor", [(-23.0, 14.4), (-23.0, 10.6), (-27.2, 10.6), (-27.2, 3.2), (-23.4, 3.2), (-23.4, -7.0), (-28.2, -7.0), (-28.2, -11.6)],
             open_bays={(4, 1, 1), (4, 2, 1)})
    corridor("ResCorridor", [(X1 - 1.25, -4.9), (X1 - 1.25, 10.7)], w=1.4, rails=(1,), open_bays={(0, 2, 1), (0, 4, 1)})   # 住宅庭院东侧的廊
    corridor("EastCorridor", [(XP - 1.1, 11.6), (XP - 1.1, -3.0), (17.3, -3.0)], rails=(-1,), open_bays={(0, 3, -1)})

    # ---- 园墙：外墙、界墙、书斋小院（月洞门）
    def wins(n, a, bq, pats=(0, 1, 2, 3)):
        return [(a + (bq - a) * (k + 0.5) / n, 'window', pats[k % len(pats)]) for k in range(n)]
    garden_wall("WallSouth", [(X0, Y0), (XP, Y0)], h=2.9, wave=0.28, ops={0: wins(9, 3.0, 54.5)})
    garden_wall("WallWest", [(X0, Y0), (X0, Y1)], h=3.0, ops={0: wins(3, 8.0, 30.0, (2, 0, 3))})
    garden_wall("WallNorth", [(X0, Y1), (X1, Y1)], h=3.0)
    garden_wall("WallEast", [(X1, Y0), (X1, Y1)], h=3.3)
    garden_wall("WallPart", [(XP, Y0), (XP, Y1)], h=3.5,
                ops={0: [(10.0, 'door'), (29.0, 'moon', 1.05), (33.2, 'window', 2), (36.4, 'window', 0), (44.0, 'window', 3), (48.5, 'window', 1)]})
    garden_wall("WallStudyS", [(7.0, 12.9), (XP, 12.9)], h=2.9, ops={0: [(1.6, 'window', 1), (5.4, 'moon', 1.05), (9.0, 'window', 3), (12.0, 'window', 0)]})
    garden_wall("WallStudyW", [(7.0, 12.9), (7.0, Y1)], h=2.9, ops={0: [(4.0, 'window', 2), (9.5, 'window', 0)]})

    # ---- 桥
    arch_bridge("ArchBridge", (-18.1, 5.75), (-14.9, 9.45))
    ZP = [(8.4, -11.4), (8.4, -6.6), (5.2, -6.6), (5.2, -1.2), (8.4, -1.2), (8.4, 3.2), (6.0, 3.2), (6.0, 7.9)]
    zigzag_bridge("ZigzagBridge", ZP)
    print("[sz] bridge sd:", [round(pond_sd(*p), 2) for p in ZP], "arch:", round(pond_sd(-18.1, 5.75), 2), round(pond_sd(-14.9, 9.45), 2), round(pond_sd(-16.5, 7.6), 2))

    # ---- 铺地：院落方砖、花街铺地、外街石板
    b = B("Paving")
    for (x0, y0, x1, y1) in ((XP + 0.4, -20.4, 33.7, -13.8), (XP + 0.4, -5.2, 33.7, -2.9), (XP + 0.4, 8.6, 33.7, 10.7), (27.6, -2.9, 29.1, 8.6),
                             (XP + 0.4, 18.2, 33.7, 26.7),                                                                  # 住宅天井与庭院
                             (7.4, 13.3, XP - 0.4, 19.1), (7.4, 19.1, 11.2, 26.6),                                          # 书斋小院
                             (-28.0, 14.0, -18.0, 15.4)):
        pave(b, x0, y0, x1, y1)
    pave(b, 1.5, -24.6, 12.5, -18.2, mat=PEBBLE)                                                                            # 南院花街铺地
    for (x0, y0, x1, y1) in ((1.3, -24.8, 12.7, -24.6), (1.3, -18.2, 12.7, -18.0), (1.3, -24.6, 1.5, -18.2), (12.5, -24.6, 12.7, -18.2)):
        box(b, (x0 + x1) / 2, (y0 + y1) / 2, GZ - 0.2, x1 - x0, y1 - y0, 0.26, GREYBRICK)
    for k in range(-40, 40):                                                  # 南面街巷（按沙盘轮廓裁剪）
        xs_ = k + 0.5
        ya, yb = -27.62, CANAL[1] + 0.55
        if isl_rho(xs_, ya)[0] < 0.985 and isl_rho(xs_, yb)[0] < 0.99:
            box(b, xs_, (ya + yb) / 2, GZ - 0.3, 1.0, ya - yb, 0.33, STREET)
    keep_rect(-41, -40.1, 41, -27.6)
    # 厅堂四周的砖铺散水
    for (cx_, cy_, w_, d_) in ((-4.0, 17.4, 13.6, 8.0), (-23.0, 19.0, 9.0, 6.6)):
        pave(b, cx_ - w_ / 2 - 1.7, cy_ - d_ / 2 - 1.7, cx_ + w_ / 2 + 1.7, cy_ + d_ / 2 + 1.7)
    box(b, RX, -27.6, GZ - 0.3, 5.0, 1.4, 0.42, GRANITE)                      # 门前阶石
    b.build()
    canal_scene()
    for (hx, hw_, hh) in ((-22.0, 10.0, 5.6), (-10.2, 11.0, 4.3), (2.4, 11.4, 5.8), (14.6, 10.0, 4.4), (24.2, 7.4, 5.4)):   # 北面墙外的邻家
        row_house("Neighbor", hx, 29.4, hw_, 3.3, hh)
    b = B("Paths")
    for pts in ([(XP - 1.9, 2.0), (18.5, 0.6), (17.0, -1.2)],
                [(14.9, -5.4), (14.2, -8.6), (11.6, -12.6), (9.4, -12.6), (8.4, -11.7)],
                [(9.6, -13.0), (8.6, -15.6), (7.4, -17.8)],
                [(7.4, -13.4), (2.0, -15.6), (-3.0, -16.9), (-8.0, -16.9), (-12.5, -15.4), (-16.0, -14.4), (-18.8, -14.6)],
                [(-21.4, -2.6), (-22.6, -2.6)],
                [(-10.9, 11.6), (-12.8, 11.4), (-14.6, 10.0)], [(-18.4, 5.4), (-20.4, 4.4), (-22.5, 3.8)],
                [(2.9, 10.6), (5.0, 9.4), (6.0, 8.1)], [(6.2, 9.2), (9.4, 11.0), (12.4, 12.0)],
                [(12.6, 12.2), (17.0, 12.0), (XP - 1.9, 11.9)],
                [(-23.0, 15.2), (-23.0, 15.8)], [(-28.2, -12.0), (-27.4, -13.6), (-25.6, -15.4), (-24.4, -17.0)]):
        step_path(b, pts)
    pebble_path(b, [(-3.4, -17.2), (-1.4, -19.4), (1.4, -21.0)])
    b.build()

    # ---- 假山：西南太湖石大假山（山顶方亭）、立峰、池岸驳石
    for i in range(150):
        a, r = ru(0, 6.28), 7.6 * math.sqrt(random.random())
        x, y = -23.5 + r * math.cos(a), -18.5 + r * math.sin(a)
        if r < 2.5 or x < X0 + 0.9 or y < Y0 + 0.9 or pond_sd(x, y) < 0.6 or blocked(x, y, 0.72):
            continue
        k = 1 - r / 7.6
        rock('taihu' if random.random() < 0.85 else 'block', x, y, s=ru(0.6, 1.0) + 0.75 * k, sink=0.25)
    for (x, y, s) in ((-21.3, -17.2, 1.3), (-25.6, -20.4, 1.45), (-20.6, -21.0, 1.15), (-26.2, -16.4, 1.1)):
        rock('peak', x, y, s=s, sink=0.2, tilt=0.06)
    for (x, y, s) in ((12.2, 20.6, 1.5), (-13.4, 14.2, 1.2), (-30.6, -3.0, 1.25), (4.6, 14.6, 0.95), (25.6, 3.4, 1.15), (5.6, -21.6, 1.0)):   # 各处立峰
        rock('peak', x, y, s=s, sink=0.15, tilt=0.05)
        for k in range(3):
            a = ru(0, 6.28)
            rock('taihu', x + 1.0 * math.cos(a), y + 0.9 * math.sin(a), s=ru(0.35, 0.55), sink=0.2)
    for (x, y) in ((3.2, -19.4), (4.4, -22.8), (10.8, -22.6), (11.6, -19.2), (16.2, -15.8), (17.8, -18.6), (-1.0, -23.2)):   # 南院黄石
        for k in range(random.randint(2, 4)):
            rock('block', x + ru(-0.7, 0.7), y + ru(-0.6, 0.6), s=ru(0.6, 1.1), sink=0.25)
    n_bank = 0
    pts_b = []
    for i in range(18000):
        x, y = ru(-24, 18.5), ru(-15.5, 13.0)
        sd = pond_sd(x, y)
        if not (-0.55 < sd < 0.30):
            continue
        if (tx0 - 0.3 < x < tx1 + 0.3 and y > ty0 - 0.4) or blocked(x, y, 1.0):
            continue
        if any((x - px) ** 2 + (y - py) ** 2 < 0.46 ** 2 for (px, py) in pts_b):
            continue
        pts_b.append((x, y))
        big = fbm(x * 0.35 + 3, y * 0.35 + 9, 2) > 0.535
        if random.random() < 0.55:
            rock('block', x, y, s=ru(0.36, 0.70) * (2.2 if big else 1.0), z=0.05, sink=0.35, reg=False)
        else:
            rock('taihu', x, y, s=ru(0.26, 0.42) * (2.0 if big else 1.0), z=0.0, sink=0.3, reg=False)
        n_bank += 1
    for (px, py) in pts_b:
        keep(px, py, 0.5)
    print(f"[sz] bank rocks={n_bank}, rocks total={N_ROCKS}")

    # ---- 水中：荷、游鱼
    b = B("Lotus")
    lotus_patch(b, -11.5, 2.4, 3.4, 70)
    lotus_patch(b, -1.0, -8.6, 2.6, 36)
    lotus_patch(b, 12.2, -9.2, 2.0, 24)
    lotus_patch(b, 1.0, 4.4, 2.2, 26)
    b.build()
    b = B("Koi")
    for cxk, cyk, nk in ((-6.0, -4.0, 10), (1.5, 0.0, 8), (-13.0, -6.0, 7), (10.0, -4.0, 6), (-2.0, 5.5, 5)):
        for k in range(nk):
            x, y = cxk + ru(-1.8, 1.8), cyk + ru(-1.4, 1.4)
            if pond_sd(x, y) < -1.0 and not blocked(x, y, 1.0):
                koi(b, x, y, ru(0, 6.28), ru(0.45, 0.7))
    b.build()

    # ---- 乔木（位置逐一指定；南面只种矮的，不挡池面）
    for (kind, x, y, s) in (("pine", -13.2, 15.6, 1.15), ("pine", -19.4, -23.0, 1.1), ("pine", -28.4, -15.6, 0.95), ("pine", -16.6, 22.6, 1.2),
                            ("pine", 10.4, 24.0, 0.9), ("pine", 18.6, 9.4, 0.9), ("pine", -29.6, -22.6, 1.0),
                            ("maple", -14.6, -12.6, 1.0), ("maple", 13.2, 4.2, 1.0), ("maple", -27.0, -21.6, 0.9), ("maple", 3.0, -20.6, 0.95),
                            ("maple", -30.4, 7.4, 1.0), ("maple", 18.6, -15.0, 0.9), ("maple", 26.4, 6.6, 0.75),
                            ("ginkgo", -30.6, 23.2, 1.0),
                            ("willow", -13.2, -11.6, 0.9), ("willow", 11.6, 8.4, 0.95), ("willow", -20.6, 8.6, 0.85),
                            ("tree", -31.0, -1.0, 0.95), ("tree", 2.2, 24.4, 1.0), ("tree", -9.6, 24.6, 0.9),
                            ("tree", 18.2, 5.0, 0.7), ("tree", 30.2, 4.6, 0.5), ("tree", 25.0, -17.2, 0.5), ("tree", 31.0, 22.6, 0.6),
                            ("peach", 9.6, 17.0, 1.0), ("peach", 25.4, -1.4, 0.85), ("peach", -17.6, -10.4, 0.9), ("peach", 11.0, -20.6, 0.9)):
        if kind == "pine":
            inst("gpine", x, y, s * ru(0.95, 1.15))          # 园内用造型松，不用冷杉模型
        else:
            plant(kind, x, y, s)
        keep(x, y, 1.0)
    # 园外的大树（墙外借景）、临河与对岸的垂柳
    for (x, y, kind, s) in ((-37.0, -19.0, "tree", 1.1), (-37.4, -6.0, "tree", 1.25), (-37.2, 9.0, "tree", 1.05), (-36.6, 22.0, "ginkgo", 0.9),
                            (-28.6, 29.6, "tree", 1.1), (-15.9, 30.0, "tree", 1.0), (-3.9, 30.2, "tree", 1.15), (8.9, 30.0, "tree", 0.95),
                            (20.0, 30.0, "tree", 1.05), (29.6, 29.2, "tree", 0.9), (37.2, 18.0, "tree", 1.0), (37.3, 4.0, "tree", 0.9),
                            (37.2, -11.0, "tree", 0.95), (-37.0, 1.5, "pine", 1.2), (37.0, -24.0, "tree", 0.8),
                            (-30.0, -31.4, "willow", 1.0), (-15.5, -31.5, "willow", 0.9), (1.5, -31.4, "willow", 1.0), (30.0, -31.4, "willow", 0.85),
                            (-9.5, -41.4, "willow", 0.95), (-2.0, -42.6, "tree", 0.8), (6.0, -41.2, "willow", 0.9), (11.5, -43.0, "maple", 0.9),
                            (-30.5, -41.6, "willow", 0.9), (-12.6, -44.4, "tree", 0.7), (30.6, -41.4, "tree", 0.7)):
        plant(kind, x, y, s)
        keep(x, y, 1.2)
    for i in range(260):                                                                  # 对岸的灌木（成丛，避开民居）
        x, y = ru(-34.0, 34.0), ru(-45.4, -40.6)
        if isl_rho(x, y)[0] < 0.962 and not blocked(x, y, 1.0) and fbm(x * 0.3 + 2, y * 0.3 + 4.0, 2) > 0.52:
            if random.random() < 0.7:
                inst("shrub", x, y, ru(0.7, 1.2))
            else:
                plant("bush", x, y, ru(0.8, 1.4))
                keep(x, y, 0.55)
    # 竹：沿墙成片
    for (x0, y0, x1, y1, n) in ((-32.8, -9.0, -32.8, 12.5, 9), (-15.0, 25.6, 5.5, 25.6, 9), (19.0, 25.4, 22.0, 20.0, 3), (-32.6, -25.6, -29.5, -25.8, 2),
                                (8.6, 25.6, 8.6, 21.5, 2), (-36.2, -24.0, -35.6, 24.0, 8), (35.6, -4.0, 36.2, 24.0, 4),
                                (21.8, -25.6, 21.8, -20.5, 3), (-12.0, -25.7, -5.0, -25.7, 4), (14.0, -25.7, 20.5, -25.7, 4), (24.2, 10.2, 24.4, 7.4, 2)):
        for k in range(n):
            t = (k + 0.5) / n
            x, y = x0 + (x1 - x0) * t + ru(-0.7, 0.7), y0 + (y1 - y0) * t + ru(-0.7, 0.7)
            if not blocked(x, y, 0.6):
                inst("bamboo", x, y, ru(0.85, 1.2))
    # 芭蕉：粉墙前
    for (x, y, s) in ((-32.4, 15.6, 1.1), (8.4, 15.4, 1.0), (21.6, -14.2, 1.0), (-1.6, -25.4, 1.05), (24.2, -19.4, 0.8), (24.6, 4.6, 0.85), (32.6, 20.0, 0.8),
                      (-13.6, -19.6, 0.95), (21.4, 14.4, 0.9), (13.6, -25.2, 0.95)):
        inst("banana", x, y, s)
    # 灌木：空地上按噪声成丛
    nb_ = 0
    for i in range(3200):
        x, y = ru(X0 + 0.8, X1 - 0.8), ru(Y0 + 0.8, Y1 - 0.8)
        if pond_sd(x, y) < 0.9 or blocked(x, y, 1.0):
            continue
        if fbm(x * 0.22 + 5, y * 0.22 + 1, 3) < 0.54:
            continue
        if random.random() < 0.6:
            inst("shrub", x, y, ru(0.7, 1.25))               # 修剪成球的灌木（成丛）
        else:
            plant("bush", x, y, ru(0.7, 1.3))
            keep(x, y, 0.55)
        nb_ += 1
    for i in range(500):   # 园外
        a = ru(0, 6.28)
        x, y = 39 * math.cos(a) * ru(0.86, 1.0), 32.5 * math.sin(a) * ru(0.86, 1.0)
        if (X0 - 1 < x < X1 + 1 and Y0 - 1 < y < Y1 + 1) or blocked(x, y, 1.0) or fbm(x * 0.2, y * 0.2 + 8, 3) < 0.48:
            continue
        plant("bush", x, y, ru(0.8, 1.7))
        nb_ += 1
    # 盆景与陈设
    b = B("Furniture")
    for (x, y) in ((24.4, -15.0), (32.6, -15.0), (24.4, -19.6), (32.6, -19.6), (26.6, -4.2), (30.2, -4.2), (24.4, 9.6), (30.6, 9.8), (9.0, 14.4),
                   (21.6, 18.0), (-9.6, 8.6), (1.6, 8.6), (-26.6, 14.7), (-19.4, 14.7), (2.4, -18.9), (11.6, -23.8)):
        potted(b, x, y, s=ru(0.9, 1.3))
    # 住宅天井：荷花缸、井
    for (x, y) in ((25.2, -18.6), (31.6, -18.6), (26.2, 9.6), (-6.5, 8.6), (-1.5, 8.6)):
        cone(b, x, y, GZ + 0.04, 0.34, 0.46, 0.62, GREYBRICK, n=14, uv=False)
        disc(b, x, y, GZ + 0.60, 0.40, WATER_VAT, n=14)
        for k in range(3):
            a = ru(0, 6.28)
            disc(b, x + 0.16 * math.cos(a), y + 0.16 * math.sin(a), GZ + 0.615, 0.15, LOTUS_LEAF, n=9)
        keep(x, y, 0.8)
    prism(b, 31.4, 20.6, GZ, 0.62, 0.55, GRANITE, n=8); prism(b, 31.4, 20.6, GZ + 0.5, 0.42, 0.06, GLASS_DARK, n=8)   # 井
    keep(31.4, 20.6, 1.0)
    # 石桌石凳
    for (x, y) in ((7.0, -21.4), (-29.4, 0.6), (30.4, 0.8)):
        prism(b, x, y, GZ, 0.5, 0.62, GRANITE, n=12); prism(b, x, y, GZ + 0.62, 0.62, 0.1, GRANITE, n=16)
        for k in range(4):
            a = math.pi / 4 + math.pi / 2 * k
            prism(b, x + 1.05 * math.cos(a), y + 1.05 * math.sin(a), GZ, 0.2, 0.42, GRANITE, n=10)
        keep(x, y, 1.5)
    b.build()
    # 沿阶草：路边、墙根、石旁
    b = B("Tufts")
    nt_ = 0
    for i in range(8000):
        x, y = ru(X0 + 0.5, X1 - 0.5), ru(Y0 + 0.5, Y1 - 0.5)
        if pond_sd(x, y) < 0.4 or blocked(x, y, 0.92) or not blocked(x, y, 1.45):
            continue
        sz_ = ru(0.8, 1.5)
        if not WEB or nt_ % 3 == 0:
            tuft(b, x, y, sz_)
        nt_ += 1
    b.build()
    print(f"[sz] plants={N_PLANTS} (bushes {nb_}), tufts={nt_}, tile rows={N_ROWS}")

# ----------------------------------------------------------------------------- 相机 / 灯光 / 背景
CAM = {"target": (0.0, -7.5, -2.0), "az": 34.0, "dist": 147.0, "pitch": 40.0, "lens": 45.0}
SUN = {"euler": (52.0, 0.0, -53.0), "color": (1.0, 0.93, 0.82), "energy": 3.8}
def setup_camera_lights():
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = CAM["lens"]
    cam_data.sensor_width = 36
    cam = bpy.data.objects.new("Camera", cam_data)
    COL.objects.link(cam)
    target = CAM["target"]
    az, dist, pitch = math.radians(CAM["az"]), CAM["dist"], math.radians(CAM["pitch"])
    hx, hy = math.sin(az), -math.cos(az)
    cam.location = (target[0] + hx * dist * math.cos(pitch), target[1] + hy * dist * math.cos(pitch), target[2] + dist * math.sin(pitch))
    direction = mathutils.Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    # 下午的侧光：太阳在西偏南、仰角 38°（相机在东南，光从左侧来，影子横过院落），光盘略放大让影子边缘发虚
    sun_data = bpy.data.lights.new("Sun", 'SUN')
    sun_data.energy = float(arg("--sun", SUN["energy"]))
    sun_data.color = SUN["color"]
    sun_data.angle = math.radians(3.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    COL.objects.link(sun)
    sun.rotation_euler = mathutils.Euler(tuple(math.radians(v) for v in SUN["euler"]), 'XYZ')

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    bg = wnt.nodes["Background"]
    hdr = os.path.normpath(os.path.join(HERE, "..", "assets", "polyhaven", "hdris", "kloppenheim_06_puresky_2k.hdr"))
    sky = float(arg("--sky", 0.30))
    if os.path.exists(hdr):
        img = bpy.data.images.load(hdr, check_existing=True)
        u = hdri_sun_u(img)
        th_, ph_ = math.radians(SUN["euler"][0]), math.radians(SUN["euler"][2])
        saz = math.degrees(math.atan2(-math.cos(ph_) * math.sin(th_), math.sin(ph_) * math.sin(th_)))
        rot = (360.0 * u - saz) if u is not None else 0.0        # HDRI 里的太阳转到主光方位
        env = wnt.nodes.new("ShaderNodeTexEnvironment")
        env.image = img
        wtc = wnt.nodes.new("ShaderNodeTexCoord")
        wmp = wnt.nodes.new("ShaderNodeMapping")
        wmp.inputs["Rotation"].default_value = (0, 0, math.radians(rot))
        wnt.links.new(wtc.outputs["Generated"], wmp.inputs["Vector"])
        wnt.links.new(wmp.outputs["Vector"], env.inputs["Vector"])
        wnt.links.new(env.outputs["Color"], bg.inputs["Color"])
        wlp = wnt.nodes.new("ShaderNodeLightPath")
        wst = wnt.nodes.new("ShaderNodeMapRange")
        wst.inputs["To Min"].default_value = sky
        wst.inputs["To Max"].default_value = float(arg("--skygloss", 0.42))    # 倒影里的天空略亮（只对镜面光线）
        wnt.links.new(wlp.outputs["Is Glossy Ray"], wst.inputs["Value"])
        wnt.links.new(wst.outputs["Result"], bg.inputs["Strength"])
        print(f"[sz] hdri sun u={u} rot={rot:.1f}")
    else:
        bg.inputs["Color"].default_value = (0.80, 0.87, 0.95, 1)
        bg.inputs["Strength"].default_value = sky

    # 纯净浅色背景：只对相机可见的自发光背板
    bd = principled("Backdrop", (1, 1, 1), rough=1.0, bevel=0)
    nt = bd.node_tree
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    grad = nt.nodes.new("ShaderNodeTexGradient")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0, 0, math.radians(90))
    mp.inputs["Scale"].default_value = (1, 1.0 / 300.0, 1)      # 先缩放后旋转：渐变沿背板的竖向展开
    mp.inputs["Location"].default_value = (0.5, 0, 0)
    rp = ramp(nt, [(0.0, (0.86, 0.88, 0.86)), (1.0, (0.95, 0.955, 0.945))])
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], rp.inputs["Fac"])
    nt.links.new(rp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], nt.nodes["Material Output"].inputs["Surface"])
    me = bpy.data.meshes.new("Backdrop")
    S = 900.0
    me.from_pydata([(-S, -S, 0), (S, -S, 0), (S, S, 0), (-S, S, 0)], [], [(0, 1, 2, 3)])
    me.materials.append(bd)
    plane = bpy.data.objects.new("Backdrop", me)
    COL.objects.link(plane)
    view_dir = (mathutils.Vector(target) - cam.location).normalized()
    plane.location = cam.location + view_dir * 400.0
    plane.rotation_euler = view_dir.to_track_quat('Z', 'Y').to_euler()
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow"):
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
        print("[sz] hdri sun search failed:", e)
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



def setup_render():
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = "--nodenoise" not in argv
    try:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    except Exception:
        pass
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 3
    scene.cycles.transmission_bounces = 4
    scene.cycles.volume_bounces = 0
    scene.cycles.transparent_max_bounces = 32
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
    vs.view_transform = 'Standard'   # AgX/Filmic 会把浅色背景板压灰、颜色变闷
    vs.look = 'None'
    vs.exposure = float(arg("--exposure", 0.22))
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
print(f"[sz] scene built in {time.time() - t0:.1f}s, objects={len(COL.objects)}")
if WEB:
    # 网页版：导出 glb + scene.json（见 tools/diorama_export.py）；树木为实例数据（卡片树），山石、竹、芭蕉为库模型 + 实例记录
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "tools")))
    import diorama_export as de
    def _vcol(mn, ob, co, nrm):
        if mn not in ("TaiDi", "ChiDi", "EarthCut", "TaiHuShi", "HuangShi"):
            return None
        if co is None:
            return (1, 1, 1)
        if mn == "EarthCut":
            return de.strata(co.z * 2.4)
        if mn == "ChiDi":
            return de.ramp([(0.0, (0.25, 0.42, 0.28)), (0.7, (0.55, 0.80, 0.50)), (1.0, (1.0, 1.0, 0.8))], (co.z + 1.25) / 1.25)
        return (1.0, 1.0, 1.0)
    libs = tuple(INST.keys())
    de.export_scene(arg("--export-glb", os.path.join(HERE, "web")), {"Backdrop"}, _vcol, uv_scale=1.0,
                    ao_objects=("Island",) + tuple(n for n in libs if "Rock" in n), extra={
        "title": "苏州园林", "unit_m": 1,
        "camera": {"target": list(CAM["target"]), "az": CAM["az"], "dist": CAM["dist"] * 1.22, "pitch": CAM["pitch"], "lens": CAM["lens"], "min_dist": 30, "max_dist": 300},
        "sun": {"euler_deg": list(SUN["euler"]), "color": list(SUN["color"]), "strength": SUN["energy"]},
        "backdrop": [[0.86, 0.88, 0.86], [0.95, 0.955, 0.945]],
        "water": ["PondWater"], "bounds": list(ISL), "shadow_half": 68, "shadow_bias": 0.05, "fog": [0.90, 0.93, 0.93],
        "hdri": "kloppenheim_06_puresky_1k.hdr",
        "lake": {"pscale": 4.0, "ripple": 0.10, "glitter": 0.0, "clear": 0.22, "reflRange": [0.26, 0.80], "distortion": 0.007,
                 "colDeep": [0.048, 0.110, 0.062], "colNear": [0.105, 0.185, 0.090], "colShore": [0.19, 0.23, 0.13]},
        "mat": {"EarthCut": {"repeat": 0.30}, "DaiWa": {"repeat": 0.55}},
        "plants": PLANTS, "plant_kinds": {k: len(v) for k, v in LIB_TREES.items()},
        "plant_src": {"peach": "willow", "maple": "tree", "ginkgo": "tree"},
        "plant_tint": {"peach": "rgba(245,150,175,0.72)", "maple": "rgba(176,62,28,0.62)", "ginkgo": "rgba(214,166,48,0.66)"}, "plant_top": False,
        "instances": INST})
    print(f"[sz] web export done in {time.time() - t0:.1f}s, plants={len(PLANTS)}, instance libs={len(INST)}, instances={sum(len(v) for v in INST.values())}")
else:
    setup_render()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if SAVE_BLEND:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.splitext(OUT)[0] + ".blend")
    t1 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[sz] rendered {OUT} in {time.time() - t1:.1f}s ({PCT}% / {SAMPLES} spp)")
