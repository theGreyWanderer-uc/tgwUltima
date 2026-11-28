# Changelog

Notable user-visible features, fixes, documentation and compatibility changes
in **titan-ultima**, grouped by version. Entries marked **Unreleased** describe
work for the next release.

---

## [Unreleased]

### Added

- **Saves started before the Forgotten World patch:** `save-check` and the
  save browser now say when a save misses part of the 1.19G/1.19H fan patch.
  `FWP01` (INFO): the installed maps have the companion fix but the save's own
  copy of the main map does not, so Mariah and Jaana will not come. `FWP02`
  (INFO): Runes and virtue items still at their old floating heights, by
  shrine. Both advise a new game for every fix; neither changes the verdict,
  because the save loads normally. Read from the maps, not from file hashes
  (`titan.u9.fan_patch`).
- **One map size option everywhere:** `--resolution full|75|50|25` on U6,
  Martian Dreams and U8 `map-render`, U8 `map-render-all`, UW2 `map-render`
  and UO `map-export`, as on U7. Whole maps now default to 25% (a crop with
  `--region` stays full size), and file names say the size (`_25pct`). U9's
  `map-render` and `map-atlas` presets now default to `25` too. Pass
  `--resolution full` for the old size.
- **Config problems, found and fixed:** `titan config` now ends with what's
  wrong with titan's config: an older copy that titan reads instead of your
  main config (e.g. a `titan.toml` in the folder you run titan from),
  entries only an older `titan setup` wrote, and paths that no longer
  resolve. `titan config --fix` applies the fixes titan knows: it renames a
  shadowing copy to `.old`, edits a file only after backing it up (`.bak`),
  and extracts U8's map data; it never deletes anything. Other commands print
  one warning line while a copy shadows your main config.
- **`u7 map-render --resolution full|75|50|25`:** renders at a fraction of
  full size. A full-world render (`--full`) now defaults to 25%, about 6000
  px square instead of 25000; pass `--resolution full` for the old size.
  The guided wizard asks for the size too, after the area, and saves at it
  (it used to save at full size only).
- **`u7 map-render` without an area renders the whole world:** given options
  but no `--superchunk`, chunk range or `--full`, it renders the full world at
  25% instead of stopping with an error. The guided wizard now offers the
  full world first when no area was supplied.
- **Front-end contract number:** `titan._meta.CONTRACT` versions what front ends
  such as titan-desktop use from titan, separately from the release number, so
  a front end can check one number instead of probing for features.
- **`u7 map-render --mod`:** renders a mod's or Exult custom game's map from
  its own folders, with its art fixes, without pointing `--map-root` at them
  by hand.
- **Map lists, for front ends:** `titan._meta.list_maps()` lists the maps a
  flavor has and how to render each: Ultima 7's main world and Exult's
  extra maps (a mod's own maps included), Ultima 8's maps with items and
  Ultima 9's regions.
  Ultima 6 and Martian Dreams (the surface and each underground level),
  Ultima Underworld II (each level in `LEV.ARK`, by name) and Ultima Online
  (each facet the client ships, exported whole by `uo map-export`) are listed
  too. The command category "Maps & world" is now called "World".
  Each of a mod's maps says what the mod does to it: edits the base game's
  map (with how many superchunks of layout and objects, and terrain chunks,
  it changes), replaces it, or adds a new one.
- **Flavors, for front ends:** `titan._meta.list_flavors()` lists every way
  a game can be worked on: for Ultima 7, each install as played by Exult
  or by the original DOS game, with Exult's mods and custom games under
  Exult; for Ultima 8, the DOS game's, Pentagram's and ScummVM's saves (with
  whether titan can read each); for Ultima Online, each configured client
  (for example the EA Classic Client and UO Forever), plus clients the
  registry records that no entry names; and for every game,
  the configured install plus copies a store or your `[search] folders`
  hold. Ultima 7's DOS saves (`GAMEnn.U7`) are now listed too.
- **Setup finds games where your launchers installed them:** `titan setup`
  now reads where Steam (every library), GOG (Galaxy and offline installers),
  EA's installer, Ultima Online clients registered the classic way (as UO
  Forever's installer does), Windows' installed-programs list, Heroic and
  Lutris installed each Ultima game, before looking in the usual
  folders, so games in custom libraries and folders are found. It says
  where it found each one (`Found Ultima 9 (Steam): ...`). Nothing goes
  online. A new optional `[search] folders` list in `titan.toml` adds your
  own folders to the search, and the usual folders are now checked on every
  fixed drive, not just C: to G:. For front ends,
  `titan._meta.store_installs()` lists each store's copy as verified,
  registered (listed but incomplete) or missing, and found installs say which
  store they came from.
- **Command categories for front ends:** every command now says what it's
  about (archives, palettes, shapes and art, models, audio, maps and world,
  characters, saves, text, data tables) through
  `titan._meta.command_metas()`, so a front end can group commands without
  guessing from their names.
- **The configured install, for front ends:** `titan._meta.configured_install()`
  returns the install your `titan.toml` selects for a game, with its files
  and any `[<game>.paths]` overrides, and the configured paths that are
  missing. Commands now take their default game folders from it in one
  shared place, now for U6, Martian Dreams, both Ultima Underworlds,
  Ultima 7 (both games), Ultima Online, Ultima 8 and Ultima 9; nothing changes in how the
  commands behave, except that some setup mistakes now exit 78 with the
  setup hint and the missing path, like other setup problems (was 1): a
  `[uo.game] install` naming a missing `[uo.installs.*]` entry, and a
  `[u8.paths]` map file or `[u9.paths]` file that doesn't exist.
- **U8 front-end metadata fix:** the browsers' and `npc-animation-report`'s
  `--shapes` (and `map-browse --globs`) are now described as the
  `U8SHAPES.FLX` / `GLOB.FLX` archives they take, not as extracted folders.
- **Every file and folder input is described for front ends:** each
  command's file and folder parameters now say what they take (a game file
  or folder from the install, the user's own file or folder, a save, a
  working folder or a palette) through `titan._meta.command_metas()`, and
  install inputs name the install file that fills them (`resources`, e.g.
  `u7 shape-export FILE` → `shapes`). A new `install-dir` kind covers
  `--gamedir`, U7 `--static` and similar folders. A test fails when a new
  file or folder parameter has no kind.
- **Update check:** `titan --version` now tells you when a newer titan is
  on PyPI, and how to update. It asks PyPI at most once a day, sends nothing
  about you, and gives up quickly when you're offline. Ordinary commands
  never check. Set `TITAN_NO_UPDATE_CHECK=1` to turn it off. Front ends can
  ask too, with `latest_release()` and `is_dev_build()` in `titan._version`.
- **Front-end metadata for every command:** the 70 commands that had no
  `@meta` tag now have one, so `titan._meta.command_meta()` describes every
  visible command. Most of them print a report (`results=("text",)`): the
  U9 `-info`/`-list`/`-show` inspectors, U6 `lib-list`, `object-list`,
  `actor-list` and `flags-*`, `u8 save-list`, `uw2 object-info`, and root
  `flex-info`, `flex-list` and `config`. Some also say what their
  parameters mean: `u9 save-check --json` is an output file, `u7 map-create
  --output-root` and `dialogue prepare --workdir` are output folders, and
  `dialogue validate`/`launch --workdir` read the folder `prepare` writes.
  A new test fails when a visible command has no tag.
- **Ultima Underworld in setup:** `titan setup` now finds Ultima Underworld
  and Ultima Underworld II installs, including both games inside a GOG
  "Ultima Underworld 1+2" folder, and writes `[uw1.game]` / `[uw2.game]`.
  `titan config` shows `[uw1.game]` too.
- **One way to find installs, for every game:** front ends can find and check
  installs without running setup's prompts. `titan._meta` now has
  `find_installs(game_id)`, `inspect_install(game_id, path)`,
  `discover_installs(game_id, path)` and `install_candidates(game_id)`, which
  return `Installation` records (root, resources found, problems, settings),
  and `install_config(install)`, which gives the `titan.toml` section to
  write. Every game with a config section supports them: U6, Martian Dreams,
  UW1, UW2, U7 Black Gate and Serpent Isle, U8, U9 and UO. Setup uses the same
  code, so the CLI and front ends agree on what counts as an install.

### Changed

- **`titan setup` prepares U8's maps:** it extracts U8SHAPES.FLX and GLOB.FLX
  into titan's `u8/shapes` and `u8/globs` working folders when they're empty,
  so map commands (and front ends) find them ready.
- **U6 and Martian Dreams `map-render` write into titan's exports:** an
  omitted `-o` used to mean a file in the current folder; it is now
  `<data folder>/<game>/exports/map-render/` and is reported to front ends.
- **UW2 `map-render` and UO `map-export` report each PNG:** front ends that
  read `TITAN_RESULTS_FILE` get the images, not just the folder, also when
  the folder is titan's own default.
- **U7 map file names name the map:** `u7 map-render` and `u7 map-export-json`
  now name an omitted output after the game and map number
  (`u7_si_map01_full_classic_25pct.png`, `u7_bg_map00.json`), so renders of
  different maps no longer overwrite each other.

- **Library code no longer prints:** saving a Flex archive, reading a
  damaged one, importing an oversized U7 frame and writing animation
  metadata now report through logging, so code using titan as a library
  gets no stray output. The commands print the same lines as before, except
  that these warnings now start `Warning:` (was `WARNING:`), like titan's
  other warnings. Flex imports still ask whether multi-frame U7 shapes
  animate; library callers pass a `choose` callback or an explicit choice.
- **Font creation without the wizard:** the `u7 font-create` wizard now
  lives in `titan.fonts.wizard_ui`, and `titan.fonts.wizard` holds the work
  itself with no prompts or printing. Front ends and scripts can build a
  font from recipe values in memory (`config_from_recipe_data()`, then
  `create_font()`), or step by step (`render()`, `mapped_glyphs()` for a
  preview, `encode()`, `write_outputs()`). The command's output is
  unchanged. `font-create` also reports the shape and archive it writes
  through `TITAN_RESULTS_FILE`.
- **Option names now match across games.** The old spellings still work, and
  `--help` shows only the new ones:

  | Old | New | Where |
  |---|---|---|
  | `--gamedir` | `--game-dir` | U6, Martian Dreams, UW1, UW2 |
  | `--savegame` | `--save` | Martian Dreams |
  | `--nonfixed` | `--save` | U8 (U9's `--nonfixed`, a region file, is unchanged) |
  | `--gamedat` | `--save` | U7 commands that read a GAMEDAT folder or Exult save |
  | `--output` | `--output-dir` | Commands that write a folder of files; `-o` is unchanged |
  | `--output-root` | `--output-dir` | `u7 map-create`, `u3 map-create` |
  | `--json` | `--format json` | `uw1 texture-info`, `uw2 map-verify`, `uw2 shape-info`, `u7 save-list` |
  | `--json FILE` | `-o/--output FILE` | `u9 save-check` |

  Front ends reading `@meta`: parameter names are unchanged except the
  four `--format` commands above, whose `json_output` is now `output_format`.
- **U9 NPC commands' `--save` flag** is no longer tagged as a save for front
  ends: it's an on/off switch saying FILE is a save, not a save to pick.
- **Config loading:** titan's U8 code now reads `[u8]` directly, and loading
  a config without U8 settings no longer imports the U8 package. The
  top-level `[game]`/`[paths]` copy of `[u8]` is kept for older readers
  outside titan but is deprecated.
- **Clearer errors and exit codes.** titan's own errors now print as one
  `ERROR:` line instead of a traceback, and the exit status says what kind of
  problem it was: `78` titan isn't set up for this (no install configured, a
  missing configured folder, or an invalid `titan.toml`, with a hint to run
  `titan config` / `titan setup`), `65` a damaged or unexpected input file,
  `66` a missing file, `69` unsupported here (or an optional library is
  missing), `74` a read/write failure, and `70` a bug in titan (the traceback
  is still printed). Before, most of these exited `1`. An invalid
  `titan.toml` used to crash with a traceback; it's now reported. For code
  using titan as a library, every game's error class now derives from
  `titan.errors` (`TitanError`, `ConfigError`, `InvalidDataError`,
  `UnsupportedError`), and they keep the built-in types callers already catch.
- **Default export folders no longer depend on where you run titan.** The U7
  and U8 browsers, `u8 world-query`/`egg-query`, `u8 npc-animation-report`
  and `u9 save-browse` used to write to a `titan-out/` folder in the current
  directory when no `-o` is given; UO exports without a configured output
  used `uodata/` there. They now write to titan's data folder, under
  `<game>/exports/<command>` (`titan config` shows the data folder), and
  still print where things went. Passing `-o` works as before.

- **U7 wizards split into logic and terminal halves.** The interactive parts
  of `shape-create`, `map-render`'s guided mode, `world-query`, `egg-query`
  and `container-browse` now live in `titan.u7.shape_wizard_ui`,
  `map_wizard_ui`, `world_workflow_ui`, `eggs_ui` and `container_ui`; the
  original modules keep the conversion, rendering and query code, which no
  longer prints. What you see in the terminal is unchanged. For code that
  imported them: `run_wizard` (and `run_from_config`, `show_preview` for
  shapes) moved to the `_ui` modules.
- **Library progress and warnings go through `logging`.** titan's library
  code logs to `titan.*` loggers; the CLI shows INFO lines as before and
  warnings/errors as `Warning: ...` / `ERROR: ...` on stderr. A test now
  stops new `print`/`input`/terminal-toolkit use in library modules.

### Added (front ends)

- **Option sets:** `@meta(option_sets={title: options})` groups options with
  no parent of their own behind one titled switch (U8's `--no-*` type-flag
  exclusions, UW2's geometry tuning). U8, U9, UW2, UO and Martian Dreams map
  commands now lay their options out like U7's; U8 `map-render --view`, UW2's
  orientation, texture transform, model style, solid fill and grid
  coordinate options, and U9's object source and footprint style are now
  Choices.
- **Option layout:** `@meta` can say which options belong under another
  (`option_groups`), which replace a switch while it is off
  (`option_alternatives`) and what an omitted option amounts to (`defaults`),
  so front ends can nest them. `u7 map-render` is the first command tagged.

- **Run results file:** set `TITAN_RESULTS_FILE` to a path and titan writes
  `{"outputs": [...], "exit_code": N}` there when a command ends, listing what
  it wrote. `flex-extract` and `uw1 texture-export` report so far; more
  commands will follow. `titan._config.export_dir(game, name)` gives the
  default export folder.

### Fixed

- **U8 maps with an old setup's default save:** early `titan setup` releases
  wrote `[u8.paths] nonfixed = "U8SAVE.000"` whether or not that save
  existed, so map commands failed with "No such file" on installs without
  slot 0. That default now means the base world unless the save is there.

- **Map commands wrote into the current folder or the game install:** with no
  `--output`, Ultima 7's `map-render`, `map-render-json` and `map-sample`,
  Ultima 8's `map-render` and `map-sample`, and Ultima 9's `map-render` and
  `map-export-glb` wrote to the current folder (Ultima 9: beside the terrain
  file, inside the game's install). They now write to titan's exports folder
  for the command, like other commands, and front ends are told the file.
- **Exult custom games listed under both parts of Ultima 7:** a custom game
  (an `exult.cfg` game such as one made in Exult Studio) now appears only
  under the part its own data comes from, Serpent Isle when it has Serpent
  Isle's paperdolls or speech, the Black Gate when it has the Black Gate's
  endgame or speech, and under both only when its data says neither.
- **Ultima 7 installs found as the wrong game:** setup and install detection
  could list a Serpent Isle folder as a Black Gate install (or the reverse)
  when the folder's name didn't say which game it was, such as
  `ultima7si_no_exult`. titan now tells the two apart by files only one game
  ships (`SISPEECH.SPC` and `PAPERDOL.VGA` for Serpent Isle; `ENDGAME.DAT`
  and `U7SPEECH.SPC` for the Black Gate), then by Exult's settings and the
  folder name. A folder you choose yourself still counts as the game you
  asked for when nothing says otherwise.
- **`u7 monster-report --game si`:** the world-object part of the report
  (`monster_world_objects.csv`) was read with Black Gate's shape metadata;
  it now uses Serpent Isle's.
- **`u7 monster-report --mod` and `u7 gamedat-info --mod`:** a mod name that is
  not configured, or a mod with no saved game state yet, quietly used the base
  game's GAMEDAT. Both commands now stop with an error naming the mod (and, for
  an unknown name, the configured ones).
- **U7 mod save folders:** `titan setup` writes each mod's save folder as
  `saves` under `[u7bg.mods."<name>".paths]`, but the world picker only read
  `savegame`, so the setting was ignored. The picker now reads `saves` (and
  still accepts `savegame`), and `titan config` checks it as a save folder.
- **`u7 monster-report` and `u7 gamedat-info` without `--mod`:** when Exult's
  profile held a played game, they read it even if `[u7bg.paths] gamedat` /
  `[u7si.paths] gamedat` named another folder. A configured gamedat now wins, as
  in every other command.

### Added

- **`titan.protocols`:** small interfaces the games share, for cross-game tools.
  `Palette` (`colors`, `to_flat_rgb()`, `to_pil_image()`) is met by every
  game's palette (U6 and MD, U7, U8, U9, UW1, UW2); `IndexedArchive`
  (`entry_count`, `read(index)`, `None` for an empty slot) by the U8/U7 Flex
  readers, U9 FLX, U6 `.LIB` and UW2 `.ARK` archives.
- **`titan u7 mods`:** lists a game's mods and Exult custom games, with the
  names `--mod` takes, whether each has been played, and its paths
  (`--format json` for every path). `--mod` completes these names in the shell.

### Changed

- **Exit codes:** commands now exit with the kind of problem they hit instead
  of `1`: `65` for a damaged or unexpected input file (including a malformed
  plan or recipe), `66` for a missing file, `73` (new) for an output that
  already exists without `--force`/`--replace`, `74` for a read/write failure
  and `78` for setup problems. `1` now means an error of none of those kinds,
  usually a bad option value. The messages are the same. See "Errors and exit
  codes" in `cli_reference.md`.
- **`TITAN_RESULTS_FILE`:** every command with an output file or folder now
  reports what it wrote (the file, or the folder and the files written into
  it), not only the three that did before.
- **Old U8-only config layout:** top-level `[game]`/`[paths]` (titan's
  original U8-only `titan.toml`) are read as `[u8]`, and `titan setup` now
  moves them under `[u8]` (keeping a `.bak`). The loaded config no longer has a
  top-level `game`/`paths` copy of `[u8]`: code reading
  `get_config()["paths"]` should read `get_config()["u8"]["paths"]`
  (`titan._config.cfg()` already does). `titan config` notes a file that still
  uses the old layout.
- **Faster `import titan`:** the names `titan` re-exports (`FlexArchive`,
  `U8Shape`, `U7Palette`, ...) now load on first use, so importing any titan
  module no longer loads the U8 and U7 readers (`import titan._meta`: 0.35 s
  to 0.06 s). `from titan import U8Shape` works as before.
- **Deprecated:** the old top-level U8 modules `titan.palette`, `titan.map`,
  `titan.shape`, `titan.save`, `titan.credits`, `titan.sound`,
  `titan.typeflag` and `titan.xformpal` warn on import; import from `titan.u8.*`
  (or `from titan import ...`) instead.
- **UW1/UW2 palettes:** `to_flat_rgb()` (bytes) and `to_pil_image()`, as in the
  other games; `flattened_rgb()` and `to_swatch_image()` still work. U8 palette
  read errors are `U8PaletteError` (still a `ValueError`).
- **Code layout (no command changes):** U6 and UW2 commands moved from one
  `cli.py` into `cli/` packages split by topic; the loose U7, U8 and MD
  `*_cli.py` modules moved into their `cli/` packages; the U7 edit-plan readers
  (`ireg-tree-edit`, `actor-rewrite`, `save-repack`) are now
  `titan.u7.edit_plans`.
- **`titan setup` and Ultima Online:** setup now finds and checks the Classic
  Client the same way as the other games: your configured base is the default,
  a folder without client files is rejected (keeping the current setting), and
  a corrected base is proposed like any other. Before, it offered only the
  detected client and saved whatever path was typed.
- **Default output folders:** 24 commands that wrote to a folder (or file) of
  their own name in the current directory when `-o` was omitted now write to
  titan's export folder, `<data folder>/<game>/exports/<command>`, as the
  browsers already did, and print where. They are U6 `tile-export-all`; U7
  `map-export-json`, `map-inventory`, `palette-export`, `shape-cycle-scan`; U8
  `map-render-all`, `map-sample-all`, `shape-convert-u7-all`; U9
  `texture-export-all`, `icon-export-all`, `model-export-all`, `map-atlas`,
  `animation-library-export`, `script-research-export`, `dimension-csv`,
  `spaces-csv`, `treedat-csv`, `areas-csv`; UW2 `map-render`, `map-3d-render`,
  `map-3d-export`, `map-stack`, `model-render`, `model-export`. Pass `-o` to
  write somewhere else. Commands whose default is the current folder itself
  (most extract commands) are unchanged.
- **Ultima 7 mods, one list everywhere:** `--mod`, the world picker (shape,
  NPC, monster and palette browsers, the map, shape and font wizards) and
  `titan setup` now find mods the same way: their `.cfg` descriptions and
  folders in Exult's and the install's `mods` folders, `[u7xx.mods]` tables
  and Exult custom games.
  - `--mod` accepts Exult custom games too, and any letter case.
  - The picker shows each mod's title with the name `--mod` takes, e.g.
    "BLACK GATE KEYRING (Keyring)".
- **Ultima 7 GAMEDAT and saves, one rule everywhere:** with no
  `[u7bg.paths] gamedat` / `[u7si.paths] gamedat` set, every U7 command, the
  world picker and `titan setup` now use Exult's live game state (`exult.cfg`'s
  `gamedat_path`, else Exult's profile folder) when it holds a played game, then
  the install's own `gamedat`. Before, most commands used only the install's
  `gamedat`, and failed when there was none. Exult's save folder (`exult.cfg`'s
  `savegame_path`, else its profile folder) is now where Exult saves are listed
  from, so saves Exult wrote there are found even when GAMEDAT is configured
  elsewhere.

## [0.8.0]

### Added

#### Setup

- **Ultima 9 on Steam:** `titan setup` now finds Ultima 9 in Steam libraries
  on drives C to G, as well as GOG and manual installs.
- **One data folder for titan's working files:** files titan extracts for
  its own use now live in one place, `%LOCALAPPDATA%\Titan` on Windows or
  `~/.local/share/titan` elsewhere, whichever folder you run titan from.
  titan-desktop uses the same folder, so extracting once serves both. Set
  `TITAN_DATA` to move it; `titan config` shows where it is.

#### Ultima 7

- **Black Gate places:** `u7 places-export -o FILE` writes one JSON file
  naming every town, building, dungeon and outdoor area in Britannia: each
  building's town, outline, doors and signs, and the NPCs who live or work
  there at the start of a new game. Names follow the printed town maps.
  Serpent Isle will follow.
- **Read your Exult saves directly:** `u7 map-render`, `map-inventory`,
  `world-query`, `container-browse`, `egg-query` and `monster-report` take
  an Exult save file (`--gamedat exult00bg.sav`) as well as a GAMEDAT
  folder, so you can look at any saved game without loading it first.

#### Ultima 8

- **Pick saves by slot:** the map commands' `--nonfixed` and
  `u8 save-browse` take a slot number, so `--nonfixed 3` reads
  `U8SAVE.003` from your save folder. `u8 save-browse 3 --compare 0` compares
  two slots. File names and full paths still work.

### Changed

- **Python 3.10 or newer is required.** titan already needed it and
  wouldn't run on 3.9.
- **Ultima 8 maps set themselves up:** the first time a map command needs
  shapes or globs, it extracts `U8SHAPES.FLX` and `GLOB.FLX` from your
  install into titan's data folder without asking, and later runs reuse
  them. Before, it asked you to type the archive's path, and the folders
  only worked from the folder you extracted them in. Folders you named
  yourself with `--shapes`/`--globs` are still only filled after a yes.
  `titan flex-extract U8SHAPES.FLX` and `GLOB.FLX` from your install also go
  to the data folder; other archives extract to the current folder as
  before.
  - **If you extracted before:** your old `shapes`/`globs` folders are no
    longer read. The map commands extract again on first use, and you can
    delete the old folders.
- **Ultima 8 saves in `titan.toml`:** setup now records your save folder
  (`[u8.paths] savegame`) rather than one save. `nonfixed` is an optional
  default you set yourself; without it, the map commands draw the fixed
  world with no save's objects on it. `titan setup` also writes
  `glob = "GLOB.FLX"`.
- **`titan config` is clearer:** shapes and globs that haven't been extracted
  yet show as `[not extracted yet]` instead of `[NOT FOUND]`.

### Fixed

- **Cancelled wizards no longer look successful:** pressing Ctrl+C in a
  wizard or browser, or its input running out before it finished, now exits
  with status `130` and prints `Cancelled.` on stderr. Before, most wizards
  exited `0`, as if they had finished, and a few exited `1` with Typer's
  `Aborted!`. Choosing a wizard's Quit option still exits `0`. This covers
  every wizard and browser, `titan setup` and `dialogue copy`.
- **U7 query commands without a terminal:** `titan u7 egg-query`,
  `world-query` and `container-browse` crashed when their input or output
  was piped or captured. With no filter options they start a wizard, and the
  wizard can't prompt without a terminal. They now run unfiltered instead and
  print every egg, a world summary, or every container. Your terminal still
  gets the wizard.
- **Output that can't show some characters:** when titan's output goes to a
  file or pipe on Windows, characters such as the wizards' `─` separators
  now print as `?` instead of crashing the command. Set
  `PYTHONIOENCODING=utf-8` to keep the real characters.
- **Ultima 8 setup on GOG:** `titan setup` wrote `nonfixed = "U8SAVE.000"`
  without checking it existed, so on GOG installs, whose saves start at 001,
  the map commands failed. Re-running setup removes that value when the file
  is missing; a `nonfixed` you set yourself is kept.
- **Ultima 9 with newer Typer:** with Typer 0.29 or later, U9 commands that
  read game files (`u9 fixed-objects`, `u9 nonfixed-entities`, ...) stopped
  with an error at once. They now work with old and new Typer.

## [0.7.9]

### Added

#### Setup

- **Ultima 6 and Martian Dreams setup:** `titan setup` now finds U6 and
  Martian Dreams installs from GOG Galaxy, GOG offline, Heroic and common
  manual folders. `titan config` shows what was found and checks it is still
  there. U6 and MD commands use the configured game automatically;
  `--gamedir` still overrides it.
- **Ultima 9 setup:** `titan setup` finds common and nested U9 installs and
  checks the texture archives and palette before saving their paths.
  `titan config` shows the U9 settings.

#### Martian Dreams

- **Map rendering:** `md map-render` draws the surface and underground maps,
  with objects and characters, from a new game or a DOS save. Saved water and
  power states show the right artwork, and optional lighting and palette
  cycling match the original game.
- **Game data reports:** `md actor-list`, `md gamestate-dump`,
  `md converse-dump`, `md converse-report`, `md look-dump` and `md book-dump`
  show characters, game state, conversations, object names and books. They
  only read the game files and never change them.

#### Ultima 7

- **Save editing:** new tools edit U7 saves and world files without touching
  the originals:
  - `u7 ireg-tree-edit` moves, deletes and creates objects in the world and
    in containers, and can change an object's shape or frame.
  - `u7 ireg-rewrite` changes individual object details such as frame,
    height, position within a chunk, quality and flags.
  - `u7 actor-rewrite` edits NPC and monster stats, names, schedules, flags
    and other character details. Inventories are kept as they are.
  - `u7 save-repack` puts edited files back into a save archive (Flex or ZIP).
    The edit tools can also write directly into a save.

  You write the changes as a JSON plan, based on what `u7 ireg-tree` and
  `u7 actor-headers` report. Each plan is checked against the exact file it
  was made for, so an out-of-date plan is refused. `--dry-run` shows the
  changes without writing anything, and output always goes to a new file.
  These tools check the file structure, not whether the game will accept the
  result, so test edited saves in the game.
- **World object reports:** `u7 ireg-dump` exports one superchunk's objects
  with their scheduled scripts, attributes, text and readied slots, including
  bodies, spellbooks, virtue stones, barges and other special objects.
- **Game data inspection:** `u7 static-data-dump` covers container, gump,
  weapon, ammo, armour and paperdoll tables, with mod patches and original
  DOS tables (`--data-format retail`). `u7 usecode-disasm` can annotate and
  check scripts, export symbols and show the original version of a function
  a mod has replaced.
- **Map inventory:** `u7 map-inventory` counts every ground tile and object a
  map uses, including fixed objects, starting items and, optionally, container
  contents. Results are ranked by how often each shape and frame is used, and
  written to CSV, JSON and a filterable page with sprite previews. `--sc`,
  `--tile-rect` and `--cx0/--cy0/--cx1/--cy1` limit it to part of the map and
  list every placement there.
- **Container previews:** containers can be shown as their in-game inventory
  artwork, with saved or random item layouts and labels for locked
  containers. Works with BG, SI and mods, and exports HTML, PNG and JSON.
- **Animated imports:** when creating or importing shapes you can choose
  whether multi-frame artwork animates. Scripts use `--animate` /
  `--no-animate` or `conversion.animated` in recipes.

#### Ultima 8

- **Shape browser:** `u8 shape-browse` covers world, gump and font shapes and
  standalone shape files, with search, property filters, animation playback
  and weapon/glow overlays. Exports PNG, GIF, JSON and contact sheets.
- **NPC browser:** `u8 npc-browse` lists characters from saves, GAMEDAT or
  loose files, with names, search, filters, sprite previews, equipment and
  animations. Exports HTML, CSV and JSON.
- **NPC animation reports:** `u8 npc-animation-report` shows one NPC or all
  NPCs with named actions, contact sheets and offline HTML/CSV reports. You
  can supply your own character names in a CSV.
- **Save browser:** `u8 save-browse` lets you search, view and extract save
  contents, including NPCs, equipment, animations and saved game state.
  Compare two saves and export offline reports. Game graphics are not needed
  to inspect saved state.
- **Map browser:** `u8 map-browse` inspects maps, objects and containers,
  with filters, colour overviews and isometric previews. Exports HTML, PNG,
  CSV and JSON.
- **Container browser:** `u8 container-browse` shows nested inventories and
  who owns them on every map. Filter containers and their contents
  separately, check quantities and equipment, and preview items and
  container artwork with saved or random layouts. Exports HTML, CSV, JSON
  and images.
- **Inventory access:** NPC details open their inventories and container
  previews directly, including empty inventories.
- **World and egg search:** `u8 world-query` and `u8 egg-query` search all
  maps, including inside containers, with teleport links and monster spawn
  details. Jump to related shapes, NPCs and inventories, and export HTML,
  CSV, JSON and PNG previews.
- **Palette browser:** `u8 palette-browse` shows numbered colour swatches,
  RGB matching, gradients and palette effects. Exports HTML, CSV, JSON,
  effect sheets and the original palette data.
- **Saved-state reports:** `u8 flags-dump`, `u8 avatar-dump`, `u8 gumps-dump`,
  `u8 kernel-dump`, `u8 itemcach-dump` and `u8 npcdata-dump` show saved game
  state as text, JSON or CSV. `u8 save-info` gives an overview including the
  game clock, and `u8 save-diff` compares flags, items, NPCs, the Avatar, the
  interface and running processes between two saves. Some process details
  are only decoded for supported game versions.
- **Map data reports:** `u8 fixed-dump` and `u8 nonfixed-dump` list map
  objects, including nested inventories, with filters and text/JSON/CSV
  output.
- **Animation data reports:** `u8 anim-dump` and `u8 wpnovlay-dump` show
  character actions, directions, movement and weapon/glow overlays, with
  filters and text/JSON/CSV output.

#### Ultima 9

- **Save browser:** `u9 save-browse` lets you page through and filter save
  contents, view and extract files, and check maps, NPCs, saved activities
  and save problems. Exports offline reports. Backups include the save, its
  loose files and the save selector. Uses the configured game when no source
  is given.
- **Export all textures:** `u9 texture-export-all` exports every texture at
  full size from the best quality available, with numbered PNGs, a manifest
  per archive and a progress bar. `--all-mips` adds the smaller versions and
  `--all-tiers` adds the other quality levels.
- **Shorter commands:** U9 commands find game files from your settings, so
  you can type just a filename or leave out a known archive and give only the
  ID or search term. Files you name yourself are used exactly as given.

#### Ultima Online

- **Facet maps:** `uo map-export` draws each facet as an overview map, one
  pixel per tile, with optional map patches, terrain-only output and
  heightmaps.
- **Map views:** `uo map-render` draws any location the way the client
  does, with terrain, buildings, hues and see-through water. Roofs, statics,
  hues and shading can each be turned off.
- **Zoomable whole-facet maps:** `uo map-tiles` renders a whole facet at full
  client detail into a zoomable map with an offline viewer (pan, zoom, cell
  coordinates, go-to). Rendering uses several processor cores and can resume
  after an interruption.
- **Map inventory:** `uo map-inventory` counts every terrain and static tile a
  facet uses, ranked by how often each appears, with its name, a category
  (wall, floor, roof, door…), height, spread and an example location. Statics
  are also grouped by name, since one name such as `plaster wall` covers many
  tiles. Writes CSV, JSON and a filterable page with art previews.
- **House footprints:** `uo house-footprints` combines a RunUO/ServUO house
  list with the client's house designs and exports each house's footprint,
  foundation, border and yard, plus a sheet showing every footprint.
- **House capacity:** `uo house-capacity` applies RunUO/ServUO house placement
  rules and regions to a whole facet. It reports how much land allows a
  house, fills it with as many houses as fit, and draws an overlay map.
  Results match a live ServUO shard. An offline viewer shows legal ground,
  why each spot is refused, regions and placed houses. A second, mixed layout
  puts small houses near towns, larger ones further out and workshops near
  mountains.
- **Server profiles:** house tools can read a server's regions and house list
  from one JSON server profile (`--server-profile`, or `server_profile` in
  `titan.toml`). Without one, houses come from the client's designs and
  regions are skipped with a warning.
- **Several installs:** you can configure more than one client install as
  `[uo.installs.<name>]`, each with its own output folder and settings, and
  use the name in any `uo` command (`titan uo map-export uof`).
  `titan config` lists them.

### Changed

- **U6 and MD hidden objects:** map renders now leave out invisible objects by
  default. Add `--show-invisible` with `--objects` to include them; U6's
  overlap check accepts the same option.
- **U6 overlap check:** `map-audit-zorder` now reports which objects overlap,
  which drawing rule decides it and how many overlaps there are, matching the
  original game's drawing order.
- **U7 and U8 container browsing:** result lists stay in place while you open
  nested containers, containers and their contents can be filtered separately,
  and items are easier to tell apart. The existing U7 tree and CSV options
  still work.
- **U8 previews:** shape, NPC and equipment previews keep full detail when
  there is room and show their size. Animation playback fits the terminal and
  adjusts when it is resized, with fewer visible gaps between colours.
- **U8 labels:** browsers and exports show character names and explain more
  NPC and animation flags. Unknown values are still shown.
- **U9 save-check advice:** `save-check` now gives advice for each problem it
  finds, including in `--json` output. Its verdicts are unchanged. Map
  comparisons that can't run are shown as notes.
- **Exports never overwrite:** U7 and U8 browser reports are saved under new
  names instead of replacing earlier reports, and never change game files.

### Fixed

- **U6 map rendering:** objects, tiles and terrain now stack in the same order
  as the original game, replacing earlier special cases. Large sprites at the
  edge of a cropped map are no longer cut off, and invalid map areas are
  refused before anything is written.
- **U7 and U8 container menus:** menus show complete item IDs and keep your
  filter text, and U7 IDs work in upper or lower case. U8 exports include
  every active filter and record what was exported.
- **U8 shape import:** solid pixels no longer turn transparent when their
  closest palette colour is the last entry (index 255). Also fixes U8-to-U7
  conversion.
- **U8 archives built or edited by Titan:** archives Titan builds, repacks or
  edits now keep their internal checksum correct. U7/Exult archives keep
  their header information.
- **U8 maps and inventories:** the current map's live state takes priority
  over stored copies. Maps that only have movable objects are now included,
  items inside inventories no longer appear on world maps, and mirrored
  sprites are positioned and layered correctly.
- **U9 music in saves:** save reports label the saved music field as `key`
  (the trigger that started the music) instead of `track`; `track` still
  works as an alias. Trigger reports now show the 1.19H patch's Minoc music
  fix.
- **UO house designs:** Titan now works out the record layout of `multi.mul`
  once per file and warns when it can't tell, instead of guessing for each
  house, which could misread some files. `multi-export` adds
  `--container auto|uop|mul` and reports which file and layout it used.
- **Windows image previews:** minimised viewers are restored and previews
  come to the front, including reused Photos windows. If a viewer can't
  open, Titan says so and shows where the image was saved.

---

## [0.7.8]

### Added

- **U7 browsers:** expanded shape, palette, monster, NPC and save browsing
  with game/mod selection, search, filters, colour previews and report
  exports. Shape browsing includes physics/equipment properties, playback,
  PNG/GIF exports and JSON reports; NPC views include schedules and nested
  inventories; monster views include equipment and spawn eggs.
- **U7 map-render wizard:** added game/world and map selection, render
  options, a reduced preview before full rendering, progress and safe saving.
- **U9 translation imports:** added `text-import` and `typename-import` to
  rebuild archives from `text-export` and `typename-csv` CSVs, including
  dialect copies. Imports retain entry numbering and references; type-name
  text supports Windows-1252 characters. Library import methods are available
  as `U9TextArchive.rebuilt()` and `U9TypeNames.rebuilt()`.
- **U9 NPC details:** `npc-show`, `npc-classes` and `npc-csv` now include
  readable combat/movement categories, weapon/material names, known spells
  and routine hours. CSV adds `*_name`, `routine_*_clock` and `known_spells`
  columns; the library exposes matching names and clock-time helpers.
- **U9 save decoding:** expanded saved-process inspection to cover movement,
  pathfinding, spells, NPC activities, object animations, cameras and timers,
  plus subsystem state such as NPCs, combat, weather, lights, UI and sound.
  `save-check --json` adds `process_sections` details; `PRC02` warns when
  subsystem sections cannot be read. Temporary-camera parsing remains
  unverified against a save containing that record and is flagged by `PRC03`.
  `PRC04` notes the game's failure to resume saved creeper plant growth.
- **U9 trigger and activity inspection:** added decoded operands, target
  selection, branch diagnostics, named action kinds, durations and special
  actions to `trigger-show`, `activity-show` and `script-research-export`.
  `nonfixed-entities` adds a `Triggers` column; the library also exposes
  world-object trigger IDs. Activity reports flag missing action steps.
  Runtime execution of special actions remains unverified.
- **U9 dialogue keys:** added `text-keys-info`, `text-key-lookup` and
  `text-keys-export` for dialogue-key lookup, export and target checks.
- **U9 colour tables:** added `shade-info`, `shade-csv`, `color-cube-info`,
  `color-cube-lookup` and `color-cube-csv` for historical authoring data.
  These optional files are not loaded by the retail game.
- **U9 acoustic environments:** added inspection and CSV export for
  `sfxenv.flx`, including validation and reporting of unusual records.
- **U9 animation exports:** added clip labels, animation events, interpolated
  poses, single-clip OBJ/STL pose exports and animated-model bundles with GLB.
- **Ultima Underworld textures:** added `titan uw1` texture inspection and
  batch PNG export, with descriptions, contact sheets and CSV/JSON manifests.

### Changed

- **Interactive menus:** show action and paging hotkeys throughout browsers.
- **U7 previews:** solid colour cells reduce font seams in NPC and shape
  previews, including playback.
- **U9 trigger documentation:** corrected how the retail loader handles
  unterminated short triggers; exported diagnostics retain the on-disk data.

### Fixed

- **U7 NPC navigation:** next/previous navigation works after searching for
  an individual NPC.
- **U9 decoding:** corrected trigger operands, movement timing, activity
  arguments and combatant field labels, including saved NPC health values.
  Trigger reports use corrected field names including `time_per_unit`,
  `below`, `instance_id`, `subtract` and `source_only`; `search_radius`
  is reported in world units.
- **U9 save checking:** valid saves are no longer rejected for unused
  pathfinder values or particle-camera fields.
- **U9 JSON reports:** `IntegrityReport.to_dict()` and `save-check --json`
  produce strict JSON, representing non-finite saved values as `null`.
- **U9 animation records:** corrected signed fields, active-part reporting
  and playback length; unusual records and trailing data remain inspectable.
- **U9 model records:** corrected model, collision and material parsing;
  orphaned indexed records are explicitly identified as forensic data.
- **Flex updates:** archive updates retain comments and U7 header information,
  preserving compatibility with U7 palette inspection.

---

## [0.7.7]

### Changed

- Improved U7 game, mod, world, map and archive selection.
- Added moving menu highlights, Tab hints and path completion.
- Improved PNG shape previews and palette selection for Exult games.
- Added colour font previews, custom preview text, gradient swatches and
  palette-aware ramp selection.
- Simplified setup by removing the extraction prompt and closing command
  suggestions.

### Fixed

- Corrected nested U7 install detection and config path reporting.
- Font and world workflows use the selected game's base, patch and save data.
- Archive updates preserve formats and allocate shape slots against combined
  base and patch data.

---

## [0.7.6]

### Added

- **U9 world and maps:** added terrain, object and water inspection, textured
  2D maps and atlases with grids, GLB export, and 3D renders with resolution
  presets.
- **U9 graphics:** expanded model/animation inspection, material reports,
  texture decoding and replacement, terrain panels and palette tools.
- **U9 archives and audio:** added FLX pack/repack, audio metadata and link
  reports, WAV/native extraction, and single/batch sound replacement.
- **U9 scripts and saves:** added trigger/activity inspection, Ghidra research
  exports, NPC/savegame and highway tools, and book/text search and export.
- Added a `glb` installation extra for GLB exports.
- **Sparse U7 mod patches:** `titan u7 map-render` fills missing patch shapes
  from the configured BG or SI base archive.

### Fixed

- Corrected U9 archive/type detection, sparse fixed-map enumeration and
  texture selection. Improved handling of truncated textures, multi-frame
  icons, duplicate model limbs and Windows paths.
- Corrected GLB sea-level depth fighting and non-finite model UVs.

---

## [0.7.5]

### Added

- **U7 map JSON:** added `titan u7 map-export-json` for terrain, map layout,
  fixed objects and metadata, and `titan u7 map-render-json` to render those
  documents without the original map files. Supports cropped, tiled,
  overview, projection and grid views.
- **U7 map creation:** added `titan u7 map-create` for empty secondary maps
  or maps built from universal JSON. Existing maps require `--overwrite-map`;
  expanding shared terrain requires `--update-chunks`. Maps can also target
  GAMEDAT namespaces.
- **Ultima III NES conversion:** added `titan u3 map-create` to expand the
  original Sosaria layout into a U7 secondary map using a Serpent Isle JSON
  source, repeatable seeds and terrain rules. Optional outputs include
  universal JSON and a full-map render.

### Changed

- **Separate graphics sources:** `titan u7 map-render --map-root` renders map
  data using graphics, palettes and metadata from another directory.
- **Library map rendering:** `U7MapRenderer` accepts terrain definitions,
  map placement and fixed objects directly.

### Fixed

- U7 map rendering resolves native map filenames case-insensitively, including
  lowercase files on Linux.
- `u7 flex-add-shape` protects the flat-texture slots in `SHAPES.VGA` by
  starting automatic allocation at shape 150. Explicit `--index` remains
  available.
- `usecode-disasm` and `usecode-scan-intrinsic` read Exult-compiled mod files
  with symbol tables and extended function IDs.
- Corrected detection of Exult V2 IFIX records with ambiguous lengths.

---

## [0.7.4]

### Added

- **UU2 map views:** added native-resolution sizing, plan/south cameras,
  diagnostic grids and world cutaways.
- **UU2 diagnostics:** added `texture-catalog`, `texture-usage`, `map-verify`,
  `terrain-export` and archive contact sheets.
- **UU2 scenes:** doors, portcullises, bridges, walls, controls, levers,
  switches and writing now render and export with their placement and state.
  Scene metadata includes signs, triggers, textures and enchantment details.
- **U7 frame reports:** added `titan u7 shape-frame-report` CSV/JSON output
  distinguishing sprite origins, drawing anchors and weapon attachments.

### Changed

- UU2 `map-3d-render` gained camera, crop, output-size, zoom, supersampling,
  texture, backend and Pillow fallback controls. Ceiling textures and vertical
  scale are selectable for renders and exports.
- U7 shape frames expose explicit origin and drawing-anchor helpers;
  `WIHH.DAT` uses weapon-attachment terminology. `shape-import` can select
  BG/SI and discover the configured palette.

### Fixed

- Corrected UU2 model geometry, triangulation and shading.
- Corrected colours for chests, moongates, tables, owner-coloured beds and
  quest-state blackrock gems.
- Corrected sub-tile placement, bridges, doorways, wall decals and camera
  framing.
- Corrected texture orientation in 3D renders and GLB exports.
- Corrected wall-panel sizing, bridge visibility and open-portcullis height.

---

## [0.7.3]

### Added

- **U7 shape import:** added `titan u7 shape-import` to create standalone
  `.shp` files from PNG frames, with palette selection, transparency and
  default hotspots. Frames follow Windows Explorer-style Name A-Z order.
- **U7 Flex creation and insertion:** added `titan u7 flex-create` for empty
  archives and `titan u7 flex-add-shape` for automatic or indexed insertion.
  Archive creation requires `--force` to replace an existing file; insertion
  accepts `--index` and requires `--replace` for occupied records. Output can
  be separate or explicitly in place.
- **Ultima Underworld II tools:** added `titan uw2` commands `map-extract`,
  `map-render`, `palette-export`, `shape-info`, `shape-export`, `shape-batch`,
  `object-info` and `object-dump`. Map rendering includes world objects and
  effects, writes final PNGs by default, and optionally retains diagnostic
  exports with `--keep-intermediates`. Furniture defaults to bitmap artwork;
  `--model-style geometry` selects executable model geometry. Commands accept
  `-g`/`--gamedir` or `[uw2.game] base` in `titan.toml`.
- **UU2 model tools:** added `titan uw2 model-render` and `model-export` for
  individual models and batch OBJ/MTL/PNG/JSON exports. Special door, bridge,
  lever, switch and writing rules are not yet supported in this release.
- **UU2 3D maps:** added `titan uw2 map-3d-render` and `map-3d-export` for
  textured camera PNGs and GLB/JSON scenes with furniture, loose objects and
  animated effects. Tile crops support smaller scenes; model placement and
  dining-table item heights are aligned with the game.

### Fixed

- **Extended U7 shapes:** corrected reflected footprints and depth sorting
  for shapes with more than 32 frames, including mod doors.
- **U8 audio filenames:** `u8 music-export` and `u8 sound-export-all` use
  embedded track/SFX names when available, with numeric fallbacks.
- **U8 shape exports:** `u8 shape-export` uses bundled shape labels when
  available; `u8 shape-batch` also accepts an entire `U8SHAPES.FLX` archive.

---

## [0.7.2]

### Added

- **Ultima Online tools:** added `titan uo` for Classic Client asset export
  and metadata inspection: art, gumps, textures, lights, hues, fonts, sounds,
  multis, tiledata, text and legacy animations. Animation exports resolve
  client redirects and include body/action/direction metadata. Commands use
  an explicit client path or `[uo.game] base`; setup can detect/configure it.
- **U9 UI icons:** added `icon-list`, `icon-export` and `icon-export-all`,
  with separate icon output directories. Candidate detection uses textures
  not referenced by models and may not identify every UI icon; single-entry
  export accepts any texture entry.
- **U8-to-U7 conversion:** added `titan u8 shape-convert-u7` and
  `shape-convert-u7-all` for scenery shapes, with palette conversion, sizing
  and hotspot adjustment. Actor animation conversion is unsupported;
  conversion cannot change the viewing angle baked into a sprite.
- **U7 shape batches:** `titan u7 shape-batch` accepts directories of
  standalone `.shp` files as well as VGA archives.

---

## [0.7.1]

### Added

- **Ultima IX tools:** added `titan u9` with archive listing/extraction,
  type-name inspection, sound extraction and model exports.
- **U9 audio:** decode PCM, stereo/mono ADPCM music and effects, and
  MicroTalk speech to WAV.
- **U9 models and textures:** inspect model hierarchies and materials, decode
  paletted/16-bit textures, and export OBJ/MTL/PNG or geometry-only STL.
  Models without visible geometry are reported rather than exported.
- **U9 palette and names:** use `ankh.pal` for paletted texture colours;
  grayscale remains the fallback without a palette. Optional model names
  are inferred from type metadata and remain best-effort and non-unique.
- **U9 model previews:** exports include previews from two opposite angles when
  optional PyVista is installed, with support for multi-material textures.
- **U9 commands:** added `flx-list`, `flx-extract`, `flx-extract-all`,
  `typename-dump`, `sound-list`, `sound-extract-pcm`, `sound-extract`,
  `model-info`, `model-export` and `model-export-all`.
- **U6 render diagnostics:** added `titan u6 map-audit-zorder` to flag
  overlapping-object candidates in `map-render --objects` for manual review.

### Fixed

- Corrected U6 map object layering for signposts, plaques, cookfires,
  container contents, wall-mounted items, doors, floor tiles and dungeon
  loot, preventing objects from incorrectly hiding one another.

---

## [0.7.0]

### Added

- **U7 animation inventory:** added `titan u7 shape-cycle-scan` with indexed
  frames and JSON/CSV reports for colour cycling, translucency and frame
  animation, including resolved timing and animation parameters.
- **U7 metadata:** expanded shape and object properties, including contact
  effects and Exult-specific metadata. `has_contact_effect` retains
  `is_poisonous` and `is_field` as compatibility aliases. `world-query` and
  `container-browse` report corrected `quality_raw`, `quality` and `flags`.
- **Ultima VI tools:** added `titan u6` for graphics, world objects,
  inventories, actors, dialogue, books, fonts, schedules and saved state.
  Render maps with world objects and animation; inspect and compare quest
  and NPC talk flags, or explicitly write flag changes to saves.
- **U6 commands:** added `lzw-decompress`, `lib-list`, `lib-extract`,
  `lib-extract-all`, `tileflag-dump`, `palette-export`, `tile-export`,
  `tile-export-all`, `map-render`, `object-list`, `egg-list`, `actor-list`,
  `gamestate-dump`, `flags-dump`, `flags-compare`, `flags-set`,
  `converse-dump`, `font-export`, `look-dump`, `book-dump` and `schedule-dump`.
  `map-render` accepts `--objects` and `--tick`.

### Changed

- Animated U7 shapes without an explicit animation type now report the
  default time-synchronized animation rather than no animation.

### Fixed

- Corrected detection of palette cycling versus translucency in U7 scans.
- Corrected container/body quality, lift and object flags in U7 inventory
  data. Quantity suffixes now appear only on quantity-class items.
- U7 `shape-animate` frame playback now applies translucency data.
  `shape-export` detects translucency automatically with `--shape` and
  `--static`, with `--translucent` and `--translucent-bg` overrides for
  standalone input.
- Translucent GIF exports blend against a background before saving.

---

## [0.6.9.1]

### Added

- Added `titan u7 shape-animate` to export frame animations and palette
  colour cycling to GIFs with their game timing.

---

## [0.6.9]

### Added

- Added `titan u7 palette-info` for palette occupancy, names, encoding and
  cycling ranges.
- Added U7 colour-cycling and translucency exports through `shape-export`
  and `shape-batch`, with `--indexed`, `--cycle-phase`, `--translucent`
  and `--translucent-bg` options.
- Added interleaved double palettes and an `--encoding` override for
  ambiguous palettes.

### Changed

- Palette inspection distinguishes empty from invalid records and retains
  original palette bytes.
- U7 `map-render` translucency uses the selected game's
  `XFORM.TBL`/`BLENDS.DAT`.

### Fixed

- `palette-export` no longer crashes on unallocated archive slots.

---

## [0.6.8]

### Added

- **U7 monsters:** added `monster-defs`, `monster-dump`, `monster-report` and
  `monster-equipment` for definitions, live actors, spawn data and possible
  equipment with probabilities and quantities, including mod support.
- **U7 NPC equipment:** added `npc-equipment` to export saved inventories
  with readied, backpack and nested-container locations.
- **U7 static metadata:** added `wihh-dump` for weapon attachments and
  `static-data-dump` for equipment, containers, blends and usecode metadata.
  Missing loose data can fall back to installed Exult bundles; blend exports
  also have a standard translucency fallback.
- **U7 usecode:** added `usecode-scan-intrinsic` for intrinsic references and
  `usecode-disasm` for individual or complete bytecode disassembly.

### Changed

- Egg CSV exports include monster appearance, spawn count, schedule and
  alignment.
- Equipment reports use game-specific ready slots and account for generated
  monster ammunition.
- Typeflag statistics separate flags from shape classes and animation types.

### Fixed

- NPC inspection distinguishes original new-game data from Exult runtime
  files. Ambiguous loose files report unknown sex; `gamedat-info` correctly
  reports sex from original initgame data.
- Inventory exports no longer misidentify Exult combat-bark IDs as items.

---

## [0.6.7]

### Added

- Completed the U8 Spell Catalog with all 36 castable spells, including
  mana costs, incantations, reagents, focuses and source references.

### Changed

- BASEBOOK is the single book-icon library launcher and appears first in
  the Objects list.
- Improved library counts, spell labels, keyboard-accessible tabs and
  list/detail navigation.
- Readable Scrolls exclude consumable-effect handlers; their objects and
  effects remain available in dialogue data.

### Fixed

- Corrected Resurrection book text and duplicate dispatch; Resurrection
  remains outside the castable Spell Catalog.
- Corrected missing-content reports for metadata-backed spells.
- NPC, Object and Util counts agree between the sidebar and header.

---

## [0.6.6]

### Added

- Added `titan dialogue copy` to copy prepared NPC JSON and META sidecars
  to a selected destination.

---

## [0.6.5]

### Added

- Added `titan u7 world-query` for placement filtering, `egg-query` for
  trigger inspection and `container-browse` for nested inventories.
- U7 names combine base-game labels, per-frame Exult names and mod overrides.
- Setup detects Exult profile GAMEDAT, mod roots, saves and initgame sources,
  and records discovered paths in config.
- `world-query` and `map-render` support secondary maps through `--map-num`.
- Dialogue browsing reports random branch chances and alternate flag outcomes.
- `titan dialogue prepare` and `validate` generate a browsable library of
  books, scrolls, graves, plaques and spells.

### Fixed

- Corrected dialogue conditions combining random and string-based branches.

---

## [0.6.4]

### Added

- Added `titan u7 npc-dump` and `schedule-dump` for loose NPC and schedule
  files, with automatic NPC-name lookup.
- Added `u7 typeflag-dump --format detail` for expanded shape metadata.
- Setup discovers initialized Exult runtime and mod initgame data;
  `u7 gamedat-info --mod NAME` inspects mod sources. Path discovery was
  incomplete in this release and is expanded in 0.6.5.

### Fixed

- Corrected CSV escaping and removed duplicate raw flag columns.
- Corrected U7 NPC/inventory parsing and exports, including Avatar inventory
  and declared NPC counts.
- Corrected U7 animation, shape-dimension and NPC-sex decoding for original
  and Exult runtime data.
- Valid long U8 conversations no longer end after ten topic choices;
  runaway conversations remain capped.
- Added ZIP initgame support for Exult mods.

---

## [0.6.3]

### Added

- Setup configures U8 and U7 BG/SI together, shows a combined path summary
  and confirms before writing multi-game config sections.
- Added `titan dialogue prepare`, `validate` and `launch` for the local
  U8 dialogue viewer.
- Added runtime dialogue theme switching, palette previews and improved
  readability and book discovery. Custom themes use colour/font tokens such
  as `--bg-main`, `--font-heading` and `--text-soft`.

---

## [0.6.2]

### Added

- U7 `map-render` supports labelled rectangle highlights with configurable
  colour, opacity, outline width and lift through `--highlight-tile-rect`,
  `--highlight-width`, `--highlight-fill-alpha`, `--highlight-lift` and
  `--highlight-labels`.
- Added built-in BG/SI zone profiles through `--zone-profile`, `--zone-id`
  and `--all-zones`; profiles and manual highlights can be combined.

### Fixed

- `u7 music-export --target gm` improves SC-55/SC-88 playback by remapping
  MT-32-oriented instruments for General MIDI while retaining timing.

---

## [0.6.1]

### Fixed

- U7 `map-sample` produces more representative terrain colours, removing
  stray object dots and void-tile halos and improving dark interior floors.
- Added chunk/superchunk grid labels and corrected `--grid` help text for
  `map-render` and `map-sample`.

---

## [0.6.0]

### Added

- **Ultima VII support:** added `titan u7`, shared root commands and
  multi-game config sections alongside U8 support.
- **U7 shapes and palettes:** read/write RLE shapes and VGA archives;
  added `shape-export`, `shape-batch` and `palette-export`. Library shapes
  support round-trip encoding through `U7Shape.to_bytes()` and `.save()`.
- **U7 audio:** added XMIDI-to-MIDI conversion, VOC decoding and batch speech
  export through `music-export`, `voc-export` and `speech-export`. U8 gained
  `music-export` and `sound-export-all`.
- **U7 maps:** added `map-render` and `map-sample` with selectable projections,
  saved objects, typeflag filters, `--full` world renders and minimaps.
- **U7 metadata and saves:** added `typeflag-dump`, `save-list`, `save-extract`,
  `gflag-dump`, `save-info`, `save-npcs` and `save-schedules`.
- **Map grids:** added chunk coordinates and superchunk boundaries for U7/U8.
- **U7 font wizard:** added `titan u7 font-create` for TrueType-to-Exult
  fonts, with slot selection, palette/gradient previews, outlines and
  standalone or archive output. Batch mode accepts `--config recipe.toml`.
- **Bundled fonts:** added DOS VGA, Ophidean, Britannian and Gargish fonts;
  see [FONTS_CREDITS.md](FONTS_CREDITS.md).
- **Exult integration:** discovers game/font paths and mod patch directories;
  generated fonts include Exult Studio thumbnails for non-standard layouts.

### Changed

- U8 commands moved under `titan u8`; root-level aliases are deprecated.

### Fixed

- Corrected U7 palette scaling and hexadecimal `--sc` input.
- Corrected terrain anchoring, tall-sprite/roof ordering and depth ordering
  across superchunk boundaries.

### Known issues

- Some U7 MIDI exports differ in timing or instrument mapping from original
  game playback.

---

## [0.5.3] — 2026-03-22

### Added

- FLX extraction uses embedded names, adds `.meta.txt` sidecars and shows
  names in `flex-list`; the library adds `summary()` and `record_table()`.
- Added per-NPC speech archive extraction with transcripts and Sonarc audio.
- `detect_record_type()` identifies plain-ASCII text records.

### Changed

- Rebuild manifests use four columns for round-trip exports.

### Fixed

- Corrected false name-table detection in speech transcripts.
- Sidecars use `.meta.txt` instead of `.txt` to avoid overwriting data;
  `from_directory()` accepts the new names.

---

## [0.4.0] — 2026-03-20

First public release.

### Added

- CLI and library tools for U8 Flex archives, shapes, palettes, audio,
  music, maps, saves, credits, typeflags, gumps and colour transforms.
- Isometric and bird's-eye U8 map renders with typeflag filtering and
  saved-object support.
- Shape export to PNG and re-import after editing.
- `titan.toml` configuration, automatic path discovery, `titan setup`
  and `titan config`.
- Importable library APIs and `py.typed` typing support.
