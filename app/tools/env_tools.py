"""
配置文件读写工具（env_get / env_set）
------------------------------------
针对 .env / .yaml / .json / .toml 等配置文件的 key=value 操作。
让 AI 能安全地改配置，不用整个重写文件。

支持格式：
  - .env：KEY=VALUE（简单解析）
  - .yaml / .yml：顶层 key: value（仅支持字符串/数字，不处理嵌套）
  - .json：完整 JSON，支持 set 复杂值
  - .toml：简单 key=value 或 [section]

实现简化：不引入 yaml/toml 依赖，用正则逐行解析，满足 90% 场景。
"""

import re
import json
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


# ─── 格式检测 ──────────────────────────────────────────────────

def _detect_format(path: Path, content: str) -> str:
    ext = path.suffix.lower()
    if ext == ".env":
        return "env"
    if ext in (".yaml", ".yml"):
        return "yaml"
    if ext == ".json":
        return "json"
    if ext == ".toml":
        return "toml"
    # 模糊检测：看文件内容长什么样
    if content.lstrip().startswith("{") or content.lstrip().startswith("["):
        try:
            json.loads(content)
            return "json"
        except Exception:
            pass
    # 默认当 env
    return "env"


# ─── env_get ──────────────────────────────────────────────────

def _get_env(args, ctx):
    path_arg = args.get("path") or args.get("file")
    key = args.get("key")
    section = args.get("section")

    if not path_arg:
        raise ValueError("必须提供 path 参数")

    p = _resolve_path(path_arg)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    if p.is_dir():
        raise IsADirectoryError(f"是目录：{p}")

    content = p.read_text(encoding="utf-8", errors="replace")
    fmt = _detect_format(p, content)

    if fmt == "json":
        return _get_json(content, key, p)
    if fmt == "yaml":
        return _get_simple_kv(content, key, p, fmt)
    if fmt == "toml":
        return _get_toml(content, key, section, p)
    # env
    return _get_env_file(content, key, p)


def _get_json(content: str, key: str | None, path: Path) -> ToolResult:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return ToolResult(text=f"❌ JSON 解析失败：{e}")

    rel = path.relative_to(CONFIG.WORKDIR)
    if key is None:
        return ToolResult(text=f"📋 {rel}（JSON，{len(data)} 个顶层 key）：\n\n```\n{json.dumps(data, indent=2, ensure_ascii=False)[:4000]}\n```")

    if isinstance(data, dict) and key in data:
        val = data[key]
        return ToolResult(text=f"• {key} = `{json.dumps(val, ensure_ascii=False)}`")
    return ToolResult(text=f"key '{key}' 不存在（文件 {rel}）")


def _get_simple_kv(content: str, key: str | None, path: Path, fmt: str) -> ToolResult:
    """yaml 顶层 key=value 或 env key=value 统一解析"""
    pairs: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        m = re.match(r"^([A-Za-z_][\w.\-]*)\s*[:=]\s*(.*)$", stripped)
        if m:
            k, v = m.group(1), m.group(2).strip()
            # 去掉首尾引号
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            pairs[k] = v

    rel = path.relative_to(CONFIG.WORKDIR)
    if key is None:
        lines = [f"📋 {rel}（{fmt}，{len(pairs)} 个顶层 key）：", "---"]
        for k, v in pairs.items():
            lines.append(f"• **{k}** = `{v}`")
        return ToolResult(text="\n".join(lines))

    if key in pairs:
        return ToolResult(text=f"• {key} = `{pairs[key]}`")
    return ToolResult(text=f"key '{key}' 不存在（文件 {rel}，格式 {fmt}）")


def _get_env_file(content: str, key: str | None, path: Path) -> ToolResult:
    return _get_simple_kv(content, key, path, "env")


def _get_toml(content: str, key: str | None, section: str | None, path: Path) -> ToolResult:
    """极简 TOML 解析：支持 [section] 和 key = value"""
    current_section = ""
    pairs: dict[tuple[str, str], str] = {}

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sm = re.match(r"^\[([^\]]+)\]", stripped)
        if sm:
            current_section = sm.group(1).strip()
            continue
        m = re.match(r"^([A-Za-z_][\w.\-]*)\s*=\s*(.*)$", stripped)
        if m:
            k, v = m.group(1), m.group(2).strip()
            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                v = v[1:-1]
            pairs[(current_section, k)] = v

    rel = path.relative_to(CONFIG.WORKDIR)

    if key is None:
        # 按 section 分组展示
        sections: dict[str, list[str]] = {}
        for (sec, k), v in pairs.items():
            sec_name = sec or "(全局)"
            sections.setdefault(sec_name, []).append(f"  • **{k}** = `{v}`")
        lines = [f"📋 {rel}（TOML，{len(pairs)} 个 key，{len(sections)} 个 section）：", "---"]
        for sec_name, entries in sections.items():
            lines.append(f"[{sec_name}]")
            lines.extend(entries)
        return ToolResult(text="\n".join(lines))

    target_sec = section or ""
    if (target_sec, key) in pairs:
        return ToolResult(text=f"• [{target_sec or '(全局)'}] {key} = `{pairs[(target_sec, key)]}`")
    return ToolResult(text=f"key '{key}' 不存在（section='{target_sec or '(全局)'}'，文件 {rel}）")


# ─── env_set ──────────────────────────────────────────────────

def _set_env(args, ctx):
    path_arg = args.get("path") or args.get("file")
    key = args.get("key")
    value = args.get("value")
    section = args.get("section")
    create = bool(args.get("create", True))

    if not path_arg:
        raise ValueError("必须提供 path 参数")
    if not key:
        raise ValueError("必须提供 key 参数")
    if value is None:
        raise ValueError("必须提供 value 参数")

    p = _resolve_path(path_arg)
    rel = p.relative_to(CONFIG.WORKDIR)

    if not p.exists():
        if not create:
            raise FileNotFoundError(f"文件不存在且 create=false：{p}")
        p.parent.mkdir(parents=True, exist_ok=True)
        original = ""
        fmt = _guess_format_from_path(p)
    else:
        original = p.read_text(encoding="utf-8", errors="replace")
        fmt = _detect_format(p, original)

    if fmt == "json":
        return _set_json(p, original, key, value, rel)
    if fmt == "toml":
        return _set_toml(p, original, key, value, section, create, rel)
    # env / yaml：行匹配替换
    return _set_line_kv(p, original, key, value, fmt, rel)


def _guess_format_from_path(path: Path) -> str:
    ext = path.suffix.lower()
    return {"env": "env", "yaml": "yaml", "yml": "yaml",
            "json": "json", "toml": "toml"}.get(ext, "env")


def _set_json(path: Path, content: str, key: str, value, rel) -> ToolResult:
    try:
        data = json.loads(content) if content.strip() else {}
    except json.JSONDecodeError as e:
        return ToolResult(text=f"❌ JSON 解析失败：{e}")
    if not isinstance(data, dict):
        return ToolResult(text=f"❌ JSON 顶层不是对象，无法 set key '{key}'")

    existed = key in data
    data[key] = _coerce_json_value(value)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    action = "更新" if existed else "新增"
    return ToolResult(text=f"✅ {action} {key} = `{json.dumps(value, ensure_ascii=False)}` → {rel}")


def _coerce_json_value(v):
    """JSON value 可以是字符串（AI 传的原始），尝试自动转成数字/布尔/null"""
    if not isinstance(v, str):
        return v
    vv = v.strip()
    if vv.lower() in ("true", "false"):
        return vv.lower() == "true"
    if vv.lower() in ("null", "none"):
        return None
    try:
        if "." in vv:
            return float(vv)
        return int(vv)
    except ValueError:
        pass
    return v  # 保持字符串


def _set_line_kv(path: Path, content: str, key: str, value, fmt: str, rel) -> ToolResult:
    """env / yaml 行匹配替换；找不到则追加"""
    # 值加引号（避免空格/特殊字符）
    value_str = str(value)
    if " " in value_str or any(c in value_str for c in "\"'#"):
        # 把内部的双引号 escape 掉
        escaped = value_str.replace('"', '\\"')
        value_str = f'"{escaped}"'

    sep = ":" if fmt == "yaml" else "="
    pattern = re.compile(rf"^([ \t]*){re.escape(key)}([ \t]*){re.escape(sep)}([ \t]*)(.*)$", re.MULTILINE)

    if pattern.search(content):
        new_content = pattern.sub(
            lambda m: f'{m.group(1)}{key}{m.group(2)}{sep}{m.group(3)}{value_str}',
            content,
        )
        path.write_text(new_content, encoding="utf-8")
        return ToolResult(text=f"✅ 更新 {key} = {value_str} → {rel}")
    else:
        # 追加（保持原内容末尾换行风格）
        new_content = content
        if new_content and not new_content.endswith("\n"):
            new_content += "\n"
        new_content += f"{key}{sep}{value_str}\n"
        path.write_text(new_content, encoding="utf-8")
        return ToolResult(text=f"✅ 新增 {key} = {value_str} → {rel}")


def _set_toml(path: Path, content: str, key: str, value, section: str | None, create: bool, rel) -> ToolResult:
    """TOML 需考虑 section"""
    value_str = str(value)
    value_str_display = value_str
    if any(c in value_str for c in "\"'#") or " " in value_str:
        value_str = '"' + value_str.replace('"', '\\"') + '"'

    target_section = section or ""
    lines = content.splitlines(keepends=True)

    # 先在指定 section 里找有没有 key
    in_section = False
    replaced = False
    section_header_found = (target_section == "")

    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip("\r")
        sm = re.match(r"^\[([^\]]+)\]", stripped.strip())
        if sm:
            in_section = (sm.group(1).strip() == target_section)
            section_header_found = True
            continue
        if in_section or target_section == "":
            m = re.match(rf"^([ \t]*){re.escape(key)}\s*=\s*(.*)$", stripped)
            if m:
                lines[i] = f"{m.group(1)}{key} = {value_str}\n"
                replaced = True
                break

    if not replaced:
        # 没找到，要追加（先确保目标 section 存在）
        if target_section and not section_header_found:
            # 加 section 头 + key
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"\n[{target_section}]\n{key} = {value_str}\n")
        else:
            # 找最后一个 section header 后面
            insert_idx = len(lines)
            if target_section:
                for i, line in enumerate(lines):
                    sm = re.match(r"^\[([^\]]+)\]", line.strip())
                    if sm and sm.group(1).strip() == target_section:
                        insert_idx = i + 1
                        while insert_idx < len(lines) and not re.match(r"^\[", lines[insert_idx]):
                            insert_idx += 1
                        break
            lines.insert(insert_idx, f"{key} = {value_str}\n")

    path.write_text("".join(lines), encoding="utf-8")
    sec = f"[{target_section}] " if target_section else ""
    return ToolResult(text=f"✅ 设置 {sec}{key} = {value_str_display} → {rel}")


# ─── 注册 ──────────────────────────────────────────────────────

def register_all():
    register(Tool(
        name="env_get", title="读取配置", perm="Visitor",
        desc=(
            "读取 .env / .yaml / .json / .toml 配置文件的 key=value。"
            "不传 key 则列出全部顶层 key。"
        ),
        usage='{"path":".env","key":"API_KEY"}',
        required={"path": "string"}, handler=_get_env,
    ))
    register(Tool(
        name="env_set", title="写入配置", perm="User",
        desc=(
            "在配置文件里设置 key=value。"
            "key 存在则更新，不存在则追加（create=true 时文件不存在也会创建）。"
        ),
        usage='{"path":".env","key":"API_KEY","value":"sk-xxx"}',
        required={"path": "string", "key": "string", "value": "string"}, handler=_set_env,
    ))
