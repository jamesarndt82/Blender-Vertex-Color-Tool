# Vertex Color Toolbox (Blender 5.2)

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

The workflow is inspired by the simplicity of **3ds Max VertexPaint**: choose a color, choose whether you are working with faces or vertices, control the strength, and fill the current selection.

The toolbox uses Blender's modern **Color Attribute** system and is designed primarily for game-art workflows such as vertex tinting, masks, variation, gradients, and shader data.

## Requirements

* **Blender 5.2**
* Mesh objects
* Uses **Face Corner Color Attributes**
* Tested with **Byte Color** storage by default

If the selected mesh does not already contain a compatible Color Attribute, the toolbox automatically creates a default `Color` attribute.

## Installation

### Install from `.py` File

1. Download the **vertex_color_toolbox_blender_5_2.py** file.
2. In Blender, open **Edit → Preferences → Add-ons**.
3. Open the Add-ons menu and choose **Install from Disk**.
4. Select the `.py` file.
5. Enable **Vertex Color Toolbox** in the Add-ons list.

## Where to Find It

In the 3D Viewport:

1. Press **N** to open the Sidebar.
2. Select the **VColor** tab.
3. Open **Vertex Color Toolbox**.

## Quick Start

1. Select a mesh object.
2. Open the **VColor** panel.
3. A `Color` attribute is created automatically if the mesh does not already contain a compatible Color Attribute.
4. Choose **Face Mode** or **Vertex Mode**.
5. Click the native Blender color swatch and choose a color.
6. Set the **Strength**.
7. Select faces or vertices.
8. Click **Fill Selection**.

The viewport is automatically configured to display the active Color Attribute in Solid View.

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

Live Preview shows color adjustments on the mesh before they are committed.

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

Turning Material Preview off restores the original material assignments.

### Flat Lighting

When using **Solid Colors**, Flat Lighting can be toggled on for an unlit-style view of the vertex colors.

Turning Flat Lighting off restores the viewport's previous Studio or MatCap lighting mode.

## Color Attributes

The Color Attribute selector at the top of the toolbox lets you switch between Color Attributes stored on the mesh.

Controls beside the selector allow you to:

* Create a new Color Attribute
* Delete the active Color Attribute
* Switch between existing Color Attributes

The toolbox keeps its active Color Attribute synchronized with Blender's native **Object Data Properties → Color Attributes** panel.

Deleting Color Attributes directly through Blender's native panel is also handled safely.

## Automatic Setup

When the toolbox encounters a mesh without a compatible Color Attribute, it automatically creates:

```text
Name: Color
Domain: Face Corner
Storage: Byte Color
Default: White
```

The viewport is also configured to display Color Attributes automatically.

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
* Material Preview uses a temporary preview material and restores the object's original materials when disabled.
* Live HSV Preview uses temporary color data until the adjustment is applied.
* The toolbox includes protection against invalid active Color Attribute references when attributes are deleted externally through Blender's native interface.

## License

Add your preferred license here.

For a small open-source Blender add-on, the **MIT License** is a common option.
