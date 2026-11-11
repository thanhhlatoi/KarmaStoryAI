import argparse
import sys

from . import cli_clean, cli_grade, cli_loop, cli_prep, cli_score, cli_skeleton, cli_usage, cli_write


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Vòng phải là số nguyên dương.")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Biên tập truyện Việt thành kịch bản de/en/es.")
    commands = parser.add_subparsers(dest="command", required=True)
    clean = commands.add_parser("clean", help="Làm sạch nguồn .srt hoặc .txt")
    clean.add_argument("file")
    clean.add_argument("--story", required=True)
    clean.set_defaults(handler=cli_clean.run)
    skeleton = commands.add_parser("skeleton", help="Tạo bộ xương truyện")
    skeleton.add_argument("id")
    skeleton.add_argument("--force", action="store_true")
    skeleton.set_defaults(handler=cli_skeleton.run)
    grade = commands.add_parser("grade", help="Chấm trực tiếp file kịch bản bất kỳ bằng Claude")
    grade.add_argument("files", nargs="+")
    grade.add_argument("--lang", choices=("de", "en", "es", "vi"),
                       help="Mặc định đoán từ tên file (vd en.txt); bản Việt dùng --lang vi")
    grade.add_argument("--skeleton", help="Đường dẫn bộ xương để đối chiếu (tùy chọn)")
    grade.add_argument("--force", action="store_true", help="Gọi Claude chấm lại")
    grade.set_defaults(handler=cli_grade.run)
    for name, module in (("write", cli_write), ("score", cli_score), ("loop", cli_loop), ("prep", cli_prep)):
        command = commands.add_parser(name, help={"write": "Viết kịch bản", "score": "Chấm và tính lại điểm",
                                                "loop": "Viết/chấm đến khi đạt", "prep": "Chuẩn bị văn bản TTS và cảnh"}[name])
        command.add_argument("id")
        command.add_argument("--lang", required=True, choices=("de", "en", "es", "all") if name in ("write", "loop") else ("de", "en", "es"))
        if name in ("write", "score"):
            command.add_argument("--round", type=positive, required=name == "score")
        if name != "prep":
            command.add_argument("--force", action="store_true")
        command.set_defaults(handler=module.run)
    prep_tr = commands.add_parser("prep-translation", help="Chuẩn bị TTS cho bản dịch đã đạt của translate_review.py")
    prep_tr.add_argument("dir", help="Thư mục --out-dir đã dùng khi dịch")
    prep_tr.add_argument("--lang", required=True, choices=("de", "en", "es", "all"))
    prep_tr.set_defaults(handler=cli_prep.run_translation)
    usage = commands.add_parser("usage", help="Thống kê số lần gọi model, ký tự và thời gian theo truyện")
    usage.add_argument("--tag", help="Lọc theo tiền tố nhãn, vd 017 hoặc 017/de")
    usage.add_argument("--since", help="Chỉ tính từ thời điểm ISO, vd 2026-11-11")
    usage.set_defaults(handler=cli_usage.run)
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Đã dừng; kết quả hoàn tất và bản dở đã lưu được giữ lại.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
