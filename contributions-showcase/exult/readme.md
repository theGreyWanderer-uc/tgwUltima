# My Open Source Contributions - EXULT

## Exult – Ultima VII Engine Recreation
**Repository**: [exult/exult](https://github.com/exult/exult)  
**My Commit**: [`8eacddb`](https://github.com/exult/exult/commit/8eacddb7dcb03ab39ce4955ab594d448a66d84e0)

### What I did
I designed and implemented a **complete dynamic container gump system** with snap zones, new Usecode intrinsics, and smart overlap resolution. This gives modders and players far more flexible container UIs in the classic Ultima VII engine.

### New Features
- `Dynamic_container_gump` class with full snap-zone support (perfect for ritual containers and custom layouts)
- Two brand-new Usecode intrinsics:
  - `UI_get_item_gump_position`
  - `UI_set_item_gump_position`
- Debug visualization system (configurable bitmask flags)
- Hybrid priority + axis-aligned split algorithm for resolving zone overlaps

### Bug Fixes
- Fixed empty container positioning bug in `Gump::check_elem_positions()`
- Fixed snap_zones parser bug in `shapevga.cc` (getline delimiter issue)

### Configuration & Integration
- Extended `gump_info.txt` with a new `snap_zones` section
- Updated template files (`data/bg/gump_info.txt` + `data/si/gump_info.txt`)
- Automatic gump type selection based on config
- Full documentation added: [`docs/dynamic_gumps.md`](https://github.com/exult/exult/blob/master/docs/dynamic_gumps.md)

**Full repo**: https://github.com/exult/exult  
**Why it matters**: This is a brand-new system that I hope other contributors are already excited to build on.
