"""Thống kê các lần gọi model từ work/llm.log theo nhãn truyện/ngôn ngữ và vai trò."""
import json
from collections import defaultdict

from .common import read, root

CHARS_PER_TOKEN = 3   # ước lượng thô cho văn bản Việt/Âu trộn; chỉ để so sánh tương đối


def summarize(prefix=None, since=None):
    path = root() / "work" / "llm.log"
    if not path.exists():
        return []
    rows = defaultdict(lambda: {"calls": 0, "failed": 0, "prompt": 0, "answer": 0, "seconds": 0.0})
    for line in read(path).splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        tag = entry.get("tag") or "(không nhãn)"
        if prefix and not tag.startswith(prefix):
            continue
        if since and entry.get("time", "") < since:
            continue
        row = rows[(tag, entry.get("role", "?"))]
        row["calls"] += 1
        row["failed"] += not entry.get("success", False)
        row["prompt"] += entry.get("prompt_length", 0)
        row["answer"] += entry.get("answer_length", 0)
        row["seconds"] += entry.get("seconds", 0)
    return sorted(rows.items())


def run(args):
    rows = summarize(args.tag, args.since)
    if not rows:
        print("Chưa có lần gọi model nào khớp điều kiện.")
        return
    print("| Nhãn | Vai trò | Lần gọi | Lỗi | Ký tự vào | Ký tự ra | ~Token | Phút |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    total = defaultdict(float)
    for (tag, role), r in rows:
        tokens = (r["prompt"] + r["answer"]) // CHARS_PER_TOKEN
        print(f"| {tag} | {role} | {r['calls']} | {r['failed']} | {r['prompt']:,} | {r['answer']:,} | "
              f"{tokens:,} | {r['seconds'] / 60:.1f} |")
        for key in ("calls", "failed", "prompt", "answer", "seconds"):
            total[key] += r[key]
    tokens = int(total["prompt"] + total["answer"]) // CHARS_PER_TOKEN
    print(f"| **Tổng** | | {int(total['calls'])} | {int(total['failed'])} | {int(total['prompt']):,} | "
          f"{int(total['answer']):,} | {tokens:,} | {total['seconds'] / 60:.1f} |")
    print(f"\n~Token = ký tự / {CHARS_PER_TOKEN}, chỉ để so sánh; số thật xem ở trang tính phí của provider. "
          "Log cũ trước khi có nhãn được gộp vào '(không nhãn)' và không có ký tự ra.")
