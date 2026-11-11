"""Chấm trực tiếp file kịch bản bất kỳ (ví dụ bản đã viết lại bằng Codex bên ngoài)."""
from pathlib import Path

from . import llm
from .cli_score import evaluate, parse_score
from .common import LANGUAGES, atomic_write, read, render, root, save_json
from .glossary import sha

GRADE_LANGUAGES = LANGUAGES + ("vi",)


def guess_lang(path):
    for part in Path(path).name.lower().replace("-", ".").replace("_", ".").split("."):
        if part in GRADE_LANGUAGES:
            return part
    return None


def grade_file(path, lang, skeleton_path=None, force=False):
    path = Path(path).resolve()
    target = path.with_name(path.name + ".score.json")
    raw = path.with_name(path.name + ".score.raw.txt")
    if force:
        target.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
    if not raw.exists():
        skeleton = read(skeleton_path) if skeleton_path else "(Không có bộ xương; chấm độc lập theo rubric.)"
        prompt = render("score.md", lang=lang, rubric=read(root() / "rubric.md"),
                        skeleton=skeleton, script=read(path))
        prompt += ("\nLưu ý: không có bản nguồn trong lượt chấm này. Không tuyên bố đã kiểm tra "
                   "sao chép so với bản nguồn không được cung cấp.")
        if lang == "vi":
            prompt += ("\nĐây là BẢN VIỆT GỐC sẽ được dịch sang de/en/es cho người nghe 60+ ở châu Âu/Mỹ. "
                       "Chấm như kịch bản kể chuyện; ở tiêu chí tu_nhien xét giọng kể miệng tiếng Việt, "
                       "và ghi vào fixes những chỗ sẽ khó hiểu khi dịch cho người nước ngoài.")
        atomic_write(raw, llm.complete("scorer", prompt))
    result = evaluate(parse_score(read(raw)), read(path), lang)
    result["source_sha"] = sha(read(path))   # để biết bản đã sửa sau lần chấm
    save_json(target, result)
    print(f"{path.name} [{lang}]: {result['score']:.2f}, ~{result['length']['minutes']} phút — "
          f"{'ĐẠT' if result['pass'] else 'CHƯA ĐẠT'}")
    print("  " + ", ".join(f"{k}={v}" for k, v in result["criteria"].items()))
    for fix in result["fixes"]:
        print(f"  - {fix}")
    print(f"  → {target}")
    return result


def run(args):
    failed = 0
    for name in args.files:
        lang = args.lang or guess_lang(name)
        if lang is None:
            raise ValueError(f"Không đoán được ngôn ngữ của {name}; dùng --lang de|en|es|vi.")
        try:
            with llm.tagged(f"grade/{Path(name).stem[:40]}/{lang}"):
                grade_file(name, lang, args.skeleton, args.force)
        except (OSError, ValueError, RuntimeError) as exc:
            failed += 1
            print(f"{name}: lỗi — {exc}")
    if failed:
        raise RuntimeError(f"{failed}/{len(args.files)} file chấm lỗi.")
