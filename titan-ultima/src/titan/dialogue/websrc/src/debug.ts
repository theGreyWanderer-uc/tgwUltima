/**
 * Dialogue Engine Debug Utility
 *
 * Controls verbose console logging throughout the engine.
 *
 * Usage in browser console:
 *   window.dialogueDebug.on()     // enable all logging
 *   window.dialogueDebug.off()    // disable all logging
 *   window.dialogueDebug.status() // show current state
 *
 * Usage in code:
 *   import { dbg } from './debug';
 *   dbg.log('evalCondition', 'checking flag arcadionName =', val);
 */

type DebugCategory =
  | 'evalCondition'
  | 'evalLook:walk'
  | 'evalLook:result'
  | 'flags:world'
  | 'step:node'
  | 'step:block'
  | 'step:if'
  | 'step:loop'
  | 'step:menu'
  | 'step:call'
  | 'step:flag'
  | 'step:bc'
  | 'step:suspend';

const ENABLED_CATEGORIES = new Set<DebugCategory | 'all'>();

function isEnabled(cat: DebugCategory): boolean {
  return ENABLED_CATEGORIES.has('all') || ENABLED_CATEGORIES.has(cat);
}

export const dbg = {
  log(cat: DebugCategory, ...args: unknown[]) {
    if (isEnabled(cat)) {
      console.log(`[${cat}]`, ...args);
    }
  },
  group(cat: DebugCategory, label: string, fn: () => void) {
    if (isEnabled(cat)) {
      console.group(`[${cat}] ${label}`);
      fn();
      console.groupEnd();
    } else {
      fn();
    }
  },
  warn(cat: DebugCategory, ...args: unknown[]) {
    if (isEnabled(cat)) {
      console.warn(`[${cat}]`, ...args);
    }
  },
  /** Dump the full world-flag state to the console under the 'flags:world' category. */
  logFlags(label: string, flags: Record<string, number>) {
    if (!isEnabled('flags:world')) return;
    const entries = Object.entries(flags);
    console.group(`[flags:world] ${label}`);
    if (entries.length === 0) {
      console.log('  (no flags set)');
    } else {
      for (const [k, v] of entries) console.log(`  ${k} = ${v}`);
    }
    console.groupEnd();
  },
};

// ── Browser global controls ───────────────────────────────────────────────────

const controls = {
  on(...cats: (DebugCategory | 'all')[]) {
    const toEnable = cats.length === 0 ? ['all' as const] : cats;
    for (const c of toEnable) ENABLED_CATEGORIES.add(c);
    console.log('[dialogueDebug] enabled:', [...ENABLED_CATEGORIES]);
  },
  off(...cats: (DebugCategory | 'all')[]) {
    if (cats.length === 0) {
      ENABLED_CATEGORIES.clear();
    } else {
      for (const c of cats) ENABLED_CATEGORIES.delete(c);
    }
    console.log('[dialogueDebug] enabled:', [...ENABLED_CATEGORIES]);
  },
  status() {
    if (ENABLED_CATEGORIES.size === 0) {
      console.log('[dialogueDebug] OFF — call dialogueDebug.on() to enable');
    } else {
      console.log('[dialogueDebug] ON — active categories:', [...ENABLED_CATEGORIES]);
    }
  },
  categories(): string[] {
    return [
      'all',
      'evalCondition',
      'evalLook:walk',
      'evalLook:result',
      'step:node',
      'step:block',
      'step:if',
      'step:loop',
      'step:menu',
      'step:call',
      'step:bc',
      'flags:world',
      'step:flag',
      'step:suspend',
    ];
  },
};

// Enable everything by default — turn off with dialogueDebug.off() in console.
controls.on();

if (typeof window !== 'undefined') {
  window.dialogueDebug = controls;
}
