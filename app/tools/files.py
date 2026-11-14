from pathlib import Path
from .base import Tool, ToolResult
from . import register
from ..config import CONFIG

def _resolve(p):
    if not p or not str(p).strip():
        raise ValueError("路径为空")
    full = Path(p).expanduser()
    if not full.is_absolute():
        full = CONFIG.WORKDIR / full
    full = full.resolve()
    try:
        full.relative_to(CONFIG.WORKDIR)
    except ValueError:
        raise ValueError(f"路径越界：{full} 不在工作目录 {CONFIG.WORKDIR} 内")
    return full

def _read(args, ctx):
    p = _resolve(args["path"])
    if not p.exists(): raise FileNotFoundError(f"文件不存在：{p}")
    if p.is_dir(): raise IsADirectoryError(f"是目录：{p}")
    limit = min(int(args.get("maxBytes") or 256 * 1024), 2 * 1024 * 1024)
    data = p.read_bytes()[:limit]
    return ToolResult(text=f"路径：{p}\n大小：{p.stat().st_size}\n---\n{data.decode('utf-8', errors='replace')}")

def _write(args, ctx):
    p = _resolve(args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    data = str(args["content"]).encode("utf-8")
    p.write_bytes(data)
    return ToolResult(text=f"已写入 {p}（{len(data)} 字节）")

def _append(args, ctx):
    p = _resolve(args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    data = str(args["content"]).encode("utf-8")
    with open(p, "ab") as f: f.write(data)
    return ToolResult(text=f"已追加到 {p}（+{len(data)} 字节）")

def _list(args, ctx):
    p = _resolve(args["path"])
    if not p.is_dir(): raise NotADirectoryError(str(p))
    rows = []
    for entry in sorted(p.iterdir(), key=lambda x: (0 if x.is_dir() else 1, x.name.lower())):
        st = entry.stat()
        rows.append(f"[{'目录' if entry.is_dir() else '文件'}] {entry.name}"
                    + (f"  ({st.st_size} B)" if entry.is_file() else ""))
    return ToolResult(text=f"目录：{p}\n共 {len(rows)} 项\n---\n" + "\n".join(rows))

def _exists(args, ctx):
    try:
        p = _resolve(args["path"])
    except ValueError as e:
        return ToolResult(text=str(e))
    return ToolResult(text=f"{'存在' if p.exists() else '不存在'}：{p}")

def _mkdir(args, ctx):
    p = _resolve(args["path"]); p.mkdir(parents=True, exist_ok=True)
    return ToolResult(text=f"已创建目录：{p}")

def _move(args, ctx):
    src = _resolve(args["path"]); dst = _resolve(args["to"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return ToolResult(text=f"已移动：{src} -> {dst}")

def _delete(args, ctx):
    if args.get("confirm") is not True:
        raise PermissionError("删除需要显式 confirm:true")
    p = _resolve(args["path"])
    if not p.exists(): raise FileNotFoundError(str(p))
    if p.is_dir():
        if args.get("recursive") is not True:
            raise PermissionError("删除目录需 recursive:true")
        import shutil; shutil.rmtree(p)
        return ToolResult(text=f"已递归删除：{p}")
    p.unlink()
    return ToolResult(text=f"已删除：{p}")

def register_all():
    register(Tool(name="file_read", title="读取文件", perm="Visitor",
        desc="读取文本文件（限定工作目录内）。", usage='{"path":"a.txt"}',
        required={"path": "string"}, handler=_read))
    register(Tool(name="file_write", title="写入文件", perm="User",
        desc="写入文件（覆盖，自动建父目录）。", usage='{"path":"a.txt","content":"hi"}',
        required={"path": "string", "content": "string"}, handler=_write))
    register(Tool(name="file_append", title="追加文件", perm="User",
        desc="追加内容到文件末尾。", usage='{"path":"log.txt","content":"line"}',
        required={"path": "string", "content": "string"}, handler=_append))
    register(Tool(name="file_list", title="列出目录", perm="Visitor",
        desc="列出目录内容。", usage='{"path":"."}',
        required={"path": "string"}, handler=_list))
    register(Tool(name="file_exists", title="检查路径", perm="Visitor",
        desc="检查文件/目录是否存在。", usage='{"path":"a.txt"}',
        required={"path": "string"}, handler=_exists))
    register(Tool(name="file_mkdir", title="新建目录", perm="User",
        desc="递归创建目录。", usage='{"path":"newdir"}',
        required={"path": "string"}, handler=_mkdir))
    register(Tool(name="file_move", title="移动/重命名", perm="User",
        desc="移动或重命名。", usage='{"path":"a.txt","to":"b.txt"}',
        required={"path": "string", "to": "string"}, handler=_move))
    register(Tool(name="file_delete", title="删除文件", perm="Root",
        desc="删除文件/目录（必须 confirm:true，目录需 recursive:true）。",
        usage='{"path":"a.txt","confirm":true}',
        required={"path": "string"}, handler=_delete))