
export type NodeType =
  | 'Bark'
  | 'DialogueLine'
  | 'Ask'
  | 'MenuSet'
  | 'MenuAdd'
  | 'StringAssign'
  | 'MenuUnion'
  | 'MenuRemove'
  | 'SetFlag'
  | 'Call'
  | 'BeginConversation'
  | 'EndConversation'
  | 'IfStatement'
  | 'ConversationLoop'
  | 'SuspendAssign'
  | 'Jump'
  | 'Unknown';

export type FunctionType =
  | 'dialogue'
  | 'shop'
  | 'look'
  | 'monologue'
  | 'behavior'
  | 'utility';

export interface FlagCondition {
  flag: string;
  negated: boolean;
  op?: '==' | '!=';
  values?: string[];
}

export interface NodeCondition {
  raw?: string;
  flags?: FlagCondition[];
  isDead?: string;
  isDeadNegated?: boolean;  // true = NOT opcode before jne → 'not isDead()' → fires when ALIVE; false → fires when DEAD
  combinator?: 'and' | 'or'; // extractor-set from fold's 'and'/'or' operator; default is 'and'
  strcmp?: { var: string; value: string }[];
}

export interface ElseIfBlock {
  condition?: NodeCondition;
  body: DialogueNode[];
  type?: string;
  flag?: string;
  exitCondition?: string;
  exitWhenMatched?: boolean;
}

export interface DialogueNode {
  id: string;
  type: NodeType;
  text?: string;
  menu?: string;
  target?: string;
  options?: string[];
  flag?: string;
  value?: string;
  var?: string;
  condition?: NodeCondition;
  exitCondition?: string;
  exitWhenMatched?: boolean;
  then?: DialogueNode[];
  else_ifs?: ElseIfBlock[];
  else?: DialogueNode[];
  body?: DialogueNode[];
  raw?: string;
}

export interface VariableHint {
  role: string;
  confidence: 'low' | 'medium' | 'high';
  evidence: string[];
}

export interface VariableHints {
  locals?: Record<string, VariableHint>;
  params?: Record<string, VariableHint>;
}

export interface ShopItem {
  name: string;
  price?: number;
  description?: string;
}

export interface DialogueFunction {
  name: string;
  type: FunctionType;
  isProcess: boolean;
  processType: string;
  params?: string;
  nodes?: DialogueNode[];
  flagsRead?: string[];
  flagsWrite?: string[];
  variableHints?: VariableHints;
  shopItems?: ShopItem[];
}

export interface WeaponProperties {
  baseDamage: number;
  damageModifier: number;
  damageType: string[];
  attackDexBonus: number;
  defendDexBonus: number;
  armourBonus: number;
  isSpecial: boolean;
  treasureChance?: number;
}

export interface ArmourProperties {
  armourClass: number;
  defenseType?: string[];
  kickBonus?: number;
}

export interface OverlayProperties {
  animationStyle: string;
  usedBy: string[];
}

export interface ItemProperties {
  weapon?: WeaponProperties;
  armour?: ArmourProperties;
  overlay?: OverlayProperties;
}

export interface NPCFile {
  npc: string;
  sourceFile: string;
  functions: Record<string, DialogueFunction>;
  flags?: {
    read: string[];
    write: string[];
  };
  stats: {
    totalFunctions: number;
    dialogueFunctions: number;
    lookFunctions: number;
    monologueFunctions: number;
    shopFunctions: number;
    behaviorFunctions: number;
    utilityFunctions: number;
    totalNodes: number;
    barkCount: number;
    dialogueLineCount: number;
    askCount: number;
    strcmpBranches: number;
  };
  hasDialogue: boolean;
  itemProperties?: ItemProperties;
  calledFrom?: Array<{ callerClass: string; callerFunc: string; targetFunc: string }>;
}

export interface SidecarMetaItem {
  name?: string;
  kind?: string;
  role?: string;
  confidence?: 'low' | 'medium' | 'high' | string;
}

export interface SidecarCallEdge {
  caller?: string;
  callee?: string;
  purpose?: string;
  confidence?: 'low' | 'medium' | 'high' | string;
}

export interface SidecarMeta {
  sidecar_schema_version?: string;
  source_of_truth?: string;
  file?: string;
  behavior_summary?: string[];
  notable_control_flow?: string[];
  open_questions?: string[];
  main_function?: {
    name?: string;
    execution_form?: string;
    purpose?: string;
    entry_conditions?: string[];
    confidence?: 'low' | 'medium' | 'high' | string;
  };
  function_map?: SidecarMetaItem[];
  call_analysis?: {
    internal_calls?: SidecarCallEdge[];
    external_calls?: SidecarCallEdge[];
  };
  global_flags?: {
    reads?: Array<{ name?: string; likely_effect?: string; confidence?: string }>;
    writes?: Array<{ name?: string; likely_effect?: string; confidence?: string }>;
  };
  ui_tags?: string[];
  quick_facts?: {
    main_function?: string;
    behavior_summary_one_liner?: string;
    external_call_count?: number;
    flag_read_count?: number;
    flag_write_count?: number;
  };
  hypotheses?: {
    parameters_and_data_flow?: unknown[];
    local_variable_inference?: unknown[];
  };
}

// Runtime types for the viewer

export interface DialogueMessage {
  speaker: 'npc' | 'player' | 'system';
  text: string;
  nodeId?: string;
}

