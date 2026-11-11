import json
import re
from pathlib import Path

from . import glossary as gl
from .cli_score import evaluate
from .common import atomic_write, config, languages, length_check, read, save_json, story_dir, words_per_minute
from .numbers import expand_numbers

# Mọi dòng "## ..." là một chương; lấy số nếu có ("## Kapitel 3", "## Capítulo 3"...).
HEADING = re.compile(r"^##\s.*$", re.M)
NUMBER = re.compile(r"^##\s+\S+\s+(\d+)")


def plain_text(text, lang):
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s*(?:#{1,6}\s*|>\s*|[-*+]\s+|\d+[.)]\s+)", "", text, flags=re.M)
    text = re.sub(r"[*_`~#]", "", text)
    text = expand_numbers(text, lang)
    text = re.sub(r"\s+", " ", text).strip()
    # Dấu kết câu có thể nằm trong ngoặc kép: „…kalt.“ / «…» / "…!"
    if text and text.rstrip("\"'“”„«»’)")[-1:] not in tuple(".!?…"):
        text += "."
    return text


def segments(text, limit=400):
    # Ưu tiên dấu hết câu, rồi dấu ngắt, cuối cùng khoảng trắng.
    while len(text) > limit:
        window = text[:limit]
        boundaries = list(re.finditer(r"[.!?…;,:](?=\s)", window))
        cut = boundaries[-1].end() if boundaries else window.rfind(" ")
        if cut <= 0:
            cut = limit
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text


def build(script, lang, folder, glossary_path):
    """Tạo <lang>.tts.txt (đã phiên âm tên) và <lang>.scenes.json (giữ chữ gốc cho phụ đề)."""
    mapping = gl.parse_pronunciation(read(glossary_path)) if glossary_path.exists() else {}
    wpm = words_per_minute(lang)
    scenes, stripped = [], []
    chapter, seen = 1, False
    for block in re.split(r"(^##\s.*$)", script, flags=re.M):
        if HEADING.fullmatch(block):
            number = NUMBER.match(block)
            chapter = int(number[1]) if number else chapter + seen
            seen = True
            continue
        for paragraph in re.split(r"\n\s*\n", block):
            if not paragraph.strip():
                continue
            cleaned = plain_text(paragraph, lang)
            for segment in segments(cleaned):
                spoken, words = gl.spoken_text(segment, lang, mapping)
                stripped += [w for w in words if w not in stripped]
                scenes.append({"chapter": chapter, "paragraph": segment, "tts": spoken,
                               "estimated_seconds": round(len(segment.split()) / wpm * 60, 2),
                               "image_prompt": "Vietnamese folk-tale setting, gentle cinematic illustration; " + segment})
    if not scenes:
        raise ValueError("Không có đoạn văn để chuẩn bị TTS.")
    atomic_write(folder / f"{lang}.tts.txt", "\n".join(scene["tts"] for scene in scenes) + "\n")
    save_json(folder / f"{lang}.scenes.json", scenes)
    total = round(sum(s["estimated_seconds"] for s in scenes) / 60, 1)
    print(f"Đã chuẩn bị {len(scenes)} đoạn TTS và cảnh cho {lang} (~{total} phút).")
    if mapping:
        print(f"  Phiên âm theo glossary: {len(mapping)} tên.")
    if stripped:
        print(f"  Chưa có phát âm, đã tự bỏ dấu: {', '.join(stripped)}. "
              f"Thêm vào mục '## Pronunciation' của {glossary_path.name} để đọc chuẩn hơn.")


def prep(story_id, lang):
    folder = story_dir(story_id)
    final = folder / f"{lang}.final.txt"
    if (folder / f"{lang}.NEEDS_REVIEW").exists():
        raise ValueError("Bản cuối chưa đạt; cần sửa và chấm lại trước khi prep.")
    script = read(final)
    approved = False
    for path in folder.glob(f"{lang}.round*.score.json"):
        draft = path.with_name(path.name.replace(".score.json", ".txt"))
        if draft.exists() and read(draft) == script and evaluate(json.loads(read(path)), script, lang)["pass"]:
            approved = True
            break
    if not approved:
        raise ValueError("Không tìm thấy vòng chấm đạt tương ứng chính xác với bản cuối.")
    build(script, lang, folder, folder / f"glossary.{lang}.md")


def prep_translation(directory, lang):
    """Chuẩn bị TTS cho bản dịch của tools/translate_review.py (đường dịch từ bản Việt)."""
    folder = Path(directory).resolve()
    script_path, review_path = folder / f"{lang}.md", folder / f"{lang}.review.json"
    if not script_path.exists() or not review_path.exists():
        raise ValueError(f"Thiếu {script_path.name} hoặc {review_path.name}; chạy translate_review.py trước.")
    script, review = read(script_path), json.loads(read(review_path))
    if review.get("translation_sha") != gl.sha(script):
        raise ValueError(f"{script_path.name} đã bị sửa sau lần review; chạy lại translate_review.py để chấm lại.")
    if not review.get("pass"):
        raise ValueError(f"Bản dịch {lang} chưa đạt ({review.get('score', 0):.2f}); xem {lang}.review.md.")
    length = length_check(script, lang)
    if not length["ok"]:
        raise ValueError(length["fix"])
    build(script, lang, folder, folder / f"glossary.{lang}.md")


def run(args):
    prep(args.id, args.lang)


def run_translation(args):
    for lang in languages(args.lang):
        prep_translation(args.dir, lang)
