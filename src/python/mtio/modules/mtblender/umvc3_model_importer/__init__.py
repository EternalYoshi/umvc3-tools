bl_info = {
"name": "UMVC3 Model Importer",
"description":"For importing UMVC3 Models.",
"author":"Most Underlying code by TGE, adapted by Eternal Yoshi",
"version":(0,0,1),
"blender":(3,4,0),
"location": "View 3D > Tool Shelf > MT Framework",
"warning": "In progress.",
"category":"All",
}

def isDebugEnv():
    import os
    return os.path.exists( os.path.join( os.path.dirname( __file__ ), '.debug' ) )

def attachDebugger():
    try:
        import ptvsd
        print( ptvsd.enable_attach() )
    except:
        pass

#from mtlib import *
import bpy
import nodeitems_utils
import os, sys, time, traceback, mathutils, re, subprocess, enum, math
import numpy as np
#from rshader import rShaderObjectId
#import util, rmodel
#import bmesh, struct
from mathutils import Vector, Matrix
from mathutils import Euler

# Import Code.
#from bpy_extras.io_utils import ImportHelper
#from bpy_extras.io_utils import ExportHelper

#From the newer Smash Ultimate Model Importer.
def check_unsupported_blender_versions():
    if bpy.app.version < (3, 4):
        raise ImportError('Unfortunately versions earlier than 3.4 cannot be used. Please use Blender 3.4 - 4.0.')
    
def register():
    check_unsupported_blender_versions()

    from . import modules
    from . import mtlib
    import properties

    from .bpy_classes import classes
    # for cls in reversed(classes):
    #     try:
    #         bpy.utils.unregister_class(cls)
    #     except RuntimeError as e:
    #         print(f'Failed to unregister thing; Error="{e}" ; Traceback=\n{traceback.format_exc()}')

    for cls in classes:
        bpy.utils.register_class(cls)

    properties.register()
    
    print('\nLoaded!')

def unregister():
    from . import modules
    from . import mtlib
    import properties
    
    from .bpy_classes import classes
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError as e:
            print(f'Failed to unregister thing; Error="{e}" ; Traceback=\n{traceback.format_exc()}')



if __name__ == "__main__":
    register()    
