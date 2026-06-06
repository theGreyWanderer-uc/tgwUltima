import { useWorldState } from './store';
import { findTalkFunction, findLookFunction, findShopFunction } from './engine';
import type { NPCFile } from './types';

const LIBRARY_CLASS_ORDER = ['BASEBOOK', 'BASESCRL', 'GRAVE_NS', 'PLAQUENS', 'KEYONEC', 'PENT', 'NEC1', 'SCROLL1', 'EARTHMAG'];
const LIBRARY_CLASSES = new Set(LIBRARY_CLASS_ORDER);
const LIBRARY_CLASS_RANK = new Map(LIBRARY_CLASS_ORDER.map((name, index) => [name, index]));

export function NPCSidebar() {
  const { interactiveNpcs, selectedNpc, npcSearchQuery, viewFilter, setNpcSearch, setViewFilter, selectNpc } = useWorldState();
  const isLibrarySource = (n: NPCFile) => LIBRARY_CLASSES.has(n.npc);

  const isNpc = (n: NPCFile) => n.hasDialogue;
  const isObject = (n: NPCFile) => !n.hasDialogue && (isLibrarySource(n) || Object.values(n.functions).some(f => f.type === 'look' || f.type === 'shop'));
  const isUtil = (n: NPCFile) => !n.hasDialogue && !isObject(n) && (Object.values(n.functions).some(f => f.type === 'behavior' || f.type === 'utility'));

  const byCategory = viewFilter === 'npc'
    ? interactiveNpcs.filter(isNpc)
    : viewFilter === 'object'
      ? interactiveNpcs.filter(isObject)
      : interactiveNpcs.filter(isUtil);

  const filtered = npcSearchQuery
    ? byCategory.filter(n => n.npc.toLowerCase().includes(npcSearchQuery.toLowerCase()))
    : byCategory;

  const sortedFiltered = viewFilter === 'object'
    ? [...filtered].sort((a, b) => {
      const aRank = LIBRARY_CLASS_RANK.get(a.npc);
      const bRank = LIBRARY_CLASS_RANK.get(b.npc);
      if (aRank !== undefined || bRank !== undefined) {
        if (aRank === undefined) return 1;
        if (bRank === undefined) return -1;
        return aRank - bRank;
      }
      return a.npc.localeCompare(b.npc);
    })
    : filtered;

  const npcCount = interactiveNpcs.filter(isNpc).length;
  const objCount = interactiveNpcs.filter(isObject).length;
  const utilCount = interactiveNpcs.filter(isUtil).length;

  const viewLabel = viewFilter === 'npc' ? 'NPCs' : viewFilter === 'object' ? 'Objects' : 'Util';

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h2>{viewLabel}</h2>
        <span className="badge">{sortedFiltered.length}</span>
      </div>
      <div className="filter-toggle" role="group" aria-label="Sidebar category filters">
        <button
          type="button"
          className={`btn btn-filter ${viewFilter === 'npc' ? 'active' : ''}`}
          onClick={() => setViewFilter('npc')}
          aria-pressed={viewFilter === 'npc'}
          aria-label="Show NPC entries"
        >
          NPCs ({npcCount})
        </button>
        <button
          type="button"
          className={`btn btn-filter ${viewFilter === 'object' ? 'active' : ''}`}
          onClick={() => setViewFilter('object')}
          aria-pressed={viewFilter === 'object'}
          aria-label="Show object entries"
        >
          Objects ({objCount})
        </button>
        <button
          type="button"
          className={`btn btn-filter ${viewFilter === 'util' ? 'active' : ''}`}
          onClick={() => setViewFilter('util')}
          aria-pressed={viewFilter === 'util'}
          aria-label="Show utility entries"
        >
          Util ({utilCount})
        </button>
      </div>
      <input
        name="npc-search"
        id="npc-search"

        type="text"
        className="search-input"
        placeholder={`Search ${viewLabel.toLowerCase()}...`}
        value={npcSearchQuery}
        onChange={e => setNpcSearch(e.target.value)}
      />
      <div className="npc-list">
        {sortedFiltered.map(npc => (
          <NPCRow
            key={npc.npc}
            npc={npc}
            selected={selectedNpc?.npc === npc.npc}
            onSelect={selectNpc}
            viewFilter={viewFilter}
          />
        ))}
        {sortedFiltered.length === 0 && (
          <div className="empty-state">No {viewLabel.toLowerCase()} match your search</div>
        )}
      </div>
    </aside>
  );
}

function NPCRow({
  npc,
  selected,
  onSelect,
  viewFilter,
}: {
  npc: NPCFile;
  selected: boolean;
  onSelect: (n: NPCFile) => void;
  viewFilter: 'npc' | 'object' | 'util';
}) {
  const hasTalk = !!findTalkFunction(npc);
  const hasLook = !!findLookFunction(npc);
  const hasShop = !!findShopFunction(npc);
  const hasBehavior = Object.values(npc.functions).some(f => f.type === 'behavior');
  const hasUtility = Object.values(npc.functions).some(f => f.type === 'utility');
  const isLibrarySource = LIBRARY_CLASSES.has(npc.npc);

  const tags: string[] = [];
  if (hasTalk) tags.push('talk');
  if (hasLook) tags.push('look');
  if (hasShop) tags.push('shop');
  if (isLibrarySource) tags.push('library');
  if (viewFilter === 'util' && hasBehavior) tags.push('behavior');
  if (viewFilter === 'util' && hasUtility) tags.push('utility');

  return (
    <button
      className={`npc-row ${selected ? 'selected' : ''} ${isLibrarySource ? 'npc-row-book' : ''}`}
      onClick={() => onSelect(npc)}
    >
      <span className="npc-name">
        {isLibrarySource && <span className="npc-leading-icon" aria-hidden="true">📖</span>}
        {npc.npc}
      </span>
      <span className="npc-tags">
        {tags.map(t => <span key={t} className={`tag ${t === 'library' ? 'tag-book' : ''}`}>{t}</span>)}
      </span>
    </button>
  );
}
