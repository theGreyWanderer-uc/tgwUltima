import { useEffect, useMemo, useRef, useState } from 'react';

interface BookEntry {
  quality: number;
  qualityHex: string;
  title: string;
  category: string;
  text: string | null;
  paragraphs?: string[];
  source?: string;
}

interface BooksData {
  itemClass: string;
  totalBooks: number;
  booksWithText: number;
  books: BookEntry[];
}

interface BookPanelProps {
  npcName: string;
  open: boolean;
  onClose: () => void;
}

let cachedBooks: BooksData | null = null;

async function loadBooks(): Promise<BooksData> {
  if (cachedBooks) return cachedBooks;
  const resp = await fetch('./data/books.json');
  if (!resp.ok) {
    throw new Error(`Failed to load books.json: ${resp.status}`);
  }
  cachedBooks = await resp.json();
  return cachedBooks!;
}

export function BookPanel({ npcName, open, onClose }: BookPanelProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [books, setBooks] = useState<BooksData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedBook, setSelectedBook] = useState<BookEntry | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>('All');
  const [search, setSearch] = useState('');
  const contentRef = useRef<HTMLDivElement>(null);

  // Load books data on first open
  useEffect(() => {
    if (open && !books) {
      setLoadError(null);
      loadBooks()
        .then(setBooks)
        .catch((err: unknown) => {
          setLoadError(err instanceof Error ? err.message : String(err));
        });
    }
  }, [open, books]);

  // Sync dialog open/close
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  // Reset selection when reopened
  useEffect(() => {
    if (open) {
      setSelectedBook(null);
      setFilterCategory('All');
      setSearch('');
      setLoadError(null);
    }
  }, [open]);

  // Handle native close (Escape key)
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const h = () => onClose();
    dialog.addEventListener('close', h);
    return () => dialog.removeEventListener('close', h);
  }, [onClose]);

  // Backdrop click
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const h = (e: MouseEvent) => { if (e.target === dialog) onClose(); };
    dialog.addEventListener('click', h);
    return () => dialog.removeEventListener('click', h);
  }, [onClose]);

  // Scroll to top when book changes
  useEffect(() => {
    contentRef.current?.scrollTo(0, 0);
  }, [selectedBook]);

  const categories = useMemo(() => {
    if (!books) return [];
    const cats = [...new Set(books.books.map(b => b.category))];
    return ['All', ...cats.sort()];
  }, [books]);

  const filteredBooks = useMemo(() => {
    if (!books) return [];
    let list = books.books;
    if (filterCategory !== 'All') {
      list = list.filter(b => b.category === filterCategory);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(b =>
        b.title.toLowerCase().includes(q) ||
        (b.text && b.text.toLowerCase().includes(q))
      );
    }
    return list;
  }, [books, filterCategory, search]);

  return (
    <dialog ref={dialogRef} className="book-dialog">
      <div className="book-modal">
        <div className="book-modal-header">
          <h2 className="book-modal-title">
            <span className="book-icon">📖</span>
            {selectedBook ? selectedBook.title : `Library: ${npcName}`}
          </h2>
          <div className="book-modal-header-actions">
            {selectedBook && (
              <button
                className="btn btn-tiny"
                onClick={() => setSelectedBook(null)}
                type="button"
                title="Back to list"
              >
                ← List
              </button>
            )}
            <button className="btn btn-tiny book-close" onClick={onClose} type="button">✕</button>
          </div>
        </div>

        <div className="book-modal-body" ref={contentRef}>
          {loadError ? (
            <p className="book-loading">Failed to load books: {loadError}</p>
          ) : !books ? (
            <p className="book-loading">Loading books…</p>
          ) : selectedBook ? (
            <BookReader book={selectedBook} />
          ) : (
            <>
              <div className="book-toolbar">
                <input
                  type="text"
                  className="book-search"
                  placeholder="Search books…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
                <select
                  className="book-category-select"
                  value={filterCategory}
                  onChange={e => setFilterCategory(e.target.value)}
                >
                  {categories.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div className="book-count">
                {filteredBooks.length} of {books.totalBooks} books
                {books.booksWithText < books.totalBooks &&
                  ` (${books.booksWithText} with readable text)`}
              </div>

              <div className="book-list">
                {filteredBooks.map(book => (
                  <button
                    key={book.quality}
                    className={`book-list-item ${!book.text ? 'book-list-item-empty' : ''}`}
                    onClick={() => book.text ? setSelectedBook(book) : undefined}
                    disabled={!book.text}
                    type="button"
                  >
                    <span className="book-list-title">{book.title}</span>
                    <span className="book-list-meta">
                      <span className="book-list-category">{book.category}</span>
                      <span className="book-list-quality">{book.qualityHex}</span>
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}

function BookReader({ book }: { book: BookEntry }) {
  const paragraphs = book.paragraphs ?? [];
  return (
    <div className="book-reader">
      <div className="book-reader-meta">
        <span className="book-reader-category">{book.category}</span>
        <span className="book-reader-quality">Quality: {book.qualityHex}</span>
        {book.source && <span className="book-reader-source">{book.source}</span>}
      </div>
      <div className="book-reader-content">
        {paragraphs.length > 0 ? (
          paragraphs.map((p, i) => <p key={i}>{p}</p>)
        ) : book.text ? (
          <p>{book.text}</p>
        ) : (
          <p className="book-reader-empty">No text content available for this book.</p>
        )}
      </div>
    </div>
  );
}
