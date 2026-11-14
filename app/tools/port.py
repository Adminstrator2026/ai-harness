"""
端口占用检查工具
----------------
检查指定端口是否被占用，返回占用进程的 PID + 命令行（如果能拿到）。
"""

import socket
import subprocess
import os
from .base import Tool, ToolResult
from . import register


def _check_port(port: int) -> dict:
    """返回 {port, in_use, pid?, process?, command?}"""
    result = {"port": port, "in_use": False}

    # 1. socket 快速检测
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        # 没抛异常 → 空闲
        s.close()
        return result
    except OSError:
        pass
    finally:
        s.close()

    result["in_use"] = True

    # 2. 找占用进程
    if os.name == "nt":
        _get_port_info_windows(port, result)
    else:
        _get_port_info_unix(port, result)

    return result


def _get_port_info_windows(port: int, result: dict) -> None:
    """Windows: netstat → PID, 再 tasklist 或 wmic 拿命令行"""
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
        )
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING":
                local = parts[1]  # 如 0.0.0.0:8080
                pid = parts[4]
                if local.endswith(f":{port}"):
                    result["pid"] = int(pid)
                    break
    except Exception:
        pass

    pid = result.get("pid")
    if pid:
        try:
            proc = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/value"],
                capture_output=True, text=True, timeout=5,
            )
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("CommandLine="):
                    cmd = line[len("CommandLine="):].strip()
                    if cmd:
                        result["command"] = cmd[:200]
                        break
        except Exception:
            pass


def _get_port_info_unix(port: int, result: dict) -> None:
    """Linux/macOS: lsof 或 ss"""
    try:
        proc = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5,
        )
        lines = proc.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 2:
                result["process"] = parts[0]
                result["pid"] = int(parts[1])
                # 其余列里可能有命令行（COMMAND 列）
                if len(parts) >= 9:
                    result["command"] = " ".join(parts[8:])[:200]
    except Exception:
        pass


def _port_check(args, ctx):
    port_raw = args.get("port")
    if port_raw is None:
        raise ValueError("必须提供 port 参数")
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise ValueError(f"port 必须是整数，收到 {port_raw}")
    if port < 1 or port > 65535:
        raise ValueError("port 必须在 1~65535 之间")

    result = _check_port(port)

    if not result["in_use"]:
        return ToolResult(text=f"✅ 端口 {port} 空闲，可安全启动服务。")

    lines = [f"⚠️ 端口 {port} 已被占用", "---"]
    if "process" in result:
        lines.append(f"• 进程名：{result['process']}")
    if "pid" in result:
        lines.append(f"• PID：{result['pid']}")
    if "command" in result:
        lines.append(f"• 命令行：{result['command']}")
    lines.append(f"\n💡 可以用 terminal_stop 关掉对应 session，或换一个端口。")

    return ToolResult(text="\n".join(lines))


def register_all():
    register(Tool(
        name="port_check", title="端口占用检查", perm="Visitor",
        desc="检查指定端口是否被占用，返回 PID + 进程名 + 命令行（跨平台）。",
        usage='{"port":8080}',
        required={"port": "string"}, handler=_port_check,
    ))
