```markdown
# My Open Source Contributions

## Exult – Ultima VII Engine Recreation
**Repository**: [exult/exult](https://github.com/exult/exult)  
**My Commit**: [`8eacddb`](https://github.com/exult/exult/commit/8eacddb7dcb03ab39ce4955ab594d448a66d84e0)  
**(committed last week, co-authored with @DominusExult)**

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

### Demo Videos
**Normal usage**  
<video src="videos/testDynamicContainer.mp4" controls width="720"></video>

**Debug visualization mode**  
<video src="videos/testDynamicContainerDebug.mp4" controls width="720"></video>

### Stats
- 17 files changed
- Added: `gumps/Dynamic_container_gump.{cc,h}`, debug system, new intrinsics, docs
- Merged by @DominusExult

**Full repo**: https://github.com/exult/exult  
**Why it matters**: This is a brand-new system that other contributors are already excited to build on.

---

**How to make the videos actually play** (2-minute setup):
1. In your showcase repo, create a folder called `videos/`
2. Upload the two `.mp4` files you originally attached to the PR into that folder (keep the exact filenames)
3. Paste the whole block above into your `README.md`

GitHub will automatically render beautiful inline video players with play/pause, scrubbing, and fullscreen. This is the cleanest and most reliable method in 2026 — no long ugly asset URLs needed.

Copy, upload the videos, and you’re done! Want me to add code snippets from `Dynamic_container_gump.cc` or screenshots next? Just say the word. 🚀
```