"""
epic.py - expanded night police chase.

5 locations, a 20 car police fleet, helicopters, tanks, warships, better cars,
better sky. One process builds one location and renders frames from a set of
10 reusable camera rigs.

Usage:
  blender -b -noaudio --python epic.py -- MODE RES_X RES_Y SAMPLES ENGINE LOCATION CAMS
  MODE     : batch | anim | build | timeit
  LOCATION : boulevard | downtown | tunnel | alley | harbor
  CAMS     : comma list of camera:frame, e.g. "rear:18,aerial:40"
"""
import bpy, math, random, sys, os, time, tempfile
from mathutils import Vector

ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
MODE    = ARGS[0] if len(ARGS) > 0 else 'batch'
RES_X   = int(ARGS[1]) if len(ARGS) > 1 else 640
RES_Y   = int(ARGS[2]) if len(ARGS) > 2 else 360
SAMPLES = int(ARGS[3]) if len(ARGS) > 3 else 32
ENGINE  = ARGS[4] if len(ARGS) > 4 else 'CYCLES'
LOC     = ARGS[5] if len(ARGS) > 5 and ARGS[5] else 'boulevard'
CAMSPEC = ARGS[6] if len(ARGS) > 6 and ARGS[6] else 'rear:18'
FPS        = 24
FRAMES     = 96
SHOT_A_END = 52
SPEED      = 26.0
X0_GA, X0_POL = -62.0, -74.0
T       = FRAMES / FPS
X1_GA   = X0_GA + SPEED * T
X1_POL  = X0_POL + SPEED * T
OUTDIR  = os.environ.get('CHASE_OUT') or os.path.join(tempfile.gettempdir(), 'epic')
os.makedirs(OUTDIR, exist_ok=True)
random.seed(sum(map(ord, LOC)) + 7)

# ---------------------------------------------------------------- core helpers
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = scene.collection


def link(ob):
    COL.objects.link(ob)
    return ob


def set_interp(ob, mode='LINEAR', path=None, index=None):
    ad = getattr(ob, 'animation_data', None)
    if not ad or not ad.action:
        return
    for fc in ad.action.fcurves:
        if path and fc.data_path != path:
            continue
        if index is not None and fc.array_index != index:
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = mode


def mat_simple(name, base, rough=0.5, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (base[0], base[1], base[2], 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    return m


def mat_emit(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial')
    e = nt.nodes.new('ShaderNodeEmission')
    e.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)
    e.inputs['Strength'].default_value = strength
    nt.links.new(e.outputs['Emission'], o.inputs['Surface'])
    return m


def mat_bumpy(name, base, rough, scale=12.0, strength=0.15, metal=0.0):
    """rough surface with a noise bump: brick, concrete, asphalt"""
    m = mat_simple(name, base, rough, metal)
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    noise.inputs['Detail'].default_value = 6.0
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = strength
    nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    return m


def mat_brick(name, tint=(0.10, 0.045, 0.035)):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial'); o.location = (600, 0)
    b = nt.nodes.new('ShaderNodeBsdfPrincipled');  b.location = (300, 0)
    b.inputs['Roughness'].default_value = 0.85
    tc = nt.nodes.new('ShaderNodeTexCoord');       tc.location = (-900, 0)
    mp = nt.nodes.new('ShaderNodeMapping');        mp.location = (-700, 0)
    mp.inputs['Scale'].default_value = (1.0, 1.0, 0.45)
    br = nt.nodes.new('ShaderNodeTexBrick');       br.location = (-450, 0)
    br.inputs['Scale'].default_value = 1.6
    br.inputs['Mortar Size'].default_value = 0.02
    br.inputs['Color1'].default_value = (tint[0], tint[1], tint[2], 1)
    br.inputs['Color2'].default_value = (tint[0] * 1.35, tint[1] * 1.3, tint[2] * 1.3, 1)
    bmp = nt.nodes.new('ShaderNodeBump');          bmp.location = (0, -250)
    bmp.inputs['Strength'].default_value = 0.25
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    nt.links.new(mp.outputs['Vector'], br.inputs['Vector'])
    nt.links.new(br.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(br.outputs['Fac'], bmp.inputs['Height'])
    nt.links.new(bmp.outputs['Normal'], b.inputs['Normal'])
    nt.links.new(b.outputs['BSDF'], o.inputs['Surface'])
    return m


def facade_mat(name, base=(0.010, 0.010, 0.013), lit=(1.0, 0.55, 0.24),
               cell=0.36, seed=0.0, bright=1.0, lit_frac=0.22):
    """building wall: window grid, part of the windows lit from inside"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (900, 0)
    mix = nt.nodes.new('ShaderNodeMixShader');     mix.location = (700, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (450, -220)
    bsdf.inputs['Base Color'].default_value = (base[0], base[1], base[2], 1)
    bsdf.inputs['Roughness'].default_value = 0.85
    em = nt.nodes.new('ShaderNodeEmission');        em.location = (450, 180)
    em.inputs['Color'].default_value = (lit[0], lit[1], lit[2], 1.0)
    em.inputs['Strength'].default_value = 1.15 * bright
    coord = nt.nodes.new('ShaderNodeTexCoord');   coord.location = (-900, 0)
    mapn = nt.nodes.new('ShaderNodeMapping');     mapn.location = (-700, 0)
    mapn.inputs['Location'].default_value = (seed * 3.1, seed * 1.7, 0.0)
    mapn.inputs['Scale'].default_value = (1.0 / cell, 1.0 / cell, 1.0 / (cell * 1.35))
    chk = nt.nodes.new('ShaderNodeTexChecker');   chk.location = (-480, 120)
    chk.inputs['Scale'].default_value = 1.0
    noise = nt.nodes.new('ShaderNodeTexNoise');   noise.location = (-700, -320)
    noise.inputs['Scale'].default_value = 1.2
    noise.inputs['Detail'].default_value = 2.0
    ra = nt.nodes.new('ShaderNodeValToRGB');      ra.location = (-480, -320)
    ra.color_ramp.interpolation = 'CONSTANT'
    ra.color_ramp.elements[0].position = 0.0
    ra.color_ramp.elements[0].color = (0, 0, 0, 1)
    ra.color_ramp.elements[1].position = lit_frac
    ra.color_ramp.elements[1].color = (1, 1, 1, 1)
    mul = nt.nodes.new('ShaderNodeMath');         mul.location = (-200, 0)
    mul.operation = 'MULTIPLY'
    nt.links.new(coord.outputs['Object'], mapn.inputs['Vector'])
    nt.links.new(mapn.outputs['Vector'], chk.inputs['Vector'])
    nt.links.new(mapn.outputs['Vector'], noise.inputs['Vector'])
    nt.links.new(noise.outputs['Fac'], ra.inputs['Fac'])
    nt.links.new(chk.outputs['Fac'], mul.inputs[0])
    nt.links.new(ra.outputs['Color'], mul.inputs[1])
    nt.links.new(mul.outputs[0], mix.inputs['Fac'])
    nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1])
    nt.links.new(em.outputs['Emission'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return m


BOX_V = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
         (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
BOX_F = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2),
         (2, 6, 7, 3), (3, 7, 4, 0)]


def add_box(name, loc, size, mat, rot=(0, 0, 0), parent=None, bevel=0.0):
    sx, sy, sz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    verts = [(v[0] * sx, v[1] * sy, v[2] * sz) for v in BOX_V]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], BOX_F)
    me.update()
    ob = bpy.data.objects.new(name, me)
    link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    if mat:
        ob.data.materials.append(mat)
    if bevel > 0:
        bv = ob.modifiers.new('bev', 'BEVEL')
        bv.width = bevel
        bv.segments = 2
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob


def add_cyl(name, loc, r, depth, mat, rot=(0, 0, 0), seg=24, parent=None,
            smooth=True):
    """cylinder built along +Z, then rotated"""
    verts, faces = [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        x, y = math.cos(a) * r, math.sin(a) * r
        verts.append((x, y, -depth / 2))
        verts.append((x, y, depth / 2))
    for i in range(seg):
        a0, a1 = 2 * i, 2 * ((i + 1) % seg)
        faces.append((a0, a0 + 1, a1 + 1, a1))
    faces.append(tuple(range(0, 2 * seg, 2)))
    faces.append(tuple(range(2 * seg - 1, 0, -2)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    link(ob)
    ob.location = loc
    ob.rotation_euler = rot
    if mat:
        ob.data.materials.append(mat)
    if smooth:
        for p in me.polygons:
            if len(p.vertices) == 4:
                p.use_smooth = True
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob


def add_sphere(name, loc, r, mat, seg=24, ring=12, parent=None):
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=ring, radius=r)
    except TypeError:
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=ring, diameter=r)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    link(ob)
    ob.location = loc
    if mat:
        ob.data.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob


def add_empty(name, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 1.0
    link(e)
    e.location = loc
    return e


def drive_x(ob, x0, x1, fr=FRAMES):
    ob.location.x = x0
    ob.keyframe_insert('location', index=0, frame=1)
    ob.location.x = x1
    ob.keyframe_insert('location', index=0, frame=fr)
    set_interp(ob, 'LINEAR', 'location', 0)


def drv(ob, path, index, expr):
    d = ob.driver_add(path, index)
    d.driver.type = 'SCRIPTED'
    d.driver.expression = expr
    return d


# ---------------------------------------------------------------- materials
M = {}
M['road']     = mat_bumpy('road', (0.016, 0.016, 0.019), 0.20, 60, 0.06)
M['pier']     = mat_bumpy('pier', (0.075, 0.075, 0.078), 0.55, 25, 0.12)
M['concrete'] = mat_bumpy('concrete', (0.085, 0.085, 0.09), 0.7, 18, 0.1)
M['brick']    = mat_brick('brick')
M['sidewalk'] = mat_bumpy('sidewalk', (0.10, 0.10, 0.105), 0.6, 40, 0.05)
M['curb']     = mat_simple('curb', (0.13, 0.13, 0.135), 0.55)
M['paint']    = mat_simple('paint', (0.40, 0.39, 0.36), 0.35)
M['glass']    = mat_simple('glass', (0.012, 0.014, 0.022), 0.06, 0.1)
M['tire']     = mat_simple('tire', (0.014, 0.014, 0.016), 0.88)
M['chrome']   = mat_simple('chrome', (0.55, 0.56, 0.58), 0.22, 0.95)
M['steel']    = mat_simple('steel', (0.22, 0.23, 0.25), 0.40, 0.85)
M['darkmetal'] = mat_simple('darkmetal', (0.045, 0.045, 0.05), 0.45, 0.7)
M['police']   = mat_simple('police_body', (0.80, 0.81, 0.83), 0.24, 0.55)
M['police_blue'] = mat_simple('police_blue', (0.02, 0.05, 0.32), 0.30, 0.3)
M['getaway']  = mat_simple('getaway_body', (0.52, 0.045, 0.03), 0.22, 0.6)
M['tank']     = mat_bumpy('tank', (0.085, 0.105, 0.065), 0.75, 30, 0.12)
M['track']    = mat_simple('track', (0.03, 0.03, 0.032), 0.9)
M['ship']     = mat_bumpy('ship', (0.155, 0.165, 0.175), 0.55, 20, 0.08)
M['shipdeck'] = mat_simple('shipdeck', (0.09, 0.095, 0.10), 0.6)
M['water']    = None
M['container'] = [mat_simple('cont%d' % i, c, 0.55, 0.25) for i, c in enumerate([
    (0.42, 0.10, 0.07), (0.06, 0.20, 0.36), (0.30, 0.28, 0.05),
    (0.05, 0.26, 0.16), (0.28, 0.09, 0.28), (0.38, 0.30, 0.06)])]
TRAFFIC_COLS = [(0.05, 0.055, 0.11), (0.16, 0.14, 0.04), (0.03, 0.10, 0.12),
                (0.14, 0.14, 0.15), (0.20, 0.06, 0.06)]

M['head']   = mat_emit('head', (1.0, 0.94, 0.82), 14.0)
M['tail']   = mat_emit('tail', (1.0, 0.05, 0.02), 7.0)
M['reverse'] = mat_emit('reverse', (1.0, 0.95, 0.85), 6.0)
M['lamp_sodium'] = mat_emit('lamp_sodium', (1.0, 0.70, 0.38), 7.0)
M['lamp_led']    = mat_emit('lamp_led', (0.72, 0.82, 1.0), 7.0)
M['strip']  = mat_emit('strip', (0.85, 0.90, 1.0), 9.0)
M['search'] = mat_emit('search', (1.0, 0.97, 0.90), 22.0)
M['moon']   = mat_emit('moon', (0.92, 0.94, 1.0), 3.0)
M['moonglow'] = mat_emit('moonglow', (0.55, 0.65, 0.95), 0.12)
M['tanklight'] = mat_emit('tanklight', (1.0, 0.93, 0.72), 10.0)
M['shipred'] = mat_emit('shipred', (1.0, 0.05, 0.03), 6.0)
M['shipgreen'] = mat_emit('shipgreen', (0.05, 1.0, 0.25), 6.0)
M['shipwhite'] = mat_emit('shipwhite', (1.0, 0.95, 0.85), 6.0)
M['flare']  = mat_emit('flare', (1.0, 0.35, 0.05), 9.0)
NEON = [(1.0, 0.05, 0.35), (0.05, 0.9, 1.0), (1.0, 0.8, 0.05),
        (0.25, 1.0, 0.35), (0.8, 0.2, 1.0), (1.0, 0.35, 0.05)]
M['neon'] = [mat_emit('neon%d' % i, c, 6.0) for i, c in enumerate(NEON)]
STROBE_RED  = [mat_emit('strobe_r%d' % i, (1.0, 0.02, 0.02), 24.0) for i in range(3)]
STROBE_BLUE = [mat_emit('strobe_b%d' % i, (0.05, 0.15, 1.0), 24.0) for i in range(3)]

# ---------------------------------------------------------------- sky
def build_sky(outdoor=True, warm=(0.10, 0.055, 0.03), cool=(0.004, 0.005, 0.011),
              stars=True, clouds=True, moon=True, strength=0.75):
    w = bpy.data.worlds.new('W')
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld'); out.location = (900, 0)
    bg = nt.nodes.new('ShaderNodeBackground');   bg.location = (700, 0)
    add = nt.nodes.new('ShaderNodeAddShader');   add.location = (500, 0)
    # sky gradient
    gb = nt.nodes.new('ShaderNodeBackground');   gb.location = (250, 200)
    tc = nt.nodes.new('ShaderNodeTexCoord');     tc.location = (-900, 200)
    sep = nt.nodes.new('ShaderNodeSeparateXYZ'); sep.location = (-700, 200)
    mr = nt.nodes.new('ShaderNodeMapRange');     mr.location = (-500, 200)
    ramp = nt.nodes.new('ShaderNodeValToRGB');   ramp.location = (-300, 200)
    ramp.color_ramp.elements[0].color = (cool[0], cool[1], cool[2], 1)
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = (warm[0], warm[1], warm[2], 1)
    mr.inputs['From Min'].default_value = -0.05
    mr.inputs['From Max'].default_value = 0.35
    mr.inputs['To Min'].default_value = 1.0
    mr.inputs['To Max'].default_value = 0.0
    nt.links.new(tc.outputs['Generated'], sep.inputs['Vector'])
    nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], gb.inputs['Color'])
    nt.links.new(gb.outputs['Background'], add.inputs[0])
    top = add
    if stars:
        nb = nt.nodes.new('ShaderNodeBackground'); nb.location = (250, 0)
        sn = nt.nodes.new('ShaderNodeTexNoise');    sn.location = (-500, -60)
        sn.inputs['Scale'].default_value = 320.0
        sn.inputs['Detail'].default_value = 1.0
        sr = nt.nodes.new('ShaderNodeValToRGB');    sr.location = (-300, -60)
        sr.color_ramp.interpolation = 'CONSTANT'
        sr.color_ramp.elements[0].color = (0, 0, 0, 1)
        sr.color_ramp.elements[1].position = 0.78
        sr.color_ramp.elements[1].color = (0.9, 0.93, 1.0, 1)
        mask = nt.nodes.new('ShaderNodeMath');      mask.location = (-100, -120)
        mask.operation = 'GREATER_THAN'
        mask.inputs[1].default_value = 0.05
        mul = nt.nodes.new('ShaderNodeMath');       mul.location = (100, -60)
        mul.operation = 'MULTIPLY'
        nt.links.new(tc.outputs['Generated'], sn.inputs['Vector'])
        nt.links.new(sn.outputs['Fac'], sr.inputs['Fac'])
        nt.links.new(sep.outputs['Z'], mask.inputs[0])
        nt.links.new(sr.outputs['Color'], mul.inputs[0])
        nt.links.new(mask.outputs[0], mul.inputs[1])
        nt.links.new(mul.outputs[0], nb.inputs['Color'])
        nb.inputs['Strength'].default_value = 1.4
        a2 = nt.nodes.new('ShaderNodeAddShader'); a2.location = (400, 100)
        nt.links.new(top.outputs['Shader'] if hasattr(top, 'outputs') else gb.outputs['Background'], a2.inputs[0])
        nt.links.new(nb.outputs['Background'], a2.inputs[1])
        top = a2
    if clouds:
        cb = nt.nodes.new('ShaderNodeBackground'); cb.location = (250, -260)
        cn = nt.nodes.new('ShaderNodeTexNoise');    cn.location = (-500, -320)
        cn.inputs['Scale'].default_value = 3.5
        cn.inputs['Detail'].default_value = 8.0
        cn.inputs['Roughness'].default_value = 0.62
        cr = nt.nodes.new('ShaderNodeValToRGB');    cr.location = (-300, -320)
        cr.color_ramp.elements[0].color = (0, 0, 0, 1)
        cr.color_ramp.elements[1].position = 0.62
        cr.color_ramp.elements[1].color = (0.16, 0.17, 0.21, 1)
        cmask = nt.nodes.new('ShaderNodeMath');     cmask.location = (-100, -380)
        cmask.operation = 'LESS_THAN'
        cmask.inputs[1].default_value = 0.45
        cm = nt.nodes.new('ShaderNodeMath');        cm.location = (100, -320)
        cm.operation = 'MULTIPLY'
        nt.links.new(tc.outputs['Generated'], cn.inputs['Vector'])
        nt.links.new(cn.outputs['Fac'], cr.inputs['Fac'])
        nt.links.new(sep.outputs['Z'], cmask.inputs[0])
        nt.links.new(cr.outputs['Color'], cm.inputs[0])
        nt.links.new(cmask.outputs[0], cm.inputs[1])
        nt.links.new(cm.outputs[0], cb.inputs['Color'])
        cb.inputs['Strength'].default_value = 0.55
        a3 = nt.nodes.new('ShaderNodeAddShader'); a3.location = (500, -120)
        if is_add(top):
            nt.links.new(top.outputs['Shader'], a3.inputs[0])
        else:
            nt.links.new(gb.outputs['Background'], a3.inputs[0])
        nt.links.new(cb.outputs['Background'], a3.inputs[1])
        top = a3
    if is_add(top):
        nt.links.new(top.outputs['Shader'], out.inputs['Surface'])
    else:
        nt.links.new(gb.outputs['Background'], out.inputs['Surface'])
    gb.inputs['Strength'].default_value = strength
    if outdoor and moon:
        add_sphere('moon_disc', (-260, 190, 300), 20.0, M['moon'], seg=32, ring=16)
        add_sphere('moon_glow', (-260, 190, 300), 62.0, M['moonglow'], seg=24, ring=12)
        s = bpy.data.lights.new('moonlight', 'SUN')
        s.energy = 0.45
        s.angle = math.radians(3.0)
        s.color = (0.72, 0.80, 1.0)
        so = link(bpy.data.objects.new('moonlight', s))
        so.location = (-260, 190, 300)
        mt = add_empty('moon_target', (0, 0, 0))
        mc = so.constraints.new('TRACK_TO')
        mc.target = mt
        mc.track_axis = 'TRACK_NEGATIVE_Z'
        mc.up_axis = 'UP_Y'
    return w


def is_add(node):
    return hasattr(node, 'node_tree') and node.bl_idname == 'ShaderNodeAddShader'


# ---------------------------------------------------------------- car factory
def make_car(name, color, kind='sedan', length=4.6, parent=None, detail=True,
             strobe=None, spin=True, headlights=True):
    """kind: sedan | police | muscle | suv"""
    root = add_empty(name + '_root')
    body = mat_simple(name + '_paint', color, rough=0.20, metal=0.62)
    L = length
    bevel = 0.06 if detail else 0.03
    # main masses
    add_box(name + '_body', (0, 0, 0.62), (L, 1.94, 0.50), body, parent=root, bevel=bevel)
    add_box(name + '_shoulder', (0, 0, 0.94), (L * 0.985, 1.86, 0.20), body,
            parent=root, bevel=bevel)
    add_box(name + '_skirt', (0, 0, 0.40), (L * 0.97, 1.80, 0.26), M['darkmetal'],
            parent=root, bevel=0.04)
    add_box(name + '_hood', (L * 0.30, 0, 1.08), (L * 0.36, 1.74, 0.12), body,
            parent=root, bevel=0.04)
    add_box(name + '_trunk', (-L * 0.32, 0, 1.09), (L * 0.30, 1.72, 0.12), body,
            parent=root, bevel=0.04)
    add_box(name + '_bumpf', (L * 0.50, 0, 0.60), (0.22, 1.92, 0.46), M['darkmetal'],
            parent=root, bevel=0.05)
    add_box(name + '_bumpr', (-L * 0.50, 0, 0.60), (0.22, 1.92, 0.46), M['darkmetal'],
            parent=root, bevel=0.05)
    # cabin: roof, glass, pillars
    add_box(name + '_roof', (-0.25, 0, 1.48), (1.95, 1.70, 0.10), body, parent=root,
            bevel=0.05)
    add_box(name + '_wind', (0.82, 0, 1.24), (0.10, 1.70, 0.78), M['glass'],
            rot=(0, math.radians(30), 0), parent=root)
    add_box(name + '_rearwin', (-1.18, 0, 1.26), (0.10, 1.70, 0.72), M['glass'],
            rot=(0, math.radians(-32), 0), parent=root)
    for sy in (1, -1):
        add_box(name + '_side%d' % sy, (-0.22, sy * 0.87, 1.30),
                (1.55, 0.06, 0.42), M['glass'], parent=root)
        if detail:
            add_box(name + '_mirror%d' % sy, (0.72, sy * 1.02, 1.18),
                    (0.16, 0.20, 0.10), M['darkmetal'], parent=root, bevel=0.02)
    # wheels
    wheels = []
    wr = 0.35 if kind != 'suv' else 0.42
    for wx in (L * 0.30, -L * 0.30):
        for wy in (0.90, -0.90):
            wl = add_cyl(name + '_wheel', (wx, wy, wr), wr, 0.26, M['tire'],
                         rot=(math.pi / 2, 0, 0), seg=20, parent=root)
            add_cyl(name + '_rim', (wx, wy + (0.135 if wy > 0 else -0.135), wr),
                    wr * 0.58, 0.05, M['chrome'], rot=(math.pi / 2, 0, 0), seg=16,
                    parent=root)
            if detail:
                for k in range(5):
                    a = math.radians(72 * k)
                    add_box(name + '_spoke', (wx + math.cos(a) * wr * 0.28,
                                              wy + (0.145 if wy > 0 else -0.145),
                                              wr + math.sin(a) * wr * 0.28),
                            (wr * 0.5, 0.03, 0.05), M['chrome'],
                            rot=(0, -a, 0), parent=root)
            wheels.append(wl)
    # lights
    for wy in (0.62, -0.62):
        add_box(name + '_hl', (L * 0.50 - 0.02, wy, 0.86), (0.14, 0.46, 0.20),
                M['head'], parent=root)
        add_box(name + '_tl', (-L * 0.50 + 0.02, wy, 0.90), (0.12, 0.52, 0.18),
                M['tail'], parent=root)
    if kind == 'police':
        for sy in (1, -1):
            add_box(name + '_strip%d' % sy, (0, sy * 0.98, 0.74),
                    (L * 0.60, 0.03, 0.36), M['police_blue'], parent=root)
            add_box(name + '_door%d' % sy, (-0.6, sy * 0.99, 1.05),
                    (1.1, 0.03, 0.34), M['police_blue'], parent=root)
        add_box(name + '_bar', (-0.30, 0, 1.56), (0.80, 1.62, 0.09), M['darkmetal'],
                parent=root)
        sr = [0, 0]
        sb = [0, 0]
        if strobe is not None:
            sr[0] = STROBE_RED[strobe % 3]
            sb[0] = STROBE_BLUE[strobe % 3]
        else:
            sr[0] = STROBE_RED[0]
            sb[0] = STROBE_BLUE[1]
        add_box(name + '_barR', (-0.30, 0.52, 1.70), (0.62, 0.50, 0.20), sr[0],
                parent=root)
        add_box(name + '_barB', (-0.30, -0.52, 1.70), (0.62, 0.50, 0.20), sb[0],
                parent=root)
        add_box(name + '_barW', (-0.30, 0.0, 1.70), (0.50, 0.40, 0.16),
                M['shipwhite'], parent=root)
        add_box(name + '_push', (L * 0.50 + 0.12, 0, 0.58), (0.18, 1.72, 0.40),
                M['steel'], parent=root, bevel=0.03)
        add_box(name + '_spotL', (0.55, 0.98, 1.32), (0.20, 0.20, 0.16), M['search'],
                parent=root)
        add_box(name + '_spotR', (0.55, -0.98, 1.32), (0.20, 0.20, 0.16), M['search'],
                parent=root)
        if detail:
            add_box(name + '_antenna', (-1.55, 0.45, 2.05), (0.03, 0.03, 1.1),
                    M['darkmetal'], parent=root)
            add_box(name + '_number', (-0.2, 0.0, 1.42), (0.5, 0.45, 0.06),
                    M['reverse'], parent=root)
    return root, wheels


def add_heli(name, loc, scale=1.0):
    root = add_empty(name)
    root.location = loc
    body = M['steel']
    s = scale
    add_box(name + '_body', (0, 0, 0), (3.6 * s, 1.6 * s, 1.3 * s), body,
            parent=root, bevel=0.18)
    add_box(name + '_nose', (2.0 * s, 0, 0.05 * s), (1.1 * s, 1.2 * s, 0.95 * s),
            M['glass'], parent=root, bevel=0.12)
    add_box(name + '_tail', (-4.4 * s, 0, 0.34 * s), (5.6 * s, 0.44 * s, 0.44 * s),
            body, parent=root, bevel=0.06)
    add_box(name + '_fin', (-6.7 * s, 0, 1.10 * s), (0.9 * s, 0.16 * s, 1.3 * s),
            body, parent=root)
    for sy in (1, -1):
        add_box(name + '_skid%d' % sy, (0, sy * 0.72 * s, -1.0 * s),
                (2.7 * s, 0.14 * s, 0.14 * s), M['darkmetal'], parent=root)
    rotors = []
    r1 = add_box(name + '_rot1', (0.2 * s, 0, 0.88 * s), (12.5 * s, 0.28 * s, 0.08 * s),
                 M['darkmetal'], parent=root)
    r2 = add_box(name + '_rot2', (0.2 * s, 0, 0.90 * s), (0.28 * s, 12.5 * s, 0.08 * s),
                 M['darkmetal'], parent=root)
    rotors += [r1, r2]
    add_box(name + '_trot', (-6.9 * s, 0.36 * s, 1.05 * s),
            (0.10 * s, 2.6 * s, 2.6 * s), M['darkmetal'],
            rot=(0, math.radians(90), 0), parent=root)
    add_box(name + '_search', (0.7 * s, -0.6 * s, -0.66 * s),
            (0.55 * s, 0.55 * s, 0.5 * s), M['search'], parent=root)
    lamp = bpy.data.lights.new(name + '_spot', 'SPOT')
    lamp.energy = 20000.0 * s
    lamp.spot_size = 0.30
    lamp.spot_blend = 0.15
    lamp.color = (1.0, 0.97, 0.90)
    lo = link(bpy.data.objects.new(name + '_spot', lamp))
    lo.location = (0.7 * s, -0.6 * s, -0.6 * s)
    lo.parent = root
    lo.matrix_parent_inverse = root.matrix_world.inverted()
    return root, rotors, lo


def add_tank(name, loc, rotz=0.0):
    root = add_empty(name)
    root.location = loc
    root.rotation_euler = (0, 0, rotz)
    add_box(name + '_hull', (0, 0, 1.00), (7.0, 3.1, 1.0), M['tank'], parent=root,
            bevel=0.08)
    add_box(name + '_glacis', (3.4, 0, 0.95), (1.2, 3.0, 0.9), M['tank'],
            rot=(0, math.radians(-28), 0), parent=root, bevel=0.05)
    for sy in (1, -1):
        add_box(name + '_track%d' % sy, (0, sy * 1.42, 0.42), (7.3, 0.72, 0.84),
                M['track'], parent=root, bevel=0.06)
        add_box(name + '_fend%d' % sy, (0, sy * 1.72, 1.05), (7.1, 0.22, 0.10),
                M['tank'], parent=root)
    add_box(name + '_turret', (-0.3, 0, 1.85), (3.2, 2.5, 0.80), M['tank'],
            parent=root, bevel=0.10)
    add_box(name + '_mantlet', (1.3, 0, 1.85), (0.5, 1.2, 0.7), M['tank'],
            parent=root)
    add_cyl(name + '_barrel', (3.6, 0, 1.88), 0.12, 4.6, M['darkmetal'],
            rot=(0, math.radians(90), 0), seg=16, parent=root)
    add_box(name + '_hatch', (-1.0, 0.45, 2.30), (0.8, 0.8, 0.14), M['darkmetal'],
            parent=root, bevel=0.03)
    add_box(name + '_cupola', (-1.0, -0.6, 2.28), (0.9, 0.9, 0.5), M['tank'],
            parent=root, bevel=0.05)
    add_cyl(name + '_mg', (-1.0, -0.6, 2.45), 0.06, 1.4, M['darkmetal'],
            rot=(0, math.radians(90), 0), seg=10, parent=root)
    for sx in (1, -1):
        for sy in (1, -1):
            add_box(name + '_smoke', (1.0 * sx + 0.4, 1.05 * sy + 0.2, 2.35),
                    (0.5, 0.24, 0.16), M['darkmetal'], parent=root)
    for sy in (1, -1):
        add_box(name + '_hl%d' % sy, (3.75, sy * 1.0, 1.15), (0.10, 0.34, 0.20),
                M['tanklight'], parent=root)
    lamp = bpy.data.lights.new(name + '_spot', 'SPOT')
    lamp.energy = 5000.0
    lamp.spot_size = 0.55
    lamp.spot_blend = 0.4
    lamp.color = (1.0, 0.95, 0.82)
    lo = link(bpy.data.objects.new(name + '_spot', lamp))
    lo.location = (2.0, 0, 2.5)
    lo.rotation_euler = (0, -0.06, 0)
    lo.parent = root
    lo.matrix_parent_inverse = root.matrix_world.inverted()
    return root


def add_ship(name, loc, rotz=0.0, scale=1.0):
    root = add_empty(name)
    root.location = loc
    root.rotation_euler = (0, 0, rotz)
    s = scale
    add_box(name + '_hull', (0, 0, 1.2 * s), (112 * s, 15 * s, 7.4 * s), M['ship'],
            parent=root, bevel=0.4)
    add_box(name + '_bow', (56 * s, 0, 1.0 * s), (10 * s, 12 * s, 6.0 * s),
            M['ship'], parent=root, bevel=0.3)
    add_box(name + '_deck', (0, 0, 5.1 * s), (104 * s, 13.6 * s, 0.6 * s),
            M['shipdeck'], parent=root)
    add_box(name + '_super', (-6 * s, 0, 10.5 * s), (26 * s, 12 * s, 10.0 * s),
            M['ship'], parent=root, bevel=0.2)
    add_box(name + '_bridge', (-8 * s, 0, 17.0 * s), (13 * s, 10 * s, 4.0 * s),
            M['ship'], parent=root, bevel=0.15)
    add_box(name + '_funnel', (4 * s, 0, 16.0 * s), (6 * s, 4.4 * s, 5.6 * s),
            M['ship'], parent=root, bevel=0.15)
    add_box(name + '_mast', (-12 * s, 0, 24.0 * s), (1.0 * s, 1.0 * s, 10 * s),
            M['darkmetal'], parent=root)
    add_box(name + '_yard', (-12 * s, 0, 27.0 * s), (0.6 * s, 9 * s, 0.5 * s),
            M['darkmetal'], parent=root)
    add_cyl(name + '_radar', (1 * s, 0, 20.0 * s), 1.6 * s, 0.25 * s, M['shipdeck'],
            rot=(math.radians(20), 0, 0), seg=18, parent=root)
    add_box(name + '_gun', (30 * s, 0, 7.4 * s), (8 * s, 7 * s, 3.2 * s), M['ship'],
            parent=root, bevel=0.15)
    add_cyl(name + '_gunbar', (36 * s, 0, 8.2 * s), 0.28 * s, 7 * s, M['darkmetal'],
            rot=(0, math.radians(90), 0), seg=14, parent=root)
    add_box(name + '_ciws', (12 * s, 0, 7.6 * s), (3.0 * s, 3.0 * s, 2.4 * s),
            M['shipdeck'], parent=root, bevel=0.2)
    add_box(name + '_ciwsbar', (12 * s, 0, 9.0 * s), (0.4 * s, 0.4 * s, 2.6 * s),
            M['darkmetal'], parent=root)
    for k in range(3):
        x = (14 + k * 6) * s
        add_box(name + '_life%d' % k, (x, 5.6 * s, 7.0 * s), (3.2 * s, 1.6 * s, 2.2 * s),
                M['shipwhite'], parent=root, bevel=0.1)
    for i in range(9):
        x = (-50 + i * 13) * s
        add_box(name + '_rlight', (x, -7.8 * s, 4.6 * s), (1.2 * s, 0.3 * s, 0.5 * s),
                M['shipred'] if i % 2 else M['shipwhite'], parent=root)
        add_box(name + '_glight', (x, 7.8 * s, 4.6 * s), (1.2 * s, 0.3 * s, 0.5 * s),
                M['shipgreen'] if i % 2 else M['shipwhite'], parent=root)
    lamp = bpy.data.lights.new(name + '_search', 'SPOT')
    lamp.energy = 9000.0
    lamp.spot_size = 0.25
    lamp.spot_blend = 0.25
    lamp.color = (1.0, 0.96, 0.88)
    lo = link(bpy.data.objects.new(name + '_search', lamp))
    lo.location = (-6 * s, -5 * s, 18 * s)
    lo.rotation_euler = (math.radians(65), 0, math.radians(-35))
    lo.parent = root
    lo.matrix_parent_inverse = root.matrix_world.inverted()
    return root


def streetlight(x, y, kind='sodium', h=7.2, with_light=False):
    col = M['lamp_sodium'] if kind == 'sodium' else M['lamp_led']
    add_box('sl_pole', (x, y, h / 2), (0.22, 0.22, h), M['steel'], bevel=0.03)
    add_box('sl_arm', (x, y - math.copysign(1.3, y), h - 0.1), (0.16, 2.6, 0.16),
            M['steel'])
    add_box('sl_head', (x, y - math.copysign(2.4, y), h - 0.25), (1.0, 0.62, 0.22), col)
    if with_light:
        L = bpy.data.lights.new('sll', 'POINT')
        L.energy = 1400.0
        L.color = (1.0, 0.72, 0.42) if kind == 'sodium' else (0.78, 0.86, 1.0)
        L.shadow_soft_size = 0.35
        ob = link(bpy.data.objects.new('sll', L))
        ob.location = (x, y - math.copysign(2.4, y), h - 0.5)


# ---------------------------------------------------------------- locations
def ground_slab(y0, y1, mat, x0=-260, x1=160, z=0.0, name='ground'):
    add_box(name, ((x0 + x1) / 2, (y0 + y1) / 2, z - 0.06),
            (x1 - x0, y1 - y0, 0.12), mat)


def lane_marks(x0=-250, x1=150, center_y=0.0, lanes=2, paint=None):
    paint = paint or M['paint']
    for x in range(int(x0), int(x1), 8):
        add_box('dash', (x, center_y, 0.02), (3.8, 0.14, 0.02), paint)
    for k in range(1, lanes):
        for sy in (1, -1):
            yy = center_y + sy * (3.4 * k)
            for x in range(int(x0), int(x1), 4):
                add_box('lane', (x, yy, 0.02), (1.7, 0.10, 0.02), paint)


def bld_row(side, y_inner=13.0, x0=-250, x1=140, hmin=8, hmax=30, cell=(0.30, 0.45),
            lit=(1.0, 0.55, 0.24), bright=(0.50, 1.00), shop=True, depth=(9, 14)):
    x = float(x0)
    i = 0
    while x < x1:
        wdt = random.uniform(9, 16)
        dep = random.uniform(depth[0], depth[1])
        hgt = random.uniform(hmin, hmax) * (1.0 + max(0.0, x / 500.0))
        yc = side * (y_inner + dep / 2 + random.uniform(0, 3))
        m = facade_mat('fac%d_%d' % (side, i), seed=random.uniform(0, 10),
                       cell=random.uniform(cell[0], cell[1]), lit=lit,
                       bright=random.uniform(bright[0], bright[1]))
        add_box('bld%d_%d' % (side, i), (x + wdt / 2, yc, hgt / 2), (wdt, dep, hgt),
                m, bevel=0.05)
        add_box('roof%d_%d' % (side, i), (x + wdt / 2, yc, hgt + 0.5),
                (wdt * 0.55, dep * 0.5, 1.0), M['darkmetal'])
        if random.random() < 0.3:
            add_box('ant%d_%d' % (side, i), (x + wdt / 2, yc, hgt + 3.0),
                    (0.2, 0.2, 5.0), M['steel'])
        if shop:
            innery = yc - side * dep / 2.0
            sm = facade_mat('shopm%d_%d' % (side, i), seed=random.uniform(0, 10),
                            cell=0.5, bright=random.uniform(0.8, 1.2), lit_frac=0.55)
            add_box('shop%d_%d' % (side, i), (x + wdt / 2, innery - side * 0.12, 0.85),
                    (wdt * 0.94, 0.14, 1.5), sm)
        x += wdt + random.uniform(3.5, 8.0)
        i += 1


def loc_boulevard():
    ground_slab(-60, 60, M['sidewalk'], z=0.0, name='far_ground')
    add_box('road', (0, 0, -0.01), (420, 13.0, 0.04), M['road'])
    for sy in (1, -1):
        add_box('sidewalk_%d' % sy, (0, sy * 8.0, 0.06), (420, 3.0, 0.24), M['curb'],
                bevel=0.06)
        add_box('curb_%d' % sy, (0, sy * 6.5, 0.03), (420, 0.35, 0.30), M['curb'])
        add_box('lot_%d' % sy, (0, sy * 15.5, 0.015), (420, 13.0, 0.05), M['sidewalk'])
    lane_marks()
    bld_row(1)
    bld_row(-1)
    for side in (1, -1):
        for x in range(-120, 90, 28):
            streetlight(x, side * 7.4, 'sodium', with_light=((x // 28) % 2 == 0))
    # overpass ahead
    add_box('ovr_deck', (70, 0, 9.5), (26, 44, 1.6), M['concrete'], bevel=0.1)
    for sy in (1, -1):
        add_box('ovr_pier', (70, sy * 11, 4.5), (3.0, 3.0, 9.0), M['concrete'])
    for x in (62, 70, 78):
        add_box('ovr_light', (x, 0, 8.4), (2.0, 0.5, 0.2), M['lamp_sodium'])


def loc_downtown():
    ground_slab(-80, 80, M['sidewalk'], z=0.0, name='far_ground')
    add_box('road', (0, 0, -0.01), (440, 15.0, 0.04), M['road'])
    add_box('xroad', (0, 0, -0.005), (15.0, 440, 0.04), M['road'])
    lane_marks(lanes=2)
    for y in range(-200, 160, 9):
        add_box('xdash', (0, y, 0.02), (0.14, 3.6, 0.02), M['paint'])
    for sx in (1, -1):
        for sy in (1, -1):
            add_box('cnr_%d_%d' % (sx, sy), (sx * 12, sy * 12, 0.13),
                    (12, 12, 0.26), M['sidewalk'])
            add_box('cnr_curb_%d_%d' % (sx, sy), (sx * 8.6, sy * 8.6, 0.14),
                    (6, 6, 0.30), M['curb'])
    bld_row(1, y_inner=18, hmin=22, hmax=70, lit=(1.0, 0.6, 0.30), shop=True,
            depth=(12, 20))
    bld_row(-1, y_inner=18, hmin=22, hmax=70, lit=(1.0, 0.6, 0.30), shop=True,
            depth=(12, 20))
    for side in (1, -1):
        for x in range(-120, 90, 26):
            streetlight(x, side * 8.5, 'led', h=8.4, with_light=((x // 26) % 2 == 0))
    # traffic signals at the intersection
    for sx in (1, -1):
        for sy in (1, -1):
            px, py = sx * 8.0, sy * 8.0
            add_cyl('tl_pole', (px, py, 2.6), 0.13, 5.2, M['steel'], seg=10)
            add_box('tl_head', (px, py, 5.4), (0.4, 0.4, 1.3), M['darkmetal'])
            add_box('tl_r', (px + sx * 0.22, py, 5.8), (0.06, 0.24, 0.24), M['tail'])
            add_box('tl_g', (px + sx * 0.22, py, 5.0), (0.06, 0.24, 0.24),
                    M['shipgreen'] if random.random() < 0.5 else M['darkmetal'])
    # neon signs and billboards on facades
    for i in range(16):
        side = random.choice((1, -1))
        x = random.uniform(-120, 70)
        h = random.uniform(8, 34)
        nm = M['neon'][i % len(M['neon'])]
        add_box('neon%d' % i, (x, side * 17.2, h),
                (random.uniform(3, 8), 0.3, random.uniform(1.2, 3.0)), nm)
    for i in range(4):
        add_box('billboard%d' % i, (-40 + i * 45, random.choice((1, -1)) * 24, 16),
                (14, 0.5, 6), M['neon'][(i + 2) % len(M['neon'])])
    # cross traffic sitting on the side road
    for i in range(4):
        add_box('xtraffic%d' % i, (-30 + i * 26, random.uniform(40, 120), 0.85),
                (4.2, 1.9, 1.5), M['darkmetal'], bevel=0.06)


def loc_tunnel():
    ground_slab(-30, 30, M['concrete'], z=0.0, name='far_ground')
    add_box('road', (0, 0, -0.01), (520, 14.0, 0.04), M['road'])
    lane_marks(lanes=2)
    for sy in (1, -1):
        add_box('twall_%d' % sy, (0, sy * 8.2, 3.2), (520, 1.2, 6.4), M['concrete'],
                bevel=0.1)
        add_box('tbase_%d' % sy, (0, sy * 7.4, 0.35), (520, 0.7, 0.7), M['curb'])
        add_box('tsvc_%d' % sy, (0, sy * 7.9, 1.3), (520, 0.25, 0.1), M['steel'])
    add_box('tceil', (0, 0, 6.6), (520, 18.0, 0.5), M['concrete'])
    for x in range(-250, 160, 14):
        add_box('tstrip', (x, 0, 6.3), (3.0, 1.1, 0.16), M['strip'])
        if (x // 14) % 4 == 0:
            L = bpy.data.lights.new('tl', 'POINT')
            L.energy = 900.0
            L.color = (0.88, 0.92, 1.0)
            L.shadow_soft_size = 0.5
            o = link(bpy.data.objects.new('tl', L))
            o.location = (x, 0, 5.9)


def loc_alley():
    ground_slab(-30, 30, M['concrete'], z=0.0, name='far_ground')
    add_box('road', (0, 0, -0.01), (420, 15.0, 0.04), M['road'])
    for sy in (1, -1):
        add_box('awall_%d' % sy, (0, sy * 9.0, 8.0), (420, 2.0, 16.0), M['brick'],
                bevel=0.05)
        add_box('akerb_%d' % sy, (0, sy * 7.7, 0.10), (420, 0.6, 0.20), M['curb'])
    # fire escapes, ac units, pipes
    for i in range(9):
        side = 1 if i % 2 else -1
        x = -150 + i * 34 + random.uniform(-6, 6)
        y = side * 7.95
        for k in range(3):
            z = 3.4 + k * 2.6
            add_box('fe_%d_%d' % (i, k), (x, y, z), (4.4, 1.3, 0.12), M['darkmetal'])
            add_box('fe_r_%d_%d' % (i, k), (x, y - side * 0.6, z + 0.55),
                    (4.4, 0.06, 1.1), M['darkmetal'])
        add_box('fe_laddr_%d' % i, (x + 2.0, y - side * 0.3, 5.2),
                (0.5, 0.5, 5.6), M['darkmetal'])
        add_box('ac_%d' % i, (x - 3.0, y - side * 0.55, 6.4), (1.4, 1.1, 1.1),
                M['steel'], bevel=0.05)
    # wall lamps
    for x in range(-140, 100, 34):
        side = 1 if (x // 34) % 2 else -1
        add_box('wl_arm', (x, side * 7.6, 5.6), (0.16, 0.9, 0.16), M['steel'])
        add_box('wl_head', (x, side * 7.1, 5.45), (0.5, 0.34, 0.22), M['lamp_sodium'])
        L = bpy.data.lights.new('wll', 'POINT')
        L.energy = 700.0
        L.color = (1.0, 0.70, 0.38)
        L.shadow_soft_size = 0.25
        o = link(bpy.data.objects.new('wll', L))
        o.location = (x, side * 7.0, 5.3)
    # dumpsters and clutter
    for i in range(10):
        x = random.uniform(-140, 90)
        side = random.choice((1, -1))
        add_box('dump%d' % i, (x, side * 6.2, 0.85), (3.2, 1.8, 1.7),
                M['container'][i % 6], bevel=0.08)
    for i in range(14):
        x = random.uniform(-140, 90)
        side = random.choice((1, -1))
        add_box('bin%d' % i, (x, side * 6.6, 0.45), (0.8, 0.8, 0.9),
                M['darkmetal'], bevel=0.05)


def loc_harbor():
    # pier
    add_box('pier', (0, 0, -0.05), (520, 22.0, 0.5), M['pier'])
    add_box('road', (0, -1.0, 0.02), (520, 15.0, 0.06), M['road'])
    lane_marks(lanes=2, center_y=-1.0)
    add_box('quay', (0, 11.6, 0.25), (520, 1.6, 0.9), M['concrete'])
    for x in range(-240, 150, 26):
        add_cyl('bollard', (x, 10.6, 0.55), 0.32, 1.1, M['darkmetal'], seg=12)
    # water
    wat = mat_simple('water', (0.004, 0.010, 0.018), 0.04, 0.0)
    nt = wat.node_tree
    b = nt.nodes.get('Principled BSDF')
    wv = nt.nodes.new('ShaderNodeTexNoise')
    wv.inputs['Scale'].default_value = 90.0
    wv.inputs['Detail'].default_value = 2.0
    bmp = nt.nodes.new('ShaderNodeBump')
    bmp.inputs['Strength'].default_value = 0.06
    nt.links.new(wv.outputs['Fac'], bmp.inputs['Height'])
    nt.links.new(bmp.outputs['Normal'], b.inputs['Normal'])
    M['water'] = wat
    add_box('sea', (0, -320, -0.9), (1600, 620, 0.4), wat)
    # warehouse along the back
    bld_row(1, y_inner=22, hmin=7, hmax=16, lit=(1.0, 0.72, 0.40), shop=False,
            depth=(14, 22))
    for side in (-1,):
        for x in range(-160, 120, 30):
            streetlight(x, side * 8.6, 'sodium', with_light=((x // 30) % 2 == 0))
    # container stacks
    for i in range(26):
        x = random.uniform(-200, 120)
        y = random.uniform(13, 20)
        h = random.choice((1, 2, 3))
        for k in range(h):
            add_box('cont%d_%d' % (i, k), (x, y, 1.3 + k * 2.7),
                    (12.2, 2.6, 2.6), M['container'][(i + k) % 6], bevel=0.06)
    # gantry cranes
    for cx in (-90, 40):
        for sx in (1, -1):
            add_box('crane_leg', (cx + sx * 7, 16, 10), (1.4, 10, 20), M['steel'],
                    bevel=0.1)
        add_box('crane_beam', (cx, 16, 20.5), (30, 11, 1.6), M['steel'], bevel=0.08)
        add_box('crane_trolley', (cx + 4, 12, 19.0), (5, 4, 2.4), M['steel'],
                bevel=0.08)
        add_box('crane_light', (cx, 11, 21.4), (2, 1, 0.3), M['lamp_led'])
    # warships offshore
    add_ship('ship1', (-30, -95, -0.4), rotz=math.radians(6))
    add_ship('ship2', (90, -190, -0.4), rotz=math.radians(-12), scale=0.9)
    # oil tanks ashore
    for i in range(3):
        add_cyl('oiltank%d' % i, (-120 + i * 26, 26, 4.0), 7.0, 8.0, M['steel'],
                seg=24)
        add_cyl('oiltankc%d' % i, (-120 + i * 26, 26, 8.2), 7.2, 0.4, M['darkmetal'],
                seg=24)
    for i in range(6):
        add_box('flarelamp%d' % i, (-200 + i * 60, 21, 0.6), (0.5, 0.5, 1.2),
                M['flare'])


LOCATIONS = {
    'boulevard': loc_boulevard,
    'downtown': loc_downtown,
    'tunnel': loc_tunnel,
    'alley': loc_alley,
    'harbor': loc_harbor,
}

# ---------------------------------------------------------------- build world
BUILDERS = {
    'boulevard': lambda: build_sky(True, warm=(0.11, 0.06, 0.032)),
    'downtown':  lambda: build_sky(True, warm=(0.13, 0.10, 0.07),
                                   cool=(0.006, 0.007, 0.016)),
    'tunnel':    lambda: build_sky(False, strength=0.08, warm=(0.01, 0.01, 0.012),
                                   cool=(0.004, 0.004, 0.006), stars=False,
                                   clouds=False, moon=False),
    'alley':     lambda: build_sky(True, warm=(0.075, 0.05, 0.035), strength=0.5),
    'harbor':    lambda: build_sky(True, warm=(0.09, 0.07, 0.055), strength=0.8),
}
BUILDERS[LOC]()
LOCATIONS[LOC]()

# ---------------------------------------------------------------- chase cast
groot, gwheels = make_car('getaway', (0.55, 0.06, 0.04), 'muscle', 4.9, detail=True)
proot, pwheels = make_car('police', (0.80, 0.81, 0.83), 'police', 4.6, detail=True,
                          strobe=0)

drive_x(groot, X0_GA, X1_GA)
drv(groot, 'location', 1, '0.6 + 1.8*sin(frame/26.0)')
drv(groot, 'rotation_euler', 2, '-0.10*cos(frame/26.0)')
drive_x(proot, X0_POL, X1_POL)
drv(proot, 'location', 1, '-0.2 + 0.9*sin(frame/20.0 + 1.5)')
drv(proot, 'rotation_euler', 2, '-0.06*cos(frame/20.0 + 1.5)')


def spin_wheels(wheels, d=1.0):
    ang = d * (SPEED * T) / 0.35
    for wl in wheels:
        wl.rotation_euler.y = 0.0
        wl.keyframe_insert('rotation_euler', index=1, frame=1)
        wl.rotation_euler.y = ang
        wl.keyframe_insert('rotation_euler', index=1, frame=FRAMES)
        set_interp(wl, 'LINEAR')


spin_wheels(gwheels)
spin_wheels(pwheels)

# hero lights: police spots + strobe point lights, getaway headlight spots
sl = bpy.data.lights.new('pol_spot', 'SPOT')
sl.energy = 4000.0
sl.spot_size = 0.7
sl.spot_blend = 0.5
sl.color = (1.0, 0.95, 0.85)
so = link(bpy.data.objects.new('pol_spot', sl))
so.location = (2.2, 0, 0.9)
so.rotation_euler = (0, -0.10, 0)
so.parent = proot
so.matrix_parent_inverse = proot.matrix_world.inverted()

HERO_STROBES = {}
for nm, col, yy in (('red', (1.0, 0.06, 0.04), 0.52), ('blue', (0.08, 0.18, 1.0), -0.52)):
    L = bpy.data.lights.new('pl_' + nm, 'POINT')
    L.color = col
    L.energy = 0.0
    L.shadow_soft_size = 0.18
    ob = link(bpy.data.objects.new('pl_' + nm, L))
    ob.location = (0, yy, 1.85)
    ob.parent = proot
    ob.matrix_parent_inverse = proot.matrix_world.inverted()
    HERO_STROBES[nm] = L

for wy in (0.62, -0.62):
    hl = bpy.data.lights.new('ga_hl', 'SPOT')
    hl.energy = 900.0
    hl.spot_size = 1.0
    hl.spot_blend = 0.6
    hl.color = (1.0, 0.93, 0.80)
    ho = link(bpy.data.objects.new('ga_hl', hl))
    ho.location = (2.55, wy, 0.78)
    ho.rotation_euler = (0, -0.16, 0)
    ho.parent = groot
    ho.matrix_parent_inverse = groot.matrix_world.inverted()

# ---------------------------------------------------------------- police fleet
FLEET = 20
N_SPIN = 8
lanes = [-3.1, 3.1, -0.1, 3.1, -3.1, -0.1]
fleet_slots = [(X0_POL + 3.0, -3.1), (X0_POL + 3.0, 3.1),
               (X0_POL + 8.0, -3.1), (X0_POL + 8.0, 3.1)]
x = X0_POL - 10.0
for i in range(FLEET - len(fleet_slots)):
    x -= random.uniform(6.5, 9.5)
    fleet_slots.append((x, lanes[i % len(lanes)]))
for i in range(FLEET):
    fx, lane = fleet_slots[i]
    yb = lane + random.uniform(-0.4, 0.4)
    detail = i < 2
    r, wl = make_car('pc%d' % i, (0.80, 0.81, 0.83), 'police', 4.6,
                     detail=detail, strobe=i)
    drive_x(r, fx, fx + SPEED * T)
    drv(r, 'location', 1, '%f + 1.3*sin(frame/22.0 + %f)' % (yb, i * 0.7))
    drv(r, 'rotation_euler', 2, '-0.08*cos(frame/22.0 + %f)' % (i * 0.7))
    if i < N_SPIN:
        spin_wheels(wl)

# traffic cars in the oncoming lane
traffic_x = [-95.0, -20.0, 60.0]
for k, tx in enumerate(traffic_x):
    t, _ = make_car('traffic%d' % k, TRAFFIC_COLS[k], 'sedan', 4.5, detail=False,
                    spin=False)
    drive_x(t, tx, tx - SPEED * 0.55 * T)
    drv(t, 'location', 1, '%f' % (5.0 + random.uniform(-0.2, 0.2)))
    drv(t, 'rotation_euler', 2, '3.14159')

# tanks: army column behind the fleet plus one forward
tanks = []
for k in range(3):
    ty = -3.2 + k * 3.2
    tk = add_tank('tank%d' % k, (X0_POL - 34 - k * 11.0, ty, 0.0),
                  rotz=random.uniform(-0.05, 0.05))
    drive_x(tk, X0_POL - 34 - k * 11.0, X0_POL - 34 - k * 11.0 + SPEED * 0.9 * T)
    tanks.append(tk)

# helicopters: always 2-3, none in the tunnel
helis = []
if LOC != 'tunnel':
    for k, (hx, hy, hz, sc) in enumerate([(-16, -20, 26, 1.0), (34, 22, 32, 1.15),
                                          (-70, 6, 20, 0.85)]):
        root, rots, lo = add_heli('heli%d' % k, (X0_POL + hx, hy, hz), scale=sc)
        for rb in rots:
            rb.rotation_euler.z = 0.0
            rb.keyframe_insert('rotation_euler', index=2, frame=1)
            rb.rotation_euler.z = math.radians(70) * FRAMES
            rb.keyframe_insert('rotation_euler', index=2, frame=FRAMES)
            set_interp(rb, 'LINEAR')
        drv(root, 'location', 0, '%f + %f*frame/24.0' % (X0_POL + hx, SPEED * 0.97))
        drv(root, 'location', 1, '%f + 3.0*sin(frame/40.0 + %f)' % (hy, k))
        drv(root, 'location', 2, '%f + 0.8*sin(frame/17.0 + %f)' % (hz, k))
        drv(root, 'rotation_euler', 2, '-0.06*cos(frame/26.0 + %f)' % k)
        tg = add_empty('heli%d_tgt' % k, (0, 0, 0))
        drive_x(tg, X0_GA, X1_GA)
        drv(tg, 'location', 1, '0.6 + 1.8*sin((frame/26.0))')
        for obj in (lo,):
            c = obj.constraints.new('TRACK_TO')
            c.target = tg
            c.track_axis = 'TRACK_NEGATIVE_Z'
            c.up_axis = 'UP_Y'
        helis.append(root)

# strobe animation: 3 phases, shared materials
def strobe_anim():
    period = 3
    for phase in range(3):
        f = 1 + phase
        on_red = (phase % 2 == 0)
        while f <= FRAMES:
            val = 1.0 if on_red else 0.0
            red = STROBE_RED[phase].node_tree.nodes['Emission']
            blue = STROBE_BLUE[phase].node_tree.nodes['Emission']
            red.inputs['Strength'].default_value = 26.0 * val
            red.inputs['Strength'].keyframe_insert('default_value', frame=f)
            blue.inputs['Strength'].default_value = 26.0 * (1.0 - val)
            blue.inputs['Strength'].keyframe_insert('default_value', frame=f)
            f += period
            on_red = not on_red
        for mat in (STROBE_RED[phase], STROBE_BLUE[phase]):
            set_interp(mat.node_tree, 'CONSTANT')
    # hero strobe lights follow phase 0
    f = 1
    on_red = True
    while f <= FRAMES:
        for nm, val in (('red', on_red), ('blue', not on_red)):
            HERO_STROBES[nm].energy = 800.0 if val else 0.0
            HERO_STROBES[nm].keyframe_insert('energy', frame=f)
        f += period
        on_red = not on_red
    for nm in HERO_STROBES:
        set_interp(HERO_STROBES[nm], 'CONSTANT')


strobe_anim()

# ---------------------------------------------------------------- camera rigs
hero = add_empty('hero')
drive_x(hero, X0_POL, X1_POL)
drv(hero, 'location', 1, '-0.2 + 0.9*sin(frame/20.0 + 1.5)')

CAMS = {
    'rear':         ((-9.5, 1.30, 1.55), 30.0, (11.0, 0.40, 1.05)),
    'side':         ((5.0, -10.5, 2.60), 20.0, (5.0, 0.50, 1.05)),
    'headon':       ((26.0, -3.40, 1.32), 30.0, (8.0, 0.40, 0.95)),
    'aerial':       ((-4.0, -9.0, 21.0), 28.0, (5.0, 0.40, 0.40)),
    'low':          ((9.0, -5.20, 0.50), 22.0, (2.0, 0.00, 1.00)),
    'tele':         ((40.0, -4.00, 2.00), 200.0, (6.0, 0.30, 1.00)),
    'wheel':        ((-2.2, -2.60, 0.50), 60.0, (1.2, -0.50, 0.70)),
    'bumper':       ((2.8, 0.00, 0.85), 20.0, (16.0, 0.00, 1.00)),
    'threequarter': ((-11.0, -6.50, 1.60), 35.0, (8.0, 0.40, 1.00)),
    'drone':        ((-14.0, -14.0, 12.0), 35.0, (7.0, 0.40, 0.60)),
}
CAMS_OB = {}
for cname, (off, lens, aimoff) in CAMS.items():
    cam = bpy.data.cameras.new('cam_' + cname)
    cam.lens = lens
    cam.sensor_width = 36
    cam.dof.use_dof = cname not in ('aerial', 'drone', 'tele')
    cam.dof.aperture_fstop = 4.0
    ob = link(bpy.data.objects.new('cam_' + cname, cam))
    rigp = add_empty('rig_' + cname, off)
    rigp.parent = hero
    rigp.matrix_parent_inverse = hero.matrix_world.inverted()
    ob.parent = rigp
    ob.matrix_parent_inverse = rigp.matrix_world.inverted()
    ob.location = (0, 0, 0)
    for idx, expr in ((0, '0.04*sin(frame*1.8 + %d)' % len(cname)),
                      (1, '0.06*sin(frame*2.4 + %d)' % len(cname)),
                      (2, '0.04*sin(frame*3.0 + %d)' % len(cname))):
        drv(ob, 'location', idx, expr)
    aim = add_empty('aim_' + cname, aimoff)
    aim.parent = hero
    aim.matrix_parent_inverse = hero.matrix_world.inverted()
    c = ob.constraints.new('TRACK_TO')
    c.target = aim
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'
    cam.dof.focus_object = aim
    CAMS_OB[cname] = ob

# ---------------------------------------------------------------- render config
r = scene.render
r.engine = ENGINE
if ENGINE.startswith('BLENDER_EEVEE'):
    try:
        scene.eevee.taa_render_samples = SAMPLES
        scene.eevee.use_raytracing = False
        scene.eevee.use_shadows = True
    except Exception as e:
        print('eevee setting skipped:', e, flush=True)
r.resolution_x, r.resolution_y = RES_X, RES_Y
r.resolution_percentage = 100
r.fps = FPS
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGB'
r.image_settings.compression = 60
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
scene.cycles.samples = SAMPLES
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
scene.cycles.denoiser = 'OPENIMAGEDENOISE'
scene.cycles.device = 'CPU'
scene.cycles.max_bounces = 8
scene.cycles.diffuse_bounces = 3
scene.cycles.glossy_bounces = 6
scene.cycles.transmission_bounces = 4
scene.cycles.transparent_max_bounces = 6
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.cycles.sample_clamp_indirect = 6.0
scene.view_settings.view_transform = 'AgX'
try:
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass
scene.view_settings.exposure = -0.75

scene.use_nodes = True
nt = scene.node_tree
nt.nodes.clear()
rl = nt.nodes.new('CompositorNodeRLayers')
gl = nt.nodes.new('CompositorNodeGlare')
gl.glare_type = 'FOG_GLOW'
gl.quality = 'MEDIUM'
gl.threshold = 1.0
gl.size = 7
gl.mix = -0.72
comp = nt.nodes.new('CompositorNodeComposite')
nt.links.new(rl.outputs['Image'], gl.inputs['Image'])
nt.links.new(gl.outputs['Image'], comp.inputs['Image'])

# ---------------------------------------------------------------- run
print('BUILD OK loc=%s objects=%d' % (LOC, len(bpy.data.objects)), flush=True)

if MODE == 'build':
    pass
elif MODE == 'timeit':
    scene.camera = CAMS_OB['rear']
    scene.frame_set(18)
    r.filepath = os.path.join(OUTDIR, 'timeit.png')
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    print('TIMEIT %s %s %dx%d %dspp -> %.1f s per frame' % (
        ENGINE, LOC, RES_X, RES_Y, SAMPLES, dt), flush=True)
elif MODE in ('batch', 'anim'):
    if MODE == 'anim':
        specs = [('rear', None), ('side', None)]
        for camname, _ in specs:
            scene.camera = CAMS_OB[camname]
            if camname == 'rear':
                scene.frame_start, scene.frame_end = 1, SHOT_A_END
                pre = 'A_'
            else:
                scene.frame_start, scene.frame_end = SHOT_A_END + 1, FRAMES
                pre = 'B_'
            r.filepath = os.path.join(OUTDIR, 'frames', LOC + '_' + pre + 'f')
            bpy.ops.render.render(animation=True)
    else:
        for item in CAMSPEC.split(','):
            camname, fr = item.split(':')
            camname = camname.strip()
            fr = int(fr)
            scene.camera = CAMS_OB[camname]
            scene.frame_set(fr)
            r.filepath = os.path.join(OUTDIR, '%s_%s_f%02d.png' % (LOC, camname, fr))
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            print('SHOT %s %s f%d: %.1fs' % (LOC, camname, fr, time.time() - t0),
                  flush=True)
print('OBJECTS %d' % len(bpy.data.objects), flush=True)
