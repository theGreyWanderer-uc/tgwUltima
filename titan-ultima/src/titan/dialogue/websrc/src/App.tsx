import { useEffect, useState } from 'react';
import { useWorldState } from './store';
import { loadAllNpcs, loadFlagMetadata } from './data';
import { NPCSidebar } from './NPCSidebar';
import { DialoguePlayer } from './DialoguePlayer';
import { FlagInspector } from './FlagInspector';

export function App() {
  const { loadNpcs, setFlagMeta, interactiveNpcs } = useWorldState();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([loadAllNpcs(), loadFlagMetadata()])
      .then(([npcs, meta]) => {
        loadNpcs(npcs);
        setFlagMeta(meta);
        setLoading(false);
      })
      .catch(err => {
        setError(String(err));
        setLoading(false);
      });
  }, [loadNpcs, setFlagMeta]);

  if (loading) {
    return <div className="loading">Loading NPC data...</div>;
  }

  if (error) {
    return (
      <div className="loading error">
        <h2>Failed to load data</h2>
        <p>{error}</p>
        <p className="hint">
          Make sure the JSON files are in <code>public/data/</code> with a{' '}
          <code>manifest.json</code>. Run the build script to generate them.
        </p>
      </div>
    );
  }

  const npcCount = interactiveNpcs.filter(n => n.hasDialogue).length;
  const objCount = interactiveNpcs.filter(
    n => !n.hasDialogue && Object.values(n.functions).some(f => f.type === 'look' || f.type === 'shop')
  ).length;
  const utilCount = interactiveNpcs.filter(
    n => !n.hasDialogue && !Object.values(n.functions).some(f => f.type === 'look' || f.type === 'shop')
  ).length;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Ultima VIII — Dialogue Viewer</h1>
        <span className="header-stats">{npcCount} NPCs, {objCount} objects, {utilCount} util loaded</span>
        <FlagInspector />
      </header>
      <div className="app-body">
        <NPCSidebar />
        <main className="main-panel">
          <DialoguePlayer />
        </main>
      </div>
    </div>
  );
}
