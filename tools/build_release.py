#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "screensaver.immich"
REPOSITORY_ID = "repository.skibish.kodi"


def parse_version(addon_xml: Path) -> str:
    root = ET.parse(addon_xml).getroot()
    version = root.attrib.get("version")
    if not version:
        raise SystemExit(f"Missing version in {addon_xml}")
    return version


def read_xml_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("<?xml"):
        _, _, text = text.partition("?>")
    return text.strip()


def write_zip(source_dir: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, f"{source_dir.name}/{path.relative_to(source_dir)}")


def write_addons_xml(xml_bodies: list[str], output_path: Path) -> None:
    entries = []
    for body in xml_bodies:
        indented = "\n".join(f"  {line}" if line else "" for line in body.splitlines())
        entries.append(indented)
    output = '<?xml version="1.0" encoding="UTF-8"?>\n<addons>\n'
    output += "\n\n".join(entries)
    output += "\n</addons>\n"
    output_path.write_text(output, encoding="utf-8")


def write_md5(source_path: Path, output_path: Path) -> None:
    digest = hashlib.md5(source_path.read_bytes()).hexdigest()
    output_path.write_text(digest, encoding="utf-8")


def main() -> None:
    zips_dir = ROOT / "zips"
    addon_dirs = [ROOT / ADDON_ID, ROOT / REPOSITORY_ID]

    zips_dir.mkdir(parents=True, exist_ok=True)
    addon_entries = []

    for addon_dir in addon_dirs:
        addon_id = addon_dir.name
        addon_version = parse_version(addon_dir / "addon.xml")
        shutil.rmtree(zips_dir / addon_id, ignore_errors=True)
        addon_zip = zips_dir / addon_id / f"{addon_id}-{addon_version}.zip"
        write_zip(addon_dir, addon_zip)
        addon_entries.append(read_xml_body(addon_dir / "addon.xml"))

    write_addons_xml(addon_entries, zips_dir / "addons.xml")
    write_md5(zips_dir / "addons.xml", zips_dir / "addons.xml.md5")


if __name__ == "__main__":
    main()
