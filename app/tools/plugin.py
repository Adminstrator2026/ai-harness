"""
AI 自举插件系统
---------------
让 AI 可以：
  1. plugin_create — 写新插件（.py 文件），自动落盘+加载
  2. plugin_reload — 热重载指定插件或全部插件
  3. plugin_list   — 列出所有已加载插件

AI 写的插件里可能用 from .base import ...（以为自己在 tools/ 目录），
实际插件在 tools/plugins/ 里，需要 from ..base import ...。
我们在落盘时自动重写这些相对导入，保证永远正确。
"""

import os
import sys
import re
import ast
import traceback
import importlib
import importlib.util
from pathlib import Path
from .base import Tool, ToolResult, Command, COMMAND_REGISTRY
from . import register, register_command, REGISTRY
from ..config import CONFIG

PLUGINS_DIR = Path(__file__).parent / "plugins"


# ─── 目录初始化 ───────────────────────────────────────────────

def _ensure_plugins_dir():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    init_py = PLUGINS_DIR / "__init__.py"
    if not init_py.exists():
        init_py.write_text("# Auto-generated, do not edit\n", encoding="utf-8")


# ─── 相对导入重写 ──────────────────────────────────────────────

# AI 通常写 from .base import Tool，以为自己在 tools/ 下
# 实际插件在 tools/plugins/ 下，需要 from ..base import Tool
_IMPORT_FIX_MAP = {
    # AI 写的 → 插件实际需要的
    "from .base": "from ..base",
    "from . import register": "from .. import register",
    "from . import Tool": "from .. import Tool",
    "from . import ToolResult": "from .. import ToolResult",
    "from . import Command": "from .. import Command",
    "from . import register_command": "from .. import register_command",
    "from .base import": "from ..base import",
}


def _rewrite_imports(code: str) -> str:
    """把 AI 写的相对导入修正到 plugins/ 子目录层级"""
    patched = code
    # 用正则精准替换整行 import 语句
    for wrong, right in _IMPORT_FIX_MAP.items():
        patched = re.sub(rf'^\s*{re.escape(wrong)}\b', right, patched, flags=re.MULTILINE)
    # 也处理 from .tools.base → from ..tools.base 这种情况
    patched = re.sub(r'^\s*from \.tools\.', 'from ..', patched, flags=re.MULTILINE)
    patched = re.sub(r'^\s*from \.tools import', 'from .. import', patched, flags=re.MULTILINE)
    return patched


# ─── 插件加载 / 重载 ───────────────────────────────────────────

def _load_plugin_file(filepath: Path) -> tuple[bool, str, list[str], list[str]]:
    """加载一个 .py 插件文件，返回 (ok, 描述, 注册的工具名列表, 注册的指令名列表)"""
    module_name = f"app.tools.plugins.{filepath.stem}"

    # 预处理导入（不覆盖原文件，只在 exec 时用 patched 代码）
    raw_code = filepath.read_text(encoding="utf-8")
    patched_code = _rewrite_imports(raw_code)

    # 清理旧版本残留（Tool + Command）
    if module_name in sys.modules:
        old_module = sys.modules[module_name]
        for attr_name in dir(old_module):
            obj = getattr(old_module, attr_name, None)
            if isinstance(obj, Tool) and obj.name:
                REGISTRY.pop(obj.name, None)
            if isinstance(obj, Command) and obj.name:
                COMMAND_REGISTRY.pop(obj.name, None)
        del sys.modules[module_name]

    # 用 exec + module dict 方式加载
    prev_tools = set(REGISTRY.keys())
    prev_cmds = set(COMMAND_REGISTRY.keys())
    try:
        try:
            compiled = compile(patched_code, str(filepath), "exec")
        except SyntaxError as e:
            return False, f"语法错误：{e}（尝试了自动修正相对导入）", [], []

        module = type(sys)(module_name)
        module.__file__ = str(filepath)
        module.__path__ = [str(filepath.parent)]
        if "." in module_name:
            module.__package__ = module_name.rsplit(".", 1)[0]
        sys.modules[module_name] = module

        exec(compiled, module.__dict__, module.__dict__)

    except Exception as e:
        tb = traceback.format_exc()
        sys.modules.pop(module_name, None)
        if patched_code != raw_code:
            try:
                old_module_name = module_name
                compiled = compile(raw_code, str(filepath), "exec")
                module = type(sys)(old_module_name)
                module.__file__ = str(filepath)
                if "." in old_module_name:
                    module.__package__ = old_module_name.rsplit(".", 1)[0]
                sys.modules[old_module_name] = module
                exec(compiled, module.__dict__, module.__dict__)
                filepath.write_text(raw_code, encoding="utf-8")
            except Exception as e2:
                tb2 = traceback.format_exc()
                sys.modules.pop(old_module_name, None)
                return False, (
                    f"加载失败（自动修正导入后仍报错）：\n{e}\n\n"
                    f"尝试原代码也失败：\n{e2}\n```\n{tb2}\n```"
                ), [], []
        return False, f"加载失败：{type(e).__name__}: {e}\n```\n{tb}\n```", [], []

    if not hasattr(module, "register_all") or not callable(module.register_all):
        sys.modules.pop(module_name, None)
        return False, "插件必须导出 register_all() 函数（无参数）", [], []

    try:
        module.register_all()
    except Exception as e:
        sys.modules.pop(module_name, None)
        return False, f"register_all() 执行失败：{e}", [], []

    new_tools = [k for k in REGISTRY.keys() if k not in prev_tools]
    new_cmds = [k for k in COMMAND_REGISTRY.keys() if k not in prev_cmds]

    if patched_code != raw_code:
        filepath.write_text(patched_code, encoding="utf-8")

    parts = [f"✅ 加载成功：{filepath.name}"]
    if new_tools:
        parts.append(f"注册了 {len(new_tools)} 个工具")
    if new_cmds:
        parts.append(f"注册了 {len(new_cmds)} 个指令")
    msg = "，".join(parts)
    return True, msg, new_tools, new_cmds


def _load_all_plugins() -> list[tuple[str, str]]:
    """扫描 plugins/ 目录下所有 .py 并加载"""
    _ensure_plugins_dir()
    results = []
    for pyfile in sorted(PLUGINS_DIR.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        ok, msg, _, _ = _load_plugin_file(pyfile)
        results.append((pyfile.name, msg))
    return results


# ─── 代码安全校验 ──────────────────────────────────────────────

def _validate_plugin_code(code: str) -> tuple[bool, str]:
    if not code or not code.strip():
        return False, "代码为空"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误：{e}"

    # 禁词
    forbidden = {"exec", "eval", "compile", "__import__"}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # 允许相对导入（插件在 plugins/ 下，往上找 tools.base）
            if node.level and node.level > 0:
                continue
            for alias in node.names:
                full = f"{node.module}.{alias.name}" if node.module else alias.name
                if full not in {"tools.base", "tools", "base", "", "json", "re", "os", "time", "pathlib", "collections", "functools", "itertools", "datetime", "math"}:
                    return False, f"禁止导入：{full}"

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in {"json", "re", "os", "time", "pathlib", "collections", "functools", "itertools", "datetime", "math"}:
                    return False, f"禁止导入：{alias.name}"

        if isinstance(node, ast.Name):
            if node.id in forbidden:
                return False, f"禁止使用：{node.id}"

    # 必须有 register_all
    has_reg = any(
        isinstance(n, ast.FunctionDef) and n.name == "register_all"
        for n in ast.walk(tree)
    )
    if not has_reg:
        return False, "必须定义 register_all() 函数"

    return True, "OK"


# ─── plugin_create ─────────────────────────────────────────────

def _plugin_create(args, ctx):
    _ensure_plugins_dir()
    name = (args.get("name") or args.get("filename") or "").strip()
    code = args.get("code") or args.get("content") or ""
    make_load = bool(args.get("auto_load", True))

    if not name:
        raise ValueError("必须提供 name")
    if not code:
        raise ValueError("必须提供 code")

    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if safe_name != name:
        return ToolResult(text=f"❌ 插件名不合法：'{name}' → 应用字母数字下划线")
    if not safe_name or safe_name == "__init__":
        return ToolResult(text="❌ 无效插件名")

    ok, msg = _validate_plugin_code(code)
    if not ok:
        return ToolResult(text=f"❌ 代码校验失败：\n\n{msg}")

    # 落盘（自动修正导入路径）
    patched_code = _rewrite_imports(code)
    target = PLUGINS_DIR / f"{safe_name}.py"
    if target.exists():
        bak = PLUGINS_DIR / f".{safe_name}.bak"
        bak.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")

    target.write_text(patched_code, encoding="utf-8")

    lines = [f"📝 已写入插件 `{safe_name}.py`（{len(code)} 字符）"]
    if patched_code != code:
        lines.append("💡 自动修正了相对导入路径（from .base → from ..base）")

    if make_load:
        ok2, msg2, new_tools, new_cmds = _load_plugin_file(target)
        lines.append("")
        lines.append(msg2)
        if ok2 and new_tools:
            lines.append("\n新注册的工具：")
            for n in new_tools:
                lines.append(f"  • `{n}`")

    return ToolResult(text="\n".join(lines))


# ─── plugin_reload ─────────────────────────────────────────────

def _plugin_reload(args, ctx):
    _ensure_plugins_dir()
    name = (args.get("name") or args.get("filename") or "").strip()

    if not name or name in ("all", "*"):
        results = _load_all_plugins()
        lines = [f"🔄 重载全部插件（{len(results)} 个文件）", "---"]
        for fname, msg in results:
            mark = "✅" if msg.startswith("✅") else "❌"
            lines.append(f"{mark} {fname}: {msg}")
        return ToolResult(text="\n".join(lines))

    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    filepath = PLUGINS_DIR / f"{safe_name}.py"
    if not filepath.exists():
        return ToolResult(text=f"❌ 插件不存在：{safe_name}.py")

    ok, msg, _, _ = _load_plugin_file(filepath)
    return ToolResult(text=f"🔄 重载 {safe_name}.py\n\n{msg}")


# ─── plugin_list ───────────────────────────────────────────────

def _plugin_list(args, ctx):
    _ensure_plugins_dir()

    # 内置模块
    internal_mods = [
        "builtin", "files", "shell", "tabbit", "web",
        "grep", "edit", "search", "git_tools", "wait_tool",
        "range_read", "sysinfo", "terminal", "pyeval",
        "patch", "port", "httpserve", "env_tools", "uia",
        "plugin",
    ]
    internal_map = {}
    for m in internal_mods:
        mod = sys.modules.get(f"app.tools.{m}")
        if not mod:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name, None)
            if isinstance(obj, Tool) and obj.name:
                internal_map.setdefault(m, []).append(obj.name)

    # AI 生成插件
    ai_map = {}
    for pyfile in sorted(PLUGINS_DIR.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        mod_name = f"app.tools.plugins.{pyfile.stem}"
        mod = sys.modules.get(mod_name)
        if not mod:
            ok, _, _, _ = _load_plugin_file(pyfile)
            mod = sys.modules.get(mod_name)
        ai_map[pyfile.name] = []
        if mod:
            for attr_name in dir(mod):
                obj = getattr(mod, attr_name, None)
                if isinstance(obj, Tool) and obj.name:
                    ai_map[pyfile.name].append(obj.name)

    lines = ["📋 插件一览", "=" * 40]

    # 内置
    lines.append(f"\n**内置插件（{len(internal_mods)} 个模块）**")
    for mod, names in sorted(internal_map.items()):
        lines.append(f"\n  📦 {mod}/ ({len(names)} 个)")
        for n in sorted(names):
            t = REGISTRY.get(n)
            lines.append(f"    • `{n}` [{t.perm}] — {t.title}")

    # AI
    lines.append(f"\n**AI 生成插件（{len(ai_map)} 个文件）**")
    if not ai_map:
        lines.append("  （暂无）")
    for fname, names in sorted(ai_map.items()):
        lines.append(f"\n  🤖 {fname} ({len(names)} 个)")
        for n in sorted(names):
            t = REGISTRY.get(n)
            lines.append(f"    • `{n}` [{t.perm}] — {t.title}")

    return ToolResult(text="\n".join(lines))


# ─── 启动自动扫描 ─────────────────────────────────────────────

def auto_discover():
    _ensure_plugins_dir()
    for pyfile in sorted(PLUGINS_DIR.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        ok, msg, _, _ = _load_plugin_file(pyfile)
        if msg.startswith("❌"):
            print(f"[plugin] ❌ {pyfile.name}: {msg}")


# ─── 注册 ──────────────────────────────────────────────────────

def register_all():
    _TEMPLATE = (
        "```python\n"
        "from ..base import Tool, ToolResult\n"
        "from .. import register\n\n"
        "def _my_tool(args, ctx):\n"
        "    return ToolResult(text='hello')\n\n"
        "def register_all():\n"
        "    register(Tool(name='my_tool', title='示例', perm='Visitor', handler=_my_tool))\n"
        "```"
    )

    register(Tool(
        name="plugin_create", title="创建插件", perm="Root",
        desc=(
            "写一个新插件 .py 文件并自动加载。"
            "插件必须导出 register_all()，里面用 register(Tool(...)) 注册工具。"
            f"模板：\n{_TEMPLATE}"
        ),
        usage='{"name":"my_plugin","code":"...完整Python代码..."}',
        required={"name": "string", "code": "string"}, handler=_plugin_create,
    ))

    register(Tool(
        name="plugin_reload", title="重载插件", perm="Root",
        desc=(
            "热重载指定插件或全部。name='all' 或 '*' 则重载 plugins/ 下全部。"
            "修改了已加载插件的 .py 文件后用这个生效。"
        ),
        usage='{"name":"all"}',
        handler=_plugin_reload,
    ))

    register(Tool(
        name="plugin_list", title="列出插件", perm="Visitor",
        desc="列出所有内置插件和 AI 生成的插件，显示工具列表和权限等级。",
        usage="{}", handler=_plugin_list,
    ))
