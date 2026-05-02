import { useEffect, useMemo, useRef, useState } from 'react';
import { startConversation } from './engine';
import { useWorldState } from './store';
import { loadSidecarMetaForNpc } from './data';
import type { DialogueFunction, NPCFile, SidecarMeta } from './types';

interface UtilPanelProps {
  npc: NPCFile;
  open: boolean;
  onClose: () => void;
}

interface ExecutionReport {
  functionName: string;
  conditionPolicy: 'permissive' | 'strict';
  callChain: string[];
  changedFlags: Array<{ name: string; before: number; after: number }>;
  reads: string[];
  writes: string[];
  unresolvedCount: number;
  historyLines: string[];
  paused: boolean;
  ended: boolean;
}

export function UtilPanel({ npc, open, onClose }: Readonly<UtilPanelProps>) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const { flags, conditionPolicy, npcIndex, sidecarMetaByNpc, setSidecarMeta } = useWorldState();
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [sidecarLoading, setSidecarLoading] = useState(false);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClose = () => onClose();
    dialog.addEventListener('close', handleClose);
    return () => dialog.removeEventListener('close', handleClose);
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const hasCached = Object.hasOwn(sidecarMetaByNpc, npc.npc);
    if (hasCached) return;
    let mounted = true;
    setSidecarLoading(true);
    loadSidecarMetaForNpc(npc.npc)
      .then((meta) => {
        if (!mounted) return;
        setSidecarMeta(npc.npc, meta);
      })
      .finally(() => {
        if (mounted) setSidecarLoading(false);
      });
    return () => { mounted = false; };
  }, [open, npc.npc, sidecarMetaByNpc, setSidecarMeta]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const handleClick = (e: MouseEvent) => {
      if (e.target === dialog) onClose();
    };
    dialog.addEventListener('click', handleClick);
    return () => dialog.removeEventListener('click', handleClick);
  }, [onClose]);

  const utilFunctions = useMemo(
    () => Object.values(npc.functions)
      .filter(f => f.type === 'behavior' || f.type === 'utility')
      .sort((a, b) => a.name.localeCompare(b.name)),
    [npc]
  );

  const readFlags = npc.flags?.read ?? [];
  const writeFlags = npc.flags?.write ?? [];
  const sidecar: SidecarMeta | null = sidecarMetaByNpc[npc.npc] ?? null;

  const normalizeFunctionName = (name: string): string => {
    const trimmed = name.trim();
    const base = trimmed.includes('::') ? trimmed.split('::').pop() ?? trimmed : trimmed;
    return base.replace(/^func/i, '').toLowerCase();
  };

  const sidecarRoleByName = useMemo(() => {
    const map = new Map<string, string>();
    const items = sidecar?.function_map ?? [];
    for (const item of items) {
      const name = item.name?.trim();
      const role = item.role?.trim();
      if (!name || !role) continue;
      map.set(name, role);
      const short = name.includes('::') ? name.split('::').pop() : name;
      if (short && !map.has(short)) {
        map.set(short, role);
      }
      const normalized = normalizeFunctionName(name);
      if (normalized && !map.has(normalized)) {
        map.set(normalized, role);
      }
    }
    return map;
  }, [sidecar]);

  const oneLinerForFunction = (functionName: string): string | null => {
    const direct = sidecarRoleByName.get(functionName);
    if (direct) return direct;
    const short = functionName.includes('::') ? functionName.split('::').pop() : functionName;
    if (short) {
      const shortMatch = sidecarRoleByName.get(short);
      if (shortMatch) return shortMatch;
    }
    return sidecarRoleByName.get(normalizeFunctionName(functionName)) ?? null;
  };

  const fallbackOneLinerForFunction = (fn: DialogueFunction): string => {
    const nodeCount = fn.nodes?.length ?? 0;
    const reads = fn.flagsRead?.length ?? 0;
    const writes = fn.flagsWrite?.length ?? 0;
    const mode = fn.isProcess ? 'Process' : 'Function';
    const details: string[] = [];

    if (nodeCount > 0) {
      details.push(`${nodeCount} nodes`);
    }
    if (reads > 0) {
      details.push(`reads ${reads} flag${reads === 1 ? '' : 's'}`);
    }
    if (writes > 0) {
      details.push(`writes ${writes} flag${writes === 1 ? '' : 's'}`);
    }

    if (details.length > 0) {
      return `${mode} ${fn.name} (${fn.type}): ${details.join(', ')}.`;
    }
    return `${mode} ${fn.name} (${fn.type}); sidecar one-liner not yet available.`;
  };

  const displayOneLinerForFunction = (fn: DialogueFunction): string => (
    oneLinerForFunction(fn.name) ?? fallbackOneLinerForFunction(fn)
  );

  const runFunction = (functionName: string) => {
    const before = { ...flags };
    const next = startConversation(npc, functionName, before, conditionPolicy, npcIndex);
    const allFlagNames = new Set([...Object.keys(before), ...Object.keys(next.flags)]);
    const changedFlags = Array.from(allFlagNames)
      .map((name) => ({ name, before: before[name] ?? 0, after: next.flags[name] ?? 0 }))
      .filter((entry) => entry.before !== entry.after)
      .sort((a, b) => a.name.localeCompare(b.name));
    const callChain = Object.keys(next.callVisitCounts).sort((a, b) => a.localeCompare(b));
    const historyLines = next.history.slice(-12).map((msg) => `${msg.speaker.toUpperCase()}: ${msg.text}`);

    setReport({
      functionName,
      conditionPolicy,
      callChain,
      changedFlags,
      reads: readFlags,
      writes: writeFlags,
      unresolvedCount: next.unresolvedConditionCount,
      historyLines,
      paused: next.paused,
      ended: next.ended,
    });
  };

  let reportEngineState = 'idle';
  if (report) {
    if (report.ended) {
      reportEngineState = 'ended';
    } else if (report.paused) {
      reportEngineState = 'paused';
    }
  }

  return (
    <dialog ref={dialogRef} className="util-dialog">
      <div className="util-modal">
        <div className="util-modal-header">
          <h2 className="util-modal-title">{npc.npc} Description</h2>
          <button className="util-close" onClick={onClose} aria-label="Close description">x</button>
        </div>

        <div className="util-modal-body">
          {sidecarLoading && (
            <section className="util-section">
              <h3 className="util-heading">Metadata</h3>
              <div className="util-empty">Loading sidecar metadata...</div>
            </section>
          )}

          {sidecar && (
            <section className="util-section">
              <h3 className="util-heading">Metadata Summary</h3>
              <div className="util-meta-grid">
                <div className="util-meta-card">
                  <div className="util-meta-label">Schema Version</div>
                  <div className="util-meta-value util-mono">{sidecar.sidecar_schema_version ?? 'unknown'}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Main Function</div>
                  <div className="util-meta-value util-mono">{sidecar.main_function?.name ?? 'n/a'}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Execution Form</div>
                  <div className="util-meta-value">{sidecar.main_function?.execution_form ?? 'n/a'}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Source of Truth</div>
                  <div className="util-meta-value util-mono">{sidecar.source_of_truth ?? 'n/a'}</div>
                </div>
              </div>

              {sidecar.quick_facts?.behavior_summary_one_liner && (
                <div className="util-report-card" style={{ marginTop: '8px' }}>
                  <div className="util-flag-label">One-Liner</div>
                  <div>{sidecar.quick_facts.behavior_summary_one_liner}</div>
                </div>
              )}

              {sidecar.ui_tags && sidecar.ui_tags.length > 0 && (
                <div className="util-report-card" style={{ marginTop: '8px' }}>
                  <div className="util-flag-label">Tags</div>
                  <div className="util-report-list">
                    {sidecar.ui_tags.map((tag) => (
                      <span key={tag} className="util-flag-pill">{tag}</span>
                    ))}
                  </div>
                </div>
              )}

              {sidecar.behavior_summary && sidecar.behavior_summary.length > 0 && (
                <div className="util-report-card" style={{ marginTop: '8px' }}>
                  <div className="util-flag-label">Behavior Summary</div>
                  <div className="util-log-list">
                    {sidecar.behavior_summary.slice(0, 5).map((line, idx) => (
                      <div key={`${npc.npc}-meta-${idx}`} className="util-log-line">{line}</div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          <div className="util-meta-grid">
            <div className="util-meta-card">
              <div className="util-meta-label">Source File</div>
              <div className="util-meta-value util-mono">{npc.sourceFile}</div>
            </div>
            <div className="util-meta-card">
              <div className="util-meta-label">Functions</div>
              <div className="util-meta-value">{utilFunctions.length}</div>
            </div>
            <div className="util-meta-card">
              <div className="util-meta-label">Flags Read</div>
              <div className="util-meta-value">{readFlags.length}</div>
            </div>
            <div className="util-meta-card">
              <div className="util-meta-label">Flags Written</div>
              <div className="util-meta-value">{writeFlags.length}</div>
            </div>
          </div>

          <section className="util-section">
            <h3 className="util-heading">Utility Functions</h3>
            <div className="util-function-list">
              {utilFunctions.map((fn) => (
                <article key={fn.name} className="util-function-card">
                  <div className="util-function-top">
                    <span className="util-function-name util-mono">{fn.name}</span>
                    <span className="util-pill">{fn.type}</span>
                  </div>
                  <div className="util-function-one-liner">
                    {displayOneLinerForFunction(fn)}
                  </div>
                  <div className="util-function-meta">
                    <span>Process: {fn.processType}</span>
                    <span>Nodes: {fn.nodes?.length ?? 0}</span>
                    <span>Mode: {fn.isProcess ? 'process' : 'function'}</span>
                  </div>
                  <div className="util-function-actions">
                    <button
                      type="button"
                      className="btn btn-small btn-primary"
                      onClick={() => runFunction(fn.name)}
                    >
                      Start Process
                    </button>
                  </div>
                </article>
              ))}
              {utilFunctions.length === 0 && (
                <div className="util-empty">No behavior or utility functions found.</div>
              )}
            </div>
          </section>

          {report && (
            <section className="util-section">
              <h3 className="util-heading">Execution Report</h3>
              <div className="util-report-grid">
                <div className="util-meta-card">
                  <div className="util-meta-label">Function</div>
                  <div className="util-meta-value util-mono">{report.functionName}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Policy</div>
                  <div className="util-meta-value">{report.conditionPolicy}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Engine State</div>
                  <div className="util-meta-value">{reportEngineState}</div>
                </div>
                <div className="util-meta-card">
                  <div className="util-meta-label">Unresolved Conditions</div>
                  <div className="util-meta-value">{report.unresolvedCount}</div>
                </div>
              </div>

              <div className="util-report-columns">
                <div className="util-report-card">
                  <div className="util-flag-label">Call Chain</div>
                  {report.callChain.length > 0 ? (
                    <div className="util-report-list">
                      {report.callChain.map((entry) => (
                        <span key={entry} className="util-flag-pill util-mono">{entry}</span>
                      ))}
                    </div>
                  ) : (
                    <div className="util-empty">No call stack activity captured.</div>
                  )}
                </div>

                <div className="util-report-card">
                  <div className="util-flag-label">Changed Flags</div>
                  {report.changedFlags.length > 0 ? (
                    <div className="util-report-list">
                      {report.changedFlags.map((entry) => (
                        <span key={entry.name} className="util-flag-pill util-mono">
                          {entry.name}: {entry.before} -&gt; {entry.after}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="util-empty">No flag changes.</div>
                  )}
                </div>
              </div>

              <div className="util-report-card">
                <div className="util-flag-label">Recent Output</div>
                {report.historyLines.length > 0 ? (
                  <div className="util-log-list">
                    {report.historyLines.map((line, idx) => (
                      <div key={`${line}-${idx}`} className="util-log-line util-mono">{line}</div>
                    ))}
                  </div>
                ) : (
                  <div className="util-empty">No bark/dialogue output for this run.</div>
                )}
              </div>
            </section>
          )}

          <section className="util-section">
            <h3 className="util-heading">Flag Activity</h3>
            <div className="util-flag-grid">
              <div className="util-flag-card">
                <div className="util-flag-label">Reads</div>
                {readFlags.length > 0 ? (
                  <div className="util-flag-list">
                    {readFlags.map((f) => (
                      <span key={`r-${f}`} className="util-flag-pill util-mono">{f}</span>
                    ))}
                  </div>
                ) : (
                  <div className="util-empty">None</div>
                )}
              </div>
              <div className="util-flag-card">
                <div className="util-flag-label">Writes</div>
                {writeFlags.length > 0 ? (
                  <div className="util-flag-list">
                    {writeFlags.map((f) => (
                      <span key={`w-${f}`} className="util-flag-pill util-mono">{f}</span>
                    ))}
                  </div>
                ) : (
                  <div className="util-empty">None</div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    </dialog>
  );
}
