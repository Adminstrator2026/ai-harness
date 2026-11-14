"""
静态文件 HTTP 快速预览工具
--------------------------
内部调 terminal_run 启动 `python -m http.server`。
返回 session_id + 访问 URL，让 AI 把它展示给用户或自己 fetch 验证。
"""

import socket
from .base import Tool, ToolResult
from . import register
from .terminal import _run as _terminal_run  # 复用 terminal_run 的实现
from ..config import CONFIG


def _find_free_port(start: int = 8766, max_tries: int = 100) -> int | None:
    """从 start 起找一个空闲端口"""
    for offset in range(max_tries):
        port = start + offset
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
            continue
    return None


def _http_serve(args, ctx):
    from pathlib import Path

    path_arg = args.get("path") or "."
    port = int(args.get("port") or 0)  # 0 = 自动找

    target = Path(path_arg).expanduser()
    if not target.is_absolute():
        target = CONFIG.WORKDIR / target
    target = target.resolve()
    try:
        target.relative_to(CONFIG.WORKDIR)
    except ValueError:
        raise ValueError(f"路径越界：{target}")
    if not target.exists():
        raise FileNotFoundError(f"路径不存在：{target}")

    if port == 0:
        port = _find_free_port()
        if port is None:
            return ToolResult(text="❌ 无法找到空闲端口（尝试了 100 个）")

    # 构造启动命令
    # 用 python -m http.server --directory 或 cd && python -m http.server
    import sys
    python_exe = sys.executable

    if target.is_dir():
        # Python 3.7+ 支持 --directory
        cmd = f'"{python_exe}" -m http.server {port} --directory "{target}"'
    else:
        raise IsADirectoryError(f"必须传入目录路径，文件不支持：{target}")

    # 复用 terminal_run 启动后台
    result = _terminal_run({"command": cmd, "shell": "cmd", "cwd": str(CONFIG.WORKDIR)}, {"cfg": ctx.get("cfg")})

    # 从 result.text 里提取 session_id（简单正则）
    import re
    m = re.search(r"session_id.*?:\s*`([^`]+)`", result.text)
    sid = m.group(1) if m else "?"

    url = f"http://localhost:{port}/"
    rel = target.relative_to(CONFIG.WORKDIR)

    return ToolResult(
        text=(
            f"🌐 静态服务器已启动\n"
            f"• 目录：`{rel}`\n"
            f"• 端口：{port}\n"
            f"• 访问地址：**{url}**\n"
            f"• 会话 ID：`{sid}`\n\n"
            f"💡 可以用 web_fetch 访问验证，用 terminal_stop('{sid}') 关闭。"
        )
    )


def register_all():
    register(Tool(
        name="http_serve", title="静态文件预览", perm="Root",
        desc=(
            "在后台启动一个 python http.server，让指定目录可通过浏览器访问。"
            "自动分配空闲端口。依赖 terminal_run。"
        ),
        usage='{"path":"./dist","port":8766}',
        required={"path": "string"}, handler=_http_serve,
    ))
