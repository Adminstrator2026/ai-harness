"""
系统资源快照工具
----------------
返回 CPU、内存、磁盘、工作目录大小、Python 版本等。
优先用 psutil（如果已安装），否则用纯 Python os + sysinfo 兜底。
"""

import os
import sys
from pathlib import Path
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG


def _try_psutil():
    """检测 psutil 可用性，返回它或 None"""
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _get_cpu_info(psutil) -> dict:
    if not psutil:
        return {"CPU": f"{os.cpu_count() or '?'} 核（未安装 psutil，无使用率）"}
    try:
        pct = psutil.cpu_percent(interval=0.5)
        count = os.cpu_count() or psutil.cpu_count() or "?"
        return {"CPU": f"{count} 核，当前使用率 {pct:.1f}%"}
    except Exception as e:
        return {"CPU": f"获取失败：{e}"}


def _get_mem_info(psutil) -> dict:
    if psutil:
        try:
            m = psutil.virtual_memory()
            used_gb = m.used / 1024**3
            total_gb = m.total / 1024**3
            pct = m.percent
            return {"内存": f"{used_gb:.1f} / {total_gb:.1f} GB（{pct:.1f}%）"}
        except Exception as e:
            return {"内存": f"获取失败：{e}"}

    # Windows 兜底：用 wmic
    try:
        import subprocess
        proc = subprocess.run(
            ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/value"],
            capture_output=True, text=True, timeout=5,
        )
        total = free = 0
        for line in proc.stdout.splitlines():
            if line.startswith("Total"):
                total = int(line.split("=", 1)[1]) * 1024
            elif line.startswith("Free"):
                free = int(line.split("=", 1)[1]) * 1024
        used = total - free
        if total:
            return {"内存": f"{used/1024**3:.1f} / {total/1024**3:.1f} GB（{used/total*100:.1f}%）"}
    except Exception:
        pass
    return {"内存": "无法获取（建议 pip install psutil）"}


def _get_disk_info(psutil) -> dict:
    if psutil:
        try:
            d = psutil.disk_usage(str(CONFIG.WORKDIR))
            used_gb = d.used / 1024**3
            total_gb = d.total / 1024**3
            return {"磁盘": f"{used_gb:.1f} / {total_gb:.1f} GB（{d.percent:.1f}%）"}
        except Exception as e:
            return {"磁盘": f"获取失败：{e}"}

    # 纯 os 兜底
    try:
        stat = os.statvfs(str(CONFIG.WORKDIR))
        total = stat.f_frsize * stat.f_blocks
        free = stat.f_frsize * stat.f_bfree
        used = total - free
        return {"磁盘": f"{used/1024**3:.1f} / {total/1024**3:.1f} GB（{used/total*100:.1f}%）"}
    except AttributeError:
        # Windows 没有 statvfs
        return {"磁盘": "Windows 下需安装 psutil 获取"}
    except Exception:
        return {"磁盘": "无法获取"}


def _get_workspace_size() -> str:
    """工作目录总大小 + 文件数（递归）"""
    total_bytes = 0
    file_count = 0
    try:
        for root, dirs, files in os.walk(CONFIG.WORKDIR):
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                try:
                    fp = Path(root) / f
                    total_bytes += fp.stat().st_size
                    file_count += 1
                except OSError:
                    pass
    except Exception:
        return "（无法扫描）"

    if total_bytes < 1024:
        size_str = f"{total_bytes} B"
    elif total_bytes < 1024**2:
        size_str = f"{total_bytes/1024:.1f} KB"
    elif total_bytes < 1024**3:
        size_str = f"{total_bytes/1024**2:.1f} MB"
    else:
        size_str = f"{total_bytes/1024**3:.2f} GB"

    return f"{size_str}，共 {file_count} 个文件"


def _sys_info(args, ctx):
    psutil = _try_psutil()
    sections = {}

    sections.update(_get_cpu_info(psutil))
    sections.update(_get_mem_info(psutil))
    sections.update(_get_disk_info(psutil))

    sections["Python"] = f"{sys.version.split()[0]} ({sys.platform})"
    sections["PID"] = os.getpid()
    sections["工作目录"] = str(CONFIG.WORKDIR)
    sections["工作目录大小"] = _get_workspace_size()

    lines = ["🖥️ 系统资源快照", "---"]
    for k, v in sections.items():
        lines.append(f"• **{k}**: {v}")

    if not psutil:
        lines.append("\n💡 提示：安装 psutil 可获得更准确的数值（pip install psutil）")

    return ToolResult(text="\n".join(lines))


def register_all():
    register(Tool(
        name="sys_info", title="系统快照", perm="Visitor",
        desc=(
            "返回 CPU / 内存 / 磁盘 / Python 版本 / PID / 工作目录大小。"
            "优先用 psutil（若已装），否则纯 Python 兜底。"
        ),
        usage="{}", handler=_sys_info,
    ))
