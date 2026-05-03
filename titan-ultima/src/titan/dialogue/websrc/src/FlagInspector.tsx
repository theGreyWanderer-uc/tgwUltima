import { useEffect, useMemo, useState } from 'react';
import { useWorldState } from './store';
import { buildFlagIndex } from './data';

const OPEN_GLOBAL_FLAGS_EVENT = 'open-global-flags';
const TRANSIENT_RUNTIME_FLAGS = new Set(['somebodyTalking']);

// Story / plot-point presets. Each entry sets a named group of flags at once.
const STORY_PRESETS: Array<{ label: string; flags: Record<string, number> }> = [
  {
    label: 'Cut Content',
    flags: { hasHeart: 1 },
  },
  {
    label: 'Post Intro Execution',
    flags: { toranDead: 1 },
  },
];

// Cut-content annotations shown in the flag tooltip.
const FLAG_NOTES: Record<string, string> = {
  hasHeart: '✂ CUT CONTENT: The hasHeart setter was removed from the shipped game ' +
    '(0 writes in EUSECODE.FLX — binary-confirmed). ' +
    'hasHeart=1 triggers zombie invasion NPC dialogue (if(hasHeart) branches). ' +
    'hasHeart=0 default shows normal dialogue. ' +
    'Set to 1 to explore cut content for: Aramina, Jenna, Devon, Darion, Shaana, Tarna, Vividos, Mythran, all City Guards.',
};

export function FlagInspector() {
  const { allNpcs, selectedNpc, flags, flagMeta, setFlag, resetFlags } = useWorldState();
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [showStory, setShowStory] = useState(false);

  const flagIndex = useMemo(() => buildFlagIndex(allNpcs), [allNpcs]);
  const allFlagNames = useMemo(() => [...flagIndex.keys()].sort((a, b) => a.localeCompare(b)), [flagIndex]);

  // Flags scoped to the selected NPC
  const npcFlagNames = useMemo(() => {
    if (!selectedNpc?.flags) return [];
    const set = new Set([...selectedNpc.flags.read, ...selectedNpc.flags.write]);
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [selectedNpc]);

  const scopedToNpc = !showAll && selectedNpc?.flags && npcFlagNames.length > 0;
  const baseFlagNames = scopedToNpc ? npcFlagNames : allFlagNames;

  // Include flags that are set but not in the index (set during gameplay).
  const activeFlags = Object.entries(flags).filter(([name, v]) => v !== 0 && !TRANSIENT_RUNTIME_FLAGS.has(name));

  const filtered = search
    ? baseFlagNames.filter(f => f.toLowerCase().includes(search.toLowerCase()))
    : baseFlagNames;

  useEffect(() => {
    const handleOpenGlobalFlags = () => {
      setOpen(true);
      setShowAll(true);
    };
    window.addEventListener(OPEN_GLOBAL_FLAGS_EVENT, handleOpenGlobalFlags);
    return () => window.removeEventListener(OPEN_GLOBAL_FLAGS_EVENT, handleOpenGlobalFlags);
  }, []);

  if (!open) {
    return (
      <button className="btn btn-panel-toggle" onClick={() => setOpen(true)}>
        &#9873; Global Flags {activeFlags.length > 0 && <span className="badge">{activeFlags.length}</span>}
      </button>
    );
  }

  return (
    <div className="flag-inspector">
      <div className="panel-header">
        <h3>Flag Inspector</h3>
        <div className="panel-actions">
          <button
            className={`btn btn-small ${showStory ? 'btn-active' : ''}`}
            onClick={() => setShowStory(s => !s)}
          >
            Story
          </button>
          <button className="btn btn-small" onClick={resetFlags}>Reset All</button>
          <button className="btn btn-small" onClick={() => setOpen(false)}>Close</button>
        </div>
      </div>

      {showStory ? (
        <div className="story-presets">
          <div className="section-label">Story Presets</div>
          {STORY_PRESETS.map(preset => {
            const isApplied = Object.entries(preset.flags).every(([k, v]) => (flags[k] ?? 0) === v);
            return (
              <div key={preset.label} className="story-preset-row">
                <div className="story-preset-info">
                  <span className="story-preset-label">{preset.label}</span>
                  <span className="story-preset-flags">
                    {Object.entries(preset.flags).map(([k, v]) => `${k}=${v}`).join(', ')}
                  </span>
                </div>
                <button
                  className={`btn btn-tiny ${isApplied ? 'btn-active' : ''}`}
                  onClick={() => {
                    if (isApplied) {
                      Object.keys(preset.flags).forEach(k => setFlag(k, 0));
                    } else {
                      Object.entries(preset.flags).forEach(([k, v]) => setFlag(k, v));
                    }
                  }}
                >
                  {isApplied ? 'Clear' : 'Apply'}
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <>
      <div className="flag-scope-toggle">
        {selectedNpc?.flags ? (
          <>
            <button className={`btn btn-tiny ${!showAll ? 'btn-active' : ''}`} onClick={() => setShowAll(false)}>
              {selectedNpc.npc} ({npcFlagNames.length})
            </button>
            <button className={`btn btn-tiny ${showAll ? 'btn-active' : ''}`} onClick={() => setShowAll(true)}>
              All ({allFlagNames.length})
            </button>
          </>
        ) : (
          <span className="scope-label">All flags ({allFlagNames.length})</span>
        )}
      </div>

      <input
        type="text"
        className="search-input"
        placeholder="Search flags..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {activeFlags.length > 0 && (
        <div className="active-flags">
          <div className="section-label">Active ({activeFlags.length})</div>
          {activeFlags.map(([name, val]) => {
            const info = flagIndex.get(name);
            const meta = flagMeta[name];
            const note = FLAG_NOTES[name];
            return (
              <div key={name} className="flag-row active">
                <div className="flag-info">
                  <code className="flag-name" title={note}>{name}{note ? ' ✂' : ''}</code>
                  <span className="flag-value">= {val}</span>
                  {info && info.readers.length > 0 && (
                    <span className="flag-npcs" title={info.readers.join(', ')}>
                      {info.readers.length} NPC{info.readers.length > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {meta ? (
                  <input
                    type="number"
                    className="flag-number-input"
                    min={0}
                    max={meta.max}
                    value={val}
                    onChange={e => setFlag(name, Math.min(meta.max, Math.max(0, Number(e.target.value) || 0)))}
                    title={`${meta.bits}-bit flag (0–${meta.max})`}
                  />
                ) : (
                  <button className="btn btn-tiny" onClick={() => setFlag(name, 0)}>Clear</button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="all-flags">
        <div className="section-label">
          {scopedToNpc ? `${selectedNpc.npc}'s Flags` : 'All Flags'} ({filtered.length})
        </div>
        {filtered.map(name => {
          const val = flags[name] ?? 0;
          const info = flagIndex.get(name);
          if (!info) return null;
          const meta = flagMeta[name];
          const note = FLAG_NOTES[name];
          return (
              <div key={name} className={`flag-row ${val ? 'active' : ''}`}>
              <div className="flag-info">
                <code className="flag-name" title={note}>{name}{note ? ' ✂' : ''}</code>
                {val !== 0 && <span className="flag-value">= {val}</span>}
                <span className="flag-npcs" title={`Readers: ${info.readers.join(', ')}\nWriters: ${info.writers.join(', ')}`}>
                  R:{info.readers.length} W:{info.writers.length}
                </span>
              </div>
              {meta ? (
                <input
                  type="number"
                  className="flag-number-input"
                  min={0}
                  max={meta.max}
                  value={val}
                  onChange={e => setFlag(name, Math.min(meta.max, Math.max(0, Number(e.target.value) || 0)))}
                  title={`${meta.bits}-bit flag (0–${meta.max})`}
                />
              ) : (
                <button className="btn btn-tiny" onClick={() => setFlag(name, val ? 0 : 1)}>
                  {val ? 'Clear' : 'Set'}
                </button>
              )}
            </div>
          );
        })}
      </div>
        </>
      )}
    </div>
  );
}
