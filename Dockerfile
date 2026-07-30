# 使用多阶段构建优化镜像大小

# 第一阶段：构建阶段，用于安装依赖和编译扩展
FROM python:3.12-slim AS builder
# 设置工作目录
WORKDIR /app
# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http      
# 配置pip使用国内镜像源以加速下载
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn \
    # 配置apt使用阿里云镜像源以加速下载
    && sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    # 更新包列表并安装编译所需的系统依赖
    && apt-get update \
    && apt-get install -y --no-install-recommends --fix-missing \
       gcc \
       python3-dev \
    && rm -rf /var/lib/apt/lists/*
# 复制requirements.txt文件并安装所有依赖
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt


# 第二阶段：生产阶段，只包含运行时所需的文件
FROM python:3.12-slim
# 设置工作目录
WORKDIR /app
# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http    
# 从构建阶段复制安装的依赖
COPY --from=builder /root/.local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
# 复制项目文件
COPY . .
# 定义数据卷
VOLUME ["/app/data"]
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