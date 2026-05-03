import { test, expect } from '@playwright/test';
import { evaluateLook, startConversation, selectOption } from '../src/engine';
import type { DialogueNode, NPCFile } from '../src/types';

function makeNpc(name: string, functions: NPCFile['functions'], hasDialogue = true): NPCFile {
  return {
    npc: name,
    sourceFile: `${name}.json`,
    functions,
    stats: {
      totalFunctions: Object.keys(functions).length,
      dialogueFunctions: 0,
      lookFunctions: 0,
      monologueFunctions: 0,
      shopFunctions: 0,
      behaviorFunctions: 0,
      utilityFunctions: 0,
      totalNodes: 0,
      barkCount: 0,
      dialogueLineCount: 0,
      askCount: 0,
      strcmpBranches: 0,
    },
    hasDialogue,
  };
}

test.describe('Engine behavior fixtures', () => {
  test('structured strcmp condition routes to correct branch', async () => {
    const talkNodes: DialogueNode[] = [
      { id: 'set-menu', type: 'MenuSet', target: 'local2', options: ['Yes', 'No'] },
      { id: 'ask', type: 'Ask', menu: 'local2' },
      { id: 'capture', type: 'SuspendAssign', var: 'local2' },
      {
        id: 'branch',
        type: 'IfStatement',
        condition: {
          raw: 'local2 strcmp "Yes"',
          strcmp: [{ var: 'local2', value: 'Yes' }],
        },
        then: [{ id: 'accepted', type: 'Bark', text: 'Accepted.' }],
        else: [{ id: 'rejected', type: 'Bark', text: 'Rejected.' }],
      },
    ];

    const npc = makeNpc('TEST_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });

    const npcIndex = { TEST_NPC: npc };
    const started = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    expect(started.paused).toBeTruthy();
    expect(started.menuOptions).toEqual(['Yes', 'No']);

    const yesPath = selectOption(started, 'Yes', npc, npcIndex);
    const yesNpcLines = yesPath.history.filter(h => h.speaker === 'npc').map(h => h.text);
    expect(yesNpcLines).toContain('Accepted.');
    expect(yesNpcLines).not.toContain('Rejected.');

    const restarted = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    const noPath = selectOption(restarted, 'No', npc, npcIndex);
    const noNpcLines = noPath.history.filter(h => h.speaker === 'npc').map(h => h.text);
    expect(noNpcLines).toContain('Rejected.');
    expect(noNpcLines).not.toContain('Accepted.');
  });

  test('conversation loop re-prompts on non-exit choice and exits on matching choice', async () => {
    const loopBody: DialogueNode[] = [
      { id: 'loop-menu', type: 'MenuSet', target: 'local2', options: ['again', 'farewell'] },
      { id: 'loop-ask', type: 'Ask', menu: 'local2' },
      { id: 'loop-capture', type: 'SuspendAssign', var: 'local2' },
      {
        id: 'loop-if',
        type: 'IfStatement',
        condition: {
          raw: 'local2 strcmp "again"',
          strcmp: [{ var: 'local2', value: 'again' }],
        },
        then: [{ id: 'loop-line', type: 'Bark', text: 'Looping once more.' }],
      },
    ];

    const talkNodes: DialogueNode[] = [
      {
        id: 'main-loop',
        type: 'ConversationLoop',
        flag: 'local2',
        exitCondition: 'farewell',
        body: loopBody,
      },
      { id: 'after-loop', type: 'Bark', text: 'Loop exited.' },
    ];

    const npc = makeNpc('LOOP_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { LOOP_NPC: npc };

    const started = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    expect(started.paused).toBeTruthy();
    expect(started.menuOptions).toEqual(['again', 'farewell']);

    const once = selectOption(started, 'again', npc, npcIndex);
    expect(once.paused).toBeTruthy();
    expect(once.menuOptions).toEqual(['again', 'farewell']);
    expect(once.history.some(h => h.text === 'Looping once more.')).toBeTruthy();

    const exited = selectOption(once, 'farewell', npc, npcIndex);
    expect(exited.paused).toBeFalsy();
    expect(exited.ended).toBeTruthy();
    expect(exited.history.some(h => h.text === 'Loop exited.')).toBeTruthy();
  });

  test('SuspendAssign pauses and surfaces menu when no prior choice exists', async () => {
    const talkNodes: DialogueNode[] = [
      { id: 'set-menu', type: 'MenuSet', target: 'local3', options: ['A', 'B'] },
      { id: 'capture-only', type: 'SuspendAssign', var: 'local3' },
      { id: 'after', type: 'Bark', text: 'After capture.' },
    ];

    const npc = makeNpc('SUSPEND_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { SUSPEND_NPC: npc };

    const started = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    expect(started.paused).toBeTruthy();
    expect(started.menuOptions).toEqual(['A', 'B']);

    const resumed = selectOption(started, 'A', npc, npcIndex);
    expect(resumed.ended).toBeTruthy();
    expect(resumed.history.some(h => h.text === 'After capture.')).toBeTruthy();
  });

  test('evaluateLook switches active description for alive/dead mode', async () => {
    const lookNodes: DialogueNode[] = [
      {
        id: 'look-if',
        type: 'IfStatement',
        condition: {
          isDead: 'Npc::isDead(this)',
          isDeadNegated: true,
          raw: 'not Npc::isDead(this)',
        },
        then: [{ id: 'alive-line', type: 'Bark', text: 'Looks very alive.' }],
        else: [{ id: 'dead-line', type: 'Bark', text: 'Looks deceased.' }],
      },
    ];

    const npc = makeNpc(
      'LOOK_NPC',
      {
        look: {
          name: 'look',
          type: 'look',
          isProcess: false,
          processType: 'function',
          nodes: lookNodes,
        },
      },
      false
    );
    const npcIndex = { LOOK_NPC: npc };

    const alive = evaluateLook(npc, {}, { deadMode: 'alive' }, npcIndex);
    const dead = evaluateLook(npc, {}, { deadMode: 'dead' }, npcIndex);

    const aliveActive = alive.filter(d => d.active).map(d => d.text);
    const deadActive = dead.filter(d => d.active).map(d => d.text);

    expect(aliveActive).toContain('Looks very alive.');
    expect(aliveActive).not.toContain('Looks deceased.');

    expect(deadActive).toContain('Looks deceased.');
    expect(deadActive).not.toContain('Looks very alive.');
  });
});
