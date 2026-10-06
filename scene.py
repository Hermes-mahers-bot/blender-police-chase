import bpy, math, random, sys, os, time, tempfile
from mathutils import Vector

ARGS = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
MODE      = ARGS[0] if len(ARGS) > 0 else 'anim'
RES_X     = int(ARGS[1]) if len(ARGS) > 1 else 640
RES_Y     = int(ARGS[2]) if len(ARGS) > 2 else 360
SAMPLES   = int(ARGS[3]) if len(ARGS) > 3 else 48
ENGINE    = ARGS[4] if len(ARGS) > 4 else 'CYCLES'
FLAGS     = (ARGS[5] if len(ARGS) > 5 else os.environ.get('CF', '')).split(',')
SHOT_A_END = 52
FRAMES     = 96
FPS        = 24
OUTDIR    = os.environ.get('CHASE_OUT') or os.path.join(tempfile.gettempdir(), 'chase')
FRAMEDIR  = os.path.join(OUTDIR, 'frames')
OUT       = os.path.join(FRAMEDIR, 'f')

random.seed(11)

# ---------------------------------------------------------------- reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
COL = scene.collection

# ---------------------------------------------------------------- helpers
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

def mat_simple(name, base, rough=0.5, metal=0.0, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (base[0], base[1], base[2], 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if 'Specular IOR Level' in b.inputs:
        b.inputs['Specular IOR Level'].default_value = spec
    return m

def mat_emit(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)
    em.inputs['Strength'].default_value = strength
    nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
    return m

BOX_V = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]
BOX_F = [(0,1,2,3),(7,6,5,4),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)]

def add_box(name, loc, size, mat, rot=(0,0,0), parent=None, bevel=0.0, smooth=False):
    sx, sy, sz = size[0]/2.0, size[1]/2.0, size[2]/2.0
    verts = [(v[0]*sx, v[1]*sy, v[2]*sz) for v in BOX_V]
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
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
    return ob

def add_cyl_y(name, loc, r, depth, mat, seg=24, parent=None, smooth=True):
    """cylinder whose axis is +Y, sits at loc"""
    verts, faces = [], []
    for i in range(seg):
        a = 2*math.pi*i/seg
        x, z = math.cos(a)*r, math.sin(a)*r
        verts.append((x, -depth/2, z))
        verts.append((x,  depth/2, z))
    for i in range(seg):
        a0, a1 = 2*i, 2*((i+1) % seg)
        faces.append((a0, a0+1, a1+1, a1))
    faces.append(tuple(range(0, 2*seg, 2)))
    faces.append(tuple(range(2*seg-1, 0, -2)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    link(ob)
    ob.location = loc
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

def add_empty(name, loc=(0,0,0)):
    em = bpy.data.objects.new(name, None)
    em.empty_display_size = 1.0
    link(em)
    em.location = loc
    return em

def facade_mat(name, base=(0.008,0.008,0.011), lit=(1.0,0.55,0.22), cell=0.36,
               seed=0.0, bright=1.0):
    """building wall: regular window grid, ~45% of windows lit"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (900, 0)
    mix = nt.nodes.new('ShaderNodeMixShader');     mix.location = (700, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (450, -220)
    bsdf.inputs['Base Color'].default_value = (base[0], base[1], base[2], 1.0)
    bsdf.inputs['Roughness'].default_value = 0.85
    em = nt.nodes.new('ShaderNodeEmission');        em.location = (450, 180)
    em.inputs['Color'].default_value = (lit[0], lit[1], lit[2], 1.0)
    em.inputs['Strength'].default_value = 1.15 * bright
    coord = nt.nodes.new('ShaderNodeTexCoord');   coord.location = (-900, 0)
    mapn = nt.nodes.new('ShaderNodeMapping');     mapn.location = (-700, 0)
    mapn.inputs['Location'].default_value = (seed*3.1, seed*1.7, 0.0)
    mapn.inputs['Scale'].default_value = (1.0/cell, 1.0/cell, 1.0/(cell*1.35))
    chk = nt.nodes.new('ShaderNodeTexChecker');   chk.location = (-480, 120)
    chk.inputs['Scale'].default_value = 1.0
    noise = nt.nodes.new('ShaderNodeTexNoise');   noise.location = (-700, -320)
    noise.inputs['Scale'].default_value = 2.5
    noise.inputs['Detail'].default_value = 2.0
    ra = nt.nodes.new('ShaderNodeValToRGB');      ra.location = (-480, -320)
    ra.color_ramp.interpolation = 'CONSTANT'
    ra.color_ramp.elements[0].position = 0.0
    ra.color_ramp.elements[0].color = (0,0,0,1)
    ra.color_ramp.elements[1].position = 0.50
    ra.color_ramp.elements[1].color = (1,1,1,1)
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

# ---------------------------------------------------------------- materials
ROAD   = mat_simple('asphalt', (0.016,0.016,0.019), rough=0.22)
CURB   = mat_simple('curb',    (0.10,0.10,0.11),   rough=0.6)
PAINT  = mat_simple('paint',   (0.38,0.37,0.35),   rough=0.35)
SIDEWALKP = mat_simple('sidewalk', (0.11,0.11,0.115), rough=0.5)
METAL  = mat_simple('metal',   (0.35,0.36,0.38),   rough=0.35, metal=0.9)
GLASS  = mat_simple('glass',   (0.01,0.012,0.02),  rough=0.06, metal=0.1)
TIRE   = mat_simple('tire',    (0.012,0.012,0.014), rough=0.85)
BLUELIGHT = mat_simple('bluelight', (0.02,0.05,0.35), rough=0.3)
POLE   = mat_simple('pole',    (0.05,0.05,0.055),  rough=0.45, metal=0.7)

HEAD   = mat_emit('headlight', (1.0,0.94,0.82), 16.0)
TAIL   = mat_emit('taillight', (1.0,0.05,0.02), 7.0)
LAMP   = mat_emit('streetlamp',(1.0,0.72,0.40), 6.0)
REDL   = mat_emit('pol_red',   (1.0,0.02,0.02), 22.0)
BLUL   = mat_emit('pol_blue',  (0.05,0.15,1.0), 22.0)
SEARCH = mat_emit('searchlight',(1.0,0.97,0.9), 22.0)
SHEDGE = mat_emit('shaft',     (1.0,0.95,0.85), 3.0)

# ---------------------------------------------------------------- world
scene.world = bpy.data.worlds.new('W')
w = scene.world
w.use_nodes = True
wn = w.node_tree
wn.nodes.clear()
wout = wn.nodes.new('ShaderNodeOutputWorld')
bg   = wn.nodes.new('ShaderNodeBackground')
tc   = wn.nodes.new('ShaderNodeTexCoord')
sep  = wn.nodes.new('ShaderNodeSeparateXYZ')
mr   = wn.nodes.new('ShaderNodeMapRange')
ramp = wn.nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].color = (0.004,0.005,0.011,1)
ramp.color_ramp.elements[1].position = 0.55
ramp.color_ramp.elements[1].color = (0.10,0.055,0.03,1)
mr.inputs['From Min'].default_value = -0.05
mr.inputs['From Max'].default_value = 0.35
mr.inputs['To Min'].default_value = 1.0
mr.inputs['To Max'].default_value = 0.0
bg.inputs['Strength'].default_value = 0.75
wn.links.new(tc.outputs['Generated'], sep.inputs['Vector'])
wn.links.new(sep.outputs['Z'], mr.inputs['Value'])
wn.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
wn.links.new(ramp.outputs['Color'], bg.inputs['Color'])
wn.links.new(bg.outputs['Background'], wout.inputs['Surface'])

# ---------------------------------------------------------------- ground + road
add_box('far_ground', (0,0,-0.06), (3000,3000,0.12), SIDEWALKP)
add_box('road', (0,0,-0.01), (420,13.0,0.04), ROAD)
for sy in (1,-1):
    add_box('sidewalk_%d'%sy, (0, sy*8.0, 0.06), (420, 3.0, 0.24), CURB, bevel=0.06)
    add_box('curb_%d'%sy,     (0, sy*6.5, 0.03), (420, 0.35, 0.30), CURB)
    add_box('lot_%d'%sy,      (0, sy*15.5, 0.015), (420, 13.0, 0.05), SIDEWALKP)
# lane markings
for x in range(-190, 190, 8):
    add_box('dash', (x, 0.0, 0.02), (3.6, 0.13, 0.02), PAINT)
for sy in (1,-1):
    for x in range(-190, 190, 4):
        add_box('lane', (x, sy*3.3, 0.02), (1.6, 0.10, 0.02), PAINT)

# ---------------------------------------------------------------- buildings
FAR = []
for side in (1,-1):
    x = -150.0
    i = 0
    while x < 80.0:
        wdt = random.uniform(9, 15)
        dep = random.uniform(9, 14)
        hgt = random.uniform(7, 26) * (1.0 + max(0.0, x/300.0))
        yc  = side * (13.0 + dep/2 + random.uniform(0, 3))
        m = facade_mat('fac_%d_%d'%(side,i), seed=random.uniform(0,10),
                       cell=random.uniform(0.30,0.45),
                       bright=random.uniform(0.5,1.2))
        add_box('bld_%d_%d'%(side,i), (x + wdt/2, yc, hgt/2), (wdt, dep, hgt), m,
                bevel=0.05)
        innery = yc - side * dep / 2.0
        sm = facade_mat('shopm_%d_%d'%(side,i), seed=random.uniform(0,10),
                        cell=0.5, bright=random.uniform(0.7,1.1))
        add_box('shop_%d_%d'%(side,i), (x + wdt/2, innery - side*0.12, 0.85),
                (wdt*0.94, 0.14, 1.5), sm)
        # roof block + antenna
        add_box('roof', (x + wdt/2, yc, hgt + 0.5), (wdt*0.55, dep*0.5, 1.0),
                mat_simple('rf%d'%i,(0.02,0.02,0.022),0.8))
        if random.random() < 0.35:
            add_box('mas', (x + wdt/2, yc, hgt + 3.0), (0.2,0.2,5.0), POLE)
        x += wdt + random.uniform(3.5, 8.0)
        i += 1
    # distant skyline
    for k in range(26):
        bx = random.uniform(-160, 120)
        by = side * random.uniform(58, 130)
        bh = random.uniform(18, 62)
        FAR.append((bx, by, bh))

# ---------------------------------------------------------------- street lights
for side in (1,-1):
    for x in range(-120, 90, 28):
        p = add_box('sl_pole', (x, side*7.4, 3.6), (0.22,0.22,7.2), POLE)
        add_box('sl_arm', (x, side*6.2, 7.1), (0.16,2.6,0.16), POLE)
        add_box('sl_head', (x, side*5.1, 6.95), (1.0,0.6,0.22), LAMP)
        if (x // 28) % 2 == 0:
            L = bpy.data.lights.new('sll', 'POINT')
            L.energy = 1500.0
            L.color = (1.0,0.72,0.42)
            L.shadow_soft_size = 0.4
            ob = link(bpy.data.objects.new('sll', L))
            ob.location = (x, side*5.1, 6.6)

# ---------------------------------------------------------------- car factory
def make_car(name, body_color, police=False, muscle=False, length=4.5):
    root = add_empty(name + '_root')
    body = mat_simple(name+'_body', body_color, rough=0.22, metal=0.6)
    L = length
    add_box(name+'_body', (0,0,0.70), (L, 1.95, 0.66), body, parent=root, bevel=0.10)
    add_box(name+'_skirt',(0,0,0.42), (L*0.97, 1.80, 0.28), TIRE, parent=root, bevel=0.05)
    cab = 1.95 if muscle else 2.15
    cabx = -0.35 if muscle else -0.15
    add_box(name+'_cab', (cabx, 0, 1.18), (cab, 1.78, 0.56), GLASS, parent=root,
            bevel=0.09)
    add_box(name+'_roof', (cabx, 0, 1.48), (cab*0.94, 1.70, 0.12), body,
            parent=root, bevel=0.05)
    add_box(name+'_hood', (L*0.32, 0, 1.00), (L*0.34, 1.80, 0.10), body,
            parent=root, bevel=0.04)
    add_box(name+'_trunk',(-L*0.34, 0, 1.02), (L*0.30, 1.80, 0.10), body,
            parent=root, bevel=0.04)
    add_box(name+'_grille', (L/2-0.04, 0, 0.60), (0.10, 1.30, 0.26), TIRE, parent=root)
    # wheels
    wheels = []
    for wx in (L*0.30, -L*0.30):
        for wy in (0.92, -0.92):
            wl = add_cyl_y(name+'_wheel', (wx, wy, 0.36), 0.36, 0.28, TIRE, parent=root)
            add_cyl_y(name+'_rim', (wx, wy + (0.145 if wy > 0 else -0.145), 0.36),
                      0.20, 0.03, METAL, parent=root)
            wheels.append(wl)
    # lights
    for wy in (0.62, -0.62):
        add_box(name+'_hl', (L/2-0.02, wy, 0.78), (0.12, 0.44, 0.18), HEAD, parent=root)
        add_box(name+'_tl', (-L/2+0.02, wy, 0.82), (0.10, 0.50, 0.16), TAIL, parent=root)
    if police:
        add_box(name+'_stripe1', (0, 0.985, 0.72), (L*0.62, 0.02, 0.34), BLUELIGHT, parent=root)
        add_box(name+'_stripe2', (0,-0.985, 0.72), (L*0.62, 0.02, 0.34), BLUELIGHT, parent=root)
        add_box(name+'_bar', (-0.30, 0, 1.56), (0.80, 1.62, 0.10), TIRE, parent=root)
        add_box(name+'_barR',(-0.30, 0.55, 1.70), (0.60, 0.52, 0.20), REDL, parent=root)
        add_box(name+'_barB',(-0.30,-0.55, 1.70), (0.60, 0.52, 0.20), BLUL, parent=root)
        add_box(name+'_barW',(-0.30, 0.00, 1.70), (0.55, 0.42, 0.18),
                mat_emit('barW',(1,1,1),12.0), parent=root)
        add_box(name+'_push', (L/2+0.10, 0, 0.55), (0.16, 1.70, 0.36), METAL, parent=root)
    return root, wheels

# ---------------------------------------------------------------- chase cast
groot, gwheels = make_car('getaway', (0.55,0.06,0.04), muscle=True, length=4.9)
proot, pwheels = make_car('police',  (0.86,0.87,0.88), police=True, length=4.6)

# two traffic cars in the oncoming lane
traffic = []
for k, tx in enumerate((-95.0, -20.0)):
    t, _ = make_car('traffic%d'%k, (0.05,0.06,0.12) if k else (0.16,0.14,0.04))
    t.location.x = tx
    t.location.y = 3.35
    t.rotation_euler.z = math.pi
    traffic.append(t)

# police light rig: red + blue point lights above the bar
plights = {}
for nm, col in (('red', (1.0,0.06,0.04)), ('blue',(0.08,0.18,1.0))):
    L = bpy.data.lights.new('pl_'+nm, 'POINT')
    L.color = col
    L.energy = 0.0
    L.shadow_soft_size = 0.18
    ob = link(bpy.data.objects.new('pl_'+nm, L))
    ob.location = (0, 0.55 if nm == 'red' else -0.55, 1.85)
    ob.parent = proot
    ob.matrix_parent_inverse = proot.matrix_world.inverted()
    plights[nm] = L

# police forward spot
sl = bpy.data.lights.new('pol_spot', 'SPOT')
sl.energy = 4000.0
sl.spot_size = 0.7
sl.spot_blend = 0.5
sl.color = (1.0,0.95,0.85)
so = link(bpy.data.objects.new('pol_spot', sl))
so.location = (2.2, 0, 0.9)
so.rotation_euler = (0, -0.10, 0)
so.parent = proot
so.matrix_parent_inverse = proot.matrix_world.inverted()

# getaway headlight spots
for wy in (0.62, -0.62):
    hl = bpy.data.lights.new('ga_hl', 'SPOT')
    hl.energy = 900.0
    hl.spot_size = 1.0
    hl.spot_blend = 0.6
    hl.color = (1.0,0.93,0.8)
    ho = link(bpy.data.objects.new('ga_hl', hl))
    ho.location = (2.55, wy, 0.78)
    ho.rotation_euler = (0, -0.16, 0)
    ho.parent = groot
    ho.matrix_parent_inverse = groot.matrix_world.inverted()

# ---------------------------------------------------------------- helicopter
hroot = add_empty('heli_root')
hbody = mat_simple('heli', (0.03,0.04,0.06), rough=0.35, metal=0.7)
add_box('h_body', (0,0,0), (3.4,1.5,1.25), hbody, parent=hroot, bevel=0.15)
add_box('h_nose', (1.9,0,0.05), (1.0,1.1,0.9), GLASS, parent=hroot, bevel=0.1)
add_box('h_tail', (-4.3,0,0.32), (5.4,0.42,0.42), hbody, parent=hroot, bevel=0.06)
add_box('h_fin',  (-6.6,0,1.05), (0.9,0.16,1.3), hbody, parent=hroot)
add_box('h_skid1',(0,-0.7,-1.0), (2.6,0.14,0.14), METAL, parent=hroot)
add_box('h_skid2',(0, 0.7,-1.0), (2.6,0.14,0.14), METAL, parent=hroot)
rotor = add_box('h_rotor', (0,0,0.85), (11.5,0.30,0.07), METAL, parent=hroot)
rotor2 = add_box('h_rotor2',(0,0,0.86), (0.30,11.5,0.07), METAL, parent=hroot)
trot = add_box('h_trotor',(-6.9,0.35,1.05), (0.10,2.4,2.4), METAL, parent=hroot,
               rot=(0,math.radians(90),0))
add_box('h_search', (0.6,-0.55,-0.65), (0.55,0.55,0.5), SEARCH, parent=hroot)
hl2 = bpy.data.lights.new('heli_spot', 'SPOT')
hl2.energy = 22000.0
hl2.spot_size = 0.30
hl2.spot_blend = 0.12
hl2.color = (1.0,0.97,0.9)
hso = link(bpy.data.objects.new('heli_spot', hl2))
hso.location = (0.6, -0.55, -0.6)
hso.parent = hroot
hso.matrix_parent_inverse = hroot.matrix_world.inverted()
# light shaft cone
import bmesh
me = bpy.data.meshes.new('shaft')
bm = bmesh.new()
bmesh.ops.create_cone(bm, cap_ends=False, segments=28, radius1=0.22, radius2=3.4,
                      depth=15.0)
bm.to_mesh(me); bm.free()
sh = bpy.data.objects.new('shaft', me)
link(sh)
sh.data.materials.append(SHEDGE)
sh.location = (0.6, -0.55, -8.2)
sh.rotation_euler = (math.radians(-8), 0, 0)
sh.parent = hroot
sh.matrix_parent_inverse = hroot.matrix_world.inverted()
m = SHEDGE
m.use_nodes = True
nt = m.node_tree
nt.nodes.clear()
o = nt.nodes.new('ShaderNodeOutputMaterial')
mx = nt.nodes.new('ShaderNodeMixShader')
tr = nt.nodes.new('ShaderNodeBsdfTransparent')
em = nt.nodes.new('ShaderNodeEmission')
em.inputs['Color'].default_value = (1.0,0.95,0.85,1)
em.inputs['Strength'].default_value = 1.4
lw = nt.nodes.new('ShaderNodeLayerWeight')
lw.inputs['Blend'].default_value = 0.35
nt.links.new(lw.outputs['Facing'], mx.inputs['Fac'])
nt.links.new(tr.outputs['BSDF'], mx.inputs[1])
nt.links.new(em.outputs['Emission'], mx.inputs[2])
nt.links.new(mx.outputs['Shader'], o.inputs['Surface'])
try:
    m.blend_method = 'BLEND'
except Exception:
    pass

# ---------------------------------------------------------------- animation
SPEED = 26.0                       # m/s
X0_GA, X0_POL = -62.0, -74.0
T = FRAMES / FPS
X1_GA  = X0_GA  + SPEED * T
X1_POL = X0_POL + SPEED * T

def drive_x(ob, x0, x1):
    ob.location.x = x0
    ob.keyframe_insert('location', index=0, frame=1)
    ob.location.x = x1
    ob.keyframe_insert('location', index=0, frame=FRAMES)
    set_interp(ob, 'LINEAR', 'location', 0)

def weave(ob, base, amp, w, phase, lean=True):
    ob.location.y = base
    d = ob.driver_add('location', 1)
    d.driver.type = 'SCRIPTED'
    d.driver.expression = '%f + %f*sin((frame/%d.0) + %f)' % (base, amp, w, phase)
    if lean:
        r = ob.driver_add('rotation_euler', 2)
        r.driver.type = 'SCRIPTED'
        r.driver.expression = '-0.10*cos((frame/%d.0) + %f)' % (w, phase)

drive_x(groot, X0_GA, X1_GA);  weave(groot, 0.6, 1.8, 26, 0.0)
drive_x(proot, X0_POL, X1_POL); weave(proot, -0.2, 0.9, 20, 1.5)

for t in traffic:
    t.location.x = t.location.x
    x0 = t.location.x
    t.keyframe_insert('location', index=0, frame=1)
    t.location.x = x0 - SPEED * 0.55 * T
    t.keyframe_insert('location', index=0, frame=FRAMES)
    set_interp(t, 'LINEAR')

# wheel spin
def spin(wheels, circumference_dir, L=4.5):
    dist = SPEED * T
    ang = circumference_dir * dist / 0.36
    for wl in wheels:
        wl.rotation_euler.y = 0.0
        wl.keyframe_insert('rotation_euler', index=1, frame=1)
        wl.rotation_euler.y = ang
        wl.keyframe_insert('rotation_euler', index=1, frame=FRAMES)
        set_interp(wl, 'LINEAR')
spin(gwheels, -1.0)
spin(pwheels, -1.0)

# helicopter follows the getaway car with lag
hx = hroot.driver_add('location', 0); hx.driver.type='SCRIPTED'
hx.driver.expression = 'fcurve'  # placeholder replaced below
hx.driver.expression = '-70.0 + %f*frame/24.0' % (SPEED * 0.98)
hy = hroot.driver_add('location', 1); hy.driver.type='SCRIPTED'
hy.driver.expression = '-16.0 + 3.0*sin(frame/40.0)'
hz = hroot.driver_add('location', 2); hz.driver.type='SCRIPTED'
hz.driver.expression = '26.0 + 0.8*sin(frame/17.0)'
hr = hroot.driver_add('rotation_euler', 2); hr.driver.type='SCRIPTED'
hr.driver.expression = '-0.06*cos(frame/26.0)'

# rotor spin (fast)
rotors = [rotor, rotor2]
for rb in rotors:
    rb.rotation_euler.z = 0.0
    rb.keyframe_insert('rotation_euler', index=2, frame=1)
    rb.rotation_euler.z = math.radians(70) * FRAMES
    rb.keyframe_insert('rotation_euler', index=2, frame=FRAMES)
    set_interp(rb, 'LINEAR')
trot.rotation_euler.y = 0.0
trot.keyframe_insert('rotation_euler', index=1, frame=1)
trot.rotation_euler.y = math.radians(70) * FRAMES
trot.keyframe_insert('rotation_euler', index=1, frame=FRAMES)
set_interp(trot, 'LINEAR')

# helicopter searchlight tracks the getaway car
htgt = add_empty('heli_target', (0,0,0))
htgt.location.x = X0_GA
htgt.keyframe_insert('location', index=0, frame=1)
htgt.location.x = X1_GA
htgt.keyframe_insert('location', index=0, frame=FRAMES)
set_interp(htgt, 'LINEAR')
ty = htgt.driver_add('location', 1); ty.driver.type='SCRIPTED'
ty.driver.expression = '0.6 + 1.8*sin((frame/26.0))'
c = hso.constraints.new('TRACK_TO')
c.target = htgt
c.track_axis = 'TRACK_NEGATIVE_Z'
c.up_axis = 'UP_Y'
c2 = sh.constraints.new('TRACK_TO')
c2.target = htgt
c2.track_axis = 'TRACK_NEGATIVE_Z'
c2.up_axis = 'UP_Y'

# police strobe
def strobe():
    period = 3
    f = 1
    on_red = True
    while f <= FRAMES:
        for nm, val in (('red', on_red), ('blue', not on_red)):
            mall = REDL if nm == 'red' else BLUL
            n = mall.node_tree.nodes['Emission']
            n.inputs['Strength'].default_value = 26.0 if val else 0.0
            n.inputs['Strength'].keyframe_insert('default_value', frame=f)
            plights[nm].energy = 1200.0 if val else 0.0
            plights[nm].keyframe_insert('energy', frame=f)
        f += period
        on_red = not on_red
    # keep constant + hold
    for nm, mall in (('red', REDL), ('blue', BLUL)):
        set_interp(mall.node_tree, 'CONSTANT')
        set_interp(plights[nm], 'CONSTANT')
strobe()

# ---------------------------------------------------------------- cameras
camA = bpy.data.cameras.new('camA'); camA.lens = 30.0; camA.sensor_width = 36
camA.dof.use_dof = True; camA.dof.aperture_fstop = 4.5
obA = link(bpy.data.objects.new('camA', camA))
aimA = add_empty('aimA')
camB = bpy.data.cameras.new('camB'); camB.lens = 20.0; camB.sensor_width = 36
camB.dof.use_dof = True; camB.dof.aperture_fstop = 3.2
obB = link(bpy.data.objects.new('camB', camB))
aimB = add_empty('aimB')

# shot A: low rear chase cam, 6.5 m behind police
obA.location = (-6.5, 0.9, 1.30)
obA.driver_add('location', 0).driver.expression = '0.05*sin(frame*1.9)'
obA.driver_add('location', 1).driver.expression = '0.07*sin(frame*2.7)'
obA.driver_add('location', 2).driver.expression = '0.045*sin(frame*3.3)'
obA.rotation_euler.z = 0.0
tgtA = obA.constraints.new('TRACK_TO'); tgtA.target = aimA
tgtA.track_axis = 'TRACK_NEGATIVE_Z'; tgtA.up_axis = 'UP_Y'
aimA.location = (7.5, 0.4, 0.95)
camA.dof.focus_object = aimA

# rig A moves with the police car (drivers)
for i, ex in enumerate(('0.0', "'0.9'", "'1.30'")):
    pass
rA = obA.driver_add('location', 0)
# need absolute motion: rebuild as parent rig instead
obA.constraints.remove(tgtA)

rigA = add_empty('rigA')
rigA.location = (0,0,0)
drive_x(rigA, X0_POL - 9.5, X1_POL - 9.5)
ry = rigA.driver_add('location', 1); ry.driver.type='SCRIPTED'
ry.driver.expression = '-0.2 + 0.9*sin((frame/20.0) + 1.5) + 1.3'
rz = rigA.driver_add('location', 2); rz.driver.type='SCRIPTED'
rz.driver.expression = '1.55 + 0.03*sin(frame/6.0)'
obA.parent = rigA
obA.matrix_parent_inverse = rigA.matrix_world.inverted()
obA.location = (0.0, 0.0, 0.0)
obA.rotation_euler = (0,0,0)
for idx, expr in ((0,'0.05*sin(frame*1.9)'), (1,'0.07*sin(frame*2.7)'),
                  (2,'0.045*sin(frame*3.3)')):
    d = obA.driver_add('location', idx)
    d.driver.type = 'SCRIPTED'
    d.driver.expression = expr
tgtA = obA.constraints.new('TRACK_TO'); tgtA.target = aimA
tgtA.track_axis = 'TRACK_NEGATIVE_Z'; tgtA.up_axis = 'UP_Y'

# aim point between police and getaway, slightly ahead
aimA.parent = None
drive_x(aimA, X0_POL + 11.0, X1_POL + 11.0)
ay = aimA.driver_add('location', 1); ay.driver.type='SCRIPTED'
ay.driver.expression = '0.6 + 1.8*sin((frame/26.0))'
aimA.location.z = 1.05
camA.dof.focus_object = aimA
camA.dof.aperture_blades = 6

# shot B: side tracking dolly
rigB = add_empty('rigB')
rigB.location = (0,0,0)
drive_x(rigB, X0_POL + 5.0, X1_POL + 5.0)
ryb = rigB.driver_add('location', 1); ryb.driver.type='SCRIPTED'
ryb.driver.expression = '-10.5'
rzb = rigB.driver_add('location', 2); rzb.driver.type='SCRIPTED'
rzb.driver.expression = '2.60 + 0.05*sin(frame/5.0)'
obB.parent = rigB
obB.matrix_parent_inverse = rigB.matrix_world.inverted()
obB.location = (0,0,0)
for idx, expr in ((0,'0.04*sin(frame*1.7)'), (1,'0.06*sin(frame*2.1)'),
                  (2,'0.04*sin(frame*2.9)')): 
    d = obB.driver_add('location', idx)
    d.driver.type = 'SCRIPTED'
    d.driver.expression = expr
drive_x(aimB, X0_POL + 5.0, X1_POL + 5.0)
ayb = aimB.driver_add('location', 1); ayb.driver.type='SCRIPTED'
ayb.driver.expression = '0.5'; 
aimB.location.z = 1.05
tgtB = obB.constraints.new('TRACK_TO'); tgtB.target = aimB
tgtB.track_axis = 'TRACK_NEGATIVE_Z'; tgtB.up_axis = 'UP_Y'
camB.dof.focus_object = aimB

# ---------------------------------------------------------------- render config
r = scene.render
r.engine = ENGINE
if ENGINE.startswith('BLENDER_EEVEE'):
    try:
        scene.eevee.taa_render_samples = SAMPLES
        scene.eevee.use_raytracing = False
        scene.eevee.use_shadows = True
    except Exception as e:
        print('eevee setting skipped:', e)
r.resolution_x, r.resolution_y = RES_X, RES_Y
r.resolution_percentage = 100
r.fps = FPS
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGB'
r.image_settings.compression = 60
r.filepath = OUT
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
r.film_transparent = False
scene.cycles.samples = SAMPLES
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
scene.cycles.denoiser = 'OPENIMAGEDENOISE'
scene.cycles.device = 'CPU'
scene.cycles.max_bounces = 8
scene.cycles.diffuse_bounces = 3
scene.cycles.glossy_bounces = 4
scene.cycles.transmission_bounces = 4
scene.cycles.transparent_max_bounces = 6
scene.cycles.caustics_reflective = False
scene.cycles.caustics_refractive = False
scene.cycles.sample_clamp_indirect = 6.0
scene.cycles.blur_glossy = 1.0
scene.cycles.use_fast_gi = False
scene.view_settings.view_transform = 'AgX'
try:
    scene.view_settings.look = 'AgX - Medium High Contrast'
except Exception:
    pass
scene.view_settings.exposure = -0.75

# compositor bloom
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
os.makedirs(FRAMEDIR, exist_ok=True)
if 'nomblur' in FLAGS:
    r.use_motion_blur = False
if 'noshaft' in FLAGS:
    bpy.data.objects['shaft'].hide_render = True
if 'noheli' in FLAGS:
    hroot.hide_render = True
if 'nocomp' in FLAGS:
    scene.use_nodes = False
if 'nosearch' in FLAGS:
    bpy.data.objects['heli_spot'].hide_render = True
if 'nodenoise' in FLAGS:
    scene.cycles.use_denoising = False
if 'nodof' in FLAGS:
    for cn in ('camA', 'camB'):
        bpy.data.cameras[cn].dof.use_dof = False
if 'nolights' in FLAGS:
    for o in list(bpy.data.objects):
        if o.type == 'LIGHT':
            o.hide_render = True
if 'nobldg' in FLAGS:
    for o in list(bpy.data.objects):
        if o.name.startswith(('bld_', 'roof', 'mas')):
            o.hide_render = True
if 'noworld' in FLAGS:
    scene.world = None
print('BUILD OK objects=%d samples=%d args=%s' % (
    len(bpy.data.objects), scene.cycles.samples, ARGS), flush=True)
if MODE == 'timeit':
    scene.camera = obA
    scene.frame_set(14)
    r.filepath = os.path.join(OUTDIR, 'timeit.png')
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    print('TIMEIT %s %dx%d %dspp -> %.1f s per frame' % (
        ENGINE, RES_X, RES_Y, SAMPLES, dt), flush=True)
    print('TIMEIT 5 min at 24 fps = %d frames -> %.1f hours' % (
        7200, dt * 7200 / 3600.0), flush=True)
    print('TIMEIT 5 min at 12 fps = %d frames -> %.1f hours' % (
        3600, dt * 3600 / 3600.0), flush=True)
elif MODE == 'build':
    pass
elif MODE == 'stills':
    shots = ((14, obA, 'A'),) if 'one' in FLAGS else ((14, obA, 'A'), (70, obB, 'B'))
    for fr, cam, tag in shots:
        scene.camera = cam
        scene.frame_set(fr)
        r.filepath = os.path.join(OUTDIR, 'still_%s.png' % tag)
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print('STILL %s frame %d: %.1fs' % (tag, fr, time.time()-t0), flush=True)
elif MODE == 'anim':
    scene.frame_start, scene.frame_end = 1, SHOT_A_END
    scene.camera = obA
    r.filepath = OUT
    t0 = time.time()
    bpy.ops.render.render(animation=True)
    print('SHOT A done %.1f s' % (time.time()-t0))
    scene.frame_start, scene.frame_end = SHOT_A_END + 1, FRAMES
    scene.camera = obB
    bpy.ops.render.render(animation=True)
    print('SHOT B done %.1f s' % (time.time()-t0))
print('OBJECTS', len(bpy.data.objects))
