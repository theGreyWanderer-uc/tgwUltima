
import type { DialogueNode, NPCFile, DialogueMessage, NodeCondition, FlagCondition } from './types';
import { dbg } from './debug';

const MAX_STEP_ITERATIONS = 5000;
const MAX_RECURSION_DEPTH = 20;
const LOOP_SAFETY_LIMIT = 10;

export interface BlockState {
  nodes: DialogueNode[];
  pc: number;
  loopId?: string;
  exitCondition?: string;
  exitWhenMatched?: boolean;
  menuVar?: string;
  handlerModifiedMenu?: boolean;
}

export interface CallFrame {
  npcName: string;
  functionName: string;
  blocks: BlockState[];
  env: Record<string, string | number>;
}

export interface EngineState {
  flags: Record<string, number>;
  history: DialogueMessage[];
  menuOptions: string[];
  menuVars: Record<string, string[]>;
  activeMenuVar: string | null;
  callStack: CallFrame[];
  lastChoice: string;
  paused: boolean;
  ended: boolean;
  conditionPolicy: 'permissive' | 'strict';
  unresolvedConditionCount: number;
  unresolvedConditionNodes: Record<string, true>;
  callVisitCounts: Record<string, number>;
  // Flags seeded via DEFAULT_FLAGS — re-applied when BeginConversation fires so any
  // flag the shipped engine would have suppressed via the BC process-kill is always
  // overridden even if a sub-function was entered before BC (e.g. Mythran).
  defaultFlags: Record<string, number>;
}

export function cloneEngineState(state: EngineState): EngineState {
  return {
    ...state,
    flags: { ...state.flags },
    defaultFlags: { ...state.defaultFlags },
    history: state.history.map(msg => ({ ...msg })),
    menuOptions: [...state.menuOptions],
    menuVars: Object.fromEntries(
      Object.entries(state.menuVars).map(([k, v]) => [k, [...v]])
    ),
    callStack: state.callStack.map(frame => ({
      ...frame,
      env: { ...frame.env },
      blocks: frame.blocks.map(block => ({ ...block }))
    })),
    unresolvedConditionNodes: { ...state.unresolvedConditionNodes },
    callVisitCounts: { ...state.callVisitCounts },
  };
}

function newState(flags: Record<string, number>, conditionPolicy: 'permissive' | 'strict'): EngineState {
  return {
    flags: { ...flags },
    defaultFlags: { ...flags },
    history: [],
    menuOptions: [],
    menuVars: {},
    activeMenuVar: null,
    callStack: [],
    lastChoice: '',
    paused: false,
    ended: false,
    conditionPolicy,
    unresolvedConditionCount: 0,
    unresolvedConditionNodes: {},
    callVisitCounts: {},
  };
}

function resolveText(text: string, npcName: string, env?: Record<string, string | number>): string {
  let res = text.replaceAll('{getName}', 'Avatar').replaceAll('{npcName}', npcName);
  if (env) {
    for (const [k, v] of Object.entries(env)) {
      res = res.replaceAll(`{${k}}`, String(v));
    }
  }
  return res;
}

function currentFrame(state: EngineState): CallFrame | undefined {
  return state.callStack.at(-1);
}

function parseRawNumber(token: string): number | null {
  const t = token.trim();
  if (/^0x[0-9a-f]+h?$/i.test(t)) {
    const hex = t.toLowerCase().endsWith('h') ? t.slice(2, -1) : t.slice(2);
    return Number.parseInt(hex, 16);
  }
  if (/^[0-9a-f]+h$/i.test(t)) return Number.parseInt(t.slice(0, -1), 16);
  if (/^-?\d+$/.test(t)) return Number.parseInt(t, 10);
  return null;
}

type TriState = 'true' | 'false' | 'unknown';

function evalCondition(
  cond: NodeCondition | undefined,
  flags: Record<string, number>,
  lastChoice: string,
  deadMode: 'alive' | 'dead' = 'alive',
  policy: 'permissive' | 'strict',
  history?: DialogueMessage[],
  env?: Record<string, string | number>,
  menuVars?: Record<string, string[]>
): boolean {
  if (!cond) {
    dbg.log('evalCondition', 'no condition → true');
    return true;
  }

  dbg.log('evalCondition', '─── raw:', JSON.stringify(cond.raw), '| deadMode:', deadMode, '| lastChoice:', JSON.stringify(lastChoice));
  dbg.log('evalCondition', '    flags snapshot:', JSON.stringify(flags));
  dbg.log('evalCondition', '    env snapshot:', JSON.stringify(env ?? {}));
  dbg.log('evalCondition', '    cond.flags:', JSON.stringify(cond.flags ?? []));
  dbg.log('evalCondition', '    cond.isDead:', cond.isDead, '| isDeadNegated:', cond.isDeadNegated);
  dbg.log('evalCondition', '    cond.strcmp:', JSON.stringify(cond.strcmp ?? []));

  // Handle FREE::getListLength(localN) OP VALUE comparisons using actual menu data.
  if (cond.raw && /FREE::getListLength/i.test(cond.raw)) {
    const m = cond.raw.match(/^(not\s+)?FREE::getListLength\((\w+)\)\s*(<=|>=|<|>|==|!=)\s*(0x[0-9a-fA-F]+h?|\d+)/i);
    if (m) {
      const negate = !!m[1];
      const varName = m[2];
      const op = m[3];
      const rawVal = m[4];
      const threshold = rawVal.startsWith('0x') ? parseInt(rawVal.replace(/h$/i,''), 16) : parseInt(rawVal, 10);
      const list = menuVars?.[varName] ?? [];
      const len = list.length;
      let result: boolean;
      if (op === '<=') result = len <= threshold;
      else if (op === '>=') result = len >= threshold;
      else if (op === '<')  result = len <  threshold;
      else if (op === '>')  result = len >  threshold;
      else if (op === '==') result = len === threshold;
      else                  result = len !== threshold;
      const final = negate ? !result : result;
      dbg.log('evalCondition', '  → getListLength: var', varName, 'list:', list, 'len', len, op, threshold, '→', result, 'negate:', negate, 'FINAL:', final);
      return final;
    }
  }

  if (cond.isDead) {
    // In U8 usecode, isDead() returns NONZERO when the NPC is ALIVE (it's a heartbeat/alive flag).
    // Therefore: not isDead() = true when DEAD (isDead()=0), false when alive.
    // Confirmed by bark text: if(not isDead()) { "the late daemon"/"deceased"/"dead daemon" } else { alive text }
    // isDeadNegated=true: fold emitted 'not isDead()' (NOT opcode before jne) → fires when ALIVE.
    // isDeadNegated=false: fold emitted 'isDead()' (no NOT opcode) → fires when DEAD.
    const result = cond.isDeadNegated ? deadMode === 'alive' : deadMode === 'dead';
    dbg.log('evalCondition', '  → isDead check: isDeadNegated=', cond.isDeadNegated, 'deadMode=', deadMode, 'RESULT:', result);
    return result;
  }

  // Detect double-negation prefix: "not not X" — the disassembler folds one `not` into the
  // flags/strcmp encoding, leaving the second uncancelled.  When raw starts with "not not",
  // the intended semantics is the positive (double-negation cancels), so we flip the result.
  const doubleNegated = /^not\s+not\s+/i.test((cond.raw ?? '').trimStart());
  if (doubleNegated) dbg.log('evalCondition', '  → double-negation detected');

  if (cond.strcmp) {
    const match = cond.strcmp.some(sc => {
      const lc = lastChoice.trim();
      const envVal = env?.[sc.var];
      return (
        // direct lastChoice match (ConversationLoop: lastChoice still set at strcmp time)
        sc.value.trim() === lc
        // env var matches lastChoice (equivalent to above when envVal == lastChoice)
        || (envVal !== undefined && String(envVal).trim() === lc)
        // env var matches the hardcoded option text directly — works even after lastChoice
        // has been consumed (reset to '') by a preceding SuspendAssign (RF-02 fix)
        || (envVal !== undefined && String(envVal).trim() === sc.value.trim())
      );
    });
    if (cond.strcmp.length > 0) {
      // Count leading NOT prefixes — same parity rule as the raw strcmp handler:
      //   0 NOTs (bare X strcmp Y):      body fires when X == Y  → return match
      //   1 NOT  (not X strcmp Y):       body fires when X != Y  → return !match
      //   2 NOTs (not not X strcmp Y):   body fires when X == Y  → return match
      // In U8 bytecode: strcmp; NOT; jne = jump (skip body) when NOT(strcmp)=1 = when EQUAL
      // → body executes when NOT EQUAL.  bare strcmp; jne = jump when nonzero = when NOT EQUAL
      // → body executes when EQUAL.
      let rawForCount = (cond.raw ?? '').trimStart();
      let notCount = 0;
      while (/^not\s+/i.test(rawForCount)) { rawForCount = rawForCount.replace(/^not\s+/i, ''); notCount++; }
      const strcmpResult = (notCount % 2 === 0) ? match : !match;
      dbg.log('evalCondition', '  → strcmp (structured): lastChoice=', JSON.stringify(lastChoice),
        'match=', match, 'notCount=', notCount, 'RESULT:', strcmpResult);
      return strcmpResult;
    }
  }

  if (cond.raw && cond.raw.includes(' strcmp ')) {
    // Strip leading "not " / "not not " prefix before splitting — "not X strcmp Y"
    // means X == Y (strcmp returns 0 on match, not inverts → truthy).
    let rawStr = cond.raw.trimStart();
    let notCountRaw = 0;
    while (/^not\s+/i.test(rawStr)) {
      rawStr = rawStr.replace(/^not\s+/i, '');
      notCountRaw++;
    }
    const parts = rawStr.split(' strcmp ');
    if (parts.length === 2) {
      let left = parts[0].trim();
      let right = parts[1].trim();

      let leftVal = env?.[left] !== undefined ? String(env[left]) : left;
      let rightVal = env?.[right] !== undefined ? String(env[right]) : right;

      if (leftVal.startsWith('"') && leftVal.endsWith('"')) leftVal = leftVal.slice(1, -1);
      if (rightVal.startsWith('"') && rightVal.endsWith('"')) rightVal = rightVal.slice(1, -1);

      if (leftVal === '(word)suspend' || leftVal === 'suspend') leftVal = lastChoice;
      if (rightVal === '(word)suspend' || rightVal === 'suspend') rightVal = lastChoice;

      const eq = leftVal.trim() === rightVal.trim();
      // Pattern 1: bare strcmp (strcmp→jne, notCount=0) → body fires when EQUAL.
      // Pattern 2: not strcmp (strcmp→NOT→jne, notCount=1) → body fires when NOT EQUAL.
      const result = (notCountRaw % 2 === 0) ? eq : !eq;
      dbg.log('evalCondition', '  → strcmp (raw): notCount=', notCountRaw, 'left=', JSON.stringify(leftVal),
        'right=', JSON.stringify(rightVal), 'eq=', eq, 'RESULT:', result);
      return result;
    }
  }

  const evalFlags = (): TriState => {
    if (!cond.flags || cond.flags.length === 0) {
      dbg.log('evalCondition', '  → evalFlags: no flags array → unknown');
      return 'unknown';
    }
    
    // combinator is set by the extractor from fold's 'and'/'or' operator — no regex needed
    const combinator = cond.combinator === 'or' ? 'some' : 'every';
    dbg.log('evalCondition', '  → evalFlags: combinator=', combinator, 'flags to check:', cond.flags.map(f => f.flag));

    const pass = cond.flags[combinator](fc => {
      const val = flags[fc.flag] ?? 0;
      const inFlags = fc.flag in flags;
      let p = false;
      if (fc.op && fc.values && fc.values.length > 0) {
        const targetVals = fc.values.map(parseRawNumber).filter((n): n is number => n !== null);
        if (targetVals.length > 0) {
          let matched = targetVals.includes(val);
          if (fc.op === '!=') matched = !matched;
          p = fc.negated ? !matched : matched;
        } else {
          p = fc.negated ? val === 0 : val !== 0;
        }
      } else {
        p = fc.negated ? val === 0 : val !== 0;
      }
      dbg.log('evalCondition', `    flag [${fc.flag}]: inFlags=${inFlags} rawVal=${val} negated=${fc.negated} op=${fc.op ?? 'none'} values=${JSON.stringify(fc.values ?? [])} → ${p}`);
      if (history) {
        history.push({ speaker: 'system', text: `⚑ Checked global flag: ${fc.flag} (currently ${val}) -> evaluated to ${p}` });
      }
      return p;
    });

    dbg.log('evalCondition', '  → evalFlags pass=', pass);
    return pass ? 'true' : 'false';
  };

  const flagsRes = evalFlags();
  dbg.log('evalCondition', '  flagsRes=', flagsRes, 'doubleNegated=', doubleNegated);
  // Apply double-negation flip: "not not X" is encoded with negated=true for
  // the inner not, and evalFlags() already applied that inversion.  The outer
  // "not" (doubleNegated) must flip the result a second time.
  if (flagsRes === 'false') { dbg.log('evalCondition', '  FINAL (flagsRes=false):', doubleNegated); return doubleNegated; }
  if (flagsRes === 'true'  && doubleNegated) { dbg.log('evalCondition', '  FINAL (flagsRes=true + doubleNeg): false'); return false; }

  if (cond.raw) {
    if (flagsRes === 'unknown') {
      // Numeric comparison: varName OP VALUE — evaluate using env if available.
      // Handles fold output like "local4 < 0x05h" or "param2 >= 3".
      const numCmp = cond.raw.match(/^(not\s+)?(\w+)\s*(<=?|>=?|[=!]=)\s*(0x[0-9a-fA-F]+h?|\d+)/i);
      if (numCmp) {
        const isNot = !!numCmp[1];
        const varName = numCmp[2];
        const op = numCmp[3];
        const rawRhs = numCmp[4];
        const threshold = rawRhs.startsWith('0x') ? parseInt(rawRhs.replace(/h$/i, ''), 16) : parseInt(rawRhs, 10);
        const envVal = env?.[varName];
        const flagVal = flags[varName];
        // local/param variables are initialized to 0 in U8 bytecode; treat unset as 0.
        const isLocalParam = /^(local|param)\d+$/i.test(varName);
        if (envVal !== undefined || flagVal !== undefined || isLocalParam) {
          const lhs = Number(envVal ?? flagVal ?? 0);
          let cmpResult: boolean;
          if      (op === '<')  cmpResult = lhs <  threshold;
          else if (op === '>')  cmpResult = lhs >  threshold;
          else if (op === '<=') cmpResult = lhs <= threshold;
          else if (op === '>=') cmpResult = lhs >= threshold;
          else if (op === '==') cmpResult = lhs === threshold;
          else                  cmpResult = lhs !== threshold;
          const result = isNot ? !cmpResult : cmpResult;
          dbg.log('evalCondition', '  → numeric cmp: varName=', varName, 'lhs=', lhs, op, threshold, 'cmpResult=', cmpResult, 'isNot=', isNot, 'RESULT:', result);
          return result;
        }
      }

      // Hex/decimal literal used as condition (e.g. 0xFFFFFFFFh = while-true loop marker).
      const litMatch = cond.raw.match(/^(not\s+)?(0x[0-9a-fA-F]+h?|\d+)$/i);
      if (litMatch) {
        const isNot = !!litMatch[1];
        const rawLit = litMatch[2];
        const litVal = rawLit.toLowerCase().startsWith('0x') ? parseInt(rawLit.replace(/h$/i, ''), 16) : parseInt(rawLit, 10);
        const result = isNot ? litVal === 0 : litVal !== 0;
        dbg.log('evalCondition', '  → numeric literal:', rawLit, '=', litVal, 'isNot=', isNot, 'RESULT:', result);
        return result;
      }

      const m = cond.raw.match(/^(not\s+)?([a-zA-Z0-9_]+)$/i);
      if (m) {
        const isNot = !!m[1];
        const varName = m[2];
        const val = Number(env?.[varName] ?? flags[varName] ?? 0);
        const result = isNot ? val === 0 : val !== 0;
        dbg.log('evalCondition', '  → simple var lookup: varName=', varName, 'val=', val, 'isNot=', isNot, 'RESULT:', result);
        return result;
      }
    }
    // Intrinsic call used as condition (e.g. Item::legal_create(...)): can't evaluate
    // in the web engine but almost always succeeds in the original game; treat as true.
    if (/\w+::\w+\s*\(/.test(cond.raw)) {
      dbg.log('evalCondition', '  → intrinsic call condition → true');
      return true;
    }
    if (/\b(byte|word|dword|local\d+|param\d+)\b/i.test(cond.raw)) {
      const result = policy === 'permissive';
      dbg.log('evalCondition', '  → raw has local/param, unresolved → policy fallback:', result, '(policy=', policy, ')');
      return result;
    }
  }

  dbg.log('evalCondition', '  → fallthrough return true (raw=', JSON.stringify(cond.raw), ')');
  return true;
}

export function findTalkFunction(npc: NPCFile | null): string | undefined {
  if (!npc) return undefined;

  // Standard entrypoints for U8 scripts
  if ('talk' in npc.functions) return 'talk';
  if ('use' in npc.functions) return 'use';

  for (const [k, v] of Object.entries(npc.functions)) {
    if (v.type === 'dialogue') return k;
  }
  return undefined;
}

export function findShopFunction(npc: NPCFile | null): string | undefined {
  if (!npc) return undefined;
  for (const [k, v] of Object.entries(npc.functions)) {
    if (v.type === 'shop') return k;
  }
  return undefined;
}

export function findLookFunction(npc: NPCFile | null): string | undefined {
  if (!npc) return undefined;
  for (const [k, v] of Object.entries(npc.functions)) {
    if (v.type === 'look') return k;
  }
  return undefined;
}

function getNodes(npcIndex: Record<string, NPCFile>, npcName: string, funcName: string): DialogueNode[] {
  return npcIndex[npcName]?.functions[funcName]?.nodes ?? [];
}

export function startConversation(
  npc: NPCFile,
  funcName: string,
  flags: Record<string, number>,
  policy: 'permissive' | 'strict',
  npcIndex: Record<string, NPCFile>
): EngineState {
  const s = newState(flags, policy);
  const nodes = getNodes(npcIndex, npc.npc, funcName);
  s.callStack.push({
    npcName: npc.npc,
    functionName: funcName,
    env: {},
    blocks: [{ nodes, pc: 0 }]
  });
  return step(s, npcIndex);
}

export function selectOption(state: EngineState, choice: string, _npc: NPCFile | null, npcIndex: Record<string, NPCFile>): EngineState {
  const s = cloneEngineState(state);
  s.lastChoice = choice;
  s.history.push({ speaker: 'player', text: choice });

  if (choice === 'bye' || choice === 'leave') {
    s.history.push({ speaker: 'system', text: '[Conversation ended]' });
    s.ended = true;
    s.paused = false;
    return s;
  }

  return step(s, npcIndex);
}


export interface LookDescription {
  text: string;
  active: boolean;
  flagNames: string[];
  requiresDead: boolean;
  condition?: string;
}

export function evaluateLook(npc: NPCFile, flags: Record<string, number>, config: { deadMode?: 'alive' | 'dead' }, npcIndex: Record<string, NPCFile>): LookDescription[] {
  const lookFunc = findLookFunction(npc);
  if (!lookFunc) return [];
  
  const deadMode = config.deadMode || 'alive';
  dbg.log('evalLook:walk', '══ evaluateLook START', npc.npc, '| deadMode:', deadMode);
  dbg.log('evalLook:walk', '  flags:', JSON.stringify(flags));

  const descriptions: LookDescription[] = [];
  const nodes = getNodes(npcIndex, npc.npc, lookFunc);

  function walk(nList: DialogueNode[], isPathActive: boolean, ancestorConds: NodeCondition[], depth = 0) {
    const indent = '  '.repeat(depth);
    // siblingPath tracks whether subsequent siblings in this list can be active.
    // When an isDead IfStatement fires, U8 exits the dead branch without evaluating
    // further sibling nodes, so we suppress them here.
    let siblingPath = isPathActive;
    for (const node of nList) {
      const allConds = [...ancestorConds];
      if (node.condition) allConds.push(node.condition);

      dbg.log('evalLook:walk', `${indent}[${node.id}] type=${node.type} isPathActive=${siblingPath} cond=${JSON.stringify(node.condition?.raw ?? null)}`);

      const passSelf = evalCondition(node.condition, flags, '', deadMode, 'permissive');
      const isNodeActive = siblingPath && passSelf;

      dbg.log('evalLook:walk', `${indent}  passSelf=${passSelf} isNodeActive=${isNodeActive}`);

      if (node.type === 'Bark' || node.type === 'DialogueLine') {
        const flagNames = allConds
          .flatMap(c => c.flags || [])
          .map(f => (f.negated ? `not ${f.flag}` : f.flag));

        const desc = {
          text: resolveText(node.text ?? '', npc.npc),
          active: isNodeActive,
          flagNames: Array.from(new Set(flagNames)),
          requiresDead: allConds.some(c => !!c.isDead),
          condition: allConds.map(c => c.raw).filter(Boolean).join(' AND ')
        };
        dbg.log('evalLook:result', `${indent}  BARK: "${desc.text}" active=${desc.active} flags=[${desc.flagNames}] requiresDead=${desc.requiresDead}`);
        descriptions.push(desc);
      }
      
      if (node.type === 'IfStatement') {
         dbg.log('evalLook:walk', `${indent}  → entering then (${(node.then ?? []).length} nodes), active=${isNodeActive}`);
         walk(node.then ?? [], isNodeActive, allConds, depth + 1);

         let anyMatched = passSelf;
         if (node.else_ifs) {
           for (let ei = 0; ei < node.else_ifs.length; ei++) {
             const elif = node.else_ifs[ei];
             const passElif = evalCondition(elif.condition, flags, '', deadMode, 'permissive');
             const elifActive = siblingPath && !anyMatched && passElif;
             const elifConds = [...ancestorConds];
             if (elif.condition) elifConds.push(elif.condition);
             dbg.log('evalLook:walk', `${indent}  → else_if[${ei}]: cond=${JSON.stringify(elif.condition?.raw)} passElif=${passElif} anyMatched=${anyMatched} elifActive=${elifActive}`);
             walk(elif.body ?? [], elifActive, elifConds, depth + 1);
             if (passElif) anyMatched = true;
           }
         }

         const elseActive = siblingPath && !anyMatched;
         dbg.log('evalLook:walk', `${indent}  → else: anyMatched=${anyMatched} elseActive=${elseActive} nodes=${(node.else ?? []).length}`);
         const elseConds = [...ancestorConds];
         walk(node.else ?? [], elseActive, elseConds, depth + 1);

         // If an isDead IfStatement fired, suppress subsequent siblings in this list.
         // U8 exits after the dead branch without evaluating further look nodes.
         if (isNodeActive && node.condition?.isDead !== undefined) {
           siblingPath = false;
         }
      }

      if (node.type === 'ConversationLoop') {
         walk(node.body ?? [], isNodeActive, allConds, depth + 1);
      }
    }
  }
  
  walk(nodes, true, []);
  dbg.log('evalLook:result', '══ evaluateLook END — total descriptions:', descriptions.length);
  descriptions.forEach((d, i) => dbg.log('evalLook:result', `  [${i}] active=${d.active} "${d.text}" flags=[${d.flagNames}] requiresDead=${d.requiresDead}`));
  return descriptions;
}

export function step(
state: EngineState, npcIndex: Record<string, NPCFile>): EngineState {
  const s = { ...state, paused: false };
  let limit = MAX_STEP_ITERATIONS;

  const menuKey = (nodeText?: string | null) => {
    const t = (nodeText ?? '').trim();
    if (!t) return s.activeMenuVar ?? '__menu';
    return t;
  };
  const loopRestartsThisStep = new WeakMap<BlockState, number>();

  while (limit-- > 0) {
    const frame = currentFrame(s);
    if (!frame) {
      if (!s.ended) s.history.push({ speaker: 'system', text: '[Conversation ended]', nodeId: '__end' });
      s.ended = true;
      return s;
    }

    if (frame.blocks.length === 0) {
      dbg.log('step:block', `frame ${frame.npcName}::${frame.functionName} exhausted all blocks — popping`);
      s.callStack.pop();
      continue;
    }

    const block = frame.blocks[frame.blocks.length - 1];

    if (block.pc >= block.nodes.length) {
      // RF-16: SuspendAssign captures the player's choice into env[loopId] (e.g.
      // env["local2"]) and then resets lastChoice to ''.  The loop-exit check must
      // consult the captured env variable when lastChoice is empty, otherwise the
      // loop can never exit (the exit condition is compared against '').
      const capturedChoice = s.lastChoice || String(frame.env?.[block.loopId ?? ''] ?? '');
      dbg.log('step:block', `block exhausted: loopId=${block.loopId ?? 'none'} exitCond=${block.exitCondition ?? 'none'} lastChoice=${JSON.stringify(s.lastChoice)} capturedChoice=${JSON.stringify(capturedChoice)}`);
      if (block.loopId) {
        const matched = capturedChoice.trim() === (block.exitCondition ?? '').trim();
        const shouldExit = capturedChoice === 'bye' ||
          (block.exitWhenMatched !== false ? matched : !matched);
        if (shouldExit) {
           frame.blocks.pop();
        } else {
           // RF-17: safety limit — cap only consecutive loop restarts that happen
           // within one engine step.  A real Ask returns from step(), so normal
           // long conversations do not accumulate toward this runaway guard.
           const loopIterations = (loopRestartsThisStep.get(block) ?? 0) + 1;
           loopRestartsThisStep.set(block, loopIterations);
           if (loopIterations > LOOP_SAFETY_LIMIT) {
             dbg.warn('step:block', `Loop safety limit reached (${loopIterations} iterations) for loopId=${block.loopId} — force-exiting`);
             s.history.push({ speaker: 'system', text: `⚠ Loop exhausted (${loopIterations} iterations) — continuing` });
             frame.blocks.pop();
             continue;
           }
           // When a handler set up a new menu via MenuSet, skip the loop's
           // menu rebuild check (body[0]) on restart — the handler's menu
           // should be shown instead.  This replicates the bytecode jmp that
           // skips from the handler to the Ask, bypassing the rebuild.
           if (block.handlerModifiedMenu && block.nodes.length > 1 &&
               block.nodes[0].type === 'IfStatement' && block.nodes[0].condition?.raw?.includes('getListLength')) {
             block.pc = 1;
           } else {
             block.pc = 0;
           }
           block.handlerModifiedMenu = false;
           s.lastChoice = ''; 
        }
      } else {
        frame.blocks.pop();
      }
      continue;
    }

    const node = block.nodes[block.pc];

    let passCond = true;
    if (node.condition && node.type !== 'IfStatement' && node.type !== 'ConversationLoop') {
      // use() is only reachable for living NPCs — dead NPCs open the loot gump instead.
      // deadMode is therefore always 'alive' in the conversation engine.
      // Look descriptions with dead/alive branching are handled separately in evaluateLook().
      dbg.log('step:node', `[${node.id}] top-level guard: type=${node.type} cond=${JSON.stringify(node.condition?.raw)}`);
      passCond = evalCondition(node.condition, s.flags, s.lastChoice, 'alive', s.conditionPolicy, s.history, frame.env, s.menuVars);
    }
    if (!passCond) {
      dbg.log('step:node', `[${node.id}] SKIP (condition false) type=${node.type} cond=${JSON.stringify(node.condition?.raw)}`);
      block.pc++;
      continue;
    }
    dbg.log('step:node', `[${node.id}] EXEC type=${node.type} cond=${JSON.stringify(node.condition?.raw ?? null)}`);

    block.pc++;

    switch (node.type) {
      case 'Bark':
      case 'DialogueLine': {
        const text = resolveText(node.text ?? '', frame.npcName, frame.env);
        if (text) s.history.push({ speaker: 'npc', text, nodeId: node.id });
        break;
      }
      case 'Ask': {
        const k = menuKey(node.menu);
        s.activeMenuVar = k;
        s.menuOptions = s.menuVars[k] ?? [];
        dbg.log('step:suspend', `[${node.id}] Ask: menuKey=${k} options=[${s.menuOptions}] → PAUSED`);
        s.paused = true;
        return s;
      }
      case 'MenuSet': {
        const k = menuKey(node.target);
        s.menuVars[k] = (node.options ?? []).map(o => resolveText(o, frame.npcName, frame.env));
        s.activeMenuVar = k;
        dbg.log('step:menu', `[${node.id}] MenuSet: key=${k} options=[${s.menuVars[k]}]`);
        // Track when a strcmp handler sets a new menu within a ConversationLoop.
        // This happens when the MenuSet is NOT in the loop's first IfStatement (the rebuild).
        // We detect this by checking if the current block is NOT the loop body
        // (i.e., we're in a nested block pushed by an IfStatement handler).
        const loopBlock = frame.blocks.find(b => b.loopId);
        if (loopBlock && frame.blocks[frame.blocks.length - 1] !== loopBlock) {
          loopBlock.handlerModifiedMenu = true;
        }
        break;
      }
      case 'MenuAdd': {
        const k = menuKey(node.target);
        const curr = new Set(s.menuVars[k] ?? []);
        for (const o of node.options ?? []) curr.add(resolveText(o, frame.npcName, frame.env));
        s.menuVars[k] = Array.from(curr);
        s.activeMenuVar = k;
        dbg.log('step:menu', `[${node.id}] MenuAdd: key=${k} options=[${s.menuVars[k]}]`);
        break;
      }
      case 'MenuRemove': {
        const k = menuKey(node.target);
        if (s.menuVars[k]) {
          const removes = new Set((node.options ?? []).map(o => resolveText(o, frame.npcName, frame.env)));
          s.menuVars[k] = s.menuVars[k].filter(o => !removes.has(o));
        }
        s.activeMenuVar = k;
        dbg.log('step:menu', `[${node.id}] MenuRemove: key=${k} remaining=[${s.menuVars[k] ?? []}]`);
        break;
      }
      case 'MenuUnion': {
        const k = menuKey(node.target);
        const curr = new Set(s.menuVars[k] ?? []);
        for (const o of node.options ?? []) curr.add(resolveText(o, frame.npcName, frame.env));
        s.menuVars[k] = Array.from(curr);
        s.activeMenuVar = k;
        break;
      }
      case 'StringAssign': {
        let resolved = node.value ?? '';
        if (resolved.startsWith('"') && resolved.endsWith('"')) {
            resolved = resolved.substring(1, resolved.length - 1);
        }
        if (resolved.includes('+ getName() +')) {
            const parts = resolved.split('+ getName() +');
            resolved = parts.map(p => p.trim().replace(/^"|"$/g, '')).join('Avatar');
        } else {
            resolved = resolved.replace(/^"|"$/g, '');
        }

        if (node.var) {
            if (!frame.env) frame.env = {};
            frame.env[node.var] = resolved;
        }
        break;
      }
      case 'SuspendAssign': {
        dbg.log('step:suspend', `[${node.id}] SuspendAssign: var=${node.var} lastChoice=${JSON.stringify(s.lastChoice)}`);
        // Capture the player's menu choice into the local variable.
        if (node.var) {
          if (!frame.env) frame.env = {};
          frame.env[node.var] = s.lastChoice;
          dbg.log('step:suspend', `  captured env[${node.var}] = ${JSON.stringify(s.lastChoice)}`);
        }
        // If no choice made yet, pause to let the player pick.
        if (!s.lastChoice) {
          const menuVar = s.activeMenuVar ?? '__menu';
          const opts = s.menuVars[menuVar] ?? [];
          dbg.log('step:suspend', `  no lastChoice — menuVar=${menuVar} opts=[${opts}]`);
          if (opts.length > 0) {
            s.menuOptions = opts;
            s.paused = true;
            return s;
          }
          // RF-14: empty menu — in the original engine this permanently suspends.
          // Log a warning; fall through with '' so the viewer doesn't freeze.
          dbg.warn('step:suspend', `[${node.id}] SuspendAssign with EMPTY menu (menuVar=${menuVar}) — original engine would suspend indefinitely`);
          s.history.push({ speaker: 'system', text: `⚠ Ask with empty menu (${menuVar}) — skipped` });
        } else {
          // Choice was consumed — reset so the next SuspendAssign/question can pause
          // correctly instead of inheriting this answer (RF-02).
          // RF-19: also clear activeMenuVar so timing suspends (e.g. barkAndWait waits)
          // cannot re-use the stale menu and present the same options a second time.
          s.lastChoice = '';
          s.activeMenuVar = null;
        }
        break;
      }
      case 'Unknown': {
        // jmp_NOPRINT inside a nested block may be a far-forward jump (early function exit)
        // OR just a skip-else artifact from if/else decompilation (no-op in our AST).
        // Distinguish by comparing the jmp address to the function's terminal address
        // (the max jmp_NOPRINT address seen in the top-level block). If they match,
        // clear all blocks so the call frame is popped on the next loop iteration.
        if (node.raw && /\/\*jmp_NOPRINT\(/.test(node.raw) && frame.blocks.length > 1) {
          const mAddr = node.raw.match(/\/\*jmp_NOPRINT\((0x[0-9a-fA-F]+)\)\*\//);
          if (mAddr) {
            const jmpAddr = parseInt(mAddr[1], 16);
            const topNodes = frame.blocks[0].nodes;
            // Collect the set of all jmp_NOPRINT addresses used at the top-level block.
            // If the nested jmp targets one of those addresses it's jumping to a shared
            // exit point (e.g. func231E early-exit → end of func1F_2) → early function exit.
            const topJmpAddrs = new Set<number>();
            for (const tn of topNodes) {
              const tm = (tn.raw ?? '').match(/\/\*jmp_NOPRINT\((0x[0-9a-fA-F]+)\)\*\//);
              if (tm) topJmpAddrs.add(parseInt(tm[1], 16));
            }
            if (topJmpAddrs.has(jmpAddr)) {
              dbg.log('step:node', `[${node.id}] jmp_NOPRINT(${mAddr[1]}) matches top-level exit address — clearing blocks (early function exit)`);
              frame.blocks = [];
              continue;
            }
          }
          // Address not shared with top level — skip-else artifact, treat as no-op.
        }
        if (node.raw) {
          const mSuspend = node.raw.match(/^([a-zA-Z0-9_]+)\s*=\s*(?:\(word\)\s*)?suspend/);
          if (mSuspend) {
            if (!frame.env) frame.env = {};
            frame.env[mSuspend[1]] = s.lastChoice;
            // "localN = (word)suspend" is the U8 usecode mechanism for capturing a menu choice.
            // If the player already made a choice (lastChoice is set), capture it and reset
            // so the next question can pause correctly — do NOT pause again (RF-02).
            // Only pause when no choice has been made yet (standalone suspend without preceding Ask).
            if (!s.lastChoice) {
              const menuVar = s.activeMenuVar ?? '__menu';
              const opts = s.menuVars[menuVar] ?? [];
              if (opts.length > 0) {
                s.menuOptions = opts;
                s.paused = true;
                return s;
              }
              // RF-14: empty menu — timing pause (after spawn/bark, not a real ask).
              // Log to console for debugging but do NOT add to history (would clutter the UI).
              dbg.warn('step:suspend', `[${node.id}] Unknown suspend with EMPTY menu (menuVar=${menuVar}) — original engine would suspend indefinitely`);
            } else {
              // Choice consumed — reset for the next question (RF-02).
              // RF-19: clear activeMenuVar so subsequent timing suspends cannot
              // re-present the same menu (stale activeMenuVar bug).
              s.lastChoice = '';
              s.activeMenuVar = null;
            }
          }
          const mAssign = node.raw.match(/^([a-zA-Z0-9_]+)\s*=\s*([a-zA-Z0-9_]+)$/);
          if (mAssign && frame.env?.[mAssign[2]]) {
            if (!frame.env) frame.env = {};
            frame.env[mAssign[1]] = frame.env[mAssign[2]];
          }
          // "localN = FREE::moveToEndOfList("item", localM)" — remove item from list and re-add at end
          const mMoveEnd = node.raw.match(/^(\w+)\s*=\s*(?:\w+::)?moveToEndOfList\(\s*"([^"]+)"\s*,\s*(\w+)\s*\)/);
          if (mMoveEnd) {
            const [, dest, item, src] = mMoveEnd;
            const srcList = s.menuVars[src] ?? [];
            const filtered = srcList.filter(o => o.trim() !== item.trim());
            filtered.push(item.endsWith(' ') ? item : item + ' ');
            s.menuVars[dest] = filtered;
            s.activeMenuVar = dest;
          }
          // "localN = FREE::prependToList("item", localM)" — prepend item to front of list
          const mPrepend = node.raw.match(/^(\w+)\s*=\s*(?:\w+::)?prependToList\(\s*"([^"]+)"\s*,\s*(\w+)\s*\)/);
          if (mPrepend) {
            const [, dest, item, src] = mPrepend;
            const srcList = s.menuVars[src] ?? [];
            const newItem = item.endsWith(' ') ? item : item + ' ';
            s.menuVars[dest] = [newItem, ...srcList.filter(o => o.trim() !== item.trim())];
            s.activeMenuVar = dest;
          }
          const mRand0 = node.raw.match(/^([a-zA-Z0-9_]+)\s*=\s*(?:[a-zA-Z0-9_:]+)?randomInRange0\(\s*(0x[0-9a-fA-F]+h|\d+)\s*\)/);
          if (mRand0) {
             const targetVar = mRand0[1];
             const maxNum = mRand0[2].endsWith('h') ? parseInt(mRand0[2].replace('h', ''), 16) : parseInt(mRand0[2], 10);       
             const randParams = maxNum || 1;
             const rand = Math.floor(Math.random() * randParams);
             if(!frame.env) frame.env = {};
             frame.env[targetVar] = rand;
          }
        }
        break;
      }
      case 'IfStatement': {
        const passIf = evalCondition(node.condition, s.flags, s.lastChoice, 'alive', s.conditionPolicy, s.history, frame.env, s.menuVars);
        // RF-15: if(0xFFFFFFFFh) is fold's decompilation of the U8 loopscr/loopnext opcode
        // (inventory-scan loop). Any bare hex literal condition (0x1Bh, 0x20h, 0x1Fh, etc.)
        // serves the same role — iterating over an NPC's container items.  Since the web
        // engine can't iterate inventory, skip the loop body and fall through to else_if/else
        // so that post-loop menu-building code runs normally.
        const isInventoryLoopMarker = /^0x[0-9a-fA-F]+h?$/i.test(node.condition?.raw?.trim() ?? '');
        const effectivePassIf = isInventoryLoopMarker ? false : passIf;
        dbg.log('step:if', `[${node.id}] IfStatement: cond=${JSON.stringify(node.condition?.raw)} lastChoice=${JSON.stringify(s.lastChoice)} passIf=${passIf}${isInventoryLoopMarker ? ` → LOOP_MARKER effectivePassIf=${effectivePassIf}` : ''}`);
        // RF-10: track unresolvable conditions (fold couldn't reduce local/param refs to flags).
        // Exclude conditions already handled: strcmp (raw or structured), getListLength, isDead,
        // and bare local/param var references (handled by simple var lookup).
        // A numeric comparison like "local4 < 0x05h" is resolved when the variable
        // exists in env — do not count it as unresolved.
        const _numCmpResolved = (() => {
          const raw = node.condition?.raw;
          if (!raw) return false;
          const m = /^(not\s+)?(\w+)\s*(<=?|>=?|[=!]=)\s*(0x[0-9a-fA-F]+h?|\d+)/i.exec(raw);
          if (!m) return false;
          const varName = m[2];
          // Resolved if in env, OR if it's a local/param (always resolvable — defaults to 0).
          return (frame.env?.[varName] !== undefined) || /^(local|param)\d+$/i.test(varName);
        })();
        if (node.condition?.raw &&
            /\b(local\d+|param\d+)\b/i.test(node.condition.raw) &&
            node.condition.isDead === undefined &&
            !(node.condition.strcmp && node.condition.strcmp.length > 0) &&
            !/\bstrcmp\b/i.test(node.condition.raw) &&
            !/FREE::getListLength/i.test(node.condition.raw) &&
            !/^(not\s+)?(local\d+|param\d+)\s*$/i.test(node.condition.raw.trim()) &&
            !_numCmpResolved &&
            !/\w+::\w+\s*\(/.test(node.condition.raw)) {
          s.unresolvedConditionCount++;
          s.unresolvedConditionNodes[node.id] = true;
          dbg.warn('step:if', `[${node.id}] Unresolved condition (local/param) — policy=${s.conditionPolicy} result=${passIf} total=${s.unresolvedConditionCount}`);
        }
        if (effectivePassIf && node.then && node.then.length > 0) {
           frame.blocks.push({ nodes: node.then, pc: 0 });
        } else {
          let matchedElif = false;
          if (node.else_ifs) {
            for (const elif of node.else_ifs) {
                 if (evalCondition(elif.condition, s.flags, s.lastChoice, 'alive', s.conditionPolicy, s.history, frame.env, s.menuVars)) {
                 if (elif.body && elif.body.length > 0) {
                    frame.blocks.push({ nodes: elif.body, pc: 0 });
                 }
                 matchedElif = true;
                 break;
               }
            }
          }
          if (!matchedElif && node.else && node.else.length > 0) {
            frame.blocks.push({ nodes: node.else, pc: 0 });
          }
        }
        break;
      }
      case 'ConversationLoop': {
        // RF-07: evaluate the loop's guard condition (if present) before entering.
        // In the original engine a guarded loop is a JNE before the ASK; if it fails
        // the code jumps entirely past the conversation block.
        if (node.condition) {
          const passLoop = evalCondition(node.condition, s.flags, s.lastChoice, 'alive', s.conditionPolicy, s.history, frame.env, s.menuVars);
          dbg.log('step:loop', `[${node.id}] ConversationLoop guard: cond=${JSON.stringify(node.condition?.raw)} pass=${passLoop}`);
          if (!passLoop) break;
        }
        // RF-18: pre-entry exit-condition check.
        // The preceding SuspendAssign/Unknown-suspend already captured the player's choice
        // into env[loopId] and reset lastChoice to ''.  If that captured value already equals
        // the loop's exit condition (e.g. "Yes, Master.") there is nothing to loop over —
        // skip the entire block.  Without this guard, the engine always enters the loop body
        // and presents another Ask even when the player already gave the correct answer.
        if (node.exitCondition && node.exitWhenMatched !== false && node.flag) {
          const capturedVal = (s.lastChoice || String(frame.env?.[node.flag] ?? '')).trim();
          if (capturedVal === node.exitCondition.trim() || capturedVal === 'bye') {
            dbg.log('step:loop', `[${node.id}] ConversationLoop pre-entry skip: ${node.flag}="${capturedVal}" already matches exitCond="${node.exitCondition}"`);
            break;
          }
        }
        if (node.body && node.body.length > 0) {
           frame.blocks.push({ nodes: node.body, pc: 0, loopId: node.flag, menuVar: node.flag, exitCondition: node.exitCondition, exitWhenMatched: node.exitWhenMatched !== false });
        }
        break;
      }
      case 'SetFlag': {
        if (node.flag && node.value !== undefined) {
          const val = parseRawNumber(node.value) ?? 1;
          dbg.log('step:flag', `[${node.id}] SetFlag: ${node.flag} = ${val} (was ${s.flags[node.flag] ?? 0})`);
          s.flags[node.flag] = val;
          s.history.push({ speaker: 'system', text: `⚑ Set global flag: ${node.flag} = ${val}` });
        }
        break;
      }
      case 'Call': {
        const target = node.target ?? '';
        dbg.log('step:call', `[${node.id}] Call: target=${target}`);
        // RF-08: Item:: and FREE:: are VM intrinsics — not dispatchable to NPC AST.
        // Check these FIRST because target.includes('::') would also match them.
        if (target.startsWith('Item::') || target.startsWith('FREE::')) {
          if (node.text) {
            // Extractor captured a text payload (e.g. from Item::bark) — surface it.
            const barkText = resolveText(node.text, frame.npcName, frame.env);
            s.history.push({ speaker: 'npc', text: barkText, nodeId: node.id });
            dbg.log('step:call', `  → intrinsic bark rendered: "${barkText}"`);
          } else {
            dbg.warn('step:call', `[${node.id}] Intrinsic call not dispatchable (no text payload): ${target}`);
          }
          break;
        }
        let targetNpc = frame.npcName;
        let targetFunc = target;
        if (target.includes('::')) {
          const parts = target.split('::');
          // METHOD:: calls are virtual base-class dispatches. Try the current NPC first
          // (in case it has an override), then fall back to the METHOD class itself.
          if (parts[0] !== 'METHOD') targetNpc = parts[0];
          targetFunc = parts[1];
        }
        // RF-10: guard against recursive call loops that would exhaust the step() budget.
        const callKey = `${targetNpc}::${targetFunc}`;
        s.callVisitCounts[callKey] = (s.callVisitCounts[callKey] ?? 0) + 1;
        if (s.callVisitCounts[callKey] > MAX_RECURSION_DEPTH) {
          dbg.warn('step:call', `[${node.id}] RECURSION GUARD: ${callKey} visited ${s.callVisitCounts[callKey]}x — skipping`);
          console.warn(`[step] Recursion guard triggered for ${callKey}`);
          break;
        }
        let tNodes = getNodes(npcIndex, targetNpc, targetFunc);
        // RF-11: METHOD:: fallback — if the current NPC doesn't override the function,
        // resolve it from the METHOD base class (the only class that defines it).
        if (tNodes.length === 0 && target.startsWith('METHOD::')) {
          const baseNodes = getNodes(npcIndex, 'METHOD', targetFunc);
          if (baseNodes.length > 0) {
            targetNpc = 'METHOD';
            tNodes = baseNodes;
            dbg.log('step:call', `  → METHOD fallback: METHOD::${targetFunc} (${tNodes.length} nodes)`);
          }
        }
        if (tNodes.length > 0) {
          dbg.log('step:call', `  → pushing frame: ${targetNpc}::${targetFunc} (${tNodes.length} nodes)`);
          s.callStack.push({
            npcName: targetNpc,
            functionName: targetFunc,
            env: {},
            blocks: [{ nodes: tNodes, pc: 0 }]
          });
        } else {
          dbg.warn('step:call', `[${node.id}] MISSING target ${targetNpc}::${targetFunc}`);
          console.warn(`[Missing target ${targetNpc}::${targetFunc}]`, node.id);
        }
        break;
      }
      case 'BeginConversation': {
        // RF-09: in the shipped engine beginConversation spawns a separate process that
        // calls Kernel::killProcesses(), terminating the use() event process and preserving
        // any pre-seeded flag state. The web engine has no process model; we re-apply
        // defaultFlags as the closest equivalent, but cannot undo arbitrary pre-BC mutations.
        const reapplied = Object.entries(s.defaultFlags);
        for (const [k, v] of reapplied) {
          s.flags[k] = v;
        }
        if (reapplied.length > 0) {
          dbg.log('step:bc', `[${node.id}] BeginConversation: re-applied ${reapplied.length} defaultFlag(s): ${reapplied.map(([k, v]) => k + '=' + v).join(', ')}`);
        } else {
          dbg.log('step:bc', `[${node.id}] BeginConversation: no defaultFlags — pre-BC flag mutations remain (web engine limitation)`);
        }
        s.history.push({ speaker: 'system', text: '[NPC approaches — beginConversation]' });
        break;
      }
      case 'EndConversation': {
        s.history.push({ speaker: 'system', text: '[Conversation ended]' });
        s.ended = true;
        return s;
      }
      default: {
        // RF-06/RF-13: unknown or unhandled node type (e.g. 'Jump' — a jmp the extractor
        // couldn't fold into structured control flow). Log and advance past it.
        dbg.warn('step:node', `[${node.id}] UNHANDLED node type: '${node.type}' raw=${JSON.stringify(node.raw ?? null)}`);
        break;
      }
    }
  }

  s.history.push({ speaker: 'system', text: '[Engine Timeout]' });
  s.ended = true;
  return s;
}

