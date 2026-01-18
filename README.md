# Vertex Color Tools (Blender 5.0)
A lightweight Blender add-on for editing **Color Attributes (vertex colors)** in **Edit Mode**. Supports applying colors to **selected faces** or **selected vertices (masking)**, plus a simple **palette** and **color picking from selection**.

## Requirements
* **Blender 5.0** (tested)
* Mesh objects with **Color Attributes** (the add-on will create one if missing)

## Installation
### Option A: Install from a `.py` file
1. Download `Vertex_Color_Tool.py` (or whatever you named the script).
2. In Blender: **Edit → Preferences → Add-ons**
3. Click **Install…**
4. Select the `.py` file and click **Install Add-on**
5. Enable the add-on by checking the box next to **Vertex Color Tools**

### Option B: Install from a `.zip` (recommended for releases)
1. Download the `.zip` release from GitHub.
2. In Blender: **Edit → Preferences → Add-ons**
3. Click **Install…**
4. Select the `.zip` and click **Install Add-on**
5. Enable the add-on by checking the box next to **Vertex Color Tools**

## Where to Find It
* 3D Viewport → press **N** (Sidebar)
* Open the **Vertex Colors** tab/panel

## Quick Start
1. Select a mesh object and go to **Edit Mode**.
2. In the add-on panel:

   * Set your layer name (default: `Col`)
   * Click **Set** to create/activate the color attribute (if needed)
3. Click **Show in Edit Mode** to make vertex colors visible in the viewport.
4. Choose a **Target**:

   * **Faces**: applies to selected faces only
   * **Vertices**: applies to selected vertices (useful for masking)
   * **Auto**: uses faces if any faces are selected, otherwise vertices
5. Pick a color and click **Apply**.

## Viewing Vertex Colors in Edit Mode
To display colors while staying in Edit Mode:

* Click **Show in Edit Mode** (or **Show + Solid** to force Solid shading)

This sets the viewport to show the **active color attribute**.

## Tools
### Apply / Modify
* **Apply**: writes the selected color to the current selection (faces/verts based on Target)
* **Multiply**: tints existing vertex colors on the selection
* **Invert**: inverts RGB on the selection (alpha unchanged)

### Color Picker (from geometry)
* Eyedropper next to **Color**: samples the average vertex color from the current selection and sets it as the active color.
* **Pick From Selection → Add**: samples the selection and adds it as a new palette swatch.

### Palette
* **+**: add a new swatch from the current Fill Color
* **-**: remove selected swatch
* **Up/Down**: reorder swatches
* **Apply Palette**: applies the selected swatch to geometry
* **To Fill**: copies selected swatch into the Fill Color
<img width="1918" height="1020" alt="Blender_Vertex_Color_Tool" src="https://github.com/user-attachments/assets/6d4d5c0b-7e06-42ff-9708-3096a6cebd09" />

<img width="343" height="677" alt="Blender_Vertex_Color_Tool_B" src="https://github.com/user-attachments/assets/a92ca68c-fd7c-494a-8a38-267d80a59c29" />

## Notes
* The add-on uses **Color Attributes** on the **CORNER (loop)** domain (standard for modern Blender vertex color workflows).
* Colors picked in the UI are handled to match on-mesh display as closely as possible.

## License
Add your preferred license here (MIT is common for small Blender add-ons).
