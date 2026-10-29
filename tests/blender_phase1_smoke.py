"""Blender 5.2+ integration smoke test.

Run from a clean Blender session:
  blender --background --factory-startup --python tests/blender_phase1_smoke.py

This requires Blender and must NOT be mistaken for the Python-only CI checks.
"""
import importlib.util
from pathlib import Path
import tempfile

import bpy


ADDON = Path(__file__).resolve().parents[1] / "vertex_color_toolbox_blender_5_2.py"
spec = importlib.util.spec_from_file_location("vct_phase1_smoke_addon", ADDON)
vct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vct)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


vct.register()
try:
    scene = bpy.context.scene
    mesh = bpy.data.meshes.new("VCT Smoke Shared Mesh")
    mesh.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()

    target = bpy.data.objects.new("VCT Smoke Target", mesh)
    linked = bpy.data.objects.new("VCT Smoke Linked Instance", mesh)
    scene.collection.objects.link(target)
    scene.collection.objects.link(linked)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)

    # Merely enabling the extension or selecting the mesh must not mutate it.
    require(not mesh.color_attributes, "Attribute created without user action")

    require(bpy.ops.vct.create_attribute() == {'FINISHED'},
            "Create Color Attribute failed")
    require(len(mesh.color_attributes) == 1, "Explicit setup made wrong number of layers")
    attribute = mesh.color_attributes.active_color
    require(attribute is not None and attribute.domain == 'CORNER',
            "Color layer is not Face Corner")

    # Material Preview must refuse to insert a shared-mesh material slot.
    ok, _ = vct._toggle_material_preview(bpy.context)
    require(not ok and len(mesh.materials) == 0,
            "Material Preview changed a mesh with no slots")

    base_material = bpy.data.materials.new("VCT Smoke Original Material")
    mesh.materials.append(base_material)
    original_link_mode = target.material_slots[0].link
    ok, message = vct._toggle_material_preview(bpy.context)
    require(ok, "Material Preview did not start: " + message)
    preview_material = scene.vct_settings.material_preview_material
    require(preview_material is not None, "Temporary material not owned by addon")
    require(target.material_slots[0].material == preview_material,
            "Preview material not active on target")
    require(linked.material_slots[0].material == base_material,
            "Preview changed another object sharing the mesh")

    target.name = "VCT Smoke Target Renamed"
    ok, message = vct._restore_material_preview(bpy.context)
    require(ok, "Material restoration failed after object rename: " + message)
    require(target.material_slots[0].link == original_link_mode,
            "Original material link mode not restored")
    require(target.material_slots[0].material == base_material,
            "Original material not restored")
    require(linked.material_slots[0].material == base_material,
            "Linked object's material was changed")

    # A live HSV preview must leave the source untouched until Apply.
    attribute = mesh.color_attributes.active_color
    attribute.data[0].color = (0.5, 0.2, 0.1, 1.0)
    before = tuple(attribute.data[0].color)
    settings = scene.vct_settings
    settings.adjust_hue = 0.15
    ok, message = vct._start_adjust_preview(bpy.context)
    require(ok, "HSV preview failed: " + message)
    require(settings.preview_active and settings.preview_temp_name,
            "Preview not tracked")
    require(tuple(mesh.color_attributes.get(settings.preview_source_name).data[0].color) == before,
            "HSV preview edited source instead of a temporary layer")

    ok, message = vct._cancel_adjust_preview(bpy.context)
    require(ok, "HSV cancel failed: " + message)
    require(not settings.preview_active, "Preview still marked active after cancel")
    require(tuple(mesh.color_attributes.active_color.data[0].color) == before,
            "HSV cancel did not preserve original colors")

    # Saving must roll back both preview types; the file must be safe to open.
    ok, message = vct._toggle_material_preview(bpy.context)
    require(ok, "Material preview failed before save test: " + message)
    ok, message = vct._start_adjust_preview(bpy.context)
    require(ok, "HSV preview failed before save test: " + message)
    with tempfile.TemporaryDirectory() as directory:
        filepath = str(Path(directory) / "vct-smoke.blend")
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
        require(Path(filepath).exists(), "Save did not create a blend file")
    require(not settings.preview_active and not settings.material_preview_active,
            "Saving preserved transient preview state")
    require(all(not x.name.startswith(vct._PREVIEW_PREFIX)
                for x in mesh.color_attributes),
            "Temporary attribute survived save")
    require(target.material_slots[0].material == base_material,
            "Saving did not restore original material")

    print("VCT PHASE 1 BLENDER SMOKE: PASS")
finally:
    vct.unregister()
