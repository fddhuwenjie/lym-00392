"""Generate realistic test PDFs covering:
1. xref stream (instead of standard xref table)
2. Object streams (ObjStm) with compressed objects
3. Chinese text with embedded ToUnicode CMap (Identity-H encoding)
"""

import zlib
import os
import struct


# ============================================================
# Helper: build a minimal PDF with xref stream (PDF 1.5+)
# ============================================================
def generate_xref_stream_pdf(filepath: str):
    """PDF using xref stream instead of traditional xref table."""
    output = bytearray()
    output += b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}

    # Obj 1: Catalog
    obj_offsets[1] = len(output)
    output += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    # Obj 2: Pages
    obj_offsets[2] = len(output)
    output += b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"

    # Obj 3: Page
    content_stream = ("BT\n/F1 14 Tf\n72 720 Td\n"
                      "(Hello from xref stream PDF!) Tj\n"
                      "0 -24 Td\n"
                      "(This PDF uses compressed xref stream.) Tj\n"
                      "ET").encode('latin-1')
    compressed_content = zlib.compress(content_stream)

    obj_offsets[4] = len(output)
    output += f"4 0 obj\n<< /Length {len(compressed_content)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
    output += compressed_content
    output += b"\nendstream\nendobj\n"

    obj_offsets[3] = len(output)
    output += (b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
               b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n")

    # Obj 5: Font
    obj_offsets[5] = len(output)
    output += b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n"

    # Obj 6: Info
    obj_offsets[6] = len(output)
    output += b"6 0 obj\n<< /Title (XRef Stream Test) /Author (Test Suite) /Creator (mypdf) >>\nendobj\n"

    # ================ Build xref stream (Obj 7) ================
    # /W = [1 3 1] means: type=1 byte, offset=3 bytes, gen=1 byte
    # Collect all objects (including free entry 0 and the xref stream itself)
    all_objs = [0, 1, 2, 3, 4, 5, 6]
    size = 8  # 0..7
    xref_entries = []

    # Entry 0: free
    xref_entries.append((0, 0, 65535))  # type=0 (free)
    # Entry 1-6: normal objects (type=1, offset, gen=0)
    for onum in [1, 2, 3, 4, 5, 6]:
        xref_entries.append((1, obj_offsets[onum], 0))
    # Entry 7: xref stream itself (type=1) - will fill offset after

    xref_stream_obj_num = 7
    xref_stream_offset = len(output)

    # Build xref stream data
    w = [1, 3, 1]  # type_width, offset_width, gen_width
    xref_data = bytearray()
    # Add entry 0
    xref_data += struct.pack('>B', 0)
    xref_data += struct.pack('>I', 0)[1:4]  # 3 bytes
    xref_data += struct.pack('>B', 0xFF)
    # Add entries 1-6
    for onum in [1, 2, 3, 4, 5, 6]:
        xref_data += struct.pack('>B', 1)  # type 1
        xref_data += struct.pack('>I', obj_offsets[onum])[1:4]  # 3 bytes offset
        xref_data += struct.pack('>B', 0)  # gen
    # Add entry 7 (xref stream self-reference)
    xref_data += struct.pack('>B', 1)
    xref_data += struct.pack('>I', xref_stream_offset)[1:4]
    xref_data += struct.pack('>B', 0)

    compressed_xref = zlib.compress(bytes(xref_data))

    # Write xref stream object
    output += f"{xref_stream_obj_num} 0 obj\n".encode('latin-1')
    output += (b"<< /Type /XRef /Size " + str(size).encode('latin-1') +
               b" /W [" + b' '.join(str(x).encode() for x in w) + b"]" +
               b" /Root 1 0 R /Info 6 0 R" +
               b" /Length " + str(len(compressed_xref)).encode('latin-1') +
               b" /Filter /FlateDecode >>\nstream\n")
    output += compressed_xref
    output += b"\nendstream\nendobj\n"

    # startxref points to the xref stream object
    output += b"startxref\n"
    output += f"{xref_stream_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))
    print(f"Generated: {filepath} (xref stream)")


# ============================================================
# Helper: build PDF with Object Streams (ObjStm)
# ============================================================
def generate_objstm_pdf(filepath: str):
    """PDF using object streams (ObjStm) to pack multiple non-stream objects."""
    output = bytearray()
    output += b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}  # only for objects NOT in object streams

    # ---------- Obj 10: Content stream (cannot be in ObjStm) ----------
    content_text = ("BT\n/F1 14 Tf\n72 720 Td\n"
                    "(Hello from ObjStm PDF!) Tj\n"
                    "0 -24 Td\n"
                    "(Catalog, Pages, Page, Font, Info all packed in object streams.) Tj\n"
                    "0 -24 Td\n"
                    "(Xref uses compressed stream.) Tj\n"
                    "ET").encode('latin-1')
    compressed_content = zlib.compress(content_text)

    obj_offsets[10] = len(output)
    output += f"10 0 obj\n<< /Length {len(compressed_content)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
    output += compressed_content
    output += b"\nendstream\nendobj\n"

    # ---------- Now build ObjStm containing objects 1,2,3,5,6 ----------
    # We'll manually create the objects in their uncompressed PDF syntax form.
    # Format inside ObjStm (after First offset):
    #   N pairs of (obj_num, relative_offset) followed by the actual objects in order.

    # Build the raw objects (without obj/endobj headers since those are implicit)
    raw_objs = []

    # Obj 1: Catalog
    raw_objs.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    # Obj 2: Pages
    raw_objs.append((2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"))
    # Obj 3: Page
    raw_objs.append((3, (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                         b"/Contents 10 0 R /Resources << /Font << /F1 5 0 R >> >> >>")))
    # Obj 5: Font
    raw_objs.append((5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"))
    # Obj 6: Info
    raw_objs.append((6, b"<< /Title (ObjStm Test) /Author (Test Suite) /Pages 1 >>"))

    # Build the object stream: header (pairs) then data
    pairs_part = bytearray()
    data_part = bytearray()
    first_offset = 0  # we'll compute this

    # First pass: compute offsets
    current_data_offset = 0
    pairs_lines = []
    for onum, raw_bytes in raw_objs:
        pairs_lines.append(f"{onum} {current_data_offset}")
        current_data_offset += len(raw_bytes) + 1  # +1 for newline separator

    # Build pairs part
    pairs_str = ' '.join(pairs_lines)
    pairs_bytes = pairs_str.encode('latin-1')
    # The 'First' offset is the byte offset *within the decoded stream data* where objects begin
    # i.e. len(pairs_bytes) + whitespace separator
    first_offset = len(pairs_bytes) + 1  # +1 for the newline after pairs

    # Build full stream data
    stream_data = bytearray()
    stream_data += pairs_bytes
    stream_data += b'\n'
    for onum, raw_bytes in raw_objs:
        stream_data += raw_bytes
        stream_data += b'\n'

    compressed_objstm = zlib.compress(bytes(stream_data))

    # Obj 7: ObjStm
    obj_offsets[7] = len(output)
    output += (b"7 0 obj\n<< /Type /ObjStm /N " + str(len(raw_objs)).encode() +
               b" /First " + str(first_offset).encode() +
               b" /Length " + str(len(compressed_objstm)).encode() +
               b" /Filter /FlateDecode >>\nstream\n")
    output += compressed_objstm
    output += b"\nendstream\nendobj\n"

    # ================ Build xref stream (Obj 8) ================
    # Objects in the document:
    #   0: free
    #   1,2,3,5,6: in object stream 7 (type=2)
    #   7: ObjStm itself (type=1)
    #   8: xref stream (type=1)
    #   10: content stream (type=1)
    size = 11  # objects 0..10

    w = [1, 4, 1]  # type=1, field2=4 bytes, field3=1
    xref_data = bytearray()

    def add_xref_entry(type_val, field2, field3):
        xref_data.extend(struct.pack('>B', type_val))
        xref_data.extend(struct.pack('>I', field2))
        xref_data.extend(struct.pack('>B', field3))

    # Entry 0: free
    add_xref_entry(0, 0, 0xFF)
    # Entry 1: in object stream 7, index 0
    add_xref_entry(2, 7, 0)
    # Entry 2: in object stream 7, index 1
    add_xref_entry(2, 7, 1)
    # Entry 3: in object stream 7, index 2
    add_xref_entry(2, 7, 2)
    # Entry 4: free (unused)
    add_xref_entry(0, 0, 0xFF)
    # Entry 5: in object stream 7, index 3
    add_xref_entry(2, 7, 3)
    # Entry 6: in object stream 7, index 4
    add_xref_entry(2, 7, 4)
    # Entry 7: ObjStm (type=1, offset, gen=0)
    add_xref_entry(1, obj_offsets[7], 0)
    # Entry 8: xref stream (will fill below)
    xref_stream_offset_placeholder_pos = len(xref_data)
    add_xref_entry(1, 0, 0)  # placeholder
    # Entry 9: free
    add_xref_entry(0, 0, 0xFF)
    # Entry 10: content stream
    add_xref_entry(1, obj_offsets[10], 0)

    # Now compute xref stream object offset
    xref_stream_obj_num = 8
    xref_stream_offset = len(output)

    # Patch entry 8 offset
    struct.pack_into('>I', xref_data, xref_stream_offset_placeholder_pos + 1, xref_stream_offset)

    compressed_xref = zlib.compress(bytes(xref_data))

    # Write xref stream object
    output += f"{xref_stream_obj_num} 0 obj\n".encode('latin-1')
    output += (b"<< /Type /XRef /Size " + str(size).encode() +
               b" /W [" + b' '.join(str(x).encode() for x in w) + b"]" +
               b" /Index [0 11]" +  # all objects 0..10
               b" /Root 1 0 R /Info 6 0 R" +
               b" /Length " + str(len(compressed_xref)).encode() +
               b" /Filter /FlateDecode >>\nstream\n")
    output += compressed_xref
    output += b"\nendstream\nendobj\n"

    output += b"startxref\n"
    output += f"{xref_stream_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))
    print(f"Generated: {filepath} (ObjStm + xref stream)")


# ============================================================
# Helper: build Chinese PDF with embedded ToUnicode CMap
# ============================================================
def generate_chinese_cmap_pdf(filepath: str, num_pages: int = 10):
    """10-page Chinese PDF with Identity-H encoding and ToUnicode CMap.

    Uses CID (Type0) font with Identity-H horizontal writing.
    Glyph IDs map to Chinese characters via ToUnicode CMap with beginbfchar.
    """
    output = bytearray()
    output += b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"

    obj_offsets = {}

    # Sample Chinese content for 10 pages
    page_contents = [
        ["PDF 中文提取测试", "第一页：欢迎使用命令行 PDF 工具",
         "本工具能够解析嵌入字体并提取中文文本。"],
        ["第二页：关于 PDF 格式", "PDF（Portable Document Format）是一种文件格式",
         "由 Adobe Systems 开发，用于文档交换。"],
        ["第三页：交叉引用表", "xref 表记录了 PDF 中所有对象的偏移位置。",
         "PDF 1.5 引入了压缩的 xref 流格式。"],
        ["第四页：对象流（ObjStm）", "对象流可以将多个非流对象压缩存储在一起，",
         "显著减小 PDF 文件大小。"],
        ["第五页：内容流与操作符", "BT 和 ET 标记文本块的开始和结束。",
         "Tj 和 TJ 操作符用于显示文本字符串。"],
        ["第六页：字体与编码", "Type0 字体用于支持大字符集（如中文）。",
         "Identity-H 是常见的水平书写编码。"],
        ["第七页：ToUnicode CMap", "ToUnicode CMap 将字形 ID 映射回 Unicode 码位。",
         "支持 beginbfchar 和 beginbfrange 两种映射方式。"],
        ["第八页：全文搜索", "使用 SQLite FTS5 虚拟表建立倒排索引，",
         "可以在毫秒级完成大量 PDF 的关键词搜索。"],
        ["第九页：性能优化", "解析器按需加载对象，避免一次性读入全部内容。",
         "对象流的批量解压提升了解析速度。"],
        ["第十页：总结", "本工具从零实现了 PDF 二进制解析，",
         "不依赖任何第三方 PDF 库，仅使用 Python 标准库。"],
    ]

    # ----------- Build ToUnicode CMap for the CID font -----------
    # We'll map CIDs 1..N to Chinese characters
    # First collect all unique Chinese chars used in all pages
    all_text = ''.join(''.join(p) for p in page_contents)
    # Add basic ASCII too
    all_text += 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,:;!?()（）《》-+='

    unique_chars = []
    seen = set()
    for ch in all_text:
        if ch not in seen:
            seen.add(ch)
            unique_chars.append(ch)

    # Build CID -> Unicode mapping (CID starts at 1, 0 is reserved)
    cid_to_char = {}
    char_to_cid = {}
    for idx, ch in enumerate(unique_chars):
        cid = idx + 1
        cid_to_char[cid] = ch
        char_to_cid[ch] = cid

    # Encode Chinese text: each char -> 2-byte CID (big-endian for Identity-H)
    def encode_chinese(text: str) -> bytes:
        result = bytearray()
        for ch in text:
            cid = char_to_cid.get(ch, 0)
            result.extend(struct.pack('>H', cid))  # 2 bytes, big-endian
        return bytes(result)

    # Build ToUnicode CMap stream (using beginbfchar entries)
    # CMap format: Adobe standard
    cmap_lines = [
        "/CIDInit /ProcSet findresource begin",
        "12 dict begin",
        "begincmap",
        "/CIDSystemInfo",
        "<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def",
        "/CMapType 2 def",
        "1 begincodespacerange",
        "<0000> <FFFF>",
        "endcodespacerange",
    ]

    # beginbfchar entries (max 100 per block per PDF spec convention)
    bfchar_entries = []
    for cid, ch in sorted(cid_to_char.items()):
        src_hex = f"<{cid:04X}>"
        code_point = ord(ch)
        if code_point <= 0xFFFF:
            dst_hex = f"<{code_point:04X}>"
        else:
            # Surrogate pair for > BMP
            hi = 0xD800 + ((code_point - 0x10000) >> 10)
            lo = 0xDC00 + ((code_point - 0x10000) & 0x3FF)
            dst_hex = f"<{hi:04X}{lo:04X}>"
        bfchar_entries.append(f"{src_hex} {dst_hex}")

    # Split into chunks of 100
    for i in range(0, len(bfchar_entries), 100):
        chunk = bfchar_entries[i:i + 100]
        cmap_lines.append(f"{len(chunk)} beginbfchar")
        cmap_lines.extend(chunk)
        cmap_lines.append("endbfchar")

    cmap_lines.extend([
        "endcmap",
        "CMapName currentdict /CMap defineresource pop",
        "end",
        "end",
    ])

    cmap_bytes = '\n'.join(cmap_lines).encode('latin-1')
    compressed_cmap = zlib.compress(cmap_bytes)

    # ----------- Font objects -----------
    # Obj 12: ToUnicode CMap stream
    obj_offsets[12] = len(output)
    output += f"12 0 obj\n<< /Length {len(compressed_cmap)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
    output += compressed_cmap
    output += b"\nendstream\nendobj\n"

    # Obj 11: CIDFont (DescendantFont)
    obj_offsets[11] = len(output)
    output += (b"11 0 obj\n<< /Type /Font /Subtype /CIDFontType2 "
               b"/BaseFont /AdobeSongStd-Light "
               b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
               b"/W [1 [500]] >>\nendobj\n")

    # Obj 10: Type0 font (composite)
    obj_offsets[10] = len(output)
    output += (b"10 0 obj\n<< /Type /Font /Subtype /Type0 "
               b"/BaseFont /AdobeSongStd-Light "
               b"/Encoding /Identity-H "
               b"/DescendantFonts [11 0 R] "
               b"/ToUnicode 12 0 R >>\nendobj\n")

    # ----------- Page content streams -----------
    page_obj_nums = []
    content_obj_nums = []

    for page_idx in range(num_pages):
        page_obj_num = 30 + page_idx
        content_obj_num = 40 + page_idx
        page_obj_nums.append(page_obj_num)
        content_obj_nums.append(content_obj_num)

        # Build content stream: use TJ for hex strings (Identity-H encoded)
        content_parts = ["BT", "/F1 16 Tf", "72 750 Td"]
        y_offset = 0
        for line in page_contents[page_idx]:
            encoded = encode_chinese(line)
            hex_str = encoded.hex().upper()
            content_parts.append(f"<{hex_str}> Tj")
            y_offset += 28
            content_parts.append(f"0 -{28} Td")
        content_parts.append("ET")

        content_bytes = '\n'.join(content_parts).encode('latin-1')
        compressed_content = zlib.compress(content_bytes)

        # Write content stream object
        obj_offsets[content_obj_num] = len(output)
        output += f"{content_obj_num} 0 obj\n".encode('latin-1')
        output += f"<< /Length {len(compressed_content)} /Filter /FlateDecode >>\nstream\n".encode('latin-1')
        output += compressed_content
        output += b"\nendstream\nendobj\n"

        # Write page object
        obj_offsets[page_obj_num] = len(output)
        output += f"{page_obj_num} 0 obj\n".encode('latin-1')
        output += (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                   f"/Contents {content_obj_num} 0 R "
                   f"/Resources << /Font << /F1 10 0 R >> >> >>\n").encode('latin-1')
        output += b"endobj\n"

    # ----------- Structural objects -----------
    # Obj 1: Catalog
    obj_offsets[1] = len(output)
    output += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    # Obj 2: Pages
    obj_offsets[2] = len(output)
    kids_str = ' '.join(f"{n} 0 R" for n in page_obj_nums)
    output += f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>\nendobj\n".encode('latin-1')

    # Obj 6: Info
    obj_offsets[6] = len(output)
    output += (b"6 0 obj\n<< /Title (\xef\xbc\xa8\xe4\xb8\xad\xe6\x96\x87 PDF \xe6\xb5\x8b\xe8\xaf\x95) "
               b"/Author (mypdf Test Suite) /Creator (generate_real_pdfs.py) "
               b"/Subject (Chinese PDF with ToUnicode CMap) >>\nendobj\n")

    # ================ Build xref stream (Obj 7) ================
    max_obj = max(obj_offsets.keys())
    size = max_obj + 1

    w = [1, 4, 1]
    xref_data = bytearray()

    def add_xref_entry(type_val, field2, field3):
        xref_data.extend(struct.pack('>B', type_val))
        xref_data.extend(struct.pack('>I', field2))
        xref_data.extend(struct.pack('>B', field3))

    # Entry 0: free
    add_xref_entry(0, 0, 0xFF)
    # Entries 1..max_obj
    for onum in range(1, size):
        if onum in obj_offsets:
            add_xref_entry(1, obj_offsets[onum], 0)
        else:
            add_xref_entry(0, 0, 0xFF)
    # Add xref stream self-reference
    xref_stream_obj_num = size
    xref_stream_offset = len(output)
    add_xref_entry(1, xref_stream_offset, 0)
    size = xref_stream_obj_num + 1

    compressed_xref = zlib.compress(bytes(xref_data))

    output += f"{xref_stream_obj_num} 0 obj\n".encode('latin-1')
    output += (b"<< /Type /XRef /Size " + str(size).encode() +
               b" /W [" + b' '.join(str(x).encode() for x in w) + b"]" +
               b" /Root 1 0 R /Info 6 0 R" +
               b" /Length " + str(len(compressed_xref)).encode() +
               b" /Filter /FlateDecode >>\nstream\n")
    output += compressed_xref
    output += b"\nendstream\nendobj\n"

    output += b"startxref\n"
    output += f"{xref_stream_offset}\n".encode('latin-1')
    output += b"%%EOF\n"

    with open(filepath, 'wb') as f:
        f.write(bytes(output))
    print(f"Generated: {filepath} ({num_pages} pages, Chinese CMap, xref stream)")
    print(f"  Total chars mapped: {len(cid_to_char)} CIDs -> Unicode")


if __name__ == '__main__':
    os.makedirs('test_pdfs', exist_ok=True)
    generate_xref_stream_pdf('test_pdfs/xref_stream.pdf')
    generate_objstm_pdf('test_pdfs/objstm.pdf')
    generate_chinese_cmap_pdf('test_pdfs/chinese_cmap.pdf', 10)
    print("\nAll realistic test PDFs generated in test_pdfs/")
