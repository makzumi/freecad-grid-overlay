# Grid Overlay for FreeCAD

![Grid Overlay demo](https://raw.githubusercontent.com/makzumi/freecad-grid-overlay/main/Resources/Media/demo.png)

A lightweight, procedural grid overlay for the FreeCAD 3D viewport. The grid is
drawn by a Coin3D/GLSL shader on a single full-screen quad — the fragment
shader intersects each pixel's view ray with the document ground plane and
renders anti-aliased, level-of-detail-blended lines. There is no per-frame
Python work or geometry rebuilds; a low-frequency lifecycle check only repairs
attachment after FreeCAD rebuilds a view scene graph. The quad is rendered in
an independent pass using FreeCAD's live camera, so model frustum culling
cannot hide it when the model is panned off-screen while the grid remains
world-aligned.

An optional soft ground shadow follows the real top-down footprint of the
visible geometry. It is rebuilt on demand from document events (never polled):
shapes are projected onto the ground, rasterized into a blurred mask with
numpy, and sampled by the same shader as a texture.

## Features

- **Procedural grid** — infinite ground grid rendered in GLSL, with automatic
  level-of-detail blending between minor and major lines.
- **Side-view grids** — when the camera looks dead-on from the front, rear,
  left or right, the grid switches to the matching vertical plane (XZ or YZ)
  and is drawn as a backdrop behind the model. Any other view uses the ground.
- **Configurable appearance** — grid color, opacity, unit, spacing, ground
  height, and axis lines.
- **Optional ground shadow** — soft contact shadow that follows each object's
  footprint (L-shapes, cylinders, rotated parts), with adjustable opacity,
  spread and softness.
- **Pick-proof & unlit** — the overlay does not interfere with selection or
  picking, and uses a base-color light model so it is unaffected by scene
  lighting.
- **Depth-safe** — the blended grid writes to the depth buffer with writes
  disabled, so it never hides the shadow beneath it.
- **Toolbar & settings dialog** — a **Grid Overlay** toolbar button opens the
  settings dialog; the button persists across workbenches.
- **Multi-document** — tracks open documents and attaches to the active 3D
  view, including views opened after startup.

## Installation

Place the addon root (the folder containing `package.xml`) anywhere inside your
FreeCAD user `Mod` directory, then restart FreeCAD. The outer folder can be
renamed or installed as a symlink; the addon resolves its resources from its
own package location. The usual `Mod` locations are:

- **Windows:** `%APPDATA%\FreeCAD\Mod` (typically `C:\Users\<username>\AppData\Roaming\FreeCAD\Mod`)
- **Linux:** `~/.local/share/FreeCAD/Mod`
- **macOS:** `~/Library/Preferences/FreeCAD/Mod`

Some FreeCAD builds use a version-specific user directory; in that case, use
the `Mod` folder inside that directory. The modern package layout is:

```text
GridOverlay/
├── package.xml
├── Resources/
└── freecad/
    └── GridOverlay/
        ├── __init__.py
        └── init_gui.py
```

## Usage

The **Grid Overlay** toolbar appears in the main window. Click the grid button
to open **Settings**:

| Setting                 | Description                                                    |
| ----------------------- | -------------------------------------------------------------- |
| Show custom grid        | Toggle the procedural grid overlay on/off.                     |
| Grid unit               | Millimeters, centimeters, meters, inches, or feet.             |
| Grid spacing            | Spacing expressed in the selected unit (0.1–100).              |
| Ground height (Z)       | World Z of the ground grid and its shadow, in the selected unit. |
| Opacity                 | Overall grid opacity.                                          |
| Grid color              | Color of the grid lines.                                       |
| Show axis lines         | Draw the colored X/Y/Z axis lines.                             |
| Grid in front / rear / left / right views | Use a vertical grid when looking straight along X or Y. |
| Show ground shadow      | Toggle the soft footprint shadow beneath geometry.             |
| Shadow opacity          | Opacity of the ground shadow.                                  |
| Shadow spread           | How far the shadow grows beyond the footprint before fading, so parts resting on the ground still show a rim. |
| Shadow softness         | How gradually the shadow edge fades out.                       |

**Restore Defaults** resets the dialog; nothing is saved until **Apply**.

### Ambient occlusion (experimental)

**Ambient occlusion** (off by default) darkens creases, corners and contact
areas between parts. It is screen-space AO, done entirely on the GPU:

1. The scene is rendered a second time into a texture with a shader that
   writes each pixel's linear depth as a 24-bit value split over the RGB
   channels (this Coin build clamps its float texture formats).
2. A full-screen pass rebuilds each model pixel's position and normal,
   looks at the surface visible at nearby points, and darkens the pixel by
   how far that surface rises above its tangent plane. Flat faces therefore
   never shade themselves. The sampling pattern is rotated over 4×4 tiles.
3. A 4×4 blur removes that pattern and darkens the viewport.

The AO textures are rendered at half the viewport resolution; the effect is
soft and blurred, so this is visually indistinguishable and much cheaper.

**Only recomputed when the view settles.** While you orbit, pan or zoom (or
geometry, placement or visibility changes), the effect is hidden; 150 ms
after the last change it is computed once for the new view and fades in.
Between changes it costs nothing: hover highlighting and other display-only
updates do not trigger it.

| Setting  | Description                                                      |
| -------- | ---------------------------------------------------------------- |
| Strength | How dark fully occluded areas get.                               |
| Radius   | How far (in screen pixels) to look for occluders, 8–80 px.       |

**Platform support:** on Linux X11 sessions Coin's offscreen rendering
crashes FreeCAD, so the option is disabled there (Wayland works). Windows
and macOS are untested. As a safeguard, if FreeCAD stops while ambient
occlusion is being enabled, it is switched off on the next start and a
warning is printed; ticking the box again opts back in.

**Performance:** orbiting runs at the same frame rate with AO on as with
it off, because the effect is paused while the view moves. Measured on a
75 Hz display (75 fps is the cap):

| Scene                          | Intel UHD (Raptor Lake) | RTX 4070 Laptop |
| ------------------------------ | ----------------------- | --------------- |
| EngineBlock example            | 75 / 75                 | 75 / 75         |
| AssemblyExample                | 75 / 75                 | 75 / 75         |
| 225 parts, ~0.4M triangles     | 75 / 75                 | 75 / 75         |
| 900 parts, ~3.1M triangles     | 66 / 66                 | 57 / 57         |

(AO off / AO on.) The one-off recompute after the view settles costs
roughly one extra frame of the scene.

Other limitations: the effect briefly disappears while the view moves and
fades back in when it stops; it follows window resizes within half a second;
and transparent objects are treated as opaque.

The grid is shown automatically whenever a document is open and the overlay is
enabled. It regenerates from the viewport's visible area as you navigate, and
the shadow updates on geometry and placement changes (throttled to 150 ms).
Shadow triangles are cached per object, so moving one part only re-tessellates
that part.

FreeCAD's internal geometry coordinates are millimeters; the selected grid unit
is converted to millimeters internally, so a spacing of `1` with **Inches**
means 25.4 FreeCAD units. The ground height is stored in millimeters, so
switching units keeps the same physical height.

## Requirements

- FreeCAD 26.x or 27.x (the current validation targets are 26.3 and 27.1)
- FreeCAD's bundled PySide compatibility module, PySide2, or PySide6 for the
  settings dialog
- `pivy` (Coin3D) for the scene-graph nodes
- `numpy` (bundled with FreeCAD) for ground shadows; without it the grid still
  works and the shadow options are disabled

The add-on keeps its FreeCAD-facing code on APIs shared by 26.x and 27.x. At
startup it detects the host release and warns if it is outside those validated
major versions. Qt enum/button compatibility is handled for both Qt5-style and
Qt6-style bindings, and the shader uses GLSL 1.20 compatibility syntax shared
by the supported Coin3D viewport builds.

For release validation, install the same add-on revision in one FreeCAD 26.x
build and one FreeCAD 27.x build, then verify startup with and without an open
document, open a 3D view, toggle the grid, change each setting, recompute and
move/hide geometry, switch documents, and close/reopen the application. Check
the FreeCAD Python console for import, shader, or observer errors.

## License

See the project license file for details.
