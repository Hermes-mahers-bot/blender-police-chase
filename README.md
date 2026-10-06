# Blender: night police chase render

A single-file, headless Blender scene: a night city police chase. Built and tested on
Blender 4.5.3 LTS, Cycles CPU.

- `scene.py` — the original single-street version: scene, animation, cameras and
  render config in one file. No dependencies outside Blender's bundled Python.
- `epic.py` — expanded version: 5 locations, a 20 car police fleet, 3 helicopters,
  3 tanks, 2 warships, rebuilt car models and a rebuilt sky.
- `run.sh` — thin wrapper that calls `scene.py` with a configurable Blender path.
- `police_chase_v1.mp4` — proof render: 4 s, 480x270, 24 fps, 96 frames.

## The scene

507 objects, all built by script (no external assets):

- wet asphalt boulevard, lane markings, sidewalks, curbs
- buildings with procedural lit window grids and lit ground-floor shopfronts
- streetlights with emissive heads and a few real point lights
- 4 cars: white police cruiser (strobing red/blue light bar plus two real flickering
  point lights, push bumper, blue side stripes), dark red getaway muscle car weaving
  ahead, 2 traffic cars in the oncoming lane
- helicopter overhead with a spinning rotor and a searchlight that tracks the getaway car
- two shots: low rear chase cam (frames 1-52), then a cut to a wide side tracking shot
  (frames 53-96)
- real motion blur, depth of field focused on the cars, AgX view transform, Fog Glow
  bloom in the compositor

## epic.py (expanded version)

Five locations, each with its own geometry, palette and lights:

- `boulevard` — 6 lanes, lit shopfronts, sodium lamps, overpass ahead
- `downtown` — 4-way junction with cross road, 22 to 70 m towers, cold LED lamps,
  traffic signals, neon signs, cross traffic
- `tunnel` — enclosed tube, ceiling light strips, no sky, hard shadows
- `alley` — brick walls, fire escapes, AC units, wall lamps, dumpsters
- `harbor` — pier and quay, containers, gantry cranes, oil tanks, water plane,
  2 warships offshore, moonlit

Ten camera rigs, usable in every location: `rear`, `side`, `headon`, `aerial`,
`low`, `tele` (200 mm), `wheel` (60 mm), `bumper`, `threequarter`, `drone`.

```bash
"$BL" -b --factory-startup -noaudio --python epic.py -- batch 640 360 32 CYCLES boulevard "rear:12,aerial:34"
"$BL" -b --factory-startup -noaudio --python epic.py -- anim 480 270 24 CYCLES downtown
```

Arguments: `MODE RES_X RES_Y SAMPLES ENGINE LOCATION "camera:frame,..."`.
Modes: `batch` (stills from the camera list), `anim` (96 frames, two shots),
`build` (construct only), `timeit` (one timed frame).

Measured: 1,215 to 1,645 objects per location, 22 to 33 s per frame at 640x360 and
32 samples, Cycles CPU.

## Install Blender

- Linux / macOS: download `blender-4.5.3-linux-x64.tar.xz` (360 MB, extracts to about
  1.1 GB) from blender.org/download, extract it, use the `blender` binary inside.
- Windows: run the installer from blender.org, then the exe is at
  `C:\Program Files\Blender Foundation\Blender 4.5\blender.exe`.

## Run

Linux / macOS:

```bash
BL=/path/to/blender-4.5.3-linux-x64/blender
cd /path/to/blender-police-chase

# 1. time one frame first (this tells you if 5 minutes is realistic on your machine)
"$BL" -b --factory-startup -noaudio --python scene.py -- timeit 480 270 24 CYCLES

# 2. render two look-check stills
"$BL" -b --factory-startup -noaudio --python scene.py -- stills 480 270 24 CYCLES

# 3. render the full 96-frame clip
"$BL" -b --factory-startup -noaudio --python scene.py -- anim 480 270 24 CYCLES
```

Windows PowerShell:

```powershell
$BL = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
cd path\to\blender-police-chase
& $BL -b --factory-startup -noaudio --python scene.py -- timeit 480 270 24 CYCLES
& $BL -b --factory-startup -noaudio --python scene.py -- anim 480 270 24 CYCLES
```

## Arguments

```
MODE RES_X RES_Y SAMPLES ENGINE [FLAGS]
```

- `MODE` — `timeit` (one timed frame, prints hours for 5 min at 24 and 12 fps),
  `stills` (frames 14 and 70), `anim` (all 96 frames), `build` (construct scene, render
  nothing)
- `ENGINE` — `CYCLES` (CPU path tracing, works with no GPU) or `BLENDER_EEVEE_NEXT`
  (needs a working GPU, far faster per frame)
- `FLAGS` — comma separated: `nomblur`, `nodof`, `nodenoise`, `noshaft`, `noheli`,
  `nosearch`, `nolights`, `nobldg`, `noworld`, `one`

## Output

Frames are written to `<tempdir>/chase/frames/f0001.png` ... Override with the
`CHASE_OUT` environment variable. Encode to video:

```bash
ffmpeg -framerate 24 -start_number 1 -i frames/f%04d.png \
  -c:v libx264 -crf 20 -pix_fmt yuv420p -movflags +faststart police_chase.mp4
```

## Measured speed

On a 4-core CPU-only box, 480x270, 24 samples, Cycles with denoise, motion blur and
depth of field: **9.3 s per frame**.

- 5 min at 24 fps = 7200 frames = **18.6 h**
- 5 min at 12 fps = 3600 frames = **9.3 h**

EEVEE is a different order of magnitude on real hardware: rasterised frames in the
seconds, not tens of seconds. Run `timeit` with `BLENDER_EEVEE_NEXT` to get your own
number before committing to a long render.

## Gotchas

- EEVEE Next in 4.5 needs a GPU context. On a headless box with no GPU it aborts with
  `Couldn't open libEGL.so.1`. `xvfb-run` with software GL works but is slow.
- Motion blur and depth of field are both on. Each costs a large multiple in render time.
- Blender 4.4+ removed the FCurve-level `interpolation` attribute. Keyframe
  interpolation is set per keyframe point. The script already does this.
- The film is silent. `police_chase_v1.mp4` carries a synthesised siren bed generated
  with ffmpeg, not part of the Blender scene.
