import { create } from 'zustand';
import type { NPCFile, SidecarMeta } from './types';
import type { EngineState } from './engine';
import type { FlagMeta } from './data';
import { buildNpcIndex } from './data';
import { startConversation, selectOption, findTalkFunction, findShopFunction, cloneEngineState } from './engine';
import { dbg } from './debug';

const TRANSIENT_RUNTIME_FLAGS = new Set(['somebodyTalking']);

// No global flags are pre-seeded. All flags start at zero.
const DEFAULT_FLAGS: Record<string, number> = {};

function persistableFlags(flags: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(flags)) {
    if (!TRANSIENT_RUNTIME_FLAGS.has(k) && !k.startsWith('local')) {
      out[k] = v;
    }
  }
  return out;
}

function collectNpcFlagNames(npc: NPCFile | null): string[] {
  if (!npc) return [];

  const names = new Set<string>();
  for (const name of npc.flags?.read ?? []) names.add(name);
  for (const name of npc.flags?.write ?? []) names.add(name);
  return [...names].filter(name => !TRANSIENT_RUNTIME_FLAGS.has(name) && !name.startsWith('local'));
}

function resetFlagNames(flags: Record<string, number>, names: Iterable<string>): Record<string, number> {
  const next = { ...flags };
  for (const name of names) {
    if (name in next) next[name] = 0;
  }
  return next;
}

function resetAllGlobalInEngine(engine: EngineState | null): EngineState | null {
  if (!engine) return null;

  const next = cloneEngineState(engine);
  for (const name of Object.keys(next.flags)) {
    if (!TRANSIENT_RUNTIME_FLAGS.has(name) && !name.startsWith('local')) {
      next.flags[name] = 0;
    }
  }
  return next;
}

type ViewFilter = 'npc' | 'object' | 'util';

interface WorldState {
  // NPC data
  allNpcs: NPCFile[];
  npcIndex: Record<string, NPCFile>;
  sidecarMetaByNpc: Record<string, SidecarMeta | null>;
  interactiveNpcs: NPCFile[]; // filtered to those with dialogue/shop/look/behavior/utility
  selectedNpc: NPCFile | null;
  npcSearchQuery: string;
  viewFilter: ViewFilter;

  // Engine state for active conversation
  engine: EngineState | null;
  undoStack: Array<{ engine: EngineState; flags: Record<string, number> }>;
  conditionPolicy: 'permissive' | 'strict';

  // Persistent world flags (survive across conversations)
  flags: Record<string, number>;

  // Multi-value flag metadata (bit widths)
  flagMeta: Record<string, FlagMeta>;

  // Actions
  loadNpcs: (npcs: NPCFile[]) => void;
  setSidecarMeta: (npcName: string, meta: SidecarMeta | null) => void;
  setFlagMeta: (meta: Record<string, FlagMeta>) => void;
  setNpcSearch: (q: string) => void;
  setViewFilter: (f: ViewFilter) => void;
  selectNpc: (npc: NPCFile) => void;
  startTalking: (npc: NPCFile) => void;
  startShopping: (npc: NPCFile) => void;
  pickOption: (choice: string) => void;
  undoLastChoice: () => void;
  setFlag: (name: string, value: number) => void;
  resetCurrentNpcFlags: () => void;
  resetAllGlobalFlags: () => void;
  resetFlags: () => void;
  endConversation: () => void;
  setConditionPolicy: (policy: 'permissive' | 'strict') => void;
}

export const useWorldState = create<WorldState>((set, get) => ({
  allNpcs: [],
  npcIndex: {},
  sidecarMetaByNpc: {},
  interactiveNpcs: [],
  selectedNpc: null,
  npcSearchQuery: '',
  viewFilter: 'npc',
  engine: null,
  undoStack: [],
  conditionPolicy: 'strict',
  flags: { ...DEFAULT_FLAGS },
  flagMeta: {},

  loadNpcs: (npcs) => {
    // FREE is the global utility library; METHOD is the NPC base class.
    // Neither represents an in-game entity, so exclude them from the sidebar.
    const SYSTEM_CLASSES = new Set(['FREE', 'METHOD']);
    const interactive = npcs.filter(npc => {
      if (SYSTEM_CLASSES.has(npc.npc)) return false;
      const fns = Object.values(npc.functions);
      return fns.some(
        f => f.type === 'dialogue' || f.type === 'shop' || f.type === 'look' || f.type === 'behavior' || f.type === 'utility'
      );
    });
    // Sort interactive NPCs alphabetically
    interactive.sort((a, b) => a.npc.localeCompare(b.npc));
    set({ allNpcs: npcs, npcIndex: buildNpcIndex(npcs), sidecarMetaByNpc: {}, interactiveNpcs: interactive });
    dbg.logFlags('app init', get().flags);
  },

  setSidecarMeta: (npcName, meta) => {
    const { sidecarMetaByNpc } = get();
    set({ sidecarMetaByNpc: { ...sidecarMetaByNpc, [npcName]: meta } });
  },

  setFlagMeta: (meta) => set({ flagMeta: meta }),

  setNpcSearch: (q) => set({ npcSearchQuery: q }),
  setViewFilter: (f) => set({ viewFilter: f, npcSearchQuery: '' }),

  selectNpc: (npc) => set({ selectedNpc: npc, engine: null, undoStack: [] }),

  startTalking: (npc) => {
    const funcName = findTalkFunction(npc);
    if (!funcName) return;
    const { flags, conditionPolicy, npcIndex } = get();
    const engine = startConversation(npc, funcName, flags, conditionPolicy, npcIndex);
    set({ engine, selectedNpc: npc, flags: persistableFlags(engine.flags), undoStack: [] });
  },

  startShopping: (npc) => {
    const funcName = findShopFunction(npc);
    if (!funcName) return;
    const { flags, conditionPolicy, npcIndex } = get();
    const engine = startConversation(npc, funcName, flags, conditionPolicy, npcIndex);
    set({ engine, selectedNpc: npc, flags: persistableFlags(engine.flags), undoStack: [] });
  },

  pickOption: (choice) => {
    const { engine, selectedNpc, npcIndex, undoStack } = get();
    if (!engine || !selectedNpc) return;
    if (!engine.paused || !engine.menuOptions.includes(choice)) return;

    const next = selectOption(engine, choice, selectedNpc, npcIndex);
    const snapshot = {
      engine: cloneEngineState(engine),
      flags: { ...persistableFlags(engine.flags) },
    };
    // Persist any flag changes back to the world.
    set({ engine: next, flags: persistableFlags(next.flags), undoStack: [...undoStack, snapshot] });
  },

  undoLastChoice: () => {
    const { undoStack } = get();
    if (undoStack.length === 0) return;

    const snapshot = undoStack[undoStack.length - 1];
    set({
      engine: cloneEngineState(snapshot.engine),
      flags: { ...snapshot.flags },
      undoStack: undoStack.slice(0, -1),
    });
  },

  setFlag: (name, value) => {
    const { flags } = get();
    set({ flags: { ...flags, [name]: value } });
  },

  resetCurrentNpcFlags: () => {
    const { selectedNpc, flags, engine } = get();
    const names = collectNpcFlagNames(selectedNpc);
    if (names.length === 0) return;

    const nextFlags = resetFlagNames(flags, names);
    const nextEngine = engine
      ? { ...cloneEngineState(engine), flags: resetFlagNames(engine.flags, names) }
      : null;

    set({ flags: nextFlags, engine: nextEngine });
    dbg.logFlags('reset current npc', nextFlags);
  },

  resetAllGlobalFlags: () => {
    const { engine } = get();
    const nextFlags = { ...DEFAULT_FLAGS };
    const nextEngine = resetAllGlobalInEngine(engine);

    set({ flags: nextFlags, engine: nextEngine });
    dbg.logFlags('reset all global', nextFlags);
  },

  resetFlags: () => {
    set({ flags: { ...DEFAULT_FLAGS }, engine: null, undoStack: [] });
    dbg.logFlags('reset all', { ...DEFAULT_FLAGS });
  },

  endConversation: () => set({ engine: null, undoStack: [] }),

  setConditionPolicy: (conditionPolicy) => set({ conditionPolicy }),
}));
if (typeof window !== 'undefined') {
  window.useWorldState = useWorldState;
}
