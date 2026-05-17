import type { DialogueFunction, DialogueNode, NPCFile, NodeCondition } from './types';

const MAX_CALL_DEPTH = 8;
const LOCAL_OR_PARAM_RE = /^(local\d+|local[A-Za-z0-9_]*|param\d+|param[A-Za-z0-9_]*)$/i;

interface WalkContext {
  npc: NPCFile;
  npcIndex: Record<string, NPCFile>;
  lines: string[];
  callPath: string[];
}

interface MenuState {
  menus: Map<string, string[]>;
}

interface OptionEntry {
  option: string;
  condition: string;
  sourceMenu: string;
  action: 'set' | 'add' | 'union';
}

interface ChoiceEntry {
  option: string;
  condition: string;
  npcLines: string[];
  adds: string[];
  removes: string[];
  sets: string[];
  writes: string[];
  exits: string[];
}

interface StateModel {
  persistentGlobals: string[];
  npcMetFlags: string[];
  multiValueFlags: string[];
  localCounters: string[];
  mapRefs: string[];
  ambientBarkFunctions: string[];
}

interface AmbientBarkEntry {
  functionName: string;
  functionType: string;
  text: string;
  condition: string;
}

function sanitizeFilename(input: string): string {
  return input.trim().replace(/[^A-Za-z0-9_.-]+/g, '_') || 'dialogue_walk';
}

function escapeMd(text: string): string {
  return text.replace(/\\/g, '\\\\').replace(/\|/g, '\\|');
}

function quoteMd(text: string): string {
  return `"${escapeMd(text)}"`;
}

function isLocalOrParam(name: string): boolean {
  return LOCAL_OR_PARAM_RE.test(name.trim());
}

function push(ctx: WalkContext, level: number, text: string): void {
  ctx.lines.push(`${'  '.repeat(level)}${text}`);
}

function cloneMenuState(state: MenuState): MenuState {
  return {
    menus: new Map(Array.from(state.menus.entries()).map(([k, v]) => [k, [...v]])),
  };
}

function menuKey(node: DialogueNode): string {
  return (node.target ?? node.menu ?? 'menu_options').trim() || 'menu_options';
}

function setMenuOptions(state: MenuState, key: string, options: string[]): void {
  state.menus.set(key, [...options]);
}

function addMenuOptions(state: MenuState, key: string, options: string[]): void {
  const current = state.menus.get(key) ?? [];
  for (const option of options) {
    if (!current.includes(option)) current.push(option);
  }
  state.menus.set(key, current);
}

function removeMenuOptions(state: MenuState, key: string, options: string[]): void {
  const current = state.menus.get(key) ?? [];
  if (current.length === 0) return;
  const removes = new Set(options);
  state.menus.set(key, current.filter(option => !removes.has(option)));
}

function formatList(values?: string[]): string {
  if (!values || values.length === 0) return '_none_';
  return values.map(v => `\`${v}\``).join(', ');
}

function formatFlagReads(cond?: NodeCondition): string[] {
  if (!cond?.flags || cond.flags.length === 0) return [];
  return cond.flags.map(flag => {
    const prefix = flag.negated ? 'not ' : '';
    const compare = flag.op && flag.values?.length
      ? ` ${flag.op} ${flag.values.join(' or ')}`
      : '';
    return `${prefix}${flag.flag}${compare}`;
  });
}

function formatCondition(cond?: NodeCondition): string {
  if (!cond) return 'true';
  if (cond.raw?.trim()) return cond.raw.trim();
  const flags = formatFlagReads(cond);
  if (flags.length > 0) {
    const joiner = cond.combinator === 'or' ? ' OR ' : ' AND ';
    return flags.join(joiner);
  }
  if (cond.isDead) {
    return cond.isDeadNegated ? `not ${cond.isDead}` : cond.isDead;
  }
  return 'true';
}

function conditionSuffix(cond?: NodeCondition): string {
  if (!cond) return '';
  const reads = formatFlagReads(cond);
  const parts = [`condition: \`${formatCondition(cond)}\``];
  if (reads.length > 0) parts.push(`reads: ${reads.map(f => `\`${f}\``).join(', ')}`);
  if (cond.isDead) parts.push('runtime death-state check');
  return ` _(${parts.join('; ')})_`;
}

function extractChoiceLabel(cond?: NodeCondition): string | null {
  if (cond?.strcmp && cond.strcmp.length > 0) return cond.strcmp[0].value;
  const raw = cond?.raw?.trim();
  if (!raw) return null;
  const m = /\bstrcmp\s+"([^"]*)"/i.exec(raw);
  return m ? m[1] : null;
}

function renderMenuOptions(options: string[]): string {
  if (options.length === 0) return '_empty or runtime-built_';
  return options.map(option => `\`${escapeMd(option)}\``).join(', ');
}

function normalizeSuggestedLabel(option: string): string {
  return option
    .trim()
    .replace(/\s+/g, ' ')
    .replace(/[?.!]+$/g, '')
    .toLowerCase();
}

function uniqueSorted(values: Iterable<string>): string[] {
  return Array.from(new Set(Array.from(values).filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

function joinCondition(parent: string, child?: NodeCondition): string {
  const formatted = formatCondition(child);
  if (!parent || parent === 'true') return formatted;
  if (!formatted || formatted === 'true') return parent;
  return `${parent} AND ${formatted}`;
}

function mapReferenceFromCondition(cond?: NodeCondition): string | null {
  const raw = cond?.raw?.trim();
  if (!raw) return null;
  const m = /Npc::getMap\(this\)\s*([=!]=)\s*(0x[0-9A-Fa-f]+h|\d+)/.exec(raw);
  if (!m) return null;

  const literal = m[2];
  let decimal = literal;
  if (/^0x/i.test(literal)) {
    decimal = String(parseInt(literal.replace(/^0x/i, '').replace(/h$/i, ''), 16));
  }
  return `Map ${literal} (${decimal}) via \`${raw}\``;
}

function shouldSkipLowLevelCall(target: string): boolean {
  return target.startsWith('METHOD::')
    || target.startsWith('FREE::')
    || target.startsWith('Npc::doAnim')
    || target.startsWith('Npc::cSetActivity');
}

function isNoiseNode(node: DialogueNode): boolean {
  if (node.type === 'Call' && shouldSkipLowLevelCall(node.target ?? '')) return true;
  if (node.type !== 'Unknown' && node.type !== 'Jump') return false;

  const raw = (node.raw ?? '').trim();
  return raw === ''
    || raw === '{'
    || raw === 'suspend'
    || raw.includes('suspend')
    || raw === 'pid'
    || raw.includes('jmp_NOPRINT')
    || raw.includes('Npc::doAnim')
    || raw.includes('Npc::cSetActivity')
    || raw.includes('FREE::resetRef')
    || raw.includes('FREE::func1C19')
    || raw.includes('<null>');
}

function resolveCallTarget(ctx: WalkContext, currentNpc: string, target: string): { npcName: string; functionName: string; nodes: DialogueNode[] } | null {
  if (!target || target.startsWith('Item::') || target.startsWith('FREE::')) return null;

  let npcName = currentNpc;
  let functionName = target;
  if (target.includes('::')) {
    const [owner, fn] = target.split('::');
    if (owner && owner !== 'METHOD') npcName = owner;
    functionName = fn;
  }

  let nodes = ctx.npcIndex[npcName]?.functions[functionName]?.nodes ?? [];
  if (nodes.length === 0 && target.startsWith('METHOD::')) {
    npcName = 'METHOD';
    nodes = ctx.npcIndex.METHOD?.functions[functionName]?.nodes ?? [];
  }
  if (nodes.length === 0) return null;
  return { npcName, functionName, nodes };
}

function walkAllNodes(nodes: DialogueNode[] | undefined, visit: (node: DialogueNode) => void): void {
  for (const node of nodes ?? []) {
    visit(node);
    walkAllNodes(node.then, visit);
    for (const elif of node.else_ifs ?? []) {
      walkAllNodes(elif.body, visit);
    }
    walkAllNodes(node.else, visit);
    walkAllNodes(node.body, visit);
  }
}

function collectBodySummary(nodes: DialogueNode[] | undefined, summary: Omit<ChoiceEntry, 'option' | 'condition'>): void {
  for (const node of nodes ?? []) {
    if (isNoiseNode(node)) continue;

    switch (node.type) {
      case 'Bark':
      case 'DialogueLine':
        if (node.text) summary.npcLines.push(node.text);
        break;
      case 'MenuAdd':
      case 'MenuUnion':
        summary.adds.push(...(node.options ?? []));
        break;
      case 'MenuRemove':
        summary.removes.push(...(node.options ?? []));
        break;
      case 'MenuSet':
        summary.sets.push(...(node.options ?? []));
        break;
      case 'SetFlag': {
        const flag = node.flag ?? 'UNKNOWN_FLAG';
        summary.writes.push(`${flag} = ${node.value ?? '1'}`);
        break;
      }
      case 'EndConversation':
        summary.exits.push(`End conversation (${node.id})`);
        break;
      default:
        break;
    }

    collectBodySummary(node.then, summary);
    for (const elif of node.else_ifs ?? []) {
      collectBodySummary(elif.body, summary);
    }
    collectBodySummary(node.else, summary);
    collectBodySummary(node.body, summary);
  }
}

function collectInitialOptions(nodes: DialogueNode[] | undefined, condition = 'true', entries: OptionEntry[] = []): OptionEntry[] {
  for (const node of nodes ?? []) {
    if (node.type === 'ConversationLoop') break;
    if (isNoiseNode(node)) continue;

    if (node.type === 'MenuSet' || node.type === 'MenuAdd' || node.type === 'MenuUnion') {
      const action = node.type === 'MenuSet' ? 'set' : node.type === 'MenuAdd' ? 'add' : 'union';
      for (const option of node.options ?? []) {
        entries.push({
          option,
          condition: joinCondition(condition, node.condition),
          sourceMenu: menuKey(node),
          action,
        });
      }
    }

    if (node.type === 'IfStatement') {
      collectInitialOptions(node.then, joinCondition(condition, node.condition), entries);
      for (const elif of node.else_ifs ?? []) {
        collectInitialOptions(elif.body, joinCondition(condition, elif.condition), entries);
      }
      if (node.else && node.else.length > 0) {
        collectInitialOptions(node.else, `${condition} AND fallback`, entries);
      }
    }
  }
  return entries;
}

function collectChoiceIndex(nodes: DialogueNode[] | undefined, entries: ChoiceEntry[] = []): ChoiceEntry[] {
  for (const node of nodes ?? []) {
    if (isNoiseNode(node)) continue;

    if (node.type === 'IfStatement') {
      const choice = extractChoiceLabel(node.condition);
      if (choice) {
        const summary = { npcLines: [], adds: [], removes: [], sets: [], writes: [], exits: [] };
        collectBodySummary(node.then, summary);
        entries.push({ option: choice, condition: formatCondition(node.condition), ...summary });
      }

      collectChoiceIndex(node.then, entries);
      for (const elif of node.else_ifs ?? []) {
        const elifChoice = extractChoiceLabel(elif.condition);
        if (elifChoice) {
          const summary = { npcLines: [], adds: [], removes: [], sets: [], writes: [], exits: [] };
          collectBodySummary(elif.body, summary);
          entries.push({ option: elifChoice, condition: formatCondition(elif.condition), ...summary });
        }
        collectChoiceIndex(elif.body, entries);
      }
      collectChoiceIndex(node.else, entries);
      continue;
    }

    collectChoiceIndex(node.body, entries);
  }
  return entries;
}

function collectStateModel(npc: NPCFile, dialogueFunctions: DialogueFunction[]): StateModel {
  const persistentGlobals = new Set<string>([...(npc.flags?.read ?? []), ...(npc.flags?.write ?? [])]);
  const localCounters = new Set<string>();
  const multiValueFlags = new Set<string>();
  const npcMetFlags = new Set<string>();
  const mapRefs = new Set<string>();
  const compareValues = new Map<string, Set<string>>();

  const npcMetCandidate = `${npc.npc.toLowerCase()}Met`;

  for (const flag of persistentGlobals) {
    if (flag.toLowerCase() === npcMetCandidate.toLowerCase() || flag.toLowerCase().endsWith('met')) {
      npcMetFlags.add(flag);
    }
  }

  for (const fn of dialogueFunctions) {
    walkAllNodes(fn.nodes, node => {
      const mapRef = mapReferenceFromCondition(node.condition);
      if (mapRef) mapRefs.add(mapRef);

      for (const flag of node.condition?.flags ?? []) {
        if (isLocalOrParam(flag.flag)) {
          localCounters.add(flag.flag);
        } else if (flag.values && flag.values.length > 0) {
          if (!compareValues.has(flag.flag)) compareValues.set(flag.flag, new Set());
          for (const value of flag.values) compareValues.get(flag.flag)?.add(value);
        }
      }

      if (node.type === 'SetFlag' && node.flag) {
        if (isLocalOrParam(node.flag)) localCounters.add(node.flag);
      }
      if ((node.type === 'SuspendAssign' || node.type === 'StringAssign') && node.var && isLocalOrParam(node.var)) {
        localCounters.add(node.var);
      }
      if (node.raw) {
        const inc = /\b([A-Za-z][A-Za-z0-9_]*)\s*=\s*0x[0-9A-Fa-f]+h\s*\+\s*\1\b/.exec(node.raw);
        if (inc) multiValueFlags.add(`${inc[1]} (incremented counter/state)`);
      }
    });
  }

  for (const [flag, values] of compareValues) {
    if (values.size > 1 || Array.from(values).some(v => !['0x00', '0x01', '0x00h', '0x01h', '0', '1'].includes(v))) {
      multiValueFlags.add(`${flag} (${Array.from(values).sort().join(', ')})`);
    }
  }

  const ambientBarkFunctions = Object.values(npc.functions)
    .filter(fn => fn.type === 'monologue' || fn.type === 'look' || fn.type === 'behavior')
    .map(fn => `${fn.name} (${fn.type})`);

  return {
    persistentGlobals: uniqueSorted(persistentGlobals),
    npcMetFlags: uniqueSorted(npcMetFlags),
    multiValueFlags: uniqueSorted(multiValueFlags),
    localCounters: uniqueSorted(localCounters),
    mapRefs: uniqueSorted(mapRefs),
    ambientBarkFunctions: uniqueSorted(ambientBarkFunctions),
  };
}

function collectAmbientBarks(npc: NPCFile): AmbientBarkEntry[] {
  const entries: AmbientBarkEntry[] = [];
  const barkFunctions = Object.values(npc.functions).filter(
    fn => fn.type === 'monologue' || fn.type === 'look' || fn.type === 'behavior',
  );

  const walk = (fn: DialogueFunction, nodes: DialogueNode[] | undefined, condition: string): void => {
    for (const node of nodes ?? []) {
      if (isNoiseNode(node)) continue;
      const nextCondition = joinCondition(condition, node.condition);

      if ((node.type === 'Bark' || node.type === 'DialogueLine') && node.text) {
        entries.push({
          functionName: fn.name,
          functionType: fn.type,
          text: node.text,
          condition: nextCondition,
        });
      }

      if (node.type === 'IfStatement') {
        walk(fn, node.then, nextCondition);
        for (const elif of node.else_ifs ?? []) {
          walk(fn, elif.body, joinCondition(condition, elif.condition));
        }
        if (node.else && node.else.length > 0) {
          walk(fn, node.else, `${condition} AND fallback`);
        }
      } else {
        walk(fn, node.then, nextCondition);
        for (const elif of node.else_ifs ?? []) {
          walk(fn, elif.body, joinCondition(condition, elif.condition));
        }
        walk(fn, node.else, nextCondition);
      }

      walk(fn, node.body, nextCondition);
    }
  };

  for (const fn of barkFunctions) {
    walk(fn, fn.nodes, 'true');
  }

  return entries;
}

function renderCompactList(values: string[], fallback = '_none found_'): string {
  return values.length > 0 ? values.map(v => `\`${escapeMd(v)}\``).join(', ') : fallback;
}

function renderConversionGuide(ctx: WalkContext, dialogueFunctions: DialogueFunction[]): void {
  const state = collectStateModel(ctx.npc, dialogueFunctions);
  const initialOptions = dialogueFunctions.flatMap(fn => collectInitialOptions(fn.nodes).map(entry => ({
    ...entry,
    functionName: fn.name,
  })));
  const choiceEntries = dialogueFunctions.flatMap(fn => collectChoiceIndex(fn.nodes).map(entry => ({
    ...entry,
    functionName: fn.name,
  })));

  ctx.lines.push('## U7 Conversion Guide');
  ctx.lines.push('');
  ctx.lines.push('### State Model');
  ctx.lines.push('');
  ctx.lines.push(`- Persistent globals: ${renderCompactList(state.persistentGlobals)}`);
  ctx.lines.push(`- NPC MET candidates: ${renderCompactList(state.npcMetFlags, '_none detected_')} - consider mapping these to Exult's NPC \`MET\` flag when appropriate.`);
  ctx.lines.push(`- Multi-value flags/counters: ${renderCompactList(state.multiValueFlags, '_none detected_')}`);
  ctx.lines.push(`- Local menu/counter variables: ${renderCompactList(state.localCounters, '_none detected_')}`);
  if (state.mapRefs.length > 0) {
    ctx.lines.push(`- Map references for manual schedule/location handling: ${state.mapRefs.map(v => escapeMd(v)).join('; ')}`);
  }
  ctx.lines.push(`- Ambient/look bark functions: ${renderCompactList(state.ambientBarkFunctions, '_none detected_')} - these are not interactive dialogue lines.`);
  ctx.lines.push('');
  ctx.lines.push('### Speech Classification');
  ctx.lines.push('');
  ctx.lines.push('- `dialogue` and `shop` functions are treated as interactive conversation speech.');
  ctx.lines.push('- `monologue`, `look`, and `behavior` functions are treated as ambient or single-click bark sources and are kept out of this dialogue walk.');
  ctx.lines.push('');

  const ambientBarks = collectAmbientBarks(ctx.npc);
  ctx.lines.push('### Ambient/Look Bark Index');
  ctx.lines.push('');
  if (ambientBarks.length === 0) {
    ctx.lines.push('_No ambient, look, or behavior bark text found._');
  } else {
    ctx.lines.push('| Function | Type | Condition | Bark text |');
    ctx.lines.push('|---|---|---|---|');
    for (const entry of ambientBarks) {
      ctx.lines.push(`| \`${entry.functionName}\` | \`${entry.functionType}\` | \`${escapeMd(entry.condition)}\` | ${quoteMd(entry.text)} |`);
    }
    ctx.lines.push('');
    ctx.lines.push('_Use `monologue`/`behavior` bark text as U7 proximity or ambient bark candidates; use `look` bark text as single-click/look description candidates._');
  }
  ctx.lines.push('');

  ctx.lines.push('### Initial Option Table');
  ctx.lines.push('');
  if (initialOptions.length === 0) {
    ctx.lines.push('_No initial menu options found before the first conversation loop._');
  } else {
    ctx.lines.push('| Function | Option | Condition | Source menu | U7 suggested label |');
    ctx.lines.push('|---|---|---|---|---|');
    for (const entry of initialOptions) {
      ctx.lines.push(`| \`${entry.functionName}\` | ${quoteMd(entry.option)} | \`${escapeMd(entry.condition)}\` | \`${entry.sourceMenu}\` (${entry.action}) | \`${escapeMd(normalizeSuggestedLabel(entry.option))}\` |`);
    }
  }
  ctx.lines.push('');

  ctx.lines.push('### Choice Index');
  ctx.lines.push('');
  if (choiceEntries.length === 0) {
    ctx.lines.push('_No strcmp choice branches found._');
  } else {
    for (const entry of choiceEntries) {
      ctx.lines.push(`- \`${escapeMd(normalizeSuggestedLabel(entry.option))}\` from ${quoteMd(entry.option)} in \`${entry.functionName}\``);
      ctx.lines.push(`  - Condition: \`${escapeMd(entry.condition)}\``);
      ctx.lines.push(`  - NPC text: ${entry.npcLines.length > 0 ? entry.npcLines.map(quoteMd).join(' / ') : '_none_'}`);
      ctx.lines.push(`  - Adds: ${renderMenuOptions(uniqueSorted(entry.adds))}`);
      ctx.lines.push(`  - Removes: ${renderMenuOptions(uniqueSorted(entry.removes))}`);
      ctx.lines.push(`  - Replaces menu with: ${renderMenuOptions(uniqueSorted(entry.sets))}`);
      ctx.lines.push(`  - Writes: ${renderCompactList(uniqueSorted(entry.writes))}`);
      ctx.lines.push(`  - Exits: ${entry.exits.length > 0 ? entry.exits.map(v => `\`${v}\``).join(', ') : '_none_'}`);
    }
  }
  ctx.lines.push('');
}

function renderFunctionHeader(ctx: WalkContext, npcName: string, fn: DialogueFunction, level: number): void {
  push(ctx, level, `### Function \`${npcName}::${fn.name}\``);
  push(ctx, level, '');
  push(ctx, level, `- Type: \`${fn.type}\``);
  push(ctx, level, `- Process: ${fn.isProcess ? '`yes`' : '`no`'} (${fn.processType || 'function'})`);
  push(ctx, level, `- Reads: ${formatList(fn.flagsRead)}`);
  push(ctx, level, `- Writes: ${formatList(fn.flagsWrite)}`);
  push(ctx, level, '');
}

function renderNodes(ctx: WalkContext, nodes: DialogueNode[], state: MenuState, level: number, currentNpc: string): void {
  for (const node of nodes) {
    if (isNoiseNode(node)) continue;

    const suffix = conditionSuffix(node.condition);

    switch (node.type) {
      case 'Bark':
      case 'DialogueLine':
        push(ctx, level, `- NPC: ${quoteMd(node.text ?? '')} \`${node.id}\`${suffix}`);
        break;

      case 'BeginConversation':
        push(ctx, level, `- Begin conversation \`${node.id}\`${suffix}`);
        break;

      case 'EndConversation':
        push(ctx, level, `- End conversation \`${node.id}\`${suffix}`);
        break;

      case 'MenuSet': {
        const key = menuKey(node);
        setMenuOptions(state, key, node.options ?? []);
        push(ctx, level, `- Menu \`${key}\` = ${renderMenuOptions(node.options ?? [])} \`${node.id}\`${suffix}`);
        break;
      }

      case 'MenuAdd':
      case 'MenuUnion': {
        const key = menuKey(node);
        addMenuOptions(state, key, node.options ?? []);
        push(ctx, level, `- Menu \`${key}\` adds ${renderMenuOptions(node.options ?? [])} \`${node.id}\`${suffix}`);
        break;
      }

      case 'MenuRemove': {
        const key = menuKey(node);
        removeMenuOptions(state, key, node.options ?? []);
        push(ctx, level, `- Menu \`${key}\` removes ${renderMenuOptions(node.options ?? [])} \`${node.id}\`${suffix}`);
        break;
      }

      case 'Ask': {
        const key = menuKey(node);
        push(ctx, level, `- Ask from menu \`${key}\`: ${renderMenuOptions(state.menus.get(key) ?? [])} \`${node.id}\`${suffix}`);
        break;
      }

      case 'SuspendAssign':
        push(ctx, level, `- Capture player choice into \`${node.var ?? 'suspend'}\` \`${node.id}\`${suffix}`);
        break;

      case 'StringAssign':
        push(ctx, level, `- Assign \`${node.var ?? 'local'}\` = ${quoteMd(node.value ?? '')} \`${node.id}\`${suffix}`);
        break;

      case 'SetFlag': {
        const flag = node.flag ?? 'UNKNOWN_FLAG';
        const scope = isLocalOrParam(flag) ? 'local' : 'global';
        push(ctx, level, `- Set ${scope} flag \`${flag}\` = \`${node.value ?? '1'}\` \`${node.id}\`${suffix}`);
        break;
      }

      case 'Call': {
        const target = node.target ?? 'UNKNOWN';
        if (shouldSkipLowLevelCall(target)) break;
        push(ctx, level, `- Call \`${target}\` \`${node.id}\`${suffix}`);
        if (node.text) push(ctx, level + 1, `- Intrinsic text: ${quoteMd(node.text)}`);
        const resolved = resolveCallTarget(ctx, currentNpc, target);
        if (!resolved) {
          if (!target.startsWith('Item::') && !target.startsWith('FREE::')) {
            push(ctx, level + 1, '- Target not available in loaded AST.');
          }
          break;
        }

        const callKey = `${resolved.npcName}::${resolved.functionName}`;
        if (ctx.callPath.includes(callKey)) {
          push(ctx, level + 1, `- Recursion guard: \`${callKey}\` already appears in this path.`);
          break;
        }
        if (ctx.callPath.length >= MAX_CALL_DEPTH) {
          push(ctx, level + 1, `- Call depth guard: skipped \`${callKey}\`.`);
          break;
        }

        push(ctx, level + 1, `- Followed call \`${callKey}\`:`);
        ctx.callPath.push(callKey);
        renderNodes(ctx, resolved.nodes, cloneMenuState(state), level + 2, resolved.npcName);
        ctx.callPath.pop();
        break;
      }

      case 'IfStatement': {
        const choice = extractChoiceLabel(node.condition);
        if (choice) {
          push(ctx, level, `- Choice branch ${quoteMd(choice)} \`${node.id}\`${suffix}`);
        } else {
          push(ctx, level, `- If \`${formatCondition(node.condition)}\` \`${node.id}\`${suffix}`);
        }
        renderNodes(ctx, node.then ?? [], cloneMenuState(state), level + 1, currentNpc);

        for (const elif of node.else_ifs ?? []) {
          const elifChoice = extractChoiceLabel(elif.condition);
          if (elifChoice) {
            push(ctx, level, `- Else-if choice ${quoteMd(elifChoice)}${conditionSuffix(elif.condition)}`);
          } else {
            push(ctx, level, `- Else-if \`${formatCondition(elif.condition)}\`${conditionSuffix(elif.condition)}`);
          }
          renderNodes(ctx, elif.body ?? [], cloneMenuState(state), level + 1, currentNpc);
        }

        if (node.else && node.else.length > 0) {
          push(ctx, level, '- Else / fallback:');
          renderNodes(ctx, node.else, cloneMenuState(state), level + 1, currentNpc);
        }
        break;
      }

      case 'ConversationLoop':
        push(
          ctx,
          level,
          `- Conversation loop \`${node.id}\` using \`${node.flag ?? 'choice'}\`; exit: \`${node.exitCondition ?? 'none'}\`${suffix}`,
        );
        push(ctx, level + 1, '- Non-flat control flow: the body can repeat after each explored choice.');
        renderNodes(ctx, node.body ?? [], cloneMenuState(state), level + 1, currentNpc);
        break;

      case 'Jump':
      case 'Unknown':
      default:
        push(ctx, level, `- ${node.type} \`${node.id}\`${node.raw ? `: \`${escapeMd(node.raw)}\`` : ''}${suffix}`);
        break;
    }
  }
}

function sortDialogueFunctions(functions: DialogueFunction[]): DialogueFunction[] {
  const score = (fn: DialogueFunction): number => {
    if (fn.name === 'talk') return 0;
    if (fn.name === 'use') return 1;
    if (fn.type === 'dialogue') return 2;
    return 3;
  };
  return [...functions].sort((a, b) => {
    const sa = score(a);
    const sb = score(b);
    if (sa !== sb) return sa - sb;
    return a.name.localeCompare(b.name);
  });
}

export function generateDialogueWalkMarkdown(npc: NPCFile, npcIndex: Record<string, NPCFile> = { [npc.npc]: npc }): string {
  const ctx: WalkContext = {
    npc,
    npcIndex,
    lines: [],
    callPath: [],
  };

  ctx.lines.push(`# ${npc.npc} Dialogue Walk`);
  ctx.lines.push('');
  ctx.lines.push(`Source: \`${npc.sourceFile}\``);
  ctx.lines.push('');
  ctx.lines.push('> This is a best-effort static dialogue walk. Ultima VIII usecode is not a flat tree: menus can be rebuilt, calls can jump into helper functions, loops can repeat, and raw/runtime conditions can hide branches. This export preserves all visible branches and marks non-flat control flow rather than forcing it into a false tree.');
  ctx.lines.push('');
  ctx.lines.push('## Summary');
  ctx.lines.push('');
  ctx.lines.push(`- Dialogue lines: ${npc.stats.dialogueLineCount}`);
  ctx.lines.push(`- Ask nodes: ${npc.stats.askCount}`);
  ctx.lines.push(`- Strcmp branches: ${npc.stats.strcmpBranches}`);
  ctx.lines.push(`- Global reads: ${formatList(npc.flags?.read)}`);
  ctx.lines.push(`- Global writes: ${formatList(npc.flags?.write)}`);
  ctx.lines.push('');

  if (npc.calledFrom && npc.calledFrom.length > 0) {
    ctx.lines.push('## Scene Callers');
    ctx.lines.push('');
    for (const ref of npc.calledFrom) {
      ctx.lines.push(`- \`${ref.callerClass}::${ref.callerFunc}\` -> \`${ref.targetFunc}\``);
    }
    ctx.lines.push('');
  }

  const dialogueFunctions = sortDialogueFunctions(Object.values(npc.functions).filter(fn => fn.type === 'dialogue'));
  if (dialogueFunctions.length === 0) {
    ctx.lines.push('## Dialogue');
    ctx.lines.push('');
    ctx.lines.push('_No dialogue functions found._');
    return ctx.lines.join('\n');
  }

  renderConversionGuide(ctx, dialogueFunctions);

  ctx.lines.push('## Dialogue');
  ctx.lines.push('');
  for (const fn of dialogueFunctions) {
    const callKey = `${npc.npc}::${fn.name}`;
    ctx.callPath = [callKey];
    renderFunctionHeader(ctx, npc.npc, fn, 0);
    renderNodes(ctx, fn.nodes ?? [], { menus: new Map() }, 0, npc.npc);
    ctx.lines.push('');
  }

  return ctx.lines.join('\n').replace(/\n{3,}/g, '\n\n');
}

export function downloadDialogueWalkMarkdown(npc: NPCFile, npcIndex: Record<string, NPCFile>): void {
  const content = generateDialogueWalkMarkdown(npc, npcIndex);
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${sanitizeFilename(npc.npc)}_dialogue_walk.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
