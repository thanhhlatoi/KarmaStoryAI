"""Provider CLI/OpenAI, gọi tuần tự, timeout và retry; không log nội dung."""
import contextlib
import fcntl
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from .common import DEFAULT_PROVIDERS, config, root


_TAG = None


@contextlib.contextmanager
def tagged(tag):
    """Gắn nhãn (vd '017/de') cho mọi lần gọi model trong khối, để thống kê chi phí theo truyện."""
    global _TAG
    previous, _TAG = _TAG, tag
    try:
        yield
    finally:
        _TAG = previous


class Completion(str):
    def __new__(cls, text, truncated=False):
        result = super().__new__(cls, text)
        result.truncated = truncated
        return result


def _openai(provider, prompt, timeout):
    url = os.environ.get(provider.get("base_url_env", "ROUTER_URL"), "").rstrip("/")
    key = os.environ.get(provider.get("key_env", "ROUTER_KEY"), "")
    model = os.environ.get(provider.get("model_env", "ROUTER_MODEL"), "")
    if not all((url, key, model)):
        raise ValueError("Thiếu biến môi trường URL, API key hoặc model cho provider OpenAI.")
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL provider phải bắt đầu bằng http:// hoặc https://.")
    endpoint = url if url.endswith("/chat/completions") else url + "/chat/completions"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": provider.get("max_tokens", 8192)}
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"API trả HTTP {exc.code}.") from None
    except urllib.error.URLError:
        raise RuntimeError("Không kết nối được API model.") from None
    choice = data["choices"][0]
    return Completion(choice["message"]["content"], choice.get("finish_reason") == "length")


def _cli(provider, prompt, timeout):
    command = provider.get("cmd")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
        raise ValueError("cmd phải là danh sách tên lệnh và các đối số.")
    try:
        result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                encoding="utf-8", timeout=timeout, cwd=root())
    except FileNotFoundError:
        raise RuntimeError(f"Không tìm thấy lệnh {command[0]}.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Lệnh model quá thời gian {timeout} giây.") from None
    if result.returncode:
        # stderr có thể chứa prompt/key, không đưa vào log hay thông báo.
        raise RuntimeError(f"Lệnh {command[0]} thất bại (mã {result.returncode}).")
    return Completion(result.stdout)


def _codex_router(provider, prompt, timeout):
    """Codex Responses API qua router; không cần đăng nhập OpenAI."""
    settings_path = Path(provider["credentials_file"]).expanduser()
    credentials = json.loads(settings_path.read_text(encoding="utf-8"))
    url = credentials["base_url"].rstrip("/")
    model = provider.get("model", credentials.get("model"))
    if not url.startswith(("http://", "https://")) or not model:
        raise ValueError("Thiếu URL hoặc model Codex router.")
    env = os.environ.copy()
    env["KARMA_CODEX_ROUTER_KEY"] = credentials["api_key"]
    # Output riêng tránh lẫn banner, tiến độ và reasoning của CLI vào kịch bản.
    with tempfile.TemporaryDirectory(prefix="karma-codex-") as directory:
        output = Path(directory) / "answer.txt"
        command = provider.get("cmd", ["npx", "--yes", "@openai/codex"])
        command = command + ["exec", "--ignore-user-config", "--skip-git-repo-check",
            "--ephemeral", "--sandbox", "read-only", "--color", "never",
            "-c", 'model_provider="karma_router"', "-m", model,
            "-c", 'model_providers.karma_router.name="9router"',
            "-c", "model_providers.karma_router.base_url=" + json.dumps(url),
            "-c", 'model_providers.karma_router.wire_api="responses"',
            "-c", 'model_providers.karma_router.env_key="KARMA_CODEX_ROUTER_KEY"',
            "-c", 'model_providers.karma_router.requires_openai_auth=false',
            "-o", str(output), "-"]
        try:
            result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                encoding="utf-8", timeout=timeout, cwd=directory, env=env)
        except FileNotFoundError:
            raise RuntimeError("Không tìm thấy Codex CLI hoặc npx.") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Codex quá thời gian {timeout} giây.") from None
        if result.returncode or not output.exists():
            raise RuntimeError(f"Codex qua 9router thất bại (mã {result.returncode}); kiểm tra URL, model và Responses API.")
        return Completion(output.read_text(encoding="utf-8"))


def complete(role, prompt):
    if role not in DEFAULT_PROVIDERS:
        raise ValueError(f"Vai trò model không hợp lệ: {role}")
    settings = config()
    provider = settings.get("llm", {}).get(role, settings.get(role, DEFAULT_PROVIDERS[role]))
    timeout = float(provider.get("timeout", 300))
    attempts = min(3, max(1, int(provider.get("attempts", 3))))
    work = root() / "work"
    work.mkdir(parents=True, exist_ok=True)
    # Khóa liên tiến trình: mọi lần gọi writer/scorer dùng chung một hàng đợi.
    with (work / "llm.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for attempt in range(attempts):
            start = time.monotonic()
            error = None
            try:
                kind = provider.get("type", "cli")
                if kind == "cli":
                    answer = _cli(provider, prompt, timeout)
                elif kind == "openai":
                    answer = _openai(provider, prompt, timeout)
                elif kind == "codex_router":
                    answer = _codex_router(provider, prompt, timeout)
                else:
                    raise ValueError(f"Loại provider không hỗ trợ: {kind}")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Model trả nội dung rỗng.")
            except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
                error = exc
            entry = {"time": datetime.now(timezone.utc).isoformat(), "role": role, "tag": _TAG,
                     "prompt_length": len(prompt),
                     "answer_length": len(answer) if error is None else 0,
                     "seconds": round(time.monotonic() - start, 3),
                     "success": error is None, "attempt": attempt + 1}
            with (work / "llm.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry) + "\n")
            if error is None:
                return answer
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Gọi model {role} thất bại sau {attempts} lần: {error}") from None
