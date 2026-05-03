# Fold Source Mapping

This file records the exact source provenance for the fold-derived component
bundled with TITAN.

## Current bundled source baseline

- Source repository: https://github.com/theGreyWanderer-uc/pentagram
- Upstream base repo: https://github.com/pentagram-u8/pentagram
- Branch: safety-ignore-cleanup-20260501-181009
- Commit: e8f5798c7e593a9f8bb4be1ad8dd454df5a35a0d
- Commit subject: chore: add runtime DLL dependencies for fold tooling

## Key source files used

- tools/fold/*.cpp
- tools/fold/*.h
- tools/fold/module.mk
- module.mk
- Makefile.mingw
- COPYING
- AUTHORS
- README
- win32/Pentagram.iss

## Build entry points

Primary build files define fold targets in:

- Makefile.mingw
- tools/fold/module.mk

Representative target from Makefile.mingw:

- fold.exe: tools/fold/Fold.o plus FOLD_OBJCS

## Rebuild notes (Windows/MSYS2 path used by maintainer)

1. Build command path:
- Repository root where Makefile.mingw is present.

2. Build target:
- make -f Makefile.mingw fold.exe

3. Runtime dependencies currently distributed alongside fold.exe:
- libgcc_s_seh-1.dll
- libstdc++-6.dll
- libwinpthread-1.dll

## Verification checklist

When fold is updated:

1. Update Branch/Commit above.
2. Refresh COPYING from the exact source commit.
3. Verify NOTICE.md, SOURCE_MAPPING.md, and COPYING are present in wheel.
4. Record binary hash in release notes (recommended).
