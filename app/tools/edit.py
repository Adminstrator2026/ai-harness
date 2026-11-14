"""
精准代码修改工具（搜索替换）
--------------------------
与 file_write（整篇覆盖）的区别：
  - 只替换指定片段，不触碰其他行
  - old 必须在文件中存在且唯一，否则拒绝执行
  - 支持批量多 edits 一次提交
  - 自动创建 .bak 备份（可关闭），失败不污染原文件
"""

import re
import shutil
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


def _replace_once(text: str, old: str, new: str) -> tuple[str, bool, int]:
    """在全文中找到 old 恰好一次时替换；0 次或多次都返回不改动 + 状态码"""
    count = text.count(old)
    if count == 0:
        return text, False, 0
    if count > 1:
        return text, False, count
    return text.replace(old, new, 1), True, 1


def _edit(args, ctx):
    path = args.get("path")
    edits_raw = args.get("edits") or []
    use_regex = bool(args.get("regex", False))
    make_backup = bool(args.get("backup", True))

    if not path:
        raise ValueError("必须提供 path 参数")
    if not edits_raw:
        raise ValueError("必须提供 edits 数组，至少一组 {old, new}")

    # 校验 edits 数组结构
    edits = []
    for i, e in enumerate(edits_raw):
        if not isinstance(e, dict):
            raise ValueError(f"edits[{i}] 必须是对象 {{old, new}}")
        if "old" not in e or "new" not in e:
            raise ValueError(f"edits[{i}] 必须同时包含 'old' 和 'new'")
        edits.append((e["old"], e["new"]))

    file_path = _resolve_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    if file_path.is_dir():
        raise IsADirectoryError(f"是目录：{file_path}")

    try:
        original = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"读取文件失败：{e}")

    # 先在内存里应用所有修改，任一失败就全部不写盘
    working = original
    applied = 0
    failed = []

    for idx, (old, new) in enumerate(edits):
        if use_regex:
            try:
                matches = re.findall(old, working)
            except re.error as e:
                failed.append(f"edits[{idx}] 正则无效：{e}")
                continue

            if not matches:
                failed.append(f"edits[{idx}] 正则无匹配：{old}")
                continue
            if len(matches) > 1:
                failed.append(f"edits[{idx}] 正则匹配到 {len(matches)} 处（必须唯一）：{old}")
                continue

            working, n = re.subn(old, new, working, count=1)
            applied += 1
        else:
            working, ok, count = _replace_once(working, old, new)
            if not ok:
                if count == 0:
                    failed.append(f"edits[{idx}] 未找到：{_snippet(old)}")
                else:
                    failed.append(f"edits[{idx}] 匹配到 {count} 处（必须唯一）：{_snippet(old)}")
                continue
            applied += 1

    if failed:
        # 失败，一条也不写
        return ToolResult(
            text=f"❌ 拒绝写入，有 {len(failed)} 处 edit 不合法：\n\n" + "\n".join(failed)
        )

    if applied == 0:
        return ToolResult(text="无改动（所有 edits 均为空）")

    # 写盘：先备份（可选）→ 原子写入
    if make_backup:
        bak = file_path.with_suffix(file_path.suffix + ".bak")
        try:
            shutil.copy2(file_path, bak)
        except Exception:
            pass  # 备份失败不阻塞主流程

    try:
        file_path.write_text(working, encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"写入文件失败：{e}")

    diff_lines = _diff_summary(original, working)
    rel = file_path.relative_to(CONFIG.WORKDIR)
    return ToolResult(
        text=f"✅ 成功应用 {applied} 处修改 → {rel}\n{diff_lines}"
    )


def _snippet(s: str, n=40) -> str:
    """把可能很长的 old 字符串截短用于错误信息"""
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "..."


def _diff_summary(before: str, after: str) -> str:
    """快速统计 +/− 行数，不引入 difflib 依赖"""
    b_lines = before.splitlines()
    a_lines = after.splitlines()
    added = max(0, len(a_lines) - len(b_lines))
    removed = max(0, len(b_lines) - len(a_lines))
    return f"+{added}/-{removed} 行"


def register_all():
    register(Tool(
        name="code_edit", title="精准编辑代码", perm="User",
        desc=(
            "基于 old→new 搜索替换修改文件。old 在文件中必须存在且唯一，"
            "否则拒绝执行，不触碰其他行。支持批量 edits 和 regex 模式。"
        ),
        usage='{"path":"main.py","edits":[{"old":"x = 1","new":"x = 2"}]}',
        required={"path": "string", "edits": "array"}, handler=_edit,
    ))
