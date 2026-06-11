"""High-level text extraction from PDF documents."""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .parser import PDFDocument, PDFEncryptedError, parse_pdf
from .content_stream import ContentStreamParser


class PDFTextExtractor:
    """Extracts text and metadata from PDF documents."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self._doc: Optional[PDFDocument] = None
        self._pages_text: List[str] = []
        self._page_count: int = 0

    def load(self):
        """Load and parse the PDF document."""
        if self._doc is not None:
            return

        self._doc = parse_pdf(self.filepath)
        self._page_count = self._doc.get_page_count()

    @property
    def document(self) -> PDFDocument:
        if self._doc is None:
            self.load()
        return self._doc

    @property
    def page_count(self) -> int:
        if self._doc is None:
            self.load()
        return self._page_count

    def extract_text(self) -> str:
        """Extract text from all pages."""
        if self._pages_text:
            return '\n'.join(self._pages_text)

        self.load()
        pages = self.document.resolve_page_nodes()
        parser = ContentStreamParser(self.document)

        self._pages_text = []
        for page in pages:
            page_text = parser.extract_text(page)
            self._pages_text.append(page_text)

        return '\n'.join(self._pages_text)

    def get_page_text(self, page_num: int) -> str:
        """Get text from a specific page (0-indexed)."""
        if not self._pages_text:
            self.extract_text()

        if 0 <= page_num < len(self._pages_text):
            return self._pages_text[page_num]
        return ''

    def get_info(self) -> Dict[str, str]:
        """Get document metadata."""
        self.load()
        info = self.document.get_info()
        result = {
            'filename': self.filename,
            'filepath': self.filepath,
            'pages': str(self.page_count),
        }

        title = info.get('Title', '')
        author = info.get('Author', '')
        subject = info.get('Subject', '')
        keywords = info.get('Keywords', '')
        creator = info.get('Creator', '')
        producer = info.get('Producer', '')

        if title:
            result['title'] = title
        if author:
            result['author'] = author
        if subject:
            result['subject'] = subject
        if keywords:
            result['keywords'] = keywords
        if creator:
            result['creator'] = creator
        if producer:
            result['producer'] = producer

        return result


def extract_pdf_text(filepath: str) -> str:
    """Extract text from a PDF file."""
    extractor = PDFTextExtractor(filepath)
    return extractor.extract_text()


def get_pdf_info(filepath: str) -> Dict[str, str]:
    """Get PDF metadata."""
    extractor = PDFTextExtractor(filepath)
    return extractor.get_info()
