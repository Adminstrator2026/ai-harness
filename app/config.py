import os
from pathlib import Path

class Config:
    HOST      = os.environ.get("AIH_HOST", "0.0.0.0")
    PORT      = int(os.environ.get("AIH_PORT", "8765"))
    TOKEN     = os.environ.get("AIH_TOKEN", "")
    WORKDIR   = Path(os.environ.get("AIH_WORKDIR", os.getcwd())).resolve()
    
    # 统一自动执行轮数，防止死循环
    MAX_ROUNDS = 20
    DEFAULT_SYS = "你是一个 AI 助手。请使用 Markdown 格式回答，代码请指定语言。"

CONFIG = Config()