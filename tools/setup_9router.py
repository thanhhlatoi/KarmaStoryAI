"""Nối Karma với kết nối 9router có sẵn, không in hoặc commit API key."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karma.common import atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(Path.home()/".config/opencode/opencode.jsonc"))
    parser.add_argument("--model", default="cx/gpt-6.1-sol")
    parser.add_argument("--stories-dir", required=True)
    args = parser.parse_args()
    # Cấu hình nguồn hiện có là JSON hợp lệ; không sửa cấu hình của ứng dụng nguồn.
    source = json.loads(Path(args.source).expanduser().read_text(encoding="utf-8"))
    options = source["provider"]["9router"]["options"]
    key = options["apiKey"]
    if key.startswith("{env:") and key.endswith("}"):
        key = os.environ.get(key[5:-1], "")
    if not key or key.startswith("{file:"):
        parser.error("Không đọc được khóa từ cấu hình nguồn; cần khóa hoặc biến môi trường hợp lệ.")
    private = Path.home()/".config/karma/9router.json"
    private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(private, json.dumps({"base_url": options["baseURL"], "api_key": key,
                                     "model": args.model}, indent=2)+"\n")
    private.chmod(0o600)
    root = Path(__file__).resolve().parent.parent
    local = {"stories_dir": str(Path(args.stories_dir).expanduser().resolve()), "llm": {
        "writer": {"type": "codex_router", "credentials_file": str(private),
                   "model": args.model, "timeout": 900, "attempts": 1},
        "scorer": {"type": "cli", "cmd": ["claude", "-p", "--tools", "",
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--disable-slash-commands", "--no-session-persistence"],
                    "timeout": 600, "attempts": 1}}}
    target = root/"config.local.json"
    if target.exists():
        parser.error("config.local.json đã có; giữ nguyên cấu hình hiện tại, không ghi đè.")
    atomic_write(target, json.dumps(local, ensure_ascii=False, indent=2)+"\n")
    print("Đã cấu hình Codex CLI qua 9router và Claude CLI; khóa được lưu riêng với quyền 0600.")
    print("Thư mục kịch bản:", local["stories_dir"])


if __name__ == "__main__":
    main()
