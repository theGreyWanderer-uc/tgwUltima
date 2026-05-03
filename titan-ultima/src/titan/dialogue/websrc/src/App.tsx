import { useEffect, useState } from 'react';
import { useWorldState } from './store';
import { loadAllNpcs, loadFlagMetadata } from './data';
import { NPCSidebar } from './NPCSidebar';
import { DialoguePlayer } from './DialoguePlayer';
import { FlagInspector } from './FlagInspector';

type ThemeId =
  | 'ocean-depths'
  | 'sunset-boulevard'
  | 'forest-canopy'
  | 'modern-minimalist'
  | 'golden-hour'
  | 'arctic-frost'
  | 'desert-rose'
  | 'tech-innovation'
  | 'botanical-garden'
  | 'midnight-galaxy';

const THEME_STORAGE_KEY = 'u8-dialogue-theme';

const THEME_OPTIONS: Array<{ id: ThemeId; label: string }> = [
  { id: 'ocean-depths', label: 'Ocean Depths' },
  { id: 'sunset-boulevard', label: 'Sunset Boulevard' },
  { id: 'forest-canopy', label: 'Forest Canopy' },
  { id: 'modern-minimalist', label: 'Modern Minimalist' },
  { id: 'golden-hour', label: 'Golden Hour' },
  { id: 'arctic-frost', label: 'Arctic Frost' },
  { id: 'desert-rose', label: 'Desert Rose' },
  { id: 'tech-innovation', label: 'Tech Innovation' },
  { id: 'botanical-garden', label: 'Botanical Garden' },
  { id: 'midnight-galaxy', label: 'Midnight Galaxy' }
];

const THEME_PREVIEW: Record<ThemeId, readonly [string, string, string, string]> = {
  'ocean-depths': ['#1a2332', '#2d8b8b', '#a8dadc', '#f1faee'],
  'sunset-boulevard': ['#e76f51', '#f4a261', '#e9c46a', '#264653'],
  'forest-canopy': ['#2d4a2b', '#7d8471', '#a4ac86', '#faf9f6'],
  'modern-minimalist': ['#36454f', '#708090', '#d3d3d3', '#ffffff'],
  'golden-hour': ['#f4a900', '#c1666b', '#d4b896', '#4a403a'],
  'arctic-frost': ['#d4e4f7', '#4a6fa5', '#c0c0c0', '#fafafa'],
  'desert-rose': ['#d4a5a5', '#b87d6d', '#e8d5c4', '#5d2e46'],
  'tech-innovation': ['#0066ff', '#00ffff', '#1e1e1e', '#ffffff'],
  'botanical-garden': ['#4a7c59', '#f9a620', '#b7472a', '#f5f3ed'],
  'midnight-galaxy': ['#2b1e3e', '#4a4e8f', '#a490c2', '#e6e6fa']
};

function getInitialTheme(): ThemeId {
  if (typeof window === 'undefined') return 'golden-hour';
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return THEME_OPTIONS.some(t => t.id === stored) ? (stored as ThemeId) : 'golden-hour';
}

export function App() {
  const { loadNpcs, setFlagMeta, interactiveNpcs } = useWorldState();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<ThemeId>(getInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

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
        <label className="theme-switcher" htmlFor="theme-switcher-select">
          Theme
          <select
            id="theme-switcher-select"
            className="theme-select"
            value={theme}
            onChange={e => setTheme(e.target.value as ThemeId)}
          >
            {THEME_OPTIONS.map(option => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="theme-preview" aria-label="Theme quick select">
          {THEME_OPTIONS.map(option => {
            const isActive = option.id === theme;
            const accent = THEME_PREVIEW[option.id][1];
            return (
              <button
                key={option.id}
                type="button"
                className={`theme-preview-swatch${isActive ? ' active' : ''}`}
                style={{ backgroundColor: accent }}
                onClick={() => setTheme(option.id)}
                aria-label={`Switch to ${option.label}`}
                title={option.label}
              />
            );
          })}
        </div>
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
