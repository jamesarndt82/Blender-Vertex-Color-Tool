"""Dependency-free source checks. Runtime behavior is tested in Blender smoke."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] /
          "vertex_color_toolbox_blender_5_2.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function_body(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node)
    raise AssertionError("Missing required function: " + name)


class Phase1SourceContractTests(unittest.TestCase):
    def test_registration_does_not_touch_current_mesh_or_viewport(self):
        registration = function_body("register")
        self.assertNotIn("color_attributes.new(", registration)
        self.assertNotIn("shading.type =", registration)
        self.assertNotIn("bpy.app.timers.register", registration)
        self.assertNotIn("subscribe_rna", SOURCE)
        self.assertNotIn("_set_default_viewport_display", SOURCE)

    def test_material_preview_only_uses_owned_material(self):
        self.assertIn("bpy.data.materials.new(_VCT_MATERIAL_PREVIEW_MATERIAL_NAME)", SOURCE)
        self.assertNotIn("bpy.data.materials.get(_VCT_MATERIAL_PREVIEW_MATERIAL_NAME)", SOURCE)
        self.assertNotIn("obj.data.materials.append(preview_mat)", SOURCE)
        self.assertNotIn("obj.data.materials.clear()", SOURCE)
        self.assertIn("settings.material_preview_material", function_body("_sync_material_preview_attribute"))
        self.assertIn("existing.node_tree.nodes.get", function_body("_ensure_material_preview_material"))

    def test_save_load_undo_recovery(self):
        for name in ("_vct_save_pre", "_vct_load_post", "_vct_undo_post",
                     "_vct_redo_post", "_cleanup_all_previews"):
            function_body(name)
        self.assertIn("_cleanup_all_previews()", function_body("unregister"))
        self.assertIn("settings.preview_object", function_body("_preview_target_object"))
        self.assertIn("settings.material_preview_object",
                      function_body("_preview_material_target_object"))

    def test_live_preview_has_no_ambiguous_layer_cleanup(self):
        self.assertNotIn("for attr in list(mesh.color_attributes)",
                         function_body("_start_adjust_preview"))
        self.assertIn("settings.preview_active", function_body("fill_selection_with_color"))
        self.assertIn("mesh.color_attributes.get(temp_name)",
                      function_body("_remove_preview_attribute"))


if __name__ == "__main__":
    unittest.main()
