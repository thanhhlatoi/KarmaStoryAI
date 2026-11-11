"""Cấu hình, đường dẫn và ghi file nguyên tử."""
import json
import math
import os
import re
import tempfile
from pathlib import Path

LANGUAGES = ("de", "en", "es")
DEFAULT_PROVIDERS = {
    "writer": {"type": "cli", "cmd": ["codex", "exec"]},
    "scorer": {"type": "cli", "cmd": ["claude", "-p"]},
}


def root():
    return Path(os.environ.get("KARMA_ROOT", Path(__file__).resolve().parent.parent)).resolve()


def config():
    data = json.loads((root() / "config.json").read_text(encoding="utf-8"))
    local = root() / "config.local.json"
    if local.exists():
        overrides = json.loads(local.read_text(encoding="utf-8"))
        data.update(overrides)
    for key in ("score_threshold", "min_each_criterion"):
        value = data.get(key, 8.0 if key == "score_threshold" else 6.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError(f"Cấu hình {key} phải nằm trong khoảng 0–10.")
        data[key] = value
    rounds = data.get("max_rounds", 5)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1:
        raise ValueError("max_rounds phải là số nguyên dương.")
    data["max_rounds"] = rounds
    minutes = data.get("target_minutes", [30, 40])
    if (not isinstance(minutes, list) or len(minutes) != 2 or
            not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in minutes)
            or minutes[0] > minutes[1]):
        raise ValueError("target_minutes phải là [tối thiểu, tối đa] số phút dương.")
    data["target_minutes"] = minutes
    return data


def words_per_minute(lang, settings=None):
    settings = settings or config()
    value = settings.get("words_per_minute", {}).get(lang, 150)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"words_per_minute.{lang} phải là số dương.")
    return value


def target_words(lang, settings=None):
    """Khoảng số từ ứng với target_minutes cho ngôn ngữ lang."""
    settings = settings or config()
    low, high = settings["target_minutes"]
    wpm = words_per_minute(lang, settings)
    return round(low * wpm), round(high * wpm)


def length_check(text, lang, settings=None):
    """Đo thời lượng đọc ước tính; trả dict minutes/ok/fix (fix rỗng khi đạt)."""
    settings = settings or config()
    low, high = settings["target_minutes"]
    wpm = words_per_minute(lang, settings)
    words = len(re.sub(r"(?m)^#+.*$", "", text).split())
    exact = words / wpm
    minutes = round(exact, 1)
    fix = ""
    if exact > high:
        fix = (f"ĐỘ DÀI: khoảng {minutes} phút ({words} từ), vượt tối đa {high} phút. "
               f"Cắt khoảng {words - round(high * wpm * 0.95)} từ: gộp cảnh lặp, rút đoạn giải thích, giữ hook, manh mối và kết.")
    elif exact < low:
        fix = (f"ĐỘ DÀI: khoảng {minutes} phút ({words} từ), dưới tối thiểu {low} phút. "
               f"Viết thêm khoảng {round(low * wpm * 1.05) - words} từ bằng cảnh và đối thoại, không độn lời kể.")
    return {"minutes": minutes, "words": words, "ok": not fix, "fix": fix}


def story_dir(story_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", story_id):
        raise ValueError("Mã truyện chỉ được chứa chữ, số, dấu - và _.")
    folder = root() / config().get("stories_dir", "stories") / story_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def render(name, **values):
    template = read(root() / "prompts" / name)
    # Một lượt thay thế: nội dung được chèn không thể trở thành placeholder mới.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m[1]]) if m[1] in values else m[0], template)


def languages(value):
    return LANGUAGES if value == "all" else (value,)
