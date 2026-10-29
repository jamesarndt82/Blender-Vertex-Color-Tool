"""Phase 2 structural regression checks; Blender runtime smoke remains mandatory."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] /
          "vertex_color_toolbox_blender_5_2.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def body(name):
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SOURCE, node)
    raise AssertionError("Missing function " + name)


class PerformanceAndUX(unittest.TestCase):
    def test_bulk_object_mode_processing(self):
        self.assertIn('source.data.foreach_get("color", values)',
                      body("_apply_adjust_preview"))
        self.assertIn('temp.data.foreach_set("color", values)',
                      body("_apply_adjust_preview"))
        self.assertIn('source.data.foreach_set("color", values)',
                      body("_commit_adjust_preview"))

    def test_linear_corner_collection(self):
        selected = body("get_selected_loops")
        self.assertIn("for face in bm.faces:", selected)
        self.assertIn("for loop in face.loops:", selected)
        self.assertNotIn("loops_for_vertex", selected)

    def test_full_strength_fast_path_preserves_alpha(self):
        fill = body("fill_selection_with_color")
        self.assertIn("if strength >= 1.0:", fill)
        self.assertIn("old_alpha", fill)
        self.assertIn("color_to_bmesh(attr, target)", fill)

    def test_delete_confirmation_and_single_mode_control(self):
        node = next(n for n in TREE.body
                    if isinstance(n, ast.ClassDef)
                    and n.name == "VCT_OT_delete_attribute")
        self.assertIn("invoke_confirm", ast.get_source_segment(SOURCE, node))
        panel = ast.get_source_segment(SOURCE, next(n for n in TREE.body
                                                   if isinstance(n, ast.ClassDef)
                                                   and n.name == "VCT_PT_main"))
        self.assertEqual(panel.count('"vct.enter_face_mode"'), 1)
        self.assertEqual(panel.count('"vct.enter_vertex_mode"'), 1)
        self.assertNotIn('row.operator("vct.set_edit_mode"', panel)
        self.assertIn("paint_ready", panel)


if __name__ == "__main__":
    unittest.main()
