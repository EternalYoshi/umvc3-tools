import os
import os.path
import bpy
import mathutils
import re
import collections
import time
import math
import traceback
import subprocess
import yaml
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
from pathlib import Path

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..mtlib.properties import ModelImportProperties

def ShowMessageBox(message = "", title = "Message Box", icon = 'INFO'):

    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)

class data():
   def __init__(self, X, Y, Z, W):
        self.X = X
        self.Y = Y
        self.Z = Z
        self.W = W

class Keyframes():
    def __init__(self, Frame, TrackType, BoneID, data):
        self.Frame = Frame
        self.TrackType = TrackType
        self.BoneID = BoneID
        self.data = data

class LMTM3AEntry:
      yaml_loader = yaml.SafeLoader
      yaml_tag = u'!LMTM3AEntry'

      def __init__(self, version, Name, FrameCount, LoopFrame, KeyFrames):
        self.version = version
        self.Name = Name
        self.FrameCount = FrameCount
        self.LoopFrame = LoopFrame
        self.KeyFrames = KeyFrames

def LMTM3AEntry_constructor(loader: yaml.SafeLoader, node: yaml.nodes.MappingNode) -> LMTM3AEntry:
  """Construct a LMTM3AEntry."""
  return LMTM3AEntry(**loader.construct_mapping(node))

def get_loader():
  """Add constructors to PyYAML loader."""
  loader = yaml.SafeLoader
  loader.add_constructor("!LMTM3AEntry", LMTM3AEntry_constructor)
  return loader

#From the SSBU Animation exporter.        
def get_heirarchy_order(bone_list: list[bpy.types.PoseBone]) -> list[bpy.types.PoseBone]:
    root_bone: bpy.types.PoseBone = None
    for bone in bone_list:
        if bone.parent is None:
            root_bone = bone
            break
    return [root_bone] + [c for c in root_bone.children_recursive if c in bone_list]

def loadMetadata( self, path ):
    metadata = ModelMetadata()
    if os.path.exists( path ):
        #self.logger.info(f'loading metadata file from {path}')
        metadata.loadFile( path )
    return metadata

#Code from my 2023 Aniamtion importer, slightly adapted.
class Location():
    def __init__(self, x, y, z):
        self.x: float = x
        self.y: float = y
        self.z: float = z
    def __repr__(self) -> str:
        return f'[{self.x=}, {self.y=}, {self.z=}]'

class Rotation():
    def __init__(self, w, x, y, z):
        self.w: float = w
        self.x: float = x
        self.y: float = y
        self.z: float = z
    def __repr__(self) -> str:
        return f'[{self.w=}, {self.x=}, {self.y=}, {self.z=}]'

class Scale():
    def __init__(self, x, y, z):
        self.x: float = x
        self.y: float = y
        self.z: float = z
    def __repr__(self) -> str:
        return f'[{self.x=}, {self.y=}, {self.z=}]'

def keyframeCount(bone, start, end) -> int:

    N_keyframes = 0

    action = bpy.data.actions["ArmatureAction"]
    for fcu in action.fcurves:
        print(fcu.data_path + " channel " + str(fcu.array_index))     
        bonename = str(bone.name)      
        for keyframe in fcu.keyframe_points:
            if str(bone.name) in fcu.data_path:
                print(keyframe.co) #coordinates x,y
                N_keyframes += 1



    return N_keyframes

#Double Checking the bone name for conflicts.
def NameChecker(index, fcu, bonename) -> bool:
    #pdb.set_trace()
#This is inteded to remove naming issues with the data path that result in redundant/incorrect keys being inserted for the bone.
    if bonename == "jnt_1":
        if "jnt_10" in fcu.data_path:
            return False
        if "jnt_11" in fcu.data_path:
            return False
        if "jnt_12" in fcu.data_path:
            return False
        if "jnt_13" in fcu.data_path:
            return False
        if "jnt_14" in fcu.data_path:
            return False
        if "jnt_15" in fcu.data_path:
            return False
        if "jnt_16" in fcu.data_path:
            return False
        if "jnt_17" in fcu.data_path:
            return False
        if "jnt_18" in fcu.data_path:
            return False
        if "jnt_19" in fcu.data_path:
            return False
        return True

    if bonename == "jnt_2":  
        if "jnt_20" in fcu.data_path:
            return False
        if "jnt_21" in fcu.data_path:
            return False
        if "jnt_22" in fcu.data_path:
            return False
        if "jnt_23" in fcu.data_path:
            return False
        if "jnt_24" in fcu.data_path:
            return False
        if "jnt_25" in fcu.data_path:
            return False
        if "jnt_26" in fcu.data_path:
            return False
        if "jnt_27" in fcu.data_path:
            return False
        if "jnt_28" in fcu.data_path:
            return False
        if "jnt_29" in fcu.data_path:
            return False
        return True

    if bonename == "jnt_3":   
        if "jnt_30" in fcu.data_path:
            return False
        if "jnt_31" in fcu.data_path:
            return False
        if "jnt_32" in fcu.data_path:
            return False
        if "jnt_33" in fcu.data_path:
            return False
        if "jnt_34" in fcu.data_path:
            return False
        if "jnt_35" in fcu.data_path:
            return False
        if "jnt_36" in fcu.data_path:
            return False
        if "jnt_37" in fcu.data_path:
            return False
        if "jnt_38" in fcu.data_path:
            return False
        if "jnt_39" in fcu.data_path:
            return False
        return True
        
    if bonename == "jnt_4":
        if "jnt_40" in fcu.data_path:
            return False
        if "jnt_41" in fcu.data_path:
            return False
        if "jnt_42" in fcu.data_path:
            return False
        if "jnt_43" in fcu.data_path:
            return False
        if "jnt_44" in fcu.data_path:
            return False
        if "jnt_45" in fcu.data_path:
            return False
        if "jnt_46" in fcu.data_path:
            return False
        if "jnt_47" in fcu.data_path:
            return False
        if "jnt_48" in fcu.data_path:
            return False
        if "jnt_49" in fcu.data_path:
            return False
        return True
        
    if bonename == "jnt_5": 
        if "jnt_50" in fcu.data_path:
            return False
        if "jnt_51" in fcu.data_path:
            return False
        if "jnt_52" in fcu.data_path:
            return False
        if "jnt_53" in fcu.data_path:
            return False
        if "jnt_54" in fcu.data_path:
            return False
        if "jnt_55" in fcu.data_path:
            return False
        if "jnt_56" in fcu.data_path:
            return False
        if "jnt_57" in fcu.data_path:
            return False
        if "jnt_58" in fcu.data_path:
            return False
        if "jnt_59" in fcu.data_path:
            return False
        return True     

    if bonename == "jnt_6":  
        if "jnt_60" in fcu.data_path:
            return False
        if "jnt_61" in fcu.data_path:
            return False
        if "jnt_62" in fcu.data_path:
            return False
        if "jnt_63" in fcu.data_path:
            return False
        if "jnt_64" in fcu.data_path:
            return False
        if "jnt_65" in fcu.data_path:
            return False
        if "jnt_66" in fcu.data_path:
            return False
        if "jnt_67" in fcu.data_path:
            return False
        if "jnt_68" in fcu.data_path:
            return False
        if "jnt_69" in fcu.data_path:
            return False 
        return True   

    if bonename == "jnt_7":
        if "jnt_70" in fcu.data_path:
            return False
        if "jnt_71" in fcu.data_path:
            return False
        if "jnt_72" in fcu.data_path:
            return False
        if "jnt_73" in fcu.data_path:
            return False
        if "jnt_74" in fcu.data_path:
            return False
        if "jnt_75" in fcu.data_path:
            return False
        if "jnt_76" in fcu.data_path:
            return False
        if "jnt_77" in fcu.data_path:
            return False
        if "jnt_78" in fcu.data_path:
            return False
        if "jnt_79" in fcu.data_path:
            return False 
        return True                          

    if bonename == "jnt_8":  
        if "jnt_80" in fcu.data_path:
            return False
        if "jnt_81" in fcu.data_path:
            return False
        if "jnt_82" in fcu.data_path:
            return False
        if "jnt_83" in fcu.data_path:
            return False
        if "jnt_84" in fcu.data_path:
            return False
        if "jnt_85" in fcu.data_path:
            return False
        if "jnt_86" in fcu.data_path:
            return False
        if "jnt_87" in fcu.data_path:
            return False
        if "jnt_88" in fcu.data_path:
            return False
        if "jnt_89" in fcu.data_path:
            return False
        return True
        
    if bonename == "jnt_9":    
        if "jnt_90" in fcu.data_path:
            return False
        if "jnt_91" in fcu.data_path:
            return False
        if "jnt_92" in fcu.data_path:
            return False
        if "jnt_93" in fcu.data_path:
            return False
        if "jnt_94" in fcu.data_path:
            return False
        if "jnt_95" in fcu.data_path:
            return False
        if "jnt_96" in fcu.data_path:
            return False
        if "jnt_97" in fcu.data_path:
            return False
        if "jnt_98" in fcu.data_path:
            return False
        if "jnt_99" in fcu.data_path:
            return False 
        return True           

    if bonename == "jnt_10":
        if "jnt_100" in fcu.data_path:
            return False    
        if "jnt_110" in fcu.data_path:
            return False
        if "jnt_101" in fcu.data_path:
            return False
        if "jnt_102" in fcu.data_path:
            return False
        if "jnt_103" in fcu.data_path:
            return False
        if "jnt_104" in fcu.data_path:
            return False
        if "jnt_105" in fcu.data_path:
            return False
        if "jnt_106" in fcu.data_path:
            return False
        if "jnt_107" in fcu.data_path:
            return False
        if "jnt_108" in fcu.data_path:
            return False
        if "jnt_109" in fcu.data_path:
            return False 
        return True    

    if bonename == "jnt_11":    
        if "jnt_110" in fcu.data_path:
            return False
        if "jnt_111" in fcu.data_path:
            return False
        if "jnt_112" in fcu.data_path:
            return False
        if "jnt_113" in fcu.data_path:
            return False
        if "jnt_114" in fcu.data_path:
            return False
        if "jnt_115" in fcu.data_path:
            return False
        if "jnt_116" in fcu.data_path:
            return False
        if "jnt_117" in fcu.data_path:
            return False
        if "jnt_118" in fcu.data_path:
            return False
        if "jnt_119" in fcu.data_path:
            return False 
        return True    

    if bonename == "jnt_12":    
        if "jnt_120" in fcu.data_path:
            return False
        if "jnt_121" in fcu.data_path:
            return False
        if "jnt_122" in fcu.data_path:
            return False
        if "jnt_123" in fcu.data_path:
            return False
        if "jnt_124" in fcu.data_path:
            return False
        if "jnt_125" in fcu.data_path:
            return False
        if "jnt_126" in fcu.data_path:
            return False
        if "jnt_127" in fcu.data_path:
            return False
        if "jnt_128" in fcu.data_path:
            return False
        if "jnt_129" in fcu.data_path:
            return False 
        return True    
    
    if bonename == "jnt_13":    
        if "jnt_130" in fcu.data_path:
            return False
        if "jnt_131" in fcu.data_path:
            return False
        if "jnt_132" in fcu.data_path:
            return False
        if "jnt_133" in fcu.data_path:
            return False
        if "jnt_134" in fcu.data_path:
            return False
        if "jnt_135" in fcu.data_path:
            return False
        if "jnt_136" in fcu.data_path:
            return False
        if "jnt_137" in fcu.data_path:
            return False
        if "jnt_138" in fcu.data_path:
            return False
        if "jnt_139" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_14":    
        if "jnt_140" in fcu.data_path:
            return False
        if "jnt_141" in fcu.data_path:
            return False
        if "jnt_142" in fcu.data_path:
            return False
        if "jnt_143" in fcu.data_path:
            return False
        if "jnt_144" in fcu.data_path:
            return False
        if "jnt_145" in fcu.data_path:
            return False
        if "jnt_146" in fcu.data_path:
            return False
        if "jnt_147" in fcu.data_path:
            return False
        if "jnt_148" in fcu.data_path:
            return False
        if "jnt_149" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_15":    
        if "jnt_150" in fcu.data_path:
            return False
        if "jnt_151" in fcu.data_path:
            return False
        if "jnt_152" in fcu.data_path:
            return False
        if "jnt_153" in fcu.data_path:
            return False
        if "jnt_154" in fcu.data_path:
            return False
        if "jnt_155" in fcu.data_path:
            return False
        if "jnt_156" in fcu.data_path:
            return False
        if "jnt_157" in fcu.data_path:
            return False
        if "jnt_158" in fcu.data_path:
            return False
        if "jnt_159" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_16":    
        if "jnt_160" in fcu.data_path:
            return False
        if "jnt_161" in fcu.data_path:
            return False
        if "jnt_162" in fcu.data_path:
            return False
        if "jnt_163" in fcu.data_path:
            return False
        if "jnt_164" in fcu.data_path:
            return False
        if "jnt_165" in fcu.data_path:
            return False
        if "jnt_166" in fcu.data_path:
            return False
        if "jnt_167" in fcu.data_path:
            return False
        if "jnt_168" in fcu.data_path:
            return False
        if "jnt_169" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_17":    
        if "jnt_170" in fcu.data_path:
            return False
        if "jnt_171" in fcu.data_path:
            return False
        if "jnt_172" in fcu.data_path:
            return False
        if "jnt_173" in fcu.data_path:
            return False
        if "jnt_174" in fcu.data_path:
            return False
        if "jnt_175" in fcu.data_path:
            return False
        if "jnt_176" in fcu.data_path:
            return False
        if "jnt_177" in fcu.data_path:
            return False
        if "jnt_178" in fcu.data_path:
            return False
        if "jnt_179" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_18":    
        if "jnt_180" in fcu.data_path:
            return False
        if "jnt_181" in fcu.data_path:
            return False
        if "jnt_182" in fcu.data_path:
            return False
        if "jnt_183" in fcu.data_path:
            return False
        if "jnt_184" in fcu.data_path:
            return False
        if "jnt_185" in fcu.data_path:
            return False
        if "jnt_186" in fcu.data_path:
            return False
        if "jnt_187" in fcu.data_path:
            return False
        if "jnt_188" in fcu.data_path:
            return False
        if "jnt_189" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_19":    
        if "jnt_190" in fcu.data_path:
            return False
        if "jnt_191" in fcu.data_path:
            return False
        if "jnt_192" in fcu.data_path:
            return False
        if "jnt_193" in fcu.data_path:
            return False
        if "jnt_194" in fcu.data_path:
            return False
        if "jnt_195" in fcu.data_path:
            return False
        if "jnt_196" in fcu.data_path:
            return False
        if "jnt_197" in fcu.data_path:
            return False
        if "jnt_198" in fcu.data_path:
            return False
        if "jnt_199" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_20":    
        if "jnt_200" in fcu.data_path:
            return False
        if "jnt_201" in fcu.data_path:
            return False
        if "jnt_202" in fcu.data_path:
            return False
        if "jnt_203" in fcu.data_path:
            return False
        if "jnt_204" in fcu.data_path:
            return False
        if "jnt_205" in fcu.data_path:
            return False
        if "jnt_206" in fcu.data_path:
            return False
        if "jnt_207" in fcu.data_path:
            return False
        if "jnt_208" in fcu.data_path:
            return False
        if "jnt_209" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_21":    
        if "jnt_210" in fcu.data_path:
            return False
        if "jnt_211" in fcu.data_path:
            return False
        if "jnt_212" in fcu.data_path:
            return False
        if "jnt_213" in fcu.data_path:
            return False
        if "jnt_214" in fcu.data_path:
            return False
        if "jnt_215" in fcu.data_path:
            return False
        if "jnt_216" in fcu.data_path:
            return False
        if "jnt_217" in fcu.data_path:
            return False
        if "jnt_218" in fcu.data_path:
            return False
        if "jnt_219" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_22":    
        if "jnt_220" in fcu.data_path:
            return False
        if "jnt_221" in fcu.data_path:
            return False
        if "jnt_222" in fcu.data_path:
            return False
        if "jnt_223" in fcu.data_path:
            return False
        if "jnt_224" in fcu.data_path:
            return False
        if "jnt_225" in fcu.data_path:
            return False
        if "jnt_226" in fcu.data_path:
            return False
        if "jnt_227" in fcu.data_path:
            return False
        if "jnt_228" in fcu.data_path:
            return False
        if "jnt_229" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_23":    
        if "jnt_230" in fcu.data_path:
            return False
        if "jnt_231" in fcu.data_path:
            return False
        if "jnt_232" in fcu.data_path:
            return False
        if "jnt_233" in fcu.data_path:
            return False
        if "jnt_234" in fcu.data_path:
            return False
        if "jnt_235" in fcu.data_path:
            return False
        if "jnt_236" in fcu.data_path:
            return False
        if "jnt_237" in fcu.data_path:
            return False
        if "jnt_238" in fcu.data_path:
            return False
        if "jnt_239" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_24":    
        if "jnt_240" in fcu.data_path:
            return False
        if "jnt_241" in fcu.data_path:
            return False
        if "jnt_242" in fcu.data_path:
            return False
        if "jnt_243" in fcu.data_path:
            return False
        if "jnt_244" in fcu.data_path:
            return False
        if "jnt_245" in fcu.data_path:
            return False
        if "jnt_246" in fcu.data_path:
            return False
        if "jnt_247" in fcu.data_path:
            return False
        if "jnt_248" in fcu.data_path:
            return False
        if "jnt_249" in fcu.data_path:
            return False 
        return True

    if bonename == "jnt_25":    
        if "jnt_250" in fcu.data_path:
            return False
        if "jnt_251" in fcu.data_path:
            return False
        if "jnt_252" in fcu.data_path:
            return False
        if "jnt_253" in fcu.data_path:
            return False
        if "jnt_254" in fcu.data_path:
            return False
        if "jnt_255" in fcu.data_path:
            return False
        if "jnt_256" in fcu.data_path:
            return False
        return True

    return True

def ApplyTheTrack(Track, obj, joint, jointEdit, AnimName, import_legacy, usingmetadata):
    
    Frame = 0
    Bone = Track[0]['BoneID']
    
    if usingmetadata == True:
        if bpy.data.objects["Armature"].data.bones.get(joint.name) is None:
            return
        
        for ID, Keyframe in enumerate(Track):
    
            if import_legacy == True:
                    
                if(Track[0]['TrackType'] == "localscale" or Track[0]['TrackType'] == "xpto"):
                    print("A scale Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.scale = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        #print(joint.scale)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (joint.name, "scale"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying scalar keyframe.",sc, "\n", traceback.format_exc())
                        continue          
            
                if(Track[0]['TrackType'] == "localposition" or Track[0]['TrackType'] == "absoluteposition"):
                    print("A Translation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.location = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        print("Bone: ", joint.name ,"Translation Keyframe: ",joint.location)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (joint.name, "location"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying translation keyframe.",sc, "\n", traceback.format_exc())
                        continue              
                    
                if(Track[0]['TrackType'] == "localrotation" or Track[0]['TrackType'] == "absoluterotation"):
                    print("A Rotation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    print(str(joint))
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        Thing = mathutils.Quaternion((float(Keyframe['data']['W']), float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z'])))
                        print(Thing)                                                
                        joint.rotation_quaternion = Thing
                        print(joint.rotation_quaternion)
                        
                        #print(obj.pose.bones[0].rotation_mode)
                        
                        obj.keyframe_insert(data_path=joint.path_from_id("rotation_quaternion"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying rotational keyframe.",sc, "\n", traceback.format_exc())
                        continue

            else:
                    
                if(Track[0]['TrackType'] == "localscale" or Track[0]['TrackType'] == "xpto"):
                    print("A scale Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.scale = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        #print(joint.scale)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (joint.name, "scale"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying scalar keyframe.",sc, "\n", traceback.format_exc())
                        continue          
            
                if(Track[0]['TrackType'] == "localposition" or Track[0]['TrackType'] == "absoluteposition"):
                    print("A Translation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.location = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        print("Bone: ", joint.name ,"Translation Keyframe: ",joint.location)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (joint.name, "location"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying translation keyframe.",sc, "\n", traceback.format_exc())
                        continue              
                    
                if(Track[0]['TrackType'] == "localrotation" or Track[0]['TrackType'] == "absoluterotation"):
                    print("A Rotation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[joint.name]
                    print(str(joint))
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        Thing = mathutils.Quaternion((float(Keyframe['data']['W']), float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z'])))
                        print(Thing)                                                
                        joint.rotation_quaternion = Thing
                        print(joint.rotation_quaternion)
                        
                        #print(obj.pose.bones[0].rotation_mode)
                        
                        obj.keyframe_insert(data_path=joint.path_from_id("rotation_quaternion"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying rotational keyframe.",sc, "\n", traceback.format_exc())
                        continue

    else:
        #Checks if the bone exists on the Armature in the scene and will skip if it doesn't.
        if bpy.data.objects["Armature"].data.bones.get(f'jnt_{Bone}') is None:
            return
    
        for ID, Keyframe in enumerate(Track):
        
            if import_legacy == True:
                    
                if(Track[0]['TrackType'] == "localscale" or Track[0]['TrackType'] == "xpto"):
                    print("A scale Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.scale = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        #print(joint.scale)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (f'jnt_{Bone}', "scale"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying scalar keyframe.",sc, "\n", traceback.format_exc())
                        continue          
            
                if(Track[0]['TrackType'] == "localposition" or Track[0]['TrackType'] == "absoluteposition"):
                    print("A Translation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.location = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        print("Bone: ", joint.name ,"Translation Keyframe: ",joint.location)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (f'jnt_{Bone}', "location"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying translation keyframe.",sc, "\n", traceback.format_exc())
                        continue              
                    
                if(Track[0]['TrackType'] == "localrotation" or Track[0]['TrackType'] == "absoluterotation"):
                    print("A Rotation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    print(str(joint))
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        Thing = mathutils.Quaternion((float(Keyframe['data']['W']), float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z'])))
                        print(Thing)                                                
                        joint.rotation_quaternion = Thing
                        print(joint.rotation_quaternion)
                        
                        #print(obj.pose.bones[0].rotation_mode)
                        
                        obj.keyframe_insert(data_path=joint.path_from_id("rotation_quaternion"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying rotational keyframe.",sc, "\n", traceback.format_exc())
                        continue

            else:
                    
                if(Track[0]['TrackType'] == "localscale" or Track[0]['TrackType'] == "xpto"):
                    print("A scale Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.scale = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        #print(joint.scale)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (f'jnt_{Bone}', "scale"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying scalar keyframe.",sc, "\n", traceback.format_exc())
                        continue          
            
                if(Track[0]['TrackType'] == "localposition" or Track[0]['TrackType'] == "absoluteposition"):
                    print("A Translation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        joint.location = (float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z']))
                        print("Bone: ", joint.name ,"Translation Keyframe: ",joint.location)
                        
                        obj.keyframe_insert(data_path='pose.bones["%s"].%s' %
                                        (f'jnt_{Bone}', "location"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying translation keyframe.",sc, "\n", traceback.format_exc())
                        continue              
                    
                if(Track[0]['TrackType'] == "localrotation" or Track[0]['TrackType'] == "absoluterotation"):
                    print("A Rotation Track.")
                    obj = bpy.data.objects["Armature"]
                    joint = obj.pose.bones[f'jnt_{Bone}']
                    print(str(joint))
                    #Do Stuff here.
                    try:
                        Frame = int(Keyframe['Frame'])
                        Thing = mathutils.Quaternion((float(Keyframe['data']['W']), float(Keyframe['data']['X']), float(Keyframe['data']['Y']), float(Keyframe['data']['Z'])))
                        print(Thing)                                                
                        joint.rotation_quaternion = Thing
                        print(joint.rotation_quaternion)
                        
                        #print(obj.pose.bones[0].rotation_mode)
                        
                        obj.keyframe_insert(data_path=joint.path_from_id("rotation_quaternion"), frame=(Frame), group=AnimName)
                        
                                            
                    except Exception as sc:
                        print("Problem applying rotational keyframe.",sc, "\n", traceback.format_exc())
                        continue

def readM3AanimationData(self,context,filepath):
    global AnimName; AnimName = ""
    GroupCount = 0
    global FrameCount; FrameCount = 0
    NodeCount = 0
    global AnimGroups; AnimGroups = {}
    keycount = 0
    os.system('cls')
    
    print(self.files); print(filepath)
    
    #Stores the object selected.
    obj = bpy.context.active_object

    #Changes the blender mode to Pose Mode.
    bpy.ops.object.mode_set(mode = 'POSE', toggle=False)    
        
    #This block forces ALL bones to use quaternion rotation & sets each bone to the Identity Matrix.
    for bone in obj.pose.bones:
        bone.matrix_basis.identity()
        bone.rotation_mode = 'QUATERNION'
    bpy.data.objects["Armature"].rotation_mode = 'QUATERNION'
    
    for AnimYAML in self.files:
        AnimYAMLPath = os.path.join(os.path.dirname(filepath), AnimYAML.name)
        if os.path.isfile(AnimYAMLPath):
            AnimName = os.path.basename(AnimYAMLPath)
            try:
                obj.animation_data.action
            except:
                obj.animation_data_create()

            action = bpy.data.actions.new(AnimName)
            obj.animation_data.action = action
            if self.save_fake_users is True:
                action.use_fake_user = True


            try:
                #Opens the yml and deserializes.
                data_loaded = yaml.load(open(AnimYAMLPath, "rb"), Loader=get_loader())
                
                print(data_loaded.version)
                print(data_loaded.Name)
                print(data_loaded.FrameCount)
                print(data_loaded.LoopFrame)
                keycount = 0
                counter = 0
                
                #Adjust the animation timeline to fit the animation and set the current frame to zero.
                #Gets The Current Scene.
                RScene = bpy.context.scene

                RScene.frame_start = 0
                context.scene.frame_start = 0

                RScene.frame_end = data_loaded.FrameCount
                context.scene.frame_end = data_loaded.FrameCount
                bpy.context.scene.frame_set(0)
                
                pose_bones = bpy.data.objects['Armature'].pose.bones
                NewJointName = ""
                for x in range(len(pose_bones)):
                    print(pose_bones[x])
                    
                
                #for idx, data_loaded.KeyFrames in enumerate(data_loaded.Keyframes):
                        #if data_loaded.KeyFrames[idx]['BoneID'] == 255:
                            #continue
                
                
                #Checks if the bone exists on the Armature in the scene and will skip if it doesn't.
                #if bpy.data.objects["Armature"].data.bones.get(f'jnt_{BID}') is None:
                    #contnniue
                
                mip:ModelImportProperties = context.scene.sub_scene_properties

                if mip.anim_import_withmetadata == True and mip.anim_metadata_file != "":
                    #This part applies it to the scene, but to Metadata bones.
                    Track = []
                    for id, Keyframe in enumerate(data_loaded.KeyFrames):
                        
                        BID = data_loaded.KeyFrames[id]['BoneID']

                        if BID == 255:
                            jointName = "jnt_255"
                        else:
                            #Gets The metadata name of the bone.
                            metadata = loadMetadata( self,mip.anim_metadata_file )
                            jointName = metadata.getJointName( BID )

                        #Checks if the bone exists on the Armature in the scene and will skip if it doesn't.
                        if bpy.data.objects["Armature"].data.bones.get(jointName) is None:
                            continue

                        #Selects the bone and deselects everything else.
                        bpy.context.active_object.select_set(False)
                        for obj in bpy.context.selected_objects:
                            bpy.context.view_layer.objects.active = obj

                        obj = bpy.data.objects["Armature"]
                        joint = obj.pose.bones[jointName]
                        jointEdit = bpy.data.armatures["Armature"].bones[jointName].matrix

                        #If the animation range is lower than the current frame, expand the animation range to accomodate.
                        if int(RScene.frame_end < data_loaded.FrameCount):
                            RScene.frame_end = data_loaded.FrameCount
                        
                        print(Keyframe['BoneID'])
                        if (id != 0):
                            #Thing.
                            if(Keyframe['BoneID'] != PrevBoneID or Keyframe['TrackType'] != PrevTrackType):
                                #Apply Stuff here.
                                                        
                                #Go To function when Track is used to apply all keyframes to specified bone.
                                ApplyTheTrack(Track, obj, joint, jointEdit, AnimName, self.import_legacy, mip.anim_import_withmetadata)
                                    
                                #Then we empty the Track.
                                del Track[:]
                                    
                                #Then continue as usual.
                                Track.append(Keyframe)
                                PrevTrackType = Keyframe['TrackType']
                                PrevBoneID = Keyframe['BoneID']
                        
                            else:      
                                Track.append(Keyframe)
                                PrevTrackType = Keyframe['TrackType']
                                PrevBoneID = Keyframe['BoneID']
                
                        else:
                            Track.append(Keyframe)    
                            PrevTrackType = Keyframe['TrackType']
                            PrevBoneID = Keyframe['BoneID']
                else:    
                    Track = []
                    #This part applies it to the scene.
                    for id, Keyframe in enumerate(data_loaded.KeyFrames):
                        
                        BID = data_loaded.KeyFrames[0]['BoneID']

                        #Checks if the bone exists on the Armature in the scene and will skip if it doesn't.
                        if bpy.data.objects["Armature"].data.bones.get(f'jnt_{BID}') is None:
                            continue

                        #Selects the bone and deselects everything else.
                        bpy.context.active_object.select_set(False)
                        for obj in bpy.context.selected_objects:
                            bpy.context.view_layer.objects.active = obj

                        obj = bpy.data.objects["Armature"]
                        joint = obj.pose.bones[f'jnt_{BID}']
                        jointEdit = bpy.data.armatures["Armature"].bones[f'jnt_{BID}'].matrix

                        #If the animation range is lower than the current frame, expand the animation range to accomodate.
                        if int(RScene.frame_end < data_loaded.FrameCount):
                            RScene.frame_end = data_loaded.FrameCount
                        
                        print(Keyframe['BoneID'])
                        if (id != 0):
                            #Thing.
                            if(Keyframe['BoneID'] != PrevBoneID or Keyframe['TrackType'] != PrevTrackType):
                                #Apply Stuff here.
                                                        
                                #Go To function when Track is used to apply all keyframes to specified bone.
                                ApplyTheTrack(Track, obj, joint, jointEdit, AnimName, self.import_legacy, mip.anim_import_withmetadata)
                                    
                                #Then we empty the Track.
                                del Track[:]
                                    
                                #Then continue as usual.
                                Track.append(Keyframe)
                                PrevTrackType = Keyframe['TrackType']
                                PrevBoneID = Keyframe['BoneID']
                        
                            else:      
                                Track.append(Keyframe)
                                PrevTrackType = Keyframe['TrackType']
                                PrevBoneID = Keyframe['BoneID']
                
                        else:
                            Track.append(Keyframe)    
                            PrevTrackType = Keyframe['TrackType']
                            PrevBoneID = Keyframe['BoneID']
                                    
                                    
                                    
                    
                
            
            except Exception as e:
                print("An error occured.",e, "\n", traceback.format_exc())    

#Parts of the code based on the Smash Ultimate Blender Animation Importer.
class SUB_PT_Anim_Import(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'    
    bl_category = 'MT Framework'
    bl_label = 'Animation Importer'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        if context.mode == "POSE" or context.mode == "OBJECT":
            return True
        return False

    def draw(self, context):
        mip:ModelImportProperties = context.scene.sub_scene_properties
        layout = self.layout
        layout.use_property_split = False        
        obj: bpy.types.Object = context.active_object
        row = layout.row()
        if obj is None:
            row.label(text="Select an Armature first.")
        elif obj.select_get() is False:
            row.label(text="Select an Armature first.")   
        elif obj.type == 'ARMATURE':            
            row = layout.row(align=True)
            row.prop(mip, 'anim_import_withmetadata',text='Use Metadata when importing:')
            row = layout.row(align=True)
            row.prop(mip, 'anim_metadata_file')
            row = layout.row(align=True)
            row.operator(SUB_PT_MOD_OT_Choose_Anim_Metadata_YML.bl_idname,icon='IMPORT',text= 'Choose metadata .yml file')
            layout.separator()
            row = layout.row(align=True)
            row.operator('sub.mod_op_add_joint_twofiftyfive', text = 'Add jnt_255 to Selected Armature')
            layout.separator()            
            row = layout.row(align=True)
            row.operator(SUB_OP_anim_import.bl_idname, icon='IMPORT', text='Import Marvel 3 .yml Animation')

class SUB_OP_anim_import(Operator, ImportHelper):
    bl_idname = 'sub.import_anim'
    bl_label = 'Import Anim'
    #bl_options = {'UNDO'}

    filter_glob: StringProperty(
        default='*.yml',
        options={'HIDDEN'}
    )

    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)

    import_legacy: BoolProperty(
        name='Import Animations on Marvel 3 FBX Models.',
        description='Imports in a way that is compatible with the FBX Collection',
        default=False,
    )
    save_fake_users: BoolProperty(
        name='Import With Fake User',
        description='Saves each animation imported as a fake user to ensure they are not discarded when the scene is closed after saving',
        default=True,
    )
    type_b: BoolProperty(
        name='Type B',
        description='For Later use. If unsure, leave False/Unchecked',
        default=False,
    )

    #filepath: StringProperty(subtype="FILE_PATH")

    @classmethod
    def poll(cls, context):
        obj: bpy.types.Object = context.object
        if obj is None:
            return False
        elif obj.type != 'ARMATURE':
            return False
        return True
    
    def invoke(self, context, _event):
        self.first_blender_frame = context.scene.frame_start
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}   
    
    def execute(self, context):
        #keywords = self.as_keywords(ignore=("filter_glob","files"))
        mip:ModelImportProperties = context.scene.sub_scene_properties
        if self.filepath == '' or Path(self.filepath).is_dir():
            self.report({"ERROR"}, f"There was no file selected......")
            ShowMessageBox("There was no file selected. Cancelling.", "Notice", 'ERROR')
            return {'CANCELLED'}
        #ShowMessageBox("There's Nothing Coded here yet.", "Notice")
        time_start = time.time()        
        readM3AanimationData(self, context, self.filepath)
        context.view_layer.update()
        time_end = time.time()
        time_elapsed = time_end - time_start
        print("Import done in "+ str(time_elapsed) + " seconds.", "Notice")
        ShowMessageBox("Import done in "+ str(time_elapsed) + " seconds.")
        return {'FINISHED'}
    
class SUB_PT_MOD_OT_Choose_Anim_Metadata_YML(bpy.types.Operator, ImportHelper):
    """Choose which Metadata YML to Use"""
    bl_idname = "sub.mod_ot_choose_anim_metadata_yml"
    bl_label = "Import YML"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    bl_options = {'UNDO', 'PRESET'}
    filename_ext = ".yml"
    filter_glob: StringProperty(default="*.yml", options={'HIDDEN'})        
    #directory: bpy.props.StringProperty(subtype="FILE_PATH")
    
    def invoke(self, context, event):  # pragma: no cover
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'} 

    def execute(self, context):
        mip:ModelImportProperties = context.scene.sub_scene_properties
        print("You chose:\n", self.filepath)
        mip.anim_metadata_file = self.filepath
        return {'FINISHED'}    
    
class SUB_OP_ADD_JOINT_TWOFIFTYFIVE(bpy.types.Operator):
    bl_idname = 'sub.mod_op_add_joint_twofiftyfive'
    bl_label = "Add jnt_255 to Armature"

    def execute(self,context):
        scene = bpy.context.scene
        #Stores the object selected.
        obj = bpy.context.active_object

        #Changes the blender mode to Edit Mode.
        bpy.ops.object.mode_set(mode = 'EDIT', toggle=False)    

        edit_bones = obj.data.edit_bones

        for bone in edit_bones:
            if bone.parent is None:
                bone.select = True
                root_bone = bone                
                copy_bone = obj.data.edit_bones.new("jnt_255")
                copy_bone.length = root_bone.length
                copy_bone.matrix = root_bone.matrix.copy()
                copy_bone.head[2] = 0
                root_bone.parent = copy_bone
                break

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)        
        return {'FINISHED'}    