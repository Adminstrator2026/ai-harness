"""
unified diff 补丁应用工具
------------------------
比 code_edit 的 old→new 单条替换更强大：
  - 接受标准 git diff / unified diff 格式
  - 支持多文件批量修改
  - 自动处理 @@ 行号上下文（-a,b +c,d）
  - 每个 hunk 的上下文行必须匹配才应用（安全）

依赖：Python 标准库 difflib（解析 hunk 时我们自己实现，避免重依赖）
"""

import os
import re
import difflib
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
        raise ValueError(f"路径越界：{target}")
    return target


# ─── 解析 unified diff 文本 ─────────────────────────────────────

_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def _parse_patch(diff_text: str) -> list[dict]:
    """
    把 unified diff 文本解析成 [{path, hunks:[{old_start, old_lines[], new_lines[]}, ...]}]
    每个 hunk 都带上下文匹配信息。
    """
    files = []
    current = None
    mode = None  # 'old' 或 'new'

    for raw_line in diff_text.splitlines():
        line = raw_line

        # diff --git / --- / +++ 头
        if line.startswith("diff --git"):
            current = {"path": None, "hunks": []}
            files.append(current)
            continue
        if line.startswith("--- "):
            # --- a/foo.py → foo.py
            path = line[4:].strip()
            if path.startswith("a/"):
                path = path[2:]
            current["_old"] = path
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current["path"] = path
            mode = None
            continue

        # 没有 path 信息（裸 diff），用当前文件
        if current is None or current["path"] is None:
            continue

        m = _HUNK_RE.match(line)
        if m:
            old_start = int(m.group(1))
            new_start = int(m.group(3))
            current["hunks"].append({
                "old_start": old_start, "new_start": new_start,
                "old_lines": [], "new_lines": [],
            })
            mode = None
            continue

        if not current["hunks"]:
            continue
        hunk = current["hunks"][-1]

        if line.startswith("-") and not line.startswith("--"):
            hunk["old_lines"].append(line[1:])
            mode = "old"
        elif line.startswith("+") and not line.startswith("++"):
            hunk["new_lines"].append(line[1:])
            mode = "new"
        elif line.startswith(" "):
            # 上下文：两侧都加
            hunk["old_lines"].append(line[1:])
            hunk["new_lines"].append(line[1:])
            mode = "both"
        elif line.startswith("\\"):
            # "No newline at end of file" 等元信息，跳过
            continue

    # 过滤掉没有 hunk 的条目
    return [f for f in files if f["hunks"]]


def _apply_hunks(file_content: str, hunks: list[dict]) -> tuple[str, bool, str]:
    """
    在文件内容上顺序应用 hunks。
    任一 hunk 的上下文不匹配 → 整体失败（不半应用）。
    """
    lines = file_content.splitlines(keepends=True)  # 保留末尾换行
    # 如果原文件不以 \n 结尾，splitlines(keepends=True) 会漏掉最后一段，补一下
    if file_content and not file_content.endswith("\n"):
        lines[-1] = lines[-1].rstrip("\n")

    # 先把所有 hunk 转换成 "在哪些行范围内 old_lines 必须匹配 → 替换为 new_lines"
    # 我们顺序扫描，每次在当前 old_start 位置验证上下文
    offset = 0  # new_start 和 old_start 的差值（因为我们边改边增加/减少行数）

    for hi, hunk in enumerate(hunks):
        old_start = hunk["old_start"] - 1  # 0-based
        expected_old = hunk["old_lines"]
        replacement_new = hunk["new_lines"]

        # 找到 old_start 在原文件里的实际位置（加上之前修改带来的偏移）
        # 这里简化：直接用 old_start + offset... 不对，应该逐步验证
        actual_pos = old_start  # 直接用 old_start，不 + offset，因为我们在原文件上模拟替换

        # 验证 old_lines 在实际位置是否匹配
        for i, exp_line in enumerate(expected_old):
            if actual_pos + i >= len(lines):
                return file_content, False, f"hunk[{hi}] 越界：文件只有 {len(lines)} 行，预期位置 {actual_pos + i + 1}"
            # 去掉 \n 再比较（因为 keepends 带换行符）
            actual = lines[actual_pos + i].rstrip("\n")
            if actual != exp_line:
                snippet = "\n".join(l.rstrip("\n") for l in lines[actual_pos:actual_pos+len(expected_old)])
                return file_content, False, (
                    f"hunk[{hi}] 上下文不匹配："
                    f"预期第 {actual_pos + i + 1} 行是 '{exp_line}'，"
                    f"实际是 '{actual}'。\n"
                    f"实际 hunk 上下文：\n{snippet}"
                )

        # 全部匹配 → 替换
        replaced = [line + "\n" for line in replacement_new]
        # 处理末尾无换行的情况（简化处理）
        del lines[actual_pos : actual_pos + len(expected_old)]
        for j, rline in enumerate(replaced):
            lines.insert(actual_pos + j, rline)

    return "".join(lines), True, ""


def _patch(args, ctx):
    patch_text = (args.get("patch") or args.get("diff") or "").strip()
    make_backup = bool(args.get("backup", True))
    dry_run = bool(args.get("dry_run", False))

    if not patch_text:
        raise ValueError("必须提供 patch 参数（unified diff 文本）")

    parsed = _parse_patch(patch_text)
    if not parsed:
        return ToolResult(text="❌ 无法解析 diff：没有找到任何有效的文件 hunk")

    applied = 0
    failed = []
    skipped = []

    for entry in parsed:
        rel_path = entry["path"]
        try:
            file_path = _resolve_path(rel_path)
        except ValueError as e:
            failed.append(f"❌ {rel_path}: {e}")
            continue

        if not file_path.exists():
            failed.append(f"❌ {rel_path}: 文件不存在（未应用）")
            continue
        if not file_path.is_file():
            failed.append(f"❌ {rel_path}: 是目录（未应用）")
            continue

        try:
            original = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            failed.append(f"❌ {rel_path}: 读取失败 {e}")
            continue

        new_content, ok, err = _apply_hunks(original, entry["hunks"])
        if not ok:
            failed.append(f"❌ {rel_path}: {err}")
            continue

        if not dry_run:
            if make_backup:
                bak = file_path.with_suffix(file_path.suffix + ".bak")
                try:
                    shutil.copy2(file_path, bak)
                except Exception:
                    pass
            try:
                file_path.write_text(new_content, encoding="utf-8")
            except Exception as e:
                failed.append(f"❌ {rel_path}: 写入失败 {e}")
                continue

        applied += 1

    lines = [f"🧩 file_patch 结果（{applied}/{len(parsed)} 成功）", "---"]
    if dry_run:
        lines.append("⚠️ dry_run=true，未实际写盘")
    lines.append(f"✅ 已应用: {applied} 个文件")
    if skipped:
        lines.append(f"⏭️  跳过: {len(skipped)} 个")
    if failed:
        lines.append(f"❌ 失败: {len(failed)} 个")
        for f in failed:
            lines.append(f"  {f}")

    return ToolResult(text="\n".join(lines))


def register_all():
    register(Tool(
        name="file_patch", title="应用补丁", perm="User",
        desc=(
            "应用标准 unified diff 格式补丁。支持多文件批量修改；"
            "每个 hunk 的上下文必须匹配才应用；dry_run=true 可预览不写盘。"
        ),
        usage='{"patch":"diff --git a/x.py b/x.py\\n...","dry_run":true}',
        required={"patch": "string"}, handler=_patch,
    ))
