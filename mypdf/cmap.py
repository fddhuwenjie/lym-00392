"""ToUnicode CMap parser for font character mapping."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .objects import PDFStream, PDFString


class CMapParser:
    """Parses ToUnicode CMap to map character codes to Unicode."""

    def __init__(self):
        self.codespace_ranges: List[Tuple[int, int]] = []
        self.char_map: Dict[int, str] = {}

    @classmethod
    def from_stream(cls, stream_data: bytes) -> 'CMapParser':
        """Parse CMap from stream data bytes."""
        parser = cls()
        parser.parse(stream_data)
        return parser

    def parse(self, data: bytes):
        """Parse the CMap data."""
        text = data.decode('latin-1', errors='replace')

        self._parse_codespace_ranges(text)
        self._parse_bfchar(text)
        self._parse_bfrange(text)

    def _parse_codespace_ranges(self, text: str):
        """Parse begincodespacerange / endcodespacerange sections."""
        pattern = r'begincodespacerange\s+(.*?)\s+endcodespacerange'
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return

        content = match.group(1).strip()
        lines = content.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            hex_pattern = r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>'
            range_match = re.match(hex_pattern, line)
            if range_match:
                start = int(range_match.group(1), 16)
                end = int(range_match.group(2), 16)
                self.codespace_ranges.append((start, end))

    def _parse_bfchar(self, text: str):
        """Parse beginbfchar / endbfchar sections."""
        pattern = r'beginbfchar\s+(.*?)\s+endbfchar'
        for match in re.finditer(pattern, text, re.DOTALL):
            content = match.group(1).strip()
            lines = content.split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                char_pattern = r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>'
                char_match = re.match(char_pattern, line)
                if char_match:
                    src = int(char_match.group(1), 16)
                    dst_hex = char_match.group(2)
                    dst_str = self._hex_to_unicode(dst_hex)
                    self.char_map[src] = dst_str

    def _parse_bfrange(self, text: str):
        """Parse beginbfrange / endbfrange sections."""
        pattern = r'beginbfrange\s+(.*?)\s+endbfrange'
        for match in re.finditer(pattern, text, re.DOTALL):
            content = match.group(1).strip()
            lines = content.split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                range_pattern = r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>'
                range_match = re.match(range_pattern, line)
                if range_match:
                    start = int(range_match.group(1), 16)
                    end = int(range_match.group(2), 16)
                    dst_start_hex = range_match.group(3)
                    dst_start = int(dst_start_hex, 16) if len(dst_start_hex) <= 8 else 0

                    offset = 0
                    for code in range(start, end + 1):
                        dst_code = dst_start + offset
                        dst_str = self._code_to_unicode(dst_code)
                        self.char_map[code] = dst_str
                        offset += 1
                    continue

                array_pattern = r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+\[(.*?)\]'
                array_match = re.match(array_pattern, line)
                if array_match:
                    start = int(array_match.group(1), 16)
                    end = int(array_match.group(2), 16)
                    array_content = array_match.group(3)

                    dst_hexes = re.findall(r'<([0-9A-Fa-f]+)>', array_content)
                    code = start
                    for dst_hex in dst_hexes:
                        if code > end:
                            break
                        dst_str = self._hex_to_unicode(dst_hex)
                        self.char_map[code] = dst_str
                        code += 1

    def _hex_to_unicode(self, hex_str: str) -> str:
        """Convert hex string to Unicode string."""
        try:
            if len(hex_str) == 4:
                code = int(hex_str, 16)
                if 0xD800 <= code <= 0xDBFF:
                    return ''
                return chr(code)
            elif len(hex_str) > 4 and len(hex_str) % 4 == 0:
                chars = []
                for i in range(0, len(hex_str), 4):
                    code = int(hex_str[i:i + 4], 16)
                    chars.append(chr(code))
                return ''.join(chars)
            else:
                code = int(hex_str, 16)
                return chr(code)
        except (ValueError, OverflowError):
            return ''

    def _code_to_unicode(self, code: int) -> str:
        """Convert a code point to Unicode string."""
        try:
            if 0xD800 <= code <= 0xDBFF:
                return ''
            return chr(code)
        except (ValueError, OverflowError):
            return ''

    def decode(self, data: bytes) -> str:
        """Decode byte data using the CMap."""
        result = []
        i = 0

        while i < len(data):
            byte = data[i]
            matched = False

            for start, end in sorted(self.codespace_ranges, key=lambda x: x[1] - x[0], reverse=True):
                num_bytes = 1
                temp = start
                while temp > 0xFF:
                    num_bytes += 1
                    temp >>= 8

                if i + num_bytes > len(data):
                    continue

                code = 0
                for j in range(num_bytes):
                    code = (code << 8) | data[i + j]

                if start <= code <= end:
                    if code in self.char_map:
                        result.append(self.char_map[code])
                    else:
                        result.append('')
                    i += num_bytes
                    matched = True
                    break

            if not matched:
                if byte in self.char_map:
                    result.append(self.char_map[byte])
                else:
                    try:
                        result.append(chr(byte))
                    except (ValueError, OverflowError):
                        result.append('?')
                i += 1

        return ''.join(result)
