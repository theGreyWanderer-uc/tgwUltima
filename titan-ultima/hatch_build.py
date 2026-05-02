from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Ensure required force-included webbundle path exists for local builds.

    CI builds generate a full web bundle before packaging. For local builds where
    the bundle has not been generated yet, create a minimal fallback shell so
    `python -m build` can still succeed.
    """

    def initialize(self, version: str, build_data: dict) -> None:
        project_root = Path(self.root)
        webbundle_dir = project_root / "src" / "titan" / "dialogue" / "webbundle"
        index_html = webbundle_dir / "index.html"

        if index_html.exists():
            return

        webbundle_dir.mkdir(parents=True, exist_ok=True)
        index_html.write_text(
            """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Titan Dialogue</title>
  </head>
  <body>
    <main style=\"font-family:sans-serif;max-width:52rem;margin:2rem auto;line-height:1.5;\">
      <h1>Titan dialogue shell placeholder</h1>
      <p>
        This package was built without the generated dialogue web assets.
      </p>
      <p>
        Rebuild in CI or run the frontend bundle step before packaging to include
        the full dialogue UI.
      </p>
    </main>
  </body>
</html>
""",
            encoding="utf-8",
        )
