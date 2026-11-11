# -*- coding: utf-8 -*-
"""
沙盘场景 → 网页（glb + scene.json）导出模块。由 build_forbidden_city.py / build_west_lake.py 在
`--export-glb <dir>` 模式下调用（Blender headless）。

做的事：
1. 删除网页里不需要的物体（背板、体积雾、空物体、灯光、相机）；
2. 没有 UV 的网格按法线主轴做盒式投影 UV（网页里贴图用）；
3. 按材质名把 Cycles 节点材质里"按高度/按物体随机"的颜色烘成顶点色（网页着色器乘上去）；
4. 把所有材质换成干净的 Principled（基色/粗糙度/金属度来自原材质的默认值），避免 glTF 导出器
   对复杂节点树束手无策；
5. 以 Draco 压缩导出 GLB。
"""
import bpy, math, os, json

def box_uv(me, scale=1.0):
    """为没有 UV 的网格生成盒式投影 UV。"""
    if me.uv_layers:
        return
    uv = me.uv_layers.new(name="UVMap")
    data = uv.data
    verts = me.vertices
    loops = me.loops
    for poly in me.polygons:
        n = poly.normal
        ax = 0 if abs(n.x) >= abs(n.y) and abs(n.x) >= abs(n.z) else (1 if abs(n.y) >= abs(n.z) else 2)
        for li in poly.loop_indices:
            co = verts[loops[li].vertex_index].co
            if ax == 2:
                u, v = co.x, co.y
            elif ax == 0:
                u, v = co.y, co.z
            else:
                u, v = co.x, co.z
            data[li].uv = (u * scale, v * scale)

def bake_vertex_colors(ob, vcol_fn):
    """vcol_fn(mat_name, ob, co_world, normal) -> (r,g,b) 或 None（白）。按角域写入 BYTE_COLOR。"""
    me = ob.data
    if not me.polygons:
        return
    mats = [m.name if m else "" for m in me.materials]
    needed = any(vcol_fn(mn, ob, None, None) is not None for mn in set(mats)) if mats else False
    if not needed:
        return
    attr = me.color_attributes.get("Col") or me.color_attributes.new(name="Col", type='BYTE_COLOR', domain='CORNER')
    me.color_attributes.active_color = attr
    mw = ob.matrix_world
    data = attr.data
    for poly in me.polygons:
        mn = mats[poly.material_index] if poly.material_index < len(mats) else ""
        nrm = (mw.to_3x3() @ poly.normal).normalized()
        for li in poly.loop_indices:
            co = mw @ me.vertices[me.loops[li].vertex_index].co
            c = vcol_fn(mn, ob, co, nrm)
            if c is None:
                c = (1.0, 1.0, 1.0)
            data[li].color = (c[0], c[1], c[2], 1.0)

def clean_materials():
    """把每个材质替换为同名的干净 Principled 材质，返回 {name: (color, rough, metal)}。"""
    info = {}
    repl = {}
    for m in list(bpy.data.materials):
        if m.name.endswith("__cycles") or not m.use_nodes:
            continue
        p = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if p is None:
            continue
        col = tuple(p.inputs["Base Color"].default_value)[:3]
        rough = float(p.inputs["Roughness"].default_value)
        metal = float(p.inputs["Metallic"].default_value)
        name = m.name
        m.name = name + "__cycles"
        m2 = bpy.data.materials.new(name)
        m2.use_nodes = True
        p2 = next(n for n in m2.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        p2.inputs["Base Color"].default_value = (*col, 1.0)
        p2.inputs["Roughness"].default_value = rough
        p2.inputs["Metallic"].default_value = metal
        repl[m] = m2
        info[name] = {"color": [round(c, 4) for c in col], "roughness": round(rough, 3), "metallic": round(metal, 3)}
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        for slot in ob.material_slots:
            if slot.material in repl:
                slot.material = repl[slot.material]
    return info

import random as _random
_PT = list(range(256)); _random.Random(3).shuffle(_PT); _PT = _PT + _PT
def _h(i, j):
    return _PT[(_PT[i & 255] + j) & 255] / 255.0
def vnoise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi
    u, v = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b, c, d = _h(xi, yi), _h(xi + 1, yi), _h(xi, yi + 1), _h(xi + 1, yi + 1)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v
def fbm(x, y, octaves=3):
    s, amp, f, tot = 0.0, 1.0, 1.0, 0.0
    for _ in range(octaves):
        s += amp * vnoise(x * f, y * f); tot += amp
        amp *= 0.5; f *= 2.0
    return s / tot

def bake_ao_to_vcol(ob, samples=24, strength=0.7):
    """用 Cycles 把环境光遮蔽烘到顶点色属性 AO，再乘进 Col（网页里的接触阴影/沟壑暗部）。"""
    me = ob.data
    col = me.color_attributes.get("Col")
    if col is None:
        return False
    ao = me.color_attributes.get("AO") or me.color_attributes.new(name="AO", type='BYTE_COLOR', domain='CORNER')
    me.color_attributes.active_color = ao
    scene = bpy.context.scene
    old_engine = scene.render.engine
    try:
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = samples
        scene.cycles.bake_type = 'AO'
        scene.render.bake.target = 'VERTEX_COLORS'
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.bake(type='AO', target='VERTEX_COLORS')
        cd, ad = col.data, ao.data
        for i in range(len(cd)):
            a = ad[i].color[0]
            k = 1.0 - strength + strength * a
            c = cd[i].color
            cd[i].color = (c[0] * k, c[1] * k, c[2] * k, 1.0)
        me.color_attributes.active_color = col
        me.color_attributes.remove(ao)
        print(f"[export] AO baked into vertex colors of {ob.name}")
        return True
    except Exception as e:
        print("[export] AO bake failed:", e)
        me.color_attributes.active_color = col
        return False
    finally:
        scene.render.engine = old_engine

def patchiness(ob, scale=0.06, lo=0.78, hi=1.12):
    """大尺度色斑：地面不再是均匀铺开的草皮贴图。"""
    me = ob.data
    col = me.color_attributes.get("Col")
    if col is None:
        return
    mw = ob.matrix_world
    data = col.data
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = mw @ me.vertices[me.loops[li].vertex_index].co
            k = lo + (hi - lo) * fbm(co.x * scale + 11, co.y * scale + 7, 3)
            k2 = 0.9 + 0.2 * fbm(co.x * 0.5, co.y * 0.5, 2)
            c = data[li].color
            data[li].color = (c[0] * k * k2, c[1] * k * k2, c[2] * k * k2, 1.0)

def export_scene(out_dir, remove_names, vcol_fn, uv_scale=1.0, extra=None, ao_objects=("Island",)):
    os.makedirs(out_dir, exist_ok=True)
    # 1. 删除不需要的物体
    for ob in list(bpy.data.objects):
        if ob.type in ('LIGHT', 'CAMERA', 'EMPTY') or ob.name in remove_names or ob.name.split('.')[0] in remove_names:
            bpy.data.objects.remove(ob)
    # 2/3. UV 与顶点色
    n_uv = 0
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        if not ob.data.uv_layers:
            box_uv(ob.data, uv_scale); n_uv += 1
        bake_vertex_colors(ob, vcol_fn)
        if ob.name.split('.')[0] in ao_objects and ob.data.color_attributes.get("Col"):
            patchiness(ob)
            bake_ao_to_vcol(ob)
    # 4. 材质
    mats = clean_materials()
    # 5. 导出
    path = os.path.join(out_dir, "scene.glb")
    kw = dict(filepath=path, export_format='GLB', export_apply=True,
              export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=10,
              export_draco_normal_quantization=8, export_draco_color_quantization=8,
              export_materials='EXPORT', export_lights=False, export_cameras=False, export_animations=False,
              export_skins=False, export_morph=False, export_yup=True, export_texcoords=True, export_normals=True)
    try:
        bpy.ops.export_scene.gltf(**kw, export_vertex_color='ACTIVE')
    except TypeError:
        try:
            bpy.ops.export_scene.gltf(**kw, export_colors=True)
        except TypeError:
            bpy.ops.export_scene.gltf(**kw)
    meta = {"materials": mats, "objects": len([o for o in bpy.data.objects if o.type == 'MESH']), "boxuv": n_uv}
    if extra:
        meta.update(extra)
    with open(os.path.join(out_dir, "scene.json"), "w", encoding="utf-8") as f:
        json.dump(_round(meta), f, ensure_ascii=False, separators=(",", ":"))   # 紧凑输出，小数留 3 位
    print(f"[export] {path}: {os.path.getsize(path) / 1e6:.1f} MB, objects={meta['objects']}, boxuv={n_uv}")
    return meta

def _round(o):
    if isinstance(o, float):
        return round(o, 3)
    if isinstance(o, dict):
        return {k: _round(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v) for v in o]
    return o

def smooth01(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)

def ramp(stops, t):
    """stops: [(pos, (r,g,b))]，线性插值。"""
    if t <= stops[0][0]:
        return stops[0][1]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            k = (t - p0) / max(1e-6, p1 - p0)
            return tuple(c0[i] + (c1[i] - c0[i]) * k for i in range(3))
    return stops[-1][1]

def strata(z):
    """地层切面：按高度的条带明暗（与 Cycles 里的 Wave 条带近似）。"""
    band = 0.5 + 0.5 * math.sin(z * 0.4 * 2 * math.pi + 1.7 * math.sin(z * 0.9))
    c = ramp([(0.15, (1.7, 1.45, 1.1)), (0.5, (2.6, 2.3, 1.8)), (0.85, (3.2, 2.9, 2.4))], band)
    return tuple(v / 3.2 for v in c)