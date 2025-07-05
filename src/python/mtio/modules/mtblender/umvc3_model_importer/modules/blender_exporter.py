from typing import Dict
from ..mtlib import *
from ..mtlib.ncl import *
from ..mtlib.base_editor import *
from ..mtlib.base_exporter import *
from .blender_plugin import *
import bpy

def progressCallback( what, i, count ):
    pass

def assertBlenderMode(expectedMode:str):
    try:
        bpy.context.object.mode == expectedMode
    except AttributeError:
        return expectedMode == 'OBJECT'

class BlenderModelExporter(ModelExporterBase):
    def __init__(self) -> None:
        super().__init__(plugin)
        self.progressCallback = progressCallback

    def getObjects( self ):
        temp = list(bpy.data.objects)
        objects = []
        for o in temp:
            if not o in self.processedNodes:
                objects.append( BlenderNodeProxy( o ) )
        return objects

    #Based on the above method to ensure that we get joints as they are not included in bpy.data.objects.
    def getObjectBones( self ):
        temp = list(bpy.data.objects)
        objects = []
        for o in temp:
            if not o in self.processedNodes:
                #Ensures we only get the bones from the Armature selected and adds all of them.
                if o.type == 'ARMATURE' and o.name == bpy.context.selected_objects[0].name:
                    # for ChildNode in enumerate(bpy.data.armatures[o.name].bones):
                    for ChildNode in bpy.data.armatures[o.name].bones:
                        #o.node = ChildNode
                        objects.append( BlenderNodeProxy( ChildNode ) )


        return objects

    # def getObjectBones( self ):
    #     temp = list(bpy.data.objects)
    #     objects = []
    #     for o in temp:
    #         if not o in self.processedNodes:
    #             if o.type == 'ARMATURE' and o.name == bpy.context.selected_objects[0].name:
    #                 for ChildNode in enumerate(bpy.data.armatures[o.name].bones):
    #                     objects.append( BlenderNodeProxy( ChildNode ) )


    #     return objects


    def updateProgress( self, what, value, count = 0 ):
        self.logger.debug( f'updateProgress({what},{value},{count})')
        
    def updateSubProgress( self, what, value, count = 0 ):
        self.logger.debug( f'updateSubProgress({what},{value},{count})')

    def getEditorGroupCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(node.unwrap())

    def getEditorPrimitiveCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(node.unwrap())

    def getEditorJointCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(node.unwrap())

    def convertPoint3ToNclVec3( self, v ) -> NclVec3:
        return NclVec3((v[0], v[1], v[2]))

    def convertPoint3ToNclVec3UV( self, v ) -> NclVec3:
        return NclVec3((v[0], 1 - v[1], v[2]))
        
    def convertPoint3ToNclVec4( self, v, w ) -> NclVec3:
        return NclVec4((v[0], v[1], v[2], w))
    
    def convertMatrix3ToNclMat43( self, v ) -> NclMat43:
        return nclCreateMat43((self.convertPoint3ToNclVec3(v[0]), 
                               self.convertPoint3ToNclVec3(v[1]), 
                               self.convertPoint3ToNclVec3(v[2]), 
                               self.convertPoint3ToNclVec3(v[3])))
        
    def convertMatrix3ToNclMat44( self, v ):
        return nclCreateMat44((self.convertPoint3ToNclVec4(v[0], 0), 
                               self.convertPoint3ToNclVec4(v[1], 0), 
                               self.convertPoint3ToNclVec4(v[2], 0), 
                               self.convertPoint3ToNclVec4(v[3], 1)))

    def processMaterial( self, material: EditorMaterialProxy ):
        self.logger.debug( f'processMaterial({material})')

    def processMesh( self, editorNode: EditorNodeProxy ):
        self.logger.debug( f'processMesh({editorNode})')