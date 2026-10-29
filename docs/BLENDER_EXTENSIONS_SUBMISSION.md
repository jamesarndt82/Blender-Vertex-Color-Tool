# Blender Extensions submission — Vertex Color Toolbox 2.5.1

This document is a ready-to-use submission checklist and listing draft.
The public listing is **not yet published**. Keep the package on the
`development` branch until the Blender validation and hands-on installation
checks pass.

## Listing details

- **Name:** Vertex Color Toolbox
- **Tagline:** Fast vertex color painting for mesh artists
- **Version:** 2.5.1
- **Type:** Add-on
- **Category:** Mesh
- **Minimum Blender version:** 5.2.0
- **License:** GPL-3.0-or-later
- **Source and support:** https://github.com/jamesarndt82/Blender-Vertex-Color-Tool
- **Special permissions:** None declared

## Description (copy into Blender Extensions listing)

Vertex Color Toolbox provides a compact workflow for painting and adjusting
mesh Color Attributes directly in the Blender 3D Viewport. It is designed for
artists creating vertex tints, masks, surface variation, stylized low-poly
colors, and other game-art data.

Open the **VColor** tab in the 3D Viewport sidebar. Select an existing
Face Corner Color Attribute or click **New** to create one. Choose **Face**
or **Vertex** selection, pick a working color, adjust the strength, and
fill the selected geometry.

Main features:

- Paint selected faces or vertices with adjustable color strength
- Sample existing face or vertex colors
- Select mesh elements by matching color, with tolerance controls
- Save and reuse working colors using a palette
- Adjust Hue, Saturation, and Value with a cancellable live preview
- Use Object Mode adjustments across the entire active Color Attribute,
  or Edit Mode adjustments on selected geometry only
- Inspect colors in Solid View or use temporary Material Preview
- Work with Byte Color and Float Color Face Corner attributes

The add-on does not create attributes or change viewport shading merely
because it is enabled or an object is selected. Temporary previews are
restored or cancelled when saving, and the add-on does not require access
to online services.

## Changelog / What's New (version 2.5.1)

- Simplified the main panel with one Face/Vertex selection control
- Improved contextual operation availability and setup instructions
- Added confirmation before deleting Color Attributes
- Improved selection traversal and full-strength painting performance
- Accelerated Object Mode HSV preview using vectorized conversion
- Improved preview cleanup and temporary material restoration
- Added Blender 5.2+ integration and performance regression tests

## Submission preparation

1. Pull the latest `development` branch in your local repository.
2. Run the commands below using **Blender 5.2.3 LTS**.
3. Install the resulting ZIP in a clean Blender session:
   **Edit → Preferences → Get Extensions → Install from Disk**.
4. Verify enabling and disabling, Face/Vertex editing, palette, selection
   helpers, HSV preview/apply/cancel, and display modes.
5. Check that old standalone `.py` installs have been disabled/removed,
   to avoid duplicate operator and panel registrations.
6. Capture fresh **version 2.5.1** screenshots: the main VColor panel,
   representative painted mesh, expanded Adjust Colors, and palette.
   Avoid Blender branding/logos in submission thumbnails.
7. Read https://extensions.blender.org/terms-of-service/ and upload the
   validated ZIP at https://extensions.blender.org/submit/ using Blender ID.
8. Respond to reviewer comments before publication.

### PowerShell validation

```powershell
cd D:\Projects\Blender-Vertex-Color-Tool
git switch development
git pull
$Blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
python tools/build_extension.py --blender $Blender
& $Blender --background --factory-startup --python tests\blender_extension_smoke.py
```

Expected package: `dist\vertex_color_toolbox-2.5.1.zip`.

The test script proves the packaged add-on can register and unregister
headlessly; it **does not** replace the interactive installation test.
No files are submitted to Blender automatically.

## Updating after platform acceptance

Users should install from Blender's **Get Extensions** repository.
Extensions from the official repository do not update automatically;
users must check for and install updates. ZIPs installed from disk
are managed locally and are not subscribed to official updates.

## Notes

- The GitHub release workflow creates drafts only when a maintainer pushes
  a matching version tag. Do not publish/tag before the review is complete.
- The repository had previously distributed MIT-licensed versions.
  The archival license text remains at
  `packaging/MIT-license-prior-to-2.5.1.txt`, and does not change the
  GPL license of version 2.5.1.
