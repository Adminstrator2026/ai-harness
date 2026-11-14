# ═══════════════════════════════════════════════
# AI Harness — Dockerfile
# 多阶段构建：builder 装依赖，runtime 跑服务
# 非 Windows 基础镜像（Debian slim）— 在 Linux 上跑 Agent 核心
# Windows 桌面自动化（uia_* 工具）在容器里不可用，会自动降级
# ═══════════════════════════════════════════════

# ─── Stage 1: builder（装依赖） ────────────────────────────────
FROM python:3.12-slim AS builder

# 系统依赖（psutil 编译需要）
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# 先拷 requirements，让 pip install 缓存生效（只有 requirements 变才重装）
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─── Stage 2: runtime（最终镜像，只有运行时文件） ────────────────
FROM python:3.12-slim AS runtime

# 关闭 Python 字节码 + 启用无缓冲输出（容器里看实时日志）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# 从 builder 拷已安装的依赖（只拷 site-packages 和 dist-info）
COPY --from=builder /install /usr/local

# 非 root 用户跑（security best practice）
RUN groupadd -g 1000 appuser \
    && useradd -m -u 1000 -g appuser appuser

# 工作目录
WORKDIR /app
COPY app ./app

# 工作目录（Agent 读写文件的地方），独立卷挂载
RUN mkdir -p /workspace && chown -R appuser:appuser /workspace /app

# 运行时配置（可被 docker-compose 覆盖）
ENV AIH_HOST=0.0.0.0 \
    AIH_PORT=8765 \
    AIH_WORKDIR=/workspace \
    AIH_TOKEN="" \
    AIH_SANDBOX=true

EXPOSE 8765

# 健康检查：每 30s 探一次 /api/health，连续 3 次失败算 unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health').read()" || exit 1

# 以非 root 身份运行
USER appuser

# 入口：server.py 是 Flask 应用
CMD ["python", "-m", "app.server"]
