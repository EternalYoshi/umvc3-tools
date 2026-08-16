import copy
from ..mtlib import *
from ..mtlib.base_importer import *
from . import blender_plugin
from .blender_plugin import *
import bpy
import mathutils
import array
import yaml
import numpy as np

def assertBlenderMode(expectedMode:str):
    try:
        bpy.context.object.mode == expectedMode
    except AttributeError:
        return expectedMode == 'OBJECT'

class BlenderModelImporter(ModelImporterBase):
    def __init__(self):
        super().__init__(blender_plugin.plugin)
        self.armature = None
        self.armatureObj = None

    def setUserProp(self, obj: EditorNodeProxy, key: str, value: Any):
        assertBlenderMode('OBJECT')
        bone = self.armature.bones.get(obj.getName())
        bone[key] = value

    def setInheritanceFlags( self, bone, flags ):
        self.logger.debug(f'setInheritanceFlags({bone},{flags})')

    def normalize( self, vector ):
        length = vector.length
        if length == 0:
            return mathutils.Vector((0, 0, 0))
        return vector / length

    def transformPoint( self, point, matrix ):
        return matrix @ point

    # Progress functions
    def updateProgress( self, what, value, count = 0 ):
        self.logger.debug(f'updateProgress({what},{value},{count})')
        
    def updateSubProgress( self, what, value, count = 0 ):
        self.logger.debug(f'updateSubProgress({what},{value},{count})')

    # Layer functions
    def newLayerFromName( self, name ):
        self.logger.debug(f'newLayerFromName({name})')
        layer = bpy.data.collections.new(name)
        if layer is None: return None
        bpy.context.scene.collection.children.link(layer)
        return BlenderLayerProxy(layer)
        
    def getLayerFromName( self, name ):
        self.logger.debug(f'getLayerFromName({name})')
        layer = bpy.data.collections.get(name)
        if layer is None: return None
        return BlenderLayerProxy(layer)

    # Convert functions
    def convertNclVec3ToPoint3( self, value ):
        return mathutils.Vector((value[0], value[1], value[2]))

    def convertNclVec4ToPoint4( self, value ):
        return mathutils.Vector((value[0], value[1], value[2], value[3]))
        
    def convertNclMat44ToMatrix( self, value ):
        matrix = mathutils.Matrix((
            self.convertNclVec4ToPoint4( value[0] ),
            self.convertNclVec4ToPoint4( value[1] ),
            self.convertNclVec4ToPoint4( value[2] ),
            self.convertNclVec4ToPoint4( value[3] )
        ))
        matrix.transpose()
        return matrix
        
    def convertNclMat43ToMatrix( self, value ):
        matrix = mathutils.Matrix(( 
            self.convertNclVec3ToPoint3( value[0] ), 
            self.convertNclVec3ToPoint3( value[1] ), 
            self.convertNclVec3ToPoint3( value[2] ), 
            self.convertNclVec3ToPoint3( value[3] ) 
        ))
        matrix.transpose()
        return matrix

    def convertMatrixToNclMat44(self, matrix):
        """Reverse of convertNclMat44ToMatrix()"""
        mtx = matrix.copy()
        mtx.transpose()  # Blender is column-major, NCL is row-major

        ncl_mat = [
            self.convertPoint4ToNclVec4(mtx[0]),
            self.convertPoint4ToNclVec4(mtx[1]),
            self.convertPoint4ToNclVec4(mtx[2]),
            self.convertPoint4ToNclVec4(mtx[3]),
        ]
        return ncl_mat

    # Import functions
    def importPrimitive( self, primitive, envelopeIndex, indexStream, vertexStream, context ):
        def setUVMap(mesh, faces,array,name):
            if len(array) > 0:
                uvs = []
                for f in faces:
                    for fi in f:
                        uv = array[fi]
                        uvs.append(uv[0])
                        uvs.append(uv[1])
                layer = mesh.uv_layers.new(name=name)
                layer.data.foreach_set("uv", uvs)

        shaderInfo: ShaderObjectInfo = mvc3shaderdb.shaderObjectsByHash[ primitive.vertexShader.getHash() ]
        self.logger.debug( f'shader {shaderInfo.name} ({hex(shaderInfo.hash)})')

        # read vertices
        vertexData = self.decodeVertices( primitive, shaderInfo, 
            vertexStream )

        # read faces
        faceArray = self.decodeFaces( primitive, indexStream )
        
        # build mesh object
        self.logger.debug('creating mesh')
        mesh_name = self.metadata.getPrimitiveName(primitive.id)
        verts = [(v[0], v[1], v[2]) for v in vertexData.vertexArray]
        faces = [(int(f[0]), int(f[1]), int(f[2])) for f in faceArray]
        
        mesh = bpy.data.meshes.new(mesh_name+'.mesh')
        obj = bpy.data.objects.new(mesh_name, mesh)
        obj.data.materials.append(self.editorMaterialArray[primitive.indices.getMaterialIndex()].unwrap())
        self.setPrimitiveCustomAttributes( primitive, shaderInfo, BlenderNodeProxy(obj), envelopeIndex )
        if self.layer != None:
            # add to layer
            self.layer.unwrap().objects.link(obj)
        else:
            # add to scene
            bpy.context.scene.collection.objects.link(obj)

        mesh.from_pydata(verts, [], faces)
        setUVMap(mesh, faces, vertexData.uvPrimaryArray, 'UVPrimary')
        setUVMap(mesh, faces, vertexData.uvSecondaryArray, 'UVSecondary')
        setUVMap(mesh, faces, vertexData.uvExtendArray, 'UVExtend')
        setUVMap(mesh, faces, vertexData.uvUniqueArray, 'UVUnique')

        # Stage formats (IANonSkinBC/BCA/TBNL) carry baked per vertex colour and alpha.
        # Store it as a POINT domain byte colour so the exporter can read it straight
        # back per vertex, no corner mapping needed.
        if len( vertexData.colorArray ) == len( verts ):
            try:
                layer = mesh.color_attributes.new( name='VertexColor', type='BYTE_COLOR', domain='POINT' )
                for i, c in enumerate( vertexData.colorArray ):
                    layer.data[i].color = ( c[0], c[1], c[2], c[3] )
            except Exception as e:
                self.logger.debug( 'could not create vertex colour layer: ' + str( e ) )
        
        mip:UMVC3ModelImportProperties = context.scene.sub_scene_properties

        # apply weights
        if len(vertexData.jointArray) > 0 and mip.import_weights:
            self.importWeights(obj, primitive, vertexData)
        elif len(vertexData.jointArray) == 0:
            self.logger.debug(f'primitive {obj.name} has no vertex weights')
        

        if mip.import_normals:
            # Adapted from https://github.com/Pherakki/BlenderToolsForGFS/blob/223c88d8bf1eaa7dd1bd01fe18edb2fd668e38fa/src/BlenderIO/Import/ImportModel.py#L241
            # Assign normals
            # Works thanks to this stackexchange answer https://blender.stackexchange.com/a/75957
            # which a few of these comments below are also taken from
            # Do this LAST because it can remove some loops
            mesh.create_normals_split()
            for face in mesh.polygons:
                face.use_smooth = True  # loop normals have effect only if smooth shading ?

            # Set loop normals
            loop_normals = [mathutils.Vector(vertexData.normalArray[loop.vertex_index]) for loop in mesh.loops]
            mesh.loops.foreach_set("normal", [subitem for item in loop_normals for subitem in item])

            mesh.validate(clean_customdata=False)  # important to not remove loop normals here!
            mesh.update()

            clnors = array.array('f', [0.0] * (len(mesh.loops) * 3))
            mesh.loops.foreach_get("normal", clnors)

            mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
            # This line is pretty smart (came from the stackoverflow answer)
            # 1. Creates three copies of the same iterator over clnors
            # 2. Splats those three copies into a zip
            # 3. Each iteration of the zip now calls the iterator three times, meaning that three consecutive elements
            #    are popped off
            # 4. Turn that triplet into a tuple
            # In this way, a flat list is iterated over in triplets without wasting memory by copying the whole list
            mesh.normals_split_custom_set(tuple(zip(*(iter(clnors),) * 3)))

            mesh.use_auto_smooth = True
        
        # parent to group
        if primitive.indices.getGroupId() in self.editorGroupLookup:
            group = self.editorGroupLookup[primitive.indices.getGroupId()].unwrap()
            obj.parent = group
        
        mesh.validate(verbose=True, clean_customdata=False)
        
        mesh.update()
        mesh.update()

    def importWeights( self, editorObj, primitive, vertexData: DecodedVertexData ):
        self.logger.info( 'importing mesh weights' )

        bpy.context.view_layer.objects.active = self.armatureObj
        bpy.ops.object.mode_set(mode='EDIT')
        
        weightData = self.preprocessWeights( primitive, vertexData )

        # add used bones to skin modifier
        vertexGroupMap = dict()
        for i, editorBone in enumerate( weightData.usedBones ):
            vertexGroupMap[i] = editorObj.vertex_groups.new(name=editorBone.getName())

        # set vertex weights
        for j in range( 0, primitive.vertexCount ):
            newMaxVtxJointArray = weightData.jointArray[j]
            newMaxVtxWeightArray = weightData.weightArray[j]
            assert len( newMaxVtxJointArray ) > 0 
            assert len( newMaxVtxWeightArray ) > 0
            assert len( newMaxVtxJointArray ) == len( newMaxVtxWeightArray )
            for k in range( 0, len( newMaxVtxJointArray )):
                vertexGroup = vertexGroupMap[newMaxVtxJointArray[k]]
                vertexGroup.add([j], newMaxVtxWeightArray[k], 'REPLACE')

        modifier = editorObj.modifiers.new('Armature', 'ARMATURE')
        modifier.object = self.armatureObj

        bpy.ops.object.mode_set(mode='OBJECT')

    # Create functions
    def createArray( self ):
        return BlenderArrayProxy()
          
    def createPoint3( self, x, y, z ):
        return mathutils.Vector((x, y, z))
    
    def createPoint2( self, x, y ):
        return mathutils.Vector((x, y))
        
    def createTexture( self, filename ):
        return bpy.data.images.load(filepath=filename)

    def createDummy( self, name, pos ):
        blendGroup = bpy.data.objects.new(name, None)
        #blendGroup.location = group.boundingSphere[0], group.boundingSphere[1], group.boundingSphere[2]
        return BlenderNodeProxy(blendGroup)

    def parentGroupToArmature( self, editorGroup ):
        if self.armatureObj is None:
            return
        obj = editorGroup.unwrap()
        obj.parent = self.armatureObj
        obj.matrix_parent_inverse = self.armatureObj.matrix_world.inverted()

    def importSkeleton( self, context ):
        # Create armature
        self.armature = bpy.data.armatures.new('Armature')
        self.armatureObj = bpy.data.objects.new('Armature', self.armature)
        if self.layer != None:
            self.layer.unwrap().objects.link(self.armatureObj)
        else:
            bpy.context.scene.collection.objects.link(self.armatureObj)

        bpy.context.view_layer.objects.active = self.armatureObj
        
        # Bones can only be created in edit mode
        bpy.ops.object.mode_set(mode='EDIT',toggle=False)

        super().importSkeleton(context)

        def findNextBone(bone):
            nextBone = None
            for otherBone in self.editorBoneArray:
                otherBone = otherBone.unwrap()
                if otherBone.parent is not None and otherBone.parent == bone:
                    nextBone = otherBone
                    break     
            return nextBone

        for bone in self.editorBoneArray:
            bone = bone.unwrap()
            nextBone = findNextBone(bone)
            tailDir = (bone.tail - bone.head).normalized()
            assert(tailDir.magnitude > 0)
            length = 0 # whichever length you prefer, they're formally 0 length but blender deletes those automagically 
            if nextBone is not None:
                length = (nextBone.head - bone.head).length
            length = max(length, 0.5)
            bone.tail = bone.head + (tailDir * length)

        # Ensure we're in object mode because after this we'll be adding
        # attributes to the object mode bone data
        bpy.ops.object.mode_set(mode='OBJECT',toggle=False)

    def createBone( self, joint: rModelJoint, name, tfm, parentBone, context ):
        assertBlenderMode('EDIT')
        mip:UMVC3ModelImportProperties = context.scene.sub_scene_properties
        def vec_roll_to_mat3(vec, roll):
            #port of the updated C function from armature.c
            #https://developer.blender.org/T39470
            #note that C accesses columns first, so all matrix indices are swapped compared to the C version

            nor = vec.normalized()
            THETA_THRESHOLD_NEGY = 1.0e-9
            THETA_THRESHOLD_NEGY_CLOSE = 1.0e-5

            #create a 3x3 matrix
            bMatrix = mathutils.Matrix().to_3x3()

            theta = 1.0 + nor[1]

            if (theta > THETA_THRESHOLD_NEGY_CLOSE) or ((nor[0] or nor[2]) and theta > THETA_THRESHOLD_NEGY):

                bMatrix[1][0] = -nor[0]
                bMatrix[0][1] = nor[0]
                bMatrix[1][1] = nor[1]
                bMatrix[2][1] = nor[2]
                bMatrix[1][2] = -nor[2]
                if theta > THETA_THRESHOLD_NEGY_CLOSE:
                    #If nor is far enough from -Y, apply the general case.
                    bMatrix[0][0] = 1 - nor[0] * nor[0] / theta
                    bMatrix[2][2] = 1 - nor[2] * nor[2] / theta
                    bMatrix[0][2] = bMatrix[2][0] = -nor[0] * nor[2] / theta

                else:
                    #If nor is too close to -Y, apply the special case.
                    theta = nor[0] * nor[0] + nor[2] * nor[2]
                    bMatrix[0][0] = (nor[0] + nor[2]) * (nor[0] - nor[2]) / -theta
                    bMatrix[2][2] = -bMatrix[0][0]
                    bMatrix[0][2] = bMatrix[2][0] = 2.0 * nor[0] * nor[2] / theta

            else:
                #If nor is -Y, simple symmetry by Z axis.
                bMatrix = mathutils.Matrix().to_3x3()
                bMatrix[0][0] = bMatrix[1][1] = -1.0

            #Make Roll matrix
            rMatrix = mathutils.Matrix.Rotation(roll, 3, nor)

            #Combine and output result
            mat = rMatrix @ bMatrix
            return mat

        def mat3_to_vec_roll(mat):
            """
            Code from
            https://blender.stackexchange.com/a/38337
            https://blender.stackexchange.com/a/90240
            """
            vec = mat.col[1]
            vecmat = vec_roll_to_mat3(mat.col[1], 0)
            try:
                vecmatinv = vecmat.inverted()
            except:
                vecmatinv = vecmat
            rollmat = vecmatinv @ mat
            roll = math.atan2(rollmat[0][2], rollmat[2][2])
            return vec, roll

        self.logger.debug(f'createBone({name},{tfm},{parentBone})')
        matrix = self.convertNclMat44ToMatrix(tfm)
        # This matrix fixes the direction of the tail
        tailRotationMatrix = mathutils.Matrix(((0.0, 1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0)))
        matrix = matrix @ tailRotationMatrix

        # Copied from https://github.com/Pherakki/BlenderToolsForGFS/blob/223c88d8bf1eaa7dd1bd01fe18edb2fd668e38fa/src/BlenderIO/Import/Utils/BoneConstruction.py#L6
        bpy_bone = self.armature.edit_bones.new(name)
        
        tail, roll = mat3_to_vec_roll(matrix.to_3x3())
        pos_vector = matrix.to_translation()
        bpy_bone.head = pos_vector
        bpy_bone.tail = pos_vector + tail
        bpy_bone.roll = roll
        
        # Head/tail/roll sets correctly in Blender 2.83, but not in
        # Blender 3.4?!
        # So here we'll just manually set the matrix because... I have no idea
        # why Blender sets the matrix_local incorrectly later
        # Can't just set the matrix because that prevents the head/tail being set,
        # so set the head/tail first and then align the roll by setting the matrix
        # I feel *extremely* uncomfortable about the fact that two different
        # roll values are required in two versions of Blender to get the same
        # matrix - need to find out why.
        
        bpy_bone.matrix = matrix
        if parentBone:
            bpy_bone.parent = parentBone.unwrap()

        if mip.inherit_scale == False:
            bpy_bone.inherit_scale = "NONE"    

        return BlenderEditBoneProxy(bpy_bone, tfm)

    def setSkeletonAttributes( self, rootBone ):
        assertBlenderMode('OBJECT')

        # if self.config.lukasCompat and rootBone is not None:
        #     self.setUserProp( rootBone, 'LMTBone', 255 )

        for i, joint in enumerate( self.model.joints ):
            editorBone = self.editorBoneArray[ i ]
            # for compat. with Lukas' Mt Framework animation importing script  
            self.setInheritanceFlags( editorBone, (1,2,3,4,5,6) )
            self.setUserProp( editorBone, 'LMTBone', joint.id )        
            self.setJointCustomAttributes( joint, editorBone )
    
    # Material functions
    def _attachUVChannel( self, bpy_material, nodes, tex_node, material, slot ):
        '''The mrl says which uv channel feeds each texture slot. Without an explicit
        UV Map node blender falls back to whichever layer happens to be active, which
        is wrong for anything not using the primary channel.'''
        try:
            channel = material.getUVChannelForSlot( slot )
        except Exception:
            channel = 'UVPrimary'
        uv = nodes.new( 'ShaderNodeUVMap' )
        uv.uv_map = channel
        uv.location.x = tex_node.location.x - 200
        uv.location.y = tex_node.location.y
        uv.label = slot + ' -> ' + channel
        bpy_material.node_tree.links.new( uv.outputs['UV'], tex_node.inputs['Vector'] )

        try:
            anim = material.getUVAnimation()
        except Exception:
            anim = None
        if anim is not None and anim['channel'] == channel and any( anim['direction'] ):
            self._attachUVScroll( bpy_material, nodes, uv, tex_node, anim )
        return uv

    UV_SCROLL_REFERENCE_RATE = 240.0    # Dante's gauntlet, the one we have seen moving
    UV_SCROLL_BASE_SPEED     = 0.004    # uv units per frame at that rate

    def _attachUVScroll( self, bpy_material, nodes, uv_node, tex_node, anim ):
        try:
            links = bpy_material.node_tree.links
            mapping = nodes.new( 'ShaderNodeMapping' )
            mapping.location.x = uv_node.location.x + 100
            mapping.location.y = uv_node.location.y - 120
            mapping.label = 'UV scroll'
            links.new( uv_node.outputs['UV'], mapping.inputs['Vector'] )
            links.new( mapping.outputs['Vector'], tex_node.inputs['Vector'] )

            rate = anim['rate'] if anim['rate'] else self.UV_SCROLL_REFERENCE_RATE
            speed = self.UV_SCROLL_BASE_SPEED * ( self.UV_SCROLL_REFERENCE_RATE / float( rate ) )

            u, v = anim['direction']

            # Speed and direction live as nodes in the graph, not as custom properties,
            # so they can be tuned in the shader editor with the viewport updating live.
            spd_node = nodes.new( 'ShaderNodeValue' )
            spd_node.location = ( mapping.location.x - 400, mapping.location.y - 200 )
            spd_node.label = 'UV scroll speed'
            spd_node.name = 'UV scroll speed'
            spd_node.outputs[0].default_value = float( speed )

            dir_node = nodes.new( 'ShaderNodeCombineXYZ' )
            dir_node.location = ( mapping.location.x - 400, mapping.location.y - 330 )
            dir_node.label = 'UV scroll direction'
            dir_node.name = 'UV scroll direction'
            dir_node.inputs['X'].default_value = float( u )
            dir_node.inputs['Y'].default_value = float( v )

            # frame is the one thing that has to be a driver, so it drives a single
            # Value node that the graph multiplies against.
            time_node = nodes.new( 'ShaderNodeValue' )
            time_node.location = ( mapping.location.x - 400, mapping.location.y - 70 )
            time_node.label = 'frame'
            time_node.name = 'frame'
            try:
                d = time_node.outputs[0].driver_add( 'default_value' ).driver
                d.type = 'SCRIPTED'
                d.expression = 'frame'
            except Exception:
                pass

            step = nodes.new( 'ShaderNodeVectorMath' )
            step.operation = 'SCALE'
            step.location = ( mapping.location.x - 220, mapping.location.y - 260 )
            step.label = 'direction * speed'
            links.new( dir_node.outputs['Vector'], step.inputs[0] )
            links.new( spd_node.outputs[0], step.inputs['Scale'] )

            offset = nodes.new( 'ShaderNodeVectorMath' )
            offset.operation = 'SCALE'
            offset.location = ( mapping.location.x - 220, mapping.location.y - 120 )
            offset.label = 'x frame'
            links.new( step.outputs['Vector'], offset.inputs[0] )
            links.new( time_node.outputs[0], offset.inputs['Scale'] )

            links.new( offset.outputs['Vector'], mapping.inputs['Location'] )

            self.logger.info(
                f"uv scroll on {bpy_material.name}: channel {anim['channel']}, "
                f"vector ({u:+.0f}, {v:+.0f}), rate {anim['rate']}" )
        except Exception as e:
            self.logger.debug( 'could not set up uv scroll: ' + str( e ) )


    def _wantsToonShading( self, context ):
        try:
            return bool( context.scene.sub_scene_properties.import_toon_shading )
        except Exception:
            return False

    def _buildToonShader( self, bpy_material, nodes, principled, albedo_tex, ramp_tex, material ):
        try:
            links = bpy_material.node_tree.links
            out = nodes.get( 'Material Output' )
            if out is None:
                for n in nodes:
                    if n.bl_idname == 'ShaderNodeOutputMaterial':
                        out = n
                        break
            if out is None:
                return

            hl = material.getHalfLambert() or ( 0.5, 0.5 )
            bias, scale = float( hl[0] ), float( hl[1] )
            bpy_material['CBHalfLambertBias']  = bias
            bpy_material['CBHalfLambertScale'] = scale

            # a plain diffuse term, converted to a scalar we can use as a lookup
            diffuse = nodes.new( 'ShaderNodeBsdfDiffuse' )
            diffuse.location = ( -1400, -600 )
            diffuse.inputs['Color'].default_value = ( 1, 1, 1, 1 )

            to_rgb = nodes.new( 'ShaderNodeShaderToRGB' )
            to_rgb.location = ( -1200, -600 )
            links.new( diffuse.outputs['BSDF'], to_rgb.inputs['Shader'] )

            # bias and scale the lambert term into the ramp's 0..1 range
            mad = nodes.new( 'ShaderNodeMapRange' )
            mad.location = ( -1000, -600 )
            mad.label = 'half lambert'
            mad.clamp = True
            links.new( to_rgb.outputs['Color'], mad.inputs['Value'] )
            mad.inputs['From Min'].default_value = 0.0
            mad.inputs['From Max'].default_value = 1.0
            # Half lambert is NdotL * scale + bias, so at NdotL = 0 the lookup sits at
            # bias and at 1 it sits at bias + scale. Centring on bias put the unlit half
            # below u = 0.5, where every ramp is flat black, which masked Dante's face.
            toMin = max( 0.0, min( 1.0, bias ) )
            toMax = max( 0.0, min( 1.0, bias + scale ) )
            mad.inputs['To Min'].default_value = toMin
            mad.inputs['To Max'].default_value = toMax

            # Every mrl number gets its own labelled node so it can be edited in the
            # shader editor and the viewport updates as you drag it. Custom properties
            # live in a different panel and are the wrong place to tune shading from.
            for socket, label, val, ypos in ( ( 'To Min', 'CBHalfLambert bias',  toMin, -520 ),
                                              ( 'To Max', 'CBHalfLambert bias+scale', toMax, -620 ) ):
                vnode = nodes.new( 'ShaderNodeValue' )
                vnode.location = ( -1200, ypos )
                vnode.label = label
                vnode.name = label
                vnode.outputs[0].default_value = float( val )
                links.new( vnode.outputs[0], mad.inputs[socket] )

            # sample the ramp along u, v is arbitrary on a 512x1 texture
            combine = nodes.new( 'ShaderNodeCombineXYZ' )
            combine.location = ( -800, -600 )
            links.new( mad.outputs['Result'], combine.inputs['X'] )
            combine.inputs['Y'].default_value = 0.5

            ramp_tex.location = ( -600, -600 )
            links.new( combine.outputs['Vector'], ramp_tex.inputs['Vector'] )

            # albedo tinted by the ramp
            mix = nodes.new( 'ShaderNodeMixRGB' )
            mix.blend_type = 'MULTIPLY'
            mix.location = ( -300, -500 )
            mix.inputs['Fac'].default_value = 1.0
            if albedo_tex is not None:
                links.new( albedo_tex.outputs['Color'], mix.inputs['Color1'] )
            else:
                mix.inputs['Color1'].default_value = ( 0.8, 0.8, 0.8, 1 )
            # Nothing in game goes fully black, there is always ambient underneath.
            floor = nodes.new( 'ShaderNodeMapRange' )
            floor.location = ( -450, -700 )
            floor.label = 'shadow floor'
            floor.clamp = True
            links.new( ramp_tex.outputs['Color'], floor.inputs['Value'] )
            floor.inputs['From Min'].default_value = 0.0
            floor.inputs['From Max'].default_value = 1.0
            floor.inputs['To Max'].default_value = 1.0
            floor_val = nodes.new( 'ShaderNodeValue' )
            floor_val.location = ( -650, -820 )
            floor_val.label = 'shadow floor'
            floor_val.name = 'shadow floor'
            floor_val.outputs[0].default_value = 0.2
            links.new( floor_val.outputs[0], floor.inputs['To Min'] )

            links.new( floor.outputs['Result'], mix.inputs['Color2'] )

            # MT's ramp is the whole lighting model, there is no separate shadow pass.
            # Leaving blender's shadowing on stamps a hard black band under the jaw
            # where the head self shadows, which the game does not have.
            try:
                bpy_material.shadow_method = 'NONE'
            except Exception:
                pass

            # diffuse tint and the flat albedo correction, both straight out of the mrl
            tint = material.getDiffuseTint()
            boost = material.getDiffuseColorCorrect()
            factor = [ 1.0, 1.0, 1.0 ]
            if tint is not None:
                factor = [ tint[0], tint[1], tint[2] ]
            if boost is not None:
                factor = [ c * boost for c in factor ]
            if factor != [ 1.0, 1.0, 1.0 ]:
                tint_rgb = nodes.new( 'ShaderNodeRGB' )
                tint_rgb.location = ( -350, -300 )
                tint_rgb.label = 'CBMaterial diffuse tint'
                tint_rgb.name = 'CBMaterial diffuse tint'
                tint_rgb.outputs[0].default_value = ( factor[0], factor[1], factor[2], 1.0 )

                tint_node = nodes.new( 'ShaderNodeMixRGB' )
                tint_node.blend_type = 'MULTIPLY'
                tint_node.location = ( -150, -400 )
                tint_node.label = 'CBMaterial tint'
                tint_node.inputs['Fac'].default_value = 1.0
                links.new( mix.outputs['Color'], tint_node.inputs['Color1'] )
                links.new( tint_rgb.outputs[0], tint_node.inputs['Color2'] )
                tinted = tint_node.outputs['Color']
            else:
                tinted = mix.outputs['Color']

            emit = nodes.new( 'ShaderNodeEmission' )
            emit.location = ( -100, -500 )
            links.new( tinted, emit.inputs['Color'] )

            # alpha materials keep their transparency
            if material.isAlphaBlended() and albedo_tex is not None:
                trans = nodes.new( 'ShaderNodeBsdfTransparent' )
                trans.location = ( -100, -700 )
                blend = nodes.new( 'ShaderNodeMixShader' )
                blend.location = ( 100, -550 )
                links.new( albedo_tex.outputs['Alpha'], blend.inputs['Fac'] )
                links.new( trans.outputs['BSDF'], blend.inputs[1] )
                links.new( emit.outputs['Emission'], blend.inputs[2] )
                links.new( blend.outputs['Shader'], out.inputs['Surface'] )
            else:
                links.new( emit.outputs['Emission'], out.inputs['Surface'] )

            principled.location = ( -300, 400 )
            principled.label = 'Principled (unused, relink to revert)'

            self.logger.info(
                f'toon shader on {bpy_material.name}: bias {bias:.3f} scale {scale:.3f}' )
        except Exception as e:
            self.logger.warning( 'could not build toon shader: ' + str( e ) )

    def _applyMaterialState( self, bpy_material, material ):
        '''Blend and raster state map straight onto blender material settings and
        matter more visually than people expect.'''
        try:
            if material.isDoubleSided():
                bpy_material.use_backface_culling = False
            else:
                bpy_material.use_backface_culling = True

            if material.isAlphaBlended():
                bpy_material.blend_method = 'BLEND'
                if hasattr( bpy_material, 'shadow_method' ):
                    bpy_material.shadow_method = 'HASHED'
                bpy_material.show_transparent_back = False
            else:
                bpy_material.blend_method = 'OPAQUE'
        except Exception as e:
            self.logger.debug( 'could not apply material state: ' + str( e ) )
    def convertMaterial( self, material: imMaterialInfo, context, materialName: str ):
        bpy_material = bpy.data.materials.new(name=materialName)
        bpy_material.use_nodes = True
        if material is not None and not hasattr( material, 'getUVChannelForSlot' ):
            self.logger.warning(
                f"material '{materialName}' has no mrl entry, importing untextured" )
            material = None

        if material is not None:
            nodes = bpy_material.node_tree.nodes
            principled_bsdf = nodes.get("Principled BSDF") or nodes.new("ShaderNodeBsdfPrincipled")

            albedo_tex = None
            albedo_map = self.loadTextureSlot(material, "tAlbedoMap", context)
            if albedo_map:
                albedo_tex = nodes.new("ShaderNodeTexImage")
                albedo_tex.image = albedo_map
                albedo_tex.location.x = -900
                albedo_tex.location.y = 300
                bpy_material.node_tree.links.new(albedo_tex.outputs["Color"], principled_bsdf.inputs["Base Color"])
                self._attachUVChannel( bpy_material, nodes, albedo_tex, material, 'tAlbedoMap' )

                # the albedo alpha channel is the transparency source when the
                # blend state composites rather than writing opaque
                if material.isAlphaBlended():
                    bpy_material.node_tree.links.new(albedo_tex.outputs["Alpha"], principled_bsdf.inputs["Alpha"])

            specular_map = self.loadTextureSlot(material, "tSpecularMap", context)
            if specular_map:
                metalness_tex = nodes.new("ShaderNodeTexImage")
                metalness_tex.image = specular_map
                metalness_tex.location.x = -900
                metalness_tex.location.y = 0


                #Specular Maps are sensitive in Marvel 3 so we have to compensate for that to get closer to the desired lighting.
                metalness_tex_power = nodes.new("ShaderNodeMath")
                metalness_tex_power.operation = 'POWER'
                metalness_tex_power.inputs[1].default_value  = 0.250

                metalness_tex_power.location.x = -300
                metalness_tex_power.location.y = 0

                bpy_material.node_tree.links.new(metalness_tex.outputs["Color"], metalness_tex_power.inputs[0])

                #Sets the Color Space to Non-Color so the material displays properly.
                metalness_tex.image.colorspace_settings.name = 'Non-Color'                
                bpy_material.node_tree.links.new(metalness_tex_power.outputs["Value"], principled_bsdf.inputs["Roughness"])
                self._attachUVChannel( bpy_material, nodes, metalness_tex, material, 'tSpecularMap' )

            normal_map = self.loadTextureSlot(material, "tNormalMap", context)
            if normal_map:
                normal_map_node = nodes.new("ShaderNodeNormalMap")
                normal_map_node.location.x = -200
                normal_map_node.location.y = -100

                normal_map_tex = nodes.new("ShaderNodeTexImage")
                normal_map_tex.location.x = -900
                normal_map_tex.location.y = -300

                normal_map_separate_color = nodes.new("ShaderNodeSeparateColor")
                normal_map_separate_color.location.x = -650
                normal_map_separate_color.location.y = -300

                normal_map_invert = nodes.new("ShaderNodeInvert")
                normal_map_invert.location.x = -650
                normal_map_invert.location.y = -500

                normal_map_combine = nodes.new("ShaderNodeCombineColor")
                normal_map_combine.location.x = -400
                normal_map_combine.location.y = -200

                # Swap the red and alpha channels of the normal map
                # normal_map_pixels = np.array(normal_map.pixels)
                # normal_map_pixels = normal_map_pixels.reshape(-1, 4)
                # normal_map_pixels[:, 0], normal_map_pixels[:, 3] = normal_map_pixels[:, 3], normal_map_pixels[:, 0]
                # normal_map_pixels = normal_map_pixels.flatten()
                # normal_map.pixels = normal_map_pixels

                #Sets the Color Space to Non-Color so the material displays properly.
                normal_map_tex.image = normal_map
                normal_map_tex.image.colorspace_settings.name = 'Non-Color' 
                bpy_material.node_tree.links.new(normal_map_tex.outputs["Color"], normal_map_separate_color.inputs["Color"])
                bpy_material.node_tree.links.new(normal_map_separate_color.outputs["Green"], normal_map_invert.inputs["Color"])

                bpy_material.node_tree.links.new(normal_map_tex.outputs["Alpha"], normal_map_combine.inputs["Red"])
                bpy_material.node_tree.links.new(normal_map_invert.outputs["Color"], normal_map_combine.inputs["Green"])
                bpy_material.node_tree.links.new(normal_map_separate_color.outputs["Blue"], normal_map_combine.inputs["Blue"])

                bpy_material.node_tree.links.new(normal_map_combine.outputs["Color"], normal_map_node.inputs["Color"])

                bpy_material.node_tree.links.new(normal_map_node.outputs["Normal"], principled_bsdf.inputs["Normal"])
                self._attachUVChannel( bpy_material, nodes, normal_map_tex, material, 'tNormalMap' )

                # normal_map_tex.image.colorspace_settings.name = 'Non-Color'                
                # bpy_material.node_tree.links.new(normal_map_tex.outputs["Color"], normal_map_node.inputs["Color"])
                # bpy_material.node_tree.links.new(normal_map_node.outputs["Normal"], principled_bsdf.inputs["Normal"])
            
            # A second albedo layered over the first, on its own uv channel.
            # Dante uses it on two materials. Mixed rather than replacing, which is
            # the sane default without knowing the shader's exact blend.
            blend_map = self.loadTextureSlot( material, 'tAlbedoBlendMap', context )
            if blend_map and albedo_map:
                blend_tex = nodes.new( 'ShaderNodeTexImage' )
                blend_tex.image = blend_map
                blend_tex.location.x = -900
                blend_tex.location.y = 600
                blend_tex.label = 'tAlbedoBlendMap'
                self._attachUVChannel( bpy_material, nodes, blend_tex, material, 'tAlbedoBlendMap' )

                try:
                    links = bpy_material.node_tree.links
                    mix = nodes.new( 'ShaderNodeMixRGB' )
                    mix.blend_type = 'MIX'
                    mix.location.x = -600
                    mix.location.y = 450
                    links.new( albedo_tex.outputs['Color'], mix.inputs['Color1'] )
                    links.new( blend_tex.outputs['Color'], mix.inputs['Color2'] )
                    links.new( blend_tex.outputs['Alpha'], mix.inputs['Fac'] )
                    links.new( mix.outputs['Color'], principled_bsdf.inputs['Base Color'] )
                except Exception as e:
                    self.logger.debug( 'could not wire tAlbedoBlendMap: ' + str( e ) )

            toon_nodes = {}
            for slot, yoff in ( ( 'tToonMap', 1200 ), ( 'tToonRevMap', 1000 ) ):
                toon_img = self.loadTextureSlot( material, slot, context )
                if toon_img:
                    toon_tex = nodes.new( 'ShaderNodeTexImage' )
                    toon_tex.image = toon_img
                    toon_tex.location.x = -400
                    toon_tex.location.y = yoff
                    toon_tex.label = slot
                    # a lookup ramp, not a colour texture
                    try:
                        toon_tex.image.colorspace_settings.name = 'Non-Color'
                        toon_tex.extension = 'EXTEND'
                        toon_tex.interpolation = 'Linear'
                    except Exception:
                        pass
                    toon_nodes[slot] = toon_tex

            if toon_nodes.get( 'tToonMap' ) is not None and self._wantsToonShading( context ):
                self._buildToonShader( bpy_material, nodes, principled_bsdf,
                                       albedo_tex,
                                       toon_nodes['tToonMap'], material )

            # CBHalfLambert drives the toon ramp lookup and varies per material,
            # 7 distinct pairs across Dante's 25. Stash it so it isn't lost.
            hl = material.getHalfLambert()
            if hl is not None:
                bpy_material['CBHalfLambert'] = [ hl[0], hl[1] ]

            #Light Maps. tOcclusionMap
            # specular tint and power feed the principled path; the toon path uses the
            # ramp for shading so they only matter here.
            try:
                spec = material.getSpecularTint()
                if spec is not None and hasattr( principled_bsdf.inputs, '__contains__' ):
                    if 'Specular Tint' in principled_bsdf.inputs:
                        st = principled_bsdf.inputs['Specular Tint']
                        if len( getattr( st, 'default_value', [] ) ) >= 3:
                            st.default_value = ( spec[0], spec[1], spec[2], 1.0 )
                bpy_material['CBMaterialSpecularTint']  = list( spec ) if spec else None
                bpy_material['CBMaterialSpecularPower'] = material.getSpecularPower()
            except Exception as e:
                self.logger.debug( 'could not apply specular tint: ' + str( e ) )

            self._applyMaterialState( bpy_material, material )

            light_map = self.loadTextureSlot(material, "tOcclusionMap", context)
            if light_map:
                light_map_tex = nodes.new("ShaderNodeTexImage")   
                light_map_tex.image = light_map
                #Not sure how to properly apply the light map to the Blender scene so we'll just put the texture in the shading tab separate from the rest.
                light_map_tex.location.x = -400
                light_map_tex.location.y = 800             

                #Attempt to create a UV Map Node & attach it.
                light_map_UVMap = nodes.new("ShaderNodeUVMap")
                # was hardcoded to UVUnique; the mrl names the channel per slot
                try:
                    light_map_UVMap.uv_map = material.getUVChannelForSlot( 'tOcclusionMap' )
                except Exception:
                    light_map_UVMap.uv_map = "UVUnique"
                light_map_UVMap.location.x = -550
                light_map_UVMap.location.y = 800
                bpy_material.node_tree.links.new(light_map_UVMap.outputs["UV"], light_map_tex.inputs["Vector"])

            # normal_map = self.loadTextureSlot(material, "tNormalMap")
            # if normal_map:
            #     normal_map_node = nodes.new("ShaderNodeSeparateRGB")
            #     normal_map_tex = nodes.new("ShaderNodeTexImage")
            #     normal_map_tex.image = normal_map
            #     bpy_material.node_tree.links.new(normal_map_tex.outputs["Color"], normal_map_node.inputs["Image"])
                
            #     # separate the RGB and Alpha channels
            #     normal_map_r = nodes.new("ShaderNodeSeparateRGB")
            #     normal_map_a = nodes.new("ShaderNodeSeparateRGB")
            #     bpy_material.node_tree.links.new(normal_map_node.outputs["Image"], normal_map_r.inputs["Image"])
            #     bpy_material.node_tree.links.new(normal_map_node.outputs["Image"], normal_map_a.inputs["Image"])
            #     normal_map_r_out = normal_map_r.outputs["R"]
            #     normal_map_a_out = normal_map_a.outputs["A"]
                
            #     # swap the RGB and Alpha channels
            #     normal_map_rgb = nodes.new("ShaderNodeCombineRGB")
            #     normal_map_rgb.inputs["R"].default_value = normal_map_a_out.default_value
            #     normal_map_rgb.inputs["G"].default_value = normal_map_r_out.default_value
            #     normal_map_rgb.inputs["B"].default_value = normal_map_r_out.default_value
            #     bpy_material.node_tree.links.new(normal_map_r_out, normal_map_rgb.inputs["G"])
            #     bpy_material.node_tree.links.new(normal_map_a_out, normal_map_rgb.inputs["R"])
                
            #     # connect the swapped RGB and Alpha channels to the normal map node
            #     normal_map_node = nodes.new("ShaderNodeNormalMap")
            #     bpy_material.node_tree.links.new(normal_map_rgb.outputs["Image"], normal_map_node.inputs["Color"])
            #     bpy_material.node_tree.links.new(normal_map_node.outputs["Normal"], principled_bsdf.inputs["Normal"])

        return BlenderMaterialProxy(bpy_material)

    # Attribute functions
    def createGroupCustomAttribute( self, obj )-> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(obj.unwrap())

    def createMaterialCustomAttribute( self, obj )-> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(obj.unwrap())

    def createPrimitiveCustomAttribute( self, obj ) -> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')
        return BlenderCustomAttributeSetProxy(obj.unwrap())

    def createJointCustomAttribute( self, obj ) -> EditorCustomAttributeSetProxy:
        assertBlenderMode('OBJECT')

        # #Because Object Mode Bone properties are not accessible in a script, 
        # #I'm adding these MT Attributes to the respective Pose bone instead.
        bone = self.armatureObj.pose.bones[obj.getName()]

        # bone = self.armature.bones.get(obj.getName())
        return BlenderCustomAttributeSetProxy(bone)

    def importModel(self, modFilePath, context):
        super().importModel(modFilePath, context)