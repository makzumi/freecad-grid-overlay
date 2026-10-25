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

An optional soft ground shadow is generated beneath visible document geometry,
updated on demand from document events (never polled).

## Features

- **Procedural grid** — infinite ground grid rendered in GLSL, with automatic
  level-of-detail blending between minor and major lines.
- **Configurable appearance** — grid color, opacity, unit, and spacing.
- **Optional ground shadow** — soft radial-falloff shadow beneath visible
  geometry, with adjustable opacity.
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

Place the `GridOverlay` folder in your FreeCAD user `Mod` directory, then
restart FreeCAD. The usual locations are:

- **Windows:** `%APPDATA%\FreeCAD\Mod` (typically `C:\Users\<username>\AppData\Roaming\FreeCAD\Mod`)
- **Linux:** `~/.local/share/FreeCAD/Mod`
- **macOS:** `~/Library/Preferences/FreeCAD/Mod`

Some FreeCAD builds use a version-specific user directory; in that case, use
the `Mod` folder inside that directory.

## Usage

The **Grid Overlay** toolbar appears in the main window. Click the grid button
to open **Settings**:

| Setting              | Description                                              |
| -------------------- | -------------------------------------------------------- |
| Show custom grid     | Toggle the procedural grid overlay on/off.              |
| Show ground shadow   | Toggle the optional soft shadow beneath geometry.       |
| Ground shadow opacity| Opacity of the ground shadow.                            |
| Grid unit            | Millimeters, centimeters, meters, inches, or feet.      |
| Grid spacing         | Spacing expressed in the selected unit (0.1–100).       |
| Opacity              | Overall grid opacity.                                    |
| Grid color           | Color of the grid lines.                                 |

The grid is shown automatically whenever a document is open and the overlay is
enabled. It regenerates from the viewport's visible area as you navigate, and
the shadow updates on geometry changes (debounced by 150 ms).

FreeCAD's internal geometry coordinates are millimeters; the selected grid unit
is converted to millimeters internally, so a spacing of `1` with **Inches**
means 25.4 FreeCAD units.

## Requirements

- FreeCAD 26.x or 27.x (the current validation targets are 26.3 and 27.1)
- FreeCAD's bundled PySide compatibility module, PySide2, or PySide6 for the
  settings dialog
- `pivy` (Coin3D) for the scene-graph nodes

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
