"""Content stream parser - handles text extraction from PDF content streams."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .objects import PDFArray, PDFDict, PDFIndirectRef, PDFName, PDFString, PDFStream
from .cmap import CMapParser


class ContentStreamParser:
    """Parses PDF content streams and extracts text."""

    def __init__(self, document):
        self.document = document
        self.fonts: Dict[str, Dict[str, Any]] = {}
        self.current_font: Optional[str] = None
        self.text_stack: List[str] = []
        self.current_line: List[str] = []
        self.lines: List[str] = []
        self.text_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.text_line_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.last_y: Optional[float] = None
        self.line_height: float = 12.0

    def extract_text(self, page: Dict[str, Any]) -> str:
        """Extract text from a page."""
        self.fonts = {}
        self.current_font = None
        self.text_stack = []
        self.current_line = []
        self.lines = []
        self.text_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.text_line_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.last_y = None

        self._load_page_fonts(page)

        contents = page.get('Contents')
        if contents is None:
            return ''

        content_data = self._get_content_stream(contents)
        if not content_data:
            return ''

        self._parse_content_stream(content_data)
        self._flush_line()

        return '\n'.join(self.lines)

    def _load_page_fonts(self, page: Dict[str, Any]):
        """Load fonts from the page resource dictionary."""
        resources = page.get('Resources')
        if resources is None:
            return

        if isinstance(resources, PDFIndirectRef):
            resources = self.document.resolve(resources)

        if not isinstance(resources, (dict, PDFDict)):
            return

        fonts = resources.get('Font')
        if fonts is None:
            return

        if isinstance(fonts, PDFIndirectRef):
            fonts = self.document.resolve(fonts)

        if not isinstance(fonts, (dict, PDFDict)):
            return

        for font_name, font_ref in fonts.items():
            font_name_str = str(font_name).lstrip('/')
            font_obj = self.document.resolve(font_ref)

            if isinstance(font_obj, (dict, PDFDict)):
                self.fonts[font_name_str] = self._process_font(font_obj)

    def _process_font(self, font_obj: Dict[str, Any]) -> Dict[str, Any]:
        """Process a font object and extract mapping information."""
        font_info: Dict[str, Any] = {
            'type': str(font_obj.get('Subtype', '')).lstrip('/'),
            'encoding': None,
            'to_unicode': None,
            'base_font': str(font_obj.get('BaseFont', '')).lstrip('/'),
        }

        encoding = font_obj.get('Encoding')
        if encoding is not None:
            if isinstance(encoding, PDFName):
                font_info['encoding'] = str(encoding).lstrip('/')
            elif isinstance(encoding, (dict, PDFDict)):
                base_enc = encoding.get('BaseEncoding')
                if isinstance(base_enc, PDFName):
                    font_info['encoding'] = str(base_enc).lstrip('/')
                font_info['encoding_dict'] = encoding

        to_unicode = font_obj.get('ToUnicode')
        if to_unicode is not None:
            if isinstance(to_unicode, PDFIndirectRef):
                to_unicode = self.document.resolve(to_unicode)
            if isinstance(to_unicode, PDFStream):
                stream_data = self.document.decode_stream(to_unicode)
                font_info['to_unicode'] = CMapParser.from_stream(stream_data)

        if font_info['type'] == 'Type0':
            desc_fonts = font_obj.get('DescendantFonts')
            if isinstance(desc_fonts, (list, PDFArray)) and len(desc_fonts) > 0:
                cid_font = self.document.resolve(desc_fonts[0])
                if isinstance(cid_font, (dict, PDFDict)):
                    cid_to_unicode = cid_font.get('ToUnicode')
                    if cid_to_unicode is not None and font_info['to_unicode'] is None:
                        if isinstance(cid_to_unicode, PDFIndirectRef):
                            cid_to_unicode = self.document.resolve(cid_to_unicode)
                        if isinstance(cid_to_unicode, PDFStream):
                            stream_data = self.document.decode_stream(cid_to_unicode)
                            font_info['to_unicode'] = CMapParser.from_stream(stream_data)

        return font_info

    def _get_content_stream(self, contents: Any) -> bytes:
        """Get the content stream data, handling arrays of streams."""
        if isinstance(contents, PDFIndirectRef):
            contents = self.document.resolve(contents)

        if isinstance(contents, PDFStream):
            return self.document.decode_stream(contents)
        elif isinstance(contents, (list, PDFArray)):
            all_data = []
            for item in contents:
                stream = self.document.resolve(item)
                if isinstance(stream, PDFStream):
                    all_data.append(self.document.decode_stream(stream))
            return b' '.join(all_data)

        return b''

    def _parse_content_stream(self, data: bytes):
        """Parse a content stream and extract text."""
        tokens: List[Any] = []
        pos = 0

        while pos < len(data):
            while pos < len(data) and data[pos:pos + 1] in b' \t\n\r\f':
                pos += 1

            if pos >= len(data):
                break

            b = data[pos:pos + 1]

            if b == b'%':
                while pos < len(data) and data[pos:pos + 1] != b'\n':
                    pos += 1
                continue

            if b == b'(':
                string_data, pos = self._parse_literal_string(data, pos)
                tokens.append(PDFString(string_data.decode('latin-1', errors='replace')))
                continue

            if b == b'[':
                pos += 1
                tokens.append('[')
                continue

            if b == b']':
                pos += 1
                tokens.append(']')
                continue

            if b == b'/':
                pos += 1
                start = pos
                while pos < len(data):
                    c = data[pos:pos + 1]
                    if c in b' \t\n\r\f[]()<>{}%/':
                        break
                    pos += 1
                name = data[start:pos].decode('latin-1')
                tokens.append(PDFName(name))
                continue

            start = pos
            while pos < len(data):
                c = data[pos:pos + 1]
                if c in b' \t\n\r\f[]()<>{}%/':
                    break
                pos += 1

            token_str = data[start:pos].decode('latin-1')
            if token_str:
                try:
                    if '.' in token_str:
                        tokens.append(float(token_str))
                    else:
                        tokens.append(int(token_str))
                except ValueError:
                    tokens.append(token_str)

        i = 0
        while i < len(tokens):
            token = tokens[i]

            if isinstance(token, str) and not isinstance(token, (PDFName, PDFString)):
                op = token
                self._execute_operator(op, tokens, i)
                i += 1
            else:
                i += 1

    def _parse_literal_string(self, data: bytes, pos: int) -> Tuple[str, int]:
        """Parse a literal string from data starting at pos."""
        result = []
        depth = 1
        pos += 1

        while pos < len(data):
            b = data[pos:pos + 1]

            if b == b'\\':
                pos += 1
                if pos >= len(data):
                    break
                next_b = data[pos:pos + 1]
                if next_b == b'n':
                    result.append(b'\n')
                elif next_b == b'r':
                    result.append(b'\r')
                elif next_b == b't':
                    result.append(b'\t')
                elif next_b == b'b':
                    result.append(b'\b')
                elif next_b == b'f':
                    result.append(b'\f')
                elif next_b == b'\\':
                    result.append(b'\\')
                elif next_b == b'(':
                    result.append(b'(')
                elif next_b == b')':
                    result.append(b')')
                else:
                    result.append(next_b)
                pos += 1
                continue

            if b == b'(':
                depth += 1
                result.append(b)
                pos += 1
            elif b == b')':
                depth -= 1
                if depth == 0:
                    pos += 1
                    break
                result.append(b)
                pos += 1
            else:
                result.append(b)
                pos += 1

        return b''.join(result), pos

    def _execute_operator(self, op: str, tokens: List[Any], pos: int):
        """Execute a content stream operator."""
        if op == 'BT':
            self.text_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            self.text_line_matrix = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        elif op == 'ET':
            self._flush_line()
        elif op == 'Tj':
            if pos >= 1 and isinstance(tokens[pos - 1], (PDFString, str)):
                text_str = str(tokens[pos - 1])
                self._show_text(text_str)
        elif op == "TJ":
            if pos >= 1:
                arg = tokens[pos - 1]
                if isinstance(arg, list) or hasattr(arg, '__iter__'):
                    self._show_text_array(list(arg))
        elif op == 'Td':
            if pos >= 2:
                tx = float(tokens[pos - 2])
                ty = float(tokens[pos - 1])
                self._text_move(tx, ty)
        elif op == 'TD':
            if pos >= 2:
                tx = float(tokens[pos - 2])
                ty = float(tokens[pos - 1])
                self._flush_line()
                self.line_height = abs(ty)
                self._text_move(tx, ty)
        elif op == 'Tm':
            if pos >= 6:
                a = float(tokens[pos - 6])
                b = float(tokens[pos - 5])
                c = float(tokens[pos - 4])
                d = float(tokens[pos - 3])
                e = float(tokens[pos - 2])
                f = float(tokens[pos - 1])
                self.text_matrix = [a, b, c, d, e, f]
                self.text_line_matrix = [a, b, c, d, e, f]
        elif op == 'T*':
            self._flush_line()
            self._text_move(0, -self.line_height)
        elif op == 'Tf':
            if pos >= 2:
                font_name = str(tokens[pos - 2]).lstrip('/') if hasattr(tokens[pos - 2], 'lstrip') else str(tokens[pos - 2])
                size = float(tokens[pos - 1])
                self.current_font = font_name
                self.line_height = size
        elif op == "T'":
            if pos >= 1 and isinstance(tokens[pos - 1], (PDFString, str)):
                self._flush_line()
                self._text_move(0, -self.line_height)
                self._show_text(str(tokens[pos - 1]))
        elif op == 'T"':
            if pos >= 3 and isinstance(tokens[pos - 3], (PDFString, str)):
                self._flush_line()
                aw = float(tokens[pos - 2])
                ac = float(tokens[pos - 1])
                self._text_move(0, -self.line_height)
                self._show_text(str(tokens[pos - 3]))

    def _show_text(self, text_str: str):
        """Show text string, applying font encoding."""
        decoded = self._decode_text(text_str)
        if decoded:
            self.current_line.append(decoded)

    def _show_text_array(self, array: List[Any]):
        """Show text from array (interleaved strings and numbers)."""
        for item in array:
            if isinstance(item, (PDFString, str)):
                decoded = self._decode_text(str(item))
                if decoded:
                    self.current_line.append(decoded)
            elif isinstance(item, (int, float)):
                pass

    def _decode_text(self, text_str: str) -> str:
        """Decode a text string using the current font's encoding."""
        if self.current_font is None or self.current_font not in self.fonts:
            return text_str

        font_info = self.fonts[self.current_font]

        if font_info.get('to_unicode') is not None:
            try:
                raw_bytes = text_str.encode('latin-1')
                return font_info['to_unicode'].decode(raw_bytes)
            except Exception:
                pass

        encoding = font_info.get('encoding', '')
        if encoding == 'Identity-H' or encoding == 'Identity-V':
            try:
                raw_bytes = text_str.encode('latin-1')
                if len(raw_bytes) % 2 == 0:
                    chars = []
                    for i in range(0, len(raw_bytes), 2):
                        code = (raw_bytes[i] << 8) | raw_bytes[i + 1]
                        if font_info.get('to_unicode'):
                            pass
                        else:
                            try:
                                chars.append(chr(code))
                            except (ValueError, OverflowError):
                                chars.append('?')
                    return ''.join(chars)
            except Exception:
                pass

        if encoding == 'WinAnsiEncoding':
            try:
                return text_str.encode('latin-1').decode('cp1252', errors='replace')
            except Exception:
                pass
        elif encoding == 'MacRomanEncoding':
            try:
                return text_str.encode('latin-1').decode('mac-roman', errors='replace')
            except Exception:
                pass

        return text_str

    def _text_move(self, tx: float, ty: float):
        """Move text position relative to current line start."""
        self.text_line_matrix[4] += tx
        self.text_line_matrix[5] += ty
        self.text_matrix = list(self.text_line_matrix)

        current_y = self.text_matrix[5]

        if self.last_y is not None and abs(current_y - self.last_y) > 1.0:
            self._flush_line()

        self.last_y = current_y

    def _flush_line(self):
        """Flush the current line to the result."""
        if self.current_line:
            line_text = ''.join(self.current_line)
            if line_text.strip():
                self.lines.append(line_text)
            self.current_line = []
