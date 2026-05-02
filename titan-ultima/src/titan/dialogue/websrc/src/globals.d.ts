export {};

type DialogueDebugCategory =
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

declare global {
  interface Window {
    useWorldState?: typeof import('./store').useWorldState;
    dialogueDebug?: {
      on: (...cats: Array<DialogueDebugCategory | 'all'>) => void;
      off: (...cats: Array<DialogueDebugCategory | 'all'>) => void;
      status: () => void;
      categories: () => string[];
    };
  }
}
