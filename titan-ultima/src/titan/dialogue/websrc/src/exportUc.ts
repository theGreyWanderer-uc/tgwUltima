import type { DialogueFunction, DialogueNode, NodeCondition, NPCFile } from './types';

const INDENT = '  ';

const LOCAL_OR_PARAM_RE = /^(local\d+|local[A-Za-z0-9_]*|param\d+|param[A-Za-z0-9_]*)$/i;

function sanitizeIdentifier(input: string): string {
  const cleaned = input.trim().replace(/[^A-Za-z0-9_]/g, '_');
  if (!cleaned) return 'unnamed';
  if (/^[0-9]/.test(cleaned)) return `_${cleaned}`;
  return cleaned;
}

function quoteString(text: string): string {
  return text
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n');
}

function quoteList(values: string[]): string {
  return values.map((v) => `"${quoteString(v)}"`).join(', ');
}

function normalizeRawCondition(raw: string): string {
  return raw
    .replace(/\&\&/g, ' and ')
    .replace(/\|\|/g, ' or ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isLocalOrParam(name: string): boolean {
  return LOCAL_OR_PARAM_RE.test(name.trim());
}

function normalizeValueExpr(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '0';

  // Preserve values that are already expressions/hex/usecode literals.
  if (
    /^0x[0-9A-Fa-f]+h$/.test(trimmed)
    || /^-?\d+$/.test(trimmed)
    || /^".*"$/.test(trimmed)
    || /[+\-*/()\[\].:]/.test(trimmed)
  ) {
    return trimmed;
  }

  return sanitizeIdentifier(trimmed);
}

function renderCondition(cond?: NodeCondition): string {
  if (!cond) return 'true';
  if (cond.raw && cond.raw.trim()) return normalizeRawCondition(cond.raw);
  if (cond.flags && cond.flags.length > 0) {
    const joiner = cond.combinator === 'or' ? ' or ' : ' and ';
    return cond.flags
      .map((f) => {
        if (f.op && f.values && f.values.length > 0) {
          if (f.values.length === 1) {
            return `${f.flag} ${f.op} ${normalizeValueExpr(f.values[0])}`;
          }
          return f.values
            .map((v) => `${f.flag} ${f.op} ${normalizeValueExpr(v)}`)
            .join(f.op === '!=' ? ' and ' : ' or ');
        }
        return f.negated ? `not ${f.flag}` : f.flag;
      })
      .join(joiner);
  }
  if (cond.isDead) {
    return cond.isDeadNegated ? `not Npc::isDead(${cond.isDead})` : `Npc::isDead(${cond.isDead})`;
  }
  return 'true';
}

function pushLine(lines: string[], level: number, text: string): void {
  lines.push(`${INDENT.repeat(level)}${text}`);
}

function extractStrcmpValue(cond?: NodeCondition): string | undefined {
  if (!cond) return undefined;
  if (cond.strcmp && cond.strcmp.length > 0) {
    return cond.strcmp[0].value;
  }

  const raw = cond.raw?.trim();
  if (!raw) return undefined;
  const quoted = /\bstrcmp\s+"([^"]*)"/i.exec(raw);
  if (quoted) return quoted[1];
  return undefined;
}

type CaseBranch = { label: string; body: DialogueNode[]; sourceId?: string };

function normalizeChoiceText(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function levenshteinDistance(a: string, b: string): number {
  if (a === b) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  const dp: number[][] = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));

  for (let i = 0; i <= a.length; i += 1) dp[i][0] = i;
  for (let j = 0; j <= b.length; j += 1) dp[0][j] = j;

  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + cost,
      );
    }
  }

  return dp[a.length][b.length];
}

function chooseBestMenuLabel(label: string, menuOptions: string[]): string {
  if (menuOptions.length === 0) return label;
  if (menuOptions.includes(label)) return label;

  const normalizedLabel = normalizeChoiceText(label);
  const exactNormalized = menuOptions.find((opt) => normalizeChoiceText(opt) === normalizedLabel);
  if (exactNormalized) return exactNormalized;

  let bestOption = '';
  let bestDistance = Number.POSITIVE_INFINITY;
  let isTie = false;

  for (const option of menuOptions) {
    const normalizedOption = normalizeChoiceText(option);
    const distance = levenshteinDistance(normalizedLabel, normalizedOption);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestOption = option;
      isTie = false;
    } else if (distance === bestDistance) {
      isTie = true;
    }
  }

  if (!isTie && bestDistance <= 2) {
    return bestOption;
  }

  return label;
}

function reconcileBranchLabels(branches: CaseBranch[], menuOptions: string[]): CaseBranch[] {
  return branches.map((branch) => ({
    label: chooseBestMenuLabel(branch.label, menuOptions),
    body: branch.body,
    sourceId: branch.sourceId,
  }));
}

function setMenuOptions(menuState: Map<string, string[]>, menuName: string, options: string[]): void {
  menuState.set(menuName, [...options]);
}

function addMenuOptions(menuState: Map<string, string[]>, menuName: string, options: string[]): void {
  const current = menuState.get(menuName) ?? [];
  for (const option of options) {
    if (!current.includes(option)) current.push(option);
  }
  menuState.set(menuName, current);
}

function removeMenuOptions(menuState: Map<string, string[]>, menuName: string, options: string[]): void {
  const current = menuState.get(menuName) ?? [];
  if (current.length === 0) return;
  const optionSet = new Set(options);
  menuState.set(menuName, current.filter((opt) => !optionSet.has(opt)));
}

function collectMenuOptionsInNodes(nodes: DialogueNode[], menuName: string, acc: Set<string>): void {
  for (const node of nodes) {
    if (
      (node.type === 'MenuSet' || node.type === 'MenuAdd' || node.type === 'MenuUnion')
      && sanitizeIdentifier(node.target ?? node.menu ?? 'menu_options') === menuName
    ) {
      for (const option of node.options ?? []) {
        acc.add(option);
      }
    }

    if (node.type === 'IfStatement') {
      collectMenuOptionsInNodes(node.then ?? [], menuName, acc);
      for (const elif of node.else_ifs ?? []) {
        collectMenuOptionsInNodes(elif.body ?? [], menuName, acc);
      }
      collectMenuOptionsInNodes(node.else ?? [], menuName, acc);
    } else if (node.type === 'ConversationLoop') {
      collectMenuOptionsInNodes(node.body ?? [], menuName, acc);
    }
  }
}

function collectCaseBranchesFromIf(node: DialogueNode): { branches: CaseBranch[]; fallback: DialogueNode[] } {
  if (node.type !== 'IfStatement') {
    return { branches: [], fallback: [] };
  }

  const branches: CaseBranch[] = [];
  const fallback: DialogueNode[] = [];

  const thenLabel = extractStrcmpValue(node.condition);
  if (thenLabel) {
    branches.push({ label: thenLabel, body: node.then ?? [], sourceId: node.id });
  } else if (node.then && node.then.length > 0) {
    fallback.push(...node.then);
  }

  for (const elif of node.else_ifs ?? []) {
    const elifLabel = extractStrcmpValue(elif.condition);
    if (elifLabel) {
      branches.push({ label: elifLabel, body: elif.body ?? [] });
    } else if (elif.body && elif.body.length > 0) {
      fallback.push(...elif.body);
    }
  }

  if (node.else && node.else.length > 0) {
    fallback.push(...node.else);
  }

  return { branches, fallback };
}

function renderCaseBlock(menuName: string, sourceId: string, branches: CaseBranch[], fallback: DialogueNode[], level: number, lines: string[], menuState: Map<string, string[]>, extraSourceIds: string[] = []): void {
  pushLine(lines, level, `// ${sourceId}`);
  for (const extraId of extraSourceIds) {
    pushLine(lines, level, `// ${extraId}`);
  }
  pushLine(lines, level, `converse(${menuName}) // ${sourceId}`);
  pushLine(lines, level, '{');

  for (const branch of branches) {
    const caseLine = branch.sourceId
      ? `case "${quoteString(branch.label)}" (remove): // ${branch.sourceId}`
      : `case "${quoteString(branch.label)}" (remove):`;
    pushLine(lines, level, caseLine);
    renderNodes(branch.body, level + 1, lines, menuState);
    pushLine(lines, level + 1, 'break;');
  }

  if (fallback.length > 0 || branches.length === 0) {
    pushLine(lines, level, 'case "<empty_string>":');
    renderNodes(fallback, level + 1, lines, menuState);
    pushLine(lines, level + 1, 'break;');
  }

  pushLine(lines, level, '}');
}

function renderConversationLoopAsConverse(node: DialogueNode, level: number, lines: string[], menuState: Map<string, string[]>): void {
  if (node.type !== 'ConversationLoop') return;
  const body = node.body ?? [];
  if (body.length === 0) {
    pushLine(lines, level, `converse(options) // ${node.id}`);
    pushLine(lines, level, '{');
    pushLine(lines, level, 'case "<empty_string>":');
    pushLine(lines, level + 1, 'break;');
    pushLine(lines, level, '}');
    return;
  }

  let askMenu: string | undefined;
  let askSourceId: string | undefined;
  let suspendSourceId: string | undefined;
  let askFound = false;
  const setupNodes: DialogueNode[] = [];
  const branches: CaseBranch[] = [];
  const fallbackNodes: DialogueNode[] = [];

  for (const child of body) {
    if (child.type === 'Ask' && !askFound) {
      askFound = true;
      askMenu = sanitizeIdentifier(child.menu ?? 'options');
      askSourceId = child.id;
      continue;
    }

    if (!askFound) {
      if (child.type !== 'SuspendAssign') setupNodes.push(child);
      continue;
    }

    if (askFound && child.type === 'SuspendAssign' && !suspendSourceId) {
      suspendSourceId = child.id;
      continue;
    }

    if (child.type === 'IfStatement') {
      const thenLabel = extractStrcmpValue(child.condition);
      if (thenLabel) {
        branches.push({ label: thenLabel, body: child.then ?? [], sourceId: child.id });
      } else if (child.then && child.then.length > 0) {
        fallbackNodes.push(...child.then);
      }

      for (const elif of child.else_ifs ?? []) {
        const elifLabel = extractStrcmpValue(elif.condition);
        if (elifLabel) {
          branches.push({ label: elifLabel, body: elif.body ?? [] });
        } else if (elif.body && elif.body.length > 0) {
          fallbackNodes.push(...elif.body);
        }
      }

      if (child.else && child.else.length > 0) {
        fallbackNodes.push(...child.else);
      }
      continue;
    }

    if (child.type !== 'SuspendAssign') {
      fallbackNodes.push(child);
    }
  }

  if (!askMenu) askMenu = 'options';

  for (const setup of setupNodes) {
    renderNodes([setup], level, lines, menuState);
  }

  const allMenuOptions = new Set<string>(menuState.get(askMenu) ?? []);
  collectMenuOptionsInNodes(body, askMenu, allMenuOptions);
  const reconciledBranches = reconcileBranchLabels(branches, Array.from(allMenuOptions));
  if (askSourceId) pushLine(lines, level, `// ${askSourceId}`);
  if (suspendSourceId) pushLine(lines, level, `// ${suspendSourceId}`);
  pushLine(lines, level, `converse(${askMenu}) // ${node.id}`);
  pushLine(lines, level, '{');
  if (reconciledBranches.length > 0) {
    for (const branch of reconciledBranches) {
      const caseLine = branch.sourceId
        ? `case "${quoteString(branch.label)}" (remove): // ${branch.sourceId}`
        : `case "${quoteString(branch.label)}" (remove):`;
      pushLine(lines, level, caseLine);
      renderNodes(branch.body, level + 1, lines, menuState);
      if (node.exitCondition && branch.label === node.exitCondition) {
        pushLine(lines, level + 1, 'sayGoodbye2(item);');
        pushLine(lines, level + 1, 'break;');
      } else {
        pushLine(lines, level + 1, 'break;');
      }
    }
  }

  if (fallbackNodes.length > 0 || reconciledBranches.length === 0) {
    pushLine(lines, level, 'case "<empty_string>":');
    renderNodes(fallbackNodes, level + 1, lines, menuState);
    pushLine(lines, level + 1, 'break;');
  }
  pushLine(lines, level, '}');
}

function renderNodes(nodes: DialogueNode[], level: number, lines: string[], menuState: Map<string, string[]> = new Map()): void {
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i];
    switch (node.type) {
      case 'Bark':
      case 'DialogueLine': {
        const text = quoteString(node.text ?? '');
        pushLine(lines, level, `say("@${text}@"); // ${node.id}`);
        break;
      }
      case 'Ask': {
        const menuName = sanitizeIdentifier(node.menu ?? 'menu_options');
        const nextNode = nodes[i + 1];
        const suspendNode = nextNode?.type === 'SuspendAssign' ? nextNode : undefined;
        const ifNodeIndex = suspendNode ? i + 2 : i + 1;
        const ifNode = nodes[ifNodeIndex];
        if (ifNode?.type === 'IfStatement') {
          const { branches, fallback } = collectCaseBranchesFromIf(ifNode);
          const allMenuOptions = new Set<string>(menuState.get(menuName) ?? []);
          collectMenuOptionsInNodes([ifNode], menuName, allMenuOptions);
          const reconciledBranches = reconcileBranchLabels(branches, Array.from(allMenuOptions));
          if (branches.length > 0) {
            const consumedIds = suspendNode ? [suspendNode.id] : [];
            renderCaseBlock(menuName, node.id, reconciledBranches, fallback, level, lines, menuState, consumedIds);
            i = ifNodeIndex;
            break;
          }
        }

        const choiceName = `${menuName}_choice`;
        if (node.menu) {
          pushLine(lines, level, `var ${choiceName} = chooseFromMenu(${menuName}); // ${node.id}`);
        } else {
          pushLine(lines, level, `var choice = chooseFromMenu(menu_options); // ${node.id}`);
        }
        break;
      }
      case 'MenuSet':
      case 'MenuAdd':
      case 'MenuUnion':
      case 'MenuRemove': {
        const menuName = sanitizeIdentifier(node.target ?? node.menu ?? 'menu_options');
        const options = node.options ?? [];
        const opts = quoteList(options);
        if (node.type === 'MenuSet') {
          pushLine(lines, level, `var ${menuName} = [${opts}]; // ${node.id}`);
          setMenuOptions(menuState, menuName, options);
        } else if (node.type === 'MenuAdd' || node.type === 'MenuUnion') {
          pushLine(lines, level, `${menuName} = ${menuName} + [${opts}]; // ${node.id}`);
          addMenuOptions(menuState, menuName, options);
        } else {
          pushLine(lines, level, `// remove [${opts}] from ${menuName} // ${node.id}`);
          removeMenuOptions(menuState, menuName, options);
        }
        break;
      }
      case 'SetFlag': {
        const flag = node.flag ?? 'UNKNOWN_FLAG';
        const value = normalizeValueExpr(node.value ?? '1');
        if (isLocalOrParam(flag)) {
          pushLine(lines, level, `${sanitizeIdentifier(flag)} = ${value}; // ${node.id}`);
        } else {
          pushLine(lines, level, `gflags[${flag}] = ${value}; // ${node.id}`);
        }
        break;
      }
      case 'StringAssign': {
        const variable = sanitizeIdentifier(node.var ?? 'localValue');
        const source = (node.raw && node.raw.trim()) ? node.raw.trim() : '';
        const assignmentFromRaw = source.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/);
        if (assignmentFromRaw) {
          pushLine(lines, level, `${sanitizeIdentifier(assignmentFromRaw[1])} = ${assignmentFromRaw[2]}; // ${node.id}`);
        } else {
          const value = quoteString(node.value ?? '');
          pushLine(lines, level, `${variable} = "${value}"; // ${node.id}`);
        }
        break;
      }
      case 'SuspendAssign': {
        const variable = sanitizeIdentifier(node.var ?? 'localChoice');
        pushLine(lines, level, `${variable} = suspend; // ${node.id}`);
        break;
      }
      case 'Call': {
        const target = node.target ?? 'UNKNOWN::function';
        pushLine(lines, level, `${target}(); // ${node.id}`);
        break;
      }
      case 'BeginConversation': {
        pushLine(lines, level, `startConvo(item, [], [], [], []); // ${node.id}`);
        break;
      }
      case 'EndConversation': {
        pushLine(lines, level, `sayGoodbye2(item); // ${node.id}`);
        pushLine(lines, level, 'return;');
        break;
      }
      case 'ConversationLoop': {
        renderConversationLoopAsConverse(node, level, lines, menuState);
        break;
      }
      case 'IfStatement': {
        const cond = renderCondition(node.condition);
        pushLine(lines, level, `if (${cond}) { // ${node.id}`);
        renderNodes(node.then ?? [], level + 1, lines, menuState);
        pushLine(lines, level, '}');

        for (const elif of node.else_ifs ?? []) {
          const elifCond = renderCondition(elif.condition);
          pushLine(lines, level, `else if (${elifCond}) {`);
          renderNodes(elif.body ?? [], level + 1, lines, menuState);
          pushLine(lines, level, '}');
        }

        if (node.else && node.else.length > 0) {
          pushLine(lines, level, 'else {');
          renderNodes(node.else, level + 1, lines, menuState);
          pushLine(lines, level, '}');
        }
        break;
      }
      case 'Unknown':
      case 'Jump':
      default: {
        const raw = node.raw ? ` ${node.raw}` : '';
        pushLine(lines, level, `// ${node.type}${raw} // ${node.id}`);
        break;
      }
    }
  }
}

function renderFunction(npcName: string, fn: DialogueFunction, forceEntryPoint = false): string {
  const lines: string[] = [];
  const fnName = sanitizeIdentifier(fn.name);
  const owner = sanitizeIdentifier(npcName);
  const isPrimaryDialogue = fn.type === 'dialogue' && (forceEntryPoint || fn.name === 'talk' || fn.name === 'use');

  if (isPrimaryDialogue) {
    lines.push(`void ${owner} object#() ()`);
  } else {
    lines.push(`var ${owner}_${fnName}()`);
  }
  lines.push('{');

  if (isPrimaryDialogue) {
    pushLine(lines, 1, '///////////');
    pushLine(lines, 1, '// SETUP //');
    pushLine(lines, 1, '///////////');
    pushLine(lines, 1, 'var npc = item;');
    pushLine(lines, 1, 'var player_name = getAvatarName();');
    pushLine(lines, 1, 'var started_talking = UI_get_item_flag(item, READ);');
    lines.push('');
  }

  if (fn.nodes && fn.nodes.length > 0) {
    renderNodes(fn.nodes, 1, lines, new Map());
  } else {
    pushLine(lines, 1, '// no nodes');
  }

  lines.push('}');
  return lines.join('\n');
}

export function generateUcForNpc(npc: NPCFile): string {
  const lines: string[] = [];
  lines.push(`// Auto-exported from dialogue/web viewer`);
  lines.push(`// Pattern target: PaganExultedEdition/npcs/Aramina.uc and Shaana.uc`);
  lines.push(`// Helper conventions: PaganExultedEdition/utility/convo_start.uc, choose_from_menu.uc`);
  lines.push(`// NPC: ${npc.npc}`);
  lines.push(`// Source: ${npc.sourceFile}`);
  lines.push('');

  const dialogueFunctions = Object.values(npc.functions)
    .filter((fn) => fn.type === 'dialogue')
    .sort((a, b) => {
      const score = (name: string): number => {
        if (name === 'use') return 0;
        if (name === 'talk') return 1;
        return 2;
      };
      const sa = score(a.name);
      const sb = score(b.name);
      if (sa !== sb) return sa - sb;
      return a.name.localeCompare(b.name);
    });

  if (dialogueFunctions.length === 0) {
    lines.push('// No dialogue function found for this NPC.');
    return lines.join('\n');
  }

  dialogueFunctions.forEach((fn, index) => {
    if (index > 0) lines.push('');
    lines.push(renderFunction(npc.npc, fn, index === 0));
  });

  return lines.join('\n');
}

export function downloadTextFile(fileName: string, content: string): void {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
