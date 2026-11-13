import os
import os.path
import bpy
import mathutils
import time
import math
import traceback
import numpy as np

from mathutils import Vector, Matrix
from mathutils import Euler
from bpy.props import StringProperty, BoolProperty
from bpy.types import Panel, Operator, EditBone
from bpy_extras import image_utils
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper
from mathutils import Quaternion
from ..mtlib.metadata import ModelMetadata
from ..mtlib.metadata import JointMetadata
from pathlib import Path
from . import blender_plugin
from .blender_plugin import *


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..mtlib.properties import UMVC3ModelImportProperties

def ShowMessageBox(message = "", title = "Message Box", icon = 'INFO'):

    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)

def _draw_joint_tools(layout):
    box = layout.box()
    box.label(text='Edited UMVC3 skeleton (keeps ID and Symmetry)')
    col = box.column(align=True)
    col.operator('sub.mod_op_clear_joint_index_data', icon='TRASH')
    col.operator('sub.mod_op_apply_joint_csv', icon='IMPORT')


class SUB_PT_OT_ADD_REMOVE_MT_STUFF(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'    
    bl_category = 'MT Framework'
    bl_label = 'Utility'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if context.mode == "POSE" or context.mode == "OBJECT":
            return True
        return False
    
    def draw(self, context):
        
        layout = self.layout
        layout.use_property_split = False        
        obj: bpy.types.Object = context.active_object
        mip:UMVC3ModelImportProperties = context.scene.sub_scene_properties
        row = layout.row()
        if obj is None:
            row.label(text="Select a primitive, joint, or group object first.")
        elif obj.type == 'ARMATURE' and context.mode != "POSE":
            row.label(text="Bones have to be selected in pose mode.")
            _draw_joint_tools(layout)
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_cleanup_vertex_groups', text = 'Cleanup Vertex Groups on Selected Meshes')
        elif obj.type == 'MESH' and context.mode != "OBJECT":
            row.label(text="Select the mesh in Object Mode.")   
        elif obj.type == 'MESH' and context.mode == "OBJECT":
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_add_mt_attributes', text = 'Add MT Attributes to Mesh')
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_remove_mt_attributes', text = 'Delete MT Attributes from Mesh')
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_cleanup_vertex_groups', text = 'Cleanup Vertex Groups on Selected Meshes')
        elif obj.type == 'EMPTY' and context.mode != "OBJECT":
            row.label(text="Select the Group Node in Object Mode.")               
        elif obj.type == 'EMPTY' and context.mode == "OBJECT":    
            layout.separator()
        elif obj.type == 'ARMATURE' and context.mode == "POSE":
            #Checks which pose bone is selected, if any at all.
            PoseBones = obj.pose.bones
            ChosenBone = None
            # the cleanup operator works on every selected MESH, so it is useful while
            # the armature is active too. it was only reachable with a mesh selected.
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_cleanup_vertex_groups', text = 'Cleanup Vertex Groups on Selected Meshes')
            _draw_joint_tools(layout)

            if len(bpy.context.selected_pose_bones) > 1:
                layout.separator()
                row = layout.row(align=True)
                row.operator('sub.mod_op_add_mt_attributes', text = 'Add MT Attributes to Mesh')
                layout.separator()
                row = layout.row(align=True)
                row.operator('sub.mod_op_remove_mt_attributes', text = 'Delete MT Attributes from Mesh')
            else:
                for Bone in PoseBones:
                    if Bone in bpy.context.selected_pose_bones:
                        ChosenBone = Bone

                        # row.prop(mip, 'anim_export_metadata_file')
                        # row = layout.row(align=True)
                        # row.operator(SUB_PT_MOD_OT_Choose_Anim_Export_Metadata_YML.bl_idname,icon='IMPORT',text= 'Choose metadata .yml file')
                        layout.separator()
                        row = layout.row(align=True)
                        row.operator('sub.mod_op_add_mt_attributes', text = 'Add MT Attributes to Mesh')
                        layout.separator()
                        row = layout.row(align=True)
                        row.operator('sub.mod_op_remove_mt_attributes', text = 'Delete MT Attributes from Mesh')
                        # row = layout.row(align=True)
                        # row.operator(SUB_OP_anim_export.bl_idname, icon='IMPORT', text='Export Marvel 3 .yml Animation')
                if ChosenBone == None:
                    row.label(text="Select a bone in pose mode.")  
        else:
            row.label(text="Select a primitive, joint, or group object first.")

        #Material Selector for later.
        layout.separator()
        row = layout.row(align=True)
        layout.prop(mip, "material_to_filter_by", text="Material")   
        layout.separator()
        row = layout.row(align=True)        
        row.operator('sub.mod_op_select_objects_by_material', text = 'Select Objects By Material')         

JOINT_REBUILT_KEYS = ('parentIndex', 'symmetryIndex', 'length', 'offsetX', 'offsetY', 'offsetZ', 'index')


def _duplicate_joint_ids(arm):
    by_id = {}
    for pb in arm.pose.bones:
        v = str(pb.get('id', '')).strip()
        if v.isdigit():
            by_id.setdefault(int(v), []).append(pb.name)
    return {i: n for i, n in by_id.items() if len(n) > 1}


def _report_ids(op, arm, msg):
    dup = _duplicate_joint_ids(arm)
    if dup:
        text = ', '.join('%d (%s)' % (i, ' and '.join(n[:3])) for i, n in sorted(dup.items())[:6])
        op.report({'WARNING'}, '%s. Shared ids, fix before export: %s' % (msg, text))
    else:
        op.report({'INFO'}, msg)


class SUB_OP_CLEAR_JOINT_INDEX_DATA(bpy.types.Operator):
    bl_idname = 'sub.mod_op_clear_joint_index_data'
    bl_label = 'Clear Index Data (keep ID and Symmetry)'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        arm = context.active_object
        bones = list(context.selected_pose_bones or []) if context.mode == 'POSE' else []
        if not bones:
            bones = list(arm.pose.bones)
        cleared = 0
        no_id = []
        for pb in bones:
            hit = False
            for k in JOINT_REBUILT_KEYS:
                if k in pb.keys():
                    del pb[k]
                    hit = True
            cleared += hit
            if str(pb.get('id', '')).strip() in ('', '0'):
                no_id.append(pb.name)
        msg = 'cleared index data on %d of %d bones' % (cleared, len(bones))
        if no_id:
            msg += '; no id on %s' % ', '.join(no_id[:5]) + ('...' if len(no_id) > 5 else '')
        _report_ids(self, arm, msg)
        return {'FINISHED'}


class SUB_OP_APPLY_JOINT_CSV(bpy.types.Operator, ImportHelper):
    bl_idname = 'sub.mod_op_apply_joint_csv'
    bl_label = 'Apply Bone CSV (ID and Symmetry)'
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = '.csv'
    filter_glob: StringProperty(default='*.csv', options={'HIDDEN'})
    rename: BoolProperty(name='Rename bones to jnt_<id>', default=True,
                         description='The animation exporter finds bones by these names')
    clear_index: BoolProperty(name='Clear their index data too', default=True,
                              description='Remove stale order, length and offset data so the exporter rebuilds it')

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        from . import custom_skeleton as CS
        arm = context.active_object
        mode = context.mode
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            rows, notes = CS.read_bone_rows(self.filepath, set(arm.data.bones.keys()))
        except Exception as e:
            self.report({'ERROR'}, 'could not read the .csv: %s' % e)
            return {'CANCELLED'}
        ids = {b: i for b, i, _ in rows}
        by_id = {i: b for b, i in ids.items()}
        for pb in arm.pose.bones:          # bones the csv doesn't list keep the ids they have
            v = str(pb.get('id', '')).strip()
            if pb.name not in ids and v.isdigit():
                by_id.setdefault(int(v), pb.name)
        sym = {}
        for b, i, s in rows:
            t = s if s in arm.data.bones else by_id.get(CS._id_of(s)) if s else None
            if s and t is None:
                notes.append('%s: symmetrical opposite %s is not on the rig' % (b, s))
            sym[b] = t or b                   # none given: the bone is its own opposite
        # a pair named only from one side points back
        for b, t in list(sym.items()):
            if t != b and sym.get(t) == t:
                sym[t] = b
        final = {b: b for b in arm.data.bones.keys()}
        if self.rename:
            want = {b: 'jnt_%d' % i for b, i in ids.items()}
            taken = {n for n in final if n not in want and n in want.values()}
            for n in taken:                   # an unlisted bone already called jnt_N steps aside
                final[n] = n + '_old'
            final.update(want)
            for b in arm.data.bones:
                b.name = '__csv_tmp_' + b.name
            for b in arm.data.bones:
                old = b.name[len('__csv_tmp_'):]
                b.name = final[old]
            if taken:
                notes.append('renamed %s out of the way' % ', '.join(sorted(taken)))
        for b, i in ids.items():
            pb = arm.pose.bones[final[b]]
            pb['id'] = str(i)
            pb['symmetryName'] = final[sym[b]]
            if self.clear_index:
                for k in JOINT_REBUILT_KEYS:
                    if k in pb.keys():
                        del pb[k]
        for n in notes:
            print('Apply Bone CSV: ' + n)
        msg = 'set id and symmetry on %d bones' % len(ids)
        if notes:
            msg += '; %d notes in the console' % len(notes)
        if mode == 'POSE':
            bpy.ops.object.mode_set(mode='POSE')
        _report_ids(self, arm, msg)
        return {'FINISHED'}


class SUB_OP_ADD_MT_ATTRIBUTES(bpy.types.Operator):
    bl_idname = 'sub.mod_op_add_mt_attributes'
    bl_label = "Add MT Attribute Data"

    def execute(self,context):
        scene = bpy.context.scene
        #Stores the object selected.
        obj = bpy.context.active_object

        if obj.type == 'MESH' and context.mode == "OBJECT":
            
            #Is this command necessary?
            BlenderNode = BlenderNodeProxy(obj)
            
            try:
                obj["flags"] = str(0)
                obj["groupId"] = str(0) 
                obj["lodIndex"] = str(0) 
                obj["matIndex"] = str(0) 
                obj["vertexFlags"] = str(0) 
                obj["vertexStride"] = str(0) 
                obj["renderFlags"] = str(0) 
                obj["vertexStartIndex"] = str(0) 
                obj["vertexBufferOffset"] = str(0) 
                obj["shaderName"] = ""
                obj["indexBufferOffset"] = str(0) 
                obj["indexCount"] = str(0) 
                obj["indexStartIndex"] = str(0) 
                obj["boneMapStartIndex"] = str(0) 
                obj["envelopeCount"] = str(0) 
                obj["envelopeIndex"] = str(0) 
                obj["id"] = str(0)
                obj["minVertexIndex"] = str(0) 
                obj["maxVertexIndex"] = str(0) 
                obj["field2c"] = str(0) 
                obj["envelopePtr"] = str(0) 
                obj["index"] = str(0) 
            except KeyError:
                print("MT Attribute data doesn't seem to exist on the selected item.")
                ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")
        #For Group nodes.
        elif obj.type == 'EMPTY' and context.mode == "OBJECT":
            BlenderNode = BlenderNodeProxy(obj)
            try:
                obj["id"] = str(0)
                obj["field04"] = str(0)    
                obj["field08"] = str(0)
                obj["field0c"] = str(0)
                obj["boundingSphere"] = str(0.0)
                obj["index"] = str(0.0)
            except KeyError:
                print("MT Attribute data doesn't seem to exist on the selected item.")
                ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")                
        #For Joints/Bones.
        elif obj.type == 'ARMATURE' and context.mode == "POSE":
            #Checks which pose bone is selected, if any at all.
            PoseBones = obj.pose.bones
            ChosenBone = None
            for Bone in bpy.context.selected_pose_bones:
                ChosenBone = Bone
                BlenderNode = BlenderNodeProxy(ChosenBone)
                try:
                    Bone["id"] = str(0)
                    Bone["parentIndex"] = str(0)
                    Bone["symmetryIndex"] = str(0)
                    Bone["symmetryName"] = str(0)
                    Bone["field03"] = str(0)
                    Bone["field04"] = str(0)
                    Bone["length"] = str(0.0)
                    Bone["offsetX"] = str(0.0)
                    Bone["offsetY"] = str(0.0)
                    Bone["offsetZ"] = str(0.0)
                    Bone["index"] = str(0)

                except KeyError:
                    print("MT Attribute data doesn't seem to exist on the selected item.")
                    ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)        
        return {'FINISHED'}       

class SUB_OP_REMOVE_MT_ATTRIBUTES(bpy.types.Operator):
    bl_idname = 'sub.mod_op_remove_mt_attributes'
    bl_label = "Delete MT Attribute Data"

    def execute(self,context):
        scene = bpy.context.scene
        #Stores the object selected.
        obj = bpy.context.active_object
        #Attempts to remove the MT Attributes from Primitives.
        if obj.type == 'MESH' and context.mode == "OBJECT":
            
            #Is this command necessary?
            BlenderNode = BlenderNodeProxy(obj)
            
            try:
                del obj["flags"] 
                del obj["groupId"] 
                del obj["lodIndex"] 
                del obj["matIndex"] 
                del obj["vertexFlags"] 
                del obj["vertexStride"] 
                del obj["renderFlags"] 
                del obj["vertexStartIndex"] 
                del obj["vertexBufferOffset"] 
                del obj["shaderName"] 
                del obj["indexBufferOffset"] 
                del obj["indexCount"] 
                del obj["indexStartIndex"] 
                del obj["boneMapStartIndex"] 
                del obj["envelopeCount"] 
                del obj["envelopeIndex"] 
                del obj["id"]
                del obj["minVertexIndex"] 
                del obj["maxVertexIndex"] 
                del obj["field2c"] 
                del obj["envelopePtr"] 
                del obj["index"] 
            except KeyError:
                print("MT Attribute data doesn't seem to exist on the selected item.")
                ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")
        #For Group nodes.
        elif obj.type == 'EMPTY' and context.mode == "OBJECT":
            BlenderNode = BlenderNodeProxy(obj)
            try:
                del obj["id"]
                del obj["field04"]    
                del obj["field08"]
                del obj["field0c"]
                del obj["boundingSphere"]
                del obj["index"]
            except KeyError:
                print("MT Attribute data doesn't seem to exist on the selected item.")
                ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")                
        #For Joints/Bones.
        elif obj.type == 'ARMATURE' and context.mode == "POSE":
            #Checks which pose bone is selected, if any at all.
            PoseBones = obj.pose.bones
            ChosenBone = None
            for Bone in bpy.context.selected_pose_bones:
                ChosenBone = Bone
                BlenderNode = BlenderNodeProxy(ChosenBone)
                try:
                    del Bone["id"]
                    del Bone["parentIndex"]
                    del Bone["symmetryIndex"]
                    del Bone["symmetryName"]
                    del Bone["field03"]
                    del Bone["field04"]
                    del Bone["length"]
                    del Bone["offsetX"]
                    del Bone["offsetY"]
                    del Bone["offsetZ"]
                    del Bone["index"]

                except KeyError:
                    print("MT Attribute data doesn't seem to exist on the selected item.")
                    ShowMessageBox("MT Attribute data doesn't seem to exist on the selected item.\nYou may have already deleted them.")        

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)        
        return {'FINISHED'}  

class SUB_OP_CLEANUP_VERTEX_GROUPS(bpy.types.Operator):
    bl_idname = 'sub.mod_op_cleanup_vertex_groups'
    bl_label = "Cleanup Vertex Groups"

    def execute(self,context):
        scene = bpy.context.scene

        #Stores the objects selected.
        for obj in bpy.context.selected_objects:
            if obj.type != 'MESH':
                continue

            #Check to see if the mesh has an Armature Modifier, and selects it.
            Armature = next(
                (
                    modifier.object
                    for modifier in obj.modifiers
                    if modifier.type == 'ARMATURE' and modifier.object
                ),
                None
            )
            if not Armature:
                continue

            #Gather the relevant bone names.
            RelevantBoneNames = {bone.name for bone in Armature.data.bones}
        
            #Discards the vertex groups that don't match bone names in the armature.
            for vertex_group in list(obj.vertex_groups):
                if vertex_group.name not in RelevantBoneNames:
                    obj.vertex_groups.remove(vertex_group)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)        
        return {'FINISHED'}

class SUB_OP_SELECT_OBJECTS_BY_MATERIAL(bpy.types.Operator):
    bl_idname = 'sub.mod_op_select_objects_by_material'
    bl_label = "Select Objects By Material"

    def execute(self, context):
        #Gets the material and checks if it is valid.
        mip:UMVC3ModelImportProperties = context.scene.sub_scene_properties
        material = mip.material_to_filter_by

        print(material.name)

        if material is None:
            self.report({'WARNING'}, "There's no material here. Select one first.")
            return {'CANCELLED'}

        #Deselects Everything else.
        bpy.context.active_object.select_set(False)

        #Checks each object based on material and only selects the objects that are using said material.
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':
                if material in obj.data.materials[:]:
                    obj.select_set(True)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)        
        return {'FINISHED'}