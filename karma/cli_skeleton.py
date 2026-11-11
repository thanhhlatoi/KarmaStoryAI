import hashlib

from . import llm
from .common import atomic_write, read, render, story_dir


def build(story_id, force=False):
    folder = story_dir(story_id)
    target = folder / "skeleton.md"
    if target.exists() and not force:
        print(f"Đã có {target}; dùng --force để tạo lại.")
        return target
    source = read(folder / "source.txt")
    words = source.split()
    if not words:
        raise ValueError("Nguồn truyện trống.")
    # Cache theo nội dung và template, tránh dùng phần cũ khi nguồn thay đổi.
    signature = hashlib.sha256((source + render("skeleton.md", story="")).encode()).hexdigest()[:16]
    parts_dir = folder / "skeleton.parts" / signature
    if force and parts_dir.exists():
        for path in parts_dir.glob("*.md"):
            path.unlink()
    chunks = [" ".join(words[i:i + 3000]) for i in range(0, len(words), 3000)]
    parts = []
    for index, chunk in enumerate(chunks, 1):
        checkpoint = parts_dir / f"{index:03d}.md"
        if not checkpoint.exists():
            answer = llm.complete("writer", render("skeleton.md", story=chunk))
            if not answer.strip() or getattr(answer, "truncated", False):
                raise ValueError("Bộ xương bị rỗng hoặc bị cắt; hãy thử lại.")
            atomic_write(checkpoint, answer.strip() + "\n")
        parts.append(read(checkpoint))
    if len(parts) == 1:
        result = parts[0]
    else:
        material = "\n\n".join(f"PHẦN {i}\n{part}" for i, part in enumerate(parts, 1))
        result = llm.complete("writer", render("skeleton.md", story=material) +
                              "\nGộp các bộ xương theo trình tự, bỏ trùng, giữ manh mối và kết. Không viết kịch bản.")
        if not result.strip() or getattr(result, "truncated", False):
            raise ValueError("Bộ xương tổng hợp rỗng hoặc bị cắt; các phần đã được lưu.")
    atomic_write(target, result.strip() + "\n")
    print(f"Đã lưu bộ xương: {target}")
    return target


def run(args):
    with llm.tagged(f"{args.id}/skeleton"):
        build(args.id, args.force)
