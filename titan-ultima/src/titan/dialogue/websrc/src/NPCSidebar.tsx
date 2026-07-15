import { useWorldState } from './store';
import { findTalkFunction, findLookFunction, findShopFunction } from './engine';
import {
  BOOK_CLASS,
  compareObjectEntries,
  isLibrarySource,
  isNpcEntry,
  isObjectEntry,
  isUtilEntry,
} from './npcClassification';
import type { NPCFile } from './types';

export function NPCSidebar() {
  const { interactiveNpcs, selectedNpc, npcSearchQuery, viewFilter, setNpcSearch, setViewFilter, selectNpc } = useWorldState();

  const byCategory = viewFilter === 'npc'
    ? interactiveNpcs.filter(isNpcEntry)
    : viewFilter === 'object'
      ? interactiveNpcs.filter(isObjectEntry)
      : interactiveNpcs.filter(isUtilEntry);

  const filtered = npcSearchQuery
    ? byCategory.filter(n => n.npc.toLowerCase().includes(npcSearchQuery.toLowerCase()))
    : byCategory;

  const sortedFiltered = viewFilter === 'object'
    ? [...filtered].sort(compareObjectEntries)
    : filtered;

  const npcCount = interactiveNpcs.filter(isNpcEntry).length;
  const objCount = interactiveNpcs.filter(isObjectEntry).length;
  const utilCount = interactiveNpcs.filter(isUtilEntry).length;

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
  const hasLibraryTag = isLibrarySource(npc);
  const isBook = npc.npc === BOOK_CLASS;

  const tags: string[] = [];
  if (hasTalk) tags.push('talk');
  if (hasLook) tags.push('look');
  if (hasShop) tags.push('shop');
  if (hasLibraryTag) tags.push('library');
  if (viewFilter === 'util' && hasBehavior) tags.push('behavior');
  if (viewFilter === 'util' && hasUtility) tags.push('utility');

  return (
    <button
      className={`npc-row ${selected ? 'selected' : ''} ${isBook ? 'npc-row-book' : ''}`}
      onClick={() => onSelect(npc)}
    >
      <span className="npc-name">
        {isBook && <span className="npc-leading-icon" aria-hidden="true">📖</span>}
        {npc.npc}
      </span>
      <span className="npc-tags">
        {tags.map(t => <span key={t} className={`tag ${t === 'library' ? 'tag-book' : ''}`}>{t}</span>)}
      </span>
    </button>
  );
}
