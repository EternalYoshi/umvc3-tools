"""
Camera importer for the UMVC3 Model Importer addon.
"""

import math
import os
import struct

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper, ImportHelper

LMCM_MAGIC = b"LMCM"
M3C_MAGIC = b"M3C1"
ENTRY_SIZE = 0x40
M3C_HEADER = 0x40
BYTES_PER_FRAME = 48

# game (x, y, z) -> blender (x, -z, y), a +90 degree turn about X
Q_ZUP = mathutils.Quaternion((math.cos(math.radians(45)),
                              math.sin(math.radians(45)), 0.0, 0.0))


# ----------------------------------------------------------------- file io

class Cam(object):
    __slots__ = ("slot", "frames", "floats", "source", "eye", "target",
                 "rot", "fov", "roll")


def _tracks(data, base, n):
    o = base
    eye = [struct.unpack_from("<3f", data, o + 12 * j) for j in range(n)]
    o += 12 * n
    tgt = [struct.unpack_from("<3f", data, o + 12 * j) for j in range(n)]
    o += 12 * n
    rot = [struct.unpack_from("<4f", data, o + 16 * j) for j in range(n)]
    o += 16 * n
    fov = [struct.unpack_from("<f", data, o + 4 * j)[0] for j in range(n)]
    o += 4 * n
    rol = [struct.unpack_from("<f", data, o + 4 * j)[0] for j in range(n)]
    return eye, tgt, rot, fov, rol


def read_m3c(path):
    d = open(path, "rb").read()
    if d[:4] != M3C_MAGIC:
        raise ValueError("not an M3C file")
    c = Cam()
    c.slot = struct.unpack_from("<H", d, 6)[0]
    c.frames = struct.unpack_from("<I", d, 8)[0]
    c.floats = list(struct.unpack_from("<5f", d, 0x10))
    c.source = d[0x24:0x40].split(b"\0")[0].decode("utf-8", "replace")
    if len(d) != M3C_HEADER + BYTES_PER_FRAME * c.frames:
        raise ValueError("M3C size does not match its frame count")
    c.eye, c.target, c.rot, c.fov, c.roll = _tracks(d, M3C_HEADER, c.frames)
    return c


def read_lmcm(path):
    """Every populated slot."""
    d = open(path, "rb").read()
    if d[:4] != LMCM_MAGIC:
        raise ValueError("not an LMCM file")
    slot_count = struct.unpack_from("<h", d, 6)[0]
    table = struct.unpack_from("<%dq" % slot_count, d, 8)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    for slot, off in enumerate(table):
        if off <= 0:
            continue
        c = Cam()
        c.slot = slot
        c.source = stem
        c.frames = struct.unpack_from("<i", d, off)[0]
        c.floats = list(struct.unpack_from("<5f", d, off + 4))
        ptr = struct.unpack_from("<5q", d, off + 24)
        n = c.frames
        c.eye = [struct.unpack_from("<3f", d, ptr[0] + 12 * j) for j in range(n)]
        c.target = [struct.unpack_from("<3f", d, ptr[1] + 12 * j) for j in range(n)]
        c.rot = [struct.unpack_from("<4f", d, ptr[2] + 16 * j) for j in range(n)]
        c.fov = [struct.unpack_from("<f", d, ptr[3] + 4 * j)[0] for j in range(n)]
        c.roll = [struct.unpack_from("<f", d, ptr[4] + 4 * j)[0] for j in range(n)]
        out.append(c)
    return out


def write_m3c(path, c):
    hdr = bytearray(M3C_HEADER)
    hdr[0:4] = M3C_MAGIC
    struct.pack_into("<HH", hdr, 4, 1, c.slot)
    struct.pack_into("<II", hdr, 8, c.frames, 0)
    struct.pack_into("<5f", hdr, 0x10, *c.floats)
    s = c.source.encode("utf-8")[:27]
    hdr[0x24:0x24 + len(s)] = s
    body = bytearray()
    for v in c.eye:
        body += struct.pack("<3f", *v)
    for v in c.target:
        body += struct.pack("<3f", *v)
    for v in c.rot:
        body += struct.pack("<4f", *v)
    for v in c.fov:
        body += struct.pack("<f", v)
    for v in c.roll:
        body += struct.pack("<f", v)
    open(path, "wb").write(bytes(hdr) + bytes(body))


def slot_label(i):
    if i < 10:
        return "Hyper %d" % i
    if i < 20:
        return "THC %d" % (i - 10)
    if i < 30:
        return "Win %d" % (i - 20)
    if i < 50:
        return "Etc %d" % (i - 30)
    if i < 60:
        return "Cinematic %d" % (i - 50)
    return "Slot %d" % i


# ----------------------------------------------------------------- helpers

def iter_fcurves(holder):
    ad = getattr(holder, "animation_data", None)
    action = getattr(ad, "action", None)
    if action is None:
        return
    try:
        legacy = list(action.fcurves)
    except (AttributeError, RuntimeError):
        legacy = []
    if legacy:
        for fc in legacy:
            yield fc
        return
    slot = getattr(ad, "action_slot", None)
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            bags = []
            if slot is not None and hasattr(strip, "channelbag"):
                try:
                    bag = strip.channelbag(slot)
                    if bag is not None:
                        bags.append(bag)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            if not bags:
                bags = list(getattr(strip, "channelbags", ()))
            for bag in bags:
                for fc in getattr(bag, "fcurves", ()):
                    yield fc


def fix_hemisphere(quats):
    out = [mathutils.Quaternion(quats[0])]
    for q in quats[1:]:
        q = mathutils.Quaternion(q)
        if q.dot(out[-1]) < 0.0:
            q.negate()
        out.append(q)
    return out


def to_loc(v, scale, zup):
    if zup:
        return mathutils.Vector((v[0] * scale, -v[2] * scale, v[1] * scale))
    return mathutils.Vector((v[0] * scale, v[1] * scale, v[2] * scale))


def to_quat(q, zup):
    bq = mathutils.Quaternion((q[3], q[0], q[1], q[2]))
    return (Q_ZUP @ bq) if zup else bq


# ----------------------------------------------------------------- build

def build_camera(context, cam, scale, zup, fov_axis, make_target,
                 extend_range, name_prefix=""):
    n = cam.frames
    if n <= 0:
        raise ValueError("camera has no frames")

    name = "%s%s_%s" % (name_prefix, cam.source or "cam",
                        slot_label(cam.slot).replace(" ", ""))

    data = bpy.data.cameras.new(name)
    data.sensor_fit = "VERTICAL" if fov_axis == "VERT" else "HORIZONTAL"
    data.clip_start = max(0.001, 0.5 * scale)
    data.clip_end = 100000.0 * scale
    obj = bpy.data.objects.new(name, data)
    context.collection.objects.link(obj)
    obj.rotation_mode = "QUATERNION"

    tgt = None
    if make_target:
        tgt = bpy.data.objects.new(name + "_target", None)
        tgt.empty_display_type = "PLAIN_AXES"
        tgt.empty_display_size = max(0.1, 20.0 * scale)
        context.collection.objects.link(tgt)

    quats = fix_hemisphere([to_quat(q, zup) for q in cam.rot])

    for j in range(n):
        obj.location = to_loc(cam.eye[j], scale, zup)
        obj.rotation_quaternion = quats[j]
        obj.keyframe_insert("location", frame=j)
        obj.keyframe_insert("rotation_quaternion", frame=j)

        if fov_axis == "VERT":
            data.angle_y = math.radians(cam.fov[j])
        else:
            data.angle_x = math.radians(cam.fov[j])
        data.keyframe_insert("lens", frame=j)

        if tgt is not None:
            tgt.location = to_loc(cam.target[j], scale, zup)
            tgt.keyframe_insert("location", frame=j)

    # every frame is an explicit sample, so stop Blender re-easing between them
    holders = [obj, data] + ([tgt] if tgt else [])
    for holder in holders:
        for fc in iter_fcurves(holder):
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
            fc.update()

    if extend_range:
        scene = context.scene
        scene.frame_start = min(scene.frame_start, 0)
        scene.frame_end = max(scene.frame_end, n - 1)

    obj["m3c_slot"] = cam.slot
    obj["m3c_source"] = cam.source
    obj["m3c_floats"] = list(cam.floats)
    obj["m3c_scale"] = scale
    obj["m3c_zup"] = bool(zup)
    if tgt is not None:
        obj["m3c_target"] = tgt.name
    return obj


# ----------------------------------------------------------------- ui

class SUB_PT_Cam_Import(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MT Framework"
    bl_label = "Camera Importer"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode in ("POSE", "OBJECT")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        row = layout.row(align=True)
        row.operator(SUB_OP_cam_import.bl_idname, icon="IMPORT",
                     text="Import Marvel 3 Camera (.lmcm / .m3c)")
        layout.separator()
        obj = context.active_object
        row = layout.row(align=True)
        if obj is not None and obj.type == "CAMERA":
            row.operator(SUB_OP_cam_export.bl_idname, icon="EXPORT",
                         text="Export Selected Camera (.m3c)")
        else:
            row.label(text="Select a camera to export.")


class SUB_OP_cam_import(Operator, ImportHelper):
    bl_idname = "sub.import_cam"
    bl_label = "Import Camera"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".m3c"
    filter_glob: StringProperty(default="*.lmcm;*.m3c", options={"HIDDEN"})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    all_slots: BoolProperty(
        name="Import every camera in the file",
        description="Only applies to .lmcm.",
        default=False,
    )
    slot: IntProperty(
        name="Slot",
        description="Which slot to pull out of a .lmcm."
                    "0-9 hyper, 10-19 THC, 20 win, 50 cinematic",
        default=0, min=0, max=255,
    )
    space: EnumProperty(
        name="Space",
        items=[("GAME", "Game Space",
                "Matches the model importer, so the camera lines up with an "
                "imported model and animation. Use this one"),
               ("ZUP", "Blender Z Up",
                "Rotates into Blender's usual orientation."
                "Will not line up with an imported model")],
        default="GAME",
    )
    scale: FloatProperty(
        name="Scale",
        description="Leave this at 1.0 when "
                    "matching a model",
        default=1.0, min=0.0001, max=1000.0,
    )
    fov_axis: EnumProperty(
        name="FOV axis",
        items=[("VERT", "Vertical", "Treat the stored FOV as vertical"),
               ("HORIZ", "Horizontal", "Treat the stored FOV as horizontal")],
        default="VERT",
        description="Testing purposes"
                    "If the framing looks off, try horizontal",
    )
    make_target: BoolProperty(
        name="Create target empty",
        description="Animate an empty on the look-at track so you can see what "
                    "the shot is aiming at",
        default=True,
    )
    extend_range: BoolProperty(
        name="Extend scene frame range",
        description="Grow the range to fit, rather than overwrite it, so an "
                    "already imported animation keeps its range",
        default=True,
    )
    set_fps: BoolProperty(name="Set scene to 60 fps", default=False)
    look_through: BoolProperty(
        name="Look through it after import", default=False)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        col = layout.column()
        col.prop(self, "all_slots")
        sub = col.row()
        sub.enabled = not self.all_slots
        sub.prop(self, "slot")
        col.separator()
        col.prop(self, "space")
        col.prop(self, "scale")
        col.prop(self, "fov_axis")
        col.separator()
        col.prop(self, "make_target")
        col.prop(self, "extend_range")
        col.prop(self, "set_fps")
        col.prop(self, "look_through")

    def execute(self, context):
        if bpy.app.version < (3, 4, 0):
            self.report({"ERROR"}, "Needs Blender 3.4 or newer")
            return {"CANCELLED"}

        paths = []
        folder = os.path.dirname(self.filepath)
        if self.files:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(folder, f.name))
        if not paths:
            paths = [self.filepath]

        zup = self.space == "ZUP"
        made = []
        try:
            for path in paths:
                head = open(path, "rb").read(4)
                if head == M3C_MAGIC:
                    cams = [read_m3c(path)]
                elif head == LMCM_MAGIC:
                    every = read_lmcm(path)
                    if not every:
                        self.report({"WARNING"},
                                    "%s has no populated slots" % os.path.basename(path))
                        continue
                    if self.all_slots:
                        cams = every
                    else:
                        cams = [c for c in every if c.slot == self.slot]
                        if not cams:
                            have = ", ".join(str(c.slot) for c in every)
                            self.report({"ERROR"},
                                        "Slot %d is empty. Populated: %s"
                                        % (self.slot, have))
                            return {"CANCELLED"}
                else:
                    self.report({"ERROR"},
                                "%s is neither LMCM nor M3C" % os.path.basename(path))
                    return {"CANCELLED"}

                for c in cams:
                    made.append(build_camera(context, c, self.scale, zup,
                                             self.fov_axis, self.make_target,
                                             self.extend_range))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        if not made:
            self.report({"WARNING"}, "Nothing imported")
            return {"CANCELLED"}

        if self.set_fps:
            context.scene.render.fps = 60
        if self.look_through:
            context.scene.camera = made[0]
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces[0].region_3d.view_perspective = "CAMERA"
                    break

        for o in context.selected_objects:
            o.select_set(False)
        made[0].select_set(True)
        context.view_layer.objects.active = made[0]

        self.report({"INFO"}, "Imported %d camera(s), %d frames on the first"
                    % (len(made), made[0].data.animation_data is not None
                       and context.scene.frame_end + 1 or 0))
        return {"FINISHED"}


class SUB_OP_cam_export(Operator, ExportHelper):
    bl_idname = "sub.export_cam"
    bl_label = "Export Camera"
    bl_options = {"REGISTER"}

    filename_ext = ".m3c"
    filter_glob: StringProperty(default="*.m3c", options={"HIDDEN"})

    use_target: BoolProperty(
        name="Use the target empty",
        description="Read the look-at track off the empty made on import. Turn "
                    "off to project a target along the view axis instead",
        default=True,
    )
    fallback_distance: FloatProperty(
        name="Fallback distance",
        description="How far ahead to place the target when there is no empty",
        default=400.0, min=0.001,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "CAMERA"

    def execute(self, context):
        obj = context.active_object
        scene = context.scene
        scale = float(obj.get("m3c_scale", 1.0))
        zup = bool(obj.get("m3c_zup", False))

        tgt = None
        if self.use_target:
            tgt = bpy.data.objects.get(obj.get("m3c_target", "") or "")

        c = Cam()
        c.slot = int(obj.get("m3c_slot", 0))
        c.source = str(obj.get("m3c_source", "blender"))
        c.floats = list(obj.get("m3c_floats", [0.0, 1.5, 0.0, 1.0, 0.0]))
        c.eye, c.target, c.rot, c.fov, c.roll = [], [], [], [], []

        saved = scene.frame_current
        try:
            for j in range(scene.frame_start, scene.frame_end + 1):
                scene.frame_set(j)
                mw = obj.matrix_world
                bq = mw.to_quaternion()
                if zup:
                    bq = Q_ZUP.inverted() @ bq
                gq = (bq.x, bq.y, bq.z, bq.w)
                c.rot.append(gq)

                loc = mw.to_translation()
                if zup:
                    eye = (loc.x / scale, loc.z / scale, -loc.y / scale)
                else:
                    eye = (loc.x / scale, loc.y / scale, loc.z / scale)
                c.eye.append(eye)

                q = mathutils.Quaternion((gq[3], gq[0], gq[1], gq[2]))
                right = q @ mathutils.Vector((1.0, 0.0, 0.0))
                up = q @ mathutils.Vector((0.0, 1.0, 0.0))
                fwd = q @ mathutils.Vector((0.0, 0.0, -1.0))
                c.roll.append(math.atan2(right.y, up.y))

                if tgt is not None:
                    t = tgt.matrix_world.to_translation()
                    if zup:
                        c.target.append((t.x / scale, t.z / scale, -t.y / scale))
                    else:
                        c.target.append((t.x / scale, t.y / scale, t.z / scale))
                else:
                    d = self.fallback_distance
                    c.target.append((eye[0] + fwd.x * d,
                                     eye[1] + fwd.y * d,
                                     eye[2] + fwd.z * d))

                cd = obj.data
                ang = cd.angle_y if cd.sensor_fit == "VERTICAL" else cd.angle_x
                c.fov.append(math.degrees(ang))
        finally:
            scene.frame_set(saved)

        c.frames = len(c.eye)
        try:
            write_m3c(self.filepath, c)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, "Exported %d frames to slot %d" % (c.frames, c.slot))
        return {"FINISHED"}
