import datetime
from .base import Tool, ToolResult
from . import register
from ..tools import REGISTRY, PERM_LEVEL, PERM_NAME

def _get_time(args, ctx):
    now = datetime.datetime.now()
    return ToolResult(text=now.strftime("%Y-%m-%d %H:%M:%S"))

def _list_tools(args, ctx):
    cfg = ctx.get("cfg", {})
    permission = str(cfg.get("permission") or "workspace")
    have = int(PERM_LEVEL.get(permission, 1))
    enabled_list = cfg.get("enabled_tools")
    if enabled_list is None:
        enabled_list = list(REGISTRY.keys())

    available = []
    for t in REGISTRY.values():
        if t.name not in enabled_list:
            continue
        need = int(PERM_LEVEL.get(t.perm or "read", 0))
        if need <= have:
            available.append(t)

    if not available:
        return ToolResult(text="当前没有任何可用的插件或工具。")

    lines = ["当前系统为你开放了以下插件/工具：\n"]
    for t in available:
        fields = ", ".join(t.required.keys()) if t.required else "无"
        lines.append(f"- **{t.name}**（{t.title}）：{t.desc}")
        lines.append(f"  ⚠️ 必填参数：{fields}")
        if t.usage:
            lines.append(f"  👉 示例：`{t.usage}`")
        lines.append("")

    lines.append("请将上述列表以 Markdown 格式输出给用户。")
    return ToolResult(text="\n".join(lines))

def _show_note(args, ctx):
    title = args.get("title") or "提示"
    text = args.get("text") or ""
    return ToolResult(
        text=f"已展示卡片：{title}",
        ui_event={"event": "note", "data": {"title": title, "text": text}},
    )

def _show_steps(args, ctx):
    steps = args.get("steps") or []
    norm = []
    for s in steps:
        if isinstance(s, str):
            norm.append({"text": s, "state": "todo"})
        elif isinstance(s, dict):
            norm.append({"text": str(s.get("text", "")), "state": s.get("state", "todo")})
    return ToolResult(
        text=f"已展示 {len(norm)} 个步骤",
        ui_event={"event": "steps", "data": {"title": args.get("title") or "进度", "steps": norm}},
    )

def _task_complete(args, ctx):
    summary = args.get("summary") or "任务已完成"
    return ToolResult(text=f"已标记任务完成：{summary}")

def _ask_user(args, ctx):
    return ToolResult(text="")

def register_all():
    register(Tool(name="get_time", title="获取时间",
        desc="返回服务器当前时间。", usage="{}", handler=_get_time))
    
    register(Tool(name="list_tools", title="查看可用插件",
        desc="列出当前 AI 可用的所有工具及其用法。当用户问「你能做什么」「查看插件」「有哪些功能」时，必须调用此工具。",
        usage="{}", handler=_list_tools))

    register(Tool(name="show_note", title="展示卡片",
        desc="插入一张 Markdown 卡片。",
        usage='{"title":"标题","text":"**正文**"}',
        required={"text": "string"}, handler=_show_note))
    register(Tool(name="show_steps", title="展示步骤",
        desc="展示多步骤进度清单。steps 为 [{text,state}]，state∈done/run/todo/err。",
        usage='{"title":"计划","steps":[{"text":"步骤1","state":"done"}]}',
        required={"steps": "array"}, handler=_show_steps))
    register(Tool(name="task_complete", title="任务完成",
        desc="全部完成后调用，结束执行并附一句总结。",
        usage='{"summary":"已完成的工作简述"}',
        handler=_task_complete))
    register(Tool(name="ask_user", title="向用户提问",
        desc="需要用户确认或补充信息时调用。questions 为 [{text,options:[{label}],custom}]。",
        usage='{"questions":[{"text":"问题","options":[{"label":"A"},{"label":"B"}]}]}',
        required={"questions": "array"}, interactive=True, handler=_ask_user))