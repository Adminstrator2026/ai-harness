from dataclasses import dataclass, field
from typing import Any, Callable, Optional

PERM_LEVEL = {"Visitor": 0, "User": 1, "Root": 2}
PERM_NAME  = {"Visitor": "访客（仅可查看）", "User": "用户（工作区内修改）", "Root": "超级用户（完全权限）"}

@dataclass
class ToolResult:
    text: str = ""
    ui_event: Optional[dict] = None

@dataclass
class Tool:
    name: str
    title: str
    desc: str = ""
    usage: str = "{}"
    required: dict = field(default_factory=dict)
    perm: str = "Visitor"
    interactive: bool = False
    handler: Optional[Callable[[dict, dict], Any]] = None

    def to_spec(self):
        return {
            "name": self.name, "title": self.title, "desc": self.desc,
            "usage": self.usage, "required": self.required,
            "perm": self.perm, "interactive": self.interactive,
        }


# ══════════════════════════════════════════════════════════════════
# REPL 斜杠指令体系（和 Tool 平行，插件可同时注册 Tool + Command）
# ══════════════════════════════════════════════════════════════════

@dataclass
class Command:
    """
    REPL 斜杠指令。handler 签名：handler(arg: str) -> None
    arg 是用户输入 /cmd 后面的整个字符串（已 strip）。
    指令名自动加 / 前缀（name="foo" → 用户打 /foo）。
    """
    name: str                    # 不含 /，如 "mycmd"
    help: str = ""               # 简短描述（/help 列表用）
    handler: Optional[Callable[[str], None]] = None


# 全局注册表
REGISTRY: dict[str, Tool] = {}          # Tool 注册表
COMMAND_REGISTRY: dict[str, Command] = {}  # REPL 斜杠指令注册表


def register(tool: Tool):
    """注册一个 Tool（Agent 可调用）"""
    REGISTRY[tool.name] = tool


def register_command(cmd: Command):
    """注册一个 REPL 斜杠指令"""
    if cmd.name.startswith("/"):
        cmd.name = cmd.name[1:]
    COMMAND_REGISTRY[cmd.name] = cmd