"""Smoke test an extension ZIP in Blender without modifying user preferences.

PowerShell, from the repository root:
  $Blender = "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"
  python tools/build_extension.py --blender $Blender
  & $Blender --background --factory-startup --python tests\\blender_extension_smoke.py

The test imports __init__.py directly from the ZIP's extracted contents. It
verifies package loading and Blender operator registration, but NOT the
interactive Preferences "Install from Disk" user interface.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import zipfile

import bpy


ROOT = Path(__file__).resolve().parents[1]
manifest = tomllib.loads((ROOT / "blender_manifest.toml").read_text(encoding="utf-8"))
archive = ROOT / "dist" / f"{manifest['id']}-{manifest['version']}.zip"
if "--" in sys.argv:
    extras = sys.argv[sys.argv.index("--") + 1:]
    if extras:
        archive = Path(extras[0]).resolve()

if not archive.is_file():
    raise FileNotFoundError(f"Build the ZIP first: {archive}")

with tempfile.TemporaryDirectory(prefix="vct-install-smoke-") as directory:
    package = Path(directory) / manifest["id"]
    package.mkdir()
    with zipfile.ZipFile(archive) as archive_file:
        if set(archive_file.namelist()) != {"__init__.py", "blender_manifest.toml", "LICENSE"}:
            raise AssertionError("Unexpected extension package contents")
        archive_file.extractall(package)

    spec = importlib.util.spec_from_file_location(
        manifest["id"], package / "__init__.py",
        submodule_search_locations=[str(package)],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if tuple(module.bl_info["version"]) != tuple(map(int, manifest["version"].split("."))):
        raise AssertionError("The packaged add-on version does not match the manifest")

    module.register()
    try:
        assert hasattr(bpy.types.Scene, "vct_settings")
        assert hasattr(bpy.types, "VCT_PT_main")
        mesh = bpy.data.meshes.new("VCT Extension Smoke")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        obj = bpy.data.objects.new("VCT Extension Smoke", mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        assert not mesh.color_attributes, "Package registration modified a mesh"
        result = bpy.ops.vct.create_attribute()
        assert result == {'FINISHED'}, f"Package Create Attribute failed: {result}"
        assert len(mesh.color_attributes) == 1
        assert mesh.color_attributes.active_color.domain == 'CORNER'
        assert bpy.context.scene.vct_settings is not None
    finally:
        module.unregister()

    assert not hasattr(bpy.types.Scene, "vct_settings"), "Unregister leaked Scene properties"
    print("VCT EXTENSION PACKAGE SMOKE: PASS")
