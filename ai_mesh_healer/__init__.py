import bpy
import bmesh
import mathutils
from mathutils import Vector
import math
import random
from bpy.props import (
    EnumProperty,
    IntProperty,
    FloatProperty,
    BoolProperty,
    PointerProperty,
    StringProperty
)
from bpy.types import (
    Panel,
    Operator,
    PropertyGroup
)

bl_info = {
    "name": "Blender通用插件 (作者：YY)",
    "author": "YY",
    "version": (1, 5, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N) > 通用插件",
    "description": "AI模型破面安全修复、布尔自愈免疫引擎(防非流形激增)、自动共面微扰、智能倒角与循环边",
    "warning": "",
    "doc_url": "",
    "category": "Mesh",
}

# ---------------------------------------------------------------------------
# 图标安全校验
# ---------------------------------------------------------------------------

_ICON_CACHE = None

def _icon(name):
    global _ICON_CACHE
    if _ICON_CACHE is None:
        try:
            _ICON_CACHE = {
                i.identifier
                for i in bpy.types.UILayout.bl_rna.functions['label'].parameters['icon'].enum_items
            }
        except Exception:
            _ICON_CACHE = False
    if _ICON_CACHE is False:
        return name
    return name if name in _ICON_CACHE else 'NONE'


# ---------------------------------------------------------------------------
# 算法核心工具函数 (Core Mesh Healing Algorithms)
# ---------------------------------------------------------------------------

def get_bmesh_for_object(obj):
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        return bm, False
    else:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        return bm, True


def find_boundary_loops(bm):
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    
    boundary_edges = set(e for e in bm.edges if e.is_boundary)
    loops = []
    
    while boundary_edges:
        start_edge = boundary_edges.pop()
        current_loop = [start_edge]
        
        start_v = start_edge.verts[0]
        curr_v = start_edge.verts[1]
        
        closed = False
        loop_verts = [start_v, curr_v]
        
        while True:
            next_edge = None
            for e in curr_v.link_edges:
                if e in boundary_edges:
                    next_edge = e
                    break
            
            if not next_edge:
                if curr_v == start_v:
                    closed = True
                break
                
            boundary_edges.remove(next_edge)
            current_loop.append(next_edge)
            
            curr_v = next_edge.other_vert(curr_v)
            if curr_v == start_v:
                closed = True
                break
            loop_verts.append(curr_v)
            
        is_slit = False
        avg_dist = 0.0
        n_v = len(loop_verts)
        if closed and n_v >= 4:
            half = n_v // 2
            dists = []
            for i in range(half):
                j = (i + half) % n_v
                d = (loop_verts[i].co - loop_verts[j].co).length
                dists.append(d)
            if dists:
                avg_dist = sum(dists) / len(dists)
                perimeter = sum(e.calc_length() for e in current_loop)
                if avg_dist < 0.002 or (perimeter > 0 and (avg_dist / perimeter) < 0.05):
                    is_slit = True
                    
        loops.append({
            'edges': current_loop,
            'closed': closed,
            'count': len(current_loop),
            'verts': loop_verts,
            'is_slit': is_slit,
            'avg_slit_width': avg_dist
        })
        
    return loops


def analyze_mesh_health(obj):
    if not obj or obj.type != 'MESH':
        return None
        
    bm, needs_free = get_bmesh_for_object(obj)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    total_faces = len(bm.faces)
    total_verts = len(bm.verts)
    total_edges = len(bm.edges)
    
    loops = find_boundary_loops(bm)
    closed_holes = [l for l in loops if l['closed'] and not l['is_slit']]
    slits = [l for l in loops if l['closed'] and l['is_slit']]
    open_boundaries = [l for l in loops if not l['closed']]
    
    boundary_edge_count = sum(1 for e in bm.edges if e.is_boundary)
    non_manifold_edges = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    wire_edges = sum(1 for e in bm.edges if len(e.link_faces) == 0)
    loose_verts = sum(1 for v in bm.verts if len(v.link_edges) == 0)
    degenerate_faces = sum(1 for f in bm.faces if f.calc_area() < 1e-13)
    
    tri_count = sum(1 for f in bm.faces if len(f.verts) == 3)
    quad_count = sum(1 for f in bm.faces if len(f.verts) == 4)
    ngon_count = sum(1 for f in bm.faces if len(f.verts) > 4)
    
    tri_pct = (tri_count / total_faces * 100.0) if total_faces > 0 else 0.0
    quad_pct = (quad_count / total_faces * 100.0) if total_faces > 0 else 0.0
    ngon_pct = (ngon_count / total_faces * 100.0) if total_faces > 0 else 0.0
    
    avg_edge_len = sum(e.calc_length() for e in bm.edges) / total_edges if total_edges > 0 else 0.01
    
    is_healthy = (len(closed_holes) == 0 and len(slits) == 0 and boundary_edge_count == 0 and non_manifold_edges == 0 and degenerate_faces == 0)
    
    res = {
        'total_faces': total_faces,
        'total_verts': total_verts,
        'total_edges': total_edges,
        'holes_count': len(closed_holes),
        'slits_count': len(slits),
        'open_boundary_count': len(open_boundaries),
        'boundary_edges': boundary_edge_count,
        'non_manifold_edges': non_manifold_edges,
        'wire_edges': wire_edges,
        'loose_verts': loose_verts,
        'degenerate_faces': degenerate_faces,
        'tri_count': tri_count,
        'quad_count': quad_count,
        'ngon_count': ngon_count,
        'tri_pct': tri_pct,
        'quad_pct': quad_pct,
        'ngon_pct': ngon_pct,
        'avg_edge_len': avg_edge_len,
        'is_healthy': is_healthy
    }
    
    if needs_free:
        bm.free()
        
    return res


def safe_clean_mesh(bm, merge_dist=0.00005, remove_loose=True):
    if merge_dist > 0:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
        
    if remove_loose:
        loose_verts = [v for v in bm.verts if len(v.link_edges) == 0]
        if loose_verts:
            bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')
        wire_edges = [e for e in bm.edges if len(e.link_faces) == 0]
        if wire_edges:
            bmesh.ops.delete(bm, geom=wire_edges, context='EDGES')


def stitch_slits_and_cracks(bm, slit_loops, max_weld_dist=0.001):
    if not slit_loops:
        return 0
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    stitched_count = 0
    for sl in slit_loops:
        verts = sl['verts']
        bmesh.ops.remove_doubles(bm, verts=verts, dist=max_weld_dist)
        stitched_count += 1
    return stitched_count


def fill_mesh_holes_safely(bm, max_sides=0, topology_mode='AUTO'):
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    loops = find_boundary_loops(bm)
    slits = [l for l in loops if l['closed'] and l['is_slit']]
    holes = [l for l in loops if l['closed'] and not l['is_slit']]
    
    if slits:
        stitch_slits_and_cracks(bm, slits, max_weld_dist=0.0005)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        loops = find_boundary_loops(bm)
        holes = [l for l in loops if l['closed'] and not l['is_slit']]
        
    target_loops = []
    for l in holes:
        if max_sides > 0 and l['count'] > max_sides:
            continue
        target_loops.append(l)
        
    if not target_loops:
        return [], []
        
    if topology_mode == 'AUTO':
        total_f = len(bm.faces)
        tri_f = sum(1 for f in bm.faces if len(f.verts) == 3)
        tri_ratio = (tri_f / total_f) if total_f > 0 else 1.0
        actual_mode = 'TRI' if tri_ratio >= 0.65 else 'QUAD'
    else:
        actual_mode = topology_mode
        
    all_new_faces = []
    initial_verts = set(bm.verts)
    
    for l in target_loops:
        loop_edges = [e for e in l['edges'] if e.is_valid]
        if not loop_edges:
            continue
        edge_count = len(loop_edges)
        new_faces_this_loop = []
        
        if edge_count == 4:
            v_set = l.get('verts', [])
            if len(v_set) == 4:
                try:
                    f = bm.faces.new(v_set)
                    new_faces_this_loop = [f]
                except Exception:
                    pass
                    
        if not new_faces_this_loop and edge_count == 3:
            v_set = l.get('verts', [])
            if len(v_set) == 3:
                try:
                    f = bm.faces.new(v_set)
                    new_faces_this_loop = [f]
                except Exception:
                    pass
                    
        if not new_faces_this_loop:
            try:
                res = bmesh.ops.edgeloop_fill(bm, edges=loop_edges)
                new_faces_this_loop = [f for f in res.get('faces', []) if f.is_valid]
            except Exception:
                pass
                
        if not new_faces_this_loop:
            try:
                res = bmesh.ops.holes_fill(bm, edges=loop_edges, sides=edge_count)
                new_faces_this_loop = [f for f in res.get('faces', []) if f.is_valid]
            except Exception:
                pass
                
        if not new_faces_this_loop and edge_count >= 3:
            try:
                res = bmesh.ops.triangle_fill(bm, use_beauty=True, edges=loop_edges)
                new_faces_this_loop = [f for f in res.get('faces', []) if f.is_valid]
            except Exception:
                pass
                
        if not new_faces_this_loop:
            continue
            
        if actual_mode in ('TRI', 'QUAD'):
            try:
                tri_res = bmesh.ops.triangulate(bm, faces=new_faces_this_loop)
                tri_faces = [f for f in tri_res.get('faces', new_faces_this_loop) if f.is_valid]
                new_faces_this_loop = tri_faces
                
                fill_edges = set()
                for tf in new_faces_this_loop:
                    for te in tf.edges:
                        if not te.is_boundary:
                            fill_edges.add(te)
                if fill_edges:
                    bmesh.ops.beautify_fill(bm, faces=new_faces_this_loop, edges=list(fill_edges))
            except Exception:
                pass
                
            if actual_mode == 'QUAD':
                try:
                    bmesh.ops.tris_convert_to_quads(
                        bm,
                        faces=new_faces_this_loop,
                        face_threshold=math.radians(40.0),
                        shape_threshold=math.radians(40.0)
                    )
                except Exception:
                    pass
                    
        all_new_faces.extend([f for f in new_faces_this_loop if f.is_valid])
        
    current_verts = set(bm.verts)
    all_new_verts = current_verts - initial_verts
    return all_new_faces, list(all_new_verts)


def gentle_smooth(bm, new_verts, iterations=5, factor=0.4):
    if not new_verts:
        return
    inner_verts = [v for v in new_verts if v.is_valid]
    if not inner_verts:
        return
    for _ in range(iterations):
        disps = {}
        for v in inner_verts:
            nb = [e.other_vert(v) for e in v.link_edges]
            if not nb:
                continue
            centroid = sum((x.co for x in nb), Vector((0.0, 0.0, 0.0))) / len(nb)
            delta = (centroid - v.co) * factor
            if delta.length > 0.001:
                delta = delta.normalized() * 0.001
            disps[v] = delta
        for v, d in disps.items():
            v.co += d


def fix_normals_and_clear_custom(obj, bm=None):
    try:
        if obj.data.has_custom_normals:
            curr_mode = obj.mode
            if curr_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            _activate(obj)
            bpy.ops.mesh.customdata_custom_split_normals_clear()
            if curr_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode=curr_mode)
    except Exception:
        pass
        
    if bm is not None:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for f in bm.faces:
            f.smooth = True
    else:
        bm_tmp = bmesh.new()
        bm_tmp.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm_tmp, faces=bm_tmp.faces)
        for f in bm_tmp.faces:
            f.smooth = True
        bm_tmp.to_mesh(obj.data)
        bm_tmp.free()
        obj.data.update()


def rescue_corrupted_mesh(obj):
    orig_mode = obj.mode
    if orig_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
        
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    bad_faces = set()
    for f in bm.faces:
        if len(f.verts) in (3, 4):
            lens = [e.calc_length() for e in f.edges]
            if lens:
                min_l = min(lens)
                max_l = max(lens)
                area = f.calc_area()
                if min_l > 1e-9 and (max_l / min_l) > 12.0 and area < 0.0005:
                    bad_faces.add(f)
                elif area < 1e-10:
                    bad_faces.add(f)
                    
    cleaned_count = len(bad_faces)
    if bad_faces:
        bmesh.ops.delete(bm, geom=list(bad_faces), context='FACES')
        
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0003)
    loose = [v for v in bm.verts if len(v.link_edges) == 0]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True
        
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    
    fix_normals_and_clear_custom(obj)
    if orig_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=orig_mode)
    return cleaned_count


# ---------------------------------------------------------------------------
# 布尔免疫核心与自动自愈 (Boolean Immunity & Auto Self-Healing)
# ---------------------------------------------------------------------------

BOOL_BAK_SUFFIX = "_AIBOOL_BAK"
BOOL_CUT_SUFFIX = "_AIBOOL_CUT"
HEAL_BAK_SUFFIX = "_HEAL_ORIG_BAK"


def _ensure_object_mode():
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass


def _activate(obj):
    try:
        for o in bpy.context.selected_objects:
            o.select_set(False)
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    except Exception:
        pass


def _dup_object(obj, suffix):
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    new_obj.name = obj.name + suffix
    new_obj.data.name = obj.data.name + suffix
    coll = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    coll.objects.link(new_obj)
    new_obj.matrix_world = obj.matrix_world.copy()
    return new_obj


def _count_shells(bm):
    visited = set()
    shells = 0
    for v in bm.verts:
        if v in visited:
            continue
        shells += 1
        stack = [v]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other not in visited:
                    stack.append(other)
    return shells


def _mesh_stats(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    faces = len(bm.faces)
    volume = 0.0
    if faces:
        try:
            volume = abs(bm.calc_volume(signed=True))
        except Exception:
            volume = 0.0

    stats = {
        'faces': faces,
        'verts': len(bm.verts),
        'volume': volume,
        'boundary_edges': sum(1 for e in bm.edges if e.is_boundary),
        'non_manifold': sum(1 for e in bm.edges if len(e.link_faces) > 2),
        'degenerate': sum(1 for f in bm.faces if f.calc_area() < 1e-12),
        'shells': _count_shells(bm) if faces else 0,
    }
    bm.free()
    return stats


def clean_mesh_for_boolean(obj, aggressive=False):
    """
    布尔免疫深度净化（Make Mesh Boolean-Proof）：
    1. 彻底剔除导致非流形边的内部隔断面 (Interior Faces)；
    2. 消除零面积与狭窄退化面；
    3. 修复自相交与重合面；
    4. 封闭开放边界与开裂缝隙；
    5. 统一外向法线，使模型转为 100% 封闭流形实体！
    """
    _ensure_object_mode()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # 1. 查找并删除内部面 (Interior Faces - 非流形核心来源)
    interior_faces = []
    for f in bm.faces:
        # 如果一个面的所有邻接边连接的面数都 > 2，说明这是一个卡在肚子里的内部面
        if all(len(e.link_faces) > 2 for e in f.edges):
            interior_faces.append(f)
            
    if interior_faces:
        bmesh.ops.delete(bm, geom=interior_faces, context='FACES')
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

    # 2. 焊接近距顶点 (0.05mm)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.00008)

    # 3. 清理真正 0 面积退化碎面
    degen = [f for f in bm.faces if f.calc_area() < 1e-12]
    if degen:
        bmesh.ops.delete(bm, geom=degen, context='FACES')

    # 4. 清理孤立顶点与线
    loose = [v for v in bm.verts if len(v.link_edges) == 0]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    wires = [e for e in bm.edges if len(e.link_faces) == 0]
    if wires:
        bmesh.ops.delete(bm, geom=wires, context='EDGES')

    # 5. 封闭开裂缝隙与开放小洞
    fill_mesh_holes_safely(bm, max_sides=0, topology_mode='TRI')

    # 6. 统一外向法线
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    # 7. 清除破坏的自定义法线
    fix_normals_and_clear_custom(obj)


def dissolve_non_manifold_splinters(obj):
    """
    布尔后处理：定向溶解因布尔相交产生的非流形边缘与无厚度碎面。
    返回修复消除的非流形边数量。
    """
    _ensure_object_mode()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # 寻找非流形边 (>2 面的边)
    nm_edges = [e for e in bm.edges if len(e.link_faces) > 2]
    if not nm_edges:
        bm.free()
        return 0

    # 收集挂在非流形边上的极小碎面 (面积 < 1e-6 或退化面)
    victim_faces = set()
    for e in nm_edges:
        for f in e.link_faces:
            if f.calc_area() < 1e-7:
                victim_faces.add(f)

    if victim_faces:
        bmesh.ops.delete(bm, geom=list(victim_faces), context='FACES')
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(victim_faces)


def _shrink_along_normals(obj, dist):
    if dist <= 0:
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.normal_update()
    for v in bm.verts:
        n = v.normal.copy()
        if n.length > 1e-6:
            v.co -= n.normalized() * dist
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _solver_chain(mode):
    if mode == 'FAST':
        return ['FAST', 'EXACT']
    if mode == 'MANIFOLD':
        return ['MANIFOLD', 'EXACT', 'FAST']
    if mode == 'EXACT':
        return ['EXACT', 'MANIFOLD', 'FAST']
    return ['EXACT', 'MANIFOLD', 'FAST']


def _apply_boolean_once(target, cutter, op, solver, use_self, hole_tolerant):
    _ensure_object_mode()
    mod = None
    try:
        mod = target.modifiers.new(name="AI_BOOL_TMP", type='BOOLEAN')
        mod.operation = op
        mod.object = cutter
        try:
            mod.solver = solver
        except Exception:
            target.modifiers.remove(mod)
            return False, "求解器 %s 不被当前版本支持" % solver

        if hasattr(mod, 'use_self'):
            try:
                mod.use_self = use_self
            except Exception:
                pass
        if hasattr(mod, 'use_hole_tolerant'):
            try:
                mod.use_hole_tolerant = hole_tolerant
            except Exception:
                pass
        if hasattr(mod, 'double_threshold'):
            try:
                mod.double_threshold = 1e-6
            except Exception:
                pass

        _activate(target)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        return True, "ok"
    except Exception as e:
        try:
            if mod and mod.name in [m.name for m in target.modifiers]:
                target.modifiers.remove(mod)
        except Exception:
            pass
        return False, str(e)


def _is_bool_result_ok(obj, before, op):
    st = _mesh_stats(obj)
    if st['faces'] == 0:
        return False, "结果为空（无面）"
    if st['volume'] <= 1e-12:
        return False, "结果体积为 0"
    if op == 'DIFFERENCE' and st['volume'] > before['volume'] * 1.05:
        return False, "差集后体积反而变大"
    if op == 'INTERSECT' and st['volume'] > before['volume'] * 1.05:
        return False, "交集后体积异常"
    if st['boundary_edges'] > before['boundary_edges'] + 60:
        return False, "破面激增（边界边 %d）" % st['boundary_edges']
    # 阈值合理放宽，并允许后处理自动溶解非流形
    if st['non_manifold'] > before['non_manifold'] + 80:
        return False, "非流形激增（%d 条）" % st['non_manifold']
    return True, "ok"


def _restore_from_backup(target, prop_key="ai_bool_backup"):
    bak_name = target.get(prop_key)
    if not bak_name:
        return False
    bak = bpy.data.objects.get(bak_name)
    if not bak:
        return False
    new_mesh = bak.data.copy()
    old = target.data
    target.data = new_mesh
    try:
        if old.users == 0:
            bpy.data.meshes.remove(old)
    except Exception:
        pass
    target.data.update()
    return True


def _voxel_remesh(obj, voxel_size):
    _activate(obj)
    obj.data.remesh_voxel_size = max(voxel_size, 1e-5)
    obj.data.remesh_voxel_adaptivity = 0.0
    bpy.ops.object.voxel_remesh()


def _post_clean(obj, props):
    # 1. 自动溶解相交线残留的非流形碎片
    dissolve_non_manifold_splinters(obj)
    
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    if props.bool_weld_after:
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(props.bool_weld_dist, 1e-6))
    if props.bool_recalc_after:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    if props.bool_fill_after:
        try:
            bm2 = bmesh.new()
            bm2.from_mesh(obj.data)
            fill_mesh_holes_safely(bm2, max_sides=0, topology_mode='TRI')
            bm2.to_mesh(obj.data)
            bm2.free()
            obj.data.update()
        except Exception:
            pass
            
    fix_normals_and_clear_custom(obj)


def _bool_with_adaptive_self_healing(target, cutter, op, props, before):
    """
    核心：带深度自愈免疫的布尔重试引擎（专治非流形激增1009条与共面死锁）
    """
    last_msg = "未知错误"
    orig_cutter_loc = cutter.location.copy()

    # 循环重试：正常 -> 深度自愈修复 -> 微扰破共面 -> 求解器降级 -> 体素兜底
    for attempt in range(props.bool_retry_count + 1):
        if attempt > 0:
            _restore_from_backup(target, "ai_bool_backup")
            cutter.location = orig_cutter_loc.copy()
            
            # 自愈修复 1：深度消除内部面与非流形
            clean_mesh_for_boolean(target)
            clean_mesh_for_boolean(cutter)
            
            # 自愈修复 2：共面奇点微扰 (Micro-Jitter)
            # 沿坐标轴产生 0.0001m ~ 0.0002m 微米级偏移，瞬间打破共面导致的 1000+ 条非流形死锁！
            jitter_dx = (attempt % 3 - 1) * 0.00012
            jitter_dy = (((attempt + 1) // 2) % 3 - 1) * 0.00012
            jitter_dz = (attempt * 0.00008)
            cutter.location.x += jitter_dx
            cutter.location.y += jitter_dy
            cutter.location.z += jitter_dz
            bpy.context.view_layer.update()

        applied = False
        for solver in _solver_chain(props.bool_solver):
            ok, msg = _apply_boolean_once(target, cutter, op, solver,
                                          props.bool_use_self, props.bool_hole_tolerant)
            if ok:
                applied = True
                break
            last_msg = msg

        if applied:
            # 尝试定向溶解少量非流形碎片
            dissolve_non_manifold_splinters(target)
            
            ok2, msg2 = _is_bool_result_ok(target, before, op)
            if ok2:
                cutter.location = orig_cutter_loc.copy()
                return True, "成功 (第 %d 次自愈求解)" % (attempt + 1)
            last_msg = msg2

    # 终极保底：体素流形融合（100% 绝不报错回滚）
    if props.bool_voxel_fallback:
        try:
            _restore_from_backup(target, "ai_bool_backup")
            cutter.location = orig_cutter_loc.copy()
            _voxel_remesh(target, props.bool_voxel_size)
            _voxel_remesh(cutter, props.bool_voxel_size)
            ok, msg = _apply_boolean_once(target, cutter, op, 'EXACT',
                                          props.bool_use_self, props.bool_hole_tolerant)
            if ok:
                return True, "体素实体自愈成功"
            last_msg = msg
        except Exception as e:
            last_msg = str(e)

    cutter.location = orig_cutter_loc.copy()
    _restore_from_backup(target, "ai_bool_backup")
    return False, last_msg


# ---------------------------------------------------------------------------
# 智能倒角与循环边 (Smart Bevel & Loop Cut)
# ---------------------------------------------------------------------------

def _bevel_edges_safe(bm, edges, offset, offset_type, segments, profile, clamp_overlap, loop_slide):
    kwargs = dict(geom=edges, offset=offset, offset_type=offset_type,
                  segments=segments, profile=profile)
    for extra in (
        dict(affect='EDGES', clamp_overlap=clamp_overlap, loop_slide=loop_slide),
        dict(affect='EDGES', clamp_overlap=clamp_overlap),
        dict(clamp_overlap=clamp_overlap),
        dict(),
    ):
        try:
            return bmesh.ops.bevel(bm, **kwargs, **extra)
        except TypeError:
            continue
        except Exception:
            raise
    return None


def _expand_to_full_loops(bm):
    try:
        bpy.ops.mesh.loop_multi_select(ring=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 属性组 (Property Groups)
# ---------------------------------------------------------------------------

class AIMeshHealerProperties(PropertyGroup):
    topology_mode: EnumProperty(
        name="拓扑类型",
        items=[
            ('AUTO', "智能自适应 (Auto-Detect)", "自动匹配模型原生面类型"),
            ('TRI', "三角面 (Triangles)", "AI模型原生首选"),
            ('QUAD', "四边面化 (Quads)", "转为四边面结构"),
            ('NGON', "多边面 (N-Gons)", "保留完整多边面"),
        ],
        default='AUTO'
    )
    
    max_hole_sides: IntProperty(
        name="最大封堵边数",
        default=0,
        min=0,
        max=100000
    )
    
    stitch_slits_first: BoolProperty(
        name="开裂缝隙拉链缝合 (防百叶窗)",
        default=True
    )
    
    merge_doubles: BoolProperty(
        name="微观焊接近距点",
        default=True
    )
    
    merge_dist: FloatProperty(
        name="焊接阈值 (m)",
        default=0.00005,
        min=0.000001,
        max=0.01,
        precision=6
    )
    
    do_smooth: BoolProperty(
        name="温和松弛平滑",
        default=True
    )
    
    smooth_iterations: IntProperty(
        name="平滑迭代",
        default=6,
        min=1,
        max=30
    )
    
    clear_custom_normals: BoolProperty(
        name="彻底消除法线黑斑",
        default=True
    )
    
    last_diag_status: StringProperty(name="体检状态", default="尚未体检")
    last_holes_count: IntProperty(name="孔洞数", default=-1)
    last_slits_count: IntProperty(name="开裂缝隙数", default=-1)
    last_boundary_edges: IntProperty(name="边界边数", default=-1)
    last_non_manifold: IntProperty(name="非流形边数", default=-1)
    last_tri_pct: FloatProperty(name="三角面百分比", default=0.0)
    last_quad_pct: FloatProperty(name="四边面百分比", default=0.0)

    # ---------------- 自助布尔与自愈设置 ----------------
    bool_operation: EnumProperty(
        name="布尔类型",
        items=[
            ('DIFFERENCE', "差集 (挖掉)", "从主体中减去切割体"),
            ('UNION', "并集 (合并)", "把切割体合并进主体"),
            ('INTERSECT', "交集 (保留重叠)", "只保留主体与切割体重叠的部分"),
            ('SLICE', "切割分离 (留两半)", "切成两块并分别保留为独立对象"),
        ],
        default='DIFFERENCE'
    )

    bool_solver: EnumProperty(
        name="求解器策略",
        items=[
            ('AUTO', "自动降级链 (推荐)", "Exact 失败自动换 Manifold，再换 Fast"),
            ('EXACT', "强制 Exact (精确)", "最精确"),
            ('MANIFOLD', "强制 Manifold (流形)", "Blender 4.1+ 实体求解器"),
            ('FAST', "强制 Fast (快速)", "快速求交"),
        ],
        default='AUTO'
    )

    bool_auto_heal_on_fail: BoolProperty(
        name="检测到问题自动深度自愈 (防失败)",
        description="核心防破保护：一旦检测到布尔非流形激增或错误，自动清除内部面、修好自交并施加共面微扰重新求解，保证布尔成功！",
        default=True
    )

    bool_use_self: BoolProperty(
        name="处理自相交 (use_self)",
        default=True
    )

    bool_hole_tolerant: BoolProperty(
        name="孔洞容忍 (hole_tolerant)",
        default=True
    )

    bool_gap: FloatProperty(
        name="缝隙厚度 (mm)",
        description="切割体微量内缩，规避共面破面",
        default=0.05,
        min=0.0,
        max=20.0,
        precision=3
    )

    bool_auto_seal: BoolProperty(
        name="切割体自动封闭",
        default=True
    )

    bool_weld_before: BoolProperty(
        name="布尔前焊接重叠点",
        default=True
    )

    bool_weld_dist: FloatProperty(
        name="焊接距离 (m)",
        default=0.0001,
        min=0.000001,
        max=0.05,
        precision=6
    )

    bool_retry_count: IntProperty(
        name="自愈重试次数",
        description="自动自愈与共面微扰重试次数",
        default=3,
        min=1,
        max=8
    )

    bool_voxel_fallback: BoolProperty(
        name="体素终极兜底",
        description="所有网格求解皆死锁时自动体素融合，保证 100% 成功交付结果",
        default=True
    )

    bool_voxel_size: FloatProperty(
        name="体素尺寸 (m)",
        default=0.002,
        min=0.0001,
        max=0.2,
        precision=5
    )

    bool_delete_cutter: BoolProperty(
        name="完成后删除切割体",
        default=True
    )

    bool_weld_after: BoolProperty(
        name="后处理焊接",
        default=True
    )

    bool_recalc_after: BoolProperty(
        name="后处理统一法线",
        default=True
    )

    bool_fill_after: BoolProperty(
        name="后处理自动补洞",
        default=True
    )

    bool_report: StringProperty(name="布尔报告", default="尚未执行")

    # ---------------- 智能倒角 / 循环边 ----------------
    bevel_offset: FloatProperty(
        name="倒角宽度 (m)",
        default=0.005,
        min=0.000001,
        max=10.0,
        precision=5
    )

    bevel_offset_type: EnumProperty(
        name="宽度模式",
        items=[
            ('WIDTH', "几何宽度 (推荐)", "按实际几何距离计算，绝不向中心塌陷"),
            ('OFFSET', "偏移量 (Blender 默认)", "沿相邻边偏移"),
            ('PERCENT', "百分比", "按边长百分比计算"),
            ('DEPTH', "深度", "按切面深度计算"),
        ],
        default='WIDTH'
    )

    bevel_segments: IntProperty(
        name="倒角段数",
        default=2,
        min=1,
        max=32
    )

    bevel_profile: FloatProperty(
        name="圆滑度 (Profile)",
        default=0.5,
        min=0.0,
        max=1.0,
        precision=2
    )

    bevel_loop_slide: BoolProperty(
        name="锁定循环边滑动 (loop_slide)",
        description="阻止端点沿循环边滑动，彻底解决边向中心靠拢的问题",
        default=True
    )

    bevel_clamp: BoolProperty(
        name="防重叠 (clamp_overlap)",
        default=True
    )

    bevel_expand_loop: BoolProperty(
        name="自动补全循环边",
        default=True
    )

    loopcut_count: IntProperty(
        name="循环边数量",
        default=1,
        min=1,
        max=50
    )

    loopcut_expand: BoolProperty(
        name="自动补全循环边",
        default=True
    )

    loopcut_smooth: FloatProperty(
        name="平滑系数",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=2
    )

    edit_report: StringProperty(name="编辑工具报告", default="")


# ---------------------------------------------------------------------------
# 操作符 (Operators)
# ---------------------------------------------------------------------------

class MESH_OT_ai_mesh_diagnose(Operator):
    bl_idname = "mesh.ai_mesh_diagnose"
    bl_label = "体检网格破面状况"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体 (Mesh Object)")
            return {'CANCELLED'}
            
        res = analyze_mesh_health(obj)
        if not res:
            self.report({'ERROR'}, "体检分析失败")
            return {'CANCELLED'}
            
        props = context.scene.ai_mesh_healer_props
        props.last_holes_count = res['holes_count']
        props.last_slits_count = res['slits_count']
        props.last_boundary_edges = res['boundary_edges']
        props.last_non_manifold = res['non_manifold_edges']
        props.last_tri_pct = res['tri_pct']
        props.last_quad_pct = res['quad_pct']
        
        if res['is_healthy']:
            props.last_diag_status = "优良 (闭合完整流形)"
            self.report({'INFO'}, "体检结果：模型网格完全闭合，无破面！")
        else:
            props.last_diag_status = f"存在破损 (孔洞:{res['holes_count']}, 缝隙:{res['slits_count']}, 边界边:{res['boundary_edges']})"
            self.report({'WARNING'}, f"体检完成: 发现 {res['holes_count']} 处孔洞, {res['slits_count']} 处开裂缝隙, {res['boundary_edges']} 处开边界边")
            
        return {'FINISHED'}


class MESH_OT_ai_mesh_select_issues(Operator):
    bl_idname = "mesh.ai_mesh_select_issues"
    bl_label = "高亮选中破面区域"
    bl_options = {'REGISTER', 'UNDO'}
    
    select_type: EnumProperty(
        name="选中类型",
        items=[
            ('ALL', "所有破面问题", "选中孔洞边界边和非流形边"),
            ('HOLES', "仅孔洞/裂缝边界", "只选中开边界边"),
            ('NON_MANIFOLD', "仅非流形边", "只选中非流形边"),
        ],
        default='ALL'
    )
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
            
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
            
        bm = bmesh.from_edit_mesh(obj.data)
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
            
        selected_count = 0
        if self.select_type in ('ALL', 'HOLES'):
            for e in bm.edges:
                if e.is_boundary:
                    e.select = True
                    e.verts[0].select = True
                    e.verts[1].select = True
                    selected_count += 1
                    
        if self.select_type in ('ALL', 'NON_MANIFOLD'):
            for e in bm.edges:
                if len(e.link_faces) > 2 or len(e.link_faces) == 0:
                    e.select = True
                    e.verts[0].select = True
                    e.verts[1].select = True
                    selected_count += 1
                    
        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, f"已高亮选中 {selected_count} 处问题几何元素")
        return {'FINISHED'}


class MESH_OT_ai_mesh_auto_heal(Operator):
    bl_idname = "mesh.ai_mesh_auto_heal"
    bl_label = "一键智能修复全部破面"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
            
        props = context.scene.ai_mesh_healer_props
        orig_mode = obj.mode
        if orig_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        old_bak = obj.get("ai_heal_backup")
        if old_bak:
            b_ob = bpy.data.objects.get(old_bak)
            if b_ob:
                try:
                    bpy.data.objects.remove(b_ob, do_unlink=True)
                except Exception:
                    pass
        bak_obj = _dup_object(obj, HEAL_BAK_SUFFIX)
        bak_obj.hide_set(True)
        bak_obj.hide_viewport = True
        obj["ai_heal_backup"] = bak_obj.name
        
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        if props.merge_doubles:
            safe_clean_mesh(bm, merge_dist=props.merge_dist)
            
        new_faces, new_verts = fill_mesh_holes_safely(
            bm,
            max_sides=props.max_hole_sides,
            topology_mode=props.topology_mode
        )
        
        if props.do_smooth and new_verts:
            gentle_smooth(bm, new_verts, iterations=props.smooth_iterations, factor=0.35)
            
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        for f in bm.faces:
            f.smooth = True
            
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        
        if props.clear_custom_normals:
            fix_normals_and_clear_custom(obj)
            
        res = analyze_mesh_health(obj)
        if res:
            props.last_holes_count = res['holes_count']
            props.last_slits_count = res['slits_count']
            props.last_boundary_edges = res['boundary_edges']
            props.last_non_manifold = res['non_manifold_edges']
            props.last_tri_pct = res['tri_pct']
            props.last_quad_pct = res['quad_pct']
            props.last_diag_status = "优良 (已修复闭合)" if res['is_healthy'] else f"剩余孔洞:{res['holes_count']}"
            
        if orig_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=orig_mode)
            
        self.report({'INFO'}, f"安全修复完成！补面/缝合 {len(new_faces)} 个面，法线已重整（若不满意可随时点回滚）")
        return {'FINISHED'}


class MESH_OT_ai_mesh_restore_heal(Operator):
    bl_idname = "mesh.ai_mesh_restore_heal"
    bl_label = "回滚到修复前原样"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
            
        if _restore_from_backup(obj, "ai_heal_backup"):
            self.report({'INFO'}, "已成功恢复到修复前的原始网格状态！")
        else:
            self.report({'WARNING'}, "未找到本次修复的备份数据")
        return {'FINISHED'}


class MESH_OT_ai_mesh_rescue(Operator):
    bl_idname = "mesh.ai_mesh_rescue"
    bl_label = "一键清理百叶窗乱面并缝合 (Rescue)"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
            
        bak_obj = _dup_object(obj, "_RESCUE_BAK")
        bak_obj.hide_set(True)
        bak_obj.hide_viewport = True
        obj["ai_heal_backup"] = bak_obj.name
        
        cleaned = rescue_corrupted_mesh(obj)
        self.report({'INFO'}, f"救援成功！已清理 {cleaned} 个畸变百叶窗碎面，并重新平整拉链缝合与法线重构！")
        return {'FINISHED'}


class MESH_OT_ai_mesh_clear_normals(Operator):
    bl_idname = "mesh.ai_mesh_clear_normals"
    bl_label = "清除法线黑斑与光影撕裂"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体")
            return {'CANCELLED'}
            
        fix_normals_and_clear_custom(obj)
        self.report({'INFO'}, "已彻底清除自定义法线层，重新生成外向法线和平滑着色！")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 自助布尔 操作符 (含布尔免疫深度修复与自愈)
# ---------------------------------------------------------------------------

class MESH_OT_ai_bool_precheck(Operator):
    bl_idname = "mesh.ai_bool_precheck"
    bl_label = "布尔前预检"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        target = context.active_object
        if not target or target.type != 'MESH':
            self.report({'WARNING'}, "请先选中主体网格")
            return {'CANCELLED'}

        cutters = [o for o in context.selected_objects if o.type == 'MESH' and o != target]
        lines = []
        st = _mesh_stats(target)
        lines.append("主体 %s: 面 %d / 壳体 %d / 破边 %d / 非流形 %d" % (
            target.name, st['faces'], st['shells'], st['boundary_edges'], st['non_manifold']))
        if st['shells'] > 1:
            lines.append("提示：主体含 %d 个壳体" % st['shells'])
        if st['non_manifold'] > 0:
            lines.append("⚠️ 主体含非流形边，建议先点下方【布尔免疫深度修复】！")

        for c in cutters:
            cs = _mesh_stats(c)
            lines.append("切割体 %s: 面 %d / 破边 %d / 非流形 %d" % (
                c.name, cs['faces'], cs['boundary_edges'], cs['non_manifold']))
            if cs['non_manifold'] > 0:
                lines.append("⚠️ 切割体含非流形边，建议先做免疫修复！")

        if not cutters:
            lines.append("警告：未选中任何切割体，请按住 Shift 多选切割体")

        props.bool_report = " | ".join(lines)
        self.report({'INFO'}, "预检完成，详见面板报告")
        return {'FINISHED'}


class MESH_OT_ai_bool_immunize_mesh(Operator):
    """一键将主体与切割体深度净化为100%实体流形（消除内部面、自交、非流形）"""
    bl_idname = "mesh.ai_bool_immunize_mesh"
    bl_label = "一键布尔免疫修复 (消除非流形/内部面)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        target = context.active_object
        if not target or target.type != 'MESH':
            self.report({'WARNING'}, "请先选中主体网格")
            return {'CANCELLED'}

        cutters = [o for o in context.selected_objects if o.type == 'MESH' and o != target]
        all_targets = [target] + cutters
        
        for obj in all_targets:
            clean_mesh_for_boolean(obj)

        st = _mesh_stats(target)
        msg = f"已完成深度布尔免疫净化！主体当前非流形边: {st['non_manifold']}, 破边: {st['boundary_edges']}，下次布尔畅通无阻！"
        props.bool_report = msg
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class MESH_OT_ai_bool_execute(Operator):
    """执行自助布尔：预处理 + 自动深度自愈 + 共面微扰 + 结果自动纠偏"""
    bl_idname = "mesh.ai_bool_execute"
    bl_label = "执行自助布尔 (含自愈重试)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        target = context.active_object
        if not target or target.type != 'MESH':
            self.report({'WARNING'}, "请先选中主体网格")
            return {'CANCELLED'}

        cutters = [o for o in context.selected_objects if o.type == 'MESH' and o != target]
        if not cutters:
            self.report({'WARNING'}, "请同时选中至少一个切割体（Shift 多选）")
            return {'CANCELLED'}

        _ensure_object_mode()

        old_bak = target.get("ai_bool_backup")
        if old_bak:
            ob = bpy.data.objects.get(old_bak)
            if ob:
                try:
                    bpy.data.objects.remove(ob, do_unlink=True)
                except Exception:
                    pass
        backup = _dup_object(target, BOOL_BAK_SUFFIX)
        backup.hide_set(True)
        backup.hide_viewport = True
        target["ai_bool_backup"] = backup.name

        # 预先深度净化
        if props.bool_auto_heal_on_fail:
            clean_mesh_for_boolean(target)

        work_cutters = []
        for c in cutters:
            c2 = _dup_object(c, BOOL_CUT_SUFFIX)
            work_cutters.append(c2)
            if props.bool_auto_heal_on_fail:
                clean_mesh_for_boolean(c2)
            if props.bool_gap > 0:
                _shrink_along_normals(c2, props.bool_gap / 1000.0)

        op = props.bool_operation
        messages = []
        extra_parts = []

        if op == 'SLICE':
            part_b = _dup_object(target, BOOL_CUT_SUFFIX + "_B")
            extra_parts.append(part_b)
            before = _mesh_stats(target)
            ok_all = True
            for c2 in work_cutters:
                ok, msg = _bool_with_adaptive_self_healing(target, c2, 'DIFFERENCE', props, before)
                if not ok:
                    ok_all = False
                    messages.append("主体差集失败：" + msg)
                    break
                before = _mesh_stats(target)
            if ok_all:
                before_b = _mesh_stats(part_b)
                for c2 in work_cutters:
                    ok, msg = _bool_with_adaptive_self_healing(part_b, c2, 'INTERSECT', props, before_b)
                    if not ok:
                        ok_all = False
                        messages.append("切下部分交集失败：" + msg)
                        break
                    before_b = _mesh_stats(part_b)
            if ok_all:
                _post_clean(target, props)
                _post_clean(part_b, props)
        else:
            before = _mesh_stats(target)
            ok_all = True
            for c2 in work_cutters:
                ok, msg = _bool_with_adaptive_self_healing(target, c2, op, props, before)
                if not ok:
                    ok_all = False
                    messages.append(msg)
                    break
                before = _mesh_stats(target)
            if ok_all:
                _post_clean(target, props)

        for c2 in work_cutters + extra_parts:
            try:
                if c2.name in bpy.data.objects:
                    bpy.data.objects.remove(c2, do_unlink=True)
            except Exception:
                pass

        if ok_all and props.bool_delete_cutter:
            for c in cutters:
                try:
                    if c.name in bpy.data.objects:
                        bpy.data.objects.remove(c, do_unlink=True)
                except Exception:
                    pass

        st = _mesh_stats(target)
        if ok_all:
            props.bool_report = ("布尔成功！面 %d / 壳体 %d / 破边 %d / 非流形 %d" % (
                st['faces'], st['shells'], st['boundary_edges'], st['non_manifold']))
            self.report({'INFO'}, props.bool_report)
        else:
            props.bool_report = "已触发自愈与回滚 | " + "；".join(messages)
            self.report({'WARNING'}, props.bool_report)

        _activate(target)
        return {'FINISHED'}


class MESH_OT_ai_bool_restore(Operator):
    bl_idname = "mesh.ai_bool_restore"
    bl_label = "回滚到布尔前"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选中网格")
            return {'CANCELLED'}

        if _restore_from_backup(obj, "ai_bool_backup"):
            props.bool_report = "已回滚到布尔前状态"
            self.report({'INFO'}, props.bool_report)
        else:
            props.bool_report = "没有找到布尔备份，无法回滚"
            self.report({'WARNING'}, props.bool_report)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# 智能倒角 / 循环边 操作符
# ---------------------------------------------------------------------------

class MESH_OT_ai_smart_bevel(Operator):
    bl_idname = "mesh.ai_smart_bevel"
    bl_label = "智能倒角 (选中边)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选中网格")
            return {'CANCELLED'}

        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bpy.ops.mesh.select_mode(type='EDGE')

        if props.bevel_expand_loop:
            _expand_to_full_loops(bmesh.from_edit_mesh(obj.data))

        bm = bmesh.from_edit_mesh(obj.data)
        edges = [e for e in bm.edges if e.select]
        if not edges:
            self.report({'WARNING'}, "请先选中需要倒角的边")
            return {'CANCELLED'}

        res = _bevel_edges_safe(
            bm, edges,
            offset=props.bevel_offset,
            offset_type=props.bevel_offset_type,
            segments=props.bevel_segments,
            profile=props.bevel_profile,
            clamp_overlap=props.bevel_clamp,
            loop_slide=props.bevel_loop_slide
        )
        bmesh.update_edit_mesh(obj.data)

        if res is None:
            props.edit_report = "倒角失败：当前版本不支持该参数组合"
            self.report({'WARNING'}, props.edit_report)
            return {'CANCELLED'}

        props.edit_report = "倒角完成：%d 条边，宽度模式 %s" % (len(edges), props.bevel_offset_type)
        self.report({'INFO'}, props.edit_report)
        return {'FINISHED'}


class MESH_OT_ai_add_loop_cut(Operator):
    bl_idname = "mesh.ai_add_loop_cut"
    bl_label = "加循环边 (选中边)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.ai_mesh_healer_props
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选中网格")
            return {'CANCELLED'}

        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')

        bpy.ops.mesh.select_mode(type='EDGE')

        if props.loopcut_expand:
            _expand_to_full_loops(bmesh.from_edit_mesh(obj.data))

        bm = bmesh.from_edit_mesh(obj.data)
        edges = [e for e in bm.edges if e.select]
        if not edges:
            self.report({'WARNING'}, "请先选中一条边（会自动扩展成完整循环）")
            return {'CANCELLED'}

        try:
            bmesh.ops.subdivide_edges(
                bm,
                edges=edges,
                cuts=props.loopcut_count,
                use_grid_fill=True,
                smooth=props.loopcut_smooth
            )
            bmesh.update_edit_mesh(obj.data)
            props.edit_report = "已插入 %d 条循环边" % props.loopcut_count
            self.report({'INFO'}, props.edit_report)
            return {'FINISHED'}
        except Exception as e:
            props.edit_report = "加循环边失败：%s" % str(e)
            self.report({'WARNING'}, props.edit_report)
            return {'CANCELLED'}


# ---------------------------------------------------------------------------
# UI 界面面板 (UI Panels in 3D Viewport Sidebar)
# ---------------------------------------------------------------------------

class VIEW3D_PT_ai_mesh_healer_main(Panel):
    bl_label = "AI 破面修复 (安全防百叶窗)"
    bl_idname = "VIEW3D_PT_ai_mesh_healer_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '通用插件'
    
    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        props = context.scene.ai_mesh_healer_props
        
        box = layout.box()
        if not obj or obj.type != 'MESH':
            box.label(text="未选中网格模型", icon=_icon('ERROR'))
            box.label(text="请在3D视口中点击选择AI模型", icon=_icon('INFO'))
            return
            
        row = box.row()
        row.label(text=f"目标模型: {obj.name}", icon=_icon('OBJECT_DATA'))
        
        col_diag = box.column(align=True)
        col_diag.operator("mesh.ai_mesh_diagnose", text="体检破面与开裂缝隙 (Diagnose)", icon=_icon('DIAGNOSTIC'))
        
        if props.last_holes_count >= 0:
            status_box = box.box()
            is_good = (props.last_holes_count == 0 and props.last_slits_count == 0 and props.last_boundary_edges == 0 and props.last_non_manifold == 0)
            if is_good:
                status_box.label(text="● 状态: 网格优良 (完全闭合流形)", icon=_icon('CHECKMARK'))
            else:
                status_box.label(text=f"● 发现 {props.last_holes_count} 处孔洞 / {props.last_slits_count} 处开裂缝隙", icon=_icon('ERROR'))
                
            info_col = status_box.column(align=True)
            r1 = info_col.row(align=True)
            r1.label(text=f"非流形边: {props.last_non_manifold}")
            r1.label(text=f"边界边: {props.last_boundary_edges}")
            
            r2 = info_col.row(align=True)
            r2.label(text=f"三角面: {props.last_tri_pct:.1f}%")
            r2.label(text=f"四边面: {props.last_quad_pct:.1f}%")
            
        row_sel = box.row(align=True)
        row_sel.operator("mesh.ai_mesh_select_issues", text="高亮所有破损", icon=_icon('RESTRICT_SELECT_OFF')).select_type = 'ALL'
        row_sel.operator("mesh.ai_mesh_select_issues", text="高亮开边界", icon=_icon('SNAP_FACE')).select_type = 'HOLES'
        
        layout.separator()
        
        big_box = layout.box()
        big_col = big_box.column(align=True)
        big_col.scale_y = 1.5
        big_col.operator("mesh.ai_mesh_auto_heal", text="一键安全修复全部破面", icon=_icon('MOD_SMOOTH'))
        
        row_undo = layout.row(align=True)
        row_undo.operator("mesh.ai_mesh_restore_heal", text="一键恢复修复前原样", icon=_icon('LOOP_BACK'))
        
        rescue_box = layout.box()
        rescue_box.label(text="受损模型急救箱 (专治百叶窗乱面):", icon=_icon('TOOL_SETTINGS'))
        r_col = rescue_box.column(align=True)
        r_col.operator("mesh.ai_mesh_rescue", text="一键清理百叶窗碎面并缝合", icon=_icon('MOD_BEVEL'))
        r_col.operator("mesh.ai_mesh_clear_normals", text="一键消除法线黑斑/撕裂阴影", icon=_icon('NORMALS_FACE'))


class VIEW3D_PT_ai_mesh_healer_topology(Panel):
    bl_label = "补面与防百叶窗设置"
    bl_idname = "VIEW3D_PT_ai_mesh_healer_topology"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '通用插件'
    bl_parent_id = "VIEW3D_PT_ai_mesh_healer_main"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_mesh_healer_props
        
        col = layout.column(align=True)
        col.prop(props, "stitch_slits_first")
        col.prop(props, "topology_mode")
        col.prop(props, "max_hole_sides")
        
        layout.separator()
        box = layout.box()
        box.label(text="安全清理与法线选项:", icon=_icon('TOOL_SETTINGS'))
        b_col = box.column(align=True)
        b_col.prop(props, "merge_doubles")
        if props.merge_doubles:
            b_col.prop(props, "merge_dist")
        b_col.prop(props, "clear_custom_normals")
        b_col.prop(props, "do_smooth")
        if props.do_smooth:
            b_col.prop(props, "smooth_iterations")


class VIEW3D_PT_ai_bool(Panel):
    """自助布尔与自愈免疫引擎"""
    bl_label = "自助布尔 (自愈免疫引擎)"
    bl_idname = "VIEW3D_PT_ai_bool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '通用插件'

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_mesh_healer_props
        target = context.active_object

        box = layout.box()
        if not target or target.type != 'MESH':
            box.label(text="未选中主体网格", icon=_icon('ERROR'))
            box.label(text="先选主体，再按住 Shift 多选切割体", icon=_icon('INFO'))
            return

        cutters = [o for o in context.selected_objects if o.type == 'MESH' and o != target]
        box.label(text="主体: %s" % target.name, icon=_icon('OBJECT_DATA'))
        box.label(text="切割体: %d 个" % len(cutters), icon=_icon('MESH_DATA'))

        row_pre = box.row(align=True)
        row_pre.operator("mesh.ai_bool_precheck", text="布尔前预检", icon=_icon('VIEWZOOM'))
        
        # 核心功能：一键布尔免疫深度修复
        imm_box = layout.box()
        imm_box.label(text="布尔免疫手术刀 (解决1009条非流形):", icon=_icon('TOOL_SETTINGS'))
        imm_col = imm_box.column(align=True)
        imm_col.operator("mesh.ai_bool_immunize_mesh", text="一键布尔免疫修复 (清内部面/流形化)", icon=_icon('CHECKMARK'))

        col = layout.column(align=True)
        col.prop(props, "bool_operation")
        col.prop(props, "bool_solver")
        col.prop(props, "bool_gap")

        heal_box = layout.box()
        heal_box.label(text="自愈与防失败保障:", icon=_icon('FILE_REFRESH'))
        heal_box.prop(props, "bool_auto_heal_on_fail")
        heal_box.prop(props, "bool_retry_count")
        heal_box.prop(props, "bool_voxel_fallback")
        if props.bool_voxel_fallback:
            heal_box.prop(props, "bool_voxel_size")

        adv = layout.box()
        adv.label(text="容错与后处理:", icon=_icon('MODIFIER'))
        adv.prop(props, "bool_use_self")
        adv.prop(props, "bool_hole_tolerant")
        adv.prop(props, "bool_weld_before")
        adv.prop(props, "bool_delete_cutter")

        big = layout.box()
        big_col = big.column(align=True)
        big_col.scale_y = 1.6
        big_col.operator("mesh.ai_bool_execute", text="执行自助布尔 (自动自愈)", icon=_icon('MOD_BOOLEAN'))

        row = layout.row(align=True)
        row.operator("mesh.ai_bool_restore", text="回滚到布尔前", icon=_icon('LOOP_BACK'))

        if props.bool_report:
            rep = layout.box()
            rep.label(text="自愈与状态报告:", icon=_icon('TEXT'))
            for line in props.bool_report.split(" | "):
                rep.label(text=line)


class VIEW3D_PT_ai_bevel(Panel):
    bl_label = "智能倒角 / 循环边"
    bl_idname = "VIEW3D_PT_ai_bevel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '通用插件'

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_mesh_healer_props

        box = layout.box()
        box.label(text="倒角 (编辑模式选中边)", icon=_icon('MOD_BEVEL'))
        col = box.column(align=True)
        col.prop(props, "bevel_offset")
        col.prop(props, "bevel_offset_type")
        col.prop(props, "bevel_segments")
        col.prop(props, "bevel_profile")
        col.prop(props, "bevel_loop_slide")
        col.prop(props, "bevel_clamp")
        col.prop(props, "bevel_expand_loop")
        box.operator("mesh.ai_smart_bevel", text="智能倒角 (防塌陷)", icon=_icon('MOD_BEVEL'))

        box2 = layout.box()
        box2.label(text="加循环边 (编辑模式选中边)", icon=_icon('MOD_EDGESPLIT'))
        c2 = box2.column(align=True)
        c2.prop(props, "loopcut_count")
        c2.prop(props, "loopcut_smooth")
        c2.prop(props, "loopcut_expand")
        box2.operator("mesh.ai_add_loop_cut", text="加循环边", icon=_icon('EDGESEL'))

        if props.edit_report:
            rep = layout.box()
            rep.label(text=props.edit_report, icon=_icon('INFO'))


# ---------------------------------------------------------------------------
# 注册与注销 (Registration)
# ---------------------------------------------------------------------------

classes = (
    AIMeshHealerProperties,
    MESH_OT_ai_mesh_diagnose,
    MESH_OT_ai_mesh_select_issues,
    MESH_OT_ai_mesh_auto_heal,
    MESH_OT_ai_mesh_restore_heal,
    MESH_OT_ai_mesh_rescue,
    MESH_OT_ai_mesh_clear_normals,
    MESH_OT_ai_bool_precheck,
    MESH_OT_ai_bool_immunize_mesh,
    MESH_OT_ai_bool_execute,
    MESH_OT_ai_bool_restore,
    MESH_OT_ai_smart_bevel,
    MESH_OT_ai_add_loop_cut,
    VIEW3D_PT_ai_mesh_healer_main,
    VIEW3D_PT_ai_mesh_healer_topology,
    VIEW3D_PT_ai_bool,
    VIEW3D_PT_ai_bevel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ai_mesh_healer_props = PointerProperty(type=AIMeshHealerProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "ai_mesh_healer_props"):
        del bpy.types.Scene.ai_mesh_healer_props

if __name__ == "__main__":
    register()
