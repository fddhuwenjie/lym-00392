"""Final acceptance test suite covering ALL acceptance criteria."""
import signal
import sys
import os
import shutil

signal.signal(signal.SIGALRM, lambda s, f: sys.exit(99))
signal.alarm(90)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mypdf.parser import parse_pdf, PDFEncryptedError
from mypdf.extractor import PDFTextExtractor
from mypdf.indexer import PDFIndexer

PASS = 0
FAIL = 0
def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name} {detail}')

TEST_PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_pdfs')

print('=' * 60)
print('FINAL ACCEPTANCE TEST')
print('=' * 60)

# ============ 1. xref stream PDF ============
print('\n[Test 1] xref stream PDF parsing')
path = os.path.join(TEST_PDF_DIR, 'xref_stream.pdf')
doc = parse_pdf(path)
check('xref stream parsed OK', doc is not None)
check('Pages count == 1', doc.get_page_count() == 1)
info = doc.get_info()
check('Title == XRef Stream Test', info.get('Title') == 'XRef Stream Test')
ex = PDFTextExtractor(path)
text = ex.extract_text()
check('Text contains xref stream', 'xref stream' in text)

# ============ 2. ObjStm PDF ============
print('\n[Test 2] Object stream (ObjStm) PDF parsing')
path = os.path.join(TEST_PDF_DIR, 'objstm.pdf')
doc = parse_pdf(path)
check('ObjStm parsed OK', doc is not None)
check('Pages count == 1', doc.get_page_count() == 1)
info = doc.get_info()
check('Title == ObjStm Test', info.get('Title') == 'ObjStm Test')
ex = PDFTextExtractor(path)
text = ex.extract_text()
check('Text contains Hello from ObjStm', 'Hello from ObjStm' in text)
check('Text contains object streams', 'object streams' in text)

# ============ 3. Chinese CMap PDF (10 pages) - CORE ACCEPTANCE ============
print('\n[Test 3] Chinese ToUnicode CMap PDF (CORE ACCEPTANCE CRITERION)')
path = os.path.join(TEST_PDF_DIR, 'chinese_cmap.pdf')
doc = parse_pdf(path)
check('Chinese PDF parsed OK', doc is not None)
check('Pages count == 10', doc.get_page_count() == 10, f'got {doc.get_page_count()}')
info = doc.get_info()
check('Author contains mypdf Test Suite', 'mypdf Test Suite' in info.get('Author', ''))

ex = PDFTextExtractor(path)
text = ex.extract_text()
lines = [l for l in text.split('\n') if l.strip()]
check(f'Has >= 30 non-empty lines (10p x 3)', len(lines) >= 30, f'got {len(lines)}')
check('Page1: 中文提取测试 present', '中文提取测试' in text)
check('Page2: 关于 PDF 格式 present', '关于 PDF 格式' in text)
check('Page3: 交叉引用表 present', '交叉引用表' in text)
check('Page4: 对象流（ObjStm） present', '对象流' in text)
check('Page5: 内容流与操作符 present', '内容流与操作符' in text)
check('Page6: 字体与编码 present', '字体与编码' in text)
check('Page7: ToUnicode CMap present', 'ToUnicode CMap' in text)
check('Page8: 全文搜索 present', '全文搜索' in text)
check('Page9: 性能优化 present', '性能优化' in text)
check('Page10: 总结 present', '总结' in text)
check('Page10: Python 标准库 present', 'Python 标准库' in text)

# ============ 4. Encrypted PDF graceful error ============
print('\n[Test 4] Encrypted PDF graceful error handling')
path = os.path.join(TEST_PDF_DIR, 'encrypted.pdf')
try:
    parse_pdf(path)
    check('Encrypted PDF raised error', False, 'no error thrown')
except PDFEncryptedError as e:
    check('PDFEncryptedError raised', True)
    check('Message contains "password protected"', 'password' in str(e).lower())
except Exception as e:
    check('Encrypted PDF raises proper type', False, f'got {type(e).__name__}: {e}')

# ============ 5. mypdf info command (metadata) ============
print('\n[Test 5] Metadata extraction (title/author/pages)')
path = os.path.join(TEST_PDF_DIR, 'chinese_cmap.pdf')
ex = PDFTextExtractor(path)
info = ex.get_info()
check('get_info returns title', bool(info.get('title')))
check('get_info returns author', bool(info.get('author')))
check('get_info returns pages (int)', isinstance(info.get('pages'), int) and info['pages'] == 10)

# ============ 6. Index 50+ PDFs & search ============
print('\n[Test 6] Index 50+ PDFs and search (bulk + FTS5)')
bulk_dir = '/tmp/mypdf_bulk_test'
os.makedirs(bulk_dir, exist_ok=True)
src = os.path.join(TEST_PDF_DIR, 'chinese_cmap.pdf')
for i in range(50):
    shutil.copy2(src, os.path.join(bulk_dir, f'copy_{i:03d}.pdf'))
shutil.copy2(os.path.join(TEST_PDF_DIR, 'xref_stream.pdf'), bulk_dir)
shutil.copy2(os.path.join(TEST_PDF_DIR, 'objstm.pdf'), bulk_dir)

db_path = '/tmp/bulk_index_test.db'
if os.path.exists(db_path):
    os.remove(db_path)

indexer = PDFIndexer(db_path)
res = indexer.index_directory(bulk_dir)
check(f'Total scanned >= 52', res['total'] >= 52, f'got {res["total"]}')
check(f'Indexed successfully >= 52', res['success'] >= 52, f'got {res["success"]}')
check('No indexing failures', res['failed'] == 0, f'got {res["failed"]}')

# Chinese search
r = indexer.search('中文提取测试')
check('Search 中文提取测试 finds >= 50 docs', len(r) >= 50, f'got {len(r)}')
if r:
    has_snippet_with_chinese = any('中' in s for s in r[0].get('snippets', []))
    check('Search result snippet contains Chinese chars', has_snippet_with_chinese)

r = indexer.search('性能优化')
check('Search 性能优化 finds results', len(r) >= 1)

# Cross-file type search
r = indexer.search('xref stream')
has_xref_pdf = any('xref_stream.pdf' in x.get('filename', '') for x in r)
check('Search "xref stream" finds xref_stream.pdf', has_xref_pdf)

r = indexer.search('ObjStm')
has_objstm = any('objstm.pdf' in x.get('filename', '') for x in r)
check('Search "ObjStm" finds objstm.pdf', has_objstm)

# Cleanup
indexer.close()
shutil.rmtree(bulk_dir, ignore_errors=True)
try:
    os.remove(db_path)
except:
    pass

# ============ 7. Regression tests (simple/multipage) ============
print('\n[Test 7] Regression: simple.pdf + multipage.pdf')
path = os.path.join(TEST_PDF_DIR, 'simple.pdf')
doc = parse_pdf(path)
check('simple.pdf pages == 1', doc.get_page_count() == 1)
ex = PDFTextExtractor(path)
check('simple.pdf has Hello, World!', 'Hello, World!' in ex.extract_text())

path = os.path.join(TEST_PDF_DIR, 'multipage.pdf')
doc = parse_pdf(path)
check('multipage.pdf pages == 5', doc.get_page_count() == 5, f'got {doc.get_page_count()}')
ex = PDFTextExtractor(path)
txt = ex.extract_text()
check('multipage has Page 1', 'Page 1' in txt)
check('multipage has Page 5', 'Page 5' in txt)
check('multipage has Line 3 on page 3', 'Line 3 on page 3' in txt)

# ============ 8. ObjStm type PDF #2 (objstm_test.pdf if exists) ============
path2 = os.path.join(TEST_PDF_DIR, 'objstm_test.pdf')
if os.path.exists(path2):
    print('\n[Test 8] Extra ObjStm PDF (objstm_test.pdf)')
    try:
        doc = parse_pdf(path2)
        check('Parses objstm_test.pdf', True)
        check(f'Has {doc.get_page_count()} pages', doc.get_page_count() >= 1)
        ex = PDFTextExtractor(path2)
        txt = ex.extract_text()
        check('Text extraction works', len(txt.strip()) > 0)
    except Exception as e:
        check(f'objstm_test.pdf parse fails: {e}', False)

print()
print('=' * 60)
print(f'RESULTS: {PASS} PASSED, {FAIL} FAILED')
print('=' * 60)
sys.exit(0 if FAIL == 0 else 1)
