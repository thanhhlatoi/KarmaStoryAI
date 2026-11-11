import re

from . import llm
from .common import atomic_write, config, languages, read, render, story_dir, target_words

END_MARKER = "[[END_SCRIPT]]"


def write_round(story_id, lang, number, fixes="", force=False):
    folder = story_dir(story_id)
    target = folder / f"{lang}.round{number}.txt"
    draft = folder / f"{lang}.round{number}.draft.txt"
    if target.exists() and not force:
        return target
    if force:
        draft.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        (folder / f"{lang}.round{number}.score.json").unlink(missing_ok=True)
        (folder / f"{lang}.round{number}.score.raw.txt").unlink(missing_ok=True)
    settings = config()
    minutes = "–".join(map(str, settings["target_minutes"]))
    low, high = target_words(lang, settings)
    prompt = render(f"write_{lang}.md", skeleton=read(folder / "skeleton.md"),
                    minutes=minutes, words=f"{low:,}–{high:,}", fixes=fixes)
    prompt += (f"\nFinish the entire story with the exact marker {END_MARKER}. "
               "Use ## Chapter N headings. If space runs out, stop at a chapter boundary; "
               "do not use the ending marker until the full story is finished.")
    script = read(draft) if draft.exists() else ""
    if END_MARKER in script:
        atomic_write(target, script.split(END_MARKER)[0].strip() + "\n")
        draft.unlink(missing_ok=True)
        return target
    for _ in range(int(settings.get("max_continuations", 8)) + 1):
        continuation = ""
        if script:
            chapters = re.findall(r"^## Chapter (\d+)", script, re.M)
            continuation = ("\nPREVIOUS PART (do not repeat it):\n" + script +
                            f"\nContinue exactly where it stops (last chapter: {chapters[-1] if chapters else '1'}). "
                            "Finish the interrupted sentence/chapter first, then write remaining chapters. "
                            f"End with {END_MARKER} only when complete.")
        answer = llm.complete("writer", prompt + continuation)
        if not answer.strip():
            raise ValueError("Model viết trả nội dung rỗng.")
        script = (script.rstrip() + "\n" + answer.strip()).lstrip()
        atomic_write(draft, script + "\n")
        if END_MARKER in answer and not getattr(answer, "truncated", False):
            atomic_write(target, script.split(END_MARKER)[0].strip() + "\n")
            draft.unlink(missing_ok=True)
            print(f"Đã viết: {target.name}")
            return target
    raise RuntimeError(f"Chưa hoàn tất {target.name}; bản dở đã lưu ở {draft.name}. Chạy lại để tiếp tục.")


def run(args):
    folder = story_dir(args.id)
    for lang in languages(args.lang):
        numbers = [int(m[1]) for p in folder.glob(f"{lang}.round*.txt")
                   if (m := re.fullmatch(rf"{lang}\.round(\d+)\.txt", p.name))]
        drafts = [int(m[1]) for p in folder.glob(f"{lang}.round*.draft.txt")
                  if (m := re.fullmatch(rf"{lang}\.round(\d+)\.draft\.txt", p.name))]
        number = args.round or (min(drafts) if drafts else max(numbers, default=0) + 1)
        write_round(args.id, lang, number, force=args.force)
