import { useRef, useEffect, useMemo, useState } from 'react';
import { useWorldState } from './store';
import { findTalkFunction, findLookFunction, findShopFunction } from './engine';
import { LookPanel } from './LookPanel';
import { ShopPanel } from './ShopPanel';
import { BookPanel } from './BookPanel';
import { UtilPanel } from './UtilPanel';
import type { DialogueMessage, NPCFile, DialogueNode, VariableHint } from './types';

const OPEN_GLOBAL_FLAGS_EVENT = 'open-global-flags';

export function DialoguePlayer() {
  const {
    selectedNpc,
    engine,
    startTalking,
    startShopping,
    pickOption,
    undoLastChoice,
    undoStack,
    resetCurrentNpcFlags,
    resetAllGlobalFlags,
    endConversation,
    conditionPolicy,
    setConditionPolicy,
  } = useWorldState();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [lookOpen, setLookOpen] = useState(false);
  const [shopOpen, setShopOpen] = useState(false);
  const [bookOpen, setBookOpen] = useState(false);
  const [utilOpen, setUtilOpen] = useState(false);

  // Reset look/shop/book view when NPC changes
  useEffect(() => { setLookOpen(false); setShopOpen(false); setBookOpen(false); setUtilOpen(false); }, [selectedNpc?.npc]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [engine?.history.length]);

  const unresolvedDebug = useMemo(() => {
    if (!selectedNpc || !engine || engine.unresolvedConditionCount === 0) return [] as Array<{
      nodeId: string;
      raw?: string;
      hints: Array<{ name: string; hint: VariableHint }>;
    }>;

    const nodeIndex = buildNodeIndex(selectedNpc);
    const unresolvedIds = Object.keys(engine.unresolvedConditionNodes);
    return unresolvedIds.map((nodeId) => {
      const entry = nodeIndex.get(nodeId);
      const raw = entry?.node.condition?.raw;
      const refs = extractLocalParamRefs(raw ?? '');
      const hints: Array<{ name: string; hint: VariableHint }> = [];

      if (entry?.func.variableHints) {
        for (const name of refs) {
          const lh = entry.func.variableHints.locals?.[name];
          const ph = entry.func.variableHints.params?.[name];
          const hint = lh ?? ph;
          if (hint) hints.push({ name, hint });
        }
      }

      return { nodeId, raw, hints };
    });
  }, [engine, selectedNpc]);

  if (!selectedNpc) {
    return (
      <div className="dialogue-panel empty-state">
        <p>Select an NPC from the sidebar to begin.</p>
      </div>
    );
  }

  const hasTalk = !!findTalkFunction(selectedNpc);
  const hasLook = !!findLookFunction(selectedNpc);
  const hasShop = !!findShopFunction(selectedNpc);
  const canUndo = undoStack.length > 0;
  const hasBooks = selectedNpc.npc === 'BASEBOOK';
  const hasUtil = !hasTalk
    && !hasLook
    && !hasShop
    && Object.values(selectedNpc.functions).some(f => f.type === 'behavior' || f.type === 'utility');

  if (!engine) {
    return (
      <div className="dialogue-panel">
        <div className="dialogue-header">
          <h2>{selectedNpc.npc}</h2>
          <div className="policy-controls">
            <span className="policy-label">Raw Conditions:</span>
            <button
              className={`btn btn-tiny ${conditionPolicy === 'permissive' ? 'btn-active' : ''}`}
              onClick={() => setConditionPolicy('permissive')}
              type="button"
            >
              Permissive
            </button>
            <button
              className={`btn btn-tiny ${conditionPolicy === 'strict' ? 'btn-active' : ''}`}
              onClick={() => setConditionPolicy('strict')}
              type="button"
            >
              Strict
            </button>
          </div>
          <div className="dialogue-meta">
            {selectedNpc.stats.dialogueLineCount} lines &middot;{' '}
            {selectedNpc.stats.strcmpBranches} branches
          </div>
        </div>
        {selectedNpc.calledFrom && selectedNpc.calledFrom.length > 0 && (
          <div className="cross-ref-note">
            <span className="cross-ref-label">Scene called from:</span>
            {selectedNpc.calledFrom.map((ref, i) => (
              <span key={`${ref.callerClass}:${ref.callerFunc}:${i}`} className="cross-ref-badge">
                {ref.callerClass}::{ref.callerFunc}
              </span>
            ))}
          </div>
        )}
        <div className="dialogue-body">
          <div className="action-buttons">
            {hasTalk && (
              <button className="btn btn-primary" onClick={() => startTalking(selectedNpc)}>
                Talk to {selectedNpc.npc}
              </button>
            )}
            {hasLook && (
              <button className="btn" onClick={() => setLookOpen(true)}>
                Look at {selectedNpc.npc}
              </button>
            )}
            {hasShop && (
              <button className="btn" onClick={() => setShopOpen(true)}>
                {selectedNpc.npc}&apos;s Shop
              </button>
            )}
            {hasBooks && (
              <button className="btn" onClick={() => setBookOpen(true)}>
                📖 Read Books
              </button>
            )}
            {hasUtil && (
              <button className="btn" onClick={() => setUtilOpen(true)}>
                Describe {selectedNpc.npc}
              </button>
            )}
          </div>
          {!hasTalk && !hasLook && !hasShop && !hasBooks && !hasUtil && (
            <div className="empty-state">
              <p>No interactive functions available.</p>
            </div>
          )}
        </div>
        {hasLook && (
          <LookPanel
            npc={selectedNpc}
            open={lookOpen}
            onClose={() => setLookOpen(false)}
            onOpenFlags={() => {
              setLookOpen(false);
              window.dispatchEvent(new CustomEvent(OPEN_GLOBAL_FLAGS_EVENT));
            }}
          />
        )}
        {hasShop && (
          <ShopPanel
            npc={selectedNpc}
            open={shopOpen}
            onClose={() => setShopOpen(false)}
          />
        )}
        {hasBooks && (
          <BookPanel
            npcName={selectedNpc.npc}
            open={bookOpen}
            onClose={() => setBookOpen(false)}
          />
        )}
        {hasUtil && (
          <UtilPanel
            npc={selectedNpc}
            open={utilOpen}
            onClose={() => setUtilOpen(false)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="dialogue-panel">
      <div className="dialogue-header">
        <h2>{selectedNpc.npc}</h2>
        <div className="dialogue-header-actions">
          <div className="policy-controls">
            <span className="policy-label">Raw Conditions:</span>
            <button
              className={`btn btn-tiny ${conditionPolicy === 'permissive' ? 'btn-active' : ''}`}
              onClick={() => setConditionPolicy('permissive')}
              type="button"
            >
              Permissive
            </button>
            <button
              className={`btn btn-tiny ${conditionPolicy === 'strict' ? 'btn-active' : ''}`}
              onClick={() => setConditionPolicy('strict')}
              type="button"
            >
              Strict
            </button>
          </div>
          <button className="btn btn-small" onClick={endConversation}>New Conversation</button>
          <div className="policy-controls">
            <span className="policy-label">Flags:</span>
            <button className="btn btn-tiny" onClick={resetCurrentNpcFlags} type="button">
              Reset {selectedNpc.npc}
            </button>
            <button className="btn btn-tiny" onClick={resetAllGlobalFlags} type="button">
              Reset ALL
            </button>
          </div>
        </div>
      </div>

      {selectedNpc.calledFrom && selectedNpc.calledFrom.length > 0 && (
        <div className="cross-ref-note">
          <span className="cross-ref-label">Scene called from:</span>
          {selectedNpc.calledFrom.map((ref, i) => (
            <span key={`${ref.callerClass}:${ref.callerFunc}:${i}`} className="cross-ref-badge">
              {ref.callerClass}::{ref.callerFunc}
            </span>
          ))}
        </div>
      )}

      {engine.callStack.length > 0 && (
        <div className="call-chain" aria-label="Call chain">
          <span className="call-chain-label">Call Chain:</span>
          {engine.callStack.map((frame, idx) => (
            <span key={`${frame.npcName}:${frame.functionName}:${idx}`} className="call-chain-badge">
              {frame.npcName}::{frame.functionName}
            </span>
          ))}
        </div>
      )}

      {engine.unresolvedConditionCount > 0 && (
        <div className="condition-health">
          <div>Unresolved conditions: {engine.unresolvedConditionCount}</div>
          {unresolvedDebug.length > 0 && (
            <div className="condition-debug-list">
              {unresolvedDebug.slice(0, 8).map(item => (
                <div key={item.nodeId} className="condition-debug-item">
                  <div className="condition-debug-head">{item.nodeId}</div>
                  {item.raw && <div className="condition-debug-raw">{item.raw}</div>}
                  {item.hints.length > 0 && (
                    <div className="condition-debug-hints">
                      {item.hints.map(({ name, hint }) => (
                        <span key={`${item.nodeId}:${name}`} className="condition-hint-pill">
                          {name}: {hint.role} ({hint.confidence})
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="dialogue-body" ref={scrollRef}>
        <div className="message-list">
          {engine.history.map((msg, i) => (
            <MessageBubble key={`${msg.nodeId ?? 'msg'}-${i}`} msg={msg} npcName={selectedNpc.npc} />
          ))}
        </div>
      </div>

      {engine.paused && engine.menuOptions.length > 0 && (
        <div className="dialogue-choices">
          <div className="choices-label">Choose your response:</div>
          {canUndo && (
            <button className="btn btn-small" onClick={undoLastChoice} type="button">
              Back (undo last choice)
            </button>
          )}
          <div className="choices-grid">
            {engine.menuOptions.map((opt, i) => (
              <button key={`${opt}-${i}`} className="btn btn-choice" onClick={() => pickOption(opt)}>
                {opt.trim() || '(walk away)'}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function buildNodeIndex(npc: NPCFile): Map<string, { node: DialogueNode; func: NPCFile['functions'][string] }> {
  const out = new Map<string, { node: DialogueNode; func: NPCFile['functions'][string] }>();
  for (const func of Object.values(npc.functions)) {
    function walk(nList: DialogueNode[]) {
      for (const node of nList) {
        out.set(node.id, { node, func });
        if (node.then) walk(node.then);
        if (node.else) walk(node.else);
        if (node.else_ifs) node.else_ifs.forEach(e => walk(e.body));
        if (node.body) walk(node.body);
      }
    }
    walk(func.nodes ?? []);
  }
  return out;
}

function extractLocalParamRefs(raw: string): string[] {
  const refs = raw.match(/\b(?:local\d+|param\d+)\b/gi) ?? [];
  return [...new Set(refs.map(r => r.trim()))];
}

function MessageBubble({ msg, npcName }: { msg: DialogueMessage; npcName: string }) {
  if (msg.speaker === 'system') {
    return <div className="msg msg-system">{msg.text}</div>;
  }
  return (
    <div className={`msg msg-${msg.speaker}`}>
      <div className={`msg-speaker msg-speaker-${msg.speaker}`}>
        {msg.speaker === 'npc' ? npcName : 'Avatar'}
      </div>
      <div className="msg-text">{msg.text}</div>
      {msg.nodeId && <div className="msg-id">{msg.nodeId}</div>}
    </div>
  );
}
