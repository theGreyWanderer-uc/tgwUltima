# TITAN Publishing How-To

## 1. Required Files (current `titan-ultima/` layout)

### Package source (REQUIRED — ships in the wheel/sdist)

| File | Purpose |
|------|---------|
| `pyproject.toml` | Build config, metadata, dependencies, entry point |
| `LICENSE` | MIT licence text |
| `README.md` | PyPI long description (rendered on the package page) |
| `src/titan/__init__.py` | Package root, public API exports |
| `src/titan/__main__.py` | `python -m titan` entry point |
| `src/titan/_version.py` | Single source of truth for version (`__version__ = "0.4.0"`) |
| `src/titan/cli.py` | Typer CLI — all 26 commands |
| `src/titan/credits.py` | XOR credits decryption |
| `src/titan/flex.py` | Flex archive read/write |
| `src/titan/map.py` | Isometric map renderer |
| `src/titan/music.py` | XMIDI → MIDI conversion |
| `src/titan/palette.py` | VGA palette handling |
| `src/titan/save.py` | U8 save archive handling |
| `src/titan/shape.py` | RLE shape sprite codec |
| `src/titan/sound.py` | Sonarc audio decoder |
| `src/titan/typeflag.py` | TYPEFLAG.DAT parser |
| `src/titan/xformpal.py` | Colour-transform palette |
| `src/titan/py.typed` | PEP 561 typed-package marker (empty file) |
| `src/titan/titan.toml.example` | Bundled config template (for `titan setup`) |

### Documentation (REQUIRED — lives in the repo, not shipped in wheel)

| File | Purpose |
|------|---------|
| `titan.toml.example` | Config template at repo root (user reference) |

### Total: 4 root files + 16 files in `src/titan/` = **20 files**

---

## 2. Files That Should Be REMOVED

These exist on disk or in git but are **no longer needed**:

### a) Stale old package directory

| File | Why remove |
|------|------------|
| `titan/cli.py` | Leftover from the `titan/` → `src/titan/` move. The old `titan/` directory should be completely gone. |

**Action:** Delete the entire `titan/` directory (it only contains `cli.py` now).

### b) Game data files tracked in git (3,280+ files)

These are the **copyrighted Ultima 8 game assets** that were committed earlier. They must NOT be in a public repo:

| Category | Count | Examples |
|----------|-------|---------|
| Root game files | 21 | `FIXED.DAT`, `U8SHAPES.FLX`, `U8PAL.PAL`, `SOUND.FLX`, `MUSIC.FLX`, `U8SAVE.000`, etc. |
| `shapes/*.shp` | 856 | Extracted sprite files |
| `globs/*.dat` | 2,130 | Extracted glob files |
| `map_renders/*.png` | 252 | Rendered map images |
| `test_output/` | 1 | `map_005_config_test.png` |
| `titan/__pycache__/*.pyc` | 20 | Compiled bytecache from old layout |

All of these show as "deleted" in `git status` because they were previously committed but no longer exist on disk (or were moved). They are still in git history.

### c) Reference docs deleted from disk

| File | Status |
|------|--------|
| `reference/cli_reference.md` | Shows as deleted — the file was removed from disk but is still tracked in git. If you want to keep it, restore it. If not, remove it from tracking. |

---

## 3. How to Clean the Deleted Items from Git

The "thousands of deleted items" appear because git still tracks files that were committed previously but no longer exist on disk.

Since the `titan` branch was **never pushed to GitHub** (no `origin/titan` exists), the game data only lives in one local commit. You do NOT need `git-filter-repo`. The simplest approach is an interactive rebase to amend that commit, or just stage everything and make a clean new commit:

### Recommended approach — stage and commit

```powershell
cd C:\_Repos\tgwUltima\titan-ultima

# Stage ALL changes (new files, deletions, modifications) at once
git add -A

# Review what will be committed
git status

# Commit
git commit -m "TITAN 0.4.0: src/ layout, Typer CLI, .gitignore, publish-ready"
```

After this commit, `git status` will be clean. When you push the `titan` branch for the first time, only the committed files will be uploaded — the game data was removed before the push, so it never reaches GitHub.

---

## 4. Pre-Publication Checklist

Before making `titan-ultima` available publicly:

### Must do

- [x] **Remove game data from git** — the `titan` branch was never pushed, so no filter-repo needed. Just commit with `.gitignore` in place and the game data won't be included.
- [x] **Add a `.gitignore`** — created with game data, extracted dirs, u7data/, u8data/, and Python build artifacts.
- [x] **Delete the stale `titan/` directory** — done (old flat-layout leftover).
- [x] **Decide on `reference/cli_reference.md`** — removed; README now points to `titan --help`.
- [ ] **Test a clean install** from a fresh venv:
  ```powershell
  python -m venv test_venv
  test_venv\Scripts\activate
  pip install .
  titan --version
  titan --help
  deactivate
  Remove-Item -Recurse test_venv
  ```
- [ ] **Build the sdist + wheel** and verify:
  ```powershell
  pip install build
  python -m build
  # Check the dist/ output:
  #   titan_ultima-0.4.0.tar.gz  (sdist)
  #   titan_ultima-0.4.0-py3-none-any.whl  (wheel)
  ```
- [x] **Create a CHANGELOG.md** — done.

### Should do

- [ ] **Add a `py.typed` entry to pyproject.toml** (already included via the file — hatchling picks it up automatically, but verify with `unzip -l dist/*.whl | grep py.typed`)
- [ ] **Test on Python 3.9** (the minimum declared version) if possible
- [ ] **Check the sdist includes README.md** (`tar tzf dist/*.tar.gz | grep README`)
- [ ] **Review the PyPI rendering** with:
  ```powershell
  pip install twine
  twine check dist/*
  ```

---

## 5. How to Publish to PyPI

### First time: create a PyPI account and API token

1. Register at https://pypi.org/account/register/
2. Go to Account Settings → API tokens → "Add API token"
3. Set scope to "Entire account" (for first upload) or project-scoped after the first release
4. Save the token — it starts with `pypi-`

### Build the package

```powershell
cd C:\_Repos\tgwUltima\titan-ultima

# Install build tools
pip install build twine

# Build
python -m build

# Verify
twine check dist/*
```

### Upload to Test PyPI first (recommended)

```powershell
# Upload to test.pypi.org
twine upload --repository testpypi dist/*
# Enter: __token__ as username, paste your TestPyPI token as password

# Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ titan-ultima
```

### Upload to real PyPI

```powershell
twine upload dist/*
# Enter: __token__ as username, paste your PyPI token as password
```

After upload, `pip install titan-ultima` works worldwide.

### Alternative: Trusted Publishers (GitHub Actions)

Instead of managing API tokens manually, you can configure PyPI "Trusted Publishers" to auto-publish on GitHub release tags:

1. On PyPI → your project → Settings → "Add a new publisher"
2. Enter: Owner=`theGreyWanderer-uc`, Repo=`tgwUltima`, Workflow=`publish.yml`, Environment=`pypi`
3. Add a `.github/workflows/publish.yml`:
   ```yaml
   name: Publish to PyPI
   on:
     release:
       types: [published]
   jobs:
     publish:
       runs-on: ubuntu-latest
       environment: pypi
       permissions:
         id-token: write
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
         - run: pip install build
         - run: cd titan-ultima && python -m build
         - uses: pypa/gh-action-pypi-publish@release/v1
           with:
             packages-dir: titan-ultima/dist/
   ```
4. Create a GitHub Release with a tag like `v0.4.0` → auto-publishes to PyPI

---

## 6. Quick Reference — What's on Disk vs. What Ships

```
titan-ultima/                     (repo directory)
├── pyproject.toml                ✅ repo + sdist
├── LICENSE                       ✅ repo + sdist + wheel
├── README.md                     ✅ repo + sdist (PyPI description)
├── titan.toml.example            ✅ repo only (user reference)
├── CHANGELOG.md                  ⬜ create before publish
├── .gitignore                    ⬜ create before publish
├── src/
│   └── titan/
│       ├── __init__.py           ✅ wheel
│       ├── __main__.py           ✅ wheel
│       ├── _version.py           ✅ wheel
│       ├── cli.py                ✅ wheel
│       ├── credits.py            ✅ wheel
│       ├── flex.py               ✅ wheel
│       ├── map.py                ✅ wheel
│       ├── music.py              ✅ wheel
│       ├── palette.py            ✅ wheel
│       ├── save.py               ✅ wheel
│       ├── shape.py              ✅ wheel
│       ├── sound.py              ✅ wheel
│       ├── typeflag.py           ✅ wheel
│       ├── xformpal.py           ✅ wheel
│       ├── py.typed              ✅ wheel
│       └── titan.toml.example    ✅ wheel (bundled config template)
│
├── titan/                        ❌ DELETE (stale leftover from move)
│   └── cli.py                    ❌ DELETE
│
├── pentagram                     📌 git submodule pointer (reference only)
│
├── shapes/                       🚫 game data — never commit
├── globs/                        🚫 game data — never commit
├── map_renders/                  🚫 generated output — never commit
└── test_output/                  🚫 generated output — never commit
```
