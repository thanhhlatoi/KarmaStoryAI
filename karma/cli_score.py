import json
import math
import re

from . import llm
from .common import atomic_write, config, length_check, read, render, root, save_json, story_dir

CRITERIA = ("hook", "twist", "nhip", "tu_nhien", "nhan_qua", "viet_nam")


def parse_score(text):
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
            if "criteria" in value:
                return value
    if candidates:
        return candidates[0]
    raise ValueError("Không tìm thấy JSON hợp lệ trong kết quả chấm điểm.")


def rubric_weights():
    weights = {}
    for name, weight in re.findall(r"\|\s*(\w+)\s*\|\s*(\d+(?:\.\d+)?)%\s*\|", read(root() / "rubric.md")):
        weights[name] = float(weight)
    if set(weights) != set(CRITERIA) or any(w <= 0 for w in weights.values()):
        raise ValueError("Rubric phải có đủ 6 tiêu chí với trọng số dương.")
    return weights


def evaluate(data, script=None, lang=None):
    criteria = data.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(CRITERIA):
        raise ValueError("JSON chấm điểm phải có đủ đúng 6 tiêu chí: " + ", ".join(CRITERIA))
    for name, value in criteria.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError(f"Điểm {name} phải là số trong khoảng 0–10.")
    fixes = data.get("fixes", [])
    if not isinstance(fixes, list) or not all(isinstance(fix, str) for fix in fixes):
        raise ValueError("fixes phải là danh sách chuỗi.")
    weights = rubric_weights()
    score = sum(criteria[name] * weight for name, weight in weights.items()) / sum(weights.values())
    settings = config()
    passed = score >= settings["score_threshold"] and min(criteria.values()) >= settings["min_each_criterion"]
    result = {"score": score, "criteria": criteria, "pass": passed, "fixes": fixes}
    if script is not None and lang is not None:
        # Độ dài đo bằng code, không tin model: ngoài khoảng target_minutes là chưa đạt.
        length = length_check(script, lang, settings)
        result["length"] = {k: length[k] for k in ("minutes", "words", "ok")}
        if not length["ok"]:
            result["pass"] = False
            result["fixes"] = [length["fix"]] + [f for f in fixes if not f.startswith("ĐỘ DÀI:")]
    return result


def score_round(story_id, lang, number, force=False):
    folder = story_dir(story_id)
    target = folder / f"{lang}.round{number}.score.json"
    raw = folder / f"{lang}.round{number}.score.raw.txt"
    script = read(folder / f"{lang}.round{number}.txt")
    if target.exists() and not force:
        result = evaluate(json.loads(read(target)), script, lang)
        save_json(target, result)
        return result
    if force:
        target.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
    if not raw.exists():
        prompt = render("score.md", lang=lang, rubric=read(root() / "rubric.md"),
                        skeleton=read(folder / "skeleton.md"), script=script)
        prompt += ("\nLưu ý: không có bản nguồn trong lượt chấm này. Chỉ đối chiếu bộ xương; "
                   "không tuyên bố đã kiểm tra sao chép so với bản nguồn không được cung cấp.")
        atomic_write(raw, llm.complete("scorer", prompt))
    result = evaluate(parse_score(read(raw)), script, lang)
    save_json(target, result)
    length = result["length"]
    print(f"{lang} vòng {number}: {result['score']:.2f}, ~{length['minutes']} phút — "
          f"{'đạt' if result['pass'] else 'chưa đạt'}" + ("" if length["ok"] else " (sai độ dài)"))
    return result


def run(args):
    score_round(args.id, args.lang, args.round, args.force)
