"""
等待工具 — 让 Agent 显式暂停若干秒
----------------------------------
看似简单，但解决了"启动服务 → 等 ready → 再发请求"的流程链。
最大 300 秒（5 分钟），防止 AI 死循环 sleep。
"""

import time
from .base import Tool, ToolResult
from . import register


def _wait(args, ctx):
    seconds = args.get("seconds", args.get("secs"))
    if seconds is None:
        raise ValueError("必须提供 seconds 参数")
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise ValueError(f"seconds 必须是数字，收到：{seconds}")

    if seconds < 0:
        seconds = 0
    if seconds > 300:
        seconds = 300

    time.sleep(seconds)
    return ToolResult(text=f"⏳ 已等待 {seconds}s")


def register_all():
    register(Tool(
        name="wait", title="等待", perm="Visitor",
        desc="暂停执行若干秒（最大 300s）。常用于等待服务器启动、构建完成等场景。",
        usage='{"seconds": 3}',
        required={"seconds": "string"}, handler=_wait,
    ))
