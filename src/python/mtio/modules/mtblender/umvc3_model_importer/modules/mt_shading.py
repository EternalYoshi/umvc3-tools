'''MT Framework character shading for Blender, rebuilt from the game's own shaders.

Everything here is taken from root.spkg / UserShaderPackage.mfx (see the ShaderPipeline
notes): the character pixel shaders were disassembled, the cbuffer members named from the
MFX, and the reconstruction checked against an emulation of the real shader (shader 1128
matches to 1e-6). The MRL flags pick building blocks the same way sShader2 does.

Two node groups, built once per blend file:

  MT Toon Coords   normal -> the u coordinates the toon ramps are sampled at, plus the view
                   space normal uv used by sphere maps and FUVViewNormal spec maps
  MT Character     textures + the MRL constants -> the final colour

Lighting comes from the scene, the way the game gets it from the stage SDL: a directional
key light, its colour, a flat ambient, and the ToonLight rim colour and power. They live
as custom properties on the scene (mt_light_dir, ...) that the groups read with View Layer
attribute nodes. A sun lamp drives the key light (direction from its rotation, colour from
its colour times strength), 'MT Key Light' by default or any sun picked in the panel, so
the scene's own sun lights MT and regular materials alike. load_stage_lighting() fills
everything from a stage's sdl folder.

The maths runs on raw texture values like the game does (it lights in gamma space), and the
group converts the result with the sRGB curve at the end, so with the scene's view transform
on Standard the render shows the same numbers the game writes.
'''
import math
import os
import struct

import bpy
import mathutils

try:
    import numpy as np
except ImportError:          # blender always ships numpy, this is only for linters
    np = None

COORDS_GROUP = 'MT Toon Coords'
CHARACTER_GROUP = 'MT Character'
GROUP_VERSION = 2
KEY_LIGHT_NAME = 'MT Key Light'

# Training Room (stg000) values from its Environment00.sdl, converted to blender axes.
# InfiniteLight_Chara_Front mDir is MT (0.0324, 0.4475, 0.8937) and points at the light.
SCENE_DEFAULTS = {
    'mt_light_dir':   ( 0.03236, -0.8937, 0.4475 ),
    'mt_light_color': ( 1.15, 1.15, 1.15 ),
    'mt_ambient':     ( 0.0, 0.0, 0.0 ),        # unknown for characters, see notes
    'mt_rim_color':   ( 0.0, 2.326, 10.0 ),     # ToonLight mRimLightColorFactor
    'mt_rim_power':   4.0,                      # ToonLight mRimLightPower
    'mt_rim_min_height': 2.0,                   # baked into the compiled shaders
    'mt_rim_max_height': 15.0,
    'mt_unit_scale':  1.0,                      # importer model scale, MT units -> blender
}

def mt_to_blender( v ):
    '''MT is y up, the importer flips to z up: (x, y, z) -> (x, -z, y).'''
    return ( v[0], -v[2], v[1] )


# ----------------------------------------------------------------------------------------
# scene lighting
# ----------------------------------------------------------------------------------------

def ensure_scene_lighting( scene, unit_scale=None ):
    for k, v in SCENE_DEFAULTS.items():
        if k not in scene.keys():
            scene[k] = v
    if unit_scale is not None:
        scene['mt_unit_scale'] = float( unit_scale )
    ensure_key_light( scene )

def _is_sun( obj ):
    return obj is not None and obj.type == 'LIGHT' and obj.data is not None and obj.data.type == 'SUN'

def key_light( scene ):
    '''The sun lamp the MT materials follow: the one picked in the panel, else 'MT Key Light'.'''
    mip = getattr( scene, 'sub_scene_properties', None )
    obj = getattr( mip, 'mt_key_light', None ) if mip is not None else None
    if _is_sun( obj ):
        return obj
    obj = bpy.data.objects.get( KEY_LIGHT_NAME )
    return obj if _is_sun( obj ) else None

def ensure_key_light( scene ):
    '''Makes sure a sun lamp drives the MT lighting. Any sun in the scene can be picked in the
    panel; its rotation sets mt_light_dir and its colour times strength sets mt_light_color,
    so it lights MT materials and regular Blender materials the same way.'''
    obj = key_light( scene )
    if obj is None:
        old = bpy.data.objects.get( KEY_LIGHT_NAME )
        direction = scene.get( 'mt_light_dir', SCENE_DEFAULTS['mt_light_dir'] )
        if old is not None:
            # blends from before this change have an arrow empty here, keep its direction
            if old.type == 'EMPTY':
                direction = tuple( old.matrix_world.col[2][:3] )
            old.name = KEY_LIGHT_NAME + ' (old)'
        sun = bpy.data.lights.new( KEY_LIGHT_NAME, 'SUN' )
        obj = bpy.data.objects.new( KEY_LIGHT_NAME, sun )
        scene.collection.objects.link( obj )
        set_key_light_direction( scene, direction, obj )
        set_key_light_color( scene, scene.get( 'mt_light_color', SCENE_DEFAULTS['mt_light_color'] ), obj )
    mip = getattr( scene, 'sub_scene_properties', None )
    if mip is not None and hasattr( mip, 'mt_key_light' ) and not _is_sun( mip.mt_key_light ):
        mip.mt_key_light = obj
    _drive_from_key_light( scene )
    return obj

def set_key_light_direction( scene, direction, obj=None ):
    d = mathutils.Vector( direction )
    if d.length < 1e-8:
        return
    d.normalize()
    scene['mt_light_dir'] = tuple( d )
    obj = obj or key_light( scene )
    if obj is not None:
        # a sun shines down its -Z, so +Z points at the light like the game's mDir
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = d.to_track_quat( 'Z', 'Y' )

def set_key_light_color( scene, color, obj=None ):
    c = [ float( x ) for x in tuple( color )[:3] ]
    scene['mt_light_color'] = tuple( c )
    obj = obj or key_light( scene )
    if obj is not None:
        strength = max( c ) if max( c ) > 0 else 0.0
        obj.data.color = [ x / strength for x in c ] if strength > 0 else ( 1.0, 1.0, 1.0 )
        obj.data.energy = strength

def _drive_from_key_light( scene ):
    '''Drivers on the scene props, read through the panel's key light pointer, so picking a
    different sun retargets every MT material at once.'''
    if not hasattr( getattr( scene, 'sub_scene_properties', None ), 'mt_key_light' ):
        return
    for prop in ( 'mt_light_dir', 'mt_light_color' ):
        try:
            scene.driver_remove( '["%s"]' % prop )
        except Exception:
            pass
    base = 'sub_scene_properties.mt_key_light'
    try:
        for i in range( 3 ):
            drv = scene.driver_add( '["mt_light_dir"]', i ).driver
            drv.type = 'SCRIPTED'
            var = drv.variables.new()
            var.name = 'z'
            var.targets[0].id_type = 'SCENE'
            var.targets[0].id = scene
            # RNA matrices are column major, so [2][i] is component i of the sun's +Z axis
            var.targets[0].data_path = '%s.matrix_world[2][%d]' % ( base, i )
            drv.expression = 'z'

            drv = scene.driver_add( '["mt_light_color"]', i ).driver
            drv.type = 'SCRIPTED'
            for name, path in ( ( 'c', '%s.data.color[%d]' % ( base, i ) ), ( 'e', '%s.data.energy' % base ) ):
                var = drv.variables.new()
                var.name = name
                var.targets[0].id_type = 'SCENE'
                var.targets[0].id = scene
                var.targets[0].data_path = path
            drv.expression = 'c * e'
    except Exception:
        pass

def set_view_transform_standard( scene ):
    try:
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
    except Exception:
        pass


# ----------------------------------------------------------------------------------------
# stage sdl
# ----------------------------------------------------------------------------------------

_SDL_VALUE = { 6: ( '<i', 4 ), 7: ( '<q', 8 ), 8: ( '<4f', 16 ), 9: ( '<f', 4 ), 11: ( '<B', 1 ) }

def read_sdl( path ):
    '''-> list of units, each { name, props: { name: first key value } }.'''
    d = open( path, 'rb' ).read()
    if d[:4] != b'SDL\0':
        return []
    count = struct.unpack_from( '<H', d, 6 )[0]
    strings = struct.unpack_from( '<Q', d, 0x18 )[0]
    def s( o ):
        e = d.index( b'\0', strings + o )
        return d[strings + o:e].decode( 'latin1' )
    tracks = []
    for i in range( count ):
        o = 0x20 + i * 0x30
        tt, pt, nf, parent = struct.unpack_from( '<BBHI', d, o )
        name = s( struct.unpack_from( '<Q', d, o + 8 )[0] )
        fo, vo = struct.unpack_from( '<QQ', d, o + 0x20 )
        val = None
        if tt in _SDL_VALUE and nf:
            fmt, size = _SDL_VALUE[tt]
            val = struct.unpack_from( fmt, d, vo )
            val = val if len( val ) > 1 else val[0]
        tracks.append( ( tt, parent, name, val ) )
    units = []
    for i, ( tt, parent, name, val ) in enumerate( tracks ):
        if tt == 2:
            units.append( { 'index': i, 'name': name, 'props': {} } )
    by_index = { u['index']: u for u in units }
    for i, ( tt, parent, name, val ) in enumerate( tracks ):
        if val is None:
            continue
        # props hang off their unit directly or through a Param track
        p = parent
        while p in range( len( tracks ) ) and p not in by_index and tracks[p][0] == 5:
            p = tracks[p][1]
        if p in by_index:
            by_index[p]['props'][name] = val
    return units

def load_stage_lighting( scene, sdl_folder ):
    '''Reads every .sdl in a stage's sdl folder and sets the scene's MT lighting from the
    character key light and the ToonLight. Returns a short report.'''
    units = []
    for fn in sorted( os.listdir( sdl_folder ) ):
        if fn.lower().endswith( '.sdl' ):
            try:
                for u in read_sdl( os.path.join( sdl_folder, fn ) ):
                    u['file'] = fn
                    units.append( u )
            except Exception:
                pass
    ensure_scene_lighting( scene )
    report = []

    def is_char_light( u ):
        g = u['props'].get( 'mGroup' )
        return 'InfiniteLight' in u['name'] and isinstance( g, int ) and ( g & 1 )
    lights = [ u for u in units if is_char_light( u ) and 'mDir' in u['props'] ]
    if not lights:
        lights = [ u for u in units if 'InfiniteLight' in u['name'] and 'mDir' in u['props'] ]
    if lights:
        u = lights[0]
        set_key_light_direction( scene, mt_to_blender( u['props']['mDir'] ) )
        if 'mColor' in u['props']:
            set_key_light_color( scene, u['props']['mColor'][:3] )
        report.append( f"key light {u['name']} ({u['file']})" )

    toons = [ u for u in units if u['name'] == 'ToonLight' ]
    # prefer the one in the environment file over the rimLight_* presets
    toons.sort( key=lambda u: 0 if 'environment' in u['file'].lower() else 1 )
    if toons:
        p = toons[0]['props']
        if 'mRimLightColorFactor' in p:
            scene['mt_rim_color'] = tuple( p['mRimLightColorFactor'][:3] )
        if 'mRimLightPower' in p:
            scene['mt_rim_power'] = float( p['mRimLightPower'] )
        if 'mRimLightMinHeight' in p:
            scene['mt_rim_min_height'] = float( p['mRimLightMinHeight'] )
        if 'mRimLightMaxHeight' in p:
            scene['mt_rim_max_height'] = float( p['mRimLightMaxHeight'] )
        report.append( f"rim from {toons[0]['file']}" )

    for u in units:
        if 'mGeometryThick' in u['props']:
            scene['mt_outline_thickness'] = float( u['props']['mGeometryThick'] )
            break
    return ', '.join( report ) if report else 'no lights found'


# ----------------------------------------------------------------------------------------
# node building helpers
# ----------------------------------------------------------------------------------------

class _NB:
    '''Small helper so the shader maths reads like maths. Every method returns an output
    socket; inputs can be sockets or plain numbers / tuples.'''
    def __init__( self, tree ):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links
        self.count = 0
        self.attr_cache = {}

    def node( self, kind, label=None, **props ):
        n = self.nodes.new( kind )
        col, row = divmod( self.count, 24 )
        n.location = ( -1400 + col * 220, 600 - row * 140 )
        self.count += 1
        for k, v in props.items():
            setattr( n, k, v )
        if label:
            n.label = label
        return n

    def feed( self, sock, val ):
        if isinstance( val, bpy.types.NodeSocket ):
            self.links.new( val, sock )
        elif val is not None:
            try:
                sock.default_value = val
            except Exception:
                if isinstance( val, ( int, float ) ):
                    sock.default_value = ( val, val, val )
                else:
                    raise

    def math( self, op, a, b=None, c=None, clamp=False, label=None ):
        n = self.node( 'ShaderNodeMath', label, operation=op, use_clamp=clamp )
        self.feed( n.inputs[0], a )
        if b is not None: self.feed( n.inputs[1], b )
        if c is not None: self.feed( n.inputs[2], c )
        return n.outputs[0]

    def vec( self, op, a, b=None, label=None ):
        n = self.node( 'ShaderNodeVectorMath', label, operation=op )
        self.feed( n.inputs[0], a )
        if b is not None:
            if op == 'SCALE':
                self.feed( n.inputs['Scale'], b )
            else:
                self.feed( n.inputs[1], b )
        out = 'Value' if op in ( 'DOT_PRODUCT', 'LENGTH', 'DISTANCE' ) else 'Vector'
        return n.outputs[out]

    def sep( self, v ):
        n = self.node( 'ShaderNodeSeparateXYZ' )
        self.feed( n.inputs[0], v )
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def comb( self, x, y, z ):
        n = self.node( 'ShaderNodeCombineXYZ' )
        self.feed( n.inputs[0], x ); self.feed( n.inputs[1], y ); self.feed( n.inputs[2], z )
        return n.outputs[0]

    def lerp_f( self, t, a, b ):
        '''a + t * (b - a) for floats'''
        return self.math( 'MULTIPLY_ADD', t, self.math( 'SUBTRACT', b, a ), a )

    def lerp_v( self, t, a, b ):
        return self.vec( 'ADD', a, self.vec( 'SCALE', self.vec( 'SUBTRACT', b, a ), t ) )

    def eq( self, a, value ):
        return self.math( 'COMPARE', a, value, 0.25 )

    def scene_value( self, name, kind ):
        '''A scene custom property, read through a View Layer attribute node.'''
        key = ( name, kind )
        if key in self.attr_cache:
            return self.attr_cache[key]
        n = self.node( 'ShaderNodeAttribute', name )
        n.attribute_type = 'VIEW_LAYER'
        n.attribute_name = name
        out = n.outputs['Fac'] if kind == 'float' else n.outputs['Vector']
        self.attr_cache[key] = out
        return out

    def srgb_decode( self, v ):
        '''exact sRGB -> linear per channel, so Standard view shows the raw value'''
        chans = []
        for c in self.sep( v ):
            c = self.math( 'MAXIMUM', c, 0.0 )
            lo = self.math( 'DIVIDE', c, 12.92 )
            hi = self.math( 'POWER', self.math( 'DIVIDE', self.math( 'ADD', c, 0.055 ), 1.055 ), 2.4 )
            is_hi = self.math( 'GREATER_THAN', c, 0.04045 )
            chans.append( self.lerp_f( is_hi, lo, hi ) )
        return self.comb( *chans )


def _interface_new( group, name, socket_type, in_out ):
    if hasattr( group, 'interface' ):
        return group.interface.new_socket( name=name, in_out=in_out, socket_type=socket_type )
    coll = group.inputs if in_out == 'INPUT' else group.outputs
    return coll.new( socket_type, name )

def _make_group( name, inputs, outputs ):
    group = bpy.data.node_groups.new( name, 'ShaderNodeTree' )
    group['mt_version'] = GROUP_VERSION
    for sname, stype, default in inputs:
        sock = _interface_new( group, sname, stype, 'INPUT' )
        if default is not None:
            try:
                sock.default_value = default
            except Exception:
                pass
    for sname, stype in outputs:
        _interface_new( group, sname, stype, 'OUTPUT' )
    gin = group.nodes.new( 'NodeGroupInput' ); gin.location = ( -1700, 0 )
    gout = group.nodes.new( 'NodeGroupOutput' ); gout.location = ( 1800, 0 )
    return group, gin.outputs, gout.inputs

def _current( name ):
    '''An existing group of this version is reused, so edits to it survive reimports.
    Older versions get renamed out of the way instead of overwritten.'''
    g = bpy.data.node_groups.get( name )
    if g is None:
        return None
    if g.get( 'mt_version', 1 ) >= GROUP_VERSION:
        return g
    g.name = name + ' (old)'
    return None


# ----------------------------------------------------------------------------------------
# MT Toon Coords
# ----------------------------------------------------------------------------------------

def get_coords_group():
    g = _current( COORDS_GROUP )
    if g is not None:
        return g
    group, I, O = _make_group( COORDS_GROUP, (
        ( 'Normal',                'NodeSocketVector', ( 0.0, 0.0, 1.0 ) ),
        ( 'Vertex Normal',         'NodeSocketVector', ( 0.0, 0.0, 1.0 ) ),
        ( 'fHalfLambertRevise',    'NodeSocketFloat', 0.5 ),
        ( 'fHalfLambertReviseRev', 'NodeSocketFloat', 0.5 ),
        ( 'Uroko',                 'NodeSocketFloat', 0.0 ),
        ( 'fUrokoFactor',          'NodeSocketFloat', 1.0 ),
    ), (
        ( 'Toon UV',        'NodeSocketVector' ),
        ( 'Rev UV',         'NodeSocketVector' ),
        ( 'View UV',        'NodeSocketVector' ),
        ( 'Shading Normal', 'NodeSocketVector' ),
        ( 'NdotL',          'NodeSocketFloat' ),
    ) )
    b = _NB( group )
    L = b.vec( 'NORMALIZE', b.scene_value( 'mt_light_dir', 'vector' ), label='L' )
    N = b.vec( 'NORMALIZE', I['Normal'] )
    Nv = b.vec( 'NORMALIZE', I['Vertex Normal'] )
    ndl = b.vec( 'DOT_PRODUCT', N, L, label='N.L' )

    # FToonShaderUroko pulls the normal toward the vertex normal as N.L rises
    p = b.math( 'MULTIPLY', I['Uroko'],
                b.math( 'POWER', b.math( 'MAXIMUM', b.math( 'MINIMUM', ndl, 1.0 ), 0.0 ), I['fUrokoFactor'] ) )
    Nb = b.vec( 'ADD', N, b.vec( 'SCALE', b.vec( 'SUBTRACT', Nv, N ), p ), label='uroko normal' )
    nbdl = b.vec( 'DOT_PRODUCT', Nb, L )

    def ramp_u( s, d ):
        # u = max(0, s * N.L + saturate(1 - s))
        return b.math( 'MAXIMUM', b.math( 'MULTIPLY_ADD', s, d, b.math( 'SUBTRACT', 1.0, s, clamp=True ) ), 0.0 )
    O_toon = b.comb( ramp_u( I['fHalfLambertRevise'], nbdl ), 0.5, 0.0 )
    O_rev = b.comb( ramp_u( I['fHalfLambertReviseRev'], ndl ), 0.5, 0.0 )

    # sphere map / FUVViewNormal: view space vertex normal, (x, y) * 0.5 + 0.5
    vt = b.node( 'ShaderNodeVectorTransform', 'view normal' )
    vt.vector_type = 'NORMAL'; vt.convert_from = 'WORLD'; vt.convert_to = 'CAMERA'
    b.feed( vt.inputs[0], Nv )
    vn = b.vec( 'NORMALIZE', vt.outputs[0] )
    vx, vy, _ = b.sep( vn )
    O_view = b.comb( b.math( 'MULTIPLY_ADD', vx, 0.5, 0.5 ), b.math( 'MULTIPLY_ADD', vy, 0.5, 0.5 ), 0.0 )

    b.links.new( O_toon, O['Toon UV'] )
    b.links.new( O_rev, O['Rev UV'] )
    b.links.new( O_view, O['View UV'] )
    b.links.new( Nb, O['Shading Normal'] )
    b.links.new( ndl, O['NdotL'] )
    return group


# ----------------------------------------------------------------------------------------
# MT Character
# ----------------------------------------------------------------------------------------

CHARACTER_INPUTS = (
    # textures
    ( 'Albedo',            'NodeSocketColor',  ( 0.8, 0.8, 0.8, 1.0 ) ),
    ( 'Alpha',             'NodeSocketFloat',  1.0 ),
    ( 'Normal',            'NodeSocketVector', ( 0.0, 0.0, 1.0 ) ),
    ( 'Shading Normal',    'NodeSocketVector', ( 0.0, 0.0, 1.0 ) ),
    ( 'Occlusion',         'NodeSocketFloat',  1.0 ),
    ( 'Specular Mask',     'NodeSocketFloat',  1.0 ),
    ( 'Toon Ramp',         'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'Toon Rev Ramp',     'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'Reflection',        'NodeSocketColor',  ( 0.0, 0.0, 0.0, 1.0 ) ),
    # mrl constants, named as in the shader
    ( 'fAlbedoColor',      'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'fDiffuseColor',     'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'fSpecularColor',    'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'fShininess',        'NodeSocketFloat',  16.0 ),
    ( 'fReflectiveColor',  'NodeSocketColor',  ( 1.0, 1.0, 1.0, 1.0 ) ),
    ( 'fFresnelSchlick',   'NodeSocketFloat',  0.0 ),
    ( 'fFresnelLegacyFactor', 'NodeSocketFloat', 1.0 ),
    ( 'fFresnelLegacyBias', 'NodeSocketFloat', 0.0 ),
    ( 'fDiffuseColorCorectValue', 'NodeSocketFloat', 1.22 ),
    ( 'fTransparency',     'NodeSocketFloat',  1.0 ),
    # which building blocks the mrl flags picked
    ( 'Toon',              'NodeSocketFloat',  1.0 ),   # FBRDF FToonShader*, else lambert
    ( 'Color Correct',     'NodeSocketFloat',  0.0 ),   # FDiffuse FDiffuseColorCorect
    ( 'Specular',          'NodeSocketFloat',  1.0 ),   # 0 Disable, 1 MaskToon, 2 Map
    ( 'Rim',               'NodeSocketFloat',  1.0 ),   # FCalcRimLight (not None)
    ( 'Fresnel',           'NodeSocketFloat',  0.0 ),   # 0 none, 1 Schlick, 2 Legacy
    ( 'Use Alpha',         'NodeSocketFloat',  0.0 ),
)

def get_character_group():
    g = _current( CHARACTER_GROUP )
    if g is not None:
        return g
    group, I, O = _make_group( CHARACTER_GROUP, CHARACTER_INPUTS, (
        ( 'Shader', 'NodeSocketShader' ),
        ( 'Color',  'NodeSocketColor' ),
    ) )
    b = _NB( group )
    L = b.vec( 'NORMALIZE', b.scene_value( 'mt_light_dir', 'vector' ), label='L' )
    LC = b.scene_value( 'mt_light_color', 'vector' )
    AMB = b.scene_value( 'mt_ambient', 'vector' )
    geo = b.node( 'ShaderNodeNewGeometry' )
    V = geo.outputs['Incoming']
    N = b.vec( 'NORMALIZE', I['Normal'] )
    Ns = b.vec( 'NORMALIZE', I['Shading Normal'] )
    ndl = b.vec( 'DOT_PRODUCT', N, L, label='N.L' )
    ndv = b.vec( 'DOT_PRODUCT', N, V, label='N.V' )

    # diffuse light: (light * ramp + ambient), or plain lambert for non toon FBRDF
    d_toon = b.vec( 'ADD', b.vec( 'MULTIPLY', LC, I['Toon Ramp'] ), AMB )
    d_lam = b.vec( 'ADD', b.vec( 'SCALE', LC, b.math( 'MAXIMUM', ndl, 0.0 ) ), AMB )
    D = b.lerp_v( I['Toon'], d_lam, d_toon )
    Dlit = b.vec( 'SCALE', b.vec( 'MULTIPLY', D, I['fDiffuseColor'] ), I['Occlusion'], )

    # albedo, saturated like the shader's mul_sat
    am = b.node( 'ShaderNodeMix', 'albedo x fAlbedoColor' )
    am.data_type = 'RGBA'; am.blend_type = 'MULTIPLY'; am.clamp_result = True
    am.inputs['Factor'].default_value = 1.0
    b.feed( am.inputs[6], I['Albedo'] ); b.feed( am.inputs[7], I['fAlbedoColor'] )
    A = am.outputs[2]

    # FDiffuseColorCorect: saturation boost from how grey the light is
    s = b.math( 'DIVIDE', b.vec( 'DOT_PRODUCT', Dlit, ( 1.0, 1.0, 1.0 ) ),
                b.math( 'MAXIMUM', b.vec( 'LENGTH', Dlit ), 1e-6 ) )
    k = b.math( 'MULTIPLY',
                b.math( 'SUBTRACT', 1.0, b.math( 'EXPONENT', b.math( 'MULTIPLY', I['fDiffuseColorCorectValue'], -1.0 ) ) ),
                b.math( 'SUBTRACT', 1.0, b.math( 'DIVIDE', s, 3.0 ) ) )
    hsv = b.node( 'ShaderNodeHueSaturation', 'color correct' )
    hsv.inputs['Hue'].default_value = 0.5
    b.feed( hsv.inputs['Saturation'], b.math( 'ADD', 1.0, k ) )
    b.feed( hsv.inputs['Value'], b.math( 'MULTIPLY', s, 0.583333 ) )
    hsv.inputs['Fac'].default_value = 1.0
    b.feed( hsv.inputs['Color'], A )
    A2 = b.lerp_v( I['Color Correct'], A, hsv.outputs['Color'] )
    diffuse = b.vec( 'MULTIPLY', Dlit, A2, label='diffuse' )

    # Blinn specular on the (uroko) shading normal
    H = b.vec( 'NORMALIZE', b.vec( 'ADD', L, V ) )
    ndh = b.vec( 'DOT_PRODUCT', Ns, H )
    on = b.math( 'GREATER_THAN', ndh, 1e-5 )
    pw = b.math( 'MULTIPLY', b.math( 'POWER', b.math( 'MAXIMUM', ndh, 1e-5 ), I['fShininess'] ), on )
    spec = b.vec( 'SCALE', b.vec( 'MULTIPLY', LC, I['fSpecularColor'] ), pw )
    spec = b.vec( 'SCALE', spec, b.math( 'GREATER_THAN', I['Specular'], 0.5 ) )
    refl = b.vec( 'MULTIPLY', I['Reflection'], I['fReflectiveColor'] )
    sr = b.vec( 'ADD', spec, refl )

    f5 = b.math( 'POWER', b.math( 'MAXIMUM', b.math( 'SUBTRACT', 1.0, ndv ), 0.0 ), 5.0 )
    schlick = b.math( 'MULTIPLY_ADD', f5, b.math( 'SUBTRACT', 1.0, I['fFresnelSchlick'] ), I['fFresnelSchlick'] )
    legacy = b.math( 'SUBTRACT', 1.0,
                     b.math( 'MULTIPLY_ADD', f5, I['fFresnelLegacyFactor'], I['fFresnelLegacyBias'], clamp=True ) )
    F = b.lerp_f( b.eq( I['Fresnel'], 1.0 ), 1.0, schlick )
    F = b.lerp_f( b.eq( I['Fresnel'], 2.0 ), F, legacy )
    # MaskToon skips the vertex occlusion, Map and the no spec map case apply it
    occ_f = b.lerp_f( b.eq( I['Specular'], 1.0 ), I['Occlusion'], 1.0 )
    spec_out = b.vec( 'SCALE', sr, b.math( 'MULTIPLY', b.math( 'MULTIPLY', F, I['Specular Mask'] ), occ_f ), )

    # rim: (1 - N.V)^2 ^ power * light * rev ramp * height fade * rim colour * spec mask
    r = b.math( 'POWER', b.math( 'MAXIMUM', b.math( 'SUBTRACT', 1.0, ndv ), 1e-5 ), 2.0 )
    rp = b.math( 'POWER', r, b.scene_value( 'mt_rim_power', 'float' ) )
    pz = b.sep( geo.outputs['Position'] )[2]
    h = b.math( 'DIVIDE', pz, b.math( 'MAXIMUM', b.scene_value( 'mt_unit_scale', 'float' ), 1e-6 ) )
    hmin = b.scene_value( 'mt_rim_min_height', 'float' )
    hmax = b.scene_value( 'mt_rim_max_height', 'float' )
    fade = b.math( 'DIVIDE', b.math( 'SUBTRACT', h, hmin ),
                   b.math( 'MAXIMUM', b.math( 'SUBTRACT', hmax, hmin ), 1e-6 ), clamp=True )
    rim = b.vec( 'MULTIPLY', b.vec( 'MULTIPLY', LC, I['Toon Rev Ramp'] ), b.scene_value( 'mt_rim_color', 'vector' ) )
    rim = b.vec( 'SCALE', rim, b.math( 'MULTIPLY', b.math( 'MULTIPLY', rp, fade ),
                                       b.math( 'MULTIPLY', I['Specular Mask'], I['Rim'] ) ) )

    total = b.vec( 'ADD', b.vec( 'ADD', diffuse, spec_out ), rim, label='game colour' )
    shown = b.srgb_decode( total )

    emit = b.node( 'ShaderNodeEmission' )
    b.feed( emit.inputs['Color'], shown )
    trans = b.node( 'ShaderNodeBsdfTransparent' )
    alpha = b.lerp_f( I['Use Alpha'], 1.0, b.math( 'MULTIPLY', I['Alpha'], I['fTransparency'] ) )
    mix = b.node( 'ShaderNodeMixShader' )
    b.feed( mix.inputs['Fac'], alpha )
    b.links.new( trans.outputs[0], mix.inputs[1] )
    b.links.new( emit.outputs[0], mix.inputs[2] )
    b.links.new( mix.outputs[0], O['Shader'] )
    b.links.new( total, O['Color'] )
    return group


# ----------------------------------------------------------------------------------------
# textures
# ----------------------------------------------------------------------------------------

def _pixels( img ):
    w, h = img.size
    buf = np.empty( w * h * 4, dtype=np.float32 )
    img.pixels.foreach_get( buf )
    return buf.reshape( h, w, 4 )

def _new_image( name, w, h, px, path=None, non_color=False ):
    out = bpy.data.images.new( name, w, h, alpha=True )
    # colour space first, changing it later regenerates a generated image and wipes it
    if non_color:
        try:
            out.colorspace_settings.name = 'Non-Color'
        except Exception:
            pass
    out.pixels.foreach_set( np.ascontiguousarray( px, dtype=np.float32 ).ravel() )
    out.update()
    if path:
        try:
            out.filepath_raw = path
            out.file_format = 'PNG'
            out.save()
        except Exception:
            out.pack()
    else:
        out.pack()
    return out

YUV_OFFSET = 123.0 / 255.0     # the game's decode, from the material and GUI shaders

def decode_yuv_image( img, png_path=None ):
    '''Format 42 (BM_HQ) textures hold Y in alpha, V in red, U in blue and opacity in
    green. Returns a new RGBA image with the game's own BT.601 decode applied.'''
    if np is None or img is None:
        return img
    px = _pixels( img ).astype( np.float64 )
    v = px[..., 0] - YUV_OFFSET
    a = px[..., 1]
    u = px[..., 2] - YUV_OFFSET
    y = px[..., 3]
    out = np.empty_like( px )
    out[..., 0] = y + 1.402 * v
    out[..., 1] = y - 0.34414 * u - 0.71414 * v
    out[..., 2] = y + 1.772 * u
    out[..., 3] = a
    out = np.clip( out, 0.0, 1.0 )
    h, w = px.shape[:2]
    new = _new_image( img.name.rsplit( '.', 1 )[0] + '_rgb', w, h, out, png_path )
    new['mt_tex_format'] = 42
    return new

def bake_toon_high_ramp( img, toon_factor ):
    '''FToonShaderHigh tweaks the ramp colour with fToonFactor before lighting. It's a
    per texel function, so bake it into a copy of the ramp (exact port, see mtramp).'''
    from ..mtlib import mtramp
    if np is None or img is None:
        return img
    key = '%s_high_%.4f_%.4f_%.4f' % ( img.name, toon_factor[0], toon_factor[1], toon_factor[2] )
    existing = bpy.data.images.get( key )
    if existing is not None:
        return existing
    px = _pixels( img )
    h, w = px.shape[:2]
    rgb = mtramp.toon_high( px[..., :3].reshape( -1, 3 ), toon_factor ).reshape( h, w, 3 )
    out = np.concatenate( [ rgb, px[..., 3:4] ], axis=2 )
    new = _new_image( key, w, h, out, None, non_color=True )
    return new
