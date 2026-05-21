from __future__ import annotations

import argparse
import tarfile
import zipfile
from collections import Counter
from pathlib import Path


WHEEL_REQUIRED = [
    "titan/dialogue/webbundle/index.html",
    "titan/dialogue/pipeline/resources/symbols.csv",
    "titan/third_party/fold/NOTICE.md",
    "titan/third_party/fold/SOURCE_MAPPING.md",
    "titan/third_party/fold/COPYING",
]

SDIST_REQUIRED_SUFFIXES = [
    "/src/titan/dialogue/webbundle/index.html",
]

SDIST_FORBIDDEN_PARTS = [
    "/.venv/",
    "/.env/",
    "/env/",
    "/venv/",
    "/build/",
    "/dist/",
    "/src/titan/dialogue/websrc/node_modules/",
    "/src/titan/dialogue/websrc/public/data/",
    "/src/titan/dialogue/websrc/dist/",
    "/src/titan/dialogue/websrc/playwright-report/",
    "/src/titan/dialogue/websrc/test-results/",
]

PLACEHOLDER_MARKER = "Titan dialogue shell placeholder"
FOLD_LICENSE_MARKER = "GNU GENERAL PUBLIC LICENSE"


def fail(message: str) -> None:
    raise SystemExit(message)


def verify_wheel(wheel: Path) -> None:
    print(f"Verifying wheel: {wheel.name}")
    with zipfile.ZipFile(wheel) as zf:
        names = [info.filename for info in zf.infolist()]
        name_set = set(names)

        dupes = [name for name, count in Counter(names).items() if count > 1]
        if dupes:
            lines = ["Duplicate wheel entries found:"]
            lines.extend(f"  {name}" for name in dupes)
            fail("\n".join(lines))
        print("  OK: no duplicate wheel entries")

        missing = [path for path in WHEEL_REQUIRED if path not in name_set]
        if missing:
            lines = ["Missing required wheel files:"]
            lines.extend(f"  {path}" for path in missing)
            fail("\n".join(lines))
        print("  OK: required wheel files present")

        index_html = zf.read("titan/dialogue/webbundle/index.html").decode(
            "utf-8", "replace"
        )
        if PLACEHOLDER_MARKER in index_html:
            fail(
                "Placeholder dialogue shell detected in wheel; expected "
                "prebuilt production web bundle"
            )
        print("  OK: dialogue shell is non-placeholder")

        copying = zf.read("titan/third_party/fold/COPYING").decode(
            "utf-8", "replace"
        )
        if FOLD_LICENSE_MARKER not in copying:
            fail("fold/COPYING does not look like GPL license text")
        print("  OK: fold compliance bundle present")


def verify_sdist(sdist: Path) -> None:
    print(f"Verifying sdist: {sdist.name}")
    with tarfile.open(sdist, "r:gz") as tf:
        names = tf.getnames()
        normalized = [f"/{name}" for name in names]

        missing = [
            suffix
            for suffix in SDIST_REQUIRED_SUFFIXES
            if not any(name.endswith(suffix) for name in normalized)
        ]
        if missing:
            lines = ["Missing required sdist files:"]
            lines.extend(f"  *{suffix}" for suffix in missing)
            fail("\n".join(lines))
        print("  OK: generated webbundle present in sdist")

        leaks = [
            name
            for name in normalized
            if any(part in name for part in SDIST_FORBIDDEN_PARTS)
        ]
        if leaks:
            lines = ["Transient files leaked into sdist:"]
            lines.extend(f"  {name.lstrip('/')}" for name in leaks[:50])
            if len(leaks) > 50:
                lines.append(f"  ... and {len(leaks) - 50} more")
            fail("\n".join(lines))
        print("  OK: no transient frontend/build files in sdist")

        index_member = next(
            (
                name
                for name in names
                if f"/{name}".endswith("/src/titan/dialogue/webbundle/index.html")
            ),
            None,
        )
        if index_member is None:
            fail("webbundle/index.html missing from sdist")
        extracted = tf.extractfile(index_member)
        if extracted is None:
            fail("Unable to read webbundle/index.html from sdist")
        index_html = extracted.read().decode("utf-8", "replace")
        if PLACEHOLDER_MARKER in index_html:
            fail(
                "Placeholder dialogue shell detected in sdist; wheel-from-sdist "
                "would produce a placeholder package"
            )
        print("  OK: sdist dialogue shell is non-placeholder")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Titan package artifacts.")
    parser.add_argument(
        "--dist-dir",
        default="dist",
        type=Path,
        help="Directory containing built .whl and .tar.gz files.",
    )
    args = parser.parse_args()

    dist_dir = args.dist_dir
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))

    if not wheels:
        fail(f"No wheel file found in {dist_dir}")
    if not sdists:
        fail(f"No sdist file found in {dist_dir}")

    for wheel in wheels:
        verify_wheel(wheel)
    for sdist in sdists:
        verify_sdist(sdist)

    print("Package verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
