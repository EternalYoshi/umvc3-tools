import json
import os
import re
from collections import defaultdict

import bpy
from mathutils import Matrix, Vector

STANDARD = frozenset(set(range(1, 24)) | set(range(25, 29)) | set(range(31, 39)) | set(range(41, 45))
                     | set(range(50, 67)) | set(range(70, 87)) | set(range(90, 130)))
MAX_ID = 254            # the bone map is 256 bytes and 255 is reserved (jnt_255 / none)

MIRROR = {8: 12, 9: 13, 10: 14, 11: 15, 16: 20, 17: 21, 18: 22, 19: 23, 25: 26, 27: 28,
          31: 35, 32: 36, 33: 37, 34: 38, 41: 43, 42: 44, 90: 99,
          111: 112, 113: 114, 119: 120, 122: 125, 123: 126, 124: 127, 128: 129}
MIRROR.update({i: i + 20 for i in range(50, 67)})
MIRROR.update({i: i + 9 for i in range(91, 99)})
MIRROR.update({v: k for k, v in list(MIRROR.items())})

# (section, left or centre id, label, required)
SLOTS = [
    ('Body', 3, 'Pelvis / hips', True),
    ('Body', 4, 'Spine (lowest)', True),
    ('Body', 5, 'Chest (clavicles hang off it)', True),
    ('Body', 6, 'Neck', False),
    ('Body', 7, 'Head', True),
    ('Body', 8, 'Clavicle', False),
    ('Body', 9, 'Upper arm', True),
    ('Body', 10, 'Forearm', True),
    ('Body', 11, 'Hand', True),
    ('Body', 16, 'Thigh', True),
    ('Body', 17, 'Shin', True),
    ('Body', 18, 'Foot', True),
    ('Body', 19, 'Toe', False),
    ('Fingers', 50, 'Thumb 1', False), ('Fingers', 51, 'Thumb 2', False), ('Fingers', 52, 'Thumb 3', False),
    ('Fingers', 53, 'Index 1', False), ('Fingers', 54, 'Index 2', False), ('Fingers', 55, 'Index 3', False),
    ('Fingers', 56, 'Middle 1', False), ('Fingers', 57, 'Middle 2', False), ('Fingers', 58, 'Middle 3', False),
    ('Fingers', 59, 'Ring 1', False), ('Fingers', 60, 'Ring 2', False), ('Fingers', 61, 'Ring 3', False),
    ('Fingers', 62, 'Pinky metacarpal', False),
    ('Fingers', 63, 'Pinky 1', False), ('Fingers', 64, 'Pinky 2', False), ('Fingers', 65, 'Pinky 3', False),
    ('Helpers', 25, 'Shoulder helper (upper arm root)', False),
    ('Helpers', 33, 'Upper arm twist', False),
    ('Helpers', 31, 'Forearm twist', False),
    ('Helpers', 32, 'Wrist twist', False),
    ('Helpers', 27, 'Hip helper', False),
    ('Helpers', 42, 'Thigh twist', False),
    ('Helpers', 41, 'Ankle helper', False),
    ('Face', 90, 'Eye', False),
    ('Face', 91, 'Upper eyelid 1', False), ('Face', 92, 'Upper eyelid 2', False), ('Face', 93, 'Upper eyelid 3', False),
    ('Face', 94, 'Lower eyelid 1', False), ('Face', 95, 'Lower eyelid 2', False), ('Face', 96, 'Lower eyelid 3', False),
    ('Face', 122, 'Brow 1 (inner)', False), ('Face', 123, 'Brow 2', False), ('Face', 124, 'Brow 3 (outer)', False),
    ('Face', 128, 'Cheek', False),
    ('Face', 108, 'Nose', False),
    ('Face', 111, 'Upper lip', False),
    ('Face', 113, 'Mouth corner', False),
    ('Face', 115, 'Jaw', False),
    ('Face', 116, 'Chin', False),
    ('Face', 117, 'Lower teeth', False),
    ('Face', 119, 'Lower lip', False),
]
SECTIONS = ['Body', 'Fingers', 'Helpers', 'Face']


def slot_ids():
    out = []
    for sec, i, label, req in SLOTS:
        out.append(i)
        if i in MIRROR:
            out.append(MIRROR[i])
    return out


def is_left(i):
    return i in MIRROR and MIRROR[i] > i


def required_ids():
    out = set()
    for sec, i, label, req in SLOTS:
        if req:
            out.add(i)
            if i in MIRROR:
                out.add(MIRROR[i])
    return out


def slot_label(i):
    for sec, j, label, req in SLOTS:
        if j == i:
            return ('Left ' + label) if i in MIRROR else label
        if MIRROR.get(j) == i:
            return 'Right ' + label
    return 'jnt_%d' % i


AIMS = [(4, 5), (5, 6), (6, 7),
        (8, 9), (9, 10), (10, 11), (11, 56, (53, 63)),
        (16, 17), (17, 18), (18, 19),
        (50, 51), (51, 52), (53, 54), (54, 55), (56, 57), (57, 58),
        (59, 60), (60, 61), (62, 63), (63, 64), (64, 65)]


def all_aims():
    out = []
    for a in AIMS:
        out.append(a)
        r = tuple(MIRROR.get(x, x) if isinstance(x, int) else tuple(MIRROR.get(y, y) for y in x) for x in a)
        if r != a:
            out.append(r)
    return out

def norm(name):
    return re.split(r'[:|]', name)[-1].lower()


_SIDE_PATTERNS = [
    (re.compile(r'(^|[_.\- ])([LR])([_.\- ]|$)'), 2, {'L': 'R', 'R': 'L'}),
    (re.compile(r'(^|[_.\- ])([lr])([_.\- ]|$)'), 2, {'l': 'r', 'r': 'l'}),
    (re.compile(r'(Left|Right)'), 1, {'Left': 'Right', 'Right': 'Left'}),
    (re.compile(r'(left|right)'), 1, {'left': 'right', 'right': 'left'}),
    (re.compile(r'(LEFT|RIGHT)'), 1, {'LEFT': 'RIGHT', 'RIGHT': 'LEFT'}),
    (re.compile(r'(^|_)([LR])(?=[A-Z])'), 2, {'L': 'R', 'R': 'L'}),        # SF4: LArm1, Face_LEye
]


def mirror_name(name, names):
    sided = False
    for rx, g, swap in _SIDE_PATTERNS:
        for m in rx.finditer(name):
            sided = True
            other = name[:m.start(g)] + swap[m.group(g)] + name[m.end(g):]
            if other in names:
                return other, True
    return None, sided

PRESET_DIR = os.path.join(os.path.dirname(__file__), 'skeleton_presets')


def load_presets():
    out = {}
    for fn in sorted(os.listdir(PRESET_DIR)) if os.path.isdir(PRESET_DIR) else []:
        if fn.endswith('.json'):
            try:
                with open(os.path.join(PRESET_DIR, fn), encoding='utf-8') as f:
                    out[fn[:-5]] = json.load(f)
            except Exception as e:
                print('umvc3-tools: bad skeleton preset %s: %s' % (fn, e))
    out['umvc3'] = dict(name='UMVC3 (jnt_N)', sides=['L', 'R'],
                        center={str(i): ['jnt_%d' % i] for i in STANDARD})
    return out


def _expand(preset):
    out = {}
    for k, names in preset.get('center', {}).items():
        out[int(k)] = list(names)
    left, right = (preset.get('sides') or ['L', 'R'])[:2]
    for k, names in preset.get('side', {}).items():
        i = int(k)
        out[i] = [n.replace('{S}', left) for n in names]
        if i in MIRROR:
            out[MIRROR[i]] = [n.replace('{S}', right) for n in names]
    return out


def match_preset(arm, preset):
    by_norm = {}
    for b in arm.data.bones:
        by_norm.setdefault(norm(b.name), b.name)
    out = {}
    for i, names in _expand(preset).items():
        for n in names:
            b = by_norm.get(norm(n))
            if b is not None and b not in out.values():
                out[i] = b
                break
    return out


def structural_fill(arm, mapping):
    bones = arm.data.bones
    m = dict(mapping)
    arm_root = m.get(8) or m.get(9)
    if 5 not in m and arm_root and bones[arm_root].parent is not None:
        m[5] = bones[arm_root].parent.name
    if 6 not in m and 7 in m and bones[m[7]].parent is not None and bones[m[7]].parent.name not in m.values():
        m[6] = bones[m[7]].parent.name
    if 4 not in m and 3 in m and 5 in m:
        b = bones[m[5]]
        chain = []
        while b is not None and b.name != m[3]:
            chain.append(b.name)
            b = b.parent
        if b is not None and len(chain) >= 2 and chain[-1] not in m.values():
            m[4] = chain[-1]
    return m


def detect(arm, presets=None):
    presets = presets or load_presets()
    best = (None, {})
    for key, p in presets.items():
        m = match_preset(arm, p)
        if len(m) > len(best[1]):
            best = (key, m)
    if best[0] is None:
        return None, {}
    return best[0], structural_fill(arm, best[1])


def preset_reparent(arm, preset):
    out = {}
    names = {b.name for b in arm.data.bones}
    left, right = (preset.get('sides') or ['L', 'R'])[:2]
    for c, p in preset.get('reparent', {}).items():
        for s in ((left, right) if '{S}' in c or '{S}' in p else (None,)):
            cc = c.replace('{S}', s) if s else c
            pp = p.replace('{S}', s) if s else p
            if cc in names and (pp.startswith('#') or pp in names):
                out[cc] = pp
    return out

def check_mapping(arm, ref_arm, mapping):
    errors, warnings = [], []
    names = set(arm.data.bones.keys())
    for i in sorted(required_ids()):
        if not mapping.get(i):
            errors.append('%s is not set' % slot_label(i))
    seen = {}
    for i, n in mapping.items():
        if not n:
            continue
        if n not in names:
            errors.append('%s: no bone named %s' % (slot_label(i), n))
        if n in seen:
            errors.append('%s is used for both %s and %s' % (n, slot_label(seen[n]), slot_label(i)))
        seen[n] = i
    # a mapped bone must not sit above a joint that comes before it in the vanilla rig
    if ref_arm is None:
        errors.append('pick the reference rig (the .mod of the slot you are replacing, imported with this addon)')
    else:
        ref = reference(ref_arm)
        missing = sorted(i for i, n in mapping.items() if n and i not in ref['frames'])
        if missing:
            warnings.append('the reference rig has no %s, those stay unmapped' % ', '.join('jnt_%d' % i for i in missing))
    if 6 not in mapping and 7 in mapping:
        warnings.append('no neck bone: a neck joint gets added between chest and head')
    for hand, first, label in ((11, 50, 'left'), (15, 70, 'right')):
        if mapping.get(hand) and not any(mapping.get(i) for i in range(first, first + 16)):
            warnings.append('%s: no fingers mapped, the hand won\'t open or close' % label)
    pelvis = mapping.get(3)
    if pelvis in names:
        a = arm.data.bones[pelvis].parent
        while a is not None:
            if a.name in seen:
                errors.append('%s (%s) sits above the pelvis' % (a.name, slot_label(seen[a.name])))
            a = a.parent
    if arm.get('umvc3_converted'):
        errors.append('this armature has already been converted')
    return errors, warnings


def reference(ref_arm):
    frames, parents = {}, {}
    for b in ref_arm.data.bones:
        m = re.match(r'jnt_(\d+)$', b.name)
        if not m:
            continue
        i = int(m.group(1))
        frames[i] = ref_arm.matrix_world @ b.matrix_local
        pm = re.match(r'jnt_(\d+)$', b.parent.name) if b.parent else None
        parents[i] = int(pm.group(1)) if pm else None
    return dict(frames=frames, parents=parents)


def skinned_meshes(arm):
    return [o for o in bpy.data.objects if o.type == 'MESH' and (
        o.parent == arm or any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers))]


def bone_weights(meshes, bone_names):
    total = defaultdict(float)
    verts = defaultdict(int)
    for me in meshes:
        names = {g.index: g.name for g in me.vertex_groups}
        for v in me.data.vertices:
            for g in v.groups:
                if g.weight > 1e-6:
                    n = names[g.group]
                    if n in bone_names:
                        total[n] += g.weight
                        verts[n] += 1
    return total, verts


def merge_group(meshes, src, dst):
    for me in meshes:
        gs = me.vertex_groups.get(src)
        if gs is None:
            continue
        gd = me.vertex_groups.get(dst) or me.vertex_groups.new(name=dst)
        idx = gs.index
        for v in me.data.vertices:
            for g in v.groups:
                if g.group == idx and g.weight > 0:
                    gd.add([v.index], g.weight, 'ADD')
        me.vertex_groups.remove(gs)


def limit_weights(meshes, bone_names, limit=4):
    changed = 0
    for me in meshes:
        bone_groups = {g.index for g in me.vertex_groups if g.name in bone_names}
        groups = {g.index: g for g in me.vertex_groups}
        for v in me.data.vertices:
            ws = [(g.weight, g.group) for g in v.groups if g.group in bone_groups and g.weight > 0]
            if not ws:
                continue
            ws.sort(reverse=True)
            keep = ws[:limit]
            s = sum(w for w, _ in keep)
            if len(ws) > limit or abs(s - 1.0) > 1e-4:
                changed += 1
                for w, gi in ws[limit:]:
                    groups[gi].remove([v.index])
                for w, gi in keep:
                    groups[gi].add([v.index], w / s if s > 0 else 1.0 / len(keep), 'REPLACE')
    return changed


def measure_merge_error(arm, actions, max_frames=40, report=print):
    import numpy as np
    meshes = skinned_meshes(arm)
    data = arm.data
    rest_inv = {b.name: np.array(b.matrix_local.inverted()) for b in data.bones}
    per_bone = {}
    for me in meshes:
        to_arm = np.array(arm.matrix_world.inverted() @ me.matrix_world)
        co = np.ones((len(me.data.vertices), 4))
        co[:, :3] = [v.co for v in me.data.vertices]
        co = co @ to_arm.T
        names = {g.index: g.name for g in me.vertex_groups}
        rows = defaultdict(list)
        for v in me.data.vertices:
            for g in v.groups:
                if g.weight > 1e-6:
                    rows[names[g.group]].append((v.index, g.weight))
        for n, r in rows.items():
            if n in data.bones and data.bones[n].parent:
                idx = np.array([i for i, _ in r])
                w = np.array([x for _, x in r])
                if n in per_bone:
                    per_bone[n] = (np.vstack([per_bone[n][0], co[idx]]), np.concatenate([per_bone[n][1], w]))
                else:
                    per_bone[n] = (co[idx], w)
    err = defaultdict(float)
    ad = arm.animation_data or arm.animation_data_create()
    keep = ad.action
    scene = bpy.context.scene
    for act in actions:
        ad.action = act
        f0, f1 = (int(x) for x in act.frame_range)
        n = min(max_frames, f1 - f0 + 1)
        for f in sorted({round(f0 + (f1 - f0) * k / max(1, n - 1)) for k in range(n)}):
            scene.frame_set(f)
            skin = {pb.name: np.array(pb.matrix) @ rest_inv[pb.name] for pb in arm.pose.bones}
            for b, (co, w) in per_bone.items():
                d = (skin[b] - skin[data.bones[b].parent.name]) @ co.T
                e = float(np.max(np.linalg.norm(d[:3], axis=0) * w))
                if e > err[b]:
                    err[b] = e
        report('  measured %s (%d frames)' % (act.name, n))
    ad.action = keep
    return dict(err)


def _mode(obj, mode):
    view = bpy.context.view_layer
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in view.objects:
        o.select_set(False)
    view.objects.active = obj
    obj.select_set(True)
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def _transform_rig(arm, meshes, mtx):
    parents = {}
    for me in meshes:
        parents[me.name] = (me.parent, me.parent_type, me.parent_bone)
        mw = me.matrix_world.copy()
        me.parent = None
        me.matrix_world = mw
    for o in [arm] + meshes:
        o.matrix_world = mtx @ o.matrix_world
    bpy.context.view_layer.update()
    _mode(arm, 'OBJECT')
    for o in [arm] + meshes:
        o.hide_set(False)
        o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for me in meshes:
        p = parents[me.name][0]
        if p is not None:
            me.parent = p
            me.matrix_parent_inverse = p.matrix_world.inverted()
    bpy.context.view_layer.update()



def _place_dummies(eb, dummies, dname, target, frames, rparent):
    placed = set()
    for _ in range(4):              # nested ones (jnt_1 above jnt_2) need a few passes
        for i in sorted(dummies):
            ch = [j for j, pj in rparent.items() if pj == i and j in target and target[j] in eb]
            if not ch:
                continue
            cpos = sum((eb[target[j]].head for j in ch), Vector()) / len(ch)
            rc = sum((frames[j].translation for j in ch), Vector()) / len(ch)
            pid = rparent.get(i)
            k = 1.0
            if pid is not None and pid in target and target[pid] in eb:
                full = (rc - frames[pid].translation).length
                if full > 1e-4:
                    k = (cpos - eb[target[pid]].head).length / full
            mm = frames[i].to_3x3().normalized().to_4x4()
            mm.translation = cpos + (frames[i].translation - rc) * k
            eb[dname[i]].matrix = mm
            placed.add(i)
    for i in dummies:
        pid = rparent.get(i)
        if i not in placed and pid in target and target[pid] in eb:
            mm = frames[i].to_3x3().normalized().to_4x4()
            mm.translation = eb[target[pid]].head
            eb[dname[i]].matrix = mm


def convert(arm, ref_arm, mapping, keep_prefixes=(), reparent=None, actions=None,
            scale_to_ref=True, report=print):
    mapping = {int(i): n for i, n in mapping.items() if n}
    errors, warnings = check_mapping(arm, ref_arm, mapping)
    if errors:
        raise RuntimeError('\n'.join(errors))
    for w in warnings:
        report('  note: ' + w)
    ref = reference(ref_arm)
    frames, rparent = ref['frames'], ref['parents']
    mapping = {i: n for i, n in mapping.items() if i in frames}
    std = {n: i for i, n in mapping.items()}           # bone -> id
    reparent = dict(reparent or {})
    report('%s: %d bones, %d mapped to vanilla joints' % (arm.name, len(arm.data.bones), len(std)))

    error = measure_merge_error(arm, actions, report=report) if actions else None
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()

    meshes = skinned_meshes(arm)
    for me in meshes:
        if me.parent == arm and me.parent_type == 'BONE' and me.parent_bone in arm.data.bones:
            mw = me.matrix_world.copy()
            g = me.vertex_groups.get(me.parent_bone) or me.vertex_groups.new(name=me.parent_bone)
            g.add(list(range(len(me.data.vertices))), 1.0, 'REPLACE')
            me.parent_type = 'OBJECT'
            me.matrix_world = mw
            report('  %s was attached to %s, now skinned to it' % (me.name, me.parent_bone))
        if not any(m.type == 'ARMATURE' and m.object == arm for m in me.modifiers):
            mod = me.modifiers.new('Armature', 'ARMATURE')
            mod.object = arm
        if me.data.shape_keys is not None:
            _mode(me, 'OBJECT')
            bpy.ops.object.shape_key_remove(all=True, apply_mix=False)
            report('  %s: shape keys removed (UMVC3 models have none)' % me.name)
    if not meshes:
        raise RuntimeError('no mesh is skinned to %s' % arm.name)

    def head(n):
        return arm.matrix_world @ arm.data.bones[n].head_local
    side = (head(mapping[9]) - head(mapping[13])) + (head(mapping[16]) - head(mapping[20]))
    up = head(mapping[7]) - head(mapping[3])
    x = side.normalized()
    z = (up - x * up.dot(x)).normalized()
    y = z.cross(x)
    rot = Matrix((x, y, z)).to_4x4()
    if 19 in mapping and 23 in mapping:
        toes = (head(mapping[19]) + head(mapping[23])) / 2 - (head(mapping[18]) + head(mapping[22])) / 2
        facing = (rot.to_3x3() @ toes).y
    elif 90 in mapping and 99 in mapping:
        facing = (rot.to_3x3() @ ((head(mapping[90]) + head(mapping[99])) / 2 - head(mapping[7]))).y
    else:
        facing = None
        report('  note: no toes or eyes mapped, can\'t check which way the model faces')
    if facing is not None and facing > 0:
        raise RuntimeError('left and right look swapped: with this mapping the character faces backwards. '
                           'Use Swap Sides, or check the Left and Right rows')
    _transform_rig(arm, meshes, rot)
    ground = min((me.matrix_world @ v.co).z for me in meshes for v in me.data.vertices)
    p = head(mapping[3])
    s = 1.0
    if scale_to_ref:
        s = frames[3].translation.z / max(1e-6, p.z - ground)
    mtx = Matrix.Scale(s, 4) @ Matrix.Translation((-p.x, -p.y, -ground))
    _transform_rig(arm, meshes, mtx)
    report('  stood up and scaled by %.4f (hips at %.2f)' % (s, head(mapping[3]).z))

    bone_names = set(arm.data.bones.keys())
    loose = 0
    for me in meshes:
        bg = {g.index for g in me.vertex_groups if g.name in bone_names}
        free = [v.index for v in me.data.vertices if not any(g.group in bg and g.weight > 0 for g in v.groups)]
        if free:
            g = me.vertex_groups.get(mapping[3]) or me.vertex_groups.new(name=mapping[3])
            g.add(free, 1.0, 'REPLACE')
            loose += len(free)
            report('  %s: %d vertices had no bone weight, now on the pelvis' % (me.name, len(free)))
    n = limit_weights(meshes, bone_names)
    if n:
        report('  %d vertices had more than 4 bone weights or did not add up to 1, fixed' % n)

    dummies = []
    for i in sorted(mapping):
        pid = rparent.get(i)
        while pid is not None and pid not in mapping and pid in frames and pid not in dummies:
            dummies.append(pid)
            pid = rparent.get(pid)
    for c, par in reparent.items():
        if par.startswith('#'):
            pid = int(par[1:])
            if pid not in mapping and pid in frames and pid not in dummies:
                dummies.append(pid)
    dname = {i: '__umvc3_jnt_%d' % i for i in dummies}

    bones = arm.data.bones
    kids = defaultdict(list)
    for b in bones:
        if b.parent:
            kids[b.parent.name].append(b.name)

    def subtree(n):
        out, st = [], [n]
        while st:
            x = st.pop()
            out.append(x)
            st += kids[x]
        return out

    total, verts = bone_weights(meshes, bone_names)
    above_pelvis = []
    b = bones[mapping[3]].parent
    while b is not None:
        above_pelvis.append(b.name)
        b = b.parent
    mapped = set(std)
    keep = set(mapped)                      
    for nme in bones.keys():
        if any(x in mapped for x in subtree(nme) if x != nme):
            keep.add(nme)
    keep -= set(above_pelvis)
    dead = [bb.name for bb in bones if bb.name not in keep and bb.name not in above_pelvis
            and all(verts[x] == 0 for x in subtree(bb.name))]
    dead_set = set(dead)
    alive = {bb.name for bb in bones if bb.name not in dead_set and bb.name not in above_pelvis}
    pool = [i for i in range(1, MAX_ID + 1) if i not in STANDARD]
    limit = len(mapping) + len(dummies) + len(pool)
    count = len(alive) + len(dummies)

    newparent = {bb.name: (bb.parent.name if bb.parent else None) for bb in bones}
    for c, par in reparent.items():
        if c in alive:
            newparent[c] = par

    def candidate(nme):
        return (nme in alive and nme not in keep and nme not in reparent.values()
                and not nme.startswith(tuple(keep_prefixes))
                and not any(newparent.get(k) == nme for k in alive)
                and newparent[nme] in alive)

    def cost(nme):
        return (error.get(nme, 0.0), total[nme]) if error is not None else (total[nme],)

    merges = []
    while count > limit:
        units = []
        names_alive = alive
        for nme in alive:
            if not candidate(nme):
                continue
            m, sided = mirror_name(nme, names_alive)
            if m is None:
                units.append(((nme,), cost(nme)))
            elif nme < m and candidate(m):
                units.append(((nme, m), max(cost(nme), cost(m))))
        if count - limit == 1 and any(len(u[0]) == 1 for u in units):
            units = [u for u in units if len(u[0]) == 1]
        if not units:
            raise RuntimeError('still %d bones and nothing left that can be merged (limit %d)' % (count, limit))
        units.sort(key=lambda u: (u[1], u[0]))
        for nme in units[0][0]:
            merges.append((nme, newparent[nme]))
            alive.discard(nme)
            count -= 1

    report('  %d -> %d bones (limit %d)' % (len(bones), count, limit))
    if dead:
        report('  deleted, nothing weighted to them (%d): %s' % (len(dead), ', '.join(dead)))
    if above_pelvis:
        report('  removed above the pelvis: %s' % ', '.join(above_pelvis))
    if merges:
        report('  merged into their parent (%d): %s' % (len(merges), ', '.join('%s>%s' % m for m in merges)))
    if dummies:
        report('  added vanilla joints: %s' % ', '.join('jnt_%d' % i for i in sorted(dummies)))

    for src, dst in merges:
        merge_group(meshes, src, dst)
    for nme in above_pelvis:
        merge_group(meshes, nme, mapping[3])
    for me in meshes:
        for nme in dead:
            g = me.vertex_groups.get(nme)
            if g:
                me.vertex_groups.remove(g)

    _mode(arm, 'EDIT')
    eb = arm.data.edit_bones
    for e in eb:
        e.use_connect = False
    target = {i: n for i, n in mapping.items()}
    target.update({i: dname[i] for i in dummies})
    for i in sorted(dummies):
        e = eb.new(dname[i])
        e.head = (0, 0, 0)
        e.tail = (0, 0, 2)
    _place_dummies(eb, dummies, dname, target, frames, rparent)
    tnames = set(target.values())
    for i, nme in target.items():
        pid = rparent.get(i)
        if pid is None or pid not in target:
            continue
        e, pe = eb[nme], eb[target[pid]]
        a = e.parent
        while a is not None and a != pe and a.name not in tnames:
            a = a.parent
        if a != pe:
            x = pe
            while x is not None and x != e:
                x = x.parent
            if x is e:
                raise RuntimeError('%s would end up its own parent: check the %s row' % (nme, slot_label(i)))
            e.parent = pe
    for c, par in reparent.items():
        if c in eb and c not in std:
            pname = target.get(int(par[1:])) if par.startswith('#') else par
            if pname in eb:
                eb[c].parent = eb[pname]
    hub = eb[target[2]] if 2 in target else eb[mapping[3]]
    gone = set(dead) | {a for a, _ in merges} | set(above_pelvis)
    for nme in gone:
        e = eb.get(nme)
        if e is None:
            continue
        for c in list(e.children):
            if c.name not in gone:
                c.parent = e.parent if e.parent is not None and e.parent.name not in above_pelvis else hub
        eb.remove(e)
    roots = [e for e in eb if e.parent is None]
    top = eb[target[1]] if 1 in target else hub
    for e in roots:
        if e != top:
            e.parent = hub
            report('  %s had no parent, now under %s' % (e.name, hub.name))
    bpy.ops.object.mode_set(mode='OBJECT')

    by_id = dict(target)
    _mode(arm, 'POSE')
    pbs = arm.pose.bones
    for aim in all_aims():
        bid, cid = aim[0], aim[1]
        if bid not in mapping or cid not in mapping:
            continue
        bpy.context.view_layer.update()
        pb = pbs[by_id[bid]]
        h = (arm.matrix_world @ pb.matrix).translation
        c = (arm.matrix_world @ pbs[by_id[cid]].matrix).translation
        if (c - h).length < 1e-5:
            continue
        d_ref = (frames[cid].translation - frames[bid].translation).normalized()
        q = (c - h).normalized().rotation_difference(d_ref)
        if len(aim) > 2:
            ua, ub = aim[2]
            if ua in mapping and ub in mapping:
                u_cur = q @ ((arm.matrix_world @ pbs[by_id[ub]].matrix).translation
                             - (arm.matrix_world @ pbs[by_id[ua]].matrix).translation)
                u_ref = frames[ub].translation - frames[ua].translation
                a = u_cur - d_ref * u_cur.dot(d_ref)
                bb = u_ref - d_ref * u_ref.dot(d_ref)
                if a.length > 1e-6 and bb.length > 1e-6:
                    q = a.normalized().rotation_difference(bb.normalized()) @ q
        r = Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h)
        pb.matrix = arm.matrix_world.inverted() @ r @ arm.matrix_world @ pb.matrix
    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode='OBJECT')
    for me in meshes:
        _mode(me, 'OBJECT')
        mods = [m for m in me.modifiers if m.type == 'ARMATURE' and m.object == arm]
        name = mods[0].name
        for m in mods[1:]:
            me.modifiers.remove(m)
        bpy.ops.object.modifier_move_to_index(modifier=name, index=0)
        bpy.ops.object.modifier_apply(modifier=name)
        nm = me.modifiers.new(name, 'ARMATURE')
        nm.object = arm
        bpy.ops.object.modifier_move_to_index(modifier=name, index=0)
    _mode(arm, 'POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    _mode(arm, 'EDIT')
    eb = arm.data.edit_bones
    tid = {n: i for i, n in target.items()}

    def frame_for(e):
        x = e
        while x is not None:
            i = tid.get(x.name)
            if i is not None:
                return frames[i]
            x = x.parent
        return None
    # the T-pose moved the limbs; put the added joints where they belong now
    _place_dummies(eb, dummies, dname, target, frames, rparent)
    passthrough = (keep - mapped) - gone
    for e in eb:
        if e.name in tid or e.name in passthrough:
            f = frame_for(e)
            if f is None:
                continue
            mm = f.to_3x3().normalized().to_4x4()
            mm.translation = e.head
            ln = max(e.length, 0.5)
            e.matrix = mm
            e.length = ln
    bpy.ops.object.mode_set(mode='OBJECT')

    order = []

    def walk(bb):
        order.append(bb.name)
        for c in sorted(bb.children, key=lambda x: (tid.get(x.name, 999), x.name)):
            walk(c)
    for r in [bb for bb in arm.data.bones if bb.parent is None]:
        walk(r)
    if len(order) > limit:
        raise RuntimeError('%d bones, limit %d' % (len(order), limit))
    ids = {n: tid[n] for n in order if n in tid}
    ref_used = set(frames)
    free_first = [i for i in pool if i not in ref_used] + [i for i in pool if i in ref_used]
    total, _ = bone_weights(meshes, set(order))
    rest = [n for n in order if n not in ids]
    # pass-through bones and heavy bones get the IDs the slot's own rig doesn't use
    rest.sort(key=lambda n: (0 if n in passthrough else 1, -total.get(n, 0.0)))
    it = iter(free_first)
    for nme in rest:
        ids[nme] = next(it)
    overlap = sorted(ids[n] for n in rest if ids[n] in ref_used)
    if overlap:
        report('  note: %d extra bones share IDs with the slot\'s own bones (%s); '
               'the slot\'s animations or physics may move them' % (len(overlap), ', '.join(map(str, overlap[:12]))))

    names = set(order)
    sym = {}
    for nme in order:
        i = ids[nme]
        if i in STANDARD:
            mi = MIRROR.get(i)
            sym[nme] = nme if mi is None else next((k for k, v in ids.items() if v == mi), None)
        else:
            m, sided = mirror_name(nme, names)
            sym[nme] = m if m is not None else (None if sided else nme)
    source = {nme: (nme if not nme.startswith('__umvc3_jnt_') else '') for nme in order}
    new_name = {nme: 'jnt_%d' % ids[nme] for nme in order}
    for nme in order:
        arm.data.bones[nme].name = '__tmp_' + nme
    for nme in order:
        arm.data.bones['__tmp_' + nme].name = new_name[nme]
    for index, nme in enumerate(order):
        pb = arm.pose.bones[new_name[nme]]
        pb['source_name'] = source[nme]
        pb['id'] = str(ids[nme])
        pb['symmetryName'] = new_name[sym[nme]] if sym[nme] else ''
        pb['index'] = str(index)
        pb['field03'] = '0'
    for me in meshes:
        bad = [g.name for g in me.vertex_groups if g.name not in arm.data.bones]
        for gname in bad:
            me.vertex_groups.remove(me.vertex_groups[gname])
        if bad:
            report('  %s: removed vertex groups with no bone: %s' % (me.name, ', '.join(bad[:10])))
    arm['umvc3_converted'] = True
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    lines = ['BoneName,ID,SymmetricalName,SourceName']
    for nme in sorted(order, key=lambda n: ids[n]):
        lines.append('%s,%d,%s,%s' % (new_name[nme], ids[nme], new_name[sym[nme]] if sym[nme] else '', source[nme]))
    txt = bpy.data.texts.get(arm.name + '_umvc3_bones.csv') or bpy.data.texts.new(arm.name + '_umvc3_bones.csv')
    txt.clear()
    txt.write('\n'.join(lines) + '\n')
    report('  done: %d bones, %d on vanilla joints; bone list in the text block %s'
           % (len(order), len([n for n in order if ids[n] in STANDARD]), txt.name))
    return {nme: ids[nme] for nme in order}



def _poll_ref(self, obj):
    return obj.type == 'ARMATURE' and any(b.name == 'jnt_3' for b in obj.data.bones)


class UMVC3SkeletonSlot(bpy.types.PropertyGroup):
    sid: bpy.props.IntProperty()
    bone: bpy.props.StringProperty(name='Bone')


_PRESET_ITEMS = []


def _preset_items(self, context):
    global _PRESET_ITEMS
    if _PRESET_ITEMS:
        return _PRESET_ITEMS
    items = [('AUTO', 'Detect automatically', 'Try every preset and keep the one that matches the most bones')]
    for k, p in load_presets().items():
        items.append((k, p.get('name', k), ''))
    _PRESET_ITEMS = items
    return items


class UMVC3SkeletonSettings(bpy.types.PropertyGroup):
    reference: bpy.props.PointerProperty(
        name='Reference rig', type=bpy.types.Object, poll=_poll_ref,
        description='The .mod of the character slot you are replacing, imported with the Model Importer. '
                    'Its joints give the rest frames the game animations expect')
    preset: bpy.props.EnumProperty(name='Bone names', items=_preset_items)
    keep_prefixes: bpy.props.StringProperty(
        name='Never merge', default='',
        description='Comma separated name prefixes of bones that must survive the bone limit (cloth or hair chains)')
    scale_to_ref: bpy.props.BoolProperty(
        name='Scale to the slot', default=True,
        description='Scale the model so its hips are as high as the reference rig\'s')
    use_actions: bpy.props.BoolProperty(
        name='Use the rig\'s animations', default=False,
        description='If the bone limit forces merges, merge the bones that move the mesh least in the animations '
                    'already on this armature (slower)')
    delete_reference: bpy.props.BoolProperty(
        name='Delete the reference afterwards', default=True,
        description='Remove the reference rig and its meshes once converted, so they are not exported by accident')
    show: bpy.props.BoolVectorProperty(size=4, default=(True, False, False, False))


def _slots(arm):
    return {s.sid: s for s in arm.umvc3_skeleton_map}


def _mapping(arm):
    return {s.sid: s.bone for s in arm.umvc3_skeleton_map if s.bone}


def _set_mapping(arm, mapping):
    arm.umvc3_skeleton_map.clear()
    for i in slot_ids():
        s = arm.umvc3_skeleton_map.add()
        s.sid = i
        s.bone = mapping.get(i, '')


def delete_reference(ref, keep=None):
    doomed = {ref} | {o for o in bpy.data.objects if o.type == 'MESH' and (o.parent == ref or any(
        m.type == 'ARMATURE' and m.object == ref for m in o.modifiers))}
    colls = []
    for c in ref.users_collection:
        if c == bpy.context.scene.collection or (keep is not None and keep.name in c.all_objects):
            continue
        if all(o in doomed or o.type == 'EMPTY' for o in c.all_objects):
            doomed |= set(c.all_objects)
            colls.append(c)
    for o in doomed:
        bpy.data.objects.remove(o, do_unlink=True)
    for c in colls:
        if not c.all_objects:
            bpy.data.collections.remove(c)


class SUB_OP_SkeletonDetect(bpy.types.Operator):
    bl_idname = 'sub.umvc3_skeleton_detect'
    bl_label = 'Detect Bones'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = context.active_object
        st = context.scene.umvc3_skeleton
        presets = load_presets()
        if st.preset == 'AUTO':
            key, m = detect(arm, presets)
        else:
            key = st.preset
            m = structural_fill(arm, match_preset(arm, presets[key]))
        _set_mapping(arm, m)
        arm['umvc3_skeleton_preset'] = key or ''
        req = required_ids()
        missing = [slot_label(i) for i in sorted(req) if i not in m]
        name = presets[key]['name'] if key else 'nothing'
        if missing:
            self.report({'WARNING'}, 'matched %d bones (%s); still to set: %s' % (len(m), name, ', '.join(missing)))
        else:
            self.report({'INFO'}, 'matched %d bones (%s)' % (len(m), name))
        return {'FINISHED'}


class SUB_OP_SkeletonSwapSides(bpy.types.Operator):
    bl_idname = 'sub.umvc3_skeleton_swap'
    bl_label = 'Swap Sides'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = context.active_object
        m = _mapping(arm)
        _set_mapping(arm, {MIRROR.get(i, i): n for i, n in m.items()})
        return {'FINISHED'}


class SUB_OP_SkeletonMirror(bpy.types.Operator):
    bl_idname = 'sub.umvc3_skeleton_mirror'
    bl_label = 'Fill Right From Left'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = context.active_object
        names = set(arm.data.bones.keys())
        m = _mapping(arm)
        n = 0
        for i, b in list(m.items()):
            if is_left(i) and MIRROR[i] not in m:
                o, _ = mirror_name(b, names)
                if o:
                    m[MIRROR[i]] = o
                    n += 1
        _set_mapping(arm, m)
        self.report({'INFO'}, 'filled %d right side rows' % n)
        return {'FINISHED'}


class SUB_OP_SkeletonConvert(bpy.types.Operator):
    bl_idname = 'sub.umvc3_skeleton_convert'
    bl_label = 'Convert to UMVC3 Skeleton'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm = context.active_object
        st = context.scene.umvc3_skeleton
        ref = st.reference
        presets = load_presets()
        preset = presets.get(arm.get('umvc3_skeleton_preset', ''), {})
        log = []

        def report(s):
            print(s)
            log.append(s)
        acts = [a for a in bpy.data.actions if any(f.data_path.startswith('pose.bones["') and
                f.data_path.split('"')[1] in arm.data.bones for f in getattr(a, 'fcurves', []))] if st.use_actions else None
        keepp = [x.strip() for x in st.keep_prefixes.split(',') if x.strip()] + list(preset.get('keep_prefixes', []))
        try:
            convert(arm, ref, _mapping(arm), keep_prefixes=keepp, reparent=preset_reparent(arm, preset),
                    actions=acts or None, scale_to_ref=st.scale_to_ref, report=report)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        # the list now shows the new names
        for s in arm.umvc3_skeleton_map:
            s.bone = 'jnt_%d' % s.sid if ('jnt_%d' % s.sid) in arm.data.bones else ''
        if st.delete_reference and ref is not None:
            delete_reference(ref, keep=arm)
        _mode(arm, 'OBJECT')
        self.report({'INFO'}, log[-1].strip() if log else 'converted')
        return {'FINISHED'}


class SUB_PT_CustomSkeleton(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = 'objectmode'
    bl_category = 'MT Framework'
    bl_label = 'Custom Skeleton'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        arm = context.active_object
        st = context.scene.umvc3_skeleton
        if arm is None or arm.type != 'ARMATURE':
            layout.label(text='Select your model\'s armature', icon='INFO')
            return
        if arm.get('umvc3_converted'):
            layout.label(text='%s is a UMVC3 skeleton now' % arm.name, icon='CHECKMARK')
            layout.label(text='Export it with the Model Exporter below')
            return
        col = layout.column(align=True)
        col.label(text='1. The slot you are replacing')
        col.prop(st, 'reference', text='')
        if st.reference is None:
            col.label(text='Import its .mod with the Model Importer first', icon='INFO')
        layout.separator()
        col = layout.column(align=True)
        col.label(text='2. Which bone is which')
        row = col.row(align=True)
        row.prop(st, 'preset', text='')
        row.operator(SUB_OP_SkeletonDetect.bl_idname, icon='VIEWZOOM')
        if not len(arm.umvc3_skeleton_map):
            return
        row = col.row(align=True)
        row.operator(SUB_OP_SkeletonMirror.bl_idname, icon='MOD_MIRROR')
        row.operator(SUB_OP_SkeletonSwapSides.bl_idname, icon='ARROW_LEFTRIGHT')
        slots = _slots(arm)
        req = required_ids()
        for k, sec in enumerate(SECTIONS):
            box = layout.box()
            ids = [(i, label) for s, i, label, r in SLOTS if s == sec]
            done = sum(1 for i, _ in ids for j in ((i, MIRROR[i]) if i in MIRROR else (i,)) if slots.get(j) and slots[j].bone)
            want = sum(2 if i in MIRROR else 1 for i, _ in ids)
            row = box.row()
            row.prop(st, 'show', index=k, text='%s  (%d of %d set)' % (sec, done, want),
                     icon='TRIA_DOWN' if st.show[k] else 'TRIA_RIGHT', emboss=False)
            if not st.show[k]:
                continue
            grid = box.column(align=True)
            for i, label in ids:
                for j, side in (((i, 'L'), (MIRROR[i], 'R')) if i in MIRROR else ((i, ''),)):
                    s = slots.get(j)
                    if s is None:
                        continue
                    row = grid.row(align=True)
                    row.alert = j in req and not s.bone
                    row.prop_search(s, 'bone', arm.data, 'bones', text=('%s %s' % (side, label)).strip())
        layout.separator()
        col = layout.column(align=True)
        col.label(text='3. Convert')
        col.prop(st, 'keep_prefixes')
        col.prop(st, 'scale_to_ref')
        col.prop(st, 'use_actions')
        col.prop(st, 'delete_reference')
        errors, warnings = check_mapping(arm, st.reference, _mapping(arm))
        for e in errors[:6]:
            r = col.row()
            r.alert = True
            r.label(text=e, icon='ERROR')
        for w in warnings[:4]:
            col.label(text=w, icon='INFO')
        row = col.row()
        row.scale_y = 1.5
        row.enabled = not errors
        row.operator(SUB_OP_SkeletonConvert.bl_idname, icon='ARMATURE_DATA')


CLASSES = [UMVC3SkeletonSlot, UMVC3SkeletonSettings, SUB_OP_SkeletonDetect, SUB_OP_SkeletonSwapSides,
           SUB_OP_SkeletonMirror, SUB_OP_SkeletonConvert, SUB_PT_CustomSkeleton]


def register_props():
    bpy.types.Object.umvc3_skeleton_map = bpy.props.CollectionProperty(type=UMVC3SkeletonSlot)
    bpy.types.Scene.umvc3_skeleton = bpy.props.PointerProperty(type=UMVC3SkeletonSettings)
