# Third-Party Notices

This project is primarily licensed under MIT (see LICENSE), but includes
additional third-party components with separate license terms.

## Bundled components with separate licenses

1. Bundled fonts used by font tooling.
- See FONTS_CREDITS.md.
- Includes one font under CC BY-SA 4.0.

2. Fold tooling component derived from Pentagram.
- Location in package: src/titan/third_party/fold/
- License: GNU General Public License, version 2 or later (GPL-2.0-or-later)
- Scope: Applies to the fold-derived component files and binaries, not the
  entire TITAN codebase by default.

## Fold component compliance artifacts

See src/titan/third_party/fold/ for:

- NOTICE.md: attribution and licensing scope
- SOURCE_MAPPING.md: exact source provenance (repo/branch/commit) and
  reproducible build entry points
- COPYING: GPL license text distributed with this component

## Release policy note

When updating bundled fold binaries, update SOURCE_MAPPING.md and refresh
COPYING from the exact source repository commit used for that build in the
same pull request.
