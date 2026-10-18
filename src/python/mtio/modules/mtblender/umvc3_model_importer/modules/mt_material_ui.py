'''The MRL entry of a game shader material, editable in one place: texture slots, the
cbuffer constants on the MT Shader / MT UV groups, and the feature flags. Shown under
Material Properties and in the shader editor's sidebar.'''
import json

import bpy

from . import mt_exact
from ..mtlib import mtshaders


def _game_material( context ):
    obj = getattr( context, 'object', None )
    mat = getattr( context, 'material', None ) or ( obj.active_material if obj is not None else None )
    if mat is not None and 'mt_mrl' in mat.keys() and mat.node_tree is not None:
        return mat
    return None

def _stored( mat ):
    return json.loads( mat.get( 'mt_mrl', '{}' ) or '{}' )


# ----------------------------------------------------------------------------------------
# flag choices: every implementation the game has a compiled shader for, given the rest of
# this material and the renderer state
# ----------------------------------------------------------------------------------------

_choices = {}

def flag_choices( context, mat, slot ):
    stored = _stored( mat )
    key = ( mat.name, slot, json.dumps( stored.get( 'cmds' ) ), mat.get( 'mt_ia' ), mat.get( 'mt_receive' ) )
    if key in _choices:
        return _choices[key]
    scene = context.scene
    native = scene.get( 'mt_game_native_dir', '' )
    out = []
    try:
        db = mtshaders.ShaderDB.get( native )
    except Exception:
        return out
    images = { k: bpy.data.images.get( v ) for k, v in json.loads( mat.get( 'mt_images', '{}' ) or '{}' ).items() }
    mfx = db.mfx
    current = next( ( c[2] for c in stored.get( 'cmds', [] ) if c[0] == 'flag' and c[1] == slot ), slot )
    import os, re
    # implementations are named after their slot (FSpecular -> FSpecularMap) or after the
    # current one's family (FToonShader -> FToonShaderHigh); the lookup below decides
    stems = { slot }
    common = os.path.commonprefix( [ slot, current ] )
    if len( common ) >= 5:
        stems.add( common )
    words = re.findall( r'[A-Z][a-z0-9]*', current )
    for k in range( 2, len( words ) + 1 ):
        stem = ''.join( words[:k] )
        if len( stem ) >= 5:
            stems.add( stem )
    names = sorted( n for n, i in mfx.idx.items() if mfx.type[i] == 2 and any( n.startswith( st ) for st in stems ) )
    for name in names:
        d = dict( stored )
        d['cmds'] = [ ( t, n, ( name if ( t == 'flag' and n == slot ) else v ) ) for t, n, v in stored.get( 'cmds', [] ) ]
        try:
            prog, _ = mt_exact.pick_program( db, mt_exact.StoredMaterial( d ), mat.get( 'mt_ia' ), images, scene,
                                             outenc=int( scene.get( 'mt_outenc', 1 ) ), receive=mat.get( 'mt_receive', True ) )
        except RecursionError:
            prog = None
        if prog is not None:
            out.append( name )
    if current not in out:
        out.insert( 0, current )
    _choices[key] = out
    return out


class SUB_OP_SetGameFlag( bpy.types.Operator ):
    """Switch this MRL feature flag. Only the implementations the game has a compiled shader for are listed; the material is rebuilt with the new shader"""
    bl_idname = 'sub.mt_set_game_flag'
    bl_label = 'Set Flag'
    bl_property = 'value'
    bl_options = { 'UNDO' }

    slot: bpy.props.StringProperty()

    def _items( self, context ):
        mat = _game_material( context )
        if mat is None:
            return [ ( '', '', '' ) ]
        SUB_OP_SetGameFlag._keep = [ ( n, n, '' ) for n in flag_choices( context, mat, self.slot ) ]
        return SUB_OP_SetGameFlag._keep

    value: bpy.props.EnumProperty( items=_items )

    def invoke( self, context, event ):
        context.window_manager.invoke_search_popup( self )
        return { 'RUNNING_MODAL' }

    def execute( self, context ):
        from .blender_plugin import plugin
        mat = _game_material( context )
        if mat is None:
            return { 'CANCELLED' }
        mt_exact.store_material_edits( mat )
        d = _stored( mat )
        d['cmds'] = [ ( t, n, ( self.value if ( t == 'flag' and n == self.slot ) else v ) ) for t, n, v in d.get( 'cmds', [] ) ]
        old = mat['mt_mrl']
        mat['mt_mrl'] = json.dumps( d )
        if not rebuild_material( context, mat, plugin.logger ):
            mat['mt_mrl'] = old
            rebuild_material( context, mat, plugin.logger )
            self.report( { 'ERROR' }, 'the game has no shader for %s = %s here' % ( self.slot, self.value ) )
            return { 'CANCELLED' }
        self.report( { 'INFO' }, '%s = %s (PS %s)' % ( self.slot, self.value, mat.get( 'mt_ps' ) ) )
        return { 'FINISHED' }


def rebuild_material( context, mat, logger=None ):
    mt_exact.store_material_edits( mat )
    material = mt_exact.StoredMaterial( json.loads( mat['mt_mrl'] ) )
    images = { k: bpy.data.images.get( v ) for k, v in json.loads( mat.get( 'mt_images', '{}' ) or '{}' ).items() }
    return mt_exact.build_exact_material( mat, material, mat['mt_ia'], images, context, logger,
                                          receive=mat.get( 'mt_receive', True ) ) is not None


class SUB_OP_RebuildGameMaterial( bpy.types.Operator ):
    """Rebuild this material's game shader (after swapping a texture for one in another format, say)"""
    bl_idname = 'sub.mt_rebuild_game_material'
    bl_label = 'Rebuild Material'
    bl_options = { 'UNDO' }

    def execute( self, context ):
        from .blender_plugin import plugin
        mat = _game_material( context )
        if mat is None or not rebuild_material( context, mat, plugin.logger ):
            self.report( { 'ERROR' }, 'could not rebuild' )
            return { 'CANCELLED' }
        return { 'FINISHED' }


def draw_game_material( layout, context ):
    mat = _game_material( context )
    if mat is None:
        layout.label( text='Not a game shader material' )
        return
    d = _stored( mat )
    tree = mat.node_tree
    sg = tree.nodes.get( 'MT Shader' )
    ug = tree.nodes.get( 'MT UV' )
    col = layout.column( align=True )
    col.label( text='%s  (%s)' % ( d.get( 'name', mat.name ), d.get( 'type', '' ).split( ':' )[-1] ), icon='MATERIAL' )
    col.label( text='PS %s  VS %s  %s' % ( mat.get( 'mt_ps' ), mat.get( 'mt_vs' ), mat.get( 'mt_ia', '' ) ) )

    box = layout.box()
    box.label( text='Textures', icon='TEXTURE' )
    for nd in sorted( ( n for n in tree.nodes if n.type == 'TEX_IMAGE' and n.name.startswith( 'mt_tex:' ) ), key=lambda n: n.name ):
        row = box.row()
        row.label( text=nd.label or nd.name[7:] )
        row.template_ID( nd, 'image', open='image.open' )
    internal = [ c for c in d.get( 'cmds', [] ) if c[0] == 'texture' and not tree.nodes.get( 'mt_tex:' + c[1] ) ]
    for t, n, v in internal:
        row = box.row()
        row.label( text=n )
        row.label( text=( v or '(none)' ).split( '\\' )[-1] )

    box = layout.box()
    box.label( text='Constants', icon='PROPERTIES' )
    for node in ( sg, ug ):
        if node is None:
            continue
        for s in node.inputs:
            if s.is_linked or not hasattr( s, 'default_value' ):
                continue
            box.prop( s, 'default_value', text=s.name )

    box = layout.box()
    box.label( text='Flags', icon='SETTINGS' )
    for t, n, v in d.get( 'cmds', [] ):
        if t != 'flag':
            continue
        row = box.row( align=True )
        row.label( text=n )
        op = row.operator( SUB_OP_SetGameFlag.bl_idname, text=v or n )
        op.slot = n
    layout.operator( SUB_OP_RebuildGameMaterial.bl_idname, icon='FILE_REFRESH' )


class SUB_PT_GameMaterial( bpy.types.Panel ):
    bl_idname = 'SUB_PT_GameMaterial'
    bl_label = 'MT Game Material'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'

    @classmethod
    def poll( cls, context ):
        return _game_material( context ) is not None

    def draw( self, context ):
        draw_game_material( self.layout, context )


class SUB_PT_GameMaterialNodes( bpy.types.Panel ):
    bl_idname = 'SUB_PT_GameMaterialNodes'
    bl_label = 'MT Game Material'
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'MT Material'

    @classmethod
    def poll( cls, context ):
        sd = getattr( context, 'space_data', None )
        return getattr( sd, 'tree_type', '' ) == 'ShaderNodeTree' and _game_material( context ) is not None

    def draw( self, context ):
        draw_game_material( self.layout, context )
