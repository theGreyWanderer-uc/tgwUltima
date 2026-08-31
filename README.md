#  ◄◄◄ theGreyWanderer's Ultima ►►► 

## 🧙‍♂️ Welcome!
I'm learning to code and thought I was going to start with something fun and simple. Well... I only got it 50% correct!
<br><br>

## Titan Ultima Toolkit

This repository is an **Ultima reverse-engineering and game-modding toolkit**
for classic **Origin Systems** games. It contains research, source data,
modding resources, and tools for inspecting, extracting, converting,
rendering, and rebuilding Ultima game data.

[**Titan Ultima**](titan-ultima/) is the main command-line toolkit. Its
game-specific commands work with archives, graphics, maps, palettes, audio,
saves, dialogue, world objects, and other proprietary Ultima formats without
requiring every project to maintain a separate parser.

## Ultima VII and Exult Support

Support for **Ultima VII (Ultima 7): The Black Gate**, **Serpent Isle**, and
the **Exult** engine includes Flex archives, SHP/VGA graphics, palettes, maps,
terrain chunks, IFIX and IREG objects, audio, saves, NPC data, schedules,
monsters, fonts, and Exult runtime data. Titan can export, render, and rebuild
U7 maps through a portable JSON format, including secondary Exult maps.

See [u7data](u7data/) and the [Titan Ultima documentation](titan-ultima/README.md).

## Ultima VIII: Pagan Support

Support for **Ultima VIII (Ultima 8): Pagan** includes Flex archives, shapes,
maps, palettes, music, sound effects, saves, static metadata, dialogue data,
and conversion of U8 scenery into U7/Exult-compatible shapes. Titan also
includes a local web interface for inspecting prepared Ultima VIII dialogue.

See [u8data](u8data/), [usecode](usecode/), and the
[Titan Ultima documentation](titan-ultima/README.md).

## Supported Ultima Games and Formats

| Game | Selected Titan support | Repository data |
|---|---|---|
| **Ultima III (Ultima 3): Exodus — NES** | Convert the original NES Sosaria overworld into an SI-sized U7/Exult map, with portable JSON, native map files, and classic rendering | [u3 NES data](u7data/u3nesData/) |
| **Ultima VI (Ultima 6): The False Prophet** | LZW and library archives, tiles, palettes, maps, world objects, actors, eggs, saves, flags, dialogue bytecode, fonts, books, and schedules | [u6data](u6data/) |
| **Ultima VII (Ultima 7): The Black Gate and Serpent Isle** | Flex and shape files, palettes, maps, audio, saves, NPCs, schedules, monsters, containers, eggs, Usecode analysis, and Exult runtime formats | [u7data](u7data/) |
| **Ultima VIII (Ultima 8): Pagan** | Flex archives, shapes, maps, palettes, music, sound, saves, metadata, dialogue, and U8-to-U7 shape conversion | [u8data](u8data/) |
| **Ultima Underworld II: Labyrinth of Worlds** | Map extraction and verification, 2D and 3D rendering, GLB export, terrain, textures, palettes, shapes, objects, doors, and executable models | [uuw2data](uuw2data/) |
| **Ultima IX (Ultima 9): Ascension** | Early support for FLX archives, type names, sound and speech, 3D models, textures, and interface icons | [u9data](u9data/) |
| **Ultima Online Classic Client** | UOP and MUL/IDX extraction for art, gumps, textures, lights, hues, radar colours, tile data, animations, localization, multis, fonts, and sound | [uodata](uodata/) |

Detailed commands and current limitations are documented in
[Titan Ultima](titan-ultima/README.md).

## Usecode Tools

The repository includes **Usecode** source, research, and modding examples for
Ultima and Exult projects. Titan adds Ultima VII intrinsic scanning and raw
Usecode disassembly, Ultima VI conversation-bytecode disassembly, and Ultima
VIII dialogue preparation, validation, and inspection tools.

See the [Usecode sources](usecode/) and
[Titan Ultima CLI reference](titan-ultima/cli_reference.md).

## 🌍 **Stay Connected**
- **Discord** (I can be found on the UDIC Discord Server)

---

## 📝 **Acknowledgments**
- A huge thank you to the **Ultima** community and to the **UDIC** for keeping this classic alive.
- Special thanks to the 🌐 [**EXULT Team**](https://github.com/exult) for their great work without which makes all of this impossible.
- Of course very special thank you to **Richard Garriott** and **Origin Systems** for all of their creativity in the creation of the Ultima Saga.

---

## 📜 **Important Note**:
**Ultima VII** (Copyright 1993) ⛓️

To use this fan-made content, you **must** own a copy of the original 🌐 [**Ultima VII: The Black Gate**](https://www.gog.com/en/game/ultima_7_complete)
 and/or 🌐 [**Ultima VII Part 2: Serpent Isle**](https://www.gog.com/en/game/ultima_7_complete). 🏰

(Optional) If you have the **add-ons** too, you can enjoy even more of the experience!

This project is strictly for fans who want to enhance their **Ultima VII** adventure and is in no way affiliated with **Electronic Arts**. All rights to Ultima VII remain with Electronic Arts. Please respect the intellectual property of **Electronic Arts** and ensure you have the original game in your collection. 🎮

---
