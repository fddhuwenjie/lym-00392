"""Command-line interface for mypdf."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .extractor import PDFTextExtractor, get_pdf_info
from .indexer import PDFIndexer
from .parser import PDFEncryptedError, PDFParseError


def cmd_extract(args):
    """Handle the 'extract' command."""
    filepath = args.file
    output = args.output

    try:
        extractor = PDFTextExtractor(filepath)
        text = extractor.extract_text()

        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"Extracted text saved to {output}")
        else:
            print(text)

    except PDFEncryptedError:
        print(f"Error: PDF is password protected: {filepath}", file=sys.stderr)
        return 1
    except PDFParseError as e:
        print(f"Error parsing PDF: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return 1

    return 0


def cmd_info(args):
    """Handle the 'info' command."""
    filepath = args.file

    try:
        info = get_pdf_info(filepath)

        print(f"Filename: {info.get('filename', 'N/A')}")
        print(f"Path:     {info.get('filepath', 'N/A')}")
        print(f"Pages:    {info.get('pages', 'N/A')}")
        print(f"Title:    {info.get('title', 'N/A')}")
        print(f"Author:   {info.get('author', 'N/A')}")
        if 'subject' in info:
            print(f"Subject:  {info.get('subject', 'N/A')}")
        if 'keywords' in info:
            print(f"Keywords: {info.get('keywords', 'N/A')}")
        if 'creator' in info:
            print(f"Creator:  {info.get('creator', 'N/A')}")
        if 'producer' in info:
            print(f"Producer: {info.get('producer', 'N/A')}")

    except PDFEncryptedError:
        print(f"Error: PDF is password protected: {filepath}", file=sys.stderr)
        return 1
    except PDFParseError as e:
        print(f"Error parsing PDF: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return 1

    return 0


def cmd_index(args):
    """Handle the 'index' command."""
    path = args.path
    db_path = args.db

    indexer = PDFIndexer(db_path)

    try:
        import os
        if os.path.isdir(path):
            results = indexer.index_directory(path, recursive=not args.no_recursive)
            print(f"Indexing complete:")
            print(f"  Total files found: {results['total']}")
            print(f"  Successfully indexed: {results['success']}")
            print(f"  Skipped (encrypted): {results['skipped']}")
            print(f"  Failed: {results['failed']}")
        elif os.path.isfile(path):
            try:
                indexer.index_file(path)
                print(f"Indexed: {path}")
            except PDFEncryptedError:
                print(f"Skipped (password protected): {path}")
                return 1
        else:
            print(f"Error: Path not found: {path}", file=sys.stderr)
            return 1

        doc_count = indexer.get_document_count()
        print(f"Total documents in index: {doc_count}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        indexer.close()

    return 0


def cmd_search(args):
    """Handle the 'search' command."""
    query = args.query
    db_path = args.db
    limit = args.limit

    indexer = PDFIndexer(db_path)

    try:
        results = indexer.search(query, limit=limit)

        if not results:
            print(f"No results found for: {query}")
            return 0

        print(f"Found {len(results)} result(s) for: {query}")
        print()

        for i, result in enumerate(results, 1):
            print(f"  [{i}] {result['filename']}")
            print(f"      Path: {result['filepath']}")
            if result.get('title'):
                print(f"      Title: {result['title']}")
            if result.get('author'):
                print(f"      Author: {result['author']}")
            print(f"      Pages: {result.get('pages', 'N/A')}")

            if result.get('snippets'):
                print(f"      Snippets:")
                for snippet in result['snippets']:
                    snippet_clean = snippet.replace('\n', ' ').replace('\r', '').strip()
                    if len(snippet_clean) > 120:
                        snippet_clean = snippet_clean[:117] + '...'
                    print(f"        - {snippet_clean}")

            print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        indexer.close()

    return 0


def cmd_list(args):
    """Handle the 'list' command."""
    db_path = args.db

    indexer = PDFIndexer(db_path)

    try:
        docs = indexer.list_documents(limit=args.limit)

        if not docs:
            print("No documents in index.")
            return 0

        print(f"Documents in index ({len(docs)}):")
        print()

        for doc in docs:
            print(f"  - {doc['filename']}")
            print(f"    Path: {doc['filepath']}")
            if doc.get('title'):
                print(f"    Title: {doc['title']}")
            print(f"    Pages: {doc.get('pages', 'N/A')}")
            print(f"    Indexed: {doc.get('indexed_at', 'N/A')}")
            print()

        doc_count = indexer.get_document_count()
        print(f"Total: {doc_count} documents")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        indexer.close()

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog='mypdf',
        description='PDF text extraction and search tool'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    extract_parser = subparsers.add_parser('extract', help='Extract text from a PDF')
    extract_parser.add_argument('file', help='PDF file to extract text from')
    extract_parser.add_argument('-o', '--output', help='Output file path (default: stdout)')
    extract_parser.set_defaults(func=cmd_extract)

    info_parser = subparsers.add_parser('info', help='Show PDF metadata')
    info_parser.add_argument('file', help='PDF file to inspect')
    info_parser.set_defaults(func=cmd_info)

    index_parser = subparsers.add_parser('index', help='Index PDF files for search')
    index_parser.add_argument('path', help='PDF file or directory to index')
    index_parser.add_argument('--db', help='Path to index database')
    index_parser.add_argument('--no-recursive', action='store_true',
                              help='Do not recursively index subdirectories')
    index_parser.set_defaults(func=cmd_index)

    search_parser = subparsers.add_parser('search', help='Search indexed PDFs')
    search_parser.add_argument('query', help='Search query (use quotes for phrases)')
    search_parser.add_argument('--db', help='Path to index database')
    search_parser.add_argument('-n', '--limit', type=int, default=20,
                               help='Maximum number of results (default: 20)')
    search_parser.set_defaults(func=cmd_search)

    list_parser = subparsers.add_parser('list', help='List indexed documents')
    list_parser.add_argument('--db', help='Path to index database')
    list_parser.add_argument('-n', '--limit', type=int, default=100,
                             help='Maximum number of documents to list (default: 100)')
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
