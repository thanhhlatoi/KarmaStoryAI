from pathlib import Path

from tools.clean_srt import clean
from .common import atomic_write, story_dir


def run(args):
    source = Path(args.file)
    if source.suffix.lower() not in (".srt", ".txt"):
        raise ValueError("Đầu vào phải là file .srt hoặc .txt.")
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    result = clean(text) if source.suffix.lower() == ".srt" else text.strip()
    if not result.strip():
        raise ValueError("Nguồn không có nội dung sau khi làm sạch.")
    target = story_dir(args.story) / "source.txt"
    atomic_write(target, result + "\n")
    print(f"Đã làm sạch: {len(result.split())} từ → {target}")
