"""Generate various test PDFs for testing the parser."""

import zlib
import os


def generate_simple_pdf(filepath: str, text_lines=None):
    """Generate a simple PDF with text."""
    if text_lines is None:
        text_lines = ["Hello, World!", "This is a test PDF.", "Second line of text."]

    content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
    y_pos = 0
    for line in text_lines:
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        content_lines.append(f"({escaped}) Tj")
        content_lines.append("0 -20 Td")
        y_pos -= 20
    content_lines.append("ET")

    content = '\n'.join(content_lines).encode('latin-1')
    compressed_content = zlib.compress(content)

    output = bytearray()
    output += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}

    obj_offsets[1] = len(output)
    output += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    obj_offsets[2] = len(output)
    output += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"

    obj_offsets[3] = len(output)
    output += b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"

    obj_offsets[4] = len(output)
    output += f"4 0 obj\n<< /Length {len(compressed_content)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
    output += compressed_content
    output += b"\nendstream\nendobj\n"

    obj_offsets[5] = len(output)
    output += b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n"

    obj_offsets[6] = len(output)
    output += b"6 0 obj\n<< /Title (Test PDF) /Author (Test Author) /Creator (mypdf test) >>\nendobj\n"

    xref_offset = len(output)
    output += b"xref\n"
    output += f"0 {len(obj_offsets) + 1}\n".encode('latin-1')
    output += b"0000000000 65535 f \n"
    for obj_num in sorted(obj_offsets.keys()):
        output += f"{obj_offsets[obj_num]:010d} 00000 n \n".encode('latin-1')

    output += b"trailer\n"
    output += f"<< /Size {len(obj_offsets) + 1} /Root 1 0 R /Info 6 0 R >>\n".encode('latin-1')
    output += b"startxref\n"
    output += f"{xref_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))

    print(f"Generated: {filepath}")


def generate_multipage_pdf(filepath: str, num_pages: int = 3):
    """Generate a multi-page PDF."""
    output = bytearray()
    output += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}
    page_obj_nums = []

    obj_offsets[1] = len(output)
    output += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    font_obj_num = 100
    obj_offsets[font_obj_num] = len(output)
    output += b"100 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n"

    for page_num in range(num_pages):
        page_obj_num = 10 + page_num
        content_obj_num = 20 + page_num
        page_obj_nums.append(page_obj_num)

        text_lines = [f"Page {page_num + 1}", f"This is page {page_num + 1} of {num_pages}", f"Line 3 on page {page_num + 1}"]
        content_lines = ["BT", "/F1 14 Tf", "72 720 Td"]
        for line in text_lines:
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            content_lines.append(f"({escaped}) Tj")
            content_lines.append("0 -24 Td")
        content_lines.append("ET")
        content = '\n'.join(content_lines).encode('latin-1')
        compressed_content = zlib.compress(content)

        obj_offsets[content_obj_num] = len(output)
        output += f"{content_obj_num} 0 obj\n".encode('latin-1')
        output += f"<< /Length {len(compressed_content)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
        output += compressed_content
        output += b"\nendstream\nendobj\n"

        obj_offsets[page_obj_num] = len(output)
        output += f"{page_obj_num} 0 obj\n".encode('latin-1')
        output += f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_obj_num} 0 R /Resources << /Font << /F1 {font_obj_num} 0 R >> >> >>\n".encode('latin-1')
        output += b"endobj\n"

    obj_offsets[2] = len(output)
    kids_str = ' '.join(f"{n} 0 R" for n in page_obj_nums)
    output += f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>\nendobj\n".encode('latin-1')

    info_obj_num = 30
    obj_offsets[info_obj_num] = len(output)
    output += f"{info_obj_num} 0 obj\n<< /Title (Multi-page Test) /Author (Test Author) /Pages {num_pages} >>\nendobj\n".encode('latin-1')

    xref_offset = len(output)
    output += b"xref\n"
    max_obj = max(obj_offsets.keys())
    output += f"0 {max_obj + 1}\n".encode('latin-1')
    output += b"0000000000 65535 f \n"
    for i in range(1, max_obj + 1):
        if i in obj_offsets:
            output += f"{obj_offsets[i]:010d} 00000 n \n".encode('latin-1')
        else:
            output += b"0000000000 65535 f \n"

    output += b"trailer\n"
    output += f"<< /Size {max_obj + 1} /Root 1 0 R /Info {info_obj_num} 0 R >>\n".encode('latin-1')
    output += b"startxref\n"
    output += f"{xref_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))

    print(f"Generated: {filepath} ({num_pages} pages)")


def generate_encrypted_pdf(filepath: str):
    """Generate a PDF marked as encrypted (for testing error handling)."""
    output = bytearray()
    output += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}

    obj_offsets[1] = len(output)
    output += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    obj_offsets[2] = len(output)
    output += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"

    obj_offsets[3] = len(output)
    output += b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"

    obj_offsets[4] = len(output)
    output += b"4 0 obj\n<< /Filter /Standard /V 1 /R 2 /O (fake) /U (fake) /P -1 >>\nendobj\n"

    obj_offsets[5] = len(output)
    output += b"5 0 obj\n<< /Title (Encrypted PDF) /Author (Test) >>\nendobj\n"

    xref_offset = len(output)
    output += b"xref\n"
    output += b"0 6\n"
    output += b"0000000000 65535 f \n"
    for obj_num in sorted(obj_offsets.keys()):
        output += f"{obj_offsets[obj_num]:010d} 00000 n \n".encode('latin-1')

    output += b"trailer\n"
    output += b"<< /Size 6 /Root 1 0 R /Info 5 0 R /Encrypt 4 0 R >>\n"
    output += b"startxref\n"
    output += f"{xref_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))

    print(f"Generated: {filepath} (encrypted test)")


if __name__ == '__main__':
    os.makedirs('test_pdfs', exist_ok=True)
    generate_simple_pdf('test_pdfs/simple.pdf')
    generate_multipage_pdf('test_pdfs/multipage.pdf', 5)
    generate_encrypted_pdf('test_pdfs/encrypted.pdf')
    print("\nAll test PDFs generated in test_pdfs/")
