"""Every third-party import must come from a dependency pyproject.toml declares.

CI installs only what pyproject.toml declares. A package that is merely present
in a local env, often pulled in by another dependency, passes locally and then
fails in CI with ModuleNotFoundError. This test fails locally instead.
"""

from __future__ import annotations

import ast
import re
import sys
from functools import cache
from importlib.metadata import packages_distributions
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY = {"titan", "tests", "__future__"}

# Unguarded imports that only run after a guarded import of the package that
# provides them has already succeeded.
REACHED_ONLY_VIA_OPTIONAL = {
    "vtk": "uw2/map3d.py imports it in a helper that receives a loaded pyvista",
}


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(requirements: list[str]) -> set[str]:
    return {
        _canonical(re.match(r"[A-Za-z0-9._-]+", req.strip()).group(0))
        for req in requirements
    }


def _project() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)["project"]


def _catches_import_error(node: ast.Try) -> bool:
    for handler in node.handlers:
        caught = handler.type
        names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
        if any(
            isinstance(name, ast.Name)
            and name.id in ("ImportError", "ModuleNotFoundError")
            for name in names
        ):
            return True
    return False


@cache
def _providers() -> dict[str, list[str]]:
    return packages_distributions()


@cache
def _third_party_imports(folder: str) -> dict[str, list[str]]:
    """Unguarded third-party top-level module names and where they are imported."""
    local_modules = {path.stem for path in (ROOT / folder).rglob("*.py")}
    found: dict[str, list[str]] = {}

    def visit(node: ast.AST, guarded: bool, where: Path) -> None:
        if isinstance(node, ast.Try) and _catches_import_error(node):
            for child in node.body:
                visit(child, True, where)
            for part in (node.handlers, node.orelse, node.finalbody):
                for child in part:
                    visit(child, guarded, where)
            return
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if (
                not guarded
                and top not in sys.stdlib_module_names
                and top not in FIRST_PARTY
                and top not in local_modules
            ):
                found.setdefault(top, []).append(
                    f"{where.relative_to(ROOT).as_posix()}:{node.lineno}"
                )
        for child in ast.iter_child_nodes(node):
            visit(child, guarded, where)

    for path in sorted((ROOT / folder).rglob("*.py")):
        visit(ast.parse(path.read_text(encoding="utf-8")), False, path)
    return found


def _undeclared(imports: dict[str, list[str]], declared: set[str]) -> list[str]:
    providers = _providers()
    problems = []
    for module, places in sorted(imports.items()):
        if module in REACHED_ONLY_VIA_OPTIONAL or _canonical(module) in declared:
            continue
        dists = {_canonical(dist) for dist in providers.get(module, [])}
        if dists & declared:
            continue
        source = f"installed via {sorted(dists)}" if dists else "not installed"
        problems.append(f"{module} ({source}) imported at {', '.join(places[:3])}")
    return problems


def test_package_imports_only_runtime_dependencies():
    # Extras such as glb are optional, so package code must guard their
    # imports with try/except ImportError.
    declared = _requirement_names(_project()["dependencies"])
    problems = _undeclared(_third_party_imports("src"), declared)
    assert not problems, (
        "Add these to [project].dependencies, or guard the import with "
        "try/except ImportError:\n  " + "\n  ".join(problems)
    )


def test_tests_import_only_declared_dependencies():
    project = _project()
    declared = _requirement_names(project["dependencies"])
    for extra in project["optional-dependencies"].values():
        declared |= _requirement_names(extra)
    problems = _undeclared(_third_party_imports("tests"), declared)
    assert not problems, (
        "Declare these in pyproject.toml (the test extra for test-only tools), "
        "or use pytest.importorskip:\n  " + "\n  ".join(problems)
    )


def test_every_runtime_dependency_is_imported():
    imported = {
        _canonical(dist)
        for module in _third_party_imports("src")
        for dist in _providers().get(module, [module])
    }
    unused = sorted(_requirement_names(_project()["dependencies"]) - imported)
    assert not unused, f"Declared but never imported by src/titan: {unused}"
