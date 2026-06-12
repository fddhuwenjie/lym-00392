"""PDF writer - serializes PDF objects to valid PDF files."""

from __future__ import annotations

import zlib
import struct
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


class PDFWriter:
    """Writes PDF objects to a valid PDF file with correct xref and object numbering."""

    def __init__(self):
        self._objects: List[Any] = []
        self._obj_map: Dict[Any, int] = {}
        self._next_obj_num: int = 1
        self._output = bytearray()
        self._obj_offsets: Dict[int, int] = {}

    def add_object(self, obj: Any) -> int:
        """Add an object and return its new object number.

        Objects are deduplicated: if the same object is added twice,
        it gets the same number.
        """
        if id(obj) in self._obj_map:
            return self._obj_map[id(obj)]

        obj_num = self._next_obj_num
        self._objects.append((obj_num, obj))
        self._obj_map[id(obj)] = obj_num
        self._next_obj_num += 1
        return obj_num

    def get_ref(self, obj: Any) -> Optional[PDFIndirectRef]:
        """Get an indirect reference to an object if it's been added."""
        if id(obj) in self._obj_map:
            return PDFIndirectRef(obj_num=self._obj_map[id(obj)], gen_num=0)
        return None

    def _serialize_value(self, value: Any) -> bytes:
        """Serialize a single PDF value to bytes."""
        if value is None or value is PDF_NULL:
            return b'null'
        elif isinstance(value, PDFIndirectRef):
            return f"{value.obj_num} {value.gen_num} R".encode('latin-1')
        elif isinstance(value, PDFBoolean):
            return b'true' if value.value else b'false'
        elif isinstance(value, bool):
            return b'true' if value else b'false'
        elif isinstance(value, PDFName):
            name_str = str(value)
            if not name_str.startswith('/'):
                name_str = '/' + name_str
            return name_str.encode('latin-1')
        elif isinstance(value, PDFString):
            return self._serialize_string(str(value))
        elif isinstance(value, str):
            return self._serialize_string(value)
        elif isinstance(value, PDFNumber):
            if float(value) == int(value):
                return str(int(value)).encode('latin-1')
            return str(float(value)).encode('latin-1')
        elif isinstance(value, int):
            return str(value).encode('latin-1')
        elif isinstance(value, float):
            return str(value).encode('latin-1')
        elif isinstance(value, PDFStream):
            return self._serialize_stream(value)
        elif isinstance(value, (dict, PDFDict)):
            return self._serialize_dict(value)
        elif isinstance(value, (list, PDFArray)):
            return self._serialize_array(value)
        else:
            return str(value).encode('latin-1')

    def _serialize_string(self, s: str) -> bytes:
        """Serialize a string, choosing literal or hex format based on content."""
        try:
            encoded = s.encode('latin-1')
            needs_hex = any(b < 0x20 or b > 0x7E or b in b'()\\' for b in encoded)
            if needs_hex:
                return b'<' + encoded.hex().upper().encode('latin-1') + b'>'
            else:
                escaped = encoded.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')
                return b'(' + escaped + b')'
        except UnicodeEncodeError:
            utf16 = b'\xfe\xff' + s.encode('utf-16-be')
            return b'<' + utf16.hex().upper().encode('latin-1') + b'>'

    def _serialize_dict(self, d: Union[dict, PDFDict]) -> bytes:
        """Serialize a dictionary to << ... >> format."""
        parts = [b'<<']
        for key, value in d.items():
            key_str = str(key)
            if not key_str.startswith('/'):
                key_str = '/' + key_str
            parts.append(key_str.encode('latin-1'))
            parts.append(b' ')
            parts.append(self._serialize_value(value))
            parts.append(b'\n')
        parts.append(b'>>')
        return b''.join(parts)

    def _serialize_array(self, arr: Union[list, PDFArray]) -> bytes:
        """Serialize an array to [ ... ] format."""
        parts = [b'[']
        for i, item in enumerate(arr):
            if i > 0:
                parts.append(b' ')
            parts.append(self._serialize_value(item))
        parts.append(b']')
        return b''.join(parts)

    def _serialize_stream(self, stream: PDFStream) -> bytes:
        """Serialize a stream (dictionary + data)."""
        dict_copy = dict(stream.dict_data)
        data = stream.data

        if 'Filter' in dict_copy:
            pass
        else:
            pass

        dict_copy['Length'] = len(data)

        result = bytearray()
        result.extend(self._serialize_value(dict_copy))
        result.extend(b'\nstream\n')
        result.extend(data)
        result.extend(b'\nendstream')
        return bytes(result)

    def _write_object(self, obj_num: int, obj: Any):
        """Write a single indirect object to output."""
        self._obj_offsets[obj_num] = len(self._output)
        header = f"{obj_num} 0 obj\n".encode('latin-1')
        self._output += header
        self._output += self._serialize_value(obj)
        self._output += b'\nendobj\n'

    def write(self, root_ref: PDFIndirectRef, info_ref: Optional[PDFIndirectRef] = None) -> bytes:
        """Write all objects and return the complete PDF bytes.

        Args:
            root_ref: Reference to the Catalog object
            info_ref: Optional reference to the Info dictionary

        Returns:
            Complete PDF file as bytes
        """
        self._output = bytearray()
        self._obj_offsets = {}

        self._output += b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"

        for obj_num, obj in self._objects:
            self._write_object(obj_num, obj)

        self._write_xref_table(root_ref, info_ref)

        return bytes(self._output)

    def _write_xref_table(self, root_ref: PDFIndirectRef, info_ref: Optional[PDFIndirectRef]):
        """Write the cross-reference table and trailer."""
        max_obj_num = max(self._obj_offsets.keys()) if self._obj_offsets else 0
        size = max_obj_num + 1

        xref_offset = len(self._output)

        self._output += b"xref\n"
        self._output += f"0 {size}\n".encode('latin-1')

        self._output += b"0000000000 65535 f \n"

        for obj_num in range(1, size):
            if obj_num in self._obj_offsets:
                offset = self._obj_offsets[obj_num]
                self._output += f"{offset:010d} 00000 n \n".encode('latin-1')
            else:
                self._output += b"0000000000 00001 f \n"

        self._output += b"trailer\n"
        self._output += b"<<\n"
        self._output += f"/Size {size}\n".encode('latin-1')
        self._output += f"/Root {root_ref.obj_num} {root_ref.gen_num} R\n".encode('latin-1')
        if info_ref is not None:
            self._output += f"/Info {info_ref.obj_num} {info_ref.gen_num} R\n".encode('latin-1')
        self._output += b">>\n"

        self._output += b"startxref\n"
        self._output += f"{xref_offset}\n".encode('latin-1')
        self._output += b"%%EOF\n"


class PDFObjectCopier:
    """Copies objects from a source PDFDocument to a PDFWriter, remapping references."""

    def __init__(self, source_doc, writer: PDFWriter):
        self.source_doc = source_doc
        self.writer = writer
        self._ref_map: Dict[Tuple[int, int], int] = {}

    def copy_object(self, ref: Union[PDFIndirectRef, int]) -> Any:
        """Copy an object (and its dependencies) from source to writer.

        Returns the new indirect reference to the copied object.
        """
        if isinstance(ref, PDFIndirectRef):
            src_key = (ref.obj_num, ref.gen_num)
        else:
            src_key = (int(ref), 0)

        if src_key in self._ref_map:
            return PDFIndirectRef(obj_num=self._ref_map[src_key], gen_num=0)

        src_obj = self.source_doc.get_object(ref)

        if src_obj is PDF_NULL:
            return PDF_NULL

        copied = self._copy_value(src_obj)

        new_obj_num = self.writer.add_object(copied)
        self._ref_map[src_key] = new_obj_num

        return PDFIndirectRef(obj_num=new_obj_num, gen_num=0)

    def _copy_value(self, value: Any) -> Any:
        """Recursively copy a value, resolving and remapping references."""
        if isinstance(value, PDFIndirectRef):
            return self.copy_object(value)
        elif isinstance(value, PDFStream):
            new_dict = self._copy_dict(value.dict_data)
            return PDFStream(dict_data=new_dict, data=bytes(value.data))
        elif isinstance(value, (dict, PDFDict)):
            return self._copy_dict(value)
        elif isinstance(value, (list, PDFArray)):
            return self._copy_array(value)
        elif isinstance(value, PDFBoolean):
            return PDF_TRUE if value.value else PDF_FALSE
        elif isinstance(value, PDFName):
            return PDFName(str(value))
        elif isinstance(value, PDFString):
            return PDFString(str(value))
        elif isinstance(value, PDFNumber):
            if float(value) == int(value):
                return PDFNumber(int(value))
            return PDFNumber(float(value))
        elif value is PDF_NULL or value is None:
            return PDF_NULL
        else:
            return value

    def _copy_dict(self, d: Union[dict, PDFDict]) -> PDFDict:
        """Copy a dictionary, recursively copying values."""
        result = PDFDict()
        for key, value in d.items():
            result[str(key)] = self._copy_value(value)
        return result

    def _copy_array(self, arr: Union[list, PDFArray]) -> PDFArray:
        """Copy an array, recursively copying values."""
        result = PDFArray()
        for item in arr:
            result.append(self._copy_value(item))
        return result
