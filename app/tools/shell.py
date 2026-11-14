import os, subprocess, tempfile, time
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG

def _decode(b):
    if not b: return ""
    for enc in ("utf-8", "gbk", "utf-16-le"):
        try: return b.decode(enc)
        except Exception: continue
    return b.decode("utf-8", errors="replace")

def _run(shell, command, cwd=None, timeout_ms=10000):
    command = str(command or "").strip()
    if not command: raise ValueError("命令为空")
    shell = (shell or "cmd").lower()
    if shell not in ("cmd", "powershell", "pwsh"):
        raise ValueError(f"不支持的 shell：{shell}")
    workdir = str(cwd) if cwd else str(CONFIG.WORKDIR)
    if not os.path.isdir(workdir):
        workdir = str(CONFIG.WORKDIR)
        
    try:
        timeout_ms = int(timeout_ms or 10000)
    except (ValueError, TypeError):
        timeout_ms = 10000
        
    timeout_s = min(max(timeout_ms / 1000.0, 1.0), 120.0)
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8"})
    tmp_bat = None
    try:
        if shell == "cmd":
            fd, tmp_bat = tempfile.mkstemp(suffix=".bat", prefix="aih-")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("@echo off\nchcp 65001>nul\n" + command + "\n")
            args = ["cmd.exe", "/d", "/s", "/c", tmp_bat]
        else:
            exe = "pwsh" if shell == "pwsh" else "powershell"
            args = [exe, "-NoProfile", "-NonInteractive", "-Command",
                    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command]
        started = time.time()
        proc = subprocess.run(args, cwd=workdir, env=env, capture_output=True,
                              timeout=timeout_s)
        return {
            "code": proc.returncode,
            "stdout": _decode(proc.stdout)[:200000],
            "stderr": _decode(proc.stderr)[:100000],
            "ms": int((time.time() - started) * 1000),
            "cwd": workdir,
        }
    finally:
        if tmp_bat:
            try: os.unlink(tmp_bat)
            except OSError: pass

def _fmt(r):
    out = [f"# 退出码：{r['code']}  用时：{r['ms']} ms",
           f"# 工作目录：{r['cwd']}"]
    if r["stdout"].strip(): out.append(r["stdout"].rstrip())
    if r["stderr"].strip(): out.append("[stderr]\n" + r["stderr"].rstrip())
    if not r["stdout"] and not r["stderr"]: out.append("（无输出）")
    return "\n".join(out)

def _cmd(args, ctx):
    return ToolResult(text=_fmt(_run("cmd", args["command"], args.get("cwd"), args.get("timeout_ms", 10000))))

def _ps(args, ctx):
    return ToolResult(text=_fmt(_run("powershell", args["command"], args.get("cwd"), args.get("timeout_ms", 10000))))

def register_all():
    register(Tool(name="run_cmd", title="执行 CMD 命令", perm="Root",
        desc="在 Windows cmd.exe 中执行命令。", usage='{"command":"dir"}',
        required={"command": "string"}, handler=_cmd))
    register(Tool(name="run_powershell", title="执行 PowerShell", perm="Root",
        desc="在 PowerShell 中执行命令。", usage='{"command":"Get-Date"}',
        required={"command": "string"}, handler=_ps))