"""Bảng thuật ngữ dùng chung cho dịch và TTS: mục dịch, phát âm, dấu nguồn."""
import hashlib
import re
import unicodedata

ENTRY = re.compile(r'^\s*[-*]\s+(.+?)\s*=>\s*(.+?)\s*(?:;\s*avoid:\s*(.+))?$')
HEADER = re.compile(r'<!--\s*source-sha:\s*([0-9a-f]+)\s*-->')
PRONUNCIATION = re.compile(r'^#+\s*(pronunciation|phát âm)', re.I)
MIN_AVOID = 4   # biến thể ngắn hơn (Sie, Man, Tin...) trùng từ thường của ngôn ngữ đích
# Chữ có dấu hợp lệ của ngôn ngữ đích; chữ có dấu khác trong một từ = tên Việt cần phiên âm.
NATIVE = {'de': set('äöüÄÖÜß'), 'en': set(), 'es': set('áéíóúüñÁÉÍÓÚÜÑ')}


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def header(source_text):
    return f'<!-- source-sha: {sha(source_text)} -->'


def source_status(glossary_text, source_text):
    """'ok' nếu glossary được tạo cho đúng nguồn này, 'stale' nếu cho nguồn khác, 'unknown' nếu không có dấu."""
    match = HEADER.search(glossary_text)
    if not match:
        return 'unknown'
    return 'ok' if match[1] == sha(source_text) else 'stale'


def lines_by_section(text):
    section = ''
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            section = line.strip()
        yield section, line


def is_pronunciation(section):
    return bool(PRONUNCIATION.match(section))


def parse_entries(text):
    """(nguồn, đích, [biến thể cấm]) từ các dòng '- nguồn => đích; avoid: a, b' (trừ mục phát âm)."""
    entries = []
    for section, line in lines_by_section(text):
        match = ENTRY.match(line)
        if match and not is_pronunciation(section):
            avoid = [x.strip(' "„“”\'`') for x in (match[3] or '').split(',')]
            entries.append((match[1], match[2], [x for x in avoid if len(x) >= MIN_AVOID]))
    return entries


def parse_pronunciation(text):
    """{cách viết: cách đọc} trong mục '## Pronunciation'."""
    mapping = {}
    for section, line in lines_by_section(text):
        match = ENTRY.match(line)
        if match and is_pronunciation(section):
            mapping[match[1].strip()] = match[2].strip()
    return mapping


def chapter_stamp(glossary_text, chapter_source):
    """Dấu chỉ gồm phần glossary ảnh hưởng tới chương: mục có thuật ngữ xuất hiện trong chương
    và các dòng chung (Style, ghi chú). Mục phát âm và dấu nguồn không ảnh hưởng bản dịch."""
    source = chapter_source.lower()
    keep = []
    for section, line in lines_by_section(glossary_text):
        line = ' '.join(line.split())
        if not line or is_pronunciation(section) or HEADER.search(line):
            continue
        match = ENTRY.match(line)
        if match:
            terms = [t.strip() for t in re.split(r'[/↔,;]', match[1]) if t.strip()]
            if not any(t.lower() in source for t in terms):
                continue
        keep.append(line)
    return sha('\n'.join(keep))


def strip_diacritics(word):
    word = word.replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', word) if not unicodedata.combining(c))


def foreign_words(text, lang):
    """Các từ chứa chữ có dấu không thuộc ngôn ngữ đích (thường là tên Việt)."""
    native = NATIVE.get(lang, set())
    found = []
    for word in re.findall(r'\w+', text):
        if any(ord(c) > 127 and c not in native for c in word) and word not in found:
            found.append(word)
    return found


def spoken_text(text, lang, mapping):
    """Văn bản cho TTS: thay tên theo bảng phát âm; tên Việt còn lại thì bỏ dấu.
    Trả (văn bản, danh sách từ đã tự bỏ dấu để người dùng bổ sung phát âm)."""
    for written in sorted(mapping, key=len, reverse=True):
        # Cho phép đuôi sở hữu cách tiếng Đức/Anh: "Hảos", "Hảo's".
        text = re.sub(r'(?<!\w)' + re.escape(written) + r"(?=(?:s|'s|’s)?(?!\w))", mapping[written], text)
    stripped = foreign_words(text, lang)
    for word in stripped:
        text = re.sub(r'(?<!\w)' + re.escape(word) + r'(?!\w)', strip_diacritics(word), text)
    return text, stripped
