'''Exact MT materials: the game's own pixel shader, compiled to Blender nodes.

For each material (and vertex layout) this picks the program UMvC3 itself would run, the
same way the game does (MRL flags and textures plus the renderer's own overrides, hashed
into the root.spkg key), and turns that pixel shader into Math nodes instruction by
instruction (mtlib.sm3ir). The vertex shader is not run; instead each of its outputs is
identified numerically (mtshaders.classify_vs) and fed from the matching Blender value
(world normal, position, tangent frame, view vector, uv), converted to the game's axes.

Constants come from three places:
  - the MRL cbuffers ($Globals, CBMaterial, CBHalfLambert, ...)          -> literal values
  - everything the renderer sets (lights, rim, ambient, cut-in, HDR ...) -> scene custom
    properties "mtc_<ctab name>_<row>", 4 floats each, read with View Layer attribute nodes.
    Defaults below, real values from a FrameCapture of the game, lights from Blender.

The output is oC0 as the game writes it (gamma space), turned into linear with the exact
sRGB curve so Standard view shows the game's numbers.
'''
import os
import json

import bpy
import mathutils

from ..mtlib import mtshaders, sm3ir

# ----------------------------------------------------------------------------------------
# renderer side values (Training Room; replaced by capture data when available)
# ----------------------------------------------------------------------------------------

RENDERER_DEFAULTS = {
    # key light: [1] = direction to the light (MT axes), [2] = colour
    'sLightParam0': [ ( 0.0, 0.0, 0.0, 0.0 ), ( 0.03236, 0.4475, 0.8937, 0.0 ), ( 1.15, 1.15, 1.15, 0.0 ), ( 0.0, 0.0, 0.0, 0.0 ) ],
    'sLightParam1': [ ( 0.0, 0.0, 0.0, 0.0 ), ( 0.0, 0.0, 0.0, 0.0 ), ( 0.0, 0.0, 0.0, 0.0 ), ( 0.0, 1.0, 0.0, 0.0 ) ],
    'CBAmbient__packed0': [ ( 0.0, 0.0, 0.0, 0.0 ) ],
    'CBAmbient__packed1': [ ( 0.0, 0.0, 0.0, 0.0 ) ],
    'CBToon__packed0': [ ( 2.0, 15.0, 4.0, 0.0 ) ],
    'fRimLightColorFactor': [ ( 0.0, 2.326, 10.0, 1.0 ) ],
    'fCutInFactor': [ ( 1.0, 1.0, 1.0, 1.0 ) ],
    'fGlobalTransparency': [ ( 1.0, 1.0, 1.0, 1.0 ) ],
    'CBROPTest__packed0': [ ( 0.0, 0.0, 0.0, 0.0 ) ],
    'CBHDRFactor__packed0': [ ( 1.0, 1.0, 1.0, 1.0 ) ],
    'fLightMaskSelector': [ ( 0.0, 0.0, 0.0, 0.0 ) ],
    'CBScreen__packed0': [ ( 0.0, 0.0, 1.0, 1.0 ) ],
    'CBScreen__packed1': [ ( 1280.0, 720.0, 1.0 / 1280.0, 1.0 / 720.0 ) ],
}

TEMPLATE_FILE = os.path.join( os.path.dirname( os.path.dirname( __file__ ) ), 'mtlib', 'res', 'renderer_templates.json' )

def renderer_templates():
    try:
        with open( TEMPLATE_FILE ) as f:
            return json.load( f )
    except Exception:
        return None

def scene_prop_name( ctab_name, row ):
    return 'mtc_%s_%d' % ( ctab_name, row )

def ensure_renderer_props( scene, values=None, overwrite=False ):
    '''Writes the renderer constants as scene props (mtc_<name>_<row>).'''
    values = values or RENDERER_DEFAULTS
    for name, rows in values.items():
        for r, v in enumerate( rows ):
            key = scene_prop_name( name, r )
            if overwrite or key not in scene.keys():
                scene[key] = [ float( x ) for x in tuple( v )[:4] ] + [ 0.0 ] * ( 4 - len( tuple( v )[:4] ) )


# ----------------------------------------------------------------------------------------
# picking the program
# ----------------------------------------------------------------------------------------

SKINNING = {
    'IASkinTB1wt': ( 'FSkinning1Weight', 'FSkinningPF1Weight' ),
    'IASkinTBC1wt': ( 'FSkinning1Weight', 'FSkinningPF1Weight' ),
    'IASkinTB2wt': ( 'FSkinning2Weight', 'FSkinningPF2Weight' ),
    'IASkinTB4wt': ( 'FSkinning4WeightBranch', 'FSkinningPF4WeightBranch' ),
    'IASkinTBC8wt': ( 'FSkinning8WeightBranch', 'FSkinningPF8WeightBranch' ),
    'IASkinBridge1wt': ( 'FSkinning1Weight', 'FSkinningPF1Weight' ),
    'IASkinBridge2wt': ( 'FSkinning2Weight', 'FSkinningPF2Weight' ),
    'IASkinBridge4wt': ( 'FSkinning4WeightBranch', 'FSkinningPF4WeightBranch' ),
    'IASkinBridge8wt': ( 'FSkinning8WeightBranch', 'FSkinningPF8WeightBranch' ),
}

def technique_for( material ):
    t = ( material.type or '' ).split( ':' )[-1]
    return 'T' + t if t else 'TMaterialChar'

def material_overrides( material, images ):
    '''MRL flags and textures -> {slot: impl name or ("tex", type)}'''
    named = {}
    for cmd in material.cmds:
        if cmd.type == 'flag' and cmd.data:
            named[cmd.name] = cmd.data
        elif cmd.type == 'texture':
            fmt = None
            img = images.get( cmd.name ) if images else None
            if img is not None:
                fmt = img.get( 'mt_tex_format' )
            named[cmd.name] = ( 'tex', mtshaders.TEX_TYPE.get( int( fmt ), 0 ) if fmt is not None else 0 )
    return named

def wanted_renderer_state( scene ):
    '''What the renderer would set for this scene: a point light in slot 1 when the MT
    point light is set, the light mask (screen space shadow mask), and the shadow face
    attenuation mode of the stage.'''
    mip = getattr( scene, 'sub_scene_properties', None )
    point = getattr( mip, 'mt_point_light', None ) if mip is not None else None
    return {
        'FDynamicLight1': 'FPointLightD' if point is not None else None,
        'FLightMask': 'FLightMaskEnable' if scene.get( 'mt_light_mask', 0 ) else None,
        'FShadowReceiveFaceAttn': scene.get( 'mt_shadow_face_attn', 'FShadowReceiveFaceAttnCut' ),
    }

def template_order( temps, scene ):
    want = wanted_renderer_state( scene )
    def score( t ):
        return sum( 1 for k, v in want.items() if t.get( k ) == v )
    return sorted( range( len( temps ) ), key=lambda i: -score( temps[i] ) )

def pick_program( db, material, ia, images, scene, outenc=1, tech=None ):
    '''Returns (Program, template index) or (None, None). Tries the renderer templates the
    game was seen using, best match for the scene first.'''
    templates = renderer_templates() or {}
    tech = tech or technique_for( material )
    temps = templates.get( '%s_%d' % ( tech, outenc ) ) or templates.get( 'TMaterialChar_%d' % outenc ) or [ {} ]
    order = template_order( temps, scene )
    named_mat = material_overrides( material, images ) if material is not None else {}
    for ti in order:
        if ti >= len( temps ):
            continue
        named = dict( temps[ti] )
        if ia in SKINNING:
            named['FSkinning'], named['FSkinningPF'] = SKINNING[ia]
        named.update( named_mat )
        prog = db.program( tech, 0, ia, outenc, named )
        if prog is not None:
            return prog, ti
    return None, None


# ----------------------------------------------------------------------------------------
# node building
# ----------------------------------------------------------------------------------------

def _is_sock( x ):
    return isinstance( x, bpy.types.NodeSocket )

class Bind:
    '''Feeds the compiled pixel shader from Blender. Everything is converted to the game's
    axes: MT (x, y, z) = Blender (x, z, -y), positions divided by the import scale.'''

    def __init__( self, tree, material, images, prog, db, scene, x0=-5000 ):
        self.tree = tree
        self.n = tree.nodes
        self.l = tree.links
        self.material = material
        self.images = images or {}
        self.prog = prog
        self.db = db
        self.scene = scene
        self.x0 = x0
        self.cache = {}
        self.ps = prog.ps
        self.ctab = sorted( [ c for c in ( self.ps.ctab['consts'] if self.ps.ctab else [] ) ], key=lambda c: c['idx'] )
        self.ps_in = mtshaders.ps_inputs( self.ps )
        self.sem = db.vs_semantics( prog.vs_index )
        self.y = 0

    # -- small helpers
    def node( self, kind, **props ):
        nd = self.n.new( kind )
        for k, v in props.items():
            setattr( nd, k, v )
        nd.location = ( self.x0 - 600, self.y )
        self.y -= 60
        nd.hide = True
        return nd

    def feed( self, sock, v ):
        if _is_sock( v ):
            self.l.new( v, sock )
        elif v is not None:
            sock.default_value = v

    def m( self, op, a, b=None, c=None ):
        nd = self.node( 'ShaderNodeMath', operation=op )
        for i, x in enumerate( ( a, b, c ) ):
            if x is not None:
                self.feed( nd.inputs[i], x )
        return nd.outputs[0]

    def sep( self, vec ):
        nd = self.node( 'ShaderNodeSeparateXYZ' )
        self.feed( nd.inputs[0], vec )
        return nd.outputs[0], nd.outputs[1], nd.outputs[2]

    def vmath( self, op, a, b=None ):
        nd = self.node( 'ShaderNodeVectorMath', operation=op )
        self.feed( nd.inputs[0], a )
        if b is not None:
            if op == 'SCALE':
                self.feed( nd.inputs['Scale'], b )
            else:
                self.feed( nd.inputs[1], b )
        return nd.outputs['Value' if op in ( 'DOT_PRODUCT', 'LENGTH', 'DISTANCE' ) else 'Vector']

    def mt_axes( self, vec, scale=False ):
        '''Blender vector -> MT components (x, y, z)'''
        x, y, z = self.sep( vec )
        out = [ x, z, self.m( 'MULTIPLY', y, -1.0 ) ]
        if scale:
            s = self.scene_float( 'mt_unit_scale', 1.0 )
            out = [ self.m( 'DIVIDE', c, s ) for c in out ]
        return out

    def scene_float( self, name, default ):
        key = ( 'sf', name )
        if key not in self.cache:
            if name not in self.scene.keys():
                return default
            a = self.node( 'ShaderNodeAttribute', attribute_type='VIEW_LAYER', attribute_name=name )
            self.cache[key] = a.outputs['Fac']
        return self.cache[key]

    def scene_vec4( self, prop ):
        key = ( 'sv', prop )
        if key not in self.cache:
            a = self.node( 'ShaderNodeAttribute', attribute_type='VIEW_LAYER', attribute_name=prop )
            a.label = prop
            x, y, z = self.sep( a.outputs['Vector'] )
            self.cache[key] = [ x, y, z, a.outputs['Alpha'] ]
        return self.cache[key]

    # -- constants
    def ctab_entry( self, reg, ctab=None ):
        for c in ( ctab if ctab is not None else self.ctab ):
            if c['set'] == 2 and c['idx'] <= reg < c['idx'] + c['cnt']:
                return c, reg - c['idx']
        return None, 0

    def const( self, reg, comp, ctab=None ):
        c, row = self.ctab_entry( reg, ctab )
        if c is None:
            return 0.0
        cb, off = mtshaders.ctab_location( c['name'] )
        if cb is not None:
            data = self.material.getCBuffer( cb )
            if data is not None:
                i = off + row * 4 + comp
                if i < len( data ):
                    return float( data[i] )
                return 0.0
        prop = scene_prop_name( c['name'], row )
        if prop not in self.scene.keys():
            self.scene[prop] = [ 0.0, 0.0, 0.0, 0.0 ]
        return self.scene_vec4( prop )[comp]

    # -- interpolators
    def geometry( self ):
        if 'geo' not in self.cache:
            self.cache['geo'] = self.node( 'ShaderNodeNewGeometry' )
        return self.cache['geo']

    def frame_vec( self, which ):
        '''tangent / bitangent of the UV map (MikkTSpace), read back through Normal Map nodes'''
        key = ( 'frame', which )
        if key not in self.cache:
            nm = self.node( 'ShaderNodeNormalMap' )
            nm.space = 'TANGENT'
            try:
                nm.uv_map = 'UVPrimary'
            except Exception:
                pass
            nm.inputs['Color'].default_value = ( 1.0, 0.5, 0.5, 1.0 ) if which == 'tangent' else ( 0.5, 1.0, 0.5, 1.0 )
            nm.inputs['Strength'].default_value = 1.0
            self.cache[key] = self.mt_axes( nm.outputs['Normal'] )
        return self.cache[key]

    def game_frame( self ):
        '''(tangent, binormal) in MT axes, as the game's vertex shader makes them: its own
        stored tangent, binormal = normalize(cross(N, T) * sign). Rebuilt from the per corner
        coefficients the importer stored against Blender's tangent frame; meshes without
        them fall back to Blender's frame.'''
        if 'gframe' in self.cache:
            return self.cache['gframe']
        geo = self.geometry()
        nm_t = self.node( 'ShaderNodeNormalMap', space='TANGENT' )
        nm_b = self.node( 'ShaderNodeNormalMap', space='TANGENT' )
        for nm, col in ( ( nm_t, ( 1.0, 0.5, 0.5, 1.0 ) ), ( nm_b, ( 0.5, 1.0, 0.5, 1.0 ) ) ):
            try:
                nm.uv_map = 'UVPrimary'
            except Exception:
                pass
            nm.inputs['Color'].default_value = col
        T_b, B_b, N_b = nm_t.outputs['Normal'], nm_b.outputs['Normal'], geo.outputs['Normal']
        coef = self.node( 'ShaderNodeAttribute', attribute_type='GEOMETRY', attribute_name='mt_tan_coef' )
        sgn = self.node( 'ShaderNodeAttribute', attribute_type='GEOMETRY', attribute_name='mt_tan_sign' )
        cx, cy, cz = self.sep( coef.outputs['Vector'] )
        Tg = self.vmath( 'ADD', self.vmath( 'ADD', self.vmath( 'SCALE', T_b, cx ), self.vmath( 'SCALE', B_b, cy ) ),
                         self.vmath( 'SCALE', N_b, cz ) )
        Tg = self.vmath( 'NORMALIZE', Tg )
        have = self.m( 'GREATER_THAN', self.vmath( 'LENGTH', coef.outputs['Vector'] ), 0.5 )
        mixT = self.node( 'ShaderNodeMix', data_type='VECTOR' )
        self.feed( mixT.inputs[0], have ); self.feed( mixT.inputs[4], T_b ); self.feed( mixT.inputs[5], Tg )
        T = self.vmath( 'NORMALIZE', mixT.outputs[1] )
        # sign: the game's when stored, else Blender's (both define it as sign * cross(N, T)
        # and agree on it for 99% of corners)
        s_have = self.m( 'MULTIPLY', sgn.outputs['Fac'], have )
        Bg = self.vmath( 'SCALE', self.vmath( 'NORMALIZE', self.vmath( 'CROSS_PRODUCT', N_b, T ) ), s_have )
        mixB = self.node( 'ShaderNodeMix', data_type='VECTOR' )
        self.feed( mixB.inputs[0], have ); self.feed( mixB.inputs[4], B_b ); self.feed( mixB.inputs[5], Bg )
        self.cache['gframe'] = ( self.mt_axes( T ), self.mt_axes( mixB.outputs[1] ) )
        return self.cache['gframe']

    def uv( self ):
        if 'uv' not in self.cache:
            u = self.node( 'ShaderNodeUVMap' )
            u.uv_map = 'UVPrimary'
            x, y, _ = self.sep( u.outputs['UV'] )
            self.cache['uv'] = ( x, self.m( 'SUBTRACT', 1.0, y ) )      # game v runs down
        return self.cache['uv']

    def semantic( self, s ):
        if s is None:
            return 0.0
        neg = s.startswith( '-' )
        if neg:
            s = s[1:]
        v = self._semantic( s )
        if neg:
            v = self.m( 'MULTIPLY', v, -1.0 ) if _is_sock( v ) else -v
        return v

    def _semantic( self, s ):
        key = ( 'sem', s )
        if key in self.cache:
            return self.cache[key]
        geo = self.geometry()
        comp = 'xyz'.index( s[-1] ) if '.' in s and s[-1] in 'xyz' else 0
        if s.startswith( 'const ' ):
            v = float( s.split()[1] )
        elif s.startswith( 'normal.' ):
            v = self._vec( 'normal', lambda: self.mt_axes( geo.outputs['Normal'] ) )[comp]
        elif s.startswith( 'pos.' ):
            v = self._vec( 'pos', lambda: self.mt_axes( geo.outputs['Position'], scale=True ) )[comp]
        elif s.startswith( 'tangent.' ):
            v = self.game_frame()[0][comp]
        elif s.startswith( 'binormal.' ):
            v = self.game_frame()[1][comp]
        elif s.startswith( 'view.' ):
            v = self._vec( 'view', lambda: self.mt_axes( self.vmath( 'SCALE', geo.outputs['Incoming'], -1.0 ) ) )[comp]
        elif s.startswith( 'eyevec.' ):
            def ev():
                cam = self.node( 'ShaderNodeCameraData' )
                return self.mt_axes( self.vmath( 'SCALE', geo.outputs['Incoming'],
                                                 self.m( 'MULTIPLY', cam.outputs['View Distance'], -1.0 ) ), scale=True )
            v = self._vec( 'eyevec', ev )[comp]
        elif s == 'eyedist':
            cam = self.node( 'ShaderNodeCameraData' )
            v = self.m( 'DIVIDE', cam.outputs['View Distance'], self.scene_float( 'mt_unit_scale', 1.0 ) )
        elif s == 'occlusion':
            a = self.node( 'ShaderNodeAttribute', attribute_type='GEOMETRY', attribute_name='mt_ao_darken' )
            v = self.m( 'SUBTRACT', 1.0, a.outputs['Fac'] )
        elif s.startswith( 'lin ' ):
            v = self.linear( s[4:] )
        else:
            v = 0.0
        self.cache[key] = v
        return v

    def _vec( self, name, make ):
        key = ( 'vec', name )
        if key not in self.cache:
            self.cache[key] = make()
        return self.cache[key]

    RAW_SKIP = ( 'position', 'normal', 'tangent', 'blendweight', 'blendindices' )

    def raw_input( self, name ):
        '''raw vertex element component, e.g. "binormal0.x": the uv lives in whatever element
        the layout put it, which is the only one that isn't position / normal / tangent'''
        usage = name.rstrip( '0123456789.xyzw' )
        comp = name[-1]
        if usage in self.RAW_SKIP:
            return 0.0
        if usage == 'color':
            return 1.0
        u, v = self.uv()
        return { 'x': u, 'y': v, 'z': 0.0, 'w': 0.0 }[comp]

    def linear( self, expr ):
        acc = None
        for term in expr.split():
            coef, name = term.split( '*', 1 )
            coef = float( coef )
            val = coef if name == '1' else self.raw_input( name )
            if name != '1':
                if _is_sock( val ):
                    val = val if abs( coef - 1.0 ) < 1e-6 else self.m( 'MULTIPLY', val, coef )
                else:
                    val = val * coef
            acc = val if acc is None else ( self.m( 'ADD', acc, val ) if ( _is_sock( acc ) or _is_sock( val ) ) else acc + val )
        return acc if acc is not None else 0.0

    GEOMETRIC = ( 'normal.', 'pos.', 'tangent.', 'binormal.', 'view.', 'eyevec.', 'eyedist', 'occlusion',
                  '-normal.', '-pos.', '-tangent.', '-binormal.', '-view.', '-eyevec.' )

    def input( self, reg, comp ):
        usage = self.ps_in.get( reg )
        if usage is None:
            return 0.0
        comps = self.sem.get( usage )
        if not comps or comps[comp] is None:
            return 0.0
        s = comps[comp]
        if s.startswith( self.GEOMETRIC ):
            return self.semantic( s )
        # anything else (uv transforms, constants the VS passes through, vertex colour):
        # run that part of the vertex shader itself, on the interpolated inputs
        return self.vs_output( usage, comp )

    def vs_output( self, usage, comp ):
        key = ( 'vsout', usage, comp )
        if key in self.cache:
            return self.cache[key]
        if 'vsir' not in self.cache:
            vs = self.prog.vs
            self.cache['vsir'] = ( vs, sm3ir.build( vs ), mtshaders._decls( vs ) )
        vs, vb, ( ins, outs ) = self.cache['vsir']
        reg = next( ( r for r, ( u, ui, m ) in outs.items() if ( u, ui ) == usage ), None )
        if reg is None:
            return 0.0
        node = vb.outputs.get( 'o%d' % reg )
        if node is None:
            return 0.0
        if 'vsemit' not in self.cache:
            from ..mtlib import sm3nodes
            self.cache['vsemit'] = sm3nodes.Emitter( self.tree, vb, VSBind( self, vs, ins ), x0=self.x0 - 2500, y0=-3000 )
        v = self.cache['vsemit'].emit_roots( [ node[comp] ] )[0]
        self.cache[key] = v
        return v

    def vface( self ):
        if 'vface' not in self.cache:
            # the game sees front faces as negative
            self.cache['vface'] = self.m( 'SUBTRACT', self.m( 'MULTIPLY', self.geometry().outputs['Backfacing'], 2.0 ), 1.0 )
        return self.cache['vface']

    def vpos( self, comp ):
        key = ( 'vpos', comp )
        if key not in self.cache:
            tc = self.node( 'ShaderNodeTexCoord' )
            x, y, _ = self.sep( tc.outputs['Window'] )
            size = self.scene_vec4( scene_prop_name( 'CBScreen__packed1', 0 ) )
            if comp == 0:
                self.cache[key] = self.m( 'MULTIPLY', x, size[0] )
            elif comp == 1:
                self.cache[key] = self.m( 'MULTIPLY', self.m( 'SUBTRACT', 1.0, y ), size[1] )
            else:
                self.cache[key] = 0.0
        return self.cache[key]

    # -- textures
    def sampler_name( self, s ):
        for c in self.ctab:
            if c['set'] == 3 and c['idx'] == s:
                return c['name']
        return ''

    def texture( self, s, kind, coords, loc ):
        name = self.sampler_name( s )
        state, _, slot = name.partition( '__' )
        img = self.images.get( slot )
        if img is None or kind != '2d':
            # system textures the game renders itself (light mask, fog table, ...) and cube
            # maps: a flat value until they're captured
            val = self.node( 'ShaderNodeRGB' )
            val.outputs[0].default_value = ( 0.0, 0.0, 0.0, 1.0 )
            val.label = slot or name
            a = self.node( 'ShaderNodeValue' )
            a.outputs[0].default_value = 0.0
            return val.outputs[0], a.outputs[0]
        t = self.n.new( 'ShaderNodeTexImage' )
        t.location = loc
        t.label = slot
        t.image = img
        try:
            img.colorspace_settings.name = 'Non-Color'
            img.alpha_mode = 'CHANNEL_PACKED'
        except Exception:
            pass
        t.interpolation = 'Closest' if 'Point' in state else 'Linear'
        t.extension = 'EXTEND' if state in ( 'SSToonMap', 'SSClamp' ) or 'Clamp' in state or 'Border' in state else 'REPEAT'
        comb = self.node( 'ShaderNodeCombineXYZ' )
        self.feed( comb.inputs[0], coords[0] )
        self.feed( comb.inputs[1], self.m( 'SUBTRACT', 1.0, coords[1] ) if _is_sock( coords[1] ) else 1.0 - coords[1] )
        self.l.new( comb.outputs[0], t.inputs['Vector'] )
        return t.outputs['Color'], t.outputs['Alpha']


class VSBind:
    """Feeds a vertex shader expression from Blender (for the outputs that aren't plain
    geometry: uv transforms, pass through constants). Skinning is identity, Blender already
    posed the mesh."""
    SKIN = { 'CBSkinning__packed0': ( 0.0, 0.5, 0.5, 0.0 ), '__tMatrixMap__invsize': ( 0.25, 0.25, 0.0, 0.0 ) }

    def __init__( self, ps_bind, vs, ins ):
        self.p = ps_bind
        self.vs = vs
        self.ins = ins
        self.ctab = sorted( vs.ctab['consts'] if vs.ctab else [], key=lambda c: c['idx'] )

    def const( self, reg, comp ):
        c, row = self.p.ctab_entry( reg, self.ctab )
        if c is not None and c['name'] in self.SKIN:
            return self.SKIN[c['name']][comp]
        return self.p.const( reg, comp, self.ctab )

    def input( self, reg, comp ):
        usage, ui, mask = self.ins.get( reg, ( None, 0, 0 ) )
        p = self.p
        if usage == 'position':
            return p.semantic( 'pos.' + 'xyz'[comp] ) if comp < 3 else 1.0
        if usage == 'normal':
            if comp < 3:
                return p.m( 'MULTIPLY_ADD', p.semantic( 'normal.' + 'xyz'[comp] ), 0.5, 0.5 )
            return p.m( 'MULTIPLY_ADD', p.semantic( 'occlusion' ), 0.5, 0.5 )
        if usage == 'tangent':
            if comp < 3:
                return p.m( 'MULTIPLY_ADD', p.semantic( 'tangent.' + 'xyz'[comp] ), 0.5, 0.5 )
            return 1.0
        if usage in ( 'blendweight', 'blendindices' ):
            return 0.0
        if usage == 'color':
            return 1.0
        u, v = p.uv()
        return ( u, v, 0.0, 0.0 )[comp]

    def vface( self ):
        return -1.0

    def vpos( self, comp ):
        return 0.0

    def texture( self, s, kind, coords, loc ):
        # bone matrix texture: identity rows, picked by texel column like the classifier sets up
        p = self.p
        x = coords[0]
        k = p.m( 'ROUND', p.m( 'MULTIPLY', p.m( 'SUBTRACT', x, 0.5 ), 4.0 ) ) if _is_sock( x ) else round( ( x - 0.5 ) * 4 )
        rows = []
        for i in range( 4 ):
            rows.append( p.m( 'COMPARE', k, float( i ), 0.25 ) if _is_sock( k ) else ( 1.0 if k == i else 0.0 ) )
        comb = p.node( 'ShaderNodeCombineColor' )
        for i in range( 3 ):
            p.feed( comb.inputs[i], rows[i] )
        a = rows[3]
        if not _is_sock( a ):
            val = p.node( 'ShaderNodeValue' )
            val.outputs[0].default_value = a
            a = val.outputs[0]
        return comb.outputs[0], a


class StoredMaterial:
    """The bits of an MRL material exact mode needs, kept on the Blender material as JSON so
    the shaders can be rebuilt later (after adding a point light, say) without the mrl."""
    def __init__( self, d ):
        self.name = d.get( 'name', '' )
        self.type = d.get( 'type', '' )
        self.blendState = d.get( 'blendState' )
        self.cmds = [ _Cmd( *c ) for c in d.get( 'cmds', [] ) ]
        self._cb = d.get( 'cbuffers', {} )
        self._alpha = d.get( 'alpha', False )

    def getCBuffer( self, name ):
        return self._cb.get( name )

    def isAlphaBlended( self ):
        return self._alpha

    @staticmethod
    def dump( material ):
        cmds, cbs = [], {}
        for c in material.cmds:
            if c.type == 'cbuffer':
                try:
                    cbs[c.name] = [ float( x ) for x in c.data ]
                except Exception:
                    pass
            elif c.type in ( 'flag', 'texture' ):
                cmds.append( ( c.type, c.name, c.data if isinstance( c.data, str ) else '' ) )
        return json.dumps( dict( name=getattr( material, 'name', '' ), type=material.type, blendState=material.blendState,
                                 cmds=cmds, cbuffers=cbs, alpha=bool( material.isAlphaBlended() ) ) )

class _Cmd:
    def __init__( self, type, name, data ):
        self.type, self.name, self.data = type, name, data


def _srgb_decode( b, sock ):
    '''exact sRGB -> linear'''
    c = b.m( 'MAXIMUM', sock, 0.0 )
    lo = b.m( 'DIVIDE', c, 12.92 )
    hi = b.m( 'POWER', b.m( 'DIVIDE', b.m( 'ADD', c, 0.055 ), 1.055 ), 2.4 )
    t = b.m( 'GREATER_THAN', c, 0.04045 )
    mix = b.node( 'ShaderNodeMix', data_type='FLOAT' )
    b.feed( mix.inputs[0], t ); b.feed( mix.inputs[2], lo ); b.feed( mix.inputs[3], hi )
    return mix.outputs[0]


def build_exact_material( bpy_material, material, ia, images, context, logger=None ):
    '''Replaces the material's graph with the compiled game shader. Returns the Program or
    None when the game files aren't found or the game has no shader for this combination.'''
    scene = context.scene
    native = scene.get( 'mt_game_native_dir', '' )
    if not native or not os.path.isdir( native ):
        return None
    try:
        db = mtshaders.ShaderDB.get( native )
    except Exception as e:
        if logger: logger.warn( f'could not read the game shaders from {native}: {e}' )
        return None
    prog, ti = pick_program( db, material, ia, images, scene )
    if prog is None:
        if logger: logger.warn( f'no game shader for {material.name} ({ia})' )
        return None
    ensure_renderer_props( scene )
    b = sm3ir.build( prog.ps )

    tree = bpy_material.node_tree
    for nd in list( tree.nodes ):
        tree.nodes.remove( nd )
    out = tree.nodes.new( 'ShaderNodeOutputMaterial' )
    out.location = ( 400, 0 )
    bind = Bind( tree, material, images, prog, db, scene )
    from ..mtlib import sm3nodes
    res, kill, em = sm3nodes.emit( tree, b, bind, x0=-4000, y0=0 )
    oc = res.get( 'oC0' )
    if oc is None:
        return None

    # HDR compress: the scene target holds colour * fHDRCompressEncode, post multiplies by
    # fHDRCompressDecode. Undo it here so the material shows the decoded colour.
    hdr = bind.scene_vec4( scene_prop_name( 'CBHDRFactor__packed0', 0 ) )
    rgb = []
    for k in range( 3 ):
        c = oc[k]
        if _is_sock( c ):
            c = bind.m( 'MULTIPLY', c, hdr[1] ) if _uses_hdr( prog ) else c
            rgb.append( _srgb_decode( bind, c ) )
        else:
            rgb.append( float( c ) )
    comb = bind.node( 'ShaderNodeCombineColor' )
    for k in range( 3 ):
        bind.feed( comb.inputs[k], rgb[k] )
    emit = tree.nodes.new( 'ShaderNodeEmission' )
    emit.location = ( 0, 0 )
    tree.links.new( comb.outputs[0], emit.inputs['Color'] )

    alpha = 1.0
    if material.isAlphaBlended():
        alpha = oc[3]
    if kill is not None:
        keep = bind.m( 'LESS_THAN', kill, 0.0 ) if _is_sock( kill ) else ( 1.0 if kill < 0 else 0.0 )
        alpha = bind.m( 'MULTIPLY', keep, alpha ) if ( _is_sock( keep ) or _is_sock( alpha ) ) else keep * alpha
    if alpha == 1.0:
        tree.links.new( emit.outputs[0], out.inputs['Surface'] )
    else:
        tr = tree.nodes.new( 'ShaderNodeBsdfTransparent' )
        mx = tree.nodes.new( 'ShaderNodeMixShader' )
        mx.location = ( 200, 0 )
        a = bind.m( 'MINIMUM', bind.m( 'MAXIMUM', alpha, 0.0 ), 1.0 ) if _is_sock( alpha ) else alpha
        bind.feed( mx.inputs['Fac'], a )
        tree.links.new( tr.outputs[0], mx.inputs[1] )
        tree.links.new( emit.outputs[0], mx.inputs[2] )
        tree.links.new( mx.outputs[0], out.inputs['Surface'] )
        try:
            bpy_material.blend_method = 'BLEND' if material.isAlphaBlended() else 'CLIP'
        except Exception:
            pass
    try:
        if not isinstance( material, StoredMaterial ):
            bpy_material['mt_mrl'] = StoredMaterial.dump( material )
        bpy_material['mt_images'] = json.dumps( { k: v.name for k, v in ( images or {} ).items() if v is not None } )
    except Exception:
        pass
    bpy_material['mt_program'] = prog.record
    bpy_material['mt_ps'] = prog.ps_number
    bpy_material['mt_vs'] = prog.vs_number
    bpy_material['mt_ia'] = ia
    bpy_material['mt_key'] = '%016X' % prog.key
    bpy_material['mt_template'] = ti
    if logger:
        logger.info( f'{material.name} ({ia}): program {prog.record}, PS {prog.ps_number}, VS {prog.vs_number}, {em.created} nodes' )
    return prog


def _uses_hdr( prog ):
    return any( c['name'].startswith( 'CBHDRFactor' ) for c in ( prog.ps.ctab['consts'] if prog.ps.ctab else [] ) )


# ----------------------------------------------------------------------------------------
# lights -> renderer constants
# ----------------------------------------------------------------------------------------

def blender_to_mt( v ):
    return ( v[0], v[2], -v[1] )

def _drive( scene, prop, index, expr, variables ):
    '''variables: [(name, id_type, id, data_path)]'''
    try:
        fc = scene.driver_add( '["%s"]' % prop, index )
    except Exception:
        return
    drv = fc.driver
    drv.type = 'SCRIPTED'
    for v in list( drv.variables ):
        drv.variables.remove( v )
    for name, id_type, idb, path in variables:
        var = drv.variables.new()
        var.name = name
        var.type = 'SINGLE_PROP'
        var.targets[0].id_type = id_type
        var.targets[0].id = idb
        var.targets[0].data_path = path
    drv.expression = expr

def link_scene_drivers( scene ):
    '''Keeps the renderer constants in step with the Blender side: the key sun drives
    sLightParam0 (direction in MT axes, colour x strength), and the MT Lighting panel
    values drive the rim (CBToon / fRimLightColorFactor) and ambient (CBAmbient).'''
    ensure_renderer_props( scene )
    base = 'sub_scene_properties.mt_key_light'
    # MT (x, y, z) = blender (x, z, -y); matrix_world[2] is the sun's +Z axis (towards the light)
    for i, ( comp, sign ) in enumerate( ( ( 0, 1.0 ), ( 2, 1.0 ), ( 1, -1.0 ) ) ):
        _drive( scene, scene_prop_name( 'sLightParam0', 1 ), i, 'z * %g' % sign,
                [ ( 'z', 'SCENE', scene, '%s.matrix_world[2][%d]' % ( base, comp ) ) ] )
        _drive( scene, scene_prop_name( 'sLightParam0', 2 ), i, 'c * e',
                [ ( 'c', 'SCENE', scene, '%s.data.color[%d]' % ( base, i ) ),
                  ( 'e', 'SCENE', scene, '%s.data.energy' % base ) ] )
    for i in range( 3 ):
        if 'mt_rim_color' in scene.keys():
            _drive( scene, scene_prop_name( 'fRimLightColorFactor', 0 ), i, 'v', [ ( 'v', 'SCENE', scene, '["mt_rim_color"][%d]' % i ) ] )
        if 'mt_ambient' in scene.keys():
            _drive( scene, scene_prop_name( 'CBAmbient__packed0', 0 ), i, 'v', [ ( 'v', 'SCENE', scene, '["mt_ambient"][%d]' % i ) ] )
    for i, key in ( ( 0, 'mt_rim_min_height' ), ( 1, 'mt_rim_max_height' ), ( 2, 'mt_rim_power' ) ):
        if key in scene.keys():
            _drive( scene, scene_prop_name( 'CBToon__packed0', 0 ), i, 'v', [ ( 'v', 'SCENE', scene, '["%s"]' % key ) ] )
    link_point_light( scene )


def rebuild_all( context, logger=None ):
    """Recompiles every exact material for the scene as it is now (lights, light mask)."""
    done = 0
    for mat in bpy.data.materials:
        if 'mt_mrl' not in mat.keys() or 'mt_ia' not in mat.keys():
            continue
        try:
            material = StoredMaterial( json.loads( mat['mt_mrl'] ) )
            images = { k: bpy.data.images.get( v ) for k, v in json.loads( mat.get( 'mt_images', '{}' ) ).items() }
            if build_exact_material( mat, material, mat['mt_ia'], images, context, logger ) is not None:
                done += 1
        except Exception as e:
            if logger: logger.warn( f'could not rebuild {mat.name}: {e}' )
    link_scene_drivers( context.scene )
    refresh_outlines( context )
    return done


def link_point_light( scene ):
    """sLightParam1 (FPointLightD): [0].xyz position (MT units), [2] colour x strength,
    [3].x distance where the falloff starts, [3].y 1 / falloff length. The light's
    "mt_falloff_start" / "mt_falloff_end" custom props set the distances (blender units)."""
    mip = getattr( scene, 'sub_scene_properties', None )
    if mip is None or not hasattr( mip, 'mt_point_light' ):
        return
    base = 'sub_scene_properties.mt_point_light'
    obj = mip.mt_point_light
    if obj is not None:
        if 'mt_falloff_start' not in obj.keys():
            obj['mt_falloff_start'] = 0.0
        if 'mt_falloff_end' not in obj.keys():
            obj['mt_falloff_end'] = 300.0
    us = [ ( 's', 'SCENE', scene, '["mt_unit_scale"]' ) ] if 'mt_unit_scale' in scene.keys() else []
    sc = ' / s' if us else ''
    for i, ( comp, sign ) in enumerate( ( ( 0, 1.0 ), ( 2, 1.0 ), ( 1, -1.0 ) ) ):
        _drive( scene, scene_prop_name( 'sLightParam1', 0 ), i, '(p * %g)%s' % ( sign, sc ),
                [ ( 'p', 'SCENE', scene, '%s.matrix_world[3][%d]' % ( base, comp ) ) ] + us )
        _drive( scene, scene_prop_name( 'sLightParam1', 2 ), i, 'c * e',
                [ ( 'c', 'SCENE', scene, '%s.data.color[%d]' % ( base, i ) ),
                  ( 'e', 'SCENE', scene, '%s.data.energy' % base ) ] )
    _drive( scene, scene_prop_name( 'sLightParam1', 3 ), 0, 'a%s' % sc, [ ( 'a', 'SCENE', scene, '%s["mt_falloff_start"]' % base ) ] + us )
    _drive( scene, scene_prop_name( 'sLightParam1', 3 ), 1, '1.0 / max(b - a, 1e-4)%s' % ( ' * s' if us else '' ),
            [ ( 'a', 'SCENE', scene, '%s["mt_falloff_start"]' % base ), ( 'b', 'SCENE', scene, '%s["mt_falloff_end"]' % base ) ] + us )


# ----------------------------------------------------------------------------------------
# outline: TMaterialOutline, an inverted hull the game draws for every character mesh
# (and the IASkinBridge meshes, which exist only for it). Its VS pushes each vertex out
# along the normal by clip w * CBOutlineFilter[9].w, so the width stays the same on screen.
# ----------------------------------------------------------------------------------------

RENDERER_DEFAULTS.update( {
    'fOutlineChannelMask': [ ( 1.0, 0.0, 0.0, 0.0 ) ],
    'fOutlineColor0': [ ( 0.0, 0.0, 0.0, 1.0 ) ],
    'CBOutlineFilter__packed9': [ ( 0.0, 0.0, 0.0, 0.0012 ) ],
} )

OUTLINE_GROUP = 'MT Outline Hull'

def _gn_socket( group, name, stype, in_out ):
    if hasattr( group, 'interface' ):
        return group.interface.new_socket( name=name, in_out=in_out, socket_type=stype )
    coll = group.inputs if in_out == 'INPUT' else group.outputs
    return coll.new( stype, name )

def outline_group():
    g = bpy.data.node_groups.get( OUTLINE_GROUP )
    if g is not None:
        return g
    g = bpy.data.node_groups.new( OUTLINE_GROUP, 'GeometryNodeTree' )
    _gn_socket( g, 'Geometry', 'NodeSocketGeometry', 'INPUT' )
    _gn_socket( g, 'Material', 'NodeSocketMaterial', 'INPUT' )
    _gn_socket( g, 'Camera', 'NodeSocketObject', 'INPUT' )
    s = _gn_socket( g, 'Width', 'NodeSocketFloat', 'INPUT' ); s.default_value = 0.0012
    s = _gn_socket( g, 'Ortho Depth', 'NodeSocketFloat', 'INPUT' ); s.default_value = 0.0
    s = _gn_socket( g, 'Keep Mesh', 'NodeSocketBool', 'INPUT' ); s.default_value = True
    _gn_socket( g, 'Geometry', 'NodeSocketGeometry', 'OUTPUT' )
    N, L = g.nodes, g.links
    gi = N.new( 'NodeGroupInput' ); gi.location = ( -1200, 0 )
    go = N.new( 'NodeGroupOutput' ); go.location = ( 900, 0 )
    def node( kind, x, y, **kw ):
        n = N.new( kind ); n.location = ( x, y )
        for k, v in kw.items(): setattr( n, k, v )
        return n
    # smooth normals across uv seams: weld a copy and read its normals back by position
    merge = node( 'GeometryNodeMergeByDistance', -900, -300 )
    merge.inputs['Distance'].default_value = 1e-4
    L.new( gi.outputs['Geometry'], merge.inputs['Geometry'] )
    pos = node( 'GeometryNodeInputPosition', -900, -500 )
    near = node( 'GeometryNodeSampleNearest', -650, -400 )
    L.new( merge.outputs['Geometry'], near.inputs['Geometry'] )
    L.new( pos.outputs['Position'], near.inputs['Sample Position'] )
    nrm = node( 'GeometryNodeInputNormal', -650, -600 )
    samp = node( 'GeometryNodeSampleIndex', -400, -450, data_type='FLOAT_VECTOR', domain='POINT' )
    L.new( merge.outputs['Geometry'], samp.inputs['Geometry'] )
    L.new( nrm.outputs['Normal'], samp.inputs[3] if len( samp.inputs ) > 3 else samp.inputs['Value'] )
    L.new( near.outputs['Index'], samp.inputs['Index'] )
    # depth from the camera (clip w), or a fixed value for an orthographic camera
    cam = node( 'GeometryNodeObjectInfo', -900, 300, transform_space='RELATIVE' )
    L.new( gi.outputs['Camera'], cam.inputs['Object'] )
    fwd = node( 'ShaderNodeVectorRotate', -650, 300, rotation_type='EULER_XYZ' )
    fwd.inputs['Vector'].default_value = ( 0.0, 0.0, -1.0 )
    L.new( cam.outputs['Rotation'], fwd.inputs['Rotation'] )
    rel = node( 'ShaderNodeVectorMath', -650, 100, operation='SUBTRACT' )
    L.new( pos.outputs['Position'], rel.inputs[0] ); L.new( cam.outputs['Location'], rel.inputs[1] )
    dep = node( 'ShaderNodeVectorMath', -400, 200, operation='DOT_PRODUCT' )
    L.new( rel.outputs[0], dep.inputs[0] ); L.new( fwd.outputs[0], dep.inputs[1] )
    useo = node( 'ShaderNodeMath', -400, 0, operation='GREATER_THAN' )
    L.new( gi.outputs['Ortho Depth'], useo.inputs[0] ); useo.inputs[1].default_value = 0.0
    mixd = node( 'ShaderNodeMix', -200, 100, data_type='FLOAT' )
    L.new( useo.outputs[0], mixd.inputs[0] ); L.new( dep.outputs['Value'], mixd.inputs[2] ); L.new( gi.outputs['Ortho Depth'], mixd.inputs[3] )
    amt = node( 'ShaderNodeMath', 0, 100, operation='MULTIPLY' )
    L.new( mixd.outputs[0], amt.inputs[0] ); L.new( gi.outputs['Width'], amt.inputs[1] )
    off = node( 'ShaderNodeVectorMath', 200, -200, operation='SCALE' )
    L.new( samp.outputs[0] if samp.outputs[0].enabled else samp.outputs['Value'], off.inputs[0] )
    L.new( amt.outputs[0], off.inputs['Scale'] )
    setp = node( 'GeometryNodeSetPosition', 400, -100 )
    L.new( gi.outputs['Geometry'], setp.inputs['Geometry'] ); L.new( off.outputs[0], setp.inputs['Offset'] )
    flip = node( 'GeometryNodeFlipFaces', 550, -100 )
    L.new( setp.outputs[0], flip.inputs[0] )
    setm = node( 'GeometryNodeSetMaterial', 700, -100 )
    L.new( flip.outputs[0], setm.inputs['Geometry'] ); L.new( gi.outputs['Material'], setm.inputs['Material'] )
    join = node( 'GeometryNodeJoinGeometry', 750, 100 )
    L.new( gi.outputs['Geometry'], join.inputs[0] ); L.new( setm.outputs[0], join.inputs[0] )
    sw = node( 'GeometryNodeSwitch', 820, 0, input_type='GEOMETRY' )
    L.new( gi.outputs['Keep Mesh'], sw.inputs[0] )
    false_in = [ s for s in sw.inputs if s.name == 'False' and s.enabled ][0]
    true_in = [ s for s in sw.inputs if s.name == 'True' and s.enabled ][0]
    L.new( setm.outputs[0], false_in ); L.new( join.outputs[0], true_in )
    out = [ s for s in sw.outputs if s.enabled ][0]
    L.new( out, go.inputs['Geometry'] )
    return g


def outline_material( db, ia, context, logger=None ):
    '''Compiled TMaterialOutline pixel shader for a vertex layout (pass 1, the colour pass).'''
    name = 'MT Outline@%s' % ia
    mat = bpy.data.materials.get( name )
    if mat is not None and mat.get( 'mt_ps' ) is not None:
        return mat
    scene = context.scene
    ensure_renderer_props( scene )
    dummy = StoredMaterial( {} )
    prog = None
    templates = renderer_templates() or {}
    for t in templates.get( 'TMaterialOutline_101', [ {} ] ):
        named = dict( t )
        if ia in SKINNING:
            named['FSkinning'], named['FSkinningPF'] = SKINNING[ia]
        prog = db.program( 'TMaterialOutline', 1, ia, 1, named )
        if prog is not None:
            break
    if prog is None:
        if logger: logger.warn( f'no game outline shader for {ia}' )
        return None
    if mat is None:
        mat = bpy.data.materials.new( name )
    mat.use_nodes = True
    tree = mat.node_tree
    for nd in list( tree.nodes ):
        tree.nodes.remove( nd )
    out = tree.nodes.new( 'ShaderNodeOutputMaterial' ); out.location = ( 400, 0 )
    b = sm3ir.build( prog.ps )
    bind = Bind( tree, dummy, {}, prog, db, scene )
    from ..mtlib import sm3nodes
    res, kill, em = sm3nodes.emit( tree, b, bind, x0=-2500, y0=0 )
    oc = res['oC0']
    hdr = bind.scene_vec4( scene_prop_name( 'CBHDRFactor__packed0', 0 ) )
    comb = bind.node( 'ShaderNodeCombineColor' )
    for k in range( 3 ):
        c = oc[k]
        if _is_sock( c ):
            c = _srgb_decode( bind, bind.m( 'MULTIPLY', c, hdr[1] ) if _uses_hdr( prog ) else c )
        bind.feed( comb.inputs[k], c )
    emit = tree.nodes.new( 'ShaderNodeEmission' ); emit.location = ( 0, 0 )
    tree.links.new( comb.outputs[0], emit.inputs['Color'] )
    # the hull's faces are flipped: the side facing the camera must not cover the mesh
    geo = bind.geometry()
    front = bind.m( 'SUBTRACT', 1.0, geo.outputs['Backfacing'] )
    a = oc[3]
    a = bind.m( 'MULTIPLY', front, bind.m( 'MINIMUM', bind.m( 'MAXIMUM', a, 0.0 ), 1.0 ) ) if _is_sock( a ) else bind.m( 'MULTIPLY', front, float( a ) )
    tr = tree.nodes.new( 'ShaderNodeBsdfTransparent' )
    mx = tree.nodes.new( 'ShaderNodeMixShader' ); mx.location = ( 200, 0 )
    bind.feed( mx.inputs['Fac'], a )
    tree.links.new( tr.outputs[0], mx.inputs[1] )
    tree.links.new( emit.outputs[0], mx.inputs[2] )
    tree.links.new( mx.outputs[0], out.inputs['Surface'] )
    for attr, val in ( ( 'blend_method', 'HASHED' ), ( 'shadow_method', 'NONE' ) ):
        try:
            setattr( mat, attr, val )
        except Exception:
            pass
    mat['mt_ps'] = prog.ps_number
    mat['mt_vs'] = prog.vs_number
    mat['mt_ia'] = ia
    if logger:
        logger.info( f'outline ({ia}): PS {prog.ps_number}, VS {prog.vs_number}' )
    return mat


def add_outline( obj, ia, context, logger=None, outline_only=False ):
    scene = context.scene
    native = scene.get( 'mt_game_native_dir', '' )
    if not native:
        return False
    db = mtshaders.ShaderDB.get( native )
    mat = outline_material( db, ia, context, logger )
    if mat is None:
        return False
    mod = obj.modifiers.get( 'MT Outline' ) or obj.modifiers.new( 'MT Outline', 'NODES' )
    mod.node_group = outline_group()
    set_outline_inputs( obj, mod, mat, scene, outline_only )
    obj['mt_outline_ia'] = ia
    obj['mt_outline_only'] = bool( outline_only )
    return True

def set_outline_inputs( obj, mod, mat, scene, outline_only ):
    cam = scene.camera
    width = scene.get( scene_prop_name( 'CBOutlineFilter__packed9', 0 ), [ 0, 0, 0, 0.0012 ] )[3]
    for item in ( mod.node_group.interface.items_tree if hasattr( mod.node_group, 'interface' ) else mod.node_group.inputs ):
        ident = getattr( item, 'identifier', None )
        nm = getattr( item, 'name', '' )
        if ident is None or getattr( item, 'in_out', 'INPUT' ) != 'INPUT':
            continue
        try:
            if nm == 'Material': mod[ident] = mat
            elif nm == 'Camera' and cam is not None: mod[ident] = cam
            elif nm == 'Width': mod[ident] = float( width )
            elif nm == 'Ortho Depth':
                # no camera yet: a typical fight camera distance; orthographic: its view size
                mod[ident] = 400.0 if cam is None else ( float( cam.data.ortho_scale ) if cam.data.type == 'ORTHO' else 0.0 )
            elif nm == 'Keep Mesh': mod[ident] = not outline_only
        except Exception:
            pass
    obj.update_tag()

def refresh_outlines( context ):
    '''points every outline at the scene camera again (after adding or switching cameras)'''
    for obj in context.scene.objects:
        mod = obj.modifiers.get( 'MT Outline' ) if obj.type == 'MESH' else None
        if mod is None:
            continue
        mat = bpy.data.materials.get( 'MT Outline@%s' % obj.get( 'mt_outline_ia', '' ) )
        set_outline_inputs( obj, mod, mat, context.scene, obj.get( 'mt_outline_only', False ) )
