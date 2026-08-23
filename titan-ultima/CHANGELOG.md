# Changelog

All notable changes to **titan-ultima** are documented here.

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0, 2.0, ...): breaking API or CLI changes
- **MINOR** (0.5, 0.6, ...): new features, new commands, new format support
- **PATCH** (0.4.1, 0.4.2, ...): bug fixes, docs, internal improvements

---

## [0.7.4]

### Added

- **UU2 native-resolution sizing for any view:** `titan uw2 map-3d --native`
  sizes a render so no floor tile in the region falls below the 64 pixels a
  `T64.TR` texture actually has. The plan view answers this by arithmetic, being
  parallel and square-on; every other preset looks at the floor from an angle,
  which foreshortens it by `sin(elevation)` - 26% at `south`, 51% at `iso-ne` -
  and under perspective the far side of the map is smaller again, so a tilted
  view needs a *larger* image than the plan to hold the same detail. Rather than
  model VTK's camera fit, the projection is measured at a small probe size with
  no geometry in it and scaled from there. A view too shallow to reach native
  within a 16384-pixel edge is refused with an explanation rather than
  attempted: at the 11 degrees of `low-s` the floor simply cannot hold its
  detail. Losslessness is still the plan view's alone - perspective resamples
  whatever the resolution - but undersampling need not be.

- **UU2 square-on southern views:** added `south` and `low-s` to
  `titan uw2 map-3d`. Every other 3D preset takes a corner bearing, which turns
  a room 45 degrees away from the shape it has on the plan. These stand due
  south and look north, so north stays up and rooms keep their plan outline
  while walls stand up and height reads. `south` sits 48 degrees above the map -
  steep enough to see over near walls into the rooms behind, shallow enough for
  height to tell; `low-s` drops to 11 degrees, matching the existing `low-ne`
  and `low-nw` eye-level presets.

- **UU2 lossless map plans:** added a `plan` camera view to `titan uw2 map-3d`,
  an orthographic straight-down projection sized from the tile region at the
  native 64 pixels per tile - the side of a `T64.TR` texture, one of which maps
  across exactly one tile. Every open tile comes back byte-identical to its
  source texture; verified across all 290 unoccupied tiles of Castle Britannia.
  Exactness needs both the parallel projection and unlit shading, since the
  light kit scales sampled texel colour to about 0.94. `--plan-scale` renders
  whole multiples, which stay lossless but add no detail. The perspective views,
  `top` included, are unchanged and cannot be pixel-exact in principle: surfaces
  at varying angles and distances give a texel a non-uniform pixel footprint.
- **UU2 texture names and usage:** added `titan uw2 texture-catalog`, joining
  `STRINGS.PAK` block 10 descriptions to `TERRAIN.DAT` properties for all 256
  `T64.TR` textures (wall at the texture's own string index, floor at
  `510 - texture_id`), and `titan uw2 texture-usage`, reporting per-level tile
  coordinates by floor, wall, and both ceiling rules. Both read original files
  directly, and wire up the previously unused `titan.uw2.strings` decoder.
- **UU2 map verification:** added `titan uw2 map-verify` to smoke-check
  `LEV.ARK`: the 320-block table, per-slot block sizes, a full decode of every
  populated slot, and the `0x7c06` marker histogram. Failures are collected
  rather than raised, and it exits non-zero so it can gate a pipeline.
- **UU2 doors in 3D scenes:** 259 doors across 34 levels, previously skipped.
  Each is one scene object with separately named frame and panel parts: frame
  from model `0x01`, leaf from `0x0E` (or `0x0F` secret). Panels take one of
  the level's six door textures; secret doors wear their tile's wall texture.
  Hinged doors swing about the edge `doordir` selects, which also reverses the
  direction; portcullises rise instead. `UW2.EXE` has no portcullis model, so
  its bars are reconstructed and flagged `door_geometry: reconstructed`. Open,
  portcullis, secret, swing, lift, and `doordir` are recorded for exporters.
- **UU2 door swing direction decoded:** object word 0 bit 13 is the door swing
  direction and was not parsed at all. It is now exposed as `doordir` on every
  decoded object record.
- **UU2 owner-coloured beds:** bed bedding now takes its instance colours -
  quilt `4 * owner + 5`, pillow `4 * owner`, masked to a byte so high owners
  wrap as the game does. The quilt and pillow share one executable colour
  group and are told apart by position along the bed.
- **UU2 special object classes in 3D scenes:** `map-3d-render` and
  `map-3d-export` now place bridges, the `0x16E`/`0x16F` texture-map walls,
  `0x170`-`0x17F` wall controls, levers, switches, and writing - 1,047
  instances across 42 levels that previously fell through as skips. Bridges
  take an object texture or a level **floor** mapping entry from `flags`;
  special walls take a **wall** entry named by `owner`.
- **UU2 sign text and instance metadata:** writing objects now carry their
  decoded prefix and readable message (`The plaque reads: LIBRARY`) in scene
  and GLB manifest metadata, resolved from `STRINGS.PAK` block 8. Placed
  objects also record their texture source and index, wall-mounted and
  removable-wall markers, trigger links, and the enchantment flag.
- **UU2 flat diagnostic grids:** added `titan uw2 map-grid`, a top-down view
  with no projection and no wall height, so a tile's screen box follows only
  its coordinates. Draws floor textures clipped to diagonal triangles, outlines
  every side not shared with an open neighbour, and marks diagonal hypotenuses
  and doors at their in-tile offset and heading, with display/raw/both labels.
- **UU2 stacked world cutaways:** added `titan uw2 map-stack` to render each
  world's levels as one vertically stacked scene, first level on top and each
  lower level dropped by `--stack-gap`, with optional per-level `--stagger-x`
  and `--stagger-y` and a `--world` slug filter.
- **UU2 terrain texture export:** added `titan uw2 terrain-export` for
  `T64.TR` PNGs with optional nearest-neighbour `--scale`, and a
  `--contact-sheet` flag on both it and `uw2 shape-batch`. Contact-sheet cells
  are sized to the largest image and smaller images centred, so ragged archives
  such as `TMOBJ.GR` stay aligned.
- **Combined U7 shape frame report:** added `titan u7 shape-frame-report` to
  export every record and frame from a U7 shape Flex archive as CSV or JSON.
  The report keeps Exult Studio Origin X/Y, top-left-relative drawing
  hotspots, and `WIHH.DAT` weapon attachment coordinates in distinct columns;
  it auto-discovers a sibling `WIHH.DAT` or accepts an explicit path.

### Changed

- **UU2 3D map render controls:** `map-3d-render` gained the `low-ne`/`low-nw`
  low-angle presets, repeatable `--slot`, non-square `--width`/`--height`,
  `--zoom`, `--fit-margin`, `--supersample` with `--downsample-filter`,
  `--texture-filter nearest` with `--texture-scale` for crisp pixel art,
  `--name-files`, and `--backend`. Without PyVista, `auto` now falls back to a
  Pillow preview with a warning instead of failing. Default output is
  pixel-identical.
- **UU2 ceiling-texture rule is selectable:** `map-3d-render` and
  `map-3d-export` accept `--ceiling-source runtime|ua`, exposing the
  UnderworldAdventures `mapping[32]` interpretation that the geometry layer
  already supported but nothing could reach. The two rules disagree on every
  level. Both commands also accept `--z-scale`, which now scales placed object
  and sprite heights alongside terrain rather than only terrain.
- **U7 frame origin convention:** `U7Shape.Frame` now exposes
  `origin_x`/`origin_y` using `xright`/`ybelow` convention.
  Explicit top-left-relative drawing-anchor helpers replace the ambiguous
  `xoff`/`yoff` fields while preserving existing SHP/VGA binary placement.
- **U7 weapon attachment terminology:** WIHH.DAT values are now identified as
  weapon attachment coordinates (`attachment_x`/`attachment_y`) and kept
  clearly separate from SHP frame origins in the API, CSV output, CLI help,
  and documentation.
- **Configured U7 shape-import palettes:** `titan u7 shape-import` now accepts
  `--game bg|si` and uses that game's `titan.toml` palette when `--palette` is
  omitted. An explicit `--palette` continues to take precedence.

### Fixed

- **UU2 model colours: a slot past the model's table is the engine's to fill.**
  A model's nodes name a slot in its own small colour table, and several reach
  past the end of it. Wrapping the index round was wrong; palette 0 suits every
  model that does it except the one where it shows. The large blackrock gem asks
  a two-entry table for slots 3 and 12 to 16 because its colours come from quest
  state, not the model: each facet is `0x52` until its bit is set in quest 130,
  then `0x4D`, with `0x4F` on the one game variable 6 points at
  (UnderworldGodot, `objects/largeblackrockgem.cs`). `0x4C` to `0x52` is a blue
  ramp. A map render has no save game, so the gem is drawn as it stands at the
  start, every facet `0x52`. It was white before, and briefly black.
- **UU2 chests were grey.** The chest declares two colours, a warm brown
  `0x8E` and a grey `0xCA`, and its face nodes call the grey twenty-one times
  and the brown once. In the game it is brown, and nothing on the placed object
  can be choosing: all forty chests in the shipped levels carry `flags` and
  `owner` of zero. There is no texture path either - the model is 112 flat faces
  with no UVs, and `TMOBJ.GR` holds no chest surface. Nor does any palette in
  `PALS.DAT` make `0xCA` warm without recolouring the rest of the game. The
  chest is now drawn in the colour it declares first, its shading unchanged, so
  it keeps the lighter lid and darker sides. Recorded rather than decoded: the
  executable says otherwise, and UnderworldAdventures' table agrees with the
  executable but shares our arithmetic, so it is not a second opinion.
  UnderworldGodot gives its chest a brown body, by hand.
- **UU2 Gouraud-shaded model faces were drawn at one flat colour.** A model
  defines a vertex shading table (`0x00D4`) giving every vertex its own step
  down the colour's ramp, and `0x00D6` switches the following faces onto it.
  Fourteen of the thirty-two models do this, covering 1035 of the 1205
  flat-shaded faces in the set, so ignoring it dropped most of the modelling:
  boulders were smooth grey blobs, the shrine a silhouette, a barrel had no
  staves. Faces now carry a colour per corner, and 90% of them have corners at
  different steps. `_part_arrays` already gives each triangle three fresh points
  rather than sharing corners between faces, so the colours line up with it
  without re-indexing; a part still names one material, which every face that
  is not shaded keeps using, and which holds the mean for anything that can take
  only one colour per face. PyVista draws them as point scalars, the GLB export
  as `COLOR_0`, and the software fallback averages the corners since it fills
  whole polygons. A moongate is a single quad with a bright middle, which now
  reads as the gradient it is rather than a flat panel. `0x002E`, which the
  format notes switches the shading back off, is honoured. The shading works on
  whatever colour the face ends up wearing: an instance can replace the model's,
  and taking the corners from the model's instead turned Castle Britannia's
  owner-coloured beds blue and gave blue moongates a red gradient. Where the
  replacement is a point on a ramp, as a gate's link colour is, it shades; where
  it is an exact entry, as an owner's is, the face stays flat.
- **UU2 executable models were drawn flat, losing their shading.** A face's
  colour node carries a shade in the word after the colour, which we read and
  threw away: "the same calculations and palette indexing rules apply here" as
  for the Gouraud table, per `uw-formats.txt`. The palette runs in short
  darkening ramps, so the shade is simply the next entries along - grey `0xCA`
  falls from 96 to 24 over five steps, the chair's brown `0x8F` from 132 to 44 -
  and faces of one model use different steps. A chest spans six of them, which
  is why it read as a flat silhouette instead of a box with a lid; benches lost
  their planking and chairs their depth. Faces are now shaded as the model asks.
  A ramp is a handful of entries long and nothing marks where one ends, so a
  step that would lighten the colour has run off the end - three faces of the
  arrow do - and keeps its base colour. An instance colour, bedding from its
  owner or a moongate from its link, is an exact entry rather than a point on a
  ramp, so it replaces the shaded colour rather than being stepped itself.
- **UU2 moongates take their colour from the placed object.** Every one was
  rendering the same, because the model's own colour table has nothing to say
  about it: a gate is tinted by its link field, `link - 512`, as UnderworldGodot
  reads it (`objects/moongate.cs`). The shipped gates use the whole spectrum the
  Ethereal Void needs - red `0x21`, blue `0x4F`, yellow `0x10`, orange `0x2D`,
  purple `0x5A` and `0x5B`, green `0xAB`, white `0xC2` - so the Yellow Zone's
  gates are yellow and the Colour Zone carries seven different ones. The index
  is recorded on the object as `moongate_palette_index`.
- **UU2 table surfaces ignored their flags.** A table's flags choose the top:
  `32` and `34` are planking, `33` marble, `35` stone. We pinned every table to
  `32`, so the thirty of the game's seventy-four that ask for something else
  were all planked. Paintings and pillars already varied correctly.
- **UU2 moongates were black.** The moongate is the only model whose info entry
  sets the top bit of its header byte, and the only one whose first colour byte
  is `0x00` - a placeholder rather than "black", which we read literally. It
  stands for palette index `0x21`, the one entry in `PALS.DAT` that reads
  `(212, 16, 36)` in palettes 0, 2, 3, 4 and 7 but `(24, 44, 188)` in 5 and 6:
  the red moongate and the blue one, from a single model and a single index. 73
  gates across the Ethereal Void. The value is recorded rather than decoded -
  the executable gives no derivation for it - and it matches the table
  UnderworldAdventures transcribed by hand. Which palette a level chooses is
  still not modelled, so all 73 render red for now.
- **UU2 wall panels were drawn a quarter of their size.** Class `0x016E` took the
  quarter-tile quad at executable slot `0x14`, so a wall hanging built from
  stacked panels came out as fragments with gaps between them - Castle
  Britannia's throne room hangs its two ankh banners either side of the stained
  glass this way. Both special texture-map classes are one tile square and one
  tile high, as UA draws them (`RenderTmapObject`: `dir *= 0.5` to each side,
  `pos.z` to `pos.z + 1.0`), and the shipped levels only work out that way: the
  banners are stacked 32 height units apart, the same spacing as the `0x016F`
  stained glass beside them, which meets end to end only at a whole tile each.
  `0x016E` now takes the full-tile slot `0x16` as well. 335 panels across 36
  levels. Levers, switches and writing keep the quarter-tile quad, which is the
  right size for them.
- **UU2 floors, ceilings and walls were drawn upside down in 3D.** Both
  consumers of a scene turn `v` over before sampling - the renderer through
  `texture.flip_y`, the GLB export through trimesh - so a surface's `v` has to
  be written in that sense, and terrain never was. Floor `v` came straight from
  the world `y`, putting image row 0 at the north edge of the tile when it
  belongs to the south; wall `v` was measured down from the ceiling, hanging the
  foot of the image from it. On the noise-like stonework that fills most of UU2
  neither shows. Two things gave it away: the pentagram inlaid across four floor
  tiles in the Ethereal Void and Scintillus Academy, textures 236 to 239, which
  only resolves into one figure the right way up, and ice wall 51, whose ground
  detail sat at the ceiling. This also settles a disagreement between pipelines,
  since the 2.5D renderers have always turned floor textures over. Executable
  models, doors and sprites were already correct and are untouched.
- **UU2 bridges and doorways sat a fraction off their own tile.** Both span a
  whole tile, so the tile is their position, but they were centred on the
  object's sub-tile cell - leaving the whole span about 1/16 of a tile out.
  Bridges were the single largest source of geometry crossing into walls, 7.4
  of 19.0 tiles-squared across the game. UW2 places both from the tile:
  underworldexporter's `RenderBridge` discards the computed position for
  `ObjectTileX * 1.2f + 1.2f / 2f`, and its door case never reads `xpos`/`ypos`.
  Bridge overlap is now zero; doors keep only the half panel thickness that sits
  in the opening by construction.
- **UU2 loose scenery no longer hangs over the wall beside it.** Objects are
  drawn centred on their sub-tile cell at full size, and UW2 puts a fifth of all
  sub-tile coordinates hard against a tile edge, so half a table or a book landed
  inside the wall. The game never had to care - it is only seen from inside the
  room - but a top-down plan shows it, and the orthographic `plan` view made it
  plain by drawing wall tiles as empty space. Renders now shift such objects the
  smallest distance that clears the wall, dropping overlap from 11.0 to 4.2
  tiles-squared. Only genuinely solid neighbours push, so an object on the
  boundary between two open tiles stays put, unlike underworldexporter's
  `WallAdjust`, which nudges on the sub-tile value alone. Wall fixtures - shelves,
  paintings, levers, writing - are shifted too: the move is only ever the depth of
  the overhang, so they end up flush against the wall face instead of through it.
  Only a door is left alone, its leaf standing in the opening. The offset is
  recorded on the object and applied when drawing, so a GLB export still carries
  the placement `LEV.ARK` holds.
- **UU2 render framing no longer moves when an object does.** The camera was
  fitted with `reset_camera()`, which frames the actors, so shifting one item a
  fraction of a tile re-fit the camera and moved every pixel in the output -
  a placement change of 0.06 tiles displaced a whole render by 6 px and made
  49% of its pixels differ. Framing now comes from the tile region the caller
  asked for, which nothing in the data can perturb; the same comparison moves
  0 px and differs only in the 2.7% of pixels the objects actually occupy.
- **UU2 sub-tile placement is shared by all sixteen call sites.** They had
  disagreed - most read `xpos / 8`, two used a `+0.5` approximation - so the
  2.5D and 3D renderers placed the same object differently. One
  `sub_tile_fraction` helper now serves them all. It applies no bias: the `0xF`
  UW2 adds when expanding a tile and `xpos` into a live coordinate belongs to
  collision, not to where static scenery is drawn, and applying it pushed wall
  furniture through the wall. The shipped levels sit on the plain eighth grid -
  a bed runs 25.25 to 25.75, the shelf at its head 25.75 to 26.00, the wall face
  at 26.00 - each piece meeting the next exactly.
- **UU2 wall decals hang on the wall face rather than near it.** A lever, switch,
  pull chain, writing or special wall panel took both coordinates from its
  sub-tile cell, leaving it up to 1/16 of a tile off the wall it is fixed to. The
  coordinate across the wall now comes from the tile edge the object's heading
  names, as UA's `RenderDecal` does, set back by the 1/16 the decal's own quad
  stands outward. All 689 decals on a square heading now sit exactly on their
  wall plane, where none did before. The heading-to-wall mapping is confirmed
  against the shipped levels.
- **UU2 sprites are no longer drawn upside down.** Every sprite billboard, in
  every 3D view and every exported GLB, was mirrored vertically. Both consumers
  flip `v` before sampling - the renderer through `texture.flip_y`, the GLB
  export through trimesh's glTF conversion - but the sprite quads put `v=0` on
  their top edge, so it sampled the source image's bottom row. The upper edge
  now takes `v=1`. Terrain and executable models were already correct: terrain
  UVs come from the geometry and model UVs are written as `1.0 - v`. Most items
  are small and near-symmetric, which is why it went unseen; anything with clear
  vertical structure, such as plants and hanging objects, was visibly inverted.
- **UU2 ceiling-height bridges no longer roof a ceiling-less render.** A bridge
  can stand in for the fixed ceiling - Castle Britannia roofs its courtyard with
  a five-by-five grid at `zpos` 127 against a ceiling of 128 - so placing them
  hid the courtyard and its fountain. Bridges at ceiling height now follow
  `--include-ceilings` like the ceiling planes do. The data separates cleanly:
  deck bridges top out at `zpos` 104, and the 43 that act as ceiling sit at 121
  or 127, so walkway bridges are unaffected.
- **UU2 open portcullises no longer float above the wall.** A placed door
  carries its raise in `zpos` - both open forms sit 24 height units above their
  tile floor, every closed one exactly on it - so adding the animation lift on
  top counted the rise twice. They now retract into the ceiling recess. The
  lift still applies to a portcullis stopped part-way, which no level contains.
- **UU2 model faces are no longer filled across concave outlines.** Faces were
  fanned from the first vertex, valid only for convex polygons; a bed's side
  outline traces up one post, along the rail and back underneath, so fanning
  filled the notch and welded the posts to the frame. Faces are now ear-clipped.
  Eight of the thirty-two models were mis-shaped - bench, boulder, large
  boulder, arrow, shrine, chest, chair, bed - and now show their real gaps and
  legs. `map-render` is unchanged; its default `--model-style icons` draws
  sprites, not executable geometry.
- **UU2 model colour tables were truncated.** A model info entry holds a count
  plus up to four palette indices, but only three were read. The bed declares
  four and references all four, so sixteen of its triangles were painted with
  the frame's colour instead of the bedding's. Of the thirty-two models, only
  the bed is affected.

---

## [0.7.3]

### Added

- **U7 standalone shape import:** added `titan u7 shape-import` to create one
  U7 RLE `.shp` from PNG frames in Windows Explorer-style Name A-Z order.
  RGBA pixels are quantized against a selected U7 palette, alpha maps to
  transparency index 255, and frame hotspots default to the bottom-right
  pixel. The command writes only a standalone `.shp`, never a Flex archive.
- **Empty U7 Flex creation:** added `titan u7 flex-create` to create a valid
  zero-record U7/Exult `.VGA` or `.FLX` archive using the U7 header format,
  with an optional title and guarded `--force` replacement.
- **U7 shape archive insertion:** added `titan u7 flex-add-shape` to validate
  and place a standalone `.shp` in the lowest empty U7 Flex record, appending
  when no gap exists, or at a specific `--index` while filling intervening
  records as empty. Occupied indexed records require `--replace`. The command
  supports separate output or explicit atomic in-place updates and reports the
  assigned record/shape number.
- **Native Ultima Underworld II command family:** added `titan uw2` with
  `map-extract`, `map-render`, `palette-export`, `shape-info`, `shape-export`,
  `shape-batch`, `object-info`, and `object-dump`. The map commands migrate
  the established `uuw2data/scripts` pipeline into Titan: `LEV.ARK` decoding,
  level/object/automap/note/light JSON, `T64.TR` terrain, GR doors and decals,
  and U7-style overhead cutaway rendering. `map-render` reads these sources
  directly into memory and leaves only final PNG files by default; optional
  `--keep-intermediates` retains diagnostic exports. It also composites normal
  `OBJECTS.GR` sprites and `ANIMO.GR` effect frames selected through
  `COMOBJ.DAT`/`OBJECTS.DAT`, including Castle Britannia's two-object fountain.
  It independently decodes the supported `UW2.EXE` model-node format in memory
  and can project common-object meshes. The U7-style renderer defaults to
  verified `OBJECTS.GR` furniture icons instead, placing tables, chairs,
  benches, chests, and similar items behind loose food and object sprites;
  executable geometry remains available through `--model-style geometry`.
  Other new library modules decode
  `PALS.DAT`, sparse `.GR` archives and known GR bitmap encodings,
  `ALLPALS.DAT`, `COMOBJ.DAT` render types, and `OBJECTS.DAT` animation frame
  ranges. Commands accept `-g`/`--gamedir` or `[uw2.game] base` from
  `titan.toml`.
- **Standalone UU2 polygon model tools:** added `titan uw2 model-render` for
  PyVista/VTK camera renders and `titan uw2 model-export` for individual
  OBJ/MTL/PNG/JSON assets. Both read `UW2.EXE`, `PALS.DAT`, and `TMOBJ.GR`
  directly. Batch export covers all 21 currently mapped built-in item IDs,
  preserves palette-colored faces, resolves item-selected bitmap textures,
  writes one directory per item, and records the batch in `manifest.json`.
  Special door, bridge, lever, switch, and writing rules remain future work.
- **Textured UU2 3D map scenes:** added `titan uw2 map-3d-render` camera PNGs
  and `map-3d-export` GLB/JSON output from one shared in-memory scene. Tile
  geometry uses `T64.TR`; mapped furniture uses individually placed, named
  `UW2.EXE` model parts with palette or `TMOBJ.GR` materials; loose objects
  and ANIMO frames use alpha billboards. Inclusive tile crops allow small
  validation scenes. Castle dining-room food records now align with table
  tops by preserving native model Z units. Placed meshes use native scale `1`,
  clockwise 45-degree headings, and each executable model's `0x0078` origin
  pivot. Individual OBJ exports use the same pivot and record both origin and
  collision half-extents in metadata.

### Fixed

- **U7 frame-32+ object footprints:** map rendering now matches Exult's
  corrected frame-bit interpretation. Frame bit 5 (`0x20`) swaps a shape's
  X/Y tile dimensions only when the shape has 32 or fewer real frames and
  the bit denotes a generated reflection. Shapes with more than 32 real
  `SHAPES.VGA` frames retain their stored TFA dimensions for frames 32+.
  This fixes depth sorting and fallback bounds for extended mod shapes such
  as the 40-frame Serpent Isle door shape 376. Door state persistence and
  Exult's separate `frame % 4 < 2` open-door rule are unchanged.
- **U8 embedded-name export filenames:** `titan u8 music-export` and
  `titan u8 sound-export-all` now preserve the names Titan already parses
  from the source archives instead of always falling back to generic archive
  stems. `MUSIC.FLX` exports now use playlist track stems when present
  (for example `0001_intro.mid`), and `SOUND.FLX` exports now use the
  built-in 8-byte SFX identifiers when present (for example
  `0001_GRUNT7A.wav`). Standalone `.xmi` and `.raw` input behavior is
  unchanged.
- **U8 shape export naming and full-archive batching:** `titan u8
  shape-export` now uses bundled `usecode_classes.csv` labels for numeric
  U8 shape IDs when available (for example `0068_DOOR_NS_f0000.png`
  instead of plain `0068_f0000.png`). `titan u8 shape-batch` now also
  accepts `U8SHAPES.FLX` directly, batch-exporting every non-empty shape
  slot to PNG frames with the same naming scheme and falling back to
  numeric stems for shapes that have no bundled class-name mapping.

---

## [0.7.2]

### Added

- Added `titan uo` for Ultima Online Classic Client extraction and metadata
  review. The new commands export 2D assets and supporting data from UOP and
  MUL/IDX client files: art/statics, gumps, textures, lights, hues, radar
  colors, fonts, sounds, multis, tiledata, `animdata.mul`, `art.def`, all
  supported `.def` redirect files, localization/speech/skills/system text, and
  legacy animation frames. Animation exports include body/action/direction
  resolution metadata using client DEF files, `mobtypes.txt`,
  `AnimationSequence.uop`, and a packaged body-name metadata cache. UO commands
  accept an optional client path and can fall back to `[uo.game] base` in
  `titan.toml`; `titan setup` can detect/prompt for that UO base.
- Added `titan u9` 2D UI icon discovery and export (`titan.u9.icon`):
  the texture archives already used for 3D model surface materials
  (`bitmap16.flx`/`bitmapC.flx`/`bitmapsh.flx`) also hold a large set
  of standalone 2D UI icons (spell-rune sigils, item icons, ...) mixed
  into the same index space, with no format-level flag distinguishing
  them from material textures. The one reliable signal found: every
  entry a 3D model material actually references is a real surface
  texture, so the complement, entries no model ever references, is
  a solid (if not provably exhaustive) set of icon candidates. Real
  data: 5,044 distinct texture_ids are claimed by `sappear.flx`
  models, leaving 1,553 of `bitmapsh.flx`'s 6,597 used entries as icon
  candidates, including a confirmed spell-rune-sigil cluster
  (entries 568-641). Kept logically separate from existing mesh/texture
  commands: its own module (`titan.u9.icon`), its own `icon-*` CLI
  command group, and its own default output directory
  (`icon_export/`, vs. `model_export/`).
  - `titan u9` CLI: `icon-list` (candidate icons with dimensions),
    `icon-export` (any single texture archive entry, mesh-referenced
    or not), `icon-export-all` (batch-export every candidate icon).
- Added `titan u8 shape-convert-u7` (`titan.u8.u7_shape_convert`) for
  converting U8 static/scenery shapes into U7/Exult-compatible shapes.
  Conversion uses resize, palette requantization, and hotspot adjustment
  from U8 bottom-center to U7 bottom-right. Output size is calibrated from
  real U7 shape footprints, based on the largest frame in each U8 shape,
  and clamped to 64 pixels per side. Actor/NPC animation conversion is out
  of scope.
  - Added `shape-convert-u7-all` to batch-convert every used shape in a
    `U8SHAPES.FLX` archive. A real Black Gate test converted 855 shapes
    and 21,450 frames with no failures.
  - Documented the known limitation for multi-orientation objects: changing
    compass direction cannot be solved with a per-pixel transform because
    the rendered sprite already bakes in one camera angle.
- `titan u7 shape-batch` now also accepts a directory of standalone
  `.shp` files, such as `shape-convert-u7-all` output, not just a
  single VGA Flex archive. Titan auto-detects whether the argument is a
  directory or a file. Matches the directory-input convention
  `titan u8 shape-batch` already had; U7 was missing the equivalent.

---

## [0.7.1]

### Added

- Added the `titan.u9` subpackage: initial format-reading support for
  Ultima 9: Ascension.
  - **Archives & metadata**: FLX archive directory reading (used by
    `sound/*.flx`, `static/TYPENAME.FLX`, and other U9 containers);
    `TYPENAME.FLX` type-ID-to-display-name decoding.
  - **Sound**: a shared 0x3C-byte sound-record header reader covering
    `Speech.flx`, `sfx.flx`, and `music.flx` alike (id, description,
    frequency, bit depth, channels, encoding type); PCM repackaging;
    stereo ADPCM decode (EA-XA, `music.flx`); mono ADPCM decode (EA-XA,
    some `sfx.flx` entries, a distinct 15-byte block shape from the
    stereo path); EA MicroTalk speech decode (`Speech.flx`, a multipulse
    CELP/RELP codec ported from vgmstream's open-source reference
    decoder). All four decode paths were validated against real game
    archives (cross-checked against independent decodes where a
    reference was available) before being wired up, and every
    `sfx.flx`/`music.flx`/`Speech.flx` entry in this project's test
    copy of the game now decodes to a playable WAV.
  - **3D models & textures**: a `static/sappear.flx` mesh reader,
    limb hierarchies (rigid body-part transforms, not vertex skinning),
    per-limb LODs, per-corner vertex/UV/normal data, and materials. A bitmap-archive texture reader
    (`bitmap16.flx`/`bitmapC.flx`/`bitmapsh.flx`: 8-bit paletted and
    16-bit 565/5551 pixel formats) and OBJ+MTL+PNG / binary-STL
    exporters that flatten the limb hierarchy to world space (STL is
    geometry-only by format limitation; OBJ carries full materials and
    textures). Checked against every real entry in this project's test
    copy of the game: 3,748/3,764 models parse (16 are genuinely
    corrupt upstream data, matching a model the reference importer's
    own author already flags as broken); of those, 3,657 export
    successfully and the remaining 91 have no visible geometry to
    export, for example collision-only placeholders. All 5,044 distinct
    textures referenced across every model resolved successfully from
    `bitmap16.flx` alone. OBJ UVs are flipped (`1.0 - v`) to match
    OBJ/OpenGL's texture-space convention, the opposite of the source
    data's own.
  - **Real palette colors for 8-bit textures**: `static/ankh.pal`
    (confirmed real: 256 RGB entries, cross-validated by decoding the
    same placeholder texture through both the 16-bit and 8-bit texture
    sets and matching color families) recovers true colors for 8-bit
    textures instead of the previous flat-grayscale fallback (kept as
    the default when no palette is given). Every real 8-bit texture
    checked across all three bitmap archives decoded to a valid,
    in-range palette index.
  - **Model naming**: since no file names a `sappear.flx` model
    directly, `model-info`/`model-export` can optionally derive a
    best-effort label through the indirect `TYPES.DAT` mapping
    (`type_id` to `default_model_id`) and `TYPENAME.FLX` mapping
    (`type_id` to display name), for example naming model 1805's export
    `model_01805_lord-british`.
    This mapping is inherently partial (about 45% of models in this
    project's test copy of the game resolve to at least one name) and
    not unique (several named types commonly share one generic body
    mesh); both are reported honestly rather than papered over.
  - **Preview rendering**: `model-export` can also render two preview
    images (`preview.png` + `preview_front.png`, the latter the same
    angle rotated 180 degrees) as part of the same export (on by
    default; skips cleanly with a note if the optional `pyvista`
    dependency isn't installed). Textured multi-material models are
    rendered via VTK's full scene importer (`vtkOBJImporter`), not a
    naive single-texture OBJ load, confirmed the naive approach
    silently renders every material but one as flat gray on a real
    16-material export, while the scene importer renders all of them
    correctly. The second, rotated render was added after noticing the
    default angle consistently showed the back of humanoid models.
    Textures render with mipmapping, interpolation, and 8x anisotropic
    filtering to avoid moire noise on high-frequency detail such as fur.
  - `titan u9` CLI: `flx-list`, `flx-extract`, `flx-extract-all`,
    `typename-dump`, `sound-list`, `sound-extract-pcm`, `sound-extract`,
    `model-info`, `model-export`, `model-export-all` (same options as
    `model-export`, batched over every used model in a `sappear.flx`).
- Added `titan u6 map-audit-zorder`: reproduces `map-render --objects`'s
  own anchor/overflow/layer-tier rules to flag candidate same-tier
  object ties (the pattern behind every hidden-object bug fixed below)
  for manual review, rather than needing to spot them by eye.

### Fixed

- Fixed a wide category of z-order/compositing bugs in `u6 map-render
  --objects`, where an object sharing a map coordinate with another was
  incorrectly hiding it (or getting hidden by it) instead of both
  rendering correctly:
  - A signpost was completely erasing its own directional plaque at 26+
    map coordinates instead of merely peeking through its transparent
    corners; the 2 spots pairing two plaques on one post needed a
    further coordinate-specific fix so the losing plaque doesn't
    independently repaint a second, unwanted plank next to the correct
    one.
  - A cookfire's logs, a basket's contents, a wall-mounted weapon, a
    doorway's door, and carpet/secret-door floor tiles were each
    winning or losing file-order coin-flip ties against the wrong
    object.
  - Ground clutter in dungeon loot piles (a dead body vs. a pile of
    bones, a club vs. a dead gargoyle, small items vs. a dropped piece
    of armor, blood vs. a cleaver/knife, a magic bow vs. a map
    fragment) was hidden by same-tier objects it should visually sit on
    top of.
- Fixed several of the above by promoting the confirmed *winning* tile
  to the foreground tier rather than demoting the loser, after an
  earlier attempt at the latter regressed unrelated matchups (a
  demoted "loser" losing to supporting furniture it should still beat).

---

## [0.7.0]

### Added

- Added `titan u7 shape-cycle-scan` to inventory a whole `SHAPES.VGA`
  archive for colour-cycling, translucency, and TFA frame-animation
  content, exporting indexed frames plus a JSON/CSV descriptor per
  shape. Each entry reports flat-tile vs RLE-sprite (index 255's
  transparency meaning depends on which) and the fully resolved
  animation parameters (type, frame count, recycle, freeze chance,
  frame delay), not just a yes/no animated flag.
- Added the TFA/Extra/Object shape metadata model:
  - `has_contact_effect` on `U7TypeFlags.ShapeEntry` (`is_poisonous`/
    `is_field` kept as compatibility aliases), plus shape-class helper
    properties (`has_quality`, `has_quantity`, `is_container`, etc.).
  - Extra model (`titan.u7.shape_extra`) for non-TFA `Shape_info` data
    from Exult's `shape_info.txt` (`field_type`, `barge_type`,
    `mountain_top`), plus a `U7ShapeInfo` facade exposing
    `becomes_field_object` (contact-effect bit plus a typed field).
  - Object model (`titan.u7.ireg.U7ObjectFlags`: invisible,
    okay_to_take, temporary), replacing three divergent, partial IREG
    decoders in `map.py`, `save.py`, and `container.py` with one
    implementation.
    `world-query` and `container-browse` now show real
    `quality_raw`/`quality`/`flags` instead of a bare, sometimes-wrong
    quality integer.
- Added the `titan.u6` subpackage: format-reading (and limited
  save-editing) support for Ultima 6: The False Prophet.
  - **Graphics & world**: LZW decompression; `lib_16`/`lib_32` library
    reader; tile graphics (plain/transparent/pixel-block); palettes;
    `TILEFLAG` terrain/object metadata; `MAP`/`CHUNKS` world renderer
    with animated-tile support and correct multi-tile ("double-size")
    object compositing (beds, banners, barrels, etc. now render as
    complete sprites instead of a single truncated tile).
  - **World objects & actors**: object placement (`LZOBJBLK`/
    `LZDNGBLK`) with container/inventory resolution; egg (object
    spawner) decoding, including spawn probability and target; the
    256-actor identity table (position, stats, alignment, talk flags);
    loading world/actor state directly from a real save's `SAVEGAME/`
    folder.
  - **Story & save state**: party roster, player state, game clock, and
    weather; a read/compare/write tool for per-NPC talk flags and
    global quest state, including writing changes back to a save.
  - **Dialogue**: a CONVERSE.A/B bytecode disassembler, with known
    global variables (karma, Gargish knowledge, party size, etc.)
    annotated by name instead of raw numbers.
  - **Text & reference data**: fonts (English + runic/gargoyle); object
    names; books/signs; NPC daily schedules.
  - `titan u6` CLI: `lzw-decompress`, `lib-list`, `lib-extract`,
    `lib-extract-all`, `tileflag-dump`, `palette-export`, `tile-export`,
    `tile-export-all`, `map-render` (`--objects`, `--tick`),
    `object-list`, `egg-list`, `actor-list`, `gamestate-dump`,
    `flags-dump`, `flags-compare`, `flags-set`, `converse-dump`,
    `font-export`, `look-dump`, `book-dump`, `schedule-dump`.

### Changed

- Corrected U7 TFA animation-type inference: a shape flagged
  `is_animated` with no explicit nonzero animation nibble now correctly
  defaults to type 0 (time-synchronized), instead of being reported as having no animation.

### Fixed

- Fixed shape/frame colour-cycle scanning conflating ordinary
  palette-cycling pixels with TFA-translucency pixels in the indices
  they share (238-254); which one applies is now determined by the
  shape's own translucency flag, not the pixel value alone.
- Fixed container/body IREG records (12/13/14-byte) reading their
  quality and lift bytes from the wrong offsets, decoding them as if
  they were plain 6-byte objects; this corrupted container quality/lift
  and read invisible/okay_to_take flags from the wrong byte entirely.
- Fixed `container-browse` showing a `xN` quantity suffix on every item
  with `quality > 1`, regardless of shape class; it now only shows for
  actual quantity-class items (a container's own unrelated quality
  byte, like a chest's lock difficulty, is not a count).
- Fixed a set of translucency rendering bugs found while chasing down
  a shape that stayed gold instead of grey in real gameplay (shape 177):
  - `shape-animate`'s frame-sequence mode (real TFA multi-frame
    animation) ignored `--static`'s translucency data entirely; only
    its colour-cycle preview mode applied it.
  - `shape-export` never auto-detected TFA translucency even with
    `--shape N` and `--static` both given, requiring a separate
    `--translucent` flag; it now auto-detects, keeping `--translucent`/
    `--translucent-bg` as an explicit override for standalone `.shp`
    input with no shape number to look up.
  - `save_gif` snapped translucent pixels straight to fully opaque with
    no blending, since GIF has no partial-alpha support; it now
    pre-composites them onto a solid background first, then flattens.

---

## [0.6.9.1]

### Added

- Added `titan u7 shape-animate` to render a shape's animation to a GIF,
  auto-detecting whether it uses TFA frame-sequence animation(a
  moongate cycling frames) or palette colour-cycling on a single fixed
  frame(a weapon's glowing power stroke), with real per-type timing.

---

## [0.6.9]

### Added

- Added `titan u7 palette-info` for palette slot occupancy, semantic names,
  encoding, and colour-cycling range inspection.
- Added real U7 colour-cycling and translucency compositing support, plus
  `--indexed`, `--cycle-phase`, `--translucent`, and `--translucent-bg`
  options on `u7 shape-export`/`shape-batch` for exact-index and
  translucency-aware exports.
- Added interleaved "double" palette support and an explicit `--encoding`
  override for ambiguous 6-bit/8-bit palettes.

### Changed

- Hardened `PALETTES.FLX` slot parsing to distinguish empty from
  invalid/truncated/overlapping records, and to preserve original palette
  bytes losslessly.
- `titan u7 map-render` translucency now sources real per-game
  `XFORM.TBL`/`BLENDS.DAT` data instead of a hardcoded approximation (same
  default output).

### Fixed

- Fixed `titan u7 palette-export` crashing with an unhandled traceback on real
  `PALETTES.FLX` archives that contain unallocated palette slots.

---

## [0.6.8]

### Added

- Added U7 monster definition and spawn-data support:
  - `MONSTERS.DAT` parser support for base and mod monster definition files,
    including decoded stats, movement flags, immunities, vulnerabilities,
    attack mode, equipment offset, SFX, raw bytes, and merged base/mod output.
  - Monster `equip.dat` parsing and monster spawn reports that join monster
    eggs to resolved `MONSTERS.DAT` definitions and equipment rows.
  - `titan u7 monster-defs` for decoded monster definition dumps.
  - `titan u7 monster-dump` for live `monsnpcs.dat` monster actors from
    loose Exult-format runtime files, GAMEDAT directories, or save archives.
  - `titan u7 monster-report` for joined monster exports covering definitions,
    live monsters, monster eggs, and placed monster-class world objects.
- Added `titan u7 monster-equipment` to calculate possible monster equipment
  from `MONSTERS.DAT` plus `equip.dat`, including probability, random quantity
  handling, and expected quantity per spawn.
- Added U7 NPC inventory/equipment export support:
  - NPC inventory item export from parsed `npc.dat` inventory blocks.
  - `titan u7 npc-equipment` to export actual saved NPC inventory/equipment
    with `readied_or_actor_top`, `backpack_container`, `backpack`, and
    `nested_container` location labels.
- Added U7 static metadata parser support:
  - `WIHH.DAT` parser and `titan u7 wihh-dump` for actor weapon-in-hand frame
    offsets.
  - `titan u7 static-data-dump` for `weapons.dat`, `ammo.dat`, `armor.dat`,
    `container.dat`, `xform.tbl`, `blends.dat`, and `usecode` function-index
    metadata.
  - BG/SI Exult-format bundled-data support for `static-data-dump`: when loose
    `container.dat` or `blends.dat` files are absent, Titan can read the
    corresponding records from an installed `exult_bg.flx` / `exult_si.flx`
    data bundle. Blend exports also fall back to the documented 17-entry U7
    translucency table when no loose or bundled source is available.
- Added U7 `USECODE` parser and raw analysis commands:
  - `titan u7 usecode-scan-intrinsic` finds `CALLI` / `CALLIS` references to a
    target intrinsic and reports function id, file offset, relative offset,
    argument count, return/no-return opcode flavor, and raw bytes.
  - `titan u7 usecode-disasm` emits conservative assembly-style bytecode for a
    single function or every function in a `USECODE` file without claiming
    high-level decompilation.

### Changed

- Expanded U7 egg CSV export for monster eggs with decoded monster shape,
  frame, spawn count, schedule, and alignment fields.
- Expanded `npc-equipment` location labels with `ready.dat` preferred ready
  slots, and expanded `monster-equipment` with runtime-generated ammo rows for
  ammo-using monster weapons in Exult-format data.
- Cleaned U7 `build_exclude_set(no_building=True)` control flow so building
  exclusion uses the same decision path as bit-flag filters.
- Cleaned U7 typeflag statistics so the flag section counts only actual
  TFA/occlusion/obstacle flags, while shape classes and animation types remain
  separate.

### Fixed

- Added U7 `npc.dat` flavor handling so loose NPC files are auto-scored as
  Exult-format runtime vs original new-game data where possible, ambiguous
  loose files report unknown sex, and `gamedat-info` decodes original
  `INITGAME.DAT` NPC sex with the correct inverted bit-9 rule.
- Filtered NPC inventory exports against the real `SHAPES.VGA` record count so
  Exult-format text-message combat bark IDs are not reported as carried items.

---

## [0.6.7]

### Added

- Completed the U8 Spell Catalog with all 36 castable spells across
  Necromancy, Sorcery, Thaumaturgy, and Theurgy, including mana costs and
  their usage context, incantations, reagents, focuses, and source references.

### Changed

- Made BASEBOOK the sole book-icon entry and library launcher in the Objects
  list, kept its related classes tagged as library sources, and pinned BASEBOOK
  above the alphabetically sorted object entries.
- Improved the library interface with content-aware counts, spell-specific
  Slot labels, stricter data-schema checks, keyboard-accessible section tabs,
  and clearer list/detail navigation.
- Excluded SCROLL2 consumable-effect handlers from the readable Scrolls
  catalogue; the underlying scroll objects and effects remain available in
  the dialogue data.

### Fixed

- Corrected BASEBOOK quality `0x66` to use Resurrection's own
  `SGBOOK::func1D26` text instead of Intervention's duplicate dispatch, while
  keeping Resurrection out of the castable Spell Catalog.
- Corrected Spell Catalog content reporting so metadata-backed spell entries
  are no longer presented as having no readable content.
- Centralized NPC, Object, and Util classification so sidebar and header
  counts remain consistent.

---

## [0.6.6]

### Added

- Added `titan dialogue copy` as an optional post-prepare step that prompts
  for a destination and copies NPC JSON files plus their bundled META JSON
  sidecars.

---

## [0.6.5]

### Added

- Added three new U7 data-inspection commands:
  - `titan u7 world-query` for IFIX and IREG placement filtering by shape,
    class, flags, and area.
  - `titan u7 egg-query` for decoded egg trigger inspection with table or CSV
    output.
  - `titan u7 container-browse` for nested container traversal with tree or
    CSV output.
- Expanded U7 naming resolution with layered sources:
  - Base shape names from `TEXT.FLX`.
  - Per-frame names from Exult FLX data.
  - Optional mod overrides from `textmsg.txt` and `shape_info.txt`.
- Added stronger Exult-aware setup and config discovery:
  - Detects runtime `gamedat` paths in user-profile Exult folders.
  - Discovers mod roots, saves, and archive/initgame sources.
  - Writes Exult paths into config when available.
- Added multi-map mod support for `world-query` and `map-render` via
  `--map-num`.
- Improved dialogue web branch reporting:
  - Random branch roll/chance reporting.
  - Flag-branch ending hints to suggest alternate outcomes.
- Added dialogue web library generation in `titan dialogue prepare` /
  `validate`, covering books, scrolls, graves, plaques, and spell catalog
  entries with a sectioned web library browser.

### Fixed

- Corrected dialogue web condition handling for mixed random and
  `strcmp`-driven branch flow.

---

## [0.6.4]

### Added

- **U7 loose NPC schedule exports:** added `titan u7 npc-dump` for loose
  `npc.dat` / `GAMEDAT` data and `titan u7 schedule-dump` for loose
  `schedule.dat`, including automatic sibling `npc.dat` name resolution.
- **U7 TFA reference output and notes:** added
  `u7 typeflag-dump --format detail` output plus source-checked parser notes
  for `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT`, shape classes,
  and BG/SI animation nibbles.
- **U7 Exult runtime source discovery:** `titan setup` now records live
  Exult profile `GAMEDAT` paths when initialized, detects mod
  `patch/initgame.dat` archives, and `u7 gamedat-info --mod NAME` can inspect
  configured/user-profile mod sources.

### Fixed

- Replaced CSV serialisation in `typeflag.py`, `save.py`,
  and `cli.py` with Python's standard `csv.writer` module for robust export
  output.
- Corrected U7 NPC and inventory parsing edge cases in runtime data paths,
  including IREG special-entry skipping so `npc.dat` parsing continues past
  Avatar inventory and exports all declared NPC records.
- Removed duplicate raw type-flag columns from U7 NPC CSV exports.
- Corrected U7 TFA parsing so BG/SI animation bytes at offset `3 * 1024` are
  decoded as packed animation nibbles instead of extra shape records.
- Corrected U7 SHPDIMS decoding/export labels to expose raw `dimY, dimX`
  bytes, X/Y obstacle bits, and decoded dimension payloads.
- Corrected the U8 dialogue web engine loop safety guard so long valid
  conversations that pause at an `Ask` no longer force-end after ten topic
  choices, while no-pause runaway loops are still capped.
- Corrected loose Exult `GAMEDAT/npc.dat` sex export to decode runtime
  `type_flags` bit 9 directly, while `INITGAME.DAT` still uses Exult's
  original new-game inversion path.
- Added raw ZIP archive support for Exult mod `initgame.dat` containers and
  initgame parsing in Exult mod data paths.

### Correction

- The U7 Exult runtime source discovery note above was incomplete: Exult
  stores initialized base-game and mod runtime files under its profile data
  folders, not only under the installed game or mod directories. The expanded
  setup/path handling is tracked in `0.6.5`.

---

## [0.6.3]

### Added

- **Expanded `titan setup` wizard:** setup now detects and configures
  Ultima 8 plus Ultima 7 (Black Gate and Serpent Isle) in one pass,
  prints a consolidated path summary, supports confirmation before write,
  and writes multi-game config sections (`[u8.*]`, `[u7bg.*]`, `[u7si.*]`).
- **New `titan dialogue` command group:** added end-to-end U8 dialogue web
  workflow commands:
  - `titan dialogue prepare` to generate runtime dialogue artifacts
  - `titan dialogue validate` to verify required outputs
  - `titan dialogue launch` to start the local dialogue web viewer
- **Dialogue web theme system updates:** added runtime theme switching with
  Palettes, preview swatches, tokenized CSS theme
  contract improvements (`--bg-main`, `--font-heading`, `--text-soft`), and
  readability/UX polish for Look/Book surfaces (including clearer book-first
  discoverability for `BASEBOOK` in the Objects list).

---

## [0.6.2]

### Added

- **`u7 map-render` tile-rectangle highlights:** new repeatable
  `--highlight-tile-rect tx0,ty0,tx1,ty1,#RRGGBB[AA]` option overlays
  world-tile rectangle bounds on rendered maps. Each rectangle can have
  its own colour code, with optional alpha channel (`#RRGGBBAA`).
- **Highlight stroke control:** new `--highlight-width` option controls
  rectangle outline thickness in pixels.
- **Highlight visibility controls:** `--highlight-fill-alpha` adds a
  configurable semi-transparent fill, `--highlight-lift` applies projected
  lift to overlays, and `--highlight-labels` draws per-rectangle coordinate
  labels (`tx0,ty0,tx1,ty1`) for easier map annotation.
- **Custom highlight labels:** `--highlight-tile-rect` now accepts optional
  custom label text (`...,#RRGGBB,label`). Highlight text is centered in each
  rectangle both horizontally and vertically.
- **Default highlight fill:** fill defaults to `128` (50% opacity), so
  underlying terrain and objects remain visible.
- **RGBA composited highlight fill:** rectangle fill is rendered through an
  overlay layer and composited onto the map for proper translucent blending.
- **Larger overlay text:** highlight coordinate/custom label text size is
  now tripled for readability on full-world renders.
- **Zone profiles for `u7 map-render`:** new `--zone-profile` option loads
  canonical rectangle sets from packaged JSON data (`si_zones`,
  `bg_zones`) and renders them through the existing highlight path.
- **Zone ID filtering:** new repeatable `--zone-id` option selects specific
  zones from a profile; `--all-zones` includes every zone.
- **Overlay composition retained:** profile-based zones and manual
  `--highlight-tile-rect` overlays can be used together in the same render.

### Fixed

- **U7 music export sound compatibility:** added a dedicated General MIDI
  conversion mode to `u7 music-export` (`--target gm`) to address SC-55/
  SC-88 playback issues from MT-32-oriented track data. The conversion path
  now applies GM-friendly patch remapping while preserving MIDI timing.

---

## [0.6.1]

### Fixed

- **`map-sample` RLE terrain:** colour-sampled minimap now uses nearby-flat
  fill for RLE terrain shapes, matching the classic renderer. Eliminates
  misleading centre-pixel colours from large sprites.
- **`map-sample` IFIX overlay removed:** fixed stray coloured specs and
  lavender/purple dots caused by sampling single pixels from mountain wall
  and small IFIX object sprites.
- **`map-sample` void tile halo:** shape 12 frame 0 (palette-cycling void)
  no longer bleeds bright blue around mountains and buildings; also fixed
  `_find_nearby_flat()` whole-chunk fallback to skip the void tile.
- **`map-sample` fortress floor:** remap shape 18 frame 16 (near-black
  indoor floor) to frame 0 (stone grey) so castle interiors are visible.
- **`map-sample` grid overlay:** dual-tier grid: blue chunk grid (scale <= 2)
  with coordinate labels + red superchunk grid with SC number labels.
- **CLI help:** `--grid` descriptions for `map-render` and `map-sample` now
  correctly describe chunk vs superchunk grid behaviour.

---

## [0.6.0]

### Added: Ultima 7 support

- **Multi-game architecture:** game-specific commands live under `titan u8`
  and `titan u7` sub-apps; shared commands remain at root.
- **U7 shapes:** read/write U7 RLE shapes and VGA Flex archives
  (`SHAPES.VGA`, `FACES.VGA`, etc.). `U7Shape.to_bytes()` / `.save()` for
  round-trip encoding. New commands: `shape-export`, `shape-batch`.
- **U7 palettes:** 12-palette `PALETTES.FLX` support. New: `palette-export`.
- **U7 music:** Flex-based XMIDI extraction (`ADLIBMUS.DAT`, `MT32MUS.DAT`,
  etc.) and standalone `.xmi` conversion. Multi-track XMIDI now produces
  MIDI Format 1. New: `u7 music-export`, `u8 music-export`.
- **U7 sound:** Creative Voice (.voc) decoder with ADPCM support; batch
  speech export from `U7SPEECH.SPC`. New: `voc-export`, `speech-export`,
  `u8 sound-export-all`.
- **U7 map rendering:** parallel oblique projection (classic / flat / steep),
  IFIX + optional IREG objects, dependency-DAG depth sorting, TFA flag
  filtering, `--full` world render, colour-sampled minimap.
  New: `map-render`, `map-sample`.
- **U7 type flags:** `TFA.DAT`, `SHPDIMS.DAT`, `WGTVOL.DAT`, `OCCLUDE.DAT`
  parser with animation nibbles, shape class enum, and `build_exclude_set()`.
  New: `typeflag-dump` (summary / detail / csv).
- **U7 savegame reader:** Exult `.sav` (ZIP & FLEX), global flags, save
  metadata, NPC stats, schedules. New: `save-list`, `save-extract`,
  `gflag-dump`, `save-info`, `save-npcs`, `save-schedules`.
- **Multi-game config:** `titan.toml` now supports `[u7bg.*]` / `[u7si.*]`
  sections alongside the existing `[u8.*]` / legacy `[game]` format.
- **Enhanced grid overlays:** chunk coordinate labels and superchunk
  boundary lines for both U7 and U8 map commands.

### Added: U7 font creation

- **Font wizard:** new `titan u7 font-create` interactive wizard builds
  Exult-compatible font shapes from TrueType sources. Steps: game/archive
  selection, slot picking (11 BG/SI stock presets), TTF source, render
  method, dimensions, palette, preview, and output (`.shp` or Flex patch).
  Non-interactive batch mode via `--config recipe.toml`.
- **Font rendering pipeline:** `titan.fonts` package: FreeType mono/grayscale
  renderer, palette LUT mapper (7 built-in LUTs), glyph-to-shape encoder.
- **Hollow gradient rendering:** stroke outline + vertical gradient fill with
  morphological erosion; 30 built-in gradient presets (from U7 palette and
  [uiGradients](https://uigradients.com)) with ANSI colour swatch display.
  Hex-to-palette resolver maps any CSS gradient to nearest game indices.
- **Bundled TTFs:** six fonts: dosVga437-win, Ophidean Runes, Britannian
  Runes I/II/II Sans Serif, and Gargish. See [FONTS_CREDITS.md](FONTS_CREDITS.md).
- **Exult integration:** parses `exult.cfg` for game paths and font config;
  scans game directories for `*font*.vga` archives; shows live slot tables
  from actual Flex data; resolves mod patch directories for archive patching.
- **Exult Studio preview:** auto-fills frame 65 (the hardcoded thumbnail
  frame) with a representative glyph for non-standard layouts (Gargish,
  Runic, Serpentine).

### Changed

- **CLI restructure:** U8 commands moved under `titan u8 <cmd>` with
  deprecated root-level aliases. Modules relocated to `titan.u8.*` with
  backward-compatible shims.

### Fixed

- U7 palette 6-bit→8-bit scaling no longer fooled by garbage at index 255.
- `map-render` hex superchunk input (`--sc 0x55`) now accepted.
- RLE terrain tiles promoted to depth-sorted objects with correct anchoring;
  eliminates black strips between multi-tile terrain.
- Dependency-DAG uses actual pixel bounds for overlap (fixes tall sprites
  rendering on top of roofs).
- Cross-superchunk depth ordering uses a single global pass (fixes
  furniture visible through rooftops at boundaries).

### Known issues

- U7 MIDI export doesn't sound 100% yet. Some tracks may have timing or
  instrument mapping differences compared to the original game playback.

---

## [0.5.3] (2026-03-22)

### Added

- **FLX name tables:** auto-detect and parse embedded name tables
  (`SOUND.FLX`, `MUSIC.FLX`); named file extraction (`NNNN_NAME.<ext>`);
  metadata sidecars (`.meta.txt`); `flex-list` Name column; library
  `summary()` / `record_table()` methods.
- **Speech FLX:** per-NPC speech archives (`E44.FLX`, etc.) with dialogue
  transcript extraction and Sonarc audio at 11,111 Hz.
- **Text content detection:** `detect_record_type()` returns `"text"` for
  plain-ASCII records.

### Changed

- Manifest format expanded to four columns for round-trip rebuilds.

### Fixed

- Name-table heuristic rejects space characters (prevents speech transcript
  false positives).
- Sidecar extension changed from `.txt` to `.meta.txt` to avoid overwriting data.
- `from_directory()` rebuild updated for `.meta.txt` sidecars.
- Build: fix duplicate `.npy` LUT files in wheel (hatchling config).
- CI: Trusted Publishers (OIDC) for PyPI; remove duplicate trigger.

---

## [0.4.0] (2026-03-20)

First public release.

### Added

- **CLI:** 26 Typer-based commands covering Flex archives, shapes, palette,
  Sonarc audio, XMIDI music, world maps, saves, credits, type-flag data,
  gump layout, colour transforms.
- **U8 map renderer:** isometric and bird's-eye views with dependency-graph
  depth sorting, 16 TYPEFLAG filter flags, live-object merge from saves.
- **Shape round-trip:** export RLE frames to PNG, edit, re-import.
- **Configuration:** `titan.toml` with auto-path resolution; `titan setup`
  wizard; `titan config` inspector.
- **Library API:** all CLI capabilities as importable Python modules.
- **PEP 561:** `py.typed` marker for type checking.

---

_Versioning note: this project started at 0.4.0 to reflect the amount of
functionality present at first release._
