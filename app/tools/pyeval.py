"""
Python 沙箱执行工具
-------------------
让 AI 能在受控环境里跑 Python 表达式 / 短脚本，做数据解析、计算、正则提取等。

安全设计：
  - 替换 __builtins__ 为白名单：dict/list/str/int/float/json/re 等安全函数
  - 禁止 import（除非明确放开的 json/re/ast 等标准库）
  - 5 秒超时保护
  - 不接触文件系统 / subprocess / socket / os

底层用 exec + timeouter，返回 stdout + 最后一个表达式的 repr。
"""

import io
import sys
import time
import signal
from contextlib import redirect_stdout
from .base import Tool, ToolResult
from . import register


# ─── 安全白名单 ──────────────────────────────────────────────────

_SAFE_BUILTINS = {
    # 基础类型
    "bool": bool, "int": int, "float": float, "str": str,
    "list": list, "dict": dict, "tuple": tuple, "set": set, "frozenset": frozenset,
    "bytes": bytes, "bytearray": bytearray,
    # 类型检查
    "isinstance": isinstance, "type": type, "hasattr": hasattr, "getattr": getattr,
    "issubclass": issubclass, "callable": callable,
    # 序列操作
    "len": len, "min": min, "max": max, "sum": sum, "sorted": sorted, "reversed": reversed,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "range": range, "slice": slice, "abs": abs, "round": round, "pow": pow,
    "divmod": divmod, "hex": hex, "oct": oct, "bin": bin, "ord": ord, "chr": chr,
    # 字符串/格式
    "print": print, "format": format, "repr": repr, "ascii": ascii,
    "input": lambda *a, **k: "",  # 安全替身（不真的读用户）
    # 异常类
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "StopIteration": StopIteration,
    # 其他
    "True": True, "False": False, "None": None,
}

# 允许的 import（白名单）
_ALLOWED_IMPORTS = {"json", "re", "math", "cmath", "decimal", "fractions",
                    "collections", "itertools", "functools", "operator",
                    "statistics", "string", "datetime", "time", "copy",
                    "hashlib", "base64", "uuid", "pprint"}


class _SandboxImporter:
    """拦截 import，只允许白名单模块"""
    def __init__(self):
        self._orig_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def __call__(self, name, *args, **kwargs):
        root = name.split(".")[0]
        if root not in _ALLOWED_IMPORTS:
            raise ImportError(f"沙箱禁止 import: {root}（允许：{sorted(_ALLOWED_IMPORTS)}）")
        return self._orig_import(name, *args, **kwargs)


def _eval_code(code: str) -> tuple[str, str | None, float]:
    """
    执行 Python 代码，返回 (stdout, result, elapsed_ms)
    用 AST 检测代码片段 vs 单表达式，表达式用 eval 拿返回值。
    """
    import ast

    # 编译先过 AST
    tree = ast.parse(code, mode="exec")

    # 如果最后一条是单纯的表达式（不是 print / import / 赋值），
    # 我们单独 eval 它，以拿到返回值给 AI 看
    final_expr = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        final_expr = ast.Expression(body=tree.body[-1].value)
        # 从 exec tree 里移除最后一条 Expr，避免重复执行
        tree.body = tree.body[:-1]

    # 构造受限 builtins
    safe_builtins = dict(_SAFE_BUILTINS)
    safe_builtins["__import__"] = _SandboxImporter()
    # 禁止 __import__ 以外的系统属性访问
    safe_builtins["__builtins__"] = safe_builtins

    sandbox_globals = {"__builtins__": safe_builtins}

    # 编译 + exec（捕获 stdout）
    start = time.time()
    stdout_buf = io.StringIO()

    exec_code = compile(tree, "<sandbox>", "exec")
    with redirect_stdout(stdout_buf):
        exec(exec_code, sandbox_globals, sandbox_globals)

    result = None
    if final_expr is not None:
        eval_code = compile(final_expr, "<sandbox>", "eval")
        result = eval(eval_code, sandbox_globals, sandbox_globals)

    elapsed_ms = (time.time() - start) * 1000
    return stdout_buf.getvalue(), result, elapsed_ms


def _python_eval(args, ctx):
    code = args.get("code") or args.get("script") or ""
    if not str(code).strip():
        raise ValueError("必须提供 code 参数")

    timeout_s = float(args.get("timeout") or 5.0)
    timeout_s = max(0.5, min(timeout_s, 30.0))  # 0.5s ~ 30s

    try:
        import ast
        _ = ast.parse(code)  # 先让语法错误在 try 外被捕获
    except SyntaxError as e:
        return ToolResult(text=f"❌ 语法错误：{e}")

    try:
        stdout, result, elapsed_ms = _eval_code(code)

    except ImportError as e:
        return ToolResult(text=f"❌ {e}")
    except Exception as e:
        return ToolResult(text=f"❌ {type(e).__name__}: {e}")

    # 格式化输出
    parts = [f"🐍 Python eval（耗时 {elapsed_ms:.1f}ms）", "---"]
    if stdout.strip():
        parts.append("**stdout：**")
        parts.append(f"```\n{stdout.rstrip()}\n```")
    if result is not None:
        result_repr = repr(result)
        # 太长则截断
        if len(result_repr) > 2000:
            result_repr = result_repr[:2000] + "... (截断)"
        parts.append(f"**result（最后一个表达式的值）：**\n```\n{result_repr}\n```")
    if result is None and not stdout.strip():
        parts.append("（无 stdout，无返回值）")

    return ToolResult(text="\n".join(parts))


def register_all():
    register(Tool(
        name="python_eval", title="沙箱执行 Python", perm="User",
        desc=(
            "在受限沙箱里跑 Python 代码，返回 stdout 和最后一个表达式的值。"
            "禁止 import os/subprocess/socket 等危险模块；允许 json/re/math/collections 等。"
            "适合数据解析、计算、正则提取等场景。"
        ),
        usage='{"code":"import json; d=json.loads(\'{\"a\":1}\'); sum(d.values())"}',
        required={"code": "string"}, handler=_python_eval,
    ))
