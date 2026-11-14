"""
Tabbit CLI 公共调用模块
----------------------
提供 CLI 路径解析和 Node.js 脚本执行能力，
供 Agent 工具（tools/tabbit.py）和 HTTP 插件端点（server.py）共同复用。
"""

import os
import json
import tempfile
import subprocess
import uuid
import shutil


# ─── CLI 路径解析 ────────────────────────────────────────────────

def resolve_cli_path():
    """
    按优先级查找 tabbit-cli 可执行文件：
    1. 环境变量 TABBIT_CLI（最灵活，跨平台可用）
    2. 系统 PATH 中查找 tabbit-cli（Linux/macOS 装到 PATH 的情况）
    3. Windows 默认安装路径（%LOCALAPPDATA%\\Tabbit\\LocalAgent\\bin\\tabbit-cli.exe）
    找不到则返回 None（不抛异常，由调用方决定如何处理）。
    """
    # 1. 环境变量
    env_path = os.environ.get("TABBIT_CLI", "").strip()
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. 系统 PATH 搜索（支持 tabbit-cli 和 tabbit-cli.exe）
    for name in ("tabbit-cli", "tabbit-cli.exe"):
        found = shutil.which(name)
        if found:
            return found

    # 3. Windows 默认路径兜底
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        win_path = os.path.join(localappdata, "Tabbit", "LocalAgent", "bin", "tabbit-cli.exe")
        if os.path.exists(win_path):
            return win_path

    return None


# ─── 内部解码辅助 ────────────────────────────────────────────────

def _decode(b):
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


# ─── CLI 执行核心 ────────────────────────────────────────────────

def run_cli(js_code, timeout_ms=60000):
    """
    把一段 Node.js 代码交给 tabbit-cli 执行，返回其 JSON 结果。

    Args:
        js_code:    在浏览器上下文里执行的 Node.js 代码字符串
        timeout_ms: 总超时毫秒数（CLI 内部 + subprocess 外层各有兜底）

    Returns:
        dict: CLI 返回的 JSON 结果（status / result / error 等字段）

    Raises:
        RuntimeError: CLI 不可用、执行超时或 CLI 本身报错
    """
    cli = resolve_cli_path()
    if not cli:
        raise RuntimeError(
            "找不到 tabbit-cli。请确认已安装 Tabbit 浏览器，"
            "或通过环境变量 TABBIT_CLI 指定可执行文件路径。"
        )

    # 写临时 JS 文件（CLI 需要文件输入，stdin 在某些平台行为不一致）
    request_id = "tb-" + uuid.uuid4().hex[:12]
    fd, prog = tempfile.mkstemp(suffix=".js", prefix="tabbit-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(js_code + "\n")

    try:
        # subprocess 外层超时比 CLI 内部超时多 5 秒作为缓冲
        subprocess_timeout_s = max(10, int(timeout_ms / 1000) + 5)
        proc = subprocess.run(
            [
                cli, "nodejs",
                "--task", "ai-assistant",
                "--request-id", request_id,
                "--timeout-ms", str(timeout_ms),
            ],
            stdin=open(prog, "r", encoding="utf-8"),
            capture_output=True,
            timeout=subprocess_timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Tabbit CLI 执行超时（>{timeout_ms}ms）")
    finally:
        try:
            os.unlink(prog)
        except OSError:
            pass

    stdout = _decode(proc.stdout).strip()
    stderr = _decode(proc.stderr).strip()

    # CLI 把 JSON 结果打印到 stdout，取第一行以 '{' 开头的行解析
    data = None
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if data is None:
        raise RuntimeError(
            f"CLI 返回格式异常，无法解析 JSON。\n"
            f"Stdout: {stdout[:500]}\nStderr: {stderr[:500]}"
        )

    if data.get("status") != "succeeded":
        raise RuntimeError(
            f"CLI 执行失败。\n"
            f"Status: {data.get('status')}\n"
            f"Result: {json.dumps(data.get('result', {}), ensure_ascii=False)[:500]}\n"
            f"Stderr: {stderr[:500]}"
        )

    return data.get("result", {})
