#!/usr/bin/env python3
"""Build both GitHub and Blender Extensions distribution ZIPs from one source.

GitHub package:   MIT-licensed, suitable for personal GitHub installs.
Official package: GPL-3.0-or-later distribution for extensions.blender.org,
                  preserving the original MIT copyright notice.

Usage:
    python tools/build_extension.py
    python tools/build_extension.py --distribution official
    python tools/build_extension.py --distribution both --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
    python tools/build_extension.py --verify dist/vertex_color_toolbox-2.5.1-blender-extensions.zip
"""
import argparse
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vertex_color_toolbox_blender_5_2.py"
MANIFEST = ROOT / "blender_manifest.toml"
MIT_LICENSE = ROOT / "LICENSE"
GPL_LICENSE = ROOT / "packaging" / "GPL-3.0-or-later.txt"
REQUIRED_MANIFEST = (
    "schema_version", "id", "version", "name", "tagline",
    "maintainer", "type", "blender_version_min", "license",
)
OFFICIAL_NOTICE = (
    b"# SPDX-License-Identifier: GPL-3.0-or-later\n"
    b"# Blender Extensions distribution. Original MIT notice in LICENSE-MIT.\n"
)


def info():
    """Ensure source, license files, and manifest versions agree."""
    raw_manifest = MANIFEST.read_text(encoding="utf-8")
    manifest = tomllib.loads(raw_manifest)
    for key in REQUIRED_MANIFEST:
        if key not in manifest:
            raise ValueError(f"Missing manifest field: {key}")
    if manifest["schema_version"] != "1.0.0":
        raise ValueError("Unsupported manifest schema")
    if manifest["type"] != "add-on":
        raise ValueError("Extension type must be add-on")
    if manifest["id"] != "vertex_color_toolbox":
        raise ValueError("Unexpected extension identifier")
    if not 1 <= len(manifest["tagline"]) <= 64:
        raise ValueError("Manifest tagline must have 1-64 characters")
    if manifest["tagline"].endswith((".", "!", "?")):
        raise ValueError("Manifest tagline cannot end with punctuation")
    if manifest["license"] != ["SPDX:MIT"]:
        raise ValueError("Repository manifest must match the MIT license")
    if tuple(map(int, manifest["blender_version_min"].split("."))) < (5, 2, 0):
        raise ValueError("Blender minimum version is too old")

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    header = next((n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "bl_info"
                           for t in n.targets)), None)
    if header is None:
        raise ValueError("Source has no bl_info")
    metadata = ast.literal_eval(header)
    version = ".".join(str(n) for n in metadata["version"])
    if version != manifest["version"]:
        raise ValueError(f"Source {version} differs from manifest {manifest['version']}")
    if tuple(metadata["blender"]) > tuple(map(int, manifest["blender_version_min"].split("."))):
        raise ValueError("Manifest supports Blender versions below the add-on minimum")
    if manifest["version"].count(".") != 2:
        raise ValueError("Expected version MAJOR.MINOR.PATCH")
    if not MIT_LICENSE.read_text(encoding="utf-8").startswith("MIT License"):
        raise ValueError("Original MIT license is missing")
    if not GPL_LICENSE.read_text(encoding="utf-8").startswith(
        "GNU GENERAL PUBLIC LICENSE\nVersion 3"
    ):
        raise ValueError("Full GPL-3.0 license text is missing")
    return manifest


def official_manifest():
    original = MANIFEST.read_text(encoding="utf-8")
    needle = 'license = ["SPDX:MIT"]'
    if original.count(needle) != 1:
        raise ValueError("Cannot locate original MIT license declaration")
    # The official platform explicitly requires GPL-3.0-or-later for add-ons.
    converted = original.replace(
        needle,
        'license = ["SPDX:GPL-3.0-or-later"]\n'
        'copyright = ["2026 James Arndt"]',
    )
    converted = converted.split("# This manifest is for GitHub-distributed installation ZIPs.")[0].rstrip() + "\n"
    parsed = tomllib.loads(converted)
    if parsed["license"] != ["SPDX:GPL-3.0-or-later"]:
        raise ValueError("Official package must specify GPL-3.0-or-later")
    return converted.encode("utf-8")


def files_for(distribution):
    """Build two archives without maintaining two copies of the implementation."""
    source = SOURCE.read_bytes()
    if distribution == "github":
        return {
            "__init__.py": source,
            "blender_manifest.toml": MANIFEST.read_bytes(),
            "LICENSE": MIT_LICENSE.read_bytes(),
        }
    if distribution == "official":
        return {
            "__init__.py": OFFICIAL_NOTICE + source,
            "blender_manifest.toml": official_manifest(),
            "LICENSE": GPL_LICENSE.read_bytes(),
            "LICENSE-MIT": MIT_LICENSE.read_bytes(),
        }
    raise ValueError(f"Unknown distribution: {distribution}")


def archive_path(directory, distribution):
    manifest = info()
    extra = "-blender-extensions" if distribution == "official" else ""
    return directory / f"{manifest['id']}-{manifest['version']}{extra}.zip"


def detect_distribution(path):
    name = path.name
    return "official" if name.endswith("-blender-extensions.zip") else "github"


def verify(path, distribution=None):
    info()
    if not path.is_file():
        raise FileNotFoundError(path)
    distribution = distribution or detect_distribution(path)
    expected = files_for(distribution)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(expected) or set(names) != set(expected):
            raise ValueError(f"Unexpected {distribution} ZIP layout: {names}")
        if z.testzip() is not None:
            raise ValueError("Extension ZIP has corrupted contents")
        for name, content in expected.items():
            if z.read(name) != content:
                raise ValueError(f"Unexpected ZIP contents: {name}")
        manifest = tomllib.loads(z.read("blender_manifest.toml").decode("utf-8"))
        expected_license = (
            ["SPDX:GPL-3.0-or-later"] if distribution == "official"
            else ["SPDX:MIT"]
        )
        if manifest["license"] != expected_license:
            raise ValueError(f"Incorrect license in {distribution} manifest")
    print(f"VALID {distribution.upper()} EXTENSION PACKAGE: {path}")


def build_python_zip(output, distribution):
    """Build byte-reproducible archives without requiring Blender on CI."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as z:
        for name, content in files_for(distribution).items():
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            z.writestr(entry, content, compresslevel=9)


def build_with_blender(output, blender, distribution):
    """Build/validate the actual submission payload with Blender CLI."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"vct-{distribution}-") as directory:
        stage = Path(directory)
        for name, content in files_for(distribution).items():
            (stage / name).write_bytes(content)
        subprocess.run(
            [str(blender), "--command", "extension", "validate", str(stage)],
            check=True,
        )
        subprocess.run(
            [str(blender), "--command", "extension", "build",
             "--source-dir", str(stage), "--output-filepath", str(output.resolve())],
            check=True,
        )
    subprocess.run(
        [str(blender), "--command", "extension", "validate", str(output.resolve())],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--distribution", choices=("github", "official", "both"), default="both",
        help="Which installable variant to build (default: both)",
    )
    parser.add_argument("--blender", type=Path, help="Use Blender's official build and validator")
    parser.add_argument("--verify", type=Path, help="Check an existing ZIP against its source")
    args = parser.parse_args()

    info()
    if args.verify:
        verify(args.verify)
        return

    if args.blender and not args.blender.is_file():
        parser.error(f"Blender executable not found: {args.blender}")

    distributions = (
        ("github", "official") if args.distribution == "both"
        else (args.distribution,)
    )
    for distribution in distributions:
        output = archive_path(args.output_dir, distribution)
        if args.blender:
            build_with_blender(output, args.blender, distribution)
        else:
            build_python_zip(output, distribution)
        verify(output, distribution)
        print(f"BUILD SUCCESS: {output}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"BUILD FAILED: {error}", file=sys.stderr)
        raise SystemExit(1)
