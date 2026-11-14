"""
工作区内文本搜索工具
--------------------
递归扫描文件，按正则或纯文本匹配，返回 [文件名:行号:行内容]。
自动跳过二进制文件、隐藏目录（.git、node_modules、__pycache__ 等）。
"""

import os
import re
from pathlib import Path
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG


# 跳过这些目录（完整目录名匹配）
_SKIP_DIRS = {
    ".git", ".svn", ".hg", ".idea", ".vscode",
    "node_modules", "venv", ".venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "dist", "build",
}

# 跳过这些二进制后缀
_BIN_EXTS = {
    ".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib", ".class", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".db", ".sqlite", ".sqlite3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".o", ".obj", ".a", ".lib",
}


def _is_binary(path: Path) -> bool:
    """简单检测：后缀命中或文件里出现 NUL 字节"""
    if path.suffix.lower() in _BIN_EXTS:
        return True
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except Exception:
        return True


def _resolve_path(p: str | None) -> Path:
    """安全解析路径（必须在 WORKDIR 内）"""
    target = Path(p).expanduser() if p else CONFIG.WORKDIR
    if not target.is_absolute():
        target = CONFIG.WORKDIR / target
    target = target.resolve()
    try:
        target.relative_to(CONFIG.WORKDIR)
    except ValueError:
        raise ValueError(f"路径越界：{target} 不在 {CONFIG.WORKDIR} 内")
    return target


def _search_file(file_path: Path, pattern: re.Pattern, max_per_file: int) -> list[str]:
    """在单个文件里搜索，返回格式化的命中行"""
    hits = []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return hits

    for line_no, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            rel = file_path.relative_to(CONFIG.WORKDIR)
            hits.append(f"{rel}:{line_no}: {line.strip()}")
            if len(hits) >= max_per_file:
                break
    return hits


def _grep(args, ctx):
    pattern = (args.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("必须提供 pattern 参数")

    is_regex = bool(args.get("regex", False))
    ignore_case = bool(args.get("ignore_case", False))
    max_results = int(args.get("max_results") or 50)
    max_per_file = int(args.get("max_per_file") or 20)

    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    try:
        raw_pattern = pattern if is_regex else re.escape(pattern)
        compiled = re.compile(raw_pattern, flags)
    except re.error as e:
        raise ValueError(f"正则表达式无效：{e}")

    root = _resolve_path(args.get("path"))

    if root.is_file():
        if _is_binary(root):
            return ToolResult(text=f"二进制文件，跳过：{root.name}")
        hits = _search_file(root, compiled, max_per_file)
        return _format(hits, root, max_results, is_regex, pattern)

    # root 是目录 → 递归扫描
    all_hits = []
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # 原地裁剪目录列表，阻止进入跳过目录
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

        for fname in filenames:
            if len(all_hits) >= max_results:
                break
            fpath = Path(dirpath) / fname
            if _is_binary(fpath):
                continue
            scanned += 1
            all_hits.extend(_search_file(fpath, compiled, max_per_file))

    return _format(all_hits, root, max_results, is_regex, pattern, scanned)


def _format(hits, root, max_results, is_regex, pattern, scanned=1):
    if not hits:
        scope = f"文件 {root.relative_to(CONFIG.WORKDIR)}" if root.is_file() else f"目录 {root.relative_to(CONFIG.WORKDIR)}"
        return ToolResult(text=f"无匹配。模式：{pattern}（{'regex' if is_regex else 'text'}），范围：{scope}")

    summary = f"共找到 {len(hits)} 处匹配"
    if len(hits) >= max_results:
        summary += f"（已截断，上限 {max_results}）"
    if root.is_dir():
        summary += f"，扫描文件 {scanned} 个"

    return ToolResult(text=summary + "\n---\n" + "\n".join(hits))


def register_all():
    register(Tool(
        name="grep_search", title="搜索工作区", perm="Visitor",
        desc="在工作区递归搜索文本。支持纯文本或正则，自动跳过二进制文件。",
        usage='{"pattern":"import requests"}',
        required={"pattern": "string"}, handler=_grep,
    ))
