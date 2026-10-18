'''Writes an .mrl from the game shader materials.

The imported .mrl is the base, so everything Blender doesn't show (sampler states, blend
states, animation data, materials no mesh uses) goes back out unchanged. What the user edits
on the material level replaces the matching MRL values:

    MT Shader / MT UV group inputs   -> cbuffer members (fDiffuseColor, fShininess, ...)
    image nodes named mt_tex:<slot>  -> texture paths
'''
import os
import json
import collections

import bpy

from ..mtlib.immaterial import imMaterialLib, imMaterialTextureInfo
from . import mt_exact


def game_materials( src=None ):
    out = collections.defaultdict( list )
    for m in bpy.data.materials:
        if 'mt_mrl' not in m.keys():
            continue
        path = m.get( 'mt_mrl_path', '' )
        if src is None or os.path.normcase( os.path.abspath( path ) ) == os.path.normcase( os.path.abspath( src ) ):
            out[path].append( m )
    return out

def texture_path( img, original, native_dir ):
    '''game path (no extension, backslashes) for an image on a texture slot'''
    p = img.get( 'mt_tex_path' ) if img is not None else None
    if p:
        return p, None
    fp = bpy.path.abspath( img.filepath_raw or img.filepath ) if img is not None else ''
    if fp and native_dir:
        rel = os.path.relpath( os.path.abspath( fp ), os.path.abspath( native_dir ) )
        if not rel.startswith( '..' ):
            return os.path.splitext( rel )[0].replace( '/', '\\' ), None
    return original, f'image "{getattr( img, "name", "?" )}" is not inside the game folder, kept the old path {original}'

def _same( a, b, eps=1e-6 ):
    return len( a ) == len( b ) and all( abs( float( x ) - float( y ) ) <= eps for x, y in zip( a, b ) )

def build_library( src, logger=None ):
    '''The source .mrl with the Blender edits applied. Returns (imMaterialLib, notes).'''
    lib = imMaterialLib()
    lib.loadBinaryFile( src )
    notes = []
    native = bpy.context.scene.get( 'mt_game_native_dir', '' )
    by_name = collections.defaultdict( list )
    for path, ms in game_materials( src ).items():
        for m in ms:
            stored = json.loads( m['mt_mrl'] )
            by_name[stored.get( 'name' )].append( m )
    for mi in lib.materials:
        variants = by_name.get( mi.name )
        if not variants:
            continue
        # one MRL material can show up as several Blender materials (one per vertex layout);
        # take the one that was edited, and say so if two disagree
        edits = [ ( m, mt_exact.read_material_edits( m ) ) for m in sorted( variants, key=lambda m: m.name ) ]
        orig = { c.name: list( c.data ) for c in mi.cmds if c.type == 'cbuffer' }
        def changed( e ):
            return any( not _same( v, orig.get( k, v ) ) for k, v in e['cbuffers'].items() if k in orig )
        chosen = next( ( e for m, e in edits if changed( e ) ), edits[0][1] )
        others = [ m.name for m, e in edits if changed( e ) and e is not chosen and
                   any( not _same( e['cbuffers'][k], chosen['cbuffers'].get( k, [] ) ) for k in e['cbuffers'] if k in orig ) ]
        if others:
            notes.append( f'{mi.name}: {", ".join( others )} differ from the edited copy, used {next( m.name for m, e in edits if e is chosen )}' )
        flags = {}
        for m, e in edits:
            for t, n, v in json.loads( m['mt_mrl'] ).get( 'cmds', [] ):
                if t == 'flag':
                    orig_flag = next( ( c.data for c in mi.cmds if c.type == 'flag' and c.name == n ), v )
                    if v != orig_flag:
                        flags.setdefault( n, v )
        for c in mi.cmds:
            if c.type == 'flag' and c.name in flags:
                c.data = flags[c.name]
            elif c.type == 'cbuffer' and c.name in chosen['cbuffers']:
                vals = chosen['cbuffers'][c.name][:len( c.data )]
                if len( vals ) == len( c.data ):
                    c.data = type( c.data )( vals ) if isinstance( c.data, tuple ) else list( vals )
            elif c.type == 'texture':
                img = None
                for m, e in edits:
                    if c.name in e['textures']:
                        img = e['textures'][c.name]
                        break
                if img is not None:
                    path, note = texture_path( img, c.data, native )
                    if note:
                        notes.append( f'{mi.name} {c.name}: {note}' )
                    c.data = path
    # texture list: what the materials reference, keeping the existing entries' types
    used = []
    for mi in lib.materials:
        for c in mi.cmds:
            if c.type == 'texture' and c.data and c.data not in used:
                used.append( c.data )
    kept = { t.path: t for t in lib.textures }
    lib.textures = []
    for p in used:
        t = kept.get( p )
        if t is None:
            t = imMaterialTextureInfo(); t.path = p; t.type = 'rTexture'
        lib.textures.append( t )
    return lib, notes

def export_mrl( out_path, src=None, write_yml=True, logger=None ):
    groups = game_materials()
    if src is None:
        if not groups:
            raise RuntimeError( 'no game shader materials in this file' )
        src = max( groups, key=lambda k: len( groups[k] ) )
    if not src or not os.path.exists( src ):
        raise RuntimeError( f'the source mrl {src!r} is gone; it is the base the edits are applied to' )
    lib, notes = build_library( src, logger )
    lib.saveBinaryFile( out_path )
    if write_yml:
        lib.saveYamlFile( out_path + '.yml' )
    for n in notes:
        if logger: logger.warn( n )
    return src, notes
