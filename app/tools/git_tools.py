"""
Git 版本控制工具（git_status / git_diff / git_log / git_commit）
-----------------------------------------------------------------
四个轻量工具，每个 20 行以内，底层 subprocess.run(["git", ...])。
所有命令都在 WORKDIR 下执行，安全可控。
commit 需要 workspace 权限。
"""

import subprocess
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG


def _run_git(args: list[str], cwd=None, timeout=30) -> str:
    """统一的 git 命令执行器，返回 stderr + stdout 合并的文本"""
    workdir = str(cwd or CONFIG.WORKDIR)
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return f"❌ git {' '.join(args)}\n{err or out or '未知错误'}"
        return out
    except FileNotFoundError:
        return "❌ 系统未安装 git 命令"
    except subprocess.TimeoutExpired:
        return f"❌ git {' '.join(args)} 执行超时（>{timeout}s）"


# ─── git status ────────────────────────────────────────────────────

def _git_status(args, ctx):
    porcelain = _run_git(["status", "--short"])
    if porcelain.startswith("❌"):
        return ToolResult(text=porcelain)
    if not porcelain:
        return ToolResult(text="✅ 工作区干净，没有未提交的改动。")

    # 统计 + 分组
    lines = porcelain.splitlines()
    staged = [l for l in lines if l[:2] != "??" and l[0] != "?"]
    unstaged = [l for l in lines if len(l) >= 2 and l[1] != " "]
    untracked = [l for l in lines if l[:2] == "??"]

    out = [f"📋 git status（共 {len(lines)} 项改动）", "---"]
    if staged:
        out.append(f"📦 已暂存 ({len(staged)}):")
        out.extend(f"  {l}" for l in staged)
    if unstaged:
        out.append(f"📝 未暂存 ({len(unstaged)}):")
        out.extend(f"  {l}" for l in unstaged)
    if untracked:
        out.append(f"🆕 未跟踪 ({len(untracked)}):")
        out.extend(f"  {l}" for l in untracked)

    return ToolResult(text="\n".join(out))


# ─── git diff ────────────────────────────────────────────────────

def _git_diff(args, ctx):
    files = args.get("files") or []
    staged = bool(args.get("staged", False))

    cmd = ["diff"]
    if staged:
        cmd.append("--cached")
    if files:
        cmd.extend(files)

    diff = _run_git(cmd, timeout=60)
    if diff.startswith("❌"):
        return ToolResult(text=diff)
    if not diff:
        return ToolResult(text="📭 没有差异。")

    # 太长则截断
    if len(diff) > 16000:
        diff = diff[:16000] + "\n\n... (diff 过长，已截断，可用 files 参数聚焦单个文件)"
    return ToolResult(text=diff)


# ─── git log ────────────────────────────────────────────────────

def _git_log(args, ctx):
    limit = int(args.get("limit") or 10)
    author = args.get("author") or ""
    path = args.get("path") or ""

    cmd = ["log", f"--oneline", f"-n", str(limit)]
    if author:
        cmd.extend(["--author", author])
    if path:
        cmd.append("--")
        cmd.append(path)

    log = _run_git(cmd)
    if log.startswith("❌"):
        return ToolResult(text=log)
    if not log:
        return ToolResult(text="📭 没有提交记录。")

    header = f"📜 git log（最近 {limit} 条）"
    if author:
        header += f"，作者：{author}"
    if path:
        header += f"，路径：{path}"

    return ToolResult(text=header + "\n---\n" + log)


# ─── git commit ──────────────────────────────────────────────────

def _git_commit(args, ctx):
    message = (args.get("message") or "").strip()
    if not message:
        raise ValueError("必须提供 message 参数")

    # 先 add（可选），再 commit
    add_all = bool(args.get("add_all", True))

    if add_all:
        add_out = _run_git(["add", "-A"])
        if add_out.startswith("❌"):
            return ToolResult(text=add_out)

    commit_out = _run_git(["commit", "-m", message])
    if commit_out.startswith("❌"):
        return ToolResult(text=commit_out)

    # 取简短 hash
    last = _run_git(["rev-parse", "--short", "HEAD"])
    return ToolResult(text=f"✅ 提交成功\n\n{last}\n\n{commit_out}")


# ─── 注册 ──────────────────────────────────────────────────────

def register_all():
    register(Tool(
        name="git_status", title="Git 状态", perm="Visitor",
        desc="显示工作区改动（已暂存 / 未暂存 / 未跟踪）。",
        usage="{}", handler=_git_status,
    ))
    register(Tool(
        name="git_diff", title="Git 差异", perm="Visitor",
        desc="显示未提交的差异。staged=true 看已暂存差异；files 可聚焦单个文件。",
        usage='{"staged":false}', handler=_git_diff,
    ))
    register(Tool(
        name="git_log", title="Git 提交历史", perm="Visitor",
        desc="oneline 格式提交记录。limit 控制条数（默认 10）。",
        usage='{"limit":10}', handler=_git_log,
    ))
    register(Tool(
        name="git_commit", title="Git 提交", perm="User",
        desc="先 add -A 再 commit（add_all=false 可跳过 add）。",
        usage='{"message":"feat: 新增 grep_search 工具"}',
        required={"message": "string"}, handler=_git_commit,
    ))
