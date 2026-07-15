import type { NPCFile } from './types';

export const BOOK_CLASS = 'BASEBOOK';

export const LIBRARY_SOURCE_CLASSES = [
  BOOK_CLASS,
  'BASESCRL',
  'GRAVE_NS',
  'PLAQUENS',
  'KEYONEC',
  'PENT',
  'NEC1',
  'SCROLL1',
  'EARTHMAG',
] as const;

const LIBRARY_SOURCE_CLASS_SET: ReadonlySet<string> = new Set(LIBRARY_SOURCE_CLASSES);
const OBJECT_FUNCTION_TYPES: ReadonlySet<string> = new Set(['look', 'shop']);
const UTIL_FUNCTION_TYPES: ReadonlySet<string> = new Set(['behavior', 'utility']);

function hasFunctionType(npc: NPCFile, types: ReadonlySet<string>): boolean {
  return Object.values(npc.functions).some(func => types.has(func.type));
}

export function isLibrarySource(npc: NPCFile): boolean {
  return LIBRARY_SOURCE_CLASS_SET.has(npc.npc);
}

export function isNpcEntry(npc: NPCFile): boolean {
  return npc.hasDialogue;
}

export function isObjectEntry(npc: NPCFile): boolean {
  return !npc.hasDialogue && (isLibrarySource(npc) || hasFunctionType(npc, OBJECT_FUNCTION_TYPES));
}

export function isUtilEntry(npc: NPCFile): boolean {
  return !npc.hasDialogue && !isObjectEntry(npc) && hasFunctionType(npc, UTIL_FUNCTION_TYPES);
}

export function compareObjectEntries(a: NPCFile, b: NPCFile): number {
  if (a.npc === BOOK_CLASS) return b.npc === BOOK_CLASS ? 0 : -1;
  if (b.npc === BOOK_CLASS) return 1;
  return a.npc.localeCompare(b.npc);
}
