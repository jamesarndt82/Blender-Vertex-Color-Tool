"""Standard-library packaging tests; no Blender installation required."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "build_extension.py"
MANIFEST = ROOT / "blender_manifest.toml"
SOURCE = ROOT / "vertex_color_toolbox_blender_5_2.py"
EXPECTED = {"__init__.py", "blender_manifest.toml", "LICENSE"}


class ExtensionPackageTests(unittest.TestCase):
    def test_manifest_matches_python_source(self):
        metadata = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(metadata["id"], "vertex_color_toolbox")
        self.assertEqual(metadata["type"], "add-on")
        self.assertEqual(metadata["blender_version_min"], "5.2.0")
        self.assertEqual(metadata["license"], ["SPDX:GPL-3.0-or-later"])
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        bl_info = next(
            ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets)
        )
        self.assertEqual(metadata["version"], ".".join(map(str, bl_info["version"])))
        self.assertTrue(
            SOURCE.read_text(encoding="utf-8").startswith(
                "# SPDX-License-Identifier: GPL-3.0-or-later"
            )
        )
        self.assertTrue((ROOT / "LICENSE").read_text(encoding="utf-8").startswith(
            "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"
        ))

    def test_zip_is_valid_unchanged_source_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "first", Path(directory) / "second"
            for out in (left, right):
                subprocess.run(
                    [sys.executable, str(BUILDER), "--output-dir", str(out)],
                    cwd=ROOT, check=True, capture_output=True, text=True,
                )
            archives = list(left.glob("*.zip"))
            self.assertEqual(len(archives), 1)
            archive = archives[0]
            subprocess.run(
                [sys.executable, str(BUILDER), "--verify", str(archive)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), EXPECTED)
                self.assertEqual(z.read("__init__.py"), SOURCE.read_bytes())
                self.assertEqual(z.read("LICENSE"), (ROOT / "LICENSE").read_bytes())
                self.assertEqual(z.testzip(), None)
            second = right / archive.name
            self.assertEqual(archive.read_bytes(), second.read_bytes(),
                             "ZIP must reproduce identically")

    def test_bad_zip_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.zip"
            with zipfile.ZipFile(invalid, "w") as z:
                z.writestr("README.txt", "Not an extension")
            proc = subprocess.run(
                [sys.executable, str(BUILDER), "--verify", str(invalid)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("BUILD FAILED", proc.stderr)


if __name__ == "__main__":
    unittest.main()
