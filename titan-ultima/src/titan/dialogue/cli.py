"""TITAN dialogue web integration commands."""

from __future__ import annotations

import os
import socketserver
import webbrowser
import csv
import json
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from urllib.parse import unquote, urlparse

import typer

from titan._config import get_config
from titan.dialogue.pipeline.build_data import build_data
from titan.dialogue.pipeline.extract_ast import main as extract_ast_main
from titan.dialogue.pipeline.extract_books import main as extract_books_main
from titan.dialogue.pipeline.extract_library import main as extract_library_main
from titan.dialogue.pipeline.lint_json import run_lint
from titan.dialogue.pipeline.run_fold import FoldRunError, get_effective_fold_path, run_fold


dialogue_app = typer.Typer(
    name="dialogue",
    help="Prepare, validate, and launch the Ultima 8 dialogue web viewer.",
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


def _dialogue_root() -> Path:
    return Path(__file__).resolve().parent


def _default_runtime_root() -> Path:
    if os.name == "nt":
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "Titan" / "dialogue-web"
    return Path.home() / ".local" / "share" / "titan" / "dialogue-web"


def _runtime_dirs(runtime_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=runtime_root,
        fold=runtime_root / "foldExtract",
        json=runtime_root / "dialogue" / "json",
        web_data=runtime_root / "web" / "public" / "data",
    )


def _resolve_usecode_path(usecode: Optional[Path]) -> Path:
    if usecode:
        return usecode

    cfg = get_config()
    paths = cfg.get("paths", {})
    game = cfg.get("game", {})

    if paths.get("usecode"):
        return Path(str(paths["usecode"]))

    base = game.get("base")
    language = game.get("language") or "ENGLISH"
    if base:
        base_dir = Path(base)
        candidates: list[Path] = []

        # Standard U8 layout: <base>/<language>/USECODE/EUSECODE.FLX
        if language:
            lang_dir = base_dir / str(language)
            candidates.append(lang_dir / "USECODE" / "EUSECODE.FLX")
            # Compatibility fallback for non-standard flat language layouts.
            candidates.append(lang_dir / "EUSECODE.FLX")

        # Additional fallback layouts.
        candidates.append(base_dir / "USECODE" / "EUSECODE.FLX")
        candidates.append(base_dir / "EUSECODE.FLX")

        for candidate in candidates:
            if candidate.exists():
                return candidate

    raise typer.BadParameter(
        "Unable to detect EUSECODE.FLX. Provide --usecode, set paths.usecode, or set config game.base/language "
        "so Titan can resolve <base>/<language>/USECODE/EUSECODE.FLX."
    )


def _resolve_symbols_path(symbols: Optional[Path]) -> Path:
    if symbols:
        if symbols.is_file():
            return symbols
        raise typer.BadParameter(f"symbols.csv not found: {symbols}")

    dialogue_root = _dialogue_root()
    candidate = dialogue_root / "pipeline" / "resources" / "symbols.csv"
    if candidate.is_file():
        return candidate
    raise typer.BadParameter(
        f"symbols.csv not found in Titan resources: {candidate}"
    )


def _resolve_classes_path(classes: Optional[Path]) -> Path:
    if classes:
        if classes.is_file():
            return classes
        raise typer.BadParameter(f"usecode_classes.csv not found: {classes}")

    dialogue_root = _dialogue_root()
    candidate = dialogue_root / "pipeline" / "resources" / "usecode_classes.csv"
    if candidate.is_file():
        return candidate
    raise typer.BadParameter(
        f"usecode_classes.csv not found in Titan resources: {candidate}"
    )


def _run_prepare(
    usecode: Path,
    runtime_root: Path,
    symbols: Path,
    classes: Path,
    force: bool,
) -> int:
    def _ok(message: str) -> None:
        typer.secho(f"[v] {message}", fg=typer.colors.GREEN)

    def _bad(message: str) -> None:
        typer.secho(f"[x] {message}", fg=typer.colors.RED, err=True)

    def _count_csv_rows(path: Path) -> int:
        with path.open("r", encoding="utf-8", newline="") as f:
            return sum(1 for _ in csv.DictReader(f))

    def _count_global_symbols(path: Path) -> int:
        with path.open("r", encoding="utf-8", newline="") as f:
            return sum(1 for row in csv.DictReader(f) if (row.get("type") or "").strip() == "global")

    dirs = _runtime_dirs(runtime_root)
    websrc_data = _dialogue_root() / "websrc" / "public" / "data"
    dirs.fold.mkdir(parents=True, exist_ok=True)
    dirs.json.mkdir(parents=True, exist_ok=True)
    dirs.web_data.mkdir(parents=True, exist_ok=True)
    websrc_data.mkdir(parents=True, exist_ok=True)

    if force:
        for pattern in ("U8P_*.txt",):
            for file in dirs.fold.glob(pattern):
                file.unlink()
        for pattern in ("U8P_*.json", "all_dialogue.json", "manifest.json", "books.json", "library.json"):
            for file in dirs.json.glob(pattern):
                file.unlink()
        for pattern in ("U8P_*.json", "all_dialogue.json", "manifest.json", "books.json", "library.json"):
            for file in dirs.web_data.glob(pattern):
                file.unlink()
        for pattern in ("U8P_*.json", "all_dialogue.json", "manifest.json", "flag_metadata.json", "books.json", "library.json"):
            for file in websrc_data.glob(pattern):
                file.unlink()

    effective_symbols = symbols
    effective_classes = classes

    typer.secho("Dialogue pipeline prepare", fg=typer.colors.BRIGHT_BLUE, bold=True)
    typer.echo(f"Runtime root: {runtime_root}")

    symbol_rows = _count_csv_rows(effective_symbols)
    class_rows = _count_csv_rows(effective_classes)
    global_symbols = _count_global_symbols(effective_symbols)
    _ok(
        "Prepare metadata: "
        f"symbols={symbol_rows} rows ({global_symbols} globals), "
        f"classes={class_rows} rows"
    )
    typer.echo(f"Using fold binary: {get_effective_fold_path(usecode)}")
    typer.echo("Starting fold extraction...")

    try:
        fold_count = run_fold(
            usecode_path=usecode,
            output_dir=dirs.fold,
            progress_cb=lambda msg: typer.echo(msg),
            symbols_path=effective_symbols,
            classes_path=effective_classes,
        )
    except FoldRunError as exc:
        _bad(str(exc))
        return 1

    _ok(f"Fold class files: {fold_count}/{class_rows}")
    typer.echo("Starting AST extraction and JSON generation...")

    extract_rc = extract_ast_main([
        str(dirs.fold),
        "--outdir",
        str(dirs.json),
        "--repo-root",
        str(Path.cwd()),
        "--symbols",
        str(effective_symbols),
        "--classes",
        str(effective_classes),
    ])
    if extract_rc != 0:
        _bad(f"AST extraction failed with exit code {extract_rc}")
        return extract_rc

    _ok("AST extraction complete")

    typer.echo("Starting book extraction...")
    books_rc = extract_books_main([
        "--json-dir",
        str(dirs.json),
        "--out",
        str(dirs.json / "books.json"),
    ])
    if books_rc != 0:
        _bad(f"Book extraction failed with exit code {books_rc}")
        return books_rc

    _ok("Book extraction complete")

    typer.echo("Starting library extraction...")
    library_rc = extract_library_main([
        "--json-dir",
        str(dirs.json),
        "--out",
        str(dirs.json / "library.json"),
    ])
    if library_rc != 0:
        _bad(f"Library extraction failed with exit code {library_rc}")
        return library_rc

    _ok("Library extraction complete")

    typer.echo("Copying JSON files and writing manifests...")

    build_rc = build_data(dirs.json, dirs.web_data)
    if build_rc != 0:
        _bad(f"Runtime data build failed with exit code {build_rc}")
        return build_rc

    _ok(f"Runtime data copied: {dirs.web_data}")

    # Keep Vite dev mode working by populating websrc/public/data as well.
    websrc_build_rc = build_data(dirs.json, websrc_data)
    if websrc_build_rc != 0:
        _bad(f"Websrc data build failed with exit code {websrc_build_rc}")
        return websrc_build_rc

    _ok(f"Websrc data copied: {websrc_data}")

    # Validation is intentionally a separate explicit step via `titan dialogue validate`.

    _ok(f"Prepared dialogue artifacts in: {runtime_root}")
    _ok(f"Fold classes: {fold_count}")
    return 0


def _has_prepared_artifacts(runtime_root: Path) -> bool:
    dirs = _runtime_dirs(runtime_root)
    return (
        any(dirs.fold.glob("U8P_*.txt"))
        and any(dirs.json.glob("U8P_*.json"))
        and (dirs.web_data / "manifest.json").is_file()
    )


def _validate_pipeline_outputs(runtime_root: Path, expected_classes: int, run_content_lint: bool) -> int:
    dirs = _runtime_dirs(runtime_root)
    pipeline_resources = _dialogue_root() / "pipeline" / "resources"
    websrc_data = _dialogue_root() / "websrc" / "public" / "data"
    websrc_meta = _dialogue_root() / "websrc" / "public" / "meta"
    errors = 0

    def _ok(message: str) -> None:
        typer.secho(f"[v] {message}", fg=typer.colors.GREEN)

    def _bad(message: str) -> None:
        nonlocal errors
        typer.secho(f"[x] {message}", fg=typer.colors.RED, err=True)
        errors += 1

    def _count(pattern_dir: Path, pattern: str) -> int:
        return sum(1 for _ in pattern_dir.glob(pattern))

    def _validate_books_json(path: Path, label: str) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _bad(f"{label} books data is not valid JSON: {path} ({exc})")
            return

        if not isinstance(payload, dict):
            _bad(f"{label} books data is not a JSON object: {path}")
            return

        books = payload.get("books")
        if payload.get("itemClass") != "BASEBOOK":
            _bad(f"{label} books itemClass mismatch: expected BASEBOOK in {path}")
        if not isinstance(books, list) or not books:
            _bad(f"{label} books list is missing or empty: {path}")
            return

        total_books = payload.get("totalBooks")
        if total_books != len(books):
            _bad(f"{label} totalBooks mismatch: declared {total_books}, actual {len(books)} in {path}")

        seen_qualities: set[int] = set()
        readable = 0
        bad_entries = 0
        for index, entry in enumerate(books):
            if not isinstance(entry, dict):
                bad_entries += 1
                continue

            quality = entry.get("quality")
            quality_hex = entry.get("qualityHex")
            title = entry.get("title")
            category = entry.get("category")
            text = entry.get("text")
            paragraphs = entry.get("paragraphs")

            if not isinstance(quality, int):
                bad_entries += 1
                continue
            if quality in seen_qualities:
                _bad(f"{label} duplicate book quality 0x{quality:02X} in {path}")
            seen_qualities.add(quality)

            expected_hex = f"0x{quality:02X}"
            if quality_hex != expected_hex:
                _bad(
                    f"{label} book #{index} qualityHex mismatch: "
                    f"expected {expected_hex}, found {quality_hex!r} in {path}"
                )
            if not isinstance(title, str) or not title.strip():
                _bad(f"{label} book {expected_hex} has missing title in {path}")
            if not isinstance(category, str) or not category.strip():
                _bad(f"{label} book {expected_hex} has missing category in {path}")

            if isinstance(text, str):
                readable += 1
                if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
                    _bad(f"{label} book {expected_hex} has text but invalid paragraphs in {path}")
            elif text is not None:
                _bad(f"{label} book {expected_hex} text must be string or null in {path}")

        if bad_entries:
            _bad(f"{label} books data contains {bad_entries} malformed entries in {path}")

        books_with_text = payload.get("booksWithText")
        if books_with_text != readable:
            _bad(
                f"{label} booksWithText mismatch: declared {books_with_text}, "
                f"actual {readable} in {path}"
            )
        else:
            _ok(f"{label} books data: {len(books)} books, {readable} with text")

    def _validate_library_json(path: Path, label: str) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _bad(f"{label} library data is not valid JSON: {path} ({exc})")
            return

        if not isinstance(payload, dict):
            _bad(f"{label} library data is not a JSON object: {path}")
            return

        sections = payload.get("sections")
        if not isinstance(sections, list) or not sections:
            _bad(f"{label} library sections missing or empty: {path}")
            return

        expected_sections = {"books", "scrolls", "graves", "plaques", "spells"}
        seen_sections = {
            section.get("id")
            for section in sections
            if isinstance(section, dict) and isinstance(section.get("id"), str)
        }
        missing = expected_sections - seen_sections
        if missing:
            _bad(f"{label} library sections missing {sorted(missing)} in {path}")

        total_items = 0
        malformed = 0
        for section in sections:
            if not isinstance(section, dict):
                malformed += 1
                continue
            items = section.get("items")
            if not isinstance(items, list) or not items:
                _bad(f"{label} library section {section.get('id')!r} has no items in {path}")
                continue
            if section.get("totalItems") != len(items):
                _bad(
                    f"{label} library section {section.get('id')!r} totalItems mismatch: "
                    f"declared {section.get('totalItems')}, actual {len(items)} in {path}"
                )
            total_items += len(items)
            for item in items:
                if not isinstance(item, dict):
                    malformed += 1
                    continue
                if not isinstance(item.get("id"), str) or not item.get("id"):
                    malformed += 1
                if not isinstance(item.get("title"), str) or not item.get("title"):
                    malformed += 1
                if not isinstance(item.get("kind"), str) or not item.get("kind"):
                    malformed += 1
                if not isinstance(item.get("category"), str) or not item.get("category"):
                    malformed += 1

        if payload.get("totalItems") != total_items:
            _bad(
                f"{label} library totalItems mismatch: declared {payload.get('totalItems')}, "
                f"actual {total_items} in {path}"
            )
        if malformed:
            _bad(f"{label} library data contains {malformed} malformed item(s) in {path}")
        else:
            _ok(f"{label} library data: {len(sections)} sections, {total_items} items")

    typer.secho("Dialogue pipeline validation", fg=typer.colors.BRIGHT_BLUE, bold=True)
    typer.echo(f"Runtime root: {runtime_root}")

    if not dirs.fold.exists():
        _bad(f"Fold output directory missing: {dirs.fold}")
    else:
        fold_count = _count(dirs.fold, "U8P_*.txt")
        if fold_count != expected_classes:
            _bad(f"Fold class count mismatch: expected {expected_classes}, found {fold_count} in {dirs.fold}")
        else:
            _ok(f"Fold class files: {fold_count}/{expected_classes}")

    if not dirs.json.exists():
        _bad(f"JSON output directory missing: {dirs.json}")
    else:
        json_count = _count(dirs.json, "U8P_*.json")
        if json_count != expected_classes:
            _bad(f"JSON class count mismatch: expected {expected_classes}, found {json_count} in {dirs.json}")
        else:
            _ok(f"JSON class files: {json_count}/{expected_classes}")

        item_props_total = 0
        item_props_weapon = 0
        item_props_armour = 0
        item_props_overlay = 0
        for class_json in dirs.json.glob("U8P_*.json"):
            try:
                payload = json.loads(class_json.read_text(encoding="utf-8"))
            except Exception:
                continue
            item_props = payload.get("itemProperties") if isinstance(payload, dict) else None
            if not isinstance(item_props, dict):
                continue
            item_props_total += 1
            if "weapon" in item_props:
                item_props_weapon += 1
            if "armour" in item_props:
                item_props_armour += 1
            if "overlay" in item_props:
                item_props_overlay += 1

        if item_props_total == 0:
            _bad(
                "No itemProperties found in generated class JSON output. "
                "This usually means weapon/armour INI resources were not consumed during extraction."
            )
        else:
            _ok(
                "Extracted itemProperties classes: "
                f"total={item_props_total} weapon={item_props_weapon} "
                f"armour={item_props_armour} overlay={item_props_overlay}"
            )

    for ini_name in ("u8weapons.ini", "u8armour.ini"):
        ini_path = pipeline_resources / ini_name
        if not ini_path.is_file():
            _bad(f"Required pipeline resource missing: {ini_path}")
        else:
            _ok(f"Pipeline resource: {ini_path}")

    manifest_path = dirs.web_data / "manifest.json"
    if not manifest_path.is_file():
        _bad(f"Runtime manifest missing: {manifest_path}")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _bad(f"Runtime manifest is not valid JSON: {manifest_path} ({exc})")
            manifest = []

        if not isinstance(manifest, list):
            _bad(f"Runtime manifest is not a JSON array: {manifest_path}")
        else:
            class_entries = [
                item for item in manifest
                if isinstance(item, str) and item.startswith("U8P_") and item.endswith(".json")
            ]
            if len(class_entries) != expected_classes:
                _bad(
                    f"Runtime manifest class entries mismatch: expected {expected_classes}, found {len(class_entries)}"
                )
            else:
                _ok(f"Runtime manifest class entries: {len(class_entries)}/{expected_classes}")

    runtime_flag_meta = dirs.web_data / "flag_metadata.json"
    if not runtime_flag_meta.is_file():
        _bad(f"Runtime flag metadata missing: {runtime_flag_meta}")
    else:
        _ok(f"Runtime flag metadata: {runtime_flag_meta}")

    runtime_books = dirs.web_data / "books.json"
    if not runtime_books.is_file():
        _bad(f"Runtime books data missing: {runtime_books}")
    else:
        _validate_books_json(runtime_books, "Runtime")

    runtime_library = dirs.web_data / "library.json"
    if not runtime_library.is_file():
        _bad(f"Runtime library data missing: {runtime_library}")
    else:
        _validate_library_json(runtime_library, "Runtime")

    websrc_manifest = websrc_data / "manifest.json"
    if not websrc_manifest.is_file():
        _bad(f"Websrc manifest missing (for npx vite): {websrc_manifest}")
    else:
        _ok(f"Websrc manifest: {websrc_manifest}")

    websrc_flag_meta = websrc_data / "flag_metadata.json"
    if not websrc_flag_meta.is_file():
        _bad(f"Websrc flag metadata missing (for npx vite): {websrc_flag_meta}")
    else:
        _ok(f"Websrc flag metadata: {websrc_flag_meta}")

    websrc_books = websrc_data / "books.json"
    if not websrc_books.is_file():
        _bad(f"Websrc books data missing (for npx vite): {websrc_books}")
    else:
        _validate_books_json(websrc_books, "Websrc")

    websrc_library = websrc_data / "library.json"
    if not websrc_library.is_file():
        _bad(f"Websrc library data missing (for npx vite): {websrc_library}")
    else:
        _validate_library_json(websrc_library, "Websrc")

    if not websrc_meta.is_dir():
        _bad(f"Websrc meta directory missing (required for dialogue launch): {websrc_meta}")
    else:
        meta_count = _count(websrc_meta, "*_META.JSON")
        if meta_count == 0:
            _bad(f"Websrc meta directory is empty (required for dialogue launch): {websrc_meta}")
        else:
            _ok(f"Websrc meta files: {meta_count}")

    if run_content_lint:
        typer.secho("Optional content lint", fg=typer.colors.BRIGHT_BLUE, bold=True)
        lint_rc = run_lint(str(dirs.json))
        if lint_rc != 0:
            _bad("Content lint reported issues")
        else:
            _ok("Content lint passed")

    if errors:
        typer.secho(f"Validation failed with {errors} issue(s).", fg=typer.colors.RED, bold=True, err=True)
        return 1

    typer.secho("Validation passed.", fg=typer.colors.GREEN, bold=True)
    return 0


def _resolve_shell_dir() -> Optional[Path]:
    dialogue_root = _dialogue_root()
    candidates = [
        dialogue_root / "webbundle",
        dialogue_root / "websrc" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _is_placeholder_shell(shell_dir: Path) -> bool:
    index_path = shell_dir / "index.html"
    if not index_path.is_file():
        return False
    try:
        text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "Titan dialogue shell placeholder" in text


def _serve_dialogue(shell_dir: Path, data_dir: Path, meta_dir: Path, host: str, port: int, open_browser: bool) -> int:
    class DialogueHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def _resolve_override(self, requested_path: str) -> Optional[Path]:
            parsed = urlparse(requested_path)
            path = unquote(parsed.path)

            if path.startswith("/data"):
                rel = path[len("/data"):].lstrip("/")
                return data_dir / rel
            if path.startswith("/meta"):
                rel = path[len("/meta"):].lstrip("/")
                return meta_dir / rel
            return None

        def translate_path(self, path: str) -> str:
            override = self._resolve_override(path)
            if override is not None:
                return str(override)
            return str(shell_dir / unquote(urlparse(path).path.lstrip("/")))

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("", "/"):
                self.path = "/index.html"
            super().do_GET()

    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer((host, port), DialogueHandler) as httpd:
        url = f"http://{host}:{port}/"
        typer.secho(f"[v] Dialogue web viewer serving at {url}", fg=typer.colors.GREEN)
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.secho("[v] Stopping server...", fg=typer.colors.GREEN)
    return 0


@dialogue_app.command("prepare")
def prepare_cmd(
    usecode: Optional[Path] = typer.Option(None, "--usecode", help="Path to EUSECODE.FLX"),
    workdir: Optional[Path] = typer.Option(None, "--workdir", help="Runtime output directory"),
    symbols: Optional[Path] = typer.Option(None, "--symbols", help="Override symbols.csv path (default: Titan bundled resources)"),
    classes: Optional[Path] = typer.Option(None, "--classes", help="Override usecode_classes.csv path (default: Titan bundled resources)"),
    force: bool = typer.Option(False, "--force", help="Regenerate by clearing existing runtime artifacts first"),
) -> None:
    """Generate fold/text/json/data artifacts for the dialogue viewer."""
    runtime_root = (workdir or _default_runtime_root()).resolve()
    usecode_path = _resolve_usecode_path(usecode).resolve()
    symbols_path = _resolve_symbols_path(symbols)
    classes_path = _resolve_classes_path(classes)

    rc = _run_prepare(
        usecode=usecode_path,
        runtime_root=runtime_root,
        symbols=symbols_path,
        classes=classes_path,
        force=force,
    )
    raise SystemExit(rc)


@dialogue_app.command("validate")
def validate_cmd(
    workdir: Optional[Path] = typer.Option(None, "--workdir", help="Runtime output directory"),
    content_lint: bool = typer.Option(False, "--content-lint", help="Also run deep JSON content lint checks"),
) -> None:
    """Validate generated dialogue pipeline artifacts required for launch."""
    runtime_root = (workdir or _default_runtime_root()).resolve()
    classes_path = _resolve_classes_path(None)
    with classes_path.open("r", encoding="utf-8", newline="") as f:
        expected_classes = sum(1 for _ in csv.DictReader(f))
    raise SystemExit(_validate_pipeline_outputs(runtime_root, expected_classes, run_content_lint=content_lint))


@dialogue_app.command("launch")
def launch_cmd(
    usecode: Optional[Path] = typer.Option(None, "--usecode", help="Path to EUSECODE.FLX"),
    workdir: Optional[Path] = typer.Option(None, "--workdir", help="Runtime output directory"),
    symbols: Optional[Path] = typer.Option(None, "--symbols", help="Override symbols.csv path (default: Titan bundled resources)"),
    classes: Optional[Path] = typer.Option(None, "--classes", help="Override usecode_classes.csv path (default: Titan bundled resources)"),
    host: str = typer.Option("127.0.0.1", "--host", help="Server bind address"),
    port: int = typer.Option(4173, "--port", help="Server port"),
    force: bool = typer.Option(False, "--force", help="Force regeneration before launch"),
    no_open: bool = typer.Option(False, "--no-open", help="Do not auto-open a browser tab"),
) -> None:
    """Launch static dialogue viewer using prepared runtime artifacts."""
    runtime_root = (workdir or _default_runtime_root()).resolve()
    usecode_path = _resolve_usecode_path(usecode).resolve()
    symbols_path = _resolve_symbols_path(symbols)
    classes_path = _resolve_classes_path(classes)

    if force or not _has_prepared_artifacts(runtime_root):
        rc = _run_prepare(
            usecode=usecode_path,
            runtime_root=runtime_root,
            symbols=symbols_path,
            classes=classes_path,
            force=force,
        )
        if rc != 0:
            raise SystemExit(rc)

    shell_dir = _resolve_shell_dir()
    if shell_dir is None:
        typer.secho(
            "[x] No dialogue web shell found. Expected index.html in webbundle/ or websrc/dist/.",
            fg=typer.colors.RED,
            err=True,
        )
        raise SystemExit(1)

    if _is_placeholder_shell(shell_dir):
        typer.secho(
            "[x] Installed dialogue shell is a placeholder, not the production web UI. "
            "Install a packaged release/CI wheel that includes the prebuilt web bundle.",
            fg=typer.colors.RED,
            err=True,
        )
        raise SystemExit(1)

    meta_dir = _dialogue_root() / "websrc" / "public" / "meta"
    if not meta_dir.exists():
        typer.secho(f"[x] Meta directory not found: {meta_dir}", fg=typer.colors.RED, err=True)
        raise SystemExit(1)

    dirs = _runtime_dirs(runtime_root)
    raise SystemExit(_serve_dialogue(shell_dir, dirs.web_data, meta_dir, host, port, open_browser=not no_open))
