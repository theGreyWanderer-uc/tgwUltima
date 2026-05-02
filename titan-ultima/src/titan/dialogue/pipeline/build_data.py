"""Generate ``manifest.json`` and copy dialogue JSON into runtime web data dir."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


FLAG_METADATA_FILENAME = "flag_metadata.json"


def build_data(json_src: Path, data_dst: Path) -> int:
    """Copy extracted class JSON files and generate ``manifest.json``.

    ``all_dialogue.json`` is intentionally excluded from manifest/runtime loading.
    """
    if not json_src.exists():
        print(f"ERROR: JSON source directory not found: {json_src}")
        print("Run extract_ast.py first.")
        return 1

    data_dst.mkdir(parents=True, exist_ok=True)

    files = sorted(f.name for f in json_src.glob("*.json") if f.name != "all_dialogue.json")
    if not files:
        print(f"ERROR: No JSON files found in {json_src}")
        return 1

    for fname in files:
        shutil.copy2(json_src / fname, data_dst / fname)

    # Always distribute flag metadata from permanent Titan resources.
    flag_metadata_src = Path(__file__).resolve().parent / "resources" / FLAG_METADATA_FILENAME
    if not flag_metadata_src.is_file():
        print(f"ERROR: Required metadata file not found: {flag_metadata_src}")
        return 1
    shutil.copy2(flag_metadata_src, data_dst / FLAG_METADATA_FILENAME)

    manifest_path = data_dst / "manifest.json"
    manifest_path.write_text(json.dumps(files, indent=2), encoding="utf-8")

    print(f"Copied {len(files)} JSON files to {data_dst}")
    print(f"Copied {FLAG_METADATA_FILENAME} to {data_dst}")
    print(f"Wrote {manifest_path}")
    return 0


def _default_paths() -> tuple[Path, Path]:
    dialogue_root = Path(__file__).resolve().parents[1]
    return (dialogue_root / "json", dialogue_root / "websrc" / "public" / "data")


def main(argv: list[str] | None = None) -> int:
    default_json_src, default_data_dst = _default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-src", default=str(default_json_src), help="Source directory containing U8P_*.json")
    parser.add_argument("--data-dst", default=str(default_data_dst), help="Destination web data directory")
    args = parser.parse_args(argv)
    return build_data(Path(args.json_src), Path(args.data_dst))


if __name__ == "__main__":
    raise SystemExit(main())
