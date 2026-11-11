"""Dịch truyện Việt sang de/en/es theo từng chương và review đối chiếu từng chương.

Mỗi lần gọi model chỉ nhận MỘT chương nguồn + bảng thuật ngữ + đoạn đuôi của chương
trước (để nối giọng), nên không còn bị cắt, không phải "tiếp tục" cả bản dài và vòng
sửa chỉ chạy lại các chương còn lỗi. Mọi kết quả trung gian được lưu để chạy lại không
tốn token.

Tệp tạo ra trong --out-dir:
  glossary.<lang>.md          bảng thuật ngữ (sửa tay được, chạy lại sẽ dùng bản này)
  <lang>.chapters/NN.rK.md    bản dịch chương NN, vòng K (+ .review.json / .review.raw.txt)
  <lang>.md                   bản ghép từ vòng mới nhất của từng chương
  <lang>.review.json/.md      tổng hợp điểm
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karma import llm
from karma.common import atomic_write, config, length_check, read, save_json, words_per_minute

LANGUAGES = {'de': 'German for older listeners in Germany',
             'en': 'natural American English for older listeners',
             'es': 'natural Spanish for older listeners in Spain'}
WEIGHTS = {'fidelity': .30, 'naturalness': .25, 'read_aloud': .20,
           'cultural_clarity': .15, 'consistency': .10}
END = '[[END_TRANSLATION]]'
MAX_CONTINUATIONS = 3
TAIL_CHARS = 600
MIN_AVOID = 4
# Số từ đích trên mỗi tiếng Việt, đo từ truyện 017 (vòng 2 → bản dịch round1).
VI_RATIO = {'de': 1.18, 'en': 1.15, 'es': 1.18}
INVISIBLE = dict.fromkeys(map(ord, '­​‌‍⁠﻿'))
ENTRY = re.compile(r'^\s*[-*]\s+(.+?)\s*=>\s*(.+?)\s*(?:;\s*avoid:\s*(.+))?$')


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def words(text):
    return len(text.split())


# ---------- Chia chương ----------

def split_chapters(text, fallback_words=2500):
    """Tách theo dòng '## '. Phần trước chương 1 (nhan đề) gộp vào chương 1."""
    text = text.strip()
    parts = [p.strip() for p in re.split(r'(?m)^(?=## )', text) if p.strip()]
    if len(parts) > 1 and not parts[0].startswith('## '):
        parts[1] = parts[0] + '\n\n' + parts[1]
        parts = parts[1:]
    if len(parts) > 1 or (parts and parts[0].startswith('## ')):
        return parts
    # Không có tiêu đề chương: chia theo đoạn văn, khoảng fallback_words từ mỗi phần.
    chunks, current, size = [], [], 0
    for paragraph in re.split(r'\n\s*\n', text):
        current.append(paragraph)
        size += words(paragraph)
        if size >= fallback_words:
            chunks.append('\n\n'.join(current))
            current, size = [], 0
    if current:
        chunks.append('\n\n'.join(current))
    return chunks


# ---------- Bảng thuật ngữ ----------

def parse_glossary(text):
    """Trả danh sách (nguồn, đích, [biến thể cấm]) từ các dòng '- nguồn => đích; avoid: a, b'."""
    entries = []
    for line in text.splitlines():
        match = ENTRY.match(line)
        if match:
            avoid = [x.strip(' "„“”\'`') for x in (match[3] or '').split(',')]
            # Biến thể < 4 ký tự (Sie, Man, Tin...) trùng từ thường của ngôn ngữ đích: bỏ qua.
            entries.append((match[1], match[2], [x for x in avoid if len(x) >= MIN_AVOID]))
    return entries


def glossary_issues(text, glossary):
    issues = []
    for source, target, avoid in glossary:
        for variant in avoid:
            count = len(re.findall(r'(?<!\w)' + re.escape(variant) + r'(?!\w)', text, re.I))
            if count:
                issues.append(f'Thuật ngữ "{source}": dùng "{variant}" {count} lần, bảng thuật ngữ '
                              f'yêu cầu "{target}" và cấm biến thể này.')
    return issues


def ensure_glossary(source_text, folder, lang):
    path = folder / f'glossary.{lang}.md'
    if path.exists():
        return read(path)
    prompt = f'''Read the Vietnamese story below and write a translation glossary for rendering it into {LANGUAGES[lang]}.
Output Markdown only, in these sections, one entry per line in EXACTLY this format:
- <Vietnamese term> => <chosen rendering>; avoid: <comma-separated LITERAL wrong words/phrases in the target language, each at least 4 letters; never pronouns, grammar choices (du/Sie, tu/usted) or descriptions - put those in the rendering instead>
Sections: ## Names (every character, nickname/real-name clues, places), ## Address and kinship (how each person is addressed by each other and by the narrator, honorifics, consistent use of formal/informal forms), ## Cultural objects (each unfamiliar object with ONE rendering and, if needed, a very short in-prose gloss for first use), ## Ambiguities (relationships or facts the source leaves unclear: say "keep ambiguous", never resolve them), ## Style (3-6 bullet lines of tone rules for listeners 60+, no "=>" needed).
Be concise. Do not translate the story. Do not use tools.
VIETNAMESE STORY:
{source_text}'''
    answer = llm.complete('writer', prompt).strip()
    answer = re.sub(r'^```\w*\n|\n```$', '', answer).strip()
    atomic_write(path, answer + '\n')
    return answer + '\n'


# ---------- Dịch một chương ----------

def clean(text):
    return text.translate(INVISIBLE).replace(END, '').strip()


def chapter_dir(folder, lang):
    path = folder / f'{lang}.chapters'
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_round(cdir, number):
    rounds = [int(p.name.split('.r')[1].split('.')[0]) for p in cdir.glob(f'{number}.r*.md')
              if re.fullmatch(rf'{number}\.r\d+\.md', p.name)]
    return max(rounds, default=0)


def generate(prompt, draft_path):
    """Gọi writer; nếu thiếu marker kết thúc thì nối tiếp trên CHÍNH chương này."""
    text = read(draft_path) if draft_path.exists() else ''
    for _ in range(MAX_CONTINUATIONS + 1):
        extra = ('\nALREADY WRITTEN (do not repeat it). Continue exactly from its last word:\n' + text) if text else ''
        answer = llm.complete('writer', prompt + extra)
        text += ('\n' if text else '') + answer.strip()
        atomic_write(draft_path, text + '\n')
        if END in answer:
            result = clean(text)
            draft_path.unlink()
            return result
    raise RuntimeError(f'Chương chưa xong ({draft_path.name}); chạy lại để tiếp tục từ draft.')


def translate_prompt(lang, source, glossary, prev_source, prev_translation, previous=None, fixes=None):
    rules = f'''You are a literary translator. Translate the Vietnamese chapter below into {LANGUAGES[lang]}.
This is translation/localization, not adaptation. Preserve every event, causal link, ambiguity, revelation, character and the ending of the chapter. Do not summarize, omit, add commentary, or repair the source plot. Keep Vietnamese setting and proper names; localize idioms, not places or cultural identity. Explain an unfamiliar object very briefly in prose only when the glossary says so. Natural, restrained oral storytelling for listeners 60+, complete sentences, short clear dialogue, easy to read aloud (avoid long compound words and awkward genitive forms of names). Keep the chapter heading translated and keep the same Markdown heading level. FOLLOW THE GLOSSARY EXACTLY. Do not use tools or subagents. Return ONLY the translated chapter, ending with the marker {END}.
GLOSSARY:
{glossary}'''
    if prev_source:
        rules += f'''
CONTINUITY ONLY (end of the previous chapter; do NOT translate or repeat it):
SOURCE: ...{prev_source}
TRANSLATION: ...{prev_translation}'''
    if previous is not None:
        rules += '\nThis is a REVISION. Apply every fix below, change nothing else, and return the complete revised chapter.\nFIXES:\n'
        rules += '\n'.join(f'- {fix}' for fix in fixes)
        rules += '\nCURRENT TRANSLATION:\n' + previous
    return rules + '\nVIETNAMESE CHAPTER:\n' + source


# ---------- Review một chương ----------

def parse_review(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != '{':
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get('criteria'), dict):
            break
    else:
        raise ValueError('Claude không trả JSON review hợp lệ; đã giữ phản hồi gốc.')
    for key in WEIGHTS:
        value = data['criteria'].get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError('Điểm review không hợp lệ: ' + key)
    data['score'] = round(sum(data['criteria'][k] * w for k, w in WEIGHTS.items()), 4)
    cfg = config()
    # Không tin cờ pass của model: tính lại theo ngưỡng cấu hình.
    data['pass'] = (data['score'] >= cfg['score_threshold']
                    and all(data['criteria'][k] >= cfg['min_each_criterion'] for k in WEIGHTS))
    return data


def review_prompt(lang, source, translation, glossary):
    return f'''Bạn là biên tập viên dịch thuật nghiêm khắc, review MỘT chương đối chiếu bản Việt. Nhận xét bằng tiếng Việt, trích nguyên văn ngôn ngữ đích và đề xuất câu sửa bằng chính ngôn ngữ đó. Không dùng công cụ hoặc tác nhân phụ.
Đây là DỊCH, không phải viết mới. Không trừ điểm fidelity vì bản dịch giữ nguyên lỗ hổng cốt truyện của nguồn; ghi lỗ hổng đó vào source_issues. Không yêu cầu đổi địa danh Việt. Kiểm tra: đủ sự kiện, ngôi kể, tên, đại từ/kính ngữ, lời thoại, nhan đề, không sót tiếng Việt ngoài tên/vật văn hóa cố ý giữ, và TUÂN THỦ BẢNG THUẬT NGỮ.
Chấm 0–10: fidelity 30%; naturalness 25%; read_aloud 20% (hợp đọc cho 60+); cultural_clarity 15%; consistency 10% (theo bảng thuật ngữ). Chỉ trả một JSON hợp lệ:
{{"criteria":{{"fidelity":0,"naturalness":0,"read_aloud":0,"cultural_clarity":0,"consistency":0}},"summary":"...","missing_events":[],"fixes":[{{"quote":"...","issue":"...","suggested":"..."}}],"source_issues":[]}}
NGÔN NGỮ ĐÍCH: {LANGUAGES[lang]}
BẢNG THUẬT NGỮ:
{glossary}
CHƯƠNG VIỆT:
{source}
CHƯƠNG DỊCH:
{translation}'''


def chapter_ok(review, threshold, min_each):
    return (review['score'] >= threshold and all(v >= min_each for v in review['criteria'].values())
            and not review.get('missing_events'))


def fix_lines(review, local):
    lines = list(local)
    if review.get('missing_events'):
        lines.append('Thiếu sự kiện: ' + '; '.join(map(str, review['missing_events'])))
    for fix in review.get('fixes', []):
        if isinstance(fix, dict):
            lines.append(f'"{fix.get("quote", "")}" — {fix.get("issue", "")} → {fix.get("suggested", "")}')
        else:
            lines.append(str(fix))
    return lines


# ---------- Điều phối ----------

def estimate_minutes(source_text, lang, cfg):
    words = len(re.sub(r'(?m)^#+.*$', '', source_text).split()) * VI_RATIO[lang]
    return words / words_per_minute(lang, cfg)


def check_source_length(source_text, lang, cfg):
    low, high = cfg['target_minutes']
    minutes = estimate_minutes(source_text, lang, cfg)
    if not low <= minutes <= high:
        vi = len(re.sub(r'(?m)^#+.*$', '', source_text).split())
        need = [round(m * words_per_minute(lang, cfg) / VI_RATIO[lang]) for m in (low, high)]
        raise ValueError(f'Bản Việt {vi} tiếng ≈ {minutes:.1f} phút tiếng {lang}, ngoài khoảng {low}–{high} phút. '
                         f'Cần khoảng {need[0]:,}–{need[1]:,} tiếng; rút/bổ sung bản Việt trước khi dịch '
                         f'(hoặc dùng --ignore-length).')
    return round(minutes, 1)

def process(source, folder, lang, max_rounds=2, glossary_only=False, ignore_length=False):
    cfg = config()
    threshold, min_each = cfg['score_threshold'], cfg['min_each_criterion']
    folder.mkdir(parents=True, exist_ok=True)
    source_text = read(source)
    if not ignore_length:
        print(f'[{lang}] ước tính ~{check_source_length(source_text, lang, cfg)} phút.', flush=True)
    chapters = split_chapters(source_text)
    glossary_text = ensure_glossary(source_text, folder, lang)
    if glossary_only:
        print(f'Đã tạo glossary.{lang}.md; sửa tay nếu cần rồi chạy lại.', flush=True)
        return
    glossary = parse_glossary(glossary_text)
    cdir = chapter_dir(folder, lang)
    meta_path = cdir / 'meta.json'
    meta = json.loads(read(meta_path)) if meta_path.exists() else {}
    results = []
    for index, src in enumerate(chapters, 1):
        number = f'{index:02d}'
        stamp = sha(src) + sha(glossary_text)
        if meta.get(number) != stamp:
            for old in cdir.glob(f'{number}.r*'):
                old.unlink()   # nguồn hoặc bảng thuật ngữ đổi: bỏ kết quả cũ của chương này
            meta[number] = stamp
            save_json(meta_path, meta)
        prev_src = chapters[index - 2][-TAIL_CHARS:] if index > 1 else ''
        prev_tr = ''
        if index > 1:
            prev_tr = read(cdir / f'{index - 1:02d}.r{latest_round(cdir, f"{index - 1:02d}")}.md')[-TAIL_CHARS:]
        rnd = latest_round(cdir, number)
        while True:
            path = cdir / f'{number}.r{rnd}.md'
            if rnd == 0:
                prompt = translate_prompt(lang, src, glossary_text, prev_src, prev_tr)
                rnd = 1
                path = cdir / f'{number}.r1.md'
                atomic_write(path, generate(prompt, cdir / f'{number}.r1.draft.md') + '\n')
                print(f'[{lang}] chương {number} dịch xong ({words(read(path))} từ).', flush=True)
            translation = read(path).strip()
            raw = cdir / f'{number}.r{rnd}.review.raw.txt'
            if not raw.exists():
                atomic_write(raw, llm.complete('scorer', review_prompt(lang, src, translation, glossary_text)))
            review = parse_review(read(raw))
            save_json(cdir / f'{number}.r{rnd}.review.json', review)
            local = glossary_issues(translation, glossary)
            if translation.count('\n#') + translation.startswith('#') < src.count('\n#') + src.startswith('#'):
                local.append('Thiếu tiêu đề chương/nhan đề so với nguồn; dịch và giữ đủ dòng tiêu đề.')
            ok = chapter_ok(review, threshold, min_each) and not local
            print(f'[{lang}] chương {number} vòng {rnd}: {review["score"]:.2f}'
                  f'{" ✓" if ok else " cần sửa"}' + (f' ({len(local)} lỗi thuật ngữ/cấu trúc)' if local else ''), flush=True)
            if ok or rnd >= max_rounds:
                break
            rnd += 1
            prompt = translate_prompt(lang, src, glossary_text, prev_src, prev_tr, translation, fix_lines(review, local))
            atomic_write(cdir / f'{number}.r{rnd}.md', generate(prompt, cdir / f'{number}.r{rnd}.draft.md') + '\n')
        results.append(dict(number=number, round=rnd, source_words=words(src), review=review,
                            local_issues=local, ok=ok, text=translation))
    finish(source, folder, lang, results, threshold, min_each, cfg)


def finish(source, folder, lang, results, threshold, min_each, cfg):
    full = '\n\n'.join(r['text'] for r in results) + '\n'
    atomic_write(folder / f'{lang}.md', full)
    length = length_check(full, lang, cfg)
    total = sum(r['source_words'] for r in results) or 1
    criteria = {k: round(sum(r['review']['criteria'][k] * r['source_words'] for r in results) / total, 3)
                for k in WEIGHTS}
    score = round(sum(criteria[k] * w for k, w in WEIGHTS.items()), 4)
    passed = (score >= threshold and all(v >= min_each for v in criteria.values())
              and all(r['ok'] for r in results) and length['ok'])
    review = dict(score=score, criteria=criteria, reviewer='Claude CLI',
                  length={k: length[k] for k in ('minutes', 'words', 'ok')},
                  source_file=str(source), translation_file=str(folder / f'{lang}.md'),
                  chapters=[dict(chapter=r['number'], round=r['round'], score=r['review']['score'],
                                 ok=r['ok'], local_issues=r['local_issues'],
                                 remaining_fixes=fix_lines(r['review'], []),
                                 source_issues=r['review'].get('source_issues', [])) for r in results])
    review['pass'] = passed
    save_json(folder / f'{lang}.review.json', review)
    lines = [f'# Claude review bản {lang}', '',
             f"**{score:.2f}/10 — {'ĐẠT' if passed else 'CHƯA ĐẠT'}**", '',
             f"Thời lượng ước tính: {length['minutes']} phút ({length['words']} từ)"
             + ('' if length['ok'] else ' — ' + length['fix']), '',
             'Điểm tổng = trung bình theo số từ nguồn của từng chương, trọng số dịch thuật; '
             'không phải rubric chất lượng cốt truyện.', '', '## Điểm từng tiêu chí']
    lines += [f'- {k} ({w:.0%}): {criteria[k]}/10' for k, w in WEIGHTS.items()]
    lines += ['', '## Từng chương', '', '| Chương | Vòng | Điểm | Trạng thái |', '|---|---|---|---|']
    lines += [f"| {c['chapter']} | {c['round']} | {c['score']:.2f} | {'đạt' if c['ok'] else 'cần sửa'} |"
              for c in review['chapters']]
    todo = [c for c in review['chapters'] if not c['ok']]
    if todo:
        lines += ['', '## Việc còn lại']
        for c in todo:
            lines += [f"### Chương {c['chapter']}"] + [f'- {x}' for x in c['local_issues'] + c['remaining_fixes']]
    issues = [(c['chapter'], x) for c in review['chapters'] for x in c['source_issues']]
    if issues:
        lines += ['', '## Lỗ hổng ở bản nguồn (không trừ điểm dịch)'] + [f'- Chương {n}: {x}' for n, x in issues]
    atomic_write(folder / f'{lang}.review.md', '\n'.join(lines) + '\n')
    print(f'{lang}: {score:.2f} — {"ĐẠT" if passed else "CHƯA ĐẠT"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--lang', choices=(*LANGUAGES, 'all'), default='all')
    parser.add_argument('--max-rounds', type=int, default=2,
                        help='số vòng dịch/sửa tối đa cho mỗi chương (mặc định 2)')
    parser.add_argument('--ignore-length', action='store_true',
                        help='bỏ qua kiểm tra độ dài bản Việt trước khi dịch')
    parser.add_argument('--glossary-only', action='store_true',
                        help='chỉ tạo glossary.<lang>.md để sửa tay rồi dừng')
    args = parser.parse_args()
    if args.max_rounds < 1:
        parser.error('--max-rounds phải >= 1')
    for lang in LANGUAGES if args.lang == 'all' else (args.lang,):
        process(args.source.resolve(), args.out_dir.resolve(), lang, args.max_rounds, args.glossary_only,
                args.ignore_length)


if __name__ == '__main__':
    main()
