"""Generate manifest.json and copy NPC JSON files into web/public/data/."""

import json
import shutil
from pathlib import Path

def main():
    web_dir = Path(__file__).parent
    json_src = web_dir.parent / "json"
    data_dst = web_dir / "public" / "data"

    if not json_src.exists():
        print(f"ERROR: JSON source directory not found: {json_src}")
        print("Run extract_ast.py first.")
        return 1

    data_dst.mkdir(parents=True, exist_ok=True)

    files = sorted(f.name for f in json_src.glob("*.json") if f.name != "all_dialogue.json")
    if not files:
        print(f"ERROR: No JSON files found in {json_src}")
        return 1

    # Copy each JSON file.
    for fname in files:
        shutil.copy2(json_src / fname, data_dst / fname)

    # Write manifest.
    manifest_path = data_dst / "manifest.json"
    manifest_path.write_text(json.dumps(files, indent=2))

    print(f"Copied {len(files)} JSON files to {data_dst}")
    print(f"Wrote {manifest_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
