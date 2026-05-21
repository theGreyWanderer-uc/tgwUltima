import { test, expect } from '@playwright/test';
import { generateDialogueWalkMarkdown } from '../src/exportDialogueWalker';
import type { DialogueNode, NPCFile } from '../src/types';

function makeNpc(name: string, functions: NPCFile['functions'], flags?: NPCFile['flags']): NPCFile {
  return {
    npc: name,
    sourceFile: `${name}.json`,
    functions,
    flags,
    stats: {
      totalFunctions: Object.keys(functions).length,
      dialogueFunctions: Object.values(functions).filter(f => f.type === 'dialogue').length,
      lookFunctions: 0,
      monologueFunctions: 0,
      shopFunctions: 0,
      behaviorFunctions: 0,
      utilityFunctions: 0,
      totalNodes: 0,
      barkCount: 0,
      dialogueLineCount: 3,
      askCount: 1,
      strcmpBranches: 2,
    },
    hasDialogue: true,
  };
}

test.describe('Dialogue walker markdown export', () => {
  test('shows feature-flagged Export button for dialogue NPCs', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.npc-row');
    await page.locator('.npc-row', { hasText: 'ARAMINA' }).click();

    await expect(page.getByRole('button', { name: 'Export ARAMINA dialogue walk markdown' })).toBeVisible();
  });

  test('exports choices, conditions, and global flag writes', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'met-check',
        type: 'IfStatement',
        condition: {
          raw: 'not testMet',
          flags: [{ flag: 'testMet', negated: true }],
        },
        then: [
          { id: 'hello', type: 'Bark', text: 'A first hello.' },
          { id: 'set-met', type: 'SetFlag', flag: 'testMet', value: '0x01h' },
        ],
      },
      { id: 'menu', type: 'MenuSet', target: 'local2', options: ['name', 'job'] },
      { id: 'ask', type: 'Ask', menu: 'local2' },
      { id: 'capture', type: 'SuspendAssign', var: 'local2' },
      {
        id: 'choice-name',
        type: 'IfStatement',
        condition: {
          raw: 'local2 strcmp "name"',
          strcmp: [{ var: 'local2', value: 'name' }],
        },
        then: [{ id: 'name-line', type: 'Bark', text: 'I have a name.' }],
        else_ifs: [
          {
            condition: {
              raw: 'local2 strcmp "job"',
              strcmp: [{ var: 'local2', value: 'job' }],
            },
            body: [{ id: 'job-line', type: 'Bark', text: 'I have a job.' }],
          },
        ],
      },
    ];

    const npc = makeNpc('TEST_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
        flagsRead: ['testMet'],
        flagsWrite: ['testMet'],
      },
      idle: {
        name: 'idle',
        type: 'monologue',
        isProcess: false,
        processType: 'function',
        nodes: [{ id: 'idle-bark', type: 'Bark', text: 'A proximity bark.' }],
      },
    }, { read: ['testMet'], write: ['testMet'] });

    const markdown = generateDialogueWalkMarkdown(npc, { TEST_NPC: npc });

    expect(markdown).toContain('# TEST_NPC Dialogue Walk');
    expect(markdown).toContain('Global reads: `testMet`');
    expect(markdown).toContain('Global writes: `testMet`');
    expect(markdown).toContain('## U7 Conversion Guide');
    expect(markdown).toContain('### State Model');
    expect(markdown).toContain('NPC MET candidates: `testMet`');
    expect(markdown).toContain('### Ambient/Look Bark Index');
    expect(markdown).toContain('| `idle` | `monologue` | `true` | "A proximity bark." |');
    expect(markdown).toContain('| `talk` | "name" | `true` | `local2` (set) | `name` |');
    expect(markdown).toContain('- `name` from "name" in `talk`');
    expect(markdown).toContain('reads: `not testMet`');
    expect(markdown).toContain('Set global flag `testMet` = `0x01h`');
    expect(markdown).toContain('Ask from menu `local2`: `name`, `job`');
    expect(markdown).toContain('Choice branch "name"');
    expect(markdown).toContain('Else-if choice "job"');
  });

  test('marks loops as non-flat and follows internal calls with recursion guard', async () => {
    const helperNodes: DialogueNode[] = [
      { id: 'helper-line', type: 'Bark', text: 'From helper.' },
      { id: 'helper-recursive', type: 'Call', target: 'helper' },
    ];
    const talkNodes: DialogueNode[] = [
      {
        id: 'loop',
        type: 'ConversationLoop',
        flag: 'local2',
        exitCondition: 'bye',
        body: [
          { id: 'loop-menu', type: 'MenuSet', target: 'local2', options: ['ask', 'bye'] },
          { id: 'loop-ask', type: 'Ask', menu: 'local2' },
        ],
      },
      { id: 'anim-call', type: 'Call', target: 'METHOD::func15E7' },
      { id: 'anim-raw', type: 'Unknown', raw: 'temp = pid <=> process Npc::doAnim(0x00h, 0x2710h, param2, param1, this)' },
      { id: 'call-helper', type: 'Call', target: 'helper' },
    ];

    const npc = makeNpc('LOOP_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
      helper: {
        name: 'helper',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: helperNodes,
      },
    });

    const markdown = generateDialogueWalkMarkdown(npc, { LOOP_NPC: npc });

    expect(markdown).toContain('Conversation loop `loop` using `local2`; exit: `bye`');
    expect(markdown).toContain('Non-flat control flow');
    expect(markdown).toContain('Followed call `LOOP_NPC::helper`');
    expect(markdown).toContain('NPC: "From helper."');
    expect(markdown).toContain('Recursion guard: `LOOP_NPC::helper` already appears in this path.');
    expect(markdown).not.toContain('METHOD::func15E7');
    expect(markdown).not.toContain('Npc::doAnim');
  });
});
