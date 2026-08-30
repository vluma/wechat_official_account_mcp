# 使用多阶段构建优化镜像大小

# 第一阶段：构建阶段，用于安装依赖（本项目所有依赖均提供预编译 manylinux wheel，
#            无需 gcc/python3-dev，避免从 Debian 镜像站下载 70MB+ 编译工具链）
FROM python:3.13-slim AS builder
# 设置工作目录
WORKDIR /app
# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http
# 配置 pip 使用国内镜像源以加速下载
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn
# 复制 requirements.txt 文件并安装所有依赖（--no-cache-dir 减小体积，--user 方便拷贝到生产阶段）
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt


# 第二阶段：生产阶段，只包含运行时所需的文件
FROM python:3.13-slim
# 设置工作目录
WORKDIR /app
# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http    
# 从构建阶段复制安装的依赖
COPY --from=builder /root/.local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
# 复制项目文件
COPY . .
# 定义数据卷
VOLUME ["/app/data"]
# 暴露端口：
#   3003 = MCP 服务默认 HTTP 端口（MCP_PORT 可覆盖）
#   3004 = 辅助服务/备用 MCP 端口（可通过环境变量按需启用）
EXPOSE 3003 3004
# MCP 服务器支持多种模式：
# - HTTP模式：默认模式，通过端口3003对外提供服务
# - stdio模式：通过标准输入输出通信（主要用于传统MCP客户端）
# - SSE模式：服务器发送事件模式
# 
# 环境变量控制：
# - MCP_TRANSPORT=http     # HTTP模式（Docker部署推荐）
# - MCP_TRANSPORT=stdio    # stdio模式（传统MCP客户端）
# - MCP_TRANSPORT=sse      # SSE模式（实时通知）
# 使用gevent作为生产环境服务器
CMD ["python", "main.py"]