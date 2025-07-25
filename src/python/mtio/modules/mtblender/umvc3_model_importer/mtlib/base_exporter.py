from abc import ABC, abstractmethod
import os
from dataclasses import dataclass
from typing import Any, Dict, List
from copy import deepcopy
import bpy
from base_editor import *
import util
from ncl import *
from immodel import *
import textureutil
import shutil
from metadata import *
import yaml
import properties

def _tryParseInt(input, base=10, default=None):
    try:
        return int(str(input).strip(), base=base)
    except Exception:
        return default
    
def _tryParseFloat(input, default=None):
    try:
        return float(str(input).strip())
    except Exception:
        return default

@dataclass(frozen=False,init=False)
class GroupCustomAttributeData:
    id: int
    field04: int
    field08: int
    field0c: int
    bsphere: NclVec4
    index: int

@dataclass(frozen=False,init=False)
class PrimitiveCustomAttributeData:
    flags: int
    groupId: int
    lodIndex: int
    renderFlags: int
    id: int
    field2c: int
    envelopeCount: int
    envelopeIndex: int
    index: int
    vertexShader: str

@dataclass(frozen=False,init=False)
class JointCustomAttributeData:
    id: int
    symmetryNode: EditorNodeProxy
    field03: int
    field04: float
    length: float
    offsetX: float
    offsetY: float
    offsetZ: float
    index: int

class ModelExporterBase(ABC):
    MAX_VERTEX_COUNT = 26758
    MAX_INDEX_COUNT = 63762

    '''Model scene exporter interface'''

    def __init__( self, plugin: EditorPluginBase ):
        self.plugin: EditorPluginBase = plugin
        self.config: EditorPluginConfigBase = plugin.config
        self.logger: EditorPluginLoggerBase = plugin.logger

        self.model = None
        self.editorNodeToJointMap = None
        self.jointToEditorNodeMap = None
        self.jointIdxByName = None
        self.ref = None
        self.textureMapCache = dict()
        self.materialCache = dict()
        self.transformMtx = None
        self.processedNodes = set()
        self.refEnvelopes = []
        self.progressCallback = None

    # Abstract methods
    @abstractmethod
    def getObjects( self ) -> List[EditorNodeProxy]:
        pass

    @abstractmethod
    def updateProgress( self, what, value, count = 0 ):
        pass
        
    @abstractmethod
    def updateSubProgress( self, what, value, count = 0 ):
        pass

    @abstractmethod
    def getEditorGroupCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        pass

    @abstractmethod
    def getEditorPrimitiveCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        pass

    @abstractmethod
    def getEditorJointCustomAttributeData( self, node: EditorNodeProxy  ) -> EditorCustomAttributeSetProxy:
        pass

    @abstractmethod
    def convertPoint3ToNclVec3( self, v: Any ) -> NclVec3:
        pass

    @abstractmethod
    def convertPoint3ToNclVec3UV( self, v: Any) -> NclVec3:
        pass
        
    @abstractmethod
    def convertPoint3ToNclVec4( self, v: Any, w ) -> NclVec3:
        pass
    
    @abstractmethod
    def convertMatrix3ToNclMat43( self, v: Any ) -> NclMat43:
        pass
        
    @abstractmethod
    def convertMatrix3ToNclMat44( self, v: Any ):
        pass

    @abstractmethod
    def processMaterial( self, material ):
        pass

    @abstractmethod
    def processMesh( self, editorNode: EditorNodeProxy ):
        pass

    def getGroupCustomAttributeData( self, node: EditorNodeProxy ) -> GroupCustomAttributeData:
        data = GroupCustomAttributeData()
        attribs = self.getEditorGroupCustomAttributeData( node )
        if attribs != None:
            #version = _tryParseInt(getattr(attribs, '_version', 1)) This property does not seem to exist on this node type.
            data.id = _tryParseInt(attribs.id)
            data.field04 = _tryParseInt(attribs.field04)
            data.field08 = _tryParseInt(attribs.field08)
            data.field0c = _tryParseInt(attribs.field0c)
            data.bsphere = NclVec4(attribs.bsphere[0], attribs.bsphere[1], attribs.bsphere[2], attribs.bsphere[3])
            data.index = _tryParseInt(getattr(attribs, 'index', None))
        else:
            data.id = None
            data.field04 = None
            data.field08 = None
            data.field0c = None
            data.bsphere = None
            data.index = None
        return data

    def getPrimitiveCustomAttributeData( self, node: EditorNodeProxy ) -> PrimitiveCustomAttributeData:
        data = PrimitiveCustomAttributeData()
        attribs = self.getEditorPrimitiveCustomAttributeData( node )
        if attribs != None:
            version = _tryParseInt(getattr(attribs, '_version', 1))
            data.flags = _tryParseInt(attribs.flags, base=0)
            if attribs.groupId == "inherit":
                if node.getParent() != None:
                    data.groupId = self.getGroupCustomAttributeData(node.getParent()).id
                else:
                    # invalid
                    data.groupId = None
            else:
                data.groupId = _tryParseInt(attribs.groupId, base=0)
            data.lodIndex = _tryParseInt(attribs.lodIndex)
            data.renderFlags = _tryParseInt(attribs.renderFlags, base=0)
            data.id = _tryParseInt(attribs.id)
            data.field2c = _tryParseInt(attribs.field2c)
            if version == 1:
                data.envelopeCount = _tryParseInt(getattr(attribs, 'primitiveJointLinkCount', None))
                data.envelopeIndex = _tryParseInt(getattr(attribs, 'primitiveJointLinkIndex', None))
            else:
                data.envelopeCount = _tryParseInt(getattr(attribs, 'envelopeCount', None))
                data.envelopeIndex = _tryParseInt(getattr(attribs, 'envelopeIndex', None))
            data.index = _tryParseInt(getattr(attribs, 'index', None))
            data.vertexShader = attribs.shaderName
        else:
            data.flags = None
            data.groupId = None
            data.lodIndex = None
            data.renderFlags = None
            data.id = None
            data.field2c = None
            data.envelopeCount = None
            data.envelopeIndex = None
            data.index = None
            data.vertexShader = None
            
            if node.getParent() != None:
                # even if no attribs are set, we should still inherit the group id if the mesh is parented to a group
                data.groupId = self.getGroupCustomAttributeData(node.getParent()).id
        return data

    def getJointCustomAttributeData( self, node: EditorNodeProxy, jointMeta: JointMetadata ) -> JointCustomAttributeData:
        data = JointCustomAttributeData()
        attribs = self.getEditorJointCustomAttributeData( node )
        if attribs != None:
            #version = _tryParseInt(getattr(attribs, '_version', 1))
            # grab attributes from custom attributes on node
            data.id = _tryParseInt(attribs.id)
            data.symmetryNode = self.plugin.getNodeByName( attribs.symmetryName )
            # auto detect if symmetry node is not found and symmetry name is set to 'auto'
            if data.symmetryNode == None and attribs.symmetryName == "auto":
                data.symmetryNode = self.detectSymmetryNode( node.getName() )
            data.field03 = _tryParseInt(attribs.field03)
            data.field04 = _tryParseFloat(attribs.field04)
            data.length = _tryParseFloat(attribs.length)
            data.offsetX = _tryParseFloat(attribs.offsetX)
            data.offsetY = _tryParseFloat(attribs.offsetY)
            data.offsetZ = _tryParseFloat(attribs.offsetZ)
            data.index = _tryParseInt(getattr(attribs, 'index', None))
        else:
            if jointMeta != None:
                data.id = jointMeta.id
            else:
                data.id = None
                
            data.symmetryNode = self.detectSymmetryNode( node.getName() )
            data.field03 = None
            data.field04 = None
            data.length = None
            data.offsetX = None
            data.offsetY = None
            data.offsetZ = None
            data.index = None
        return data
            
    def detectSymmetryNode( self, name: str ):
        return self.plugin.getNodeByName( util.replaceSuffix( name, "_l", "_r" ) ) if name.endswith("_l") else \
               self.plugin.getNodeByName( util.replaceSuffix( name, "_r", "_l" ) ) if name.endswith("_r") else \
               self.plugin.getNodeByName( util.replaceSuffix( name, "_L", "_R" ) ) if name.endswith("_L") else \
               self.plugin.getNodeByName( util.replaceSuffix( name, "_R", "_L" ) ) if name.endswith("_R") else \
               self.plugin.getNodeByName( util.replaceSuffix( name, "L", "R" ) ) if name.endswith("L") else \
               self.plugin.getNodeByName( util.replaceSuffix( name, "R", "L" ) ) if name.endswith("R") else \
               None

    def shouldExportNode( self, node: EditorNodeProxy ):
        '''Returns if the node should be included in the export'''
        if node.isHidden():
            return False
        if self.config.lukasCompat and (node.isBoneNode() and node.getName() == 'bone255'):
            return False
        return True

    def shouldExportBoneNode( self, node: EditorNodeProxy ):
        '''Returns if the node should be included in the export'''
        if node.isBoneHidden():
            return False
        if self.config.lukasCompat and (node.isBoneNode() and node.getName() == 'bone255'):
            return False
        return True

    def getNodeBoneLocalMtx( self, mip, node: EditorNodeProxy ) -> Any:
        worldMtx = node.getTransform()
        if node.node.parent is None or node.getParent() is None:
             parentWorldMtx = nclCreateMat44()
        elif self.shouldExportBoneNode( node.getParent() ):
            parentWorldMtx = node.getParent().getTransform()
        #parentWorldMtx = node.getParent().getTransform() if node.getParent() is not None and self.shouldExportBoneNode( node.getParent() ) else nclCreateMat44()
        localMtx = nclMultiply( worldMtx, nclInverse( parentWorldMtx ) )
        if self.plugin.config.exportBakeScale:
            localMtx[3] *= NclVec4((self.plugin.config.exportScale, self.plugin.config.exportScale, self.plugin.config.exportScale, 1))
            if node.getParent() is None or node.node.parent is None or not self.shouldExportBoneNode(node.getParent()):
                localMtx = self.transformMtxNoScale * localMtx
        else:
            if node.getParent() is None or node.node.parent is None or not self.shouldExportBoneNode(node.getParent()):
                localMtx = self.transformMtx * localMtx
        return localMtx

    def getNodeLocalMtx( self, mip, node: EditorNodeProxy ) -> Any:
        worldMtx = node.getTransform()
        parentWorldMtx = node.getParent().getTransform() if node.getParent() is not None and self.shouldExportNode( node.getParent() ) else nclCreateMat44()
        localMtx = nclMultiply( worldMtx, nclInverse( parentWorldMtx ) )
        if self.plugin.config.exportBakeScale:
            localMtx[3] *= NclVec4((self.plugin.config.exportScale, self.plugin.config.exportScale, self.plugin.config.exportScale, 1))
            if node.getParent() is None or not self.shouldExportNode(node.getParent()):
                localMtx = self.transformMtxNoScale * localMtx
        else:
            if node.getParent() is None or not self.shouldExportNode(node.getParent()):
                localMtx = self.transformMtx * localMtx
        return localMtx
    
        # arma = bpy.data.objects['Armature']
        # worldMtx = arma.matrix_world @ node.node.matrix
        # if node.getParent() is not None and self.shouldExportNode( node.getParent()):
        #     ParentNode = node.getParent()
        #     parentWorldMtx = arma.matrix_world @ ParentNode.node.matrix
        # else:
        #     parentWorldMtx = nclCreateMat44()
        # localMtx = nclMultiply( worldMtx, nclInverse( parentWorldMtx ) )

        # if mip.export_bake_scale:
        #     localMtx[3] *= NclVec4((mip.export_model_scale, mip.export_model_scale, mip.export_model_scale, 1))
        #     if node.getParent() is None or not self.shouldExportNode(node.getParent()):
        #         localMtx = self.transformMtxNoScale * localMtx
        # else:
        #     if node.getParent() is None or not self.shouldExportNode(node.getParent()):
        #         localMtx = self.transformMtx * localMtx
        # return localMtx

    def getNodeWorldMtx( self, node: EditorNodeProxy ) -> Any:
        worldMtx = node.getTransform() 
        if self.config.exportBakeScale:
            worldMtx[3] *= NclVec4((self.config.exportScale, self.config.exportScale, self.config.exportScale, 1))
        return worldMtx

    def processBone( self, mip, editorNode: EditorNodeProxy ): 
        assert( editorNode.isBoneNode() )

        if editorNode.unwrap() in self.editorNodeToJointMap:
            # prevent recursion
            return self.editorNodeToJointMap[editorNode.unwrap()]

        self.logger.info(f'processing bone: {editorNode.getName()}')
        jointMeta = self.metadata.getJointByName( editorNode.getName() )
        attribs = self.getJointCustomAttributeData( editorNode, jointMeta )
        localMtx = self.getNodeBoneLocalMtx( mip, editorNode )
        
        joint = imJoint(
            name=editorNode.getName(), 
            id=attribs.id if attribs.id != None else len(self.model.joints) + 1, 
            localMtx=localMtx,
            #parent=self.processBone( editorNode.getParent() ) if editorNode.getParent() is not None and self.shouldExportNode( editorNode.getParent() ) else None, # must be specified here to not infere with matrix calculations
            field03=attribs.field03,
            field04=attribs.field04,
            length=attribs.length,
            invBindMtx=None,    # TODO copy from attribs (?)
            offset=None,        # TODO copy from attribs (?)
            symmetry=None,      # need to create current joint first to resolve self and forward references
            index=attribs.index,
        )
        
        self.editorNodeToJointMap[editorNode.unwrap()] = joint
        parent = self.processBone( mip, editorNode.getParent() ) if (editorNode.getParent() is not None or editorNode.node.parent is not None) and self.shouldExportBoneNode( editorNode.getParent() ) else None
        if parent is not None:
            joint.setParent( parent )

        self.jointToEditorNodeMap[joint] = editorNode
        self.model.joints.append( joint )
        self.jointIdxByName[ joint.name ] = len( self.model.joints ) - 1
        
    def iterBoneNodes( self ):

        #process all bones in the scene(TGE's Original Code)
        for editorNode in self.getObjectBones():
            if not self.shouldExportBoneNode( editorNode ) or not editorNode.isBoneNode():
                continue

            yield editorNode

        # # Get the selected Armature first.
        # for editorNode in self.getObjects():
        #     obj = bpy.context.active_object
        #     if editorNode.node.name == obj.name:
        #         # Now the bones.
        #         for ChildNode in editorNode.node.data.bones:
        #             obj = ChildNode
        #             yield obj
        #     else:
        #         continue

        # # process all bones in the scene
        # for editorNode in self.getObjects():
        #     #Gotta get the Armature to get the bones first. Also want to ensure the Armature's name matches.            
        #     if editorNode.node.type == 'ARMATURE' and editorNode.node.name == bpy.context.selected_objects[0].name:
        #         arm = editorNode.node
        #         # for ChildNode in bpy.data.armatures[arm.name].bones:
        #         # editorNode.node = bpy.data.armatures[arm.name].bones[0]
        #         #     if editorNode.isBoneNode():
        #         for index ,ChildNode in enumerate(bpy.data.armatures[arm.name].bones):
        #             editorNode.node = bpy.data.armatures[arm.name].bones[index]
        #             yield editorNode
        #     else:
        #         continue

        # process all bones in the scene(TGE's Original Code)
        # for editorNode in self.getObjects():
        #     if not self.shouldExportNode( editorNode ) or not editorNode.isBoneNode():
        #         continue

        #     yield editorNode

        # # process all bones in the scene(Previous Fixing Attempt)
        # for editorNode in self.getObjects():
        #     #Gotta get the Armature to get the bones first.
        #     if editorNode.node.type == 'ARMATURE':
        #         arm = editorNode.node
        #         for ChildNode in bpy.data.armatures[arm.name].bones:
        #             editorNode.node = ChildNode
        #             if editorNode.isBoneNode():
        #                 yield editorNode
        #     else:
        #         continue
    
    def processBones( self, mip ):
        if not self.config.exportSkeleton:
            self.logger.info('processing bones skipped because it has been disabled through the config')
            return
        
        self.logger.info('processing bones')
        
        # convert all joints first
        # so we can reference them when building the primitives
        self.editorNodeToJointMap = dict()
        self.jointToEditorNodeMap = dict()
        self.jointIdxByName = dict()
        #bpy.ops.object.mode_set(mode='EDIT',toggle=False)

        if self.ref != None and self.config.exportUseRefJoints:
            # copy over original joints
            self.logger.info('copying bones from reference model')
            for i, refJoint in enumerate(self.ref.joints):
                joint = imJoint(
                    name=self.metadata.getJointName(refJoint.id),
                    id=refJoint.id,
                    localMtx=self.ref.jointLocalMtx[i],
                    invBindMtx=self.ref.jointInvBindMtx[i],
                    parent=self.model.joints[refJoint.parentIndex] if refJoint.parentIndex != 255 else None,
                    symmetry=None, # resolve later
                    field03=refJoint.field03,
                    field04=refJoint.field04,
                    length=refJoint.length,
                    offset=refJoint.offset,
                )

                self.jointIdxByName[joint.name] = i
                self.model.joints.append(joint)

            for i, joint in enumerate(self.model.joints):
                refJoint = self.ref.joints[i]
                joint.symmetry = self.model.joints[refJoint.symmetryIndex] if refJoint.symmetryIndex != 255 else None
        else:
            # process all bones in the scene
            boneNodes = list(self.iterBoneNodes())

            #Rewritten function to get all the joints of the selected Armature.
            # boneNodes = []
            # for editorNode in self.getObjects():
            #     #Gotta get the Armature to get the bones first. Also want to ensure the Armature's name matches.            
            #     if editorNode.node.type == 'ARMATURE' and editorNode.node.name == bpy.context.selected_objects[0].name:
            #         arm = editorNode.node
            #         for i, ChildNode in enumerate(bpy.data.armatures[arm.name].bones):
            #             boneNodes.append(bpy.data.armatures[arm.name].bones[i])                            
            #     else:
            #         continue

            for i, editorNode in enumerate( boneNodes ):
                self.updateProgress( 'Processing bones', i, len(boneNodes) )
                self.processBone( mip, editorNode )
                self.processedNodes.add( editorNode )

            # resolve references
            for joint in self.model.joints:
                editorNode = self.jointToEditorNodeMap[joint]
                jointMeta = self.metadata.getJointByName( editorNode.getName() )
                attribs = self.getJointCustomAttributeData( editorNode, jointMeta )
                joint.symmetry = self.processBone(mip, attribs.symmetryNode ) if attribs.symmetryNode != None else None

        bpy.ops.object.mode_set(mode='OBJECT',toggle=False)        

    def convertTextureToTEX( self, filename, context ):
        if filename != None and not filename in self.textureMapCache:
            # add to cache
            self.textureMapCache[filename] = True
            
            self.logger.info(f'processing texture: {filename}')
            if os.path.exists(filename):
                relPath = self.getTextureMapResourcePathOrDefault( filename, None, None, context )
                fullPath = mip.extracted_archive_directory + '/' + relPath
                
                if self.outPath.hash != None:
                    texPath = fullPath + '.241f5deb.tex'
                else:
                    texPath = fullPath + '.tex'
                if self.config.exportOverwriteTextures or not os.path.exists(texPath):
                    self.logger.info('converting texture to TEX')
                    try:
                        textureutil.convertTexture( filename, texPath )
                    except PermissionError as e:
                        raise RuntimeError( f"unable to save tex file, make sure you have write permissions to {texPath}" )
                else:
                    self.logger.info(f'skipping texture conversion because {texPath} already exists')
            else:
                self.logger.info(f'skipping texture conversion because {filename} does not exist')
                
    def getTextureMapResourcePathInternal( self, name ):
        if self.outPath.relBasePath != None:
            # take the relative directory path of the model and append the name of the texture
            result = self.outPath.relBasePath + '\\' + name
        else:
            # because the model output path is not relative to the root, we put the texture at the root
            # the user will likely have to fix this
            result = name
        return result
            
    def getTextureMapResourcePathOrDefault( self, filename, default, context ):
        if filename == None: return self.getTextureMapResourcePathInternal( default )
        path = util.ResourcePath( filename, rootPath=mip.extracted_archive_directory )
        result = self.getTextureMapResourcePathInternal( path.baseName )
        result = result.replace('/', '\\')
        return result
    
    def copyUsedDefaultTexturesToOutput( self, material ):
        for map in material.iterTextures():
            if imMaterialInfo.isDefaultTextureMap( map ):
                # make sure to export the default textures whenever they are used
                defaultMapTexPath = os.path.join( util.getResourceDir(), 'textures', os.path.basename( map ) + ".tex" )
                
                if map[0] != '\\':
                    # add separator if it's somehow missing
                    map = '\\' + map
                    
                defaultMapTexExportPath = mip.extracted_archive_directory + map + '.tex' if self.outPath.hash == None else \
                                          mip.extracted_archive_directory + map + '.241f5deb.tex'

                shutil.copy( defaultMapTexPath, defaultMapTexExportPath )

    def getMaterialName( self, material: EditorMaterialProxy ):
        if material == None:
            return 'default_material'
        else:
            return material.getName()
            
    def iterMeshNodes( self ):
        for editorNode in self.getObjects():
            if not self.shouldExportNode( editorNode ):
                continue
            
            if not editorNode.isMeshNode() and not editorNode.isSplineNode():
                continue
            
            yield editorNode

    def generatePrimitives( self, editorNode: EditorNodeProxy, attribs: PrimitiveCustomAttributeData, 
        primWorkingSets: Dict[int, imPrimitiveWorkingSet] ):
        for i, primWorkingSet in enumerate(primWorkingSets.values()):
            primWorkingSet: imPrimitiveWorkingSet
            
            for prim in primWorkingSet.primitives:
                prim: imPrimitive
                if self.plugin.updateUI(): self.updateProgress( "Optimizing submesh", i, len(primWorkingSets) )
                self.logger.info(f'processing submesh with material {prim.materialName}')

                # copy over attribs
                if attribs.flags != None: prim.flags = attribs.flags
                if attribs.groupId != None: 
                    group = self.model.getGroupById(attribs.groupId)
                    if group == None:
                        # add group
                        group = imGroup(self.metadata.getGroupName(attribs.groupId), attribs.groupId)
                        self.model.groups.append(group)
                    prim.group = group
                elif self.config.exportGroupPerMesh:
                    prim.group = imGroup(editorNode.getName() + '_' + str(i), len(self.model.groups)+1)
                    self.model.groups.append(prim.group)
                        
                if attribs.lodIndex != None: prim.lodIndex = attribs.lodIndex
                if attribs.renderFlags != None: prim.renderFlags = attribs.renderFlags
                if attribs.id != None: prim.id = attribs.id
                if attribs.field2c != None: prim.field2c = attribs.field2c
                if attribs.envelopeCount != None and attribs.envelopeIndex != None and len( self.refEnvelopes ) > 0: 
                    # add envelopes from ref to the primitive
                    for i in range(attribs.envelopeIndex, attribs.envelopeIndex+attribs.envelopeCount):
                        prim.envelopes.append(self.refEnvelopes[i])
                elif self.config.exportGenerateEnvelopes:
                    # TODO local transform/pivot, link to joint(s)
                    prim.envelopes.append(imEnvelope())
                if attribs.index != None: prim.index = attribs.index
                if attribs.vertexShader != None: prim.vertexFormat = imVertexFormat.createFromShader( attribs.vertexShader )
                
                if self.config.debugExportForceShader != '':
                    # force shader on export if specified
                    prim.vertexFormat = imVertexFormat.createFromShader( self.config.debugExportForceShader )
                    
                self.logger.debug( "trimming uvs" )
                prim.removeUnusedUvs( self.progressCallback )
                                
                if prim.hasUvs():
                    self.logger.debug( "generating tangents" )
                    prim.generateTangents( self.progressCallback )
                
                self.logger.debug( "optimizing mesh" )
                prim.makeIndexed( self.progressCallback )
                if target.current.useTriStrips:
                    prim.generateTriStrips( self.progressCallback )
                
                self.model.primitives.append( prim )
        
    def processMeshes( self ):
        if not self.config.exportPrimitives:
            self.logger.info('exporting meshes skipped because it has been disabled through the config')
            return
        
        # convert meshes
        self.logger.info('processing meshes')
        meshNodes = list(self.iterMeshNodes())
        for i, editorNode in enumerate( meshNodes ):
            self.updateProgress('Processing meshes', i, len( meshNodes ) )
            self.processMesh( editorNode )
            self.processedNodes.add( editorNode )
            
    def iterGroupNodes( self ):
        # process all groups in the scene
        for editorNode in self.getObjects():
            if not self.shouldExportNode( editorNode ) or not editorNode.isGroupNode():
                continue
            yield editorNode

    def processGroups( self, mip ):
        if not mip.export_groups:
            self.logger.info('exporting groups skipped because it has been disabled through the config')
            return
        
        self.logger.info('processing groups')
        if self.ref != None and self.config.exportUseRefGroups:
            self.logger.info('copying groups from reference model')
            for i, refGroup in enumerate(self.ref.groups):
                group = imGroup(
                    name=self.metadata.getGroupName(refGroup.id),
                    id=refGroup.id,
                    field04=refGroup.field04,
                    field08=refGroup.field08,
                    field0c=refGroup.field0c,
                    boundingSphere=refGroup.boundingSphere,
                    index=i,
                )
                self.model.groups.append(group)
        else:
            # process all groups in the scene
            groupNodes = list(self.iterGroupNodes())
            for i in range( 0, len( groupNodes ) ):
                self.updateProgress( 'Processing groups', i, len( groupNodes ) )
                editorNode = groupNodes[i]
                
                self.logger.info(f'processing group node {editorNode.getName()}')
                attribs = self.getGroupCustomAttributeData(editorNode)
                group = imGroup(
                    name=editorNode.getName(),
                    id=attribs.id,
                    field04=attribs.field04 if attribs.field04 != None else 0,
                    field08=attribs.field08 if attribs.field08 != None else 0,
                    field0c=attribs.field0c if attribs.field0c != None else 0,
                    boundingSphere=attribs.bsphere if attribs.bsphere != None else None,
                    index=attribs.index,
                )
                self.model.groups.append(group)
                self.processedNodes.add( editorNode )
                
    def processEnvelope( self ):
        if not self.config.exportEnvelopes:
            self.logger.info('exporting envelope skipped because it has been disabled through the config')
            return
        
        self.logger.info('processing envelope')
        if self.ref != None and self.config.exportUseRefEnvelopes:
            self.logger.info('copying envelope from reference model')
            for i, refEnvelope in enumerate(self.ref.envelopes):
                envelope = imEnvelope(
                    name='env_'+str(i),
                    joint=self.model.joints[refEnvelope.jointIndex] if refEnvelope.jointIndex != 255 else None,
                    field04=refEnvelope.field04,
                    field08=refEnvelope.field08,
                    field0c=refEnvelope.field0c,
                    boundingSphere=refEnvelope.boundingSphere,
                    min=refEnvelope.min,
                    max=refEnvelope.max,
                    localMtx=refEnvelope.localMtx,
                    field80=refEnvelope.field80,
                    index=i,
                )
                self.refEnvelopes.append( envelope )
        else:
            # TODO: represent these in the scene
            self.logger.debug("exporting envelope from scene not implemented")
    
    def writeBinaries( self ):
        self.logger.info('writing files')
        self.logger.debug('converting intermediate model to binary model format')
        self.updateProgress( 'Writing files', 0 )
        binMod = self.model.toBinaryModel( self.progressCallback )
        self.updateProgress( 'Writing files', 25 )
        
        self.logger.debug('writing binary model')
        stream = NclBitStream()
        binMod.write( stream )
        try:
            util.saveByteArrayToFile( self.outPath.fullPath, stream.getBuffer() )
        except PermissionError as e:
            raise RuntimeError( f"Unable to save mod file, make sure you have write permissions to {self.outPath.fullPath}" )
        
        if self.outPath.hash != None:
            mrlExportPath = self.outPath.basePath + '/' + self.outPath.baseName + '.2749c8a8.mrl' 
        else:
            mrlExportPath = self.outPath.basePath + '/' + self.outPath.baseName + '.mrl'
            
        self.updateProgress( 'Writing files', 50 )
        if self.config.exportGenerateMrl:
            mrlYmlExportPath = mrlExportPath + ".yml"
            self.logger.info(f"writing generated mrl yml to {mrlYmlExportPath}")
            self.mrl.updateTextureList()
            try:
                self.mrl.saveYamlFile( mrlYmlExportPath )
            except PermissionError as e:
                raise RuntimeError( f"Unable to save mrl yml file, make sure you have write permissions to {mrlYmlExportPath}" )
          
        self.updateProgress( 'Writing files', 75 )  
        if self.config.exportGenerateMrl or (self.config.exportExistingMrlYml and self.mrl != None):
            self.logger.info(f'exporting mrl yml to {mrlExportPath}')
            
            try:
                self.mrl.saveBinaryFile( mrlExportPath )
            except PermissionError as e:
                raise RuntimeError( f"Unable to save mrl file, make sure you have write permissions to {mrlExportPath}" )
            
        self.updateProgress( 'Writing files', 100 )
    
    def calcMatrices( self ):
        self.transformMtx = nclCreateMat44()
        if self.config.flipUpAxis:
            self.transformMtx *= util.Z_TO_Y_UP_MATRIX
            
        self.scaleMtx = nclScale( self.config.exportScale )
        self.transformMtxNoScale = deepcopy( self.transformMtx )
        self.transformMtx *= self.scaleMtx
        self.transformMtxNormal = nclTranspose( nclInverse( self.transformMtx ) )
    
    def exportModel( self, path, context ):
        self.logger.info(f'script version: {self.plugin.version}')
        self.logger.info(f'exporting to {path}')
        
        #Chose to make a dedicated bool for disabling Metadata.
        mip:ModelImportProperties = context.scene.sub_scene_properties

        # start building intermediate model data for conversion
        self.model = imModel()
        if mip.export_use_reference_model == True:
            self.ref = mip.export_reference_model_file
        else:
            self.ref = None
        self.path = mip.export_modelpath
        self.rootpath = mip.extracted_archive_directory
        self.outPath = util.ResourcePath(path, rootPath=mip.extracted_archive_directory)
        if self.outPath.relBasePath == None:
            raise RuntimeError(
"The model export path is not in a subfolder of the specified extracted archive directory.\n"+
"If your extracted archive directory is C:\\Export, the model export path should start with C:\\Export.")
        
        self.metadata = ModelMetadata()
        self.mrl = None
        self.calcMatrices()

        if mip.export_withmetadata:
            if os.path.exists( self.config.exportMetadataPath ):
                self.logger.info(f'loading metadata file from {mip.export_withmetadata}')
                self.metadata.loadFile( self.config.exportMetadataPath )
        # else:
        #     blank = ''
        #     self.metadata = blank
        
        if os.path.exists( mip.export_reference_model_file ):
            self.logger.info(f'loading reference model from {mip.export_reference_model_file}')
            self.ref = rModelData()
            self.ref.read( NclBitStream( util.loadIntoByteArray( mip.export_reference_model_file ) ) )
            
        if os.path.exists( mip.existing_mrl_yml ):
            self.logger.info(f'loading mrl yml from {mip.existing_mrl_yml}')
            self.mrl = imMaterialLib()
            self.mrl.loadYamlFile( mip.existing_mrl_yml )
        elif self.config.exportGenerateMrl:
            self.logger.info(f'generating new mrl')
            self.mrl = imMaterialLib()
            
        self.logger.debug('creating output directories')
        if not os.path.exists( mip.extracted_archive_directory ):
            os.makedirs( mip.extracted_archive_directory )
        if not os.path.exists( os.path.dirname( mip.export_modelpath ) ):
            os.makedirs( mip.export_modelpath )


        self.logger.info('processing scene')
        if mip.export_reference_model_file != None and mip.export_use_reference_model:
            # copy over header values
            self.logger.debug('copying over header values from reference model')
            self.model.field90 = self.ref.header.field90
            self.model.field94 = self.ref.header.field94
            self.model.field98 = self.ref.header.field98
            self.model.field9c = self.ref.header.field9c
            self.model.center = self.ref.header.center
            self.model.max = self.ref.header.max
            self.model.min = self.ref.header.min
            self.model.radius = self.ref.header.radius
        
        # groups share types with bones, so we must disambiguate carefully
        # it's easier to distinguish a group from a bone, so process the groups first
        self.processGroups(mip)
        
        # after the groups have been processed, there should be no room for error when finding
        # the bones in the scene
        self.processBones(mip)
        self.processEnvelope()
        self.processMeshes()
        self.writeBinaries()
        
        self.updateProgress( 'Done', 0 )
        self.updateSubProgress( '', 0 )
        self.logger.info('export completed successfully')