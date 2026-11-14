"""
AI Harness 指令行 REPL
----------------------
横幅打印完后进入 REPL 循环，支持：
  /help                    显示指令列表
  /ai <消息>               命令行版 AI Agent（走 run_agent）
  /addplugin <name>        交互输入代码创建插件
  /removeplugin <name>     删除插件文件
  /reload [name|all]       热重载插件
  /list                    列出所有插件
  /tools                   列出所有已注册工具
  /quit, /exit             退出 REPL（不影响 Flask）

注意：REPL 跑在 daemon 线程里，Flask 占主线程。
所有输出必须走 sys.__stdout__（绕过 server.py 的 redirect_stdout）。
"""

import sys
import os
import re
import threading

# ── readline（Tab 补全）─────────────────────────────────────────
# Windows 没 GNU readline，需要 pyreadline3（纯 Python 实现）
# Linux/macOS 自带。两个都兼容。
try:
    import readline  # type: ignore
    _HAS_READLINE = True
except ImportError:
    try:
        import pyreadline3 as readline  # type: ignore
        _HAS_READLINE = True
    except ImportError:
        _HAS_READLINE = False

from .tools import REGISTRY, COMMAND_REGISTRY
from .tools.plugin import (
    PLUGINS_DIR,
    _load_plugin_file,
    _load_all_plugins,
    _validate_plugin_code,
    _ensure_plugins_dir,
)


# ─── 输出工具（绕过 redirect_stdout）─────────────────────────────

def _out(s="", end="\n"):
    print(s, file=sys.__stdout__, end=end, flush=True)


# ─── Tab 补全（Minecraft 风格循环切换）────────────────────────────

# 内置 REPL 指令（硬编码，不会被插件覆盖）
_BUILTIN_CMDS = {
    "help", "ai", "addplugin", "removeplugin", "reload",
    "list", "tools", "quit", "exit",
}


def _all_cmd_names() -> list[str]:
    """内置指令 + 插件注册的 COMMAND_REGISTRY（插件可动态增减）"""
    names = set(_BUILTIN_CMDS)
    names.update(COMMAND_REGISTRY.keys())
    return sorted(f"/{n}" for n in names)


# 需要补全插件名的指令（参数位 → plugins/ 里的 .py 文件去掉后缀）
_PLUGIN_ARG_CMDS = {"/removeplugin", "/reload"}


def _list_plugin_names():
    """扫描 plugins/ 目录下的 .py 文件（排除 __init__ 和 _ 开头）"""
    if not PLUGINS_DIR.exists():
        return []
    return sorted(
        p.stem for p in PLUGINS_DIR.glob("*.py")
        if not p.name.startswith("_")
    )


def _list_builtin_cmds(prefix=""):
    """补全斜杠指令（带公共前缀过滤，含动态插件指令）"""
    return [c for c in _all_cmd_names() if c.startswith(prefix.lower())]


def _completer(text, state):
    """
    readline completer 签名。
    readline 会依次调 _completer(text, 0), _completer(text, 1), ...
    直到返回 None，此时如果只有一个候选就自动补全，多个候选则循环切换。
    Minecraft 风格。
    """
    # state=0 时 readline 传入当前 token（可能是空字符串 ""）
    # 判断是不是斜杠指令位
    if text.startswith("/"):
        candidates = _list_builtin_cmds(text)
    elif not text:
        # 空开头 → 全部指令（用户刚按 Tab）
        candidates = list(_ALL_CMDS)
    else:
        # 非斜杠 → 补全工具名（隐式 /ai 消息开头）
        candidates = [n for n in sorted(REGISTRY.keys()) if n.startswith(text.lower())]

    if state < len(candidates):
        return candidates[state]
    return None


def _setup_readline():
    """初始化 readline 补全"""
    if not _HAS_READLINE:
        return False
    try:
        readline.set_completer(_completer)
        # Tab = 补全，双 Tab = 列出全部候选（Readline 自动支持）
        readline.parse_and_bind("tab: complete")
        # 允许补全时忽略大小写
        readline.set_completer_delims(" \t\n;")
        return True
    except Exception:
        return False


def _prompt() -> str:
    """绕过 redirect_stdout 的 input()：prompt 用 sys.__stdout__，Tab 补全走 readline"""
    _out(">> ", end="")
    try:
        if _HAS_READLINE:
            # readline 自己读 stdin、写 stdout，需要重定向到 sys.__stdout__
            import sys as _sys
            old_out = _sys.stdout
            _sys.stdout = _sys.__stdout__  # readline 输出（prompt/补全列表）走真实终端
            try:
                line = input("")
            finally:
                _sys.stdout = old_out
        else:
            line = sys.stdin.readline()
    except KeyboardInterrupt:
        _out("")
        raise
    if not line:
        raise EOFError
    return line.strip()


# ─── /help ───────────────────────────────────────────────────────

HELP_TEXT = """
可用指令：
  /help                       显示这个帮助
  /ai <消息>                  让 AI 执行任务（Agent 模式）
  /addplugin [name]           弹出文件选择框导入 .py 插件（无 GUI 回退到命令行）
  /removeplugin <name>        直接删除插件文件
  /reload [name | all]        热重载插件（不指定=全部）
  /list                       列出所有插件文件
  /tools                      列出所有已注册工具（{n} 个）
  /quit  (或 Ctrl+C)          退出 REPL（Flask 继续跑）

AI 配置（/ai 需要）：
  export AIH_API_URL=https://.../v1
  export AIH_API_KEY=sk-...
  export AIH_MODEL=gpt-4o
"""


def _help(_arg):
    _out(HELP_TEXT.format(n=len(REGISTRY)))
    if COMMAND_REGISTRY:
        _out(f"\n🧩 插件指令（{len(COMMAND_REGISTRY)} 个）：")
        for name in sorted(COMMAND_REGISTRY):
            cmd = COMMAND_REGISTRY[name]
            hint = f"  — {cmd.help}" if cmd.help else ""
            _out(f"  /{name}{hint}")


# ─── /ai ─────────────────────────────────────────────────────────

def _ai(arg):
    if not arg:
        _out("⚠️  用法：/ai <你的消息>")
        return

    api_url = os.environ.get("AIH_API_URL", "").rstrip("/")
    api_key = os.environ.get("AIH_API_KEY", "")
    model = os.environ.get("AIH_MODEL", "")

    if not api_url or not model:
        _out("❌ 请先设置 LLM 环境变量：")
        _out("     AIH_API_URL=https://.../v1")
        _out("     AIH_API_KEY=sk-...")
        _out("     AIH_MODEL=gpt-4o")
        return

    from .agent import run_agent
    from .sessions import get_or_create

    _out(f"🤖  AI [{model}]: {arg[:80]}{'…' if len(arg) > 80 else ''}")

    sid = "cli_" + threading.current_thread().name
    session = get_or_create(sid)
    messages = [{"role": "user", "content": arg}]

    cfg = {
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
        "tools_enabled": True,
        "think_level": 0,
        "permission": "Root",
        "sandbox_mode": False,
    }

    tool_count = 0
    try:
        for ev in run_agent(cfg, messages, session):
            t = ev.get("type")
            if t == "round":
                _out(f"  ↻ 第 {ev['round']}/{ev['max']} 轮")
            elif t == "reasoning":
                pass  # CLI 不显示思考
            elif t == "token":
                _out(ev.get("text", ""), end="")
            elif t == "tool_start":
                _out(f"  🔧 调用 {ev['name']} {ev.get('args', {})}")
            elif t == "tool_end":
                tool_count += 1
                ok = "✅" if ev.get("ok") else "❌"
                result = (ev.get("result") or "").strip().replace("\n", " | ")
                _out(f"     {ok} {result[:120]}")
            elif t == "done":
                _out("")
            elif t == "error":
                _out(f"  ❌ {ev.get('message', '')}")
            elif t == "round_limit":
                _out(f"  ⚠️  达到 {ev['max']} 轮上限")
    except KeyboardInterrupt:
        _out("\n⏹️  中断")
        return

    _out(f"  📊 本轮调用了 {tool_count} 个工具")


# ─── /addplugin ──────────────────────────────────────────────────

# ─── AST 预扫插件副作用（在信任弹窗之前）────────────────────────

_AST_RISK_KEYWORDS = {
    # 网络/外部执行
    "requests", "urllib", "http", "socket", "subprocess", "Popen", "os.system",
    # 文件/系统
    "open(", "shutil", "rmtree", "remove", "unlink", "kill", "ctypes",
    # 动态执行
    "exec(", "eval(", "compile(", "__import__", "imp.",
    # 敏感
    "token", "password", "secret", "key",
}


def _scan_plugin_side_effects(code: str) -> dict:
    """
    对插件做 AST 粗扫描，在信任弹窗里告诉用户：
      - 预计注册多少 Tool / Command
      - 命中哪些风险关键词（命中就列出来）
    不执行代码，只看 AST。返回 dict: {tools, cmds, risks}
    """
    import ast
    result = {"tools": 0, "cmds": 0, "risks": []}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        result["risks"].append("⚠️  代码有语法错误（无法完整扫描）")
        return result

    # 扫 AST 节点
    for node in ast.walk(tree):
        # 找 register(Tool(...)) / register_command(Command(...)) 调用
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in ("register", "register_command"):
                # 检查第一个参数的类型
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Call):
                    cn = ""
                    if isinstance(first.func, ast.Name):
                        cn = first.func.id
                    elif isinstance(first.func, ast.Attribute):
                        cn = first.func.attr
                    if cn == "Tool":
                        result["tools"] += 1
                    elif cn == "Command":
                        result["cmds"] += 1
            # 风险关键词（Name + Attribute）
            if func_name and func_name in _AST_RISK_KEYWORDS:
                tip = func_name
                if tip not in result["risks"]:
                    result["risks"].append(tip)

    # 字符串层面再扫一次（AST Name 可能漏掉 import 里的别名用法）
    import re
    for kw in _AST_RISK_KEYWORDS:
        if kw in code and kw not in result["risks"]:
            # 只在独立 token 命中时才算，减少误报
            if re.search(r"\b" + re.escape(kw) + r"\b", code):
                result["risks"].append(kw)

    return result


# ─── 信任确认（GUI 弹窗 + CLI y/N fallback）─────────────────────

def _gui_trust_prompt(filepath: str, scan: dict) -> bool | None:
    """
    tkinter messagebox askyesno。
    用户点 YES → True；点 NO 或关窗口 → False；GUI 不可用 → None。
    """
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        return None

    # headless 环境下 tk.Tk() 会抛异常，检测一下
    try:
        root = tk.Tk()
    except Exception:
        return None

    root.withdraw()
    root.attributes("-topmost", True)

    # 组装消息
    parts = [f"插件文件：{filepath}"]
    parts.append(f"将注册：{scan['tools']} 个工具 + {scan['cmds']} 个斜杠指令")
    if scan["risks"]:
        parts.append(f"⚠️  检测到可能风险：{', '.join(scan['risks'])}")
    else:
        parts.append("✓ 未发现明显风险关键词")
    parts.append("")
    parts.append("此插件将加载到 DeepHub MAX，可能：")
    parts.append("  • 访问本地文件 / 执行系统命令")
    parts.append("  • 发起网络请求")
    parts.append("  • 向 AI Agent 注册新能力")
    parts.append("")
    parts.append("只信任来自可信来源的插件。")
    parts.append("是否继续加载此插件？")

    msg = "\n".join(parts)
    try:
        ok = messagebox.askyesno(
            title="🔐 信任新插件？",
            message=msg,
            icon="warning",
            default="no",
        )
    except Exception:
        ok = None
    root.destroy()
    return ok


def _cli_trust_prompt(filepath: str, scan: dict) -> bool:
    """终端信任确认（y/N，默认 N）"""
    _out("")
    _out("┌─────────────────────────────────────────────────────┐")
    _out("│  🔐  信任新插件？                                     │")
    _out("├─────────────────────────────────────────────────────┤")
    _out(f"│  📄 文件：{filepath}")
    _out(f"│  🧰 将注册：{scan['tools']} 个工具 + {scan['cmds']} 个斜杠指令")
    if scan["risks"]:
        _out(f"│  ⚠️  风险关键词：{', '.join(scan['risks'])}")
    else:
        _out("│  ✓  未发现明显风险关键词")
    _out("│")
    _out("│  插件加载后将获得 DeepHub MAX 的运行权限，可能：")
    _out("│    • 访问本地文件 / 执行系统命令")
    _out("│    • 发起网络请求")
    _out("│    • 向 AI Agent 注册新能力")
    _out("│")
    _out("│  只信任来自可信来源的插件。")
    _out("└─────────────────────────────────────────────────────┘")
    while True:
        _out(">>  输入 y 信任并加载，其它 = 取消  ", end="")
        try:
            resp = sys.stdin.readline().strip().lower()
        except (EOFError, KeyboardInterrupt):
            _out("  🚫 已取消"); return False
        if resp in ("y", "yes"):
            return True
        if resp in ("", "n", "no"):
            _out("  🚫 已取消"); return False
        _out("  请输入 y 或 n")


def _confirm_trust(filepath: str, code: str) -> bool:
    """先 AST 扫描，然后 GUI 弹窗（可用优先），fallback 到 CLI y/N"""
    scan = _scan_plugin_side_effects(code)

    # GUI 弹窗优先（Windows 大多数终端都有）
    gui_ok = _gui_trust_prompt(filepath, scan)
    if gui_ok is True:
        return True
    if gui_ok is False:
        return False
    # gui_ok is None → GUI 不可用，走 CLI

    return _cli_trust_prompt(filepath, scan)


# ─── 文件选择 ───────────────────────────────────────────────────

def _pick_file_via_dialog() -> str | None:
    """弹系统文件选择框，让用户选 .py 文件。无 GUI 环境返回 None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    # 创建隐藏的根窗口（tkinter 必须有）
    root = tk.Tk()
    root.withdraw()          # 隐藏主窗口
    root.attributes("-topmost", True)

    try:
        path = filedialog.askopenfilename(
            title="选择插件 Python 文件",
            filetypes=[("Python 文件", "*.py"), ("所有文件", "*.*")],
        )
    except Exception:
        path = ""
    finally:
        root.destroy()

    return path if path else None


def _addplugin(arg):
    _ensure_plugins_dir()

    # 弹文件选择框
    _out("📂 弹出文件选择框（请选择一个 .py 文件作为插件）…")
    picked = _pick_file_via_dialog()

    if picked is None:
        # 无 GUI 环境 → fallback 到老的名字+粘贴模式
        _out("⚠️  无 GUI 环境，回退到命令行模式")
        name = arg.strip()
        if not name:
            _out("  用法：/addplugin <插件名>")
            _out("  或在有 GUI 的终端里直接 /addplugin 弹文件选择框")
            return
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
        target = PLUGINS_DIR / f"{safe}.py"
        _out(f"  请粘贴 Python 代码（单独一行 '.' 结束）：")
        lines = []
        while True:
            try:
                line = _prompt()
            except (EOFError, KeyboardInterrupt):
                _out("  🚫 已取消"); return
            if line == ".": break
            lines.append(line)
        code = "\n".join(lines).strip()
        if not code:
            _out("❌ 代码为空"); return
    else:
        # 有 GUI → 读文件内容
        import pathlib
        p = pathlib.Path(picked)
        if not p.exists():
            _out(f"❌ 文件不存在：{picked}"); return
        if p.suffix.lower() != ".py":
            _out(f"❌ 不是 .py 文件：{p.name}"); return
        code = p.read_text(encoding="utf-8")
        # 从文件名推断插件名
        safe = p.stem
        target = PLUGINS_DIR / f"{safe}.py"
        _out(f"✅ 选中：{p.name}（{len(code)} 字符）")

    if not safe or safe == "__init__":
        _out(f"❌ 无效插件名：{safe}"); return

    # ① 安全校验（AST + 黑名单）
    ok, msg = _validate_plugin_code(code)
    if not ok:
        _out(f"❌ 代码校验失败：{msg}"); return
    _out(f"  ✅ 安全校验通过")

    # ② 信任确认（AST 预扫副作用 + GUI/CLI 确认）
    scan_filepath = target.name if target.exists() else (picked or f"{safe}.py")
    _out(f"  🔐 信任确认…")
    trusted = _confirm_trust(scan_filepath, code)
    if not trusted:
        _out("  🚫 用户拒绝，已取消")
        return
    _out(f"  ✅ 信任通过，开始加载")

    # ③ 落盘 + 加载
    from .tools.plugin import _rewrite_imports
    patched = _rewrite_imports(code)
    if target.exists():
        _out(f"  ⚠️  已存在 {target.name}，覆盖")
    target.write_text(patched, encoding="utf-8")
    _out(f"  💾 已落盘到 plugins/{target.name}")

    ok2, msg2, new_tools, new_cmds = _load_plugin_file(target)
    _out(f"  {msg2}")
    if ok2:
        if new_tools:
            _out(f"  🧰 注册工具（{len(new_tools)} 个）：")
            for n in new_tools:
                _out(f"    • {n}")
        if new_cmds:
            _out(f"  ⌨️  注册指令（{len(new_cmds)} 个）：")
            for n in new_cmds:
                _out(f"    • /{n}  Tab 补全已包含")
        if not new_tools and not new_cmds:
            _out(f"  ℹ️  插件没有注册新 Tool/Command（可能只是副作用导入）")


# ─── /removeplugin ───────────────────────────────────────────────

def _removeplugin(arg):
    name = arg.strip()
    if not name:
        _out("⚠️  用法：/removeplugin <插件名>")
        return

    _ensure_plugins_dir()
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    target = PLUGINS_DIR / f"{safe}.py"

    if not target.exists():
        _out(f"❌ 插件不存在：{safe}.py")
        return

    # 先卸掉注册的工具
    mod_name = f"app.tools.plugins.{safe}"
    mod = sys.modules.get(mod_name)
    if mod:
        from .tools.base import Tool
        for attr_name in list(dir(mod)):
            obj = getattr(mod, attr_name, None)
            if isinstance(obj, Tool) and obj.name:
                REGISTRY.pop(obj.name, None)
        del sys.modules[mod_name]

    target.unlink()
    _out(f"🗑️  已删除 {safe}.py（共 {len(REGISTRY)} 个工具剩余）")


# ─── /reload ─────────────────────────────────────────────────────

def _reload(arg):
    target = arg.strip() or "all"
    _ensure_plugins_dir()

    if target in ("all", "*"):
        results = _load_all_plugins()
        _out(f"🔄 重载全部插件（{len(results)} 个文件）")
        for fname, msg in results:
            mark = "✅" if msg.startswith("✅") else "❌"
            _out(f"  {mark} {fname}: {msg}")
    else:
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in target)
        filepath = PLUGINS_DIR / f"{safe}.py"
        if not filepath.exists():
            _out(f"❌ 插件不存在：{safe}.py")
            return
        ok, msg, new_tools = _load_plugin_file(filepath)
        _out(f"🔄 {safe}.py: {msg}")


# ─── /list ───────────────────────────────────────────────────────

def _listplugins(_arg):
    _ensure_plugins_dir()
    files = sorted(p for p in PLUGINS_DIR.glob("*.py") if not p.name.startswith("_"))
    if not files:
        _out("📂 plugins/ 目录为空（AI 插件会自动落盘到这里）")
        return

    _out(f"📂 AI 插件目录（{len(files)} 个文件）：{PLUGINS_DIR}")
    _out("─" * 60)
    for f in files:
        mod_name = f"app.tools.plugins.{f.stem}"
        mod = sys.modules.get(mod_name)
        tool_names = []
        if mod:
            from .tools.base import Tool
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name, None)
                if isinstance(obj, Tool) and obj.name:
                    tool_names.append(obj.name)
        _out(f"  📄 {f.name:20s}  ({f.stat().st_size} B)  →  {', '.join(tool_names) if tool_names else '未加载'}")


# ─── /tools ──────────────────────────────────────────────────────

def _listtools(_arg):
    _out(f"🧰 已注册工具（{len(REGISTRY)} 个）：")
    _out("─" * 60)
    per_row = 5
    names = sorted(REGISTRY.keys())
    for i in range(0, len(names), per_row):
        row = names[i:i + per_row]
        _out("  " + "  ".join(f"{n:<18s}" for n in row))


# ─── 指令分发表 ──────────────────────────────────────────────────

# 内置指令分发表（插件指令会在 _resolve_handler() 里查 COMMAND_REGISTRY）
_COMMANDS = {
    "/help": _help,
    "/ai": _ai,
    "/addplugin": _addplugin,
    "/removeplugin": _removeplugin,
    "/reload": _reload,
    "/list": _listplugins,
    "/tools": _listtools,
}


def _resolve_handler(cmd: str):
    """解析一个指令：先查内置 _COMMANDS，再查插件 COMMAND_REGISTRY"""
    cmd_lower = cmd.lower()
    # 内置
    handler = _COMMANDS.get(cmd_lower)
    if handler:
        return handler
    # 插件指令（COMMAND_REGISTRY 存的是不带 / 的名字）
    bare = cmd_lower.lstrip("/")
    plugin_cmd = COMMAND_REGISTRY.get(bare)
    if plugin_cmd and plugin_cmd.handler:
        return plugin_cmd.handler
    return None


# ─── 主循环 ──────────────────────────────────────────────────────

def run_repl():
    """REPL 入口（在 daemon 线程里调用）"""
    _out(f"\n💬 AI Harness 指令模式  ·  {len(REGISTRY)} 个工具就绪")
    _out("  输入 /help 查看全部指令，直接输入消息等价于 /ai")

    # 启用 Tab 补全（Minecraft 风格循环切换）
    has_tab = _setup_readline()
    if has_tab:
        _out("  Tab 补全 ✅  单 Tab 补全  双 Tab 列候选")
    else:
        _out("  ⚠️  Tab 补全不可用（pip install pyreadline3 可启用）")

    _out("  Ctrl+C 或 /quit 退出 REPL（Flask 继续运行）\n")

    while True:
        try:
            line = _prompt()
        except EOFError:
            _out("\n👋 REPL 退出")
            break
        except KeyboardInterrupt:
            _out("\n👋 REPL 退出")
            break

        if not line:
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            _out("👋 REPL 退出（Flask 仍在运行，按 Ctrl+C 停服务）")
            break

        handler = _resolve_handler(cmd)
        if handler:
            try:
                handler(arg)
            except Exception as e:
                _out(f"❌ 执行出错: {type(e).__name__}: {e}")
        elif cmd.startswith("/"):
            _out(f"❌ 未知指令: {cmd}（/help 查看）")
        else:
            # 没打前缀 → 等价 /ai
            try:
                _ai(line)
            except KeyboardInterrupt:
                _out("\n⏹️  中断本轮")
