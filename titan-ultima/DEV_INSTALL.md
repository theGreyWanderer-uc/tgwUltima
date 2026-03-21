# TITAN — Dev Install Guide

How to set up a clean development environment from scratch.

---

## Prerequisites

- **Python 3.9+** (3.12 recommended)
- **Conda** (Miniconda or Anaconda) _— or use plain `venv`, either works_
- **Git**

---

## Steps

### 1. Clone the repo (skip if you already have it)

```powershell
git clone https://github.com/theGreyWanderer-uc/tgwUltima.git
cd tgwUltima
git checkout titan
```

### 2. Create a fresh environment

**With Conda:**

```powershell
conda create -n ultimaData python=3.12 -y
conda activate ultimaData
```

**Or with venv:**

```powershell
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
```

### 3. Install TITAN in editable (dev) mode

```powershell
cd titan-ultima
pip install -e .
```

This installs TITAN and all its dependencies (NumPy, Pillow, Typer, tomli)
in one step. The `-e` flag means edits to the source code take effect
immediately without reinstalling.

### 4. Verify the install

```powershell
titan --version
# → TITAN v0.4.0

titan --help
# → lists all 26 commands
```

### 5. (Optional) Set up game data

Copy or symlink your Ultima 8 game files into the `titan-ultima/` directory,
or run the interactive setup wizard:

```powershell
titan setup
```

The wizard auto-detects GOG installs, writes `titan.toml`, and optionally
extracts the shape and glob archives.

**Or do it manually:**

```powershell
# Extract shapes and globs from the game archives
titan flex-extract /path/to/U8SHAPES.FLX -o shapes/
titan flex-extract /path/to/GLOB.FLX     -o globs/

# Test a map render
titan map-render -m 5 \
  --fixed /path/to/FIXED.DAT \
  --shapes shapes/ --globs globs/ \
  --palette /path/to/U8PAL.PAL \
  --typeflag /path/to/TYPEFLAG.DAT \
  -o map_005.png
```

---

## Reinstalling after deleting the venv

If you deleted your conda env or venv and need to start over:

```powershell
# Remove the old env (if it still exists)
conda remove -n ultimaData --all -y    # conda
# or: Remove-Item -Recurse .venv       # venv

# Then repeat steps 2–4 above
conda create -n ultimaData python=3.12 -y
conda activate ultimaData
cd C:\_Repos\tgwUltima\titan-ultima
pip install -e .
titan --version
```

That's it. No other setup is needed — `pip install -e .` handles everything.

---

## Building a distributable package

```powershell
pip install build
python -m build
# Creates:
#   dist/titan_ultima-0.4.0.tar.gz          (sdist)
#   dist/titan_ultima-0.4.0-py3-none-any.whl (wheel)
```

## Running without installing

If you just want to run the CLI without installing:

```powershell
pip install numpy pillow typer
python -m titan --version
```

(Run from the `titan-ultima/` directory so Python can find `src/titan/`.)
