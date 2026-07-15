import { useEffect, useMemo, useRef, useState } from 'react';

interface LibraryItem {
  id: string;
  kind: string;
  quality: number | null;
  qualityHex: string;
  slot?: number;
  title: string;
  category: string;
  text: string | null;
  paragraphs?: string[];
  source?: string;
  school?: string;
  details?: Record<string, string | number | string[] | null>;
}

interface LibrarySection {
  id: string;
  title: string;
  description: string;
  icon: string;
  itemClass: string;
  totalItems: number;
  itemsWithText: number;
  itemsWithContent?: number;
  items: LibraryItem[];
}

interface LibraryData {
  schemaVersion: string;
  totalSections: number;
  totalItems: number;
  sections: LibrarySection[];
}

interface LegacyBookEntry {
  quality: number;
  qualityHex: string;
  title: string;
  category: string;
  text: string | null;
  paragraphs?: string[];
  source?: string;
}

interface LegacyBooksData {
  itemClass: string;
  totalBooks: number;
  booksWithText: number;
  books: LegacyBookEntry[];
}

interface BookPanelProps {
  npcName: string;
  open: boolean;
  onClose: () => void;
}

let cachedLibrary: LibraryData | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(item => typeof item === 'string');
}

function isLibraryItem(value: unknown): value is LibraryItem {
  if (!isRecord(value)) return false;
  const details = value.details;
  const validDetails = details === undefined || (isRecord(details) && Object.values(details).every(detail =>
    detail === null
    || typeof detail === 'string'
    || typeof detail === 'number'
    || isStringArray(detail)
  ));
  return typeof value.id === 'string'
    && typeof value.kind === 'string'
    && (typeof value.quality === 'number' || value.quality === null)
    && typeof value.qualityHex === 'string'
    && (value.slot === undefined || typeof value.slot === 'number')
    && typeof value.title === 'string'
    && typeof value.category === 'string'
    && (typeof value.text === 'string' || value.text === null)
    && (value.paragraphs === undefined || isStringArray(value.paragraphs))
    && isOptionalString(value.source)
    && isOptionalString(value.school)
    && validDetails;
}

function isLibrarySection(value: unknown): value is LibrarySection {
  if (!isRecord(value) || !Array.isArray(value.items) || !value.items.every(isLibraryItem)) return false;
  return typeof value.id === 'string'
    && typeof value.title === 'string'
    && typeof value.description === 'string'
    && typeof value.icon === 'string'
    && typeof value.itemClass === 'string'
    && typeof value.totalItems === 'number'
    && value.totalItems === value.items.length
    && typeof value.itemsWithText === 'number'
    && (value.itemsWithContent === undefined || typeof value.itemsWithContent === 'number');
}

function isLibraryData(value: unknown): value is LibraryData {
  if (!isRecord(value) || value.schemaVersion !== '1.1' || !Array.isArray(value.sections)) return false;
  if (!value.sections.every(isLibrarySection)) return false;
  const totalItems = value.sections.reduce((sum, section) => sum + section.totalItems, 0);
  return value.totalSections === value.sections.length && value.totalItems === totalItems;
}

function isLegacyBookEntry(value: unknown): value is LegacyBookEntry {
  if (!isRecord(value)) return false;
  return typeof value.quality === 'number'
    && typeof value.qualityHex === 'string'
    && typeof value.title === 'string'
    && typeof value.category === 'string'
    && (typeof value.text === 'string' || value.text === null)
    && (value.paragraphs === undefined || isStringArray(value.paragraphs))
    && isOptionalString(value.source);
}

function isLegacyBooksData(value: unknown): value is LegacyBooksData {
  if (!isRecord(value) || !Array.isArray(value.books) || !value.books.every(isLegacyBookEntry)) return false;
  return typeof value.itemClass === 'string'
    && typeof value.totalBooks === 'number'
    && value.totalBooks === value.books.length
    && typeof value.booksWithText === 'number';
}

async function loadLibrary(): Promise<LibraryData> {
  if (cachedLibrary) return cachedLibrary;

  const libraryResp = await fetch('./data/library.json');
  let libraryFailure = `HTTP ${libraryResp.status}`;
  if (libraryResp.ok) {
    try {
      const payload: unknown = await libraryResp.json();
      if (isLibraryData(payload)) {
        cachedLibrary = payload;
        return payload;
      }
      libraryFailure = 'invalid or unsupported schema';
    } catch (err: unknown) {
      libraryFailure = `invalid JSON: ${err instanceof Error ? err.message : String(err)}`;
    }
  }

  const booksResp = await fetch('./data/books.json');
  if (!booksResp.ok) {
    throw new Error(`Failed to load library.json (${libraryFailure}) and books.json (HTTP ${booksResp.status})`);
  }
  let booksPayload: unknown;
  try {
    booksPayload = await booksResp.json();
  } catch (err: unknown) {
    throw new Error(`Failed to load library.json (${libraryFailure}) and books.json (invalid JSON: ${err instanceof Error ? err.message : String(err)})`);
  }
  if (!isLegacyBooksData(booksPayload)) {
    throw new Error(`Failed to load library.json (${libraryFailure}) and books.json (invalid schema)`);
  }
  const books = booksPayload;
  const items: LibraryItem[] = books.books.map(book => ({
    ...book,
    id: `book-${book.qualityHex}`,
    kind: 'book',
  }));
  cachedLibrary = {
    schemaVersion: 'legacy-books',
    totalSections: 1,
    totalItems: items.length,
    sections: [{
      id: 'books',
      title: 'Books',
      description: 'Readable books indexed from BASEBOOK quality branches.',
      icon: 'book',
      itemClass: books.itemClass,
      totalItems: books.totalBooks,
      itemsWithText: books.booksWithText,
      itemsWithContent: books.booksWithText,
      items,
    }],
  };
  return cachedLibrary;
}

function iconFor(section: LibrarySection | LibraryItem): string {
  const key = 'icon' in section ? section.icon : section.kind;
  switch (key) {
    case 'scroll': return '📜';
    case 'grave': return '▥';
    case 'plaque': return '▣';
    case 'spell': return '✦';
    default: return '📖';
  }
}

function stringifyDetail(value: string | number | string[] | null): string {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null) return '';
  return String(value);
}

function formatDetailLabel(key: string): string {
  const words = key.replace(/([A-Z])/g, ' $1').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function itemPosition(item: LibraryItem): string {
  if (item.kind === 'spell') return `Slot: ${item.slot ?? item.quality}`;
  return `Quality: ${item.qualityHex}`;
}

function itemPositionShort(item: LibraryItem): string {
  if (item.kind === 'spell') return `Slot ${item.slot ?? item.quality}`;
  return item.qualityHex;
}

export function BookPanel({ npcName, open, onClose }: BookPanelProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [library, setLibrary] = useState<LibraryData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<LibraryItem | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<string>('books');
  const [filterCategory, setFilterCategory] = useState<string>('All');
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (open && !library) {
      setLoadError(null);
      loadLibrary()
        .then(data => {
          setLibrary(data);
          if (!data.sections.some(section => section.id === activeSectionId)) {
            setActiveSectionId(data.sections[0]?.id ?? 'books');
          }
        })
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : String(err));
        });
    }
  }, [open, library, activeSectionId]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (open) {
      setSelectedItem(null);
      setFilterCategory('All');
      setSearch('');
      setLoadError(null);
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const h = () => onClose();
    dialog.addEventListener('close', h);
    return () => dialog.removeEventListener('close', h);
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const h = (e: MouseEvent) => { if (e.target === dialog) onClose(); };
    dialog.addEventListener('click', h);
    return () => dialog.removeEventListener('click', h);
  }, [onClose]);

  useEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [selectedItem, activeSectionId]);

  const activeSection = useMemo(() => {
    if (!library) return null;
    return library.sections.find(section => section.id === activeSectionId) ?? library.sections[0] ?? null;
  }, [library, activeSectionId]);

  const categories = useMemo(() => {
    if (!activeSection) return [];
    const cats = [...new Set(activeSection.items.map(item => item.category))];
    return ['All', ...cats.sort()];
  }, [activeSection]);

  const filteredItems = useMemo(() => {
    if (!activeSection) return [];
    let list = activeSection.items;
    if (filterCategory !== 'All') {
      list = list.filter(item => item.category === filterCategory);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(item => {
        const detailText = item.details
          ? Object.values(item.details).map(stringifyDetail).join(' ')
          : '';
        return item.title.toLowerCase().includes(q)
          || item.category.toLowerCase().includes(q)
          || (item.text ? item.text.toLowerCase().includes(q) : false)
          || detailText.toLowerCase().includes(q);
      });
    }
    return list;
  }, [activeSection, filterCategory, search]);

  const itemsWithContent = activeSection?.itemsWithContent ?? activeSection?.itemsWithText ?? 0;

  const selectSection = (sectionId: string) => {
    setActiveSectionId(sectionId);
    setSelectedItem(null);
    setFilterCategory('All');
    setSearch('');
  };

  const handleSectionKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, sectionIndex: number) => {
    if (!library) return;
    let nextIndex: number | null = null;
    if (event.key === 'ArrowRight') nextIndex = (sectionIndex + 1) % library.sections.length;
    if (event.key === 'ArrowLeft') nextIndex = (sectionIndex - 1 + library.sections.length) % library.sections.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = library.sections.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const nextSection = library.sections[nextIndex];
    selectSection(nextSection.id);
    requestAnimationFrame(() => document.getElementById(`book-section-tab-${nextSection.id}`)?.focus());
  };

  return (
    <dialog ref={dialogRef} className="book-dialog" aria-labelledby="book-dialog-title">
      <div className="book-modal">
        <div className="book-modal-header">
          <h2 id="book-dialog-title" className="book-modal-title">
            <span className="book-icon">{selectedItem ? iconFor(selectedItem) : '📚'}</span>
            {selectedItem ? selectedItem.title : `Library: ${npcName}`}
          </h2>
          <div className="book-modal-header-actions">
            {selectedItem && (
              <button
                className="btn btn-tiny"
                onClick={() => setSelectedItem(null)}
                type="button"
                title="Back to list"
              >
                ← List
              </button>
            )}
            <button
              className="btn btn-tiny book-close"
              onClick={onClose}
              type="button"
              aria-label="Close library"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="book-modal-body" ref={contentRef}>
          {loadError ? (
            <p className="book-loading">Failed to load library: {loadError}</p>
          ) : !library || !activeSection ? (
            <p className="book-loading">Loading library…</p>
          ) : selectedItem ? (
            <LibraryReader item={selectedItem} />
          ) : (
            <>
              <div className="book-section-tabs" role="tablist" aria-label="Library sections">
                {library.sections.map((section, sectionIndex) => (
                  <button
                    key={section.id}
                    id={`book-section-tab-${section.id}`}
                    className={`book-section-tab ${section.id === activeSection.id ? 'active' : ''}`}
                    onClick={() => selectSection(section.id)}
                    onKeyDown={event => handleSectionKeyDown(event, sectionIndex)}
                    type="button"
                    role="tab"
                    aria-selected={section.id === activeSection.id}
                    aria-controls={`book-section-panel-${section.id}`}
                    tabIndex={section.id === activeSection.id ? 0 : -1}
                  >
                    <span aria-hidden="true">{iconFor(section)}</span>
                    <span>{section.title}</span>
                    <span className="book-section-count">{section.totalItems}</span>
                  </button>
                ))}
              </div>

              <div
                id={`book-section-panel-${activeSection.id}`}
                role="tabpanel"
                aria-labelledby={`book-section-tab-${activeSection.id}`}
              >
                <div className="book-toolbar">
                  <input
                    type="text"
                    className="book-search"
                    placeholder={`Search ${activeSection.title.toLowerCase()}…`}
                    aria-label={`Search ${activeSection.title}`}
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                  />
                  <select
                    className="book-category-select"
                    aria-label={`Filter ${activeSection.title} by category`}
                    value={filterCategory}
                    onChange={e => setFilterCategory(e.target.value)}
                  >
                    {categories.map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>

                <div className="book-count">
                  {filteredItems.length} of {activeSection.totalItems} {activeSection.title.toLowerCase()}
                  {itemsWithContent < activeSection.totalItems &&
                    ` (${itemsWithContent} with content)`}
                </div>

                <div className="book-list">
                  {filteredItems.map(item => (
                    <button
                      key={item.id}
                      className={`book-list-item ${!item.text && !item.details ? 'book-list-item-empty' : ''}`}
                      onClick={() => (item.text || item.details) ? setSelectedItem(item) : undefined}
                      disabled={!item.text && !item.details}
                      type="button"
                    >
                      <span className="book-list-title">
                        <span className="book-list-kind" aria-hidden="true">{iconFor(item)}</span>
                        {item.title}
                      </span>
                      <span className="book-list-meta">
                        <span className="book-list-category">{item.category}</span>
                        <span className="book-list-quality">{itemPositionShort(item)}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}

function LibraryReader({ item }: { item: LibraryItem }) {
  const paragraphs = item.paragraphs ?? [];
  const detailEntries = Object.entries(item.details ?? {})
    .filter(([, value]) => stringifyDetail(value).trim().length > 0);

  return (
    <div className="book-reader">
      <div className="book-reader-meta">
        <span className="book-reader-category">{item.category}</span>
        <span className="book-reader-quality">{itemPosition(item)}</span>
        {item.school && <span className="book-reader-source">{item.school}</span>}
        {item.source && <span className="book-reader-source">{item.source}</span>}
      </div>
      {detailEntries.length > 0 && (
        <dl className="book-reader-details">
          {detailEntries.map(([key, value]) => (
            <div key={key} className="book-reader-detail">
              <dt>{formatDetailLabel(key)}</dt>
              <dd>{stringifyDetail(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="book-reader-content">
        {paragraphs.length > 0 ? (
          paragraphs.map((p, i) => <p key={i}>{p}</p>)
        ) : item.text ? (
          <p>{item.text}</p>
        ) : detailEntries.length > 0 ? null : (
          <p className="book-reader-empty">No text content available for this entry.</p>
        )}
      </div>
    </div>
  );
}
