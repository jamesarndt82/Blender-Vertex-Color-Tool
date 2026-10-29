# Vertex Color Toolbox (Blender 5.2+)

<table>
  <tr>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/005c4e12-c085-449d-ae46-1e1383780a3a"
           height="340"
           alt="Vertex Color Toolbox Panel">
    </td>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/d3204e13-5084-4ecb-99ef-1460623a49c9"
           height="340"
           alt="Vertex Color Toolbox Viewport">
    </td>
  </tr>
</table>

A compact Blender add-on for working with **Color Attributes (vertex colors)** directly on mesh objects.

The workflow is inspired by the simplicity of **3ds Max VertexPaint**: choose a color, switch between Face or Vertex selection with one control, adjust strength, and fill the current selection.

The toolbox uses Blender's modern **Color Attribute** system and is designed primarily for game-art workflows such as vertex tinting, masks, variation, gradients, and shader data.

## Requirements

- **Blender 5.2 or newer** (tested with Blender 5.2.3 LTS)
- A mesh object, with the **Face Corner** Color Attribute domain
- The default color storage is **Byte Color**; Float Color is also supported

The toolbox does **not** automatically modify meshes or viewport settings when enabled or when objects are selected. If a mesh has no suitable Color Attribute, select **New** in the VColor sidebar.

## Installation

### Official Blender Extensions (after publication)

Once Blender's moderators approve the add-on, open **Edit → Preferences → Get Extensions**, search for **Vertex Color Toolbox**, and choose **Install**. Enable it if necessary. For future updates, use **Get Extensions → Check for Updates**; extensions do **not** update automatically.

Until the listing is approved, install the development ZIP using the instructions below.

### Install the ZIP locally (available now)

1. Download the `vertex_color_toolbox-2.5.1.zip` build artifact from the [latest development CI run](https://github.com/jamesarndt82/Blender-Vertex-Color-Tool/actions/workflows/source-checks.yml) or build it locally using the commands below.
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Open the upper-right menu and choose **Install from Disk**.
4. Select the downloaded **ZIP without extracting it**. Enable the extension if needed.
5. Open a 3D Viewport, press **N**, and select the **VColor** tab.

**Locally installed ZIPs belong to a local extension repository and do not receive official-platform update notifications.** Until the official listing is live, repeat the local installation process for newer versions. See the [Blender manual](https://docs.blender.org/manual/en/5.2/editors/preferences/extensions.html) for update behavior.

### Upgrading from the older standalone add-on

If you previously installed `vertex_color_toolbox_blender_5_2.py`:

1. Save your work and finish or cancel any live previews.
2. In **Edit → Preferences → Add-ons**, disable and remove the old standalone **Vertex Color Toolbox**.
3. Restart Blender.
4. Install the extension ZIP as described above.

Do not enable both the legacy Python-file add-on and the ZIP extension at the same time: they register the same operators and sidebar panel.

### Legacy installation (.py file)

The single-file installer remains available for existing workflows. In **Edit → Preferences → Add-ons**, open the menu, choose **Install from Disk**, select `vertex_color_toolbox_blender_5_2.py`, then enable **Vertex Color Toolbox**. **New installations should use the ZIP.**

## Where to Find It

In the 3D Viewport:

1. Press **N** to open the Sidebar.
2. Select the **VColor** tab.
3. Open **Vertex Color Toolbox**.

## Quick Start

1. Select a mesh object.
2. Open the **VColor** panel.
3. If needed, click **+** beside the Color Attribute selector to create a `Color` attribute.
4. Choose **Face** or **Vertex** to enter Edit Mode.
5. Click the native Blender color swatch and choose a color.
6. Set the **Strength**.
7. Select faces or vertices.
8. Click **Fill Selected Faces** or **Fill Selected Vertices**.

The Face/Vertex buttons now also enter Edit Mode if needed. If an operation cannot run, its control is disabled, and the panel displays the next required step.

To see vertex colors directly, open **Display → Solid Colors**. Enabling the add-on will not change your viewport shading.

## Face and Vertex Modes

The toolbox uses a single underlying **Face Corner Color Attribute** for both workflows.

### Face Mode

**Face Mode** switches Blender into Edit Mode with Face Select enabled.

Filling selected faces assigns the chosen color to all corners of those faces.

This is useful for:

* Hard color boundaries
* Low-poly color blocking
* Face masks
* Material or shader IDs
* Stylized color variation

### Vertex Mode

**Vertex Mode** switches Blender into Edit Mode with Vertex Select enabled.

Filling selected vertices modifies the corresponding face-corner colors attached to those vertices.

Colors naturally interpolate across polygons, making this useful for:

* Gradients
* Vertex masks
* Terrain blending
* Foliage variation
* Shader effects

The toolbox follows Blender's actual mesh selection mode, so switching between Face and Vertex selection using Blender's normal controls also updates how the tools behave.

## Working Color

The **Color** control uses Blender's native color swatch and color picker.

No custom color picker is used.

### Strength

**Strength** controls how strongly the selected color affects the existing vertex color.

* `100%` completely replaces the existing color.
* `50%` blends halfway toward the selected color.
* Lower values allow colors to be built up gradually.

This provides a simple VertexPaint-style blending workflow without requiring separate color-layer blend modes.

## Fill Selection

**Fill Selection** applies the current Working Color to the selected geometry using the current Strength.

In:

* **Face Mode**, selected faces are affected.
* **Vertex Mode**, selected vertices are affected.

## Sample Selected

**Sample Selected** reads an existing color from the mesh and copies it into the Working Color.

In Face Mode, the selected face is sampled.

In Vertex Mode, the selected vertex and its connected face-corner colors are sampled.

## Selection

The **Selection** section is collapsible and contains helpers for working with existing colors.

### Select Similar

Select geometry whose color is similar to the current Working Color.

### Add Similar

Adds matching geometry to the current selection instead of replacing it.

### Tolerance

Controls how closely colors must match.

### Grow / Shrink

Expands or contracts the current mesh selection using Blender's standard selection tools.

### Invert / Clear

Quick controls for inverting or clearing the current selection.

## Palette

The **Palette** section provides reusable color swatches.

Available controls include:

* **Add Current** - adds the current Working Color to the palette.
* **Remove** - deletes the selected palette entry.
* **Use** - copies the selected palette color into the Working Color.
* **Fill Selection** - immediately applies the selected palette color to the mesh.
* **Create Starter Palette** - creates a basic set of useful colors.

Palette entries can also be renamed and edited.

## Adjust Colors

The **Adjust Colors** section provides non-destructive Hue, Saturation, and Value adjustments.

Available controls:

* **Hue**
* **Saturation**
* **Value**
* **Live Preview**
* **Apply**
* **Cancel**
* **Reset**

### Live Preview

Click **Start Live Preview** to see color adjustments before committing them. While previewing, click **Commit Preview** to keep the result or **Cancel** to discard it. Without a preview, **Apply Adjustment** performs a one-shot adjustment.

The original Color Attribute remains untouched until **Apply** is pressed.

**Cancel** restores the original colors.

Slider changes are recalculated from the original color data rather than repeatedly modifying the previous preview, preventing cumulative adjustment errors.

### Object Mode Adjustments

Adjust Colors can also be used directly in **Object Mode**.

In Object Mode:

> Hue, Saturation, and Value adjustments affect the entire active Color Attribute.

This is useful for quickly changing the overall color treatment of an object.

### Edit Mode Adjustments

In Edit Mode:

> Adjustments affect only the currently selected faces or vertices.

The Adjust Colors panel displays the current adjustment scope so it is clear whether the entire object or only selected geometry will be modified.

## Display

The **Display** section provides two primary vertex-color viewing modes.

### Solid Colors

Displays the active Color Attribute directly in Blender's Solid View.

This does not require a material or shader setup.

### Material Preview

Material Preview normally renders the object's material and does not automatically display vertex colors.

The toolbox can temporarily create a preview material that reads the active Color Attribute and switches the viewport into Material Preview.

This allows vertex colors to be viewed with Blender's Material Preview lighting without permanently modifying the object's production materials.

Turning Material Preview off restores the original material assignments. For safety, an object must already have a material slot to use this mode; otherwise, use **Solid Colors**. The preview does not add slots to shared mesh data.

### Flat Lighting

When using **Solid Colors**, Flat Lighting can be toggled on for an unlit-style view of the vertex colors.

Turning Flat Lighting off restores the viewport's previous Studio or MatCap lighting mode.

## Color Attributes

The Color Attribute selector at the top of the toolbox lets you switch between Color Attributes stored on the mesh.

Controls beside the selector allow you to:

* Create a new Color Attribute
* Delete the active Color Attribute after confirming the operation
* Switch between existing Color Attributes

The toolbox keeps its active Color Attribute synchronized with Blender's native **Object Data Properties → Color Attributes** panel.

Deleting Color Attributes directly through Blender's native panel is also handled safely.

## First-Time Setup (Explicit)

If a mesh does not have a compatible attribute, click the **+** icon next to the attribute selector. The default is:

```text
Name: Color
Domain: Face Corner
Storage: Byte Color
Default: White
```

The toolbox does **not** create attributes when selecting objects, opening files, or enabling the add-on. It does not alter viewport shading until you choose a Display mode.

### Temporary preview safety

- **Material Preview** uses a newly created, temporary material instead of overwriting an existing material with a matching name.
- Previewed material slots are changed at the **object** level, protecting other objects sharing the same mesh. Meshes without a material slot should use Solid Colors.
- **Live HSV Preview** creates a temporary Color Attribute. Apply commits the result; Cancel removes the temporary attribute without changing the source.
- Saving a Blender project automatically ends both preview types and restores original materials, so temporary preview data is not intentionally saved into the project.
- Undo, redo, and loading a project trigger recovery of any tracked temporary preview state.

### Testing

GitHub Actions compiles the add-on, checks both extension packaging and numerical/color behavior, and builds a GPL ZIP. These checks do **not** replace testing inside Blender. For Blender 5.2+ runtime integration, run:

```bash
blender --background --factory-startup --python tests/blender_phase1_smoke.py
blender --background --factory-startup --python tests/blender_phase2_smoke.py
# After building the extension ZIP:
blender --background --factory-startup --python tests/blender_extension_smoke.py
# Optional timing-only benchmark:
blender --background --factory-startup --python tests/blender_phase2_benchmark.py
```

The Phase 1 smoke test covers explicit attribute setup, shared meshes, material restoration after object renaming, HSV preview cancellation, and saving during previews.

The Phase 2 smoke test covers Byte/Float attribute initialization, full-strength face and vertex fills, alpha preservation, bulk HSV preview and commit accuracy. The extension smoke test loads the packaged add-on, verifies registration and basic operation, then unregisters cleanly.

On Windows PowerShell, replace `blender` with `& "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"` and run each command separately.

### Version 2.5.1 (development)

This iteration preserves the Phase 2 UI and fill improvements, and adds:

- Vectorized NumPy HSV color conversion for Object Mode previews (128+ face corners), with scalar `colorsys` fallback for small meshes or environments without NumPy
- Float64 intermediate color math with Float32 storage, preserving the alpha channel
- Coalescing repeated identical slider notifications without suppressing manual preview refreshes
- Numerical regression tests comparing scalar and vectorized HSV math, including black, white, grayscale, primaries, byte-resolution and random colors
- Expanded Blender smoke tests for Float Color HSV accuracy
- A configurable benchmark that measures both the scalar baseline and optimized preview at approximately 100K and 1M face corners

### Performance benchmark

Use the `VCT_BENCH_GRID` environment variable to choose grid size (number of quad faces is `grid * grid`). The standard 160 grid produces 102,400 face corners; the 500 grid produces 1,000,000.

In Windows PowerShell, from the repository root:

```powershell
$Blender = "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"
$env:VCT_BENCH_GRID = "160"
& $Blender --background --factory-startup --python tests\\blender_phase2_benchmark.py
$env:VCT_BENCH_GRID = "500"
& $Blender --background --factory-startup --python tests\\blender_phase2_benchmark.py
Remove-Item Env:VCT_BENCH_GRID
```

Each test reports median timings and the measured scalar-versus-optimized speedup. These are **not** hardware-independent performance guarantees. Run the Blender Phase 2 smoke test after pulling new changes before relying on 2.5.1 for production assets.

## Advanced

The **Advanced** section exposes settings that normally do not need to be changed during regular painting.

These include:

* Active attribute domain
* Storage type
* New Color Attribute name
* Byte Color / Float Color storage
* Affect Alpha
* Match Alpha

For most game-art workflows, the default **Face Corner + Byte Color** configuration is recommended.

## Why Face Corner Colors?

Blender supports both Vertex and Face Corner Color Attribute domains.

Vertex Color Toolbox uses **Face Corner** storage because it can support both:

* Hard per-face color boundaries
* Smooth interpolated vertex-color gradients

This allows Face Mode and Vertex Mode to work on the same Color Attribute instead of maintaining separate color datasets.

## Typical Game-Art Uses

Vertex Color Toolbox is useful for authoring data such as:

* Vertex tint
* Material blending masks
* Foliage variation
* Ambient occlusion
* Dirt or damage masks
* Terrain blending
* Wind or animation masks
* Shader parameters
* Stylized low-poly coloring

## Notes

* The toolbox is built around Blender's modern **Color Attributes** system.
* New attributes use the **Face Corner** domain by default.
* **Byte Color** is the default storage type.
* The native Blender color picker is used for color selection.
* Face and Vertex operations modify the same underlying Color Attribute.
* Material Preview uses an add-on-owned temporary material and restores the object's original material assignments when disabled or when the file is saved.
* Live HSV Preview uses temporary color data until applied, and is cancelled on save or recovery events.
* The toolbox includes protection against invalid active Color Attribute references when attributes are deleted externally through Blender's native interface.
* Blender 5.2+ is the declared API target; runtime validation on each Blender patch release is still required.

## License

**GPL-3.0-or-later** — see [LICENSE](LICENSE).

Copyright © 2026 James Arndt.

Versions previously distributed under MIT remain available under their original terms; the historical MIT license text is archived at [packaging/MIT-license-prior-to-2.5.1.txt](packaging/MIT-license-prior-to-2.5.1.txt). The current source code and all newly built extension ZIPs use GPL-3.0-or-later.

## Build and submit to Blender Extensions

Build a single ZIP from the existing add-on source:

```powershell
cd D:\Projects\Blender-Vertex-Color-Tool
git switch development
git pull
$Blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
python tools/build_extension.py --blender $Blender
& $Blender --background --factory-startup --python tests\blender_extension_smoke.py
```

The resulting file is `dist/vertex_color_toolbox-2.5.1.zip`. The builder validates the GPL manifest, source SPDX header, version match, full GPL license, and packaged source. It normalizes Windows CRLF and Unix LF line endings into a consistent package. With `--blender` it also runs Blender's official extension validator and packager. The extension smoke test checks package load/unload, but does **not** substitute for testing an interactive install in Blender's Preferences.

After the package smoke test, install the ZIP through **Get Extensions → Install from Disk** and verify the sidebar (Face and Vertex tools, HSV preview, palette, display modes) in a fresh Blender session. For public distribution, submit this same ZIP at [Blender Extensions](https://extensions.blender.org/submit/) using your Blender ID. Provide a description, up-to-date screenshots of version 2.5.1, and any metadata requested by reviewers. Blender moderates the submission before publication. No workflow submits or publishes the extension automatically.

A copy-ready listing description, screenshot checklist, and reviewer-preparation instructions are available in [the Blender Extensions submission guide](docs/BLENDER_EXTENSIONS_SUBMISSION.md).

GitHub Actions builds the same GPL-licensed ZIP for the `development` branch. The GitHub release workflow only prepares an unpublished draft after an explicit version tag.
