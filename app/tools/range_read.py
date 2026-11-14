"""
大文件定点读取工具
------------------
与 file_read（前 256KB）的区别：
  - 按行号读取：offset + limit，可跳读文件任意位置
  - 适合看大日志的末尾、大 JSON 的中间段等场景
实现：逐行 enumerate，到 offset 才开始收集，内存友好（不读全文）。
"""

from pathlib import Path
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG


def _resolve_path(p: str) -> Path:
    target = Path(p).expanduser()
    if not target.is_absolute():
        target = CONFIG.WORKDIR / target
    target = target.resolve()
    try:
        target.relative_to(CONFIG.WORKDIR)
    except ValueError:
        raise ValueError(f"路径越界：{target} 不在 {CONFIG.WORKDIR} 内")
    return target


def _read_range(args, ctx):
    path = args.get("path")
    offset = int(args.get("offset") or 1)  # 从第几行开始（1-based）
    limit = args.get("limit")              # 读多少行（None = 读到末尾）
    max_bytes = int(args.get("max_bytes") or 512 * 1024)  # 单段默认上限 512KB

    if not path:
        raise ValueError("必须提供 path 参数")

    file_path = _resolve_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    if file_path.is_dir():
        raise IsADirectoryError(f"是目录：{file_path}")

    if offset < 1:
        offset = 1

    # limit 处理：None → 读到底；数字 → 读 limit 行；带 + 的字符串 → 从 offset 起读 limit 行
    if isinstance(limit, str) and limit.startswith("+"):
        limit = int(limit[1:])
    if limit is not None:
        limit = max(1, int(limit))

    collected = []
    total_lines = 0  # 用于统计总行数
    bytes_read = 0

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                total_lines = line_no
                if line_no < offset:
                    continue
                if limit is not None and len(collected) >= limit:
                    break
                collected.append(line.rstrip("\n"))
                bytes_read += len(line.encode("utf-8", errors="replace"))
                if bytes_read >= max_bytes:
                    break
    except Exception as e:
        raise RuntimeError(f"读取文件失败：{e}")

    rel = file_path.relative_to(CONFIG.WORKDIR)
    header = f"文件：{rel}（总 {total_lines} 行）"
    header += f"\n读取：第 {offset} 行起"
    if limit is not None:
        header += f"，上限 {limit} 行"
    header += f"（实际 {len(collected)} 行，{bytes_read} 字节）"
    if bytes_read >= max_bytes:
        header += "\n⚠️ 触发 max_bytes 截断"

    body = "\n".join(collected) if collected else "（该位置无内容）"
    return ToolResult(text=header + "\n---\n" + body)


def register_all():
    register(Tool(
        name="read_file_range", title="定点读大文件", perm="Visitor",
        desc=(
            "按行号读取文件任意片段。offset=起始行号（1-based），"
            "limit=读取行数（可省略读到底）。适合看大日志末尾、大 JSON 中间段等。"
        ),
        usage='{"path":"app.log","offset":1500,"limit":100}',
        required={"path": "string"}, handler=_read_range,
    ))
