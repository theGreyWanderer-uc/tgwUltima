import { test, expect } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
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

function loadGeneratedNpc(filename: string): NPCFile {
  const localPath = join(process.cwd(), 'public/data', filename);
  const fallbackPath = join('C:/temp/dialogue/dialogue/websrc/public/data', filename);
  const sourcePath = existsSync(localPath) ? localPath : fallbackPath;
  return JSON.parse(readFileSync(sourcePath, 'utf8')) as NPCFile;
}

function withMockRandom<T>(value: number, fn: () => T): T {
  const originalRandom = Math.random;
  Math.random = () => value;
  try {
    return fn();
  } finally {
    Math.random = originalRandom;
  }
}

function withMockRandomSequence<T>(values: number[], fn: () => T): T {
  const originalRandom = Math.random;
  let index = 0;
  Math.random = () => values[Math.min(index++, values.length - 1)];
  try {
    return fn();
  } finally {
    Math.random = originalRandom;
  }
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

  test('raw strcmp or-chain handles mixed literal and variable comparisons', async () => {
    const talkNodes: DialogueNode[] = [
      { id: 'name-var', type: 'StringAssign', var: 'local3', value: '"I am Avatar."' },
      { id: 'set-menu', type: 'MenuSet', target: 'local2', options: ['I am the Avatar! ', '{local3}', 'Not telling. '] },
      { id: 'ask', type: 'Ask', menu: 'local2' },
      { id: 'capture', type: 'SuspendAssign', var: 'local1' },
      {
        id: 'mixed-branch',
        type: 'IfStatement',
        condition: {
          raw: 'local1 strcmp "I am the Avatar! " or local1 strcmp local3',
          strcmp: [{ var: 'local1', value: 'I am the Avatar! ' }],
        },
        then: [{ id: 'recognized', type: 'Bark', text: 'Recognized.' }],
        else: [{ id: 'unknown', type: 'Bark', text: 'Unknown.' }],
      },
    ];

    const npc = makeNpc('MIXED_STRCMP_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { MIXED_STRCMP_NPC: npc };

    const started = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    expect(started.paused).toBeTruthy();
    expect(started.menuOptions).toEqual(['I am the Avatar! ', 'I am Avatar.', 'Not telling. ']);

    const dynamicNamePath = selectOption(started, 'I am Avatar.', npc, npcIndex);
    const dynamicMessages = dynamicNamePath.history.map(h => h.text);
    expect(dynamicMessages).toContain('Recognized.');
    expect(dynamicMessages).not.toContain('Unknown.');

    const restarted = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    const literalPath = selectOption(restarted, 'I am the Avatar! ', npc, npcIndex);
    expect(literalPath.history.map(h => h.text)).toContain('Recognized.');

    const unknownPath = selectOption(startConversation(npc, 'talk', {}, 'strict', npcIndex), 'Not telling. ', npc, npcIndex);
    expect(unknownPath.history.map(h => h.text)).toContain('Unknown.');
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

  test('conversation loop allows more than ten valid choices when each cycle reaches Ask', async () => {
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

    const npc = makeNpc('LONG_LOOP_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { LONG_LOOP_NPC: npc };

    let state = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    for (let i = 0; i < 12; i++) {
      expect(state.paused, `Expected loop to pause before choice ${i + 1}`).toBeTruthy();
      expect(state.menuOptions).toEqual(['again', 'farewell']);
      state = selectOption(state, 'again', npc, npcIndex);
    }

    expect(state.paused).toBeTruthy();
    expect(state.ended).toBeFalsy();
    expect(state.history.map(h => h.text)).not.toContain('⚠ Loop exhausted (11 iterations) — continuing');

    const exited = selectOption(state, 'farewell', npc, npcIndex);
    expect(exited.ended).toBeTruthy();
    expect(exited.history.some(h => h.text === 'Loop exited.')).toBeTruthy();
  });

  test('conversation loop still caps runaway restarts that do not reach Ask', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'runaway-loop',
        type: 'ConversationLoop',
        flag: 'local2',
        exitCondition: 'farewell',
        body: [{ id: 'runaway-line', type: 'Bark', text: 'Still looping.' }],
      },
      { id: 'after-loop', type: 'Bark', text: 'Recovered after loop guard.' },
    ];

    const npc = makeNpc('RUNAWAY_LOOP_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { RUNAWAY_LOOP_NPC: npc };

    const state = startConversation(npc, 'talk', {}, 'strict', npcIndex);
    const messages = state.history.map(h => h.text);

    expect(messages).toContain('⚠ Loop exhausted (11 iterations) — continuing');
    expect(messages).toContain('Recovered after loop guard.');
    expect(state.ended).toBeTruthy();
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

  test('random conversation branches are rolled and reported at conversation end', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'random-branch',
        type: 'IfStatement',
        condition: { raw: 'urandom(0x64h) > 0x32h' },
        then: [{ id: 'true-line', type: 'Bark', text: 'True random branch.' }],
        else: [
          { id: 'false-line', type: 'Bark', text: 'False random branch.' },
          { id: 'false-end', type: 'EndConversation' },
        ],
      },
    ];

    const npc = makeNpc('RANDOM_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { RANDOM_NPC: npc };

    const state = withMockRandom(0.99, () => startConversation(npc, 'talk', {}, 'strict', npcIndex));
    const messages = state.history.map(h => h.text);

    expect(messages).toContain('True random branch.');
    expect(messages.some(m => m.startsWith('🎲 Random roll at random-branch chose the true branch'))).toBeTruthy();
    expect(messages.some(m => m.includes('first visible outcome: "True random branch."'))).toBeTruthy();
    expect(messages.findIndex(m => m === '[Conversation ended]')).toBeLessThan(
      messages.findIndex(m => m.startsWith('🎲 Random roll at random-branch chose the true branch'))
    );
  });

  test('random branch notes report the selected branch chance', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'random-branch',
        type: 'IfStatement',
        condition: { raw: 'urandom(0x64h) > 0x32h' },
        then: [{ id: 'true-line', type: 'Bark', text: 'True random branch.' }],
        else: [
          { id: 'false-line', type: 'Bark', text: 'False random branch.' },
          { id: 'false-end', type: 'EndConversation' },
        ],
      },
    ];

    const npc = makeNpc('RANDOM_FALSE_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { RANDOM_FALSE_NPC: npc };

    const state = withMockRandom(0, () => startConversation(npc, 'talk', {}, 'strict', npcIndex));
    const messages = state.history.map(h => h.text);

    expect(messages).toContain('False random branch.');
    expect(messages).toContain(
      '🎲 Random roll at random-branch chose the false branch (51% chance; roll 0/99); first visible outcome: "False random branch."; this selected branch ends the conversation. Try New Conversation for another roll.'
    );
  });

  test('random branch notes do not mark endings reached after a later player choice', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'random-branch',
        type: 'IfStatement',
        condition: { raw: 'urandom(0x64h) > 0x32h' },
        then: [{ id: 'direct-end', type: 'EndConversation' }],
        else: [
          { id: 'prompt-line', type: 'Bark', text: 'Choose what happens next.' },
          { id: 'set-menu', type: 'MenuSet', target: 'local2', options: ['bye'] },
          { id: 'ask', type: 'Ask', menu: 'local2' },
          { id: 'capture', type: 'SuspendAssign', var: 'local2' },
          { id: 'later-end', type: 'EndConversation' },
        ],
      },
    ];

    const npc = makeNpc('RANDOM_ASK_THEN_END_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { RANDOM_ASK_THEN_END_NPC: npc };

    const started = withMockRandom(0, () => startConversation(npc, 'talk', {}, 'strict', npcIndex));
    expect(started.paused).toBeTruthy();

    const ended = selectOption(started, 'bye', npc, npcIndex);
    const diceNote = ended.history.map(h => h.text).find(m => m.startsWith('🎲 Random roll at random-branch'));

    expect(diceNote).toContain('first visible outcome: "Choose what happens next."');
    expect(diceNote).not.toContain('this selected branch ends the conversation');
  });

  test('flag-gated endings explain the alternate branch flag value', async () => {
    const talkNodes: DialogueNode[] = [
      {
        id: 'flag-branch',
        type: 'IfStatement',
        condition: {
          raw: 'questDone',
          flags: [{ flag: 'questDone', negated: false }],
        },
        then: [{ id: 'success-line', type: 'Bark', text: 'Quest complete.' }],
        else: [
          { id: 'blocked-line', type: 'Bark', text: 'Come back later.' },
          { id: 'blocked-end', type: 'EndConversation' },
        ],
      },
    ];

    const npc = makeNpc('FLAG_END_NPC', {
      talk: {
        name: 'talk',
        type: 'dialogue',
        isProcess: false,
        processType: 'function',
        nodes: talkNodes,
      },
    });
    const npcIndex = { FLAG_END_NPC: npc };

    const state = startConversation(npc, 'talk', { questDone: 0 }, 'strict', npcIndex);
    const messages = state.history.map(h => h.text);

    expect(messages).toContain('Come back later.');
    expect(messages).toContain('[Conversation ended]');
    expect(messages).toContain(
      '⚑ Conversation ended through the questDone = false branch. Set questDone to true to see the alternate path.'
    );
    expect(messages.findIndex(m => m === '[Conversation ended]')).toBeLessThan(
      messages.findIndex(m => m.startsWith('⚑ Conversation ended through the questDone'))
    );
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

test.describe('Engine behavior real NPC regressions', () => {
  test('CORINTH keeps offering valid topics after the Lleu herdsman branch', async () => {
    const corinth = loadGeneratedNpc('U8P_CORINTH.json');
    const npcIndex = { CORINTH: corinth };

    let state = startConversation(corinth, 'use', {}, 'strict', npcIndex);
    const choose = (choice: string) => {
      expect(state.paused, `Expected CORINTH to be waiting before choosing ${choice}`).toBeTruthy();
      expect(state.menuOptions, `Expected menu to contain ${choice}`).toContain(choice);
      state = selectOption(state, choice, corinth, npcIndex);
    };

    choose('Hello, stranger. ');
    choose("I apologize, m'lady. ");
    choose("I'm called Avatar.");
    choose("So, you don't see many strangers? ");
    choose('What hermit? ');
    choose('What kinds of tales? ');
    choose('Corinth? ');
    choose('Mother ');
    choose('Father ');
    choose('He was a herdsman? ');
    choose('Cost him? ');
    choose('Lleu ');

    const npcLines = state.history.filter(h => h.speaker === 'npc').map(h => h.text);
    expect(npcLines).toContain("Yes, long ago Lleu's herd was attacked by a kith. The kith killed Lleu. ");
    expect(npcLines).toContain("Yes, Lleu, it's an old name. It is rarely used today. In many ways my father's name suited him well. ");
    expect(state.history.map(h => h.text)).not.toContain('⚠ Loop exhausted (11 iterations) — continuing');
  });

  test('CHILD can reach the ask-driven Yeah question chain', async () => {
    const child = loadGeneratedNpc('U8P_CHILD.json');
    const npcIndex = { CHILD: child };

    const state = withMockRandom(0, () => startConversation(child, 'use', {}, 'strict', npcIndex));
    const npcLines = state.history.filter(h => h.speaker === 'npc').map(h => h.text);

    expect(npcLines).toContain('What is your name? ');
    expect(state.paused).toBeTruthy();
    expect(state.menuOptions).toContain('I am the Avatar! ');
    expect(state.menuOptions).toContain('I am Avatar.');
    expect(npcLines).not.toContain("I can't talk to you. ");
  });

  test('CHILD can continue past the first Yeah response after naming the Avatar', async () => {
    const child = loadGeneratedNpc('U8P_CHILD.json');
    const npcIndex = { CHILD: child };

    const started = withMockRandom(0, () => startConversation(child, 'use', {}, 'strict', npcIndex));
    expect(started.paused, 'Expected CHILD to ask for the Avatar name').toBeTruthy();
    expect(started.menuOptions).toContain('I am the Avatar! ');

    const state = selectOption(started, 'I am the Avatar! ', child, npcIndex);
    const npcLines = state.history.filter(h => h.speaker === 'npc').map(h => h.text);

    expect(npcLines).toContain('Yeah? ');
    expect(npcLines).toContain('Where do you come from? ');
    expect(state.paused).toBeTruthy();
    expect(state.menuOptions).toContain('From another world. ');
    expect(state.menuOptions).toContain('From another town. ');
  });

  test('CHILD can continue after choosing the getName-derived Avatar answer', async () => {
    const child = loadGeneratedNpc('U8P_CHILD.json');
    const npcIndex = { CHILD: child };

    const started = withMockRandom(0, () => startConversation(child, 'use', {}, 'strict', npcIndex));
    expect(started.paused, 'Expected CHILD to ask for the Avatar name').toBeTruthy();
    expect(started.menuOptions).toContain('I am Avatar.');

    const state = selectOption(started, 'I am Avatar.', child, npcIndex);
    const npcLines = state.history.filter(h => h.speaker === 'npc').map(h => h.text);

    expect(npcLines).toContain('Yeah? ');
    expect(npcLines).toContain('Where do you come from? ');
    expect(state.paused).toBeTruthy();
    expect(state.menuOptions).toContain('From another world. ');
    expect(state.menuOptions).toContain('From another town. ');
  });

  test('CHILD refusal path reports the random rolls that selected it', async () => {
    const child = loadGeneratedNpc('U8P_CHILD.json');
    const npcIndex = { CHILD: child };

    const state = withMockRandomSequence([0.65, 0.65], () => startConversation(child, 'use', {}, 'strict', npcIndex));
    const messages = state.history.map(h => h.text);

    expect(messages).toContain('Hello... ');
    expect(messages).toContain("I don't know you. ");
    expect(messages).toContain("I can't talk to you. ");
    expect(messages).toContain('[Conversation ended]');
    expect(messages.some(m =>
      m.startsWith('🎲 Random roll at use_n005 chose the true branch') &&
      m.includes('first visible outcome: "Hello..."')
    )).toBeTruthy();
    expect(messages.some(m =>
      m.startsWith('🎲 Random roll at use_n014 chose the true branch') &&
      m.includes('first visible outcome: "I don\'t know you."') &&
      m.includes('this selected branch ends the conversation')
    )).toBeTruthy();
    expect(messages.findIndex(m => m === '[Conversation ended]')).toBeLessThan(
      messages.findIndex(m => m.startsWith('🎲 Random roll at use_n005'))
    );
  });

  test('GUARD10 explains the devonInRule flag-gated ending', async () => {
    const guard = loadGeneratedNpc('U8P_GUARD10.json');
    const npcIndex = { GUARD10: guard };

    let state = withMockRandom(0, () => startConversation(guard, 'use', { devonInRule: 0 }, 'strict', npcIndex));
    for (const choice of ['Who are you? ', 'What is your duty? ', 'Where am I? ']) {
      expect(state.paused, `Expected GUARD10 to be waiting before choosing ${choice}`).toBeTruthy();
      expect(state.menuOptions, `Expected GUARD10 menu to contain ${choice}`).toContain(choice);
      state = selectOption(state, choice, guard, npcIndex);
    }

    const messages = state.history.map(h => h.text);

    expect(messages).toContain('What makes you think I have time for this kind of talk? ');
    expect(messages).toContain('Continue on your way before I decide to put you away. ');
    expect(messages).toContain(
      '⚑ Conversation ended through the devonInRule = false branch. Set devonInRule to true to see the alternate path.'
    );
  });
});
