"""
持久化终端进程管理（terminal_run / terminal_stop / terminal_list）
-----------------------------------------------------------------
解决当前 run_cmd 是一次性 subprocess.run 的根本限制：
  AI 无法启动长期运行的进程（开发服务器、数据库、worker），
  等它 ready，测试，最后关掉。

设计：
  - TerminalSession: 单个后台进程的封装（Popen + stdout 后台线程 + 环形缓冲区）
  - TERMINALS 全局字典: session_id → TerminalSession
  - 三个工具:
      terminal_run   — 启动后台命令，返回 session_id
      terminal_stop  — 发送 SIGTERM/SIGKILL 并回收
      terminal_list  — 列出所有会话（running/exited + 最新输出）
"""

import os
import sys
import uuid
import time
import threading
import subprocess
from collections import deque
from pathlib import Path

from .base import Tool, ToolResult
from . import register
from ..config import CONFIG


# ─── 内部解码 ───────────────────────────────────────────────────

def _decode_bytes(b: bytes) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


# ─── 会话类 ─────────────────────────────────────────────────────

class TerminalSession:
    """一个后台运行的终端进程 + stdout/stderr 环形缓冲"""

    BUF_MAX = 2000  # 最多保留 2000 行输出（防止爆内存）

    def __init__(self, shell: str, command: str, cwd: str | None):
        self.id = "trm_" + uuid.uuid4().hex[:10]
        self.shell = shell
        self.command = command
        self.cwd = cwd or str(CONFIG.WORKDIR)
        self.created_at = time.time()
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self._lock = threading.Lock()
        self._buf: deque[str] = deque(maxlen=self.BUF_MAX)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """启动进程 + 后台线程收集输出"""
        # 根据 shell 类型构造 Popen 参数
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        if self.shell in ("cmd", "powershell", "pwsh"):
            # Windows 系：用 shell=True 更稳
            self._proc = subprocess.Popen(
                self.command,
                shell=True,
                cwd=self.cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # stderr 合并进 stdout，一条管道就够了
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        else:
            # Unix / 直接命令
            self._proc = subprocess.Popen(
                self.command,
                shell=True,
                cwd=self.cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )

        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._thread.start()

    def _collect(self) -> None:
        """后台线程：逐行读 stdout，追加到环形缓冲区"""
        assert self._proc and self._proc.stdout
        try:
            for raw_line in self._proc.stdout:
                line = raw_line.rstrip("\n").rstrip("\r")
                with self._lock:
                    self._buf.append(line)
        except Exception:
            pass

        # 进程结束
        if self._proc:
            self.exit_code = self._proc.poll()
        self.finished_at = time.time()

    def stop(self, force: bool = False, timeout: float = 5.0) -> None:
        """停止进程：先 SIGTERM，等 timeout 秒，再 force 则 SIGKILL"""
        if not self._proc or self._proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                self._proc.terminate()
            else:
                import signal
                self._proc.send_signal(signal.SIGTERM)
        except Exception:
            pass

        # 等一会儿
        deadline = time.time() + timeout
        while time.time() < deadline and self._proc.poll() is None:
            time.sleep(0.2)

        if self._proc.poll() is None and force:
            try:
                if os.name == "nt":
                    self._proc.kill()
                else:
                    import signal
                    self._proc.send_signal(signal.SIGKILL)
            except Exception:
                pass

    def get_output(self, tail: int | None = None) -> list[str]:
        """读取当前缓冲区内容（线程安全）"""
        with self._lock:
            lines = list(self._buf)
        if tail is not None and tail > 0:
            return lines[-tail:]
        return lines

    def status_line(self) -> str:
        """状态摘要一行"""
        if self.is_running:
            return f"🟢 running（PID {self._proc.pid}）"
        if self.exit_code is None:
            return "⚪ 未启动"
        return f"🔴 exited（code {self.exit_code}，已运行 {self._uptime_s()}s）"

    def _uptime_s(self) -> str:
        end = self.finished_at or time.time()
        return f"{end - self.created_at:.0f}"


# ─── 全局注册表 ────────────────────────────────────────────────

_TERMINALS: dict[str, TerminalSession] = {}


def _register(session: TerminalSession) -> None:
    _TERMINALS[session.id] = session


def _lookup(sid: str) -> TerminalSession | None:
    return _TERMINALS.get(sid)


# ─── terminal_run ───────────────────────────────────────────────

def _run(args, ctx):
    command = (args.get("command") or args.get("cmd") or "").strip()
    if not command:
        raise ValueError("必须提供 command 参数")

    shell = (args.get("shell") or "cmd").lower()
    cwd = args.get("cwd") or str(CONFIG.WORKDIR)
    tail_lines = int(args.get("tail_lines") or 5)  # 启动成功后给 AI 看看初始输出

    session = TerminalSession(shell=shell, command=command, cwd=cwd)
    session.start()
    _register(session)

    # 短暂等待让进程吐出一些输出（最多 2s）
    wait_end = time.time() + 2.0
    while time.time() < wait_end and session.is_running:
        time.sleep(0.1)

    lines = session.get_output(tail=tail_lines)
    output_text = "\n".join(lines) if lines else "（暂无输出）"

    status = session.status_line()
    return ToolResult(
        text=(
            f"🟢 已启动后台进程\n"
            f"• session_id: `{session.id}`\n"
            f"• command: `{command}`\n"
            f"• cwd: `{cwd}`\n"
            f"• {status}\n\n"
            f"**最近 {tail_lines} 行输出：**\n"
            f"```\n{output_text}\n```\n\n"
            f"💡 用 terminal_list 看完整状态，terminal_stop 停掉它。"
        )
    )


# ─── terminal_stop ──────────────────────────────────────────────

def _stop(args, ctx):
    sid = (args.get("session_id") or args.get("id") or "").strip()
    if not sid:
        raise ValueError("必须提供 session_id 参数")

    session = _lookup(sid)
    if not session:
        return ToolResult(text=f"❌ 找不到会话：{sid}（可能已自动清理）")

    force = bool(args.get("force", False))
    timeout = float(args.get("timeout") or 5.0)

    if not session.is_running:
        return ToolResult(
            text=f"该进程已经退出（code {session.exit_code}）\n最近输出：\n"
            + "\n".join(session.get_output(tail=10))
        )

    session.stop(force=force, timeout=timeout)

    # 再等一下线程收尾
    time.sleep(0.3)

    return ToolResult(
        text=(
            f"✅ 已停止 {session.id}\n"
            f"• 命令：`{session.command}`\n"
            f"• 退出码：{session.exit_code}\n"
            f"• 最近输出：\n```\n{chr(10).join(session.get_output(tail=15))}\n```"
        )
    )


# ─── terminal_list ──────────────────────────────────────────────

def _list(args, ctx):
    if not _TERMINALS:
        return ToolResult(text="📋 当前没有任何后台终端会话。")

    show_output = bool(args.get("show_output", True))
    tail = int(args.get("tail") or 15)

    lines = [f"📋 后台会话（共 {len(_TERMINALS)} 个）", "---"]
    for sid, sess in sorted(_TERMINALS.items()):
        lines.append(f"• **{sid}**  {sess.status_line()}")
        lines.append(f"  command: `{sess.command[:120]}{'...' if len(sess.command) > 120 else ''}`")
        lines.append(f"  cwd: `{sess.cwd}`")
        if show_output:
            out = sess.get_output(tail=tail)
            if out:
                lines.append(f"  最近 {len(out)} 行输出：")
                for ln in out[-10:]:
                    lines.append(f"    {ln}")
            else:
                lines.append("  （暂无输出）")
        lines.append("")

    return ToolResult(text="\n".join(lines).rstrip())


# ─── 清理已结束很久的会话 ──────────────────────────────────────

def _gc_finished():
    """自动清理已结束超过 10 分钟的会话，防止注册表无限增长"""
    now = time.time()
    expired = [sid for sid, s in _TERMINALS.items()
               if s.finished_at is not None and now - s.finished_at > 600]
    for sid in expired:
        _TERMINALS.pop(sid, None)


# ─── 注册 ──────────────────────────────────────────────────────

def register_all():
    register(Tool(
        name="terminal_run", title="启动后台进程", perm="Root",
        desc=(
            "在后台启动一个长期运行的进程（开发服务器、worker 等），"
            "返回 session_id。可用 terminal_list 看状态，terminal_stop 停掉。"
        ),
        usage='{"command":"npm run dev","shell":"cmd","tail_lines":5}',
        required={"command": "string"}, handler=_run,
    ))
    register(Tool(
        name="terminal_stop", title="停止后台进程", perm="Root",
        desc="停止指定 session_id 的后台进程。force=true 强制 kill。",
        usage='{"session_id":"trm_abc123xyz"}',
        required={"session_id": "string"}, handler=_stop,
    ))
    register(Tool(
        name="terminal_list", title="列出后台会话", perm="Root",
        desc="列出所有后台运行/已退出的会话及最近输出。",
        usage='{}', handler=_list,
    ))
