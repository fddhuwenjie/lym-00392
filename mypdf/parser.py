"""Core PDF parser - handles xref, objects, streams, and basic structure."""

from __future__ import annotations

import zlib
from typing import Any, Dict, List, Optional, Tuple, Union

from .objects import (
    PDFArray,
    PDFBoolean,
    PDFDict,
    PDFIndirectRef,
    PDFName,
    PDF_NULL,
    PDFNumber,
    PDFStream,
    PDFString,
    PDF_TRUE,
    PDF_FALSE,
)


class PDFParseError(Exception):
    """Raised when PDF parsing fails."""
    pass


class PDFEncryptedError(PDFParseError):
    """Raised when PDF is encrypted."""
    pass


class PDFTokenizer:
    """Tokenizes PDF content."""

    WHITE_SPACE = b' \t\n\r\f\x00'
    DELIMITERS = b'<>()[]{}/%'

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.length = len(data)

    def skip_whitespace(self):
        while self.pos < self.length and self.data[self.pos:self.pos + 1] in self.WHITE_SPACE:
            self.pos += 1

    def skip_comment(self):
        if self.pos < self.length and self.data[self.pos:self.pos + 1] == b'%':
            while self.pos < self.length and self.data[self.pos:self.pos + 1] != b'\n':
                self.pos += 1

    def skip_whitespace_and_comments(self):
        while self.pos < self.length:
            old_pos = self.pos
            self.skip_whitespace()
            self.skip_comment()
            if self.pos == old_pos:
                break

    def peek_byte(self) -> bytes:
        if self.pos >= self.length:
            return b''
        return self.data[self.pos:self.pos + 1]

    def read_byte(self) -> bytes:
        if self.pos >= self.length:
            raise PDFParseError("Unexpected end of data")
        b = self.data[self.pos:self.pos + 1]
        self.pos += 1
        return b

    def next_token(self) -> Optional[str]:
        """Get the next token as a string, or None if EOF."""
        self.skip_whitespace_and_comments()

        if self.pos >= self.length:
            return None

        b = self.peek_byte()

        if b == b'<':
            self.read_byte()
            if self.peek_byte() == b'<':
                self.read_byte()
                return '<<'
            return '<'
        elif b == b'>':
            self.read_byte()
            if self.peek_byte() == b'>':
                self.read_byte()
                return '>>'
            return '>'
        elif b == b'/':
            return self._parse_name_token()
        elif b in b'()[]{}':
            self.read_byte()
            return b.decode('latin-1')

        if b == b'%':
            self.skip_comment()
            return self.next_token()

        start = self.pos
        while self.pos < self.length:
            b = self.data[self.pos:self.pos + 1]
            if b in self.WHITE_SPACE or b in self.DELIMITERS:
                break
            self.pos += 1

        if start == self.pos:
            return None

        return self.data[start:self.pos].decode('latin-1')

    def _parse_name_token(self) -> str:
        """Parse a PDF name token starting with /."""
        start = self.pos
        self.pos += 1

        while self.pos < self.length:
            b = self.data[self.pos:self.pos + 1]
            if b in self.WHITE_SPACE or b in self.DELIMITERS:
                break
            self.pos += 1

        return self.data[start:self.pos].decode('latin-1')


class PDFParser:
    """Parses PDF objects from tokenized data."""

    def __init__(self, data: bytes):
        self.data = data
        self.tokenizer = PDFTokenizer(data)

    def parse_object(self) -> Any:
        """Parse a single PDF object."""
        token = self.tokenizer.next_token()
        if token is None:
            raise PDFParseError("Unexpected end of data while parsing object")

        if self._is_number(token):
            return self._parse_number_or_reference(token)

        return self.parse_object_from_token(token)

    def _parse_number_or_reference(self, first_token: str) -> Any:
        """Parse a number, or an indirect reference (obj_num gen_num R)."""
        first_num = float(first_token) if '.' in first_token else int(first_token)

        saved_pos = self.tokenizer.pos

        second_token = self.tokenizer.next_token()
        if second_token is None or not self._is_number(second_token):
            self.tokenizer.pos = saved_pos
            return self._parse_number(first_token)

        second_num = float(second_token) if '.' in second_token else int(second_token)

        third_token = self.tokenizer.next_token()
        if third_token != 'R':
            self.tokenizer.pos = saved_pos
            return self._parse_number(first_token)

        if isinstance(first_num, float) or isinstance(second_num, float):
            self.tokenizer.pos = saved_pos
            return self._parse_number(first_token)

        return PDFIndirectRef(obj_num=int(first_num), gen_num=int(second_num))

    def parse_object_from_token(self, token: str) -> Any:
        """Parse an object given the first token."""
        if token == '<<':
            return self.parse_dict()
        elif token == '[':
            return self.parse_array()
        elif token == '(':
            return self.parse_literal_string()
        elif token == '<':
            return self.parse_hex_string()
        elif token.startswith('/'):
            return self.parse_name(token)
        elif token == 'true':
            return PDF_TRUE
        elif token == 'false':
            return PDF_FALSE
        elif token == 'null':
            return PDF_NULL
        elif self._is_number(token):
            return self._parse_number(token)
        else:
            return token

    def _is_number(self, token: str) -> bool:
        if token in ('+', '-', '.'):
            return False
        try:
            float(token)
            return True
        except ValueError:
            return False

    def _parse_number(self, token: str) -> PDFNumber:
        try:
            if '.' in token:
                return PDFNumber(float(token))
            return PDFNumber(int(token))
        except ValueError:
            raise PDFParseError(f"Invalid number: {token}")

    def parse_dict(self) -> PDFDict:
        """Parse a PDF dictionary << ... >>."""
        result = PDFDict()

        while True:
            token = self.tokenizer.next_token()
            if token is None:
                raise PDFParseError("Unterminated dictionary")
            if token == '>>':
                break
            if not token.startswith('/'):
                raise PDFParseError(f"Expected name key in dictionary, got: {token}")

            key = self.parse_name(token)
            value = self.parse_object()
            result[str(key)] = value

        next_token = self.tokenizer.next_token()
        if next_token == 'stream':
            return self._parse_stream_body(result)

        if next_token is not None:
            self.tokenizer.pos -= len(next_token.encode('latin-1'))
            self._skip_back_whitespace()

        return result

    def _skip_back_whitespace(self):
        while self.tokenizer.pos > 0:
            b = self.tokenizer.data[self.tokenizer.pos - 1:self.tokenizer.pos]
            if b in PDFTokenizer.WHITE_SPACE:
                self.tokenizer.pos -= 1
            else:
                break

    def _parse_stream_body(self, dict_data: PDFDict) -> PDFStream:
        """Parse the body of a stream after 'stream' keyword."""
        self.tokenizer.skip_whitespace()
        b = self.tokenizer.peek_byte()
        if b == b'\r':
            self.tokenizer.read_byte()
            if self.tokenizer.peek_byte() == b'\n':
                self.tokenizer.read_byte()
        elif b == b'\n':
            self.tokenizer.read_byte()

        length = dict_data.get('Length')
        if length is None:
            raise PDFParseError("Stream missing Length entry")

        if isinstance(length, PDFIndirectRef):
            length = self._resolve_indirect_length(length)

        length = int(length)
        stream_data = self.tokenizer.data[self.tokenizer.pos:self.tokenizer.pos + length]
        self.tokenizer.pos += length

        endstream_token = self.tokenizer.next_token()
        if endstream_token != 'endstream':
            pass

        endobj_token = self.tokenizer.next_token()
        if endobj_token and endobj_token != 'endobj':
            pass

        return PDFStream(dict_data=dict_data, data=stream_data)

    def _resolve_indirect_length(self, ref: PDFIndirectRef) -> int:
        raise PDFParseError("Indirect Length reference requires full document context")

    def parse_array(self) -> PDFArray:
        """Parse a PDF array [ ... ]."""
        result = PDFArray()

        while True:
            saved_pos = self.tokenizer.pos
            token = self.tokenizer.next_token()
            if token is None:
                raise PDFParseError("Unterminated array")
            if token == ']':
                break
            self.tokenizer.pos = saved_pos
            result.append(self.parse_object())

        return result

    def parse_literal_string(self) -> PDFString:
        """Parse a literal string ( ... )."""
        result = []
        depth = 1
        escaped = False

        while self.tokenizer.pos < self.tokenizer.length:
            b = self.tokenizer.read_byte()

            if escaped:
                if b == b'n':
                    result.append(b'\n')
                elif b == b'r':
                    result.append(b'\r')
                elif b == b't':
                    result.append(b'\t')
                elif b == b'b':
                    result.append(b'\b')
                elif b == b'f':
                    result.append(b'\f')
                elif b == b'\\':
                    result.append(b'\\')
                elif b == b'(':
                    result.append(b'(')
                elif b == b')':
                    result.append(b')')
                elif b in b'\r\n':
                    if b == b'\r' and self.tokenizer.peek_byte() == b'\n':
                        self.tokenizer.read_byte()
                else:
                    result.append(b)
                escaped = False
                continue

            if b == b'\\':
                escaped = True
                continue

            if b == b'(':
                depth += 1
                result.append(b)
            elif b == b')':
                depth -= 1
                if depth == 0:
                    break
                result.append(b)
            else:
                result.append(b)

        if depth != 0:
            raise PDFParseError("Unterminated literal string")

        raw = b''.join(result)
        return self._decode_string(raw)

    def parse_hex_string(self) -> PDFString:
        """Parse a hexadecimal string < ... >."""
        hex_chars = []
        hex_digits = b'0123456789abcdefABCDEF'

        while self.tokenizer.pos < self.tokenizer.length:
            b = self.tokenizer.read_byte()
            if b == b'>':
                break
            if b in PDFTokenizer.WHITE_SPACE:
                continue
            if b not in hex_digits:
                raise PDFParseError(f"Invalid hex character: {b!r}")
            hex_chars.append(b.decode('latin-1'))

        if len(hex_chars) % 2 != 0:
            hex_chars.append('0')

        hex_str = ''.join(hex_chars)
        try:
            raw = bytes.fromhex(hex_str)
        except ValueError:
            raise PDFParseError(f"Invalid hex string: {hex_str}")

        return self._decode_string(raw)

    def _decode_string(self, raw: bytes) -> PDFString:
        """Decode raw string bytes, detecting UTF-16 BOM."""
        if raw.startswith(b'\xfe\xff'):
            try:
                return PDFString(raw.decode('utf-16-be'))
            except UnicodeDecodeError:
                pass
        elif raw.startswith(b'\xff\xfe'):
            try:
                return PDFString(raw.decode('utf-16-le'))
            except UnicodeDecodeError:
                pass

        try:
            return PDFString(raw.decode('utf-8'))
        except UnicodeDecodeError:
            return PDFString(raw.decode('latin-1', errors='replace'))

    def parse_name(self, token: str) -> PDFName:
        """Parse a PDF name from a token (starts with /)."""
        name_part = token[1:]
        raw = name_part.encode('latin-1')

        name_bytes = []
        i = 0
        while i < len(raw):
            if raw[i:i + 1] == b'#':
                if i + 2 >= len(raw):
                    raise PDFParseError("Incomplete # escape in name")
                hex_bytes = raw[i + 1:i + 3]
                try:
                    name_bytes.append(bytes([int(hex_bytes, 16)]))
                except ValueError:
                    raise PDFParseError(f"Invalid # escape in name: #{hex_bytes.decode()}")
                i += 3
            else:
                name_bytes.append(raw[i:i + 1])
                i += 1

        return PDFName(b''.join(name_bytes).decode('latin-1'))


class PDFDocument:
    """Represents a parsed PDF document."""

    def __init__(self, data: bytes):
        self.data = data
        self.objects: Dict[Tuple[int, int], Any] = {}
        self.trailer: Dict[str, Any] = {}
        self.xref: Dict[int, Tuple[int, int, str]] = {}
        self._parser = PDFParser(data)
        self._parse()

    def _parse(self):
        """Parse the entire PDF document."""
        if not self.data.startswith(b'%PDF-'):
            raise PDFParseError("Not a valid PDF file (missing %PDF- header)")

        self._parse_xref()
        self._load_all_objects()

        if 'Encrypt' in self.trailer:
            raise PDFEncryptedError("PDF is password protected")

    def _parse_xref(self):
        """Parse the cross-reference table."""
        startxref_pos = self._find_startxref()

        self.xref = {}
        self.trailer = {}

        self._parse_xref_section(startxref_pos)

    def _find_startxref(self) -> int:
        """Find the startxref position from end of file."""
        eof_marker = b'%%EOF'
        eof_pos = self.data.rfind(eof_marker)
        if eof_pos == -1:
            raise PDFParseError("Missing %%EOF marker")

        startxref_marker = b'startxref'
        search_start = max(0, eof_pos - 200)
        search_area = self.data[search_start:eof_pos]

        marker_pos = search_area.rfind(startxref_marker)
        if marker_pos == -1:
            raise PDFParseError("Missing startxref marker")

        num_start = search_start + marker_pos + len(startxref_marker)
        num_str = self.data[num_start:eof_pos].strip()

        try:
            return int(num_str.split()[0])
        except (ValueError, IndexError):
            raise PDFParseError("Invalid startxref offset")

    def _parse_xref_section(self, offset: int):
        """Parse an xref section starting at offset."""
        self._parser.tokenizer.pos = offset
        token = self._parser.tokenizer.next_token()

        if token == 'xref':
            self._parse_xref_table()
        elif token.isdigit() if token else False:
            first_obj_num = int(token)
            num_entries_tok = self._parser.tokenizer.next_token()
            obj_tok = self._parser.tokenizer.next_token()

            if obj_tok == 'obj':
                stream_obj = self._parse_indirect_object_body(first_obj_num, 0)
                if isinstance(stream_obj, PDFStream):
                    self._parse_xref_stream(stream_obj)
                else:
                    raise PDFParseError("Expected xref stream")
            else:
                raise PDFParseError(f"Expected 'obj' after xref header, got: {obj_tok}")
        else:
            raise PDFParseError(f"Expected xref table or stream at offset {offset}")

    def _parse_xref_table(self):
        """Parse a standard xref table."""
        while True:
            self._parser.tokenizer.skip_whitespace_and_comments()
            if self._parser.tokenizer.peek_byte() == b'':
                break

            next_char = self._parser.tokenizer.data[self._parser.tokenizer.pos:self._parser.tokenizer.pos + 1]

            if next_char == b't':
                break

            obj_num_tok = self._parser.tokenizer.next_token()
            if obj_num_tok is None:
                break

            try:
                obj_num = int(obj_num_tok)
            except ValueError:
                self._parser.tokenizer.pos -= len(obj_num_tok.encode('latin-1'))
                break

            count_tok = self._parser.tokenizer.next_token()
            if count_tok is None:
                break

            try:
                count = int(count_tok)
            except ValueError:
                raise PDFParseError(f"Invalid xref entry count: {count_tok}")

            for i in range(count):
                offset_tok = self._parser.tokenizer.next_token()
                gen_tok = self._parser.tokenizer.next_token()
                type_tok = self._parser.tokenizer.next_token()

                if offset_tok is None or gen_tok is None or type_tok is None:
                    raise PDFParseError("Incomplete xref entry")

                try:
                    offset = int(offset_tok)
                    gen = int(gen_tok)
                except ValueError:
                    raise PDFParseError("Invalid xref entry numbers")

                self.xref[obj_num + i] = (offset, gen, type_tok)

        trailer_tok = self._parser.tokenizer.next_token()
        if trailer_tok != 'trailer':
            raise PDFParseError(f"Expected 'trailer', got: {trailer_tok}")

        trailer_dict = self._parser.parse_object()
        if not isinstance(trailer_dict, (dict, PDFDict)):
            raise PDFParseError(f"Expected trailer dictionary, got: {type(trailer_dict)}")
        self._merge_trailer(trailer_dict)

        if 'Prev' in trailer_dict:
            prev_offset = int(trailer_dict['Prev'])
            self._parse_xref_section(prev_offset)

    def _parse_xref_stream(self, stream: PDFStream):
        """Parse a cross-reference stream (ObjStm style xref)."""
        self.trailer = stream.dict_data

        if 'W' not in stream.dict_data:
            raise PDFParseError("XRef stream missing /W entry")

        w = stream.dict_data['W']
        if not isinstance(w, (list, PDFArray)) or len(w) != 3:
            raise PDFParseError("Invalid /W entry in xref stream")

        type_width = int(w[0])
        offset_width = int(w[1])
        gen_width = int(w[2])

        size = int(stream.dict_data.get('Size', 0))
        index = stream.dict_data.get('Index', [0, size])
        if not isinstance(index, (list, PDFArray)):
            index = [0, size]

        decoded_data = self._decode_stream_data(stream)

        entry_size = type_width + offset_width + gen_width
        pos = 0

        for i in range(0, len(index), 2):
            start_obj = int(index[i])
            count = int(index[i + 1]) if i + 1 < len(index) else size

            for j in range(count):
                if pos + entry_size > len(decoded_data):
                    break

                entry_data = decoded_data[pos:pos + entry_size]
                pos += entry_size

                if type_width > 0:
                    type_val = self._bytes_to_int(entry_data[0:type_width])
                else:
                    type_val = 1

                offset_val = self._bytes_to_int(entry_data[type_width:type_width + offset_width])
                gen_val = self._bytes_to_int(entry_data[type_width + offset_width:entry_size])

                obj_num = start_obj + j

                if type_val == 0:
                    entry_type = 'f'
                elif type_val == 1:
                    entry_type = 'n'
                elif type_val == 2:
                    entry_type = 's'
                else:
                    entry_type = 'n'

                self.xref[obj_num] = (offset_val, gen_val, entry_type)

        self._merge_trailer(stream.dict_data)

        if 'Prev' in stream.dict_data:
            prev_offset = int(stream.dict_data['Prev'])
            self._parse_xref_section(prev_offset)

    def _bytes_to_int(self, data: bytes) -> int:
        """Convert big-endian bytes to integer."""
        result = 0
        for b in data:
            result = (result << 8) | b
        return result

    def _merge_trailer(self, new_trailer: Dict[str, Any]):
        """Merge a trailer dict into the main trailer (newer values win)."""
        for key, value in new_trailer.items():
            if key not in self.trailer:
                self.trailer[key] = value

    def _load_all_objects(self):
        """Load all indirect objects from the xref table."""
        for obj_num, (offset, gen, entry_type) in list(self.xref.items()):
            if entry_type == 'n':
                try:
                    obj = self.load_object(obj_num)
                    self.objects[(obj_num, gen)] = obj
                except Exception:
                    pass

    def load_object(self, obj_num: int) -> Any:
        """Load a specific indirect object by number."""
        if obj_num not in self.xref:
            raise PDFParseError(f"Object {obj_num} not found in xref")

        offset, gen, entry_type = self.xref[obj_num]

        if entry_type == 'f':
            return PDF_NULL
        elif entry_type == 's':
            return self._load_object_from_stream(obj_num, offset, gen)
        elif entry_type == 'n':
            pass
        else:
            return PDF_NULL

        self._parser.tokenizer.pos = offset

        obj_num_tok = self._parser.tokenizer.next_token()
        gen_tok = self._parser.tokenizer.next_token()
        obj_tok = self._parser.tokenizer.next_token()

        if obj_num_tok is None or gen_tok is None or obj_tok is None:
            raise PDFParseError(f"Invalid object header at offset {offset}")

        try:
            parsed_obj_num = int(obj_num_tok)
            parsed_gen = int(gen_tok)
        except ValueError:
            raise PDFParseError(f"Invalid object header at offset {offset}")

        if obj_tok != 'obj':
            raise PDFParseError(f"Expected 'obj' keyword, got: {obj_tok}")

        obj = self._parse_indirect_object_body(parsed_obj_num, parsed_gen)
        return obj

    def _load_object_from_stream(self, obj_num: int, stream_obj_num: int, index_in_stream: int) -> Any:
        """Load an object from an object stream (ObjStm)."""
        stream_obj = self.get_object(stream_obj_num)

        if not isinstance(stream_obj, PDFStream):
            raise PDFParseError(f"Object {stream_obj_num} is not a stream")

        stream_type = stream_obj.dict_data.get('Type')
        if isinstance(stream_type, PDFName):
            stream_type = str(stream_type)
        if str(stream_type).lstrip('/') != 'ObjStm':
            raise PDFParseError(f"Object {stream_obj_num} is not an ObjStm")

        num_objects = int(stream_obj.dict_data.get('N', 0))
        first_offset = int(stream_obj.dict_data.get('First', 0))

        decoded_data = self._decode_stream_data(stream_obj)

        offsets = []
        pos = 0
        for i in range(num_objects):
            while pos < len(decoded_data) and decoded_data[pos:pos+1] in b' \t\n\r':
                pos += 1

            obj_num_start = pos
            while pos < len(decoded_data) and decoded_data[pos:pos+1] not in b' \t\n\r':
                pos += 1
            obj_num_in_stream = int(decoded_data[obj_num_start:pos])

            while pos < len(decoded_data) and decoded_data[pos:pos+1] in b' \t\n\r':
                pos += 1

            offset_start = pos
            while pos < len(decoded_data) and decoded_data[pos:pos+1] not in b' \t\n\r':
                pos += 1
            obj_offset = int(decoded_data[offset_start:pos])

            offsets.append((obj_num_in_stream, first_offset + obj_offset))

        target_offset = None
        for onum, ooffset in offsets:
            if onum == obj_num:
                target_offset = ooffset
                break

        if target_offset is None:
            raise PDFParseError(f"Object {obj_num} not found in object stream {stream_obj_num}")

        next_offset = len(decoded_data)
        for onum, ooffset in offsets:
            if ooffset > target_offset and ooffset < next_offset:
                next_offset = ooffset

        obj_data = decoded_data[target_offset:next_offset]

        temp_parser = PDFParser(obj_data)
        obj = temp_parser.parse_object()

        return obj

    def _parse_indirect_object_body(self, obj_num: int, gen_num: int) -> Any:
        """Parse the body of an indirect object (after 'obj' keyword)."""
        obj = self._parser.parse_object()

        if isinstance(obj, PDFStream):
            pass
        else:
            endobj_tok = self._parser.tokenizer.next_token()
            if endobj_tok and endobj_tok != 'endobj':
                pass

        return obj

    def get_object(self, ref: Union[PDFIndirectRef, int]) -> Any:
        """Get an object by reference or number."""
        if isinstance(ref, PDFIndirectRef):
            obj_num = ref.obj_num
            gen_num = ref.gen_num
        else:
            obj_num = int(ref)
            gen_num = 0

        key = (obj_num, gen_num)
        if key in self.objects:
            return self.objects[key]

        try:
            obj = self.load_object(obj_num)
            self.objects[key] = obj
            return obj
        except Exception:
            return PDF_NULL

    def resolve(self, obj: Any) -> Any:
        """Resolve indirect references recursively."""
        if isinstance(obj, PDFIndirectRef):
            resolved = self.get_object(obj)
            return self.resolve(resolved)
        return obj

    def decode_stream(self, stream: PDFStream) -> bytes:
        """Decode a stream based on its filters."""
        return self._decode_stream_data(stream)

    def _decode_stream_data(self, stream: PDFStream) -> bytes:
        """Decode stream data, applying filters."""
        data = stream.data
        filters = stream.dict_data.get('Filter', [])

        if not isinstance(filters, (list, PDFArray)):
            filters = [filters]

        for filter_name in filters:
            if isinstance(filter_name, PDFName):
                filter_str = str(filter_name)
            else:
                filter_str = str(filter_name)

            if filter_str == 'FlateDecode' or filter_str == 'Fl':
                data = self._decode_flate(data, stream.dict_data)
            elif filter_str in ('ASCIIHexDecode', 'AHx', 'ASCII85Decode', 'A85',
                                'LZWDecode', 'LZW', 'RunLengthDecode', 'RL',
                                'CCITTFaxDecode', 'CCF', 'JBIG2Decode',
                                'DCTDecode', 'DCT', 'JPXDecode', 'Crypt'):
                pass
            else:
                pass

        return data

    def _decode_flate(self, data: bytes, params: Dict[str, Any]) -> bytes:
        """Decode Flate-compressed data."""
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompress(data, -15)
            except zlib.error as e:
                raise PDFParseError(f"Flate decode error: {e}")

    def resolve_page_nodes(self) -> List[Dict[str, Any]]:
        """Resolve all pages by traversing the Pages tree."""
        pages = []
        root_ref = self.trailer.get('Root')
        if root_ref is None:
            return pages

        catalog = self.resolve(root_ref)
        if not isinstance(catalog, (dict, PDFDict)):
            return pages

        pages_ref = catalog.get('Pages')
        if pages_ref is None:
            return pages

        self._traverse_pages_node(pages_ref, pages)
        return pages

    def _traverse_pages_node(self, node_ref: Any, pages: List[Dict[str, Any]]):
        """Recursively traverse the Pages tree."""
        node = self.resolve(node_ref)
        if not isinstance(node, (dict, PDFDict)):
            return

        node_type = str(node.get('Type', '')) if 'Type' in node else ''

        if node_type == '/Pages' or 'Kids' in node:
            kids = node.get('Kids', [])
            if isinstance(kids, (list, PDFArray)):
                for kid in kids:
                    self._traverse_pages_node(kid, pages)
        elif node_type == '/Page' or ('Contents' in node and 'MediaBox' in node):
            pages.append(node)
        elif 'Kids' in node:
            kids = node.get('Kids', [])
            if isinstance(kids, (list, PDFArray)):
                for kid in kids:
                    self._traverse_pages_node(kid, pages)
        elif node_type == '/Page':
            pages.append(node)

    def get_page_count(self) -> int:
        """Get total number of pages."""
        pages = self.resolve_page_nodes()
        return len(pages)

    def get_info(self) -> Dict[str, str]:
        """Get document metadata."""
        info = {}
        info_ref = self.trailer.get('Info')
        if info_ref is None:
            return info

        info_dict = self.resolve(info_ref)
        if not isinstance(info_dict, (dict, PDFDict)):
            return info

        for key, value in info_dict.items():
            key_str = str(key).lstrip('/')
            resolved = self.resolve(value)
            info[key_str] = str(resolved) if resolved is not None else ''

        return info


def parse_pdf(filepath: str) -> PDFDocument:
    """Parse a PDF file and return a PDFDocument."""
    with open(filepath, 'rb') as f:
        data = f.read()
    return PDFDocument(data)
