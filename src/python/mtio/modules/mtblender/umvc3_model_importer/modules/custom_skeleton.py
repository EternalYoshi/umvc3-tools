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
    ('Body', 4, 'Spine (lowest)', False),
    ('Body', 5, 'Chest (clavicles hang off it)', True),
    ('Body', 6, 'Neck', False),
    ('Body', 7, 'Head', True),
    ('Body', 8, 'Clavicle', False),
    ('Body', 9, 'Upper arm', True),
    ('Body', 10, 'Forearm', True),
    ('Body', 11, 'Hand', True),
    ('Body', 16, 'Thigh', True),
    ('Body', 17, 'Shin', False),
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


# ----------------------------------------------------------------------------- structure

def structural_detect(arm):
    """Work out which bone is which from the rig's shape alone, no names.
    Returns ({id: bone}, [notes]). Uses bone head positions in world space and the
    hierarchy; bones with no skin weight anywhere below them are ignored."""
    bones = arm.data.bones
    names = list(bones.keys())
    notes = []
    H = {b.name: arm.matrix_world @ b.head_local for b in bones}
    T = {b.name: arm.matrix_world @ b.tail_local for b in bones}
    parent = {b.name: (b.parent.name if b.parent else None) for b in bones}
    kids = {n: [] for n in names}
    for n, p in parent.items():
        if p is not None:
            kids[p].append(n)
    total, verts = bone_weights(skinned_meshes(arm), set(names))
    sub = {}

    def subw(n):
        if n not in sub:
            sub[n] = verts.get(n, 0) + sum(subw(c) for c in kids[n])
        return sub[n]
    live = {n for n in names if subw(n) > 0}
    if len(live) < 8:
        return {}, ['too few weighted bones to read the skeleton']
    pts = [H[n] for n in live]
    ext = max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3))
    tol = 0.02 * ext

    # the mirror plane: the world axis that pairs up the most bones
    best = None
    for ax in range(3):
        c = (max(p[ax] for p in pts) + min(p[ax] for p in pts)) / 2
        score = 0
        for p in pts:
            if abs(p[ax] - c) < tol:
                continue
            q = p.copy()
            q[ax] = 2 * c - p[ax]
            if any((q - o).length < tol for o in pts):
                score += 1
        if best is None or score > best[0]:
            best = (score, ax, c)
    _, ax, c = best

    def off(n):
        return H[n][ax] - c

    def mirrored(p):
        q = p.copy()
        q[ax] = 2 * c - p[ax]
        return q
    # a side bone has a partner at its mirrored position; clavicles can start almost on
    # the centre line, so distance from the plane alone can't tell
    sided = set()
    for n in live:
        if abs(off(n)) < 0.1 * tol:
            continue
        q = mirrored(H[n])
        if any(m_ != n and (H[m_] - q).length < tol and off(m_) * off(n) < 0 for m_ in live):
            sided.add(n)

    def centre(n):
        if n in sided:
            return False
        if abs(off(n)) < tol * 1.5:
            return True
        # one sided bones (a holster, a single shoulder pad) follow their parent
        return parent[n] is None or centre(parent[n])
    depth = {}

    def dep(n):
        if n not in depth:
            depth[n] = 0 if parent[n] is None else dep(parent[n]) + 1
        return depth[n]
    desc = {}

    def below(n):
        if n not in desc:
            out = [n]
            for k in kids[n]:
                if k in live:
                    out += below(k)
            desc[n] = out
        return desc[n]

    def reach(frm, n):
        return max((H[d] - H[frm]).length for d in below(n) + [n])

    def main_chain(n):
        chain = [n]
        while True:
            cs = [k for k in kids[chain[-1]] if k in live]
            if not cs:
                return chain
            chain.append(max(cs, key=lambda k: (reach(chain[-1], k), subw(k))))

    # limb roots: side bones hanging off a centre bone; two per side, longest first
    roots = [n for n in live if not centre(n) and (parent[n] is None or centre(parent[n]))]
    sides = {}
    for sgn in (1, -1):
        rs = sorted([n for n in roots if off(n) * sgn > 0], key=lambda n: -max(
            (H[d] - H[n]).length for d in below(n)) - (T[n] - H[n]).length)
        rs = [n for n in rs if max((H[d] - H[n]).length for d in below(n) + [n]) + (T[n] - H[n]).length > 0.15 * ext]
        if len(rs) < 2:
            return {}, ['couldn\'t find two limbs on each side of the rig']
        a, b = rs[0], rs[1]
        pa, pb = dep(parent[a]) if parent[a] else -1, dep(parent[b]) if parent[b] else -1
        if pa == pb:        # same attach depth: the arm ends in a hand that branches into fingers
            leaves = lambda n: sum(1 for d in below(n) if not [k for k in kids[d] if k in live])
            leg, armr = (a, b) if leaves(a) < leaves(b) else (b, a)
        else:
            leg, armr = (a, b) if pa < pb else (b, a)
        sides[sgn] = dict(leg=leg, arm=armr)

    legs = [sides[1]['leg'], sides[-1]['leg']]
    arms = [sides[1]['arm'], sides[-1]['arm']]
    up = ((H[arms[0]] + H[arms[1]]) / 2 - (H[legs[0]] + H[legs[1]]) / 2).normalized()

    def height(n):
        return H[n].dot(up)
    ground = min(min(H[d].dot(up), T[d].dot(up)) for l in legs for d in below(l))

    def lca(ns):
        paths = []
        for n in ns:
            p, x = [], n
            while x is not None:
                p.append(x)
                x = parent[x]
            paths.append(p[::-1])
        out = None
        for group in zip(*paths):
            if all(g == group[0] for g in group):
                out = group[0]
            else:
                break
        return out

    m = {}
    out = {}
    for sgn in (1, -1):
        s = sides[sgn]
        # ---- leg: thigh, shin, foot, toe
        L = main_chain(s['leg'])
        hip_h = height(L[0]) - ground
        fi = next((i for i in range(1, len(L)) if height(L[i]) - ground < 0.25 * hip_h), None)
        leg = dict(thigh=L[0])
        if fi is not None:
            leg['foot'] = L[fi]
            if fi + 1 < len(L):
                leg['toe'] = L[fi + 1]
            mid = [L[i] for i in range(1, fi)]
            span = H[L[fi]] - H[L[0]]
            best = None
            for n in mid:
                r = (H[n] - H[L[0]]).dot(span) / max(span.length_squared, 1e-9)
                if 0.25 < r < 0.75 and (best is None or abs(r - 0.5) < best[0]):
                    best = (abs(r - 0.5), n)
            if best:
                leg['shin'] = best[1]
        # ---- arm: clavicle, upper arm, forearm, hand
        A = main_chain(s['arm'])
        hand = None
        for i in range(2, len(A)):
            n = A[i]
            cs = [k for k in kids[n] if k in live]
            d0 = (H[n] - H[A[0]]).length
            if len(cs) >= 2 and all(reach(n, k) < 0.6 * d0 for k in cs):
                hand = i
                break
        if hand is None:
            hand = min(len(A) - 1, 3 if len(A) > 4 else 2)
            notes.append('no fingers found on one hand; guessed the hand from the arm length')
        pre = [A[0]]
        for n in A[1:hand]:
            if (H[n] - H[pre[-1]]).length > tol:
                pre.append(n)
        wrist = H[A[hand]]
        armd = dict(hand=A[hand])
        if len(pre) >= 3 and abs(off(pre[0])) < 0.35 * abs(wrist[ax] - c):
            armd['clavicle'] = pre[0]
            pre = pre[1:]
        armd['upper'] = pre[0]
        span = wrist - H[pre[0]]
        best = None
        for n in pre[1:]:
            r = (H[n] - H[pre[0]]).dot(span) / max(span.length_squared, 1e-9)
            if 0.25 < r < 0.8 and (best is None or abs(r - 0.5) < best[0]):
                best = (abs(r - 0.5), n)
        if best:
            armd['fore'] = best[1]
        out[sgn] = dict(leg=leg, arm=armd)

    # facing: toes point forward; left = up x forward
    toes = [out[s]['leg'].get('toe') for s in (1, -1)]
    feet = [out[s]['leg'].get('foot') for s in (1, -1)]
    fwd = None
    if all(toes) and all(feet):
        f = sum(((H[t] - H[f]) for t, f in zip(toes, feet)), Vector())
        f = f - up * f.dot(up)
        if f.length > 1e-6:
            fwd = f.normalized()
    if fwd is None:
        side = Vector((0, 0, 0))
        side[ax] = 1
        fwd = up.cross(side).normalized() * -1          # Blender's habit: facing -Y with left at +X
        notes.append('no toes, so the facing is a guess; check Left and Right')
    left = up.cross(fwd)
    lsign = 1 if left[ax] > 0 else -1

    for sgn in (1, -1):
        is_l = sgn == lsign
        o = out[sgn]
        base = {'thigh': 16, 'shin': 17, 'foot': 18, 'toe': 19, 'clavicle': 8, 'upper': 9, 'fore': 10, 'hand': 11}
        for k, v in list(o['leg'].items()) + list(o['arm'].items()):
            i = base[k] if is_l else MIRROR[base[k]]
            m[i] = v
        # fingers
        hand = o['arm']['hand']
        roots = []
        for k in kids[hand]:
            if k not in live:
                continue
            cs = [x for x in kids[k] if x in live]
            if len(cs) >= 2 and (H[k] - H[hand]).length < 0.5 * max(reach(hand, x) for x in cs):
                roots += cs          # a palm helper with fingers under it
            else:
                roots.append(k)
        def length(r):
            return max(max((H[d] - H[hand]).length, (T[d] - H[hand]).length) for d in below(r))
        if roots:
            longest = max(length(r) for r in roots)
            roots = [r for r in roots if length(r) >= 0.55 * longest]
        if roots:
            fo = {r: (H[r] - H[hand]).dot(fwd) for r in roots}
            along = (H[hand] - H[o['arm'].get('fore', hand)])
            along = along.normalized() if along.length > 1e-6 else fwd
            thumb = max(roots, key=lambda r: fo[r] - 0.5 * abs((H[r] - H[hand]).dot(along)))
            rest = sorted([r for r in roots if r != thumb], key=lambda r: -fo[r])
            order = {1: [53], 2: [53, 56], 3: [53, 56, 63]}.get(len(rest), [53, 56, 59, 63])
            chains = [(thumb, 50)] + list(zip(rest, order))
            for r, b in chains:
                ch = main_chain(r)
                if b != 50 and len(ch) >= 4:
                    meta, ch = ch[0], ch[1:]
                    if b == 63:
                        m[62 if is_l else 82] = meta
                for j, n in enumerate(ch[:3]):
                    i = b + j
                    m[i if is_l else MIRROR[i]] = n

    # spine, neck, head
    chest = lca(arms)
    pelvis = lca(legs + [chest]) if chest else None
    if chest is None or pelvis is None or chest == pelvis:
        notes.append('couldn\'t trace the spine between hips and chest')
    else:
        m[3] = pelvis
        m[5] = chest
        path, x = [], parent[chest]
        while x is not None and x != pelvis:
            path.append(x)
            x = parent[x]
        if path:
            m[4] = path[-1]
        q = []
        x = chest
        while True:
            cs = [k for k in kids[x] if k in live and centre(k) and height(k) > height(chest) - tol
                  and not any(a in below(k) for a in arms)]
            if not cs:
                break
            x = max(cs, key=lambda k: (reach(x, k), subw(k)))
            q.append(x)
        if q:
            # the head carries most of what hangs above the chest (hair and face bones
            # carry less), and it is usually where the face bones branch off
            cand = [n for n in q if subw(n) >= 0.5 * subw(q[0])]
            branching = [n for n in cand[1:] if len([k for k in kids[n] if k in live]) >= 2]
            head = branching[0] if branching else cand[-1]
            hi = q.index(head)
            if hi > 0:
                m[6] = q[hi - 1]
            m[7] = head
            # eyes: a mirrored pair right under the head, in front of it and above it
            pair = [k for k in kids[head] if k in live and not centre(k)
                    and (H[k] - H[head]).dot(fwd) > 0 and (H[k] - H[head]).dot(up) > 0]
            l_eye = [k for k in pair if (off(k) > 0) == (lsign > 0)]
            r_eye = [k for k in pair if (off(k) > 0) != (lsign > 0)]
            if len(l_eye) == 1 and len(r_eye) == 1:
                m[90], m[99] = l_eye[0], r_eye[0]
    used = {}
    for i, n in list(m.items()):
        if n in used:
            del m[i]
        else:
            used[n] = i
    return m, notes


def detect(arm, presets=None, preset=None):
    """(preset key or None, {id: bone}, notes). The rig's shape decides by default; bone
    names from a matching preset fill what the shape can't tell (face, twist helpers).
    When a preset knows most of the body by name, its names win for those rows.
    preset: None tries them all, 'NONE' ignores names."""
    presets = presets or load_presets()
    shape, notes = structural_detect(arm)
    key, named = None, {}
    if preset != 'NONE':
        for k, p in (presets.items() if preset in (None, 'AUTO') else [(preset, presets[preset])]):
            mm = match_preset(arm, p)
            if len(mm) > len(named):
                key, named = k, mm
    body = [i for i in slot_ids() if i < 24]
    trust_names = sum(1 for i in body if i in named) >= 10
    first, second = (named, shape) if trust_names else (shape, named)
    m = dict(first)
    for i, n in second.items():
        if i not in m and n not in m.values():
            m[i] = n
    if not trust_names:
        m = structural_fill(arm, m)
    return key, m, notes


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
    if 4 not in mapping and 5 in mapping:
        warnings.append('no lower spine bone: one gets added between pelvis and chest')
    for shin, label in ((17, 'left'), (21, 'right')):
        if shin not in mapping and mapping.get(shin + 1):
            warnings.append('%s: no shin bone, the knee joint gets added but nothing below it bends' % label)
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
            scale_to_ref=True, report=print, forced=None):
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
    # extra bones with an id from a .csv: kept whatever their weights, never merged
    forced = {b: (int(v[0]), (v[1] if len(v) > 1 else '') or '') for b, v in (forced or {}).items()
              if b in arm.data.bones and b not in std}
    fids = [v[0] for v in forced.values()]
    clash = sorted({i for i in fids if fids.count(i) > 1} | {i for i in fids if i in mapping})
    if clash:
        raise RuntimeError('the .csv ids %s are used twice (or by a mapped row)' % ', '.join(map(str, clash)))
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
    protected = set()
    for nme in forced:
        x = bones[nme]
        while x is not None and x.name not in protected:
            protected.add(x.name)
            x = x.parent
    protected -= set(above_pelvis) | mapped
    dead = [bb.name for bb in bones if bb.name not in keep and bb.name not in protected and bb.name not in above_pelvis
            and all(verts[x] == 0 for x in subtree(bb.name))]
    dead_set = set(dead)
    alive = {bb.name for bb in bones if bb.name not in dead_set and bb.name not in above_pelvis}
    pool = [i for i in range(1, MAX_ID + 1) if i not in STANDARD]
    bad = sorted(i for i in fids if i in dummies)
    if bad:
        raise RuntimeError('the .csv gives ids %s to extra bones, but the rig needs them as vanilla joints'
                           % ', '.join(map(str, bad)))
    limit = len(mapping) + len(dummies) + len(pool) + len([i for i in fids if i in STANDARD])
    count = len(alive) + len(dummies)

    newparent = {bb.name: (bb.parent.name if bb.parent else None) for bb in bones}
    for c, par in reparent.items():
        if c in alive:
            newparent[c] = par

    def candidate(nme):
        return (nme in alive and nme not in keep and nme not in protected and nme not in reparent.values()
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
    for nme, (i, _) in forced.items():
        if nme in order:
            ids[nme] = i
    ref_used = set(frames)
    free_first = [i for i in pool if i not in ref_used and i not in fids] + [i for i in pool if i in ref_used and i not in fids]
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
    # symmetry from the .csv: a bone name or jnt_N; the partner points back
    by_id = {v: k for k, v in ids.items()}
    for nme, (i, s) in forced.items():
        if nme not in ids or not s:
            continue
        t = s if s in names else by_id.get(_id_of(s))
        if t is None:
            report('  note: %s: symmetrical opposite %s is not on the rig, left as is' % (nme, s))
            continue
        sym[nme] = t
        if t not in forced or not forced[t][1]:
            sym[t] = nme
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



# ----------------------------------------------------------------------------- csv

def _id_of(text):
    m = re.match(r'\s*(?:jnt_)?(\d+)\s*$', text or '')
    return int(m.group(1)) if m else None


def read_bone_csv(path, arm):
    """A bone list as .csv: bone name, UMVC3 id (9 or jnt_9), optionally the symmetrical
    opposite. A header row is optional; with one, BoneName/SourceName/Name, ID and any
    Symmetrical/Mirror column are recognised, so the converter's own bone list and the
    3ds Max MT attribute CSV both load. Returns ({id: bone} for the shared joints,
    {bone: [id, symmetry]} for the rest, notes)."""
    import csv
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = [r for r in csv.reader(f) if r and any(x.strip() for x in r)]
    if not rows:
        raise RuntimeError('the .csv is empty')
    names = set(arm.data.bones.keys())
    first = [x.strip() for x in rows[0]]
    if len(first) > 1 and _id_of(first[1]) is None:
        hdr = [x.lower().replace(' ', '').replace('_', '') for x in first]
        rows = rows[1:]
        bone_cols = [i for i, h in enumerate(hdr) if h in (
            'sourcename', 'source', 'sfvname', 'originalname', 'original', 'bonename', 'bone', 'name', 'node')]
        id_col = next((i for i, h in enumerate(hdr) if h in ('id', 'jnt', 'jointid', 'jntid', 'boneid', 'umvc3id')), 1)
        sym_col = next((i for i, h in enumerate(hdr) if 'sym' in h or 'mirror' in h or 'opposite' in h), None)
        bone_cols = bone_cols or [0]
    else:
        bone_cols, id_col, sym_col = [0], 1, (2 if len(first) > 2 else None)
    mapping, forced, notes = {}, {}, []
    for r in rows:
        cells = [x.strip() for x in r]
        bone = next((cells[c] for c in bone_cols if c < len(cells) and cells[c] in names), None)
        i = _id_of(cells[id_col]) if id_col < len(cells) else None
        if bone is None:
            notes.append('no bone named %s' % (cells[bone_cols[0]] if bone_cols[0] < len(cells) else '?'))
            continue
        if i is None or not (1 <= i <= MAX_ID):
            notes.append('%s: id %s is not 1-%d' % (bone, cells[id_col] if id_col < len(cells) else '?', MAX_ID))
            continue
        sym = cells[sym_col] if sym_col is not None and sym_col < len(cells) else ''
        if i in STANDARD:
            mapping[i] = bone
        else:
            forced[bone] = [i, sym]
    return mapping, forced, notes


def write_bone_csv(path, arm):
    """the current rows and fixed ids as BoneName,ID,SymmetricalName"""
    m = _mapping(arm)
    forced = _forced(arm)
    lines = ['BoneName,ID,SymmetricalName']
    for i in sorted(m):
        mi = MIRROR.get(i, i)
        lines.append('%s,%d,%s' % (m[i], i, ('jnt_%d' % mi) if (mi == i or mi in m) else ''))
    for b, (i, sym) in sorted(forced.items(), key=lambda kv: kv[1][0]):
        lines.append('%s,%d,%s' % (b, i, sym))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\n'.join(lines) + '\n')
    return len(lines) - 1


def _forced(arm):
    try:
        return {k: list(v) for k, v in json.loads(arm.get('umvc3_forced', '{}') or '{}').items()}
    except Exception:
        return {}


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
    items = [('AUTO', 'Shape, then any matching names', 'Read the rig from its shape; bone names from a matching preset fill the rest'),
             ('NONE', 'Shape only', 'Ignore bone names completely')]
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
    show: bpy.props.BoolVectorProperty(size=5, default=(True, False, False, False, False))


def _slots(arm):
    return {s.sid: s for s in arm.umvc3_skeleton_map}


def _mapping(arm):
    return {s.sid: s.bone for s in arm.umvc3_skeleton_map if s.bone}


def _set_mapping(arm, mapping):
    arm.umvc3_skeleton_map.clear()
    for i in slot_ids() + sorted(set(mapping) - set(slot_ids())):
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
        key, m, notes = detect(arm, presets, st.preset)
        _set_mapping(arm, m)
        arm['umvc3_skeleton_preset'] = key or ''
        req = required_ids()
        missing = [slot_label(i) for i in sorted(req) if i not in m]
        how = 'from the rig\'s shape' + (' and %s names' % presets[key]['name'].split(' (')[0] if key else '')
        msg = 'found %d bones %s' % (len(m), how)
        for n in notes:
            print('Detect Bones: ' + n)
        if missing:
            self.report({'WARNING'}, '%s; still to set: %s' % (msg, ', '.join(missing)))
        elif notes:
            self.report({'WARNING'}, '%s; %s' % (msg, notes[0]))
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


from bpy_extras.io_utils import ImportHelper, ExportHelper


class SUB_OP_SkeletonLoadCSV(bpy.types.Operator, ImportHelper):
    """Fill the rows from a .csv bone list (bone name, UMVC3 id, symmetrical opposite). Bones given an id outside the shared joints keep that id and symmetry when converted"""
    bl_idname = 'sub.umvc3_skeleton_load_csv'
    bl_label = 'Load CSV'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.csv'
    filter_glob: bpy.props.StringProperty(default='*.csv', options={'HIDDEN'})
    replace: bpy.props.BoolProperty(name='Replace the rows', default=True,
                                    description='Clear the current rows first; off adds to them')

    def execute(self, context):
        arm = context.active_object
        try:
            m, forced, notes = read_bone_csv(self.filepath, arm)
        except Exception as e:
            self.report({'ERROR'}, 'could not read the .csv: %s' % e)
            return {'CANCELLED'}
        cur = {} if self.replace else _mapping(arm)
        cur = {i: n for i, n in cur.items() if n not in m.values() and n not in forced}
        cur.update(m)
        _set_mapping(arm, cur)
        old = {} if self.replace else _forced(arm)
        old.update(forced)
        arm['umvc3_forced'] = json.dumps(old)
        for n in notes:
            print('Load CSV: ' + n)
        msg = '%d shared joints and %d extra bones from the .csv' % (len(m), len(forced))
        self.report({'WARNING'} if notes else {'INFO'}, msg + ('; %d rows skipped (see the console)' % len(notes) if notes else ''))
        return {'FINISHED'}


class SUB_OP_SkeletonSaveCSV(bpy.types.Operator, ExportHelper):
    """Save the rows (and any fixed ids) as a .csv bone list, to reuse on a rig with the same bones"""
    bl_idname = 'sub.umvc3_skeleton_save_csv'
    bl_label = 'Save CSV'
    filename_ext = '.csv'
    filter_glob: bpy.props.StringProperty(default='*.csv', options={'HIDDEN'})

    def execute(self, context):
        n = write_bone_csv(self.filepath, context.active_object)
        self.report({'INFO'}, 'saved %d bones' % n)
        return {'FINISHED'}


class SUB_OP_SkeletonClearFixed(bpy.types.Operator):
    """Forget the ids the .csv gave to extra bones; they get free ids when converted"""
    bl_idname = 'sub.umvc3_skeleton_clear_fixed'
    bl_label = 'Clear Fixed IDs'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.active_object['umvc3_forced'] = '{}'
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
            convert(arm, ref, _mapping(arm), keep_prefixes=keepp, reparent=preset_reparent(arm, preset), forced=_forced(arm),
                    actions=acts or None, scale_to_ref=st.scale_to_ref, report=report)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        # the list now shows the new names
        for s in arm.umvc3_skeleton_map:
            s.bone = 'jnt_%d' % s.sid if ('jnt_%d' % s.sid) in arm.data.bones else ''
        # the reference has done its job; gone, it can't be exported by mistake
        if ref is not None:
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
        row = col.row()
        row.scale_y = 1.2
        row.operator(SUB_OP_SkeletonDetect.bl_idname, icon='VIEWZOOM')
        row = col.row(align=True)
        row.operator(SUB_OP_SkeletonLoadCSV.bl_idname, icon='IMPORT')
        row.operator(SUB_OP_SkeletonSaveCSV.bl_idname, icon='EXPORT')
        fixed = _forced(arm)
        if fixed:
            row = col.row(align=True)
            row.label(text='%d extra bones keep their .csv ids' % len(fixed), icon='LINKED')
            row.operator(SUB_OP_SkeletonClearFixed.bl_idname, text='', icon='X')
        if not len(arm.umvc3_skeleton_map):
            return
        row = col.row(align=True)
        row.operator(SUB_OP_SkeletonMirror.bl_idname, icon='MOD_MIRROR')
        row.operator(SUB_OP_SkeletonSwapSides.bl_idname, icon='ARROW_LEFTRIGHT')
        slots = _slots(arm)
        req = required_ids()

        def section(parent, sec, k):
            box = parent.box()
            ids = [(i, label) for s_, i, label, r in SLOTS if s_ == sec]
            done = sum(1 for i, _ in ids for j in ((i, MIRROR[i]) if i in MIRROR else (i,)) if slots.get(j) and slots[j].bone)
            want = sum(2 if i in MIRROR else 1 for i, _ in ids)
            missing = any(j in req and not (slots.get(j) and slots[j].bone)
                          for i, _ in ids for j in ((i, MIRROR[i]) if i in MIRROR else (i,)))
            row = box.row()
            row.alert = missing
            row.prop(st, 'show', index=k, text='%s  (%d of %d set)' % (sec, done, want),
                     icon='TRIA_DOWN' if st.show[k] else 'TRIA_RIGHT', emboss=False)
            if not st.show[k]:
                return
            grid = box.column(align=True)
            for i, label in ids:
                for j, side in (((i, 'L'), (MIRROR[i], 'R')) if i in MIRROR else ((i, ''),)):
                    s_ = slots.get(j)
                    if s_ is None:
                        continue
                    row = grid.row(align=True)
                    row.alert = j in req and not s_.bone
                    row.prop_search(s_, 'bone', arm.data, 'bones', text=('%s %s' % (side, label)).strip())
        section(layout, 'Body', 0)
        section(layout, 'Fingers', 1)

        layout.separator()
        col = layout.column(align=True)
        col.label(text='3. Convert')
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

        # everything a first conversion doesn't need
        box = layout.box()
        box.prop(st, 'show', index=3, text='Advanced', icon='TRIA_DOWN' if st.show[3] else 'TRIA_RIGHT', emboss=False)
        if st.show[3]:
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(st, 'preset', text='Names')
            col.prop(st, 'scale_to_ref')
            col.prop(st, 'keep_prefixes')
            col.prop(st, 'use_actions')
            box.label(text='Optional joints (twist helpers, face):')
            section(box, 'Helpers', 2)
            section(box, 'Face', 4)


CLASSES = [UMVC3SkeletonSlot, UMVC3SkeletonSettings, SUB_OP_SkeletonDetect, SUB_OP_SkeletonLoadCSV,
           SUB_OP_SkeletonSaveCSV, SUB_OP_SkeletonClearFixed, SUB_OP_SkeletonSwapSides,
           SUB_OP_SkeletonMirror, SUB_OP_SkeletonConvert, SUB_PT_CustomSkeleton]


def register_props():
    bpy.types.Object.umvc3_skeleton_map = bpy.props.CollectionProperty(type=UMVC3SkeletonSlot)
    bpy.types.Scene.umvc3_skeleton = bpy.props.PointerProperty(type=UMVC3SkeletonSettings)
