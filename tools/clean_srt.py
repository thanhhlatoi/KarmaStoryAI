"""Lam sach phu de tu dong YouTube (.srt) -> van ban lien mach.

Dung: python3 tools/clean_srt.py file.srt [-o out.txt] [--gap 2.5]
Bo cue lap/rong, noi cac dong thanh doan (ngat doan khi im lang > --gap giay).
"""
import argparse
import re
import sys
from pathlib import Path

TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def clean(text, gap=2.5):
    paras, cur, last, prev_end = [], [], None, None
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = block.strip().splitlines()
        ts = next((TS.match(l) for l in lines if TS.match(l)), None)
        if not ts:
            continue
        start, end = secs(*ts.groups()[:4]), secs(*ts.groups()[4:])
        new = False
        for l in lines:
            l = re.sub(r"<[^>]+>", "", l).strip()
            if not l or l.isdigit() or TS.match(l) or re.fullmatch(r"\[[^\]]*\]", l):
                continue
            if l == last:
                continue  # dong lap cua phu de cuon
            if prev_end is not None and start - prev_end > gap and cur and not new:
                paras.append(" ".join(cur)); cur = []
            cur.append(l); last = l; new = True
        prev_end = end
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("srt"); ap.add_argument("-o", "--out"); ap.add_argument("--gap", type=float, default=2.5)
    a = ap.parse_args()
    src = Path(a.srt)
    out = Path(a.out) if a.out else src.with_suffix(".txt")
    txt = clean(src.read_text(encoding="utf-8-sig", errors="replace"), a.gap)
    out.write_text(txt + "\n", encoding="utf-8")
    print(f"{src.name}: {len(txt.split())} tu -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
