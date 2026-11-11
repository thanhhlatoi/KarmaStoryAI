import json
import re

from .cli_score import evaluate, score_round
from .cli_write import write_round
from .common import atomic_write, config, languages, read, story_dir


def report(folder):
    lines = ["# Báo cáo biên tập", "", "| Ngôn ngữ | Vòng | Điểm | Phút | Tiêu chí yếu nhất | Kết quả |",
             "|---|---:|---:|---:|---|---|"]
    for path in sorted(folder.glob("*.score.json")):
        match = re.fullmatch(r"(de|en|es)\.round(\d+)\.score\.json", path.name)
        if not match:
            continue
        script = folder / f"{match[1]}.round{match[2]}.txt"
        result = evaluate(json.loads(read(path)), read(script) if script.exists() else None, match[1])
        weakest = min(result["criteria"], key=result["criteria"].get)
        minutes = result.get("length", {}).get("minutes", "?")
        lines.append(f"| {match[1]} | {match[2]} | {result['score']:.2f} | {minutes} | {weakest}: {result['criteria'][weakest]} | {'Đạt' if result['pass'] else 'Chưa đạt'} |")
    lines += ["", "## Kết quả", ""]
    for lang in ("de", "en", "es"):
        if (folder / f"{lang}.final.txt").exists():
            marker = folder / f"{lang}.NEEDS_REVIEW"
            lines.append(f"- {lang}: " + (read(marker).strip() if marker.exists() else "Đạt; đã xuất bản cuối."))
    atomic_write(folder / "report.md", "\n".join(lines) + "\n")


def reset(folder, lang):
    for path in folder.iterdir():
        if (re.fullmatch(rf"{lang}\.round\d+\.(txt|draft\.txt|score\.json|score\.raw\.txt)", path.name)
                or path.name in {f"{lang}.final.txt", f"{lang}.NEEDS_REVIEW", f"{lang}.tts.txt", f"{lang}.scenes.json"}):
            path.unlink()


def loop(story_id, lang, force=False):
    folder = story_dir(story_id)
    if force:
        reset(folder, lang)
        report(folder)
    previous = ""
    best = None
    for number in range(1, config()["max_rounds"] + 1):
        target = write_round(story_id, lang, number, fixes=previous)
        result = score_round(story_id, lang, number)
        if best is None or result["score"] > best[0]:
            best = (result["score"], number, result)
        report(folder)
        if result["pass"]:
            atomic_write(folder / f"{lang}.final.txt", read(target))
            (folder / f"{lang}.NEEDS_REVIEW").unlink(missing_ok=True)
            report(folder)
            return result
        previous = ("REVISION INSTRUCTIONS:\n" + "\n".join(f"- {fix}" for fix in result["fixes"]) +
                    "\nCriterion scores: " + json.dumps(result["criteria"], ensure_ascii=False) +
                    "\nRewrite the entire script, correcting the weak criteria.\nPREVIOUS DRAFT:\n" + read(target))
    _, number, result = best
    atomic_write(folder / f"{lang}.final.txt", read(folder / f"{lang}.round{number}.txt"))
    weakest = min(result["criteria"], key=result["criteria"].get)
    reason = (f"Cần duyệt: hết {config()['max_rounds']} vòng; chọn vòng {number}, "
              f"điểm {result['score']:.2f}; tiêu chí yếu nhất {weakest}={result['criteria'][weakest]}. "
              f"Yêu cầu tổng >= {config()['score_threshold']}, mỗi tiêu chí >= {config()['min_each_criterion']}.\n" +
              "\n".join(result["fixes"]) + "\n")
    atomic_write(folder / f"{lang}.NEEDS_REVIEW", reason)
    report(folder)
    return result


def run(args):
    for lang in languages(args.lang):
        loop(args.id, lang, args.force)
