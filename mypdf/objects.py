"""PDF object type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


class PDFObject:
    """Base class for PDF objects."""
    pass


@dataclass
class PDFIndirectRef:
    """Reference to an indirect object (obj_num gen_num R)."""
    obj_num: int
    gen_num: int


@dataclass
class PDFStream:
    """PDF stream object with dictionary and data."""
    dict_data: Dict[str, Any] = field(default_factory=dict)
    data: bytes = b""


class PDFArray(list, PDFObject):
    """PDF array object."""
    pass


class PDFDict(dict, PDFObject):
    """PDF dictionary object."""
    pass


class PDFName(str, PDFObject):
    """PDF name object (starts with /)."""
    pass


class PDFString(str, PDFObject):
    """PDF string object (literal or hex)."""
    pass


class PDFNumber(float, PDFObject):
    """PDF number object (integer or real)."""
    pass


class PDFBoolean(PDFObject):
    """PDF boolean object."""
    def __init__(self, value: bool):
        self.value = value

    def __bool__(self) -> bool:
        return self.value

    def __repr__(self) -> str:
        return "true" if self.value else "false"


class PDFNull(PDFObject):
    """PDF null object."""
    def __repr__(self) -> str:
        return "null"


PDF_NULL = PDFNull()
PDF_TRUE = PDFBoolean(True)
PDF_FALSE = PDFBoolean(False)
