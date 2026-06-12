"""PDF manipulation - split and merge operations."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

from .objects import (
    PDFArray,
    PDFDict,
    PDFIndirectRef,
    PDFName,
    PDF_NULL,
    PDFNumber,
)
from .parser import PDFDocument, parse_pdf, PDFEncryptedError, PDFParseError
from .writer import PDFWriter, PDFObjectCopier


def parse_page_ranges(page_spec: str, total_pages: int) -> List[Tuple[int, int, str]]:
    """Parse a page specification string like '1-3,5,7-9' into a list of ranges.

    Returns list of (start, end, label) tuples, where pages are 0-indexed.
    Labels are like 'p1-3', 'p5', 'p7-9'.
    """
    ranges = []

    if not page_spec.strip():
        raise ValueError("Page specification cannot be empty")

    parts = page_spec.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            try:
                start_str, end_str = part.split('-', 1)
                start = int(start_str.strip())
                end = int(end_str.strip())
            except ValueError:
                raise ValueError(f"Invalid page range: {part}")

            if start < 1 or end < 1:
                raise ValueError(f"Page numbers must be >= 1: {part}")
            if start > end:
                raise ValueError(f"Start page must be <= end page: {part}")
            if start > total_pages or end > total_pages:
                raise ValueError(
                    f"Page range {part} exceeds document length ({total_pages} pages)"
                )

            ranges.append((start - 1, end - 1, f"p{start}-{end}"))
        else:
            try:
                page = int(part)
            except ValueError:
                raise ValueError(f"Invalid page number: {part}")

            if page < 1:
                raise ValueError(f"Page number must be >= 1: {part}")
            if page > total_pages:
                raise ValueError(
                    f"Page {page} exceeds document length ({total_pages} pages)"
                )

            ranges.append((page - 1, page - 1, f"p{page}"))

    if not ranges:
        raise ValueError("No valid page ranges specified")

    return ranges


def build_new_document(
    source_docs_with_pages: List[Tuple[PDFDocument, List[int]]],
) -> bytes:
    """Build a new PDF document from selected pages of source documents.

    Args:
        source_docs_with_pages: List of (source_doc, page_indices_list) tuples.
            page_indices are 0-indexed.

    Returns:
        Bytes of the new PDF document.
    """
    writer = PDFWriter()

    all_page_refs = []
    info_ref = None

    for source_doc, page_indices in source_docs_with_pages:
        copier = PDFObjectCopier(source_doc, writer)

        pages = source_doc.resolve_page_nodes()

        if info_ref is None and 'Info' in source_doc.trailer:
            try:
                info_ref = copier.copy_object(source_doc.trailer['Info'])
            except Exception:
                pass

        for idx in page_indices:
            if idx < 0 or idx >= len(pages):
                raise ValueError(f"Page index {idx} out of range (0-{len(pages)-1})")

            page_dict = pages[idx]

            page_ref = _copy_page_with_resources(copier, page_dict)
            all_page_refs.append(page_ref)

    if not all_page_refs:
        raise ValueError("No pages selected for output")

    pages_dict = PDFDict()
    pages_dict['Type'] = PDFName('Pages')
    pages_dict['Count'] = PDFNumber(len(all_page_refs))
    pages_dict['Kids'] = PDFArray(all_page_refs)

    pages_obj_num = writer.add_object(pages_dict)
    pages_ref = PDFIndirectRef(obj_num=pages_obj_num, gen_num=0)

    for page_ref in all_page_refs:
        page_obj_id = None
        for obj_num, obj in writer._objects:
            if obj_num == page_ref.obj_num:
                if isinstance(obj, (dict, PDFDict)):
                    obj['Parent'] = pages_ref
                break

    catalog = PDFDict()
    catalog['Type'] = PDFName('Catalog')
    catalog['Pages'] = pages_ref

    catalog_obj_num = writer.add_object(catalog)
    catalog_ref = PDFIndirectRef(obj_num=catalog_obj_num, gen_num=0)

    return writer.write(catalog_ref, info_ref)


def _copy_page_with_resources(
    copier: PDFObjectCopier,
    page_dict: Union[dict, PDFDict],
) -> PDFIndirectRef:
    """Copy a page dictionary and all its dependencies.

    Returns an indirect reference to the copied page.
    """
    new_page = PDFDict()

    page_keys = ['Type', 'MediaBox', 'CropBox', 'BleedBox', 'TrimBox', 'ArtBox',
                 'Rotate', 'UserUnit', 'Annots', 'AA', 'Metadata', 'StructParents',
                 'ID', 'PZ', 'SeparationInfo', 'Tabs']

    for key in page_keys:
        if key in page_dict:
            new_page[key] = copier._copy_value(page_dict[key])

    if 'Resources' in page_dict:
        new_page['Resources'] = copier._copy_value(page_dict['Resources'])

    if 'Contents' in page_dict:
        contents = page_dict['Contents']
        if isinstance(contents, (list, PDFArray)):
            new_contents = PDFArray()
            for item in contents:
                new_contents.append(copier._copy_value(item))
            new_page['Contents'] = new_contents
        else:
            new_page['Contents'] = copier._copy_value(contents)

    new_page['Type'] = PDFName('Page')

    page_obj_num = copier.writer.add_object(new_page)
    return PDFIndirectRef(obj_num=page_obj_num, gen_num=0)


def split_pdf(
    input_path: str,
    page_spec: str,
    output_dir: str,
    output_prefix: str = "",
) -> List[str]:
    """Split a PDF by page ranges.

    Args:
        input_path: Path to the input PDF file.
        page_spec: Page specification like '1-3,5,7-9'.
        output_dir: Directory to write output files.
        output_prefix: Optional prefix for output filenames.

    Returns:
        List of paths to the generated output files.
    """
    doc = parse_pdf(input_path)
    total_pages = doc.get_page_count()

    ranges = parse_page_ranges(page_spec, total_pages)

    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    if output_prefix:
        base_name = output_prefix

    output_files = []

    for start, end, label in ranges:
        page_indices = list(range(start, end + 1))
        pdf_bytes = build_new_document([(doc, page_indices)])

        output_path = os.path.join(output_dir, f"{base_name}_{label}.pdf")
        with open(output_path, 'wb') as f:
            f.write(pdf_bytes)

        output_files.append(output_path)

    return output_files


def merge_pdfs(input_paths: List[str], output_path: str) -> str:
    """Merge multiple PDF files into one.

    Args:
        input_paths: List of paths to input PDF files.
        output_path: Path to the output PDF file.

    Returns:
        Path to the output file.
    """
    if not input_paths:
        raise ValueError("No input files specified for merge")

    source_docs_with_pages = []

    for path in input_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")

        doc = parse_pdf(path)
        page_count = doc.get_page_count()
        page_indices = list(range(page_count))

        source_docs_with_pages.append((doc, page_indices))

    pdf_bytes = build_new_document(source_docs_with_pages)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(pdf_bytes)

    return output_path
