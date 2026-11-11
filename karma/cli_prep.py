import json
import re

from .cli_score import evaluate
from .common import atomic_write, read, save_json, story_dir
from .numbers import expand_numbers


def plain_text(text, lang):
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s*(?:#{1,6}\s*|>\s*|[-*+]\s+|\d+[.)]\s+)", "", text, flags=re.M)
    text = re.sub(r"[*_`~#]", "", text)
    text = expand_numbers(text, lang)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?…":
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
    scenes = []
    chapter = 1
    for block in re.split(r"(^## Chapter \d+[^\n]*$)", script, flags=re.M):
        heading = re.match(r"^## Chapter (\d+)", block)
        if heading:
            chapter = int(heading[1])
            continue
        for paragraph in re.split(r"\n\s*\n", block):
            cleaned = plain_text(paragraph, lang)
            for segment in segments(cleaned):
                scenes.append({"chapter": chapter, "paragraph": segment,
                               "estimated_seconds": round(len(segment.split()) / 150 * 60, 2),
                               "image_prompt": "Vietnamese folk-tale setting, gentle cinematic illustration; " + segment})
    if not scenes:
        raise ValueError("Không có đoạn văn để chuẩn bị TTS.")
    atomic_write(folder / f"{lang}.tts.txt", "\n".join(scene["paragraph"] for scene in scenes) + "\n")
    save_json(folder / f"{lang}.scenes.json", scenes)
    print(f"Đã chuẩn bị {len(scenes)} đoạn TTS và cảnh cho {lang}.")


def run(args):
    prep(args.id, args.lang)
