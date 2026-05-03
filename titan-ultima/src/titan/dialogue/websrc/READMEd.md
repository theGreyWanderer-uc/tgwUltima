# U8 Dialogue Viewer

An interactive web application for exploring decompiled Ultima VIII: Pagan dialogue. The viewer parses structured JSON extracted from Pentagram's `fold.exe` decompiler output and presents NPC conversations as a playable, branching dialogue system — complete with world flag tracking, look descriptions, and shop inventories.

## Goal

Reconstruct the full dialogue experience of Ultima VIII from decompiled usecode bytecode, making it browsable and testable without running the game engine. This serves as:

- **A research tool** for documenting Ultima VIII's narrative content, NPC behaviors, and game flag logic.
- **A testing harness** for verifying the correctness of Pentagram's `fold.exe` decompiler output.
- **A reference** for anyone studying Ultima VIII's scripting system or building mods.

## Features

### Dialogue Engine
- **Branching conversations** — Full ask/strcmp_branch routing: player chooses from menu options, engine matches against strcmp branches and executes the corresponding body.
- **Conversation loop-back** — After answering a question, the engine loops back to the ask node for the next choice (replicating the original usecode `while(not "bye")` pattern).
- **Chain-based mutual exclusion** — If/else-if/else greeting chains use a `chainId`/`branchIndex` system so only one branch fires per chain, even across nested conditions.
- **Sub-function calls** — `call` nodes follow into sub-functions within the same NPC (e.g., separate topic handlers).
- **Multi-value flag comparisons** — Conditions like `flag == 0x03h` and `flag != 0x00h` are evaluated with proper hex parsing.
- **Flag side effects** — `set_flag` nodes and inline side effects on bark/dialogue_line nodes modify world state during conversation.
- **Flag change messages** — When a flag changes during dialogue, a `⚑ flagName = value` system message appears in the chat.
- **Menu operations** — `menu_set`, `menu_add`, `menu_union`, `menu_remove` dynamically build the player's choice list.

### NPC Browser
- **516 data files** covering every usecode class in Ultima VIII (NPCs, objects, spells, items).
- **NPC/Object filter** — Toggle between NPCs (characters with dialogue) and objects (items, world interactables).
- **Search** — Real-time filtering of the sidebar by name.
- **Look panel** — Shows the NPC's look descriptions with flag-conditional variants (e.g., "a man" vs. "Devon" depending on whether `devonName` is set), plus a Runtime `Alive`/`Dead` toggle in the modal to preview either branch.
- **Action buttons** — "Talk to NPC", "Look at NPC", shop buttons, and a "Describe" utility button for utility-only classes.

### Shop Viewer
- **Display-only shop panel** — Shows extracted shop inventory entries for shop functions.
- **Prices and descriptions** — Renders item name, numeric price, and description fields when present.
- **Intentional scope** — Browse-only UI; no buy/sell simulation, stock mutation, currency logic, or transaction state.

### Utility Function Viewer
- **Describe modal for utility/behavior classes** — For entries without talk/look/shop/book flows, the UI exposes a `Describe` action that opens a utility viewer.
- **Metadata summary + one-liners** — Shows source file, function counts, read/write flag totals, and sidecar-derived role summaries when metadata is available.
- **Utility function catalog** — Lists behavior/utility functions with process mode, node count, and a per-function action.
- **Process execution report** — `Start Process` runs the selected function through the engine and reports call chain, changed flags, unresolved condition count, paused/ended state, and recent history lines.

### Flag Inspector
- **NPC-scoped flags** — By default shows only flags read/written by the selected NPC, with toggle to show all 414+ global flags.
- **Active flags display** — Flags that are currently set appear in a separate highlighted section with their current values.
- **Multi-value flags** — 47 flags with bit width > 1 show a number input with proper min/max bounds instead of a simple toggle.
- **Boolean flags** — Single-bit flags show Set/Clear toggle buttons.
- **Search** — Filter flags by name within the inspector.
- **Persistent across conversations** — Flags survive when switching NPCs or restarting conversations.

### UI
- **Golden Hour theme** — Warm color palette (mustard accent, terracotta danger, chocolate text, warm beige backgrounds) inspired by Ultima VIII's Pagan aesthetic.
- **New Conversation button** — Always visible during active conversations for quick restart.
- **System messages** — Conversation start/end markers, flag changes, and unresolved call targets shown inline.

## Project Structure

```
dialogue/
├── pipeline/
│   ├── extract_ast.py        # Python extractor: folded pseudo-code → structured JSON AST
│   ├── build_data.py         # Copies json/ → websrc/public/data/ + manifest.json
│   └── lint_json.py          # JSON validation / linting
├── json/                     # Raw extracted JSON (516 files, gitignored)
│
└── websrc/                   # React web application
    ├── package.json          # Dependencies: React 19, Zustand 5, Vite 6, Playwright
    ├── vite.config.ts
    ├── playwright.config.ts
  ├── build_data.py         # Local equivalent of pipeline/build_data.py
    │
    ├── public/data/          # Served JSON data files (516 NPC/object files + metadata)
    │   ├── manifest.json     # Array of all JSON filenames
    │   ├── flag_metadata.json # Multi-value flag bit widths and max values
    │   └── U8P_*.json        # Per-class structured dialogue data
    │
    ├── src/
    │   ├── main.tsx          # Entry point
    │   ├── App.tsx           # Root component, data loading, layout
    │   ├── types.ts          # TypeScript types mirroring extract_ast.py output
    │   ├── data.ts           # Data loading (manifest, NPC files, flag metadata)
    │   ├── store.ts          # Zustand store (world state, flags, NPC selection, engine)
    │   ├── engine.ts         # Dialogue execution VM (step, evalCondition, loop-back)
    │   ├── DialoguePlayer.tsx # Conversation UI (messages, choices, New Conversation)
    │   ├── NPCSidebar.tsx    # Sidebar NPC/object list with search and filter
    │   ├── FlagInspector.tsx  # Flag panel (scoped, multi-value, search)
    │   ├── LookPanel.tsx     # Look description panel with flag-conditional display
    │   └── styles.css        # Golden Hour theme, all component styles
    │
    └── tests/
        └── app.spec.ts       # 17 Playwright end-to-end tests
```

### Data Pipeline

```
fold.exe --pseudo *.u8o        (C++ decompiler — produces .txt pseudo-code)
        ↓
extract_ast.py                 (Python — parses pseudo-code → structured JSON AST)
        ↓
dialogue/json/U8P_*.json       (516 files — one per usecode class)
        ↓
build_data.py                  (copies to websrc/public/data/ + manifest)
        ↓
web app loads manifest.json → fetches each NPC file on startup
```

### JSON Data Format

Each `U8P_*.json` file contains:

```json
{
  "npc": "DEVON",
  "sourceFile": "U8P_DEVON.txt",
  "functions": {
    "use": {
      "name": "use",
      "type": "dialogue",
      "isProcess": false,
      "processType": "0207",
      "nodes": [
        {
          "id": "n001",
          "type": "bark",
          "text": "Hello there, {getName}!",
          "condition": {
            "flags": [{ "flag": "devonMet", "negated": true }],
            "chains": [{ "chainId": 1, "branchIndex": 0 }]
          },
          "sideEffects": [{ "set": "devonMet", "value": "1" }]
        }
      ]
    }
  },
  "flags": { "read": ["devonMet", "devonName"], "write": ["devonMet"] },
  "stats": { "totalFunctions": 14, "dialogueFunctions": 1, "totalNodes": 150 },
  "hasDialogue": true
}
```

## Past Issues Resolved

### Fold Decompiler (C++ — `fold.exe`)
| Issue | Description | Fix |
|-------|-------------|-----|
| **Bug A — JNE polarity inversion** | Conditional branches had inverted true/false logic | Fixed JNE condition polarity in fold's control flow pass |
| **Bug B — Control flow misrouting** | Some if/else blocks routed to wrong targets | Corrected block boundary detection in the folding algorithm |
| **Bug C — Cross-function else blocks** | 18 functions had else blocks spanning across function boundaries | Fixed scope tracking to stop else propagation at function edges |
| **Bug D — Cross-function else (final)** | Residual cross-function else artifacts after Bug C fix | Complete elimination — audit drops from 18 → 0 |
| **Crashes & missing opcodes** | Various opcodes caused fold.exe to crash or produce empty output | Added handlers for all missing opcodes |
| **BP variable naming** | Stack variables showed raw byte offsets instead of readable names | Implemented BP-to-local-variable name resolution |
| **Function name resolution** | Calls showed raw addresses instead of `CLASS::functionName` | Built resolution system covering 63 functions across 14 classes |
| **Result**: 516/516 classes decompile cleanly (0 errors, 0 crashes) | | |

### Dialogue Extractor (`extract_ast.py`)
| Issue | Description | Fix |
|-------|-------------|-----|
| **Lost nested conditions** | Inner nodes lost outer scope flag conditions | `_current_cond()` merges conditions from ALL nesting levels |
| **Unconditional non-dialogue nodes** | `set_flag`, `call`, `menu_*` nodes ignored enclosing conditions | All node types now inherit conditions via `_current_cond()` |
| **Missing comparison operators** | Only boolean flag checks; couldn't handle `flag == 0x03h` | Added `RE_FLAG_COMPARE` regex, `op`/`values` in FlagCondition |
| **No chain tracking** | If/else-if/else branches all executed sequentially | Chain counter + `active_chains` stack assigns `chainId`/`branchIndex` |

### Dialogue Engine (`engine.ts`)
| Issue | Description | Fix |
|-------|-------------|-----|
| **All greetings showing** | ARAMINA showed 4-5 greeting branches instead of 1 | Chain-based mutual exclusion with `satisfiedChains` Map |
| **Conversation dying after answer** | After "Who are you?" the conversation ended instead of looping | Added `askPc`/`branchMatched` loop-back to ask node |
| **Devon "Have you met" ending** | "Have you met Devon?" killed the conversation early | Removed `end_conversation` from `findNextBranch` boundary types |
| **New Conversation button missing** | Button disappeared after loop-back fix (never reached `ended` state) | Made button always visible during active conversation |
| **Nested chain failures** | Single chainId per node failed for nodes inside nested if/else | Evolved to `chains: ChainMembership[]` array carrying all nesting levels |

## Current Known Issues

- **`isDead` conditions** — Full runtime death state is not auto-derived from game simulation data. For look descriptions, the Look modal already provides a Runtime toggle (`Alive` / `Dead`) so you can manually inspect either branch.
- **`raw` conditions** — Complex expressions, map coordinate checks, and multi-variable conditions that don't reduce to simple flag checks are passed through as `true` (node always executes). The raw condition text is preserved in the JSON for inspection.
- **`{getName}` only** — Only `{getName}` → "Avatar" and `{npcName}` substitutions are implemented. Other runtime placeholders (item names, counts, etc.) display as-is.
- **External calls** — Calls to functions in other usecode classes (e.g., `AVATAR::someFunc`) are shown as system messages but not followed. Only intra-NPC calls are executed.
- **Ambient proximity bark randomness** — The `urandom(...)` cases identified so far are ambient proximity bark emitters, not player-driven dialogue branches. The web engine does not currently emulate their random selection semantics, so bark outcomes can be deterministic instead of randomly selected.
- **No save/load** — Flag state is held in memory only. Refreshing the page resets all flags.

## Development Environment

### Prerequisites
- **Node.js** ≥ 18 (for Vite and Playwright)
- **Python** ≥ 3.10 (for data extraction scripts)
- **Pentagram `fold.exe`** (for re-decompiling from `.u8o` bytecode — not needed if using existing JSON)

### Setup

```bash
cd dialogue/websrc
npm install
npx playwright install chromium   # first time only, for tests
```

### Data Pipeline (if re-extracting from source)

```bash
# 1. Decompile all .u8o files with fold.exe (from pentagram build)
#    This produces .txt pseudo-code files in foldExtract/

# 2. Extract structured JSON from pseudo-code
cd dialogue
python pipeline/extract_ast.py foldExtract -o json

# 3. Generate multi-value flag metadata
python gen_flag_metadata.py

# 4. Copy data files into the web app's public directory
python pipeline/build_data.py
```

### Running the Dev Server

```bash
cd dialogue/websrc
npm run dev
# Opens at http://localhost:5173 (or next available port)
```

### Running Tests

```bash
cd dialogue/websrc
npx playwright test                    # all 17 tests
npx playwright test --reporter=line    # compact output
npx playwright test --headed           # watch in browser
npx playwright test -g "loop"          # run test by name pattern
```

The Playwright config auto-starts a Vite preview server on port 4173 for testing.

### Building for Production

```bash
cd dialogue/websrc
npm run build    # outputs to dist/
npm run preview  # serves the production build locally
```

### Test Coverage Summary

| # | Test | Covers |
|---|------|--------|
| 1 | App loads NPC data | Data loading, manifest, sidebar rendering |
| 2 | Search filters | Real-time search, empty state |
| 3 | NPC selection + Look | Action buttons, look panel, flag-conditional descriptions |
| 4 | Conversation greeting | Single greeting (chain exclusion), menu choices |
| 5 | Dialogue choice response | Player message, NPC response, message count |
| 6 | Goodbye ends conversation | end_conversation, system message |
| 7 | Flag inspector | Scoped flags, All toggle, open/close |
| 8 | Flag → look change | Setting devonName changes look from "man" to "Devon" |
| 9 | Conversation flag persistence | "Who are you?" sets devonName, visible in inspector |
| 10 | No console errors | Zero JS errors during interaction |
| 11 | Complex NPC no hang | MYTHRAN (122KB) loads without infinite loop |
| 12 | Loop-back after answer | Choices reappear after answering a question |
| 13 | ARAMINA chain exclusion | Only 1 greeting from 5-branch chain |
| 14 | Flag change messages | `⚑ devonName = 1` system message appears |
| 15 | New Conversation button | Visible mid-conversation, resets on click |
| 16 | Multi-value flag inputs | Number inputs with proper min/max for multi-bit flags |
| 17 | Complex branch survival | ARAMINA survives multiple non-Goodbye choices |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI | React 19 with TypeScript 5.7 |
| State | Zustand 5 (single store, persistent flags) |
| Build | Vite 6 (dev server + production bundler) |
| Testing | Playwright (Chromium, end-to-end) |
| Data extraction | Python 3 (regex-based parser) |
| Decompiler | Pentagram `fold.exe` (C++, custom-built) |
| Data format | JSON (516 files, ~15MB total) |
