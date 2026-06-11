"""PDF indexing with SQLite FTS5."""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional

from .extractor import PDFTextExtractor
from .parser import PDFEncryptedError


DEFAULT_INDEX_PATH = os.path.expanduser('~/.mypdf_index.db')


class PDFIndexer:
    """Indexes PDF files using SQLite FTS5."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_INDEX_PATH
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._initialize_schema()
        return self._conn

    def _initialize_schema(self):
        """Initialize database schema."""
        cursor = self.conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                title TEXT,
                author TEXT,
                pages INTEGER,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts5(
                    content,
                    filepath UNINDEXED,
                    filename UNINDEXED,
                    tokenize = 'unicode61'
                )
            ''')
        except sqlite3.OperationalError as e:
            if 'no such module' in str(e).lower() and 'fts5' in str(e).lower():
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts4(
                        content,
                        filepath,
                        filename
                    )
                ''')
            else:
                raise

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                page_num INTEGER NOT NULL,
                content TEXT,
                FOREIGN KEY (doc_id) REFERENCES documents(id)
            )
        ''')

        self.conn.commit()

    def index_directory(self, dir_path: str, recursive: bool = True) -> Dict[str, int]:
        """Index all PDF files in a directory."""
        dir_path = os.path.abspath(dir_path)

        if not os.path.isdir(dir_path):
            raise ValueError(f"Not a directory: {dir_path}")

        pdf_files = self._find_pdf_files(dir_path, recursive)

        results = {
            'total': len(pdf_files),
            'success': 0,
            'skipped': 0,
            'failed': 0,
        }

        for filepath in pdf_files:
            try:
                self.index_file(filepath)
                results['success'] += 1
            except PDFEncryptedError:
                results['skipped'] += 1
            except Exception as e:
                print(f"Error indexing {filepath}: {e}")
                results['failed'] += 1

        return results

    def _find_pdf_files(self, dir_path: str, recursive: bool) -> List[str]:
        """Find all PDF files in a directory."""
        pdf_files = []

        if recursive:
            for root, dirs, files in os.walk(dir_path):
                for filename in files:
                    if filename.lower().endswith('.pdf'):
                        pdf_files.append(os.path.join(root, filename))
        else:
            for filename in os.listdir(dir_path):
                filepath = os.path.join(dir_path, filename)
                if os.path.isfile(filepath) and filename.lower().endswith('.pdf'):
                    pdf_files.append(filepath)

        return sorted(pdf_files)

    def index_file(self, filepath: str) -> int:
        """Index a single PDF file."""
        filepath = os.path.abspath(filepath)

        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        extractor = PDFTextExtractor(filepath)

        try:
            text = extractor.extract_text()
            info = extractor.get_info()
        except PDFEncryptedError:
            raise

        cursor = self.conn.cursor()

        cursor.execute(
            'SELECT id FROM documents WHERE filepath = ?',
            (filepath,)
        )
        row = cursor.fetchone()

        if row:
            doc_id = row['id']
            cursor.execute('DELETE FROM pdf_fts WHERE filepath = ?', (filepath,))
            cursor.execute('DELETE FROM pages WHERE doc_id = ?', (doc_id,))
            cursor.execute(
                '''UPDATE documents
                   SET title = ?, author = ?, pages = ?, indexed_at = CURRENT_TIMESTAMP
                   WHERE id = ?''',
                (info.get('title'), info.get('author'), int(info.get('pages', 0)), doc_id)
            )
        else:
            cursor.execute(
                '''INSERT INTO documents (filepath, filename, title, author, pages)
                   VALUES (?, ?, ?, ?, ?)''',
                (filepath, os.path.basename(filepath),
                 info.get('title'), info.get('author'),
                 int(info.get('pages', 0)))
            )
            doc_id = cursor.lastrowid

        cursor.execute(
            'INSERT INTO pdf_fts (content, filepath, filename) VALUES (?, ?, ?)',
            (text, filepath, os.path.basename(filepath))
        )

        pages_text = extractor._pages_text
        for page_num, page_content in enumerate(pages_text):
            cursor.execute(
                'INSERT INTO pages (doc_id, page_num, content) VALUES (?, ?, ?)',
                (doc_id, page_num + 1, page_content)
            )

        self.conn.commit()
        return doc_id

    def search(self, query: str, limit: int = 50) -> List[Dict]:
        """Search the index for matching documents."""
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                '''SELECT 
                   pdf_fts.filepath,
                   pdf_fts.filename,
                   pdf_fts.content,
                   documents.title,
                   documents.author,
                   documents.pages,
                   rank
                   FROM pdf_fts
                   LEFT JOIN documents ON pdf_fts.filepath = documents.filepath
                   WHERE pdf_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?''',
                (query, limit)
            )
        except sqlite3.OperationalError:
            cursor.execute(
                '''SELECT 
                   pdf_fts.filepath,
                   pdf_fts.filename,
                   pdf_fts.content,
                   documents.title,
                   documents.author,
                   documents.pages
                   FROM pdf_fts
                   LEFT JOIN documents ON pdf_fts.filepath = documents.filepath
                   WHERE pdf_fts MATCH ?
                   LIMIT ?''',
                (query, limit)
            )

        results = []
        for row in cursor.fetchall():
            result = {
                'filepath': row['filepath'],
                'filename': row['filename'],
                'title': row['title'],
                'author': row['author'],
                'pages': row['pages'],
                'snippets': self._get_snippets(row['content'], query),
            }
            results.append(result)

        return results

    def _get_snippets(self, content: str, query: str, context_chars: int = 50) -> List[str]:
        """Extract snippets from content around query matches."""
        snippets = []
        query_lower = query.lower()
        content_lower = content.lower()

        search_terms = []
        for part in query.replace('"', '').split():
            if part and not part.startswith(('AND', 'OR', 'NOT')):
                search_terms.append(part.lower())

        if not search_terms:
            search_terms = [query_lower]

        positions = []
        for term in search_terms:
            start = 0
            while True:
                pos = content_lower.find(term, start)
                if pos == -1:
                    break
                positions.append(pos)
                start = pos + 1

        positions.sort()

        last_end = -1
        for pos in positions:
            if pos <= last_end:
                continue

            start = max(0, pos - context_chars)
            end = min(len(content), pos + len(query) + context_chars)

            snippet = content[start:end]
            if start > 0:
                snippet = '...' + snippet
            if end < len(content):
                snippet = snippet + '...'

            snippets.append(snippet)
            last_end = end

            if len(snippets) >= 3:
                break

        return snippets

    def get_document_count(self) -> int:
        """Get the number of indexed documents."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM documents')
        return cursor.fetchone()['count']

    def list_documents(self, limit: int = 100) -> List[Dict]:
        """List all indexed documents."""
        cursor = self.conn.cursor()
        cursor.execute(
            '''SELECT filepath, filename, title, author, pages, indexed_at
               FROM documents
               ORDER BY indexed_at DESC
               LIMIT ?''',
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
