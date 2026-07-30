# 微信公众号 MCP 服务器 (FastMCP 2.0)

微信公众号管理的完整 MCP 工具集，支持 HTTP 模式和 stdio 模式，集成了 AI 聊天功能和静态网页管理。

## 功能特性

### 微信公众号管理
- **认证管理**：配置和管理微信公众号认证信息和 Access Token
- **素材管理**：上传、获取和管理临时素材和永久素材
- **图文草稿**：创建、更新、删除和查询图文草稿
- **文章发布**：提交发布任务、查询发布状态和管理已发布文章
- **静态网页**：生成和管理静态 HTML 网页

### AI 聊天功能
- **独立 AI 配置**：支持页面聊天和公众号消息回复使用独立的 AI 配置
- **交互模式**：支持 stream（流式）和 block（阻塞）两种交互模式
- **用户验证**：基于验证码的用户访问控制
- **浏览器持久化**：验证状态保存到浏览器 localStorage，有效期 90 天

### MCP 工具
- **user_verification_code**：生成和验证用户验证码
- **wechat_auth**：管理微信公众号认证
- **wechat_temporary_media**：管理临时素材
- **wechat_upload_img**：上传图文消息图片
- **wechat_permanent_media**：管理永久素材
- **wechat_draft**：管理图文草稿
- **wechat_publish**：管理文章发布
- **static_page**：管理静态网页
- **storage_sync**：远程存储同步

### 技术特性
- **FastMCP 2.0**：基于 FastMCP 2.0 框架，支持多种传输模式
- **环境变量配置**：支持通过环境变量灵活配置
- **Docker 支持**：提供 Dockerfile 和 docker-compose.yml
- **S3 兼容存储**：支持本地存储和 S3 兼容存储
- **定时任务**：支持验证码清理等定时任务

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 文件为 `.env`，并根据需要修改配置：

```bash
cp .env.example .env
```

### 3. 启动服务器

```bash
python main.py
```

### 4. 访问服务

- **Web 管理界面**：http://localhost:3004
- **聊天界面**：http://localhost:3004/chat
- **MCP 服务**：默认使用 stdio 模式，可通过配置改为 HTTP/SSE 模式

## 配置说明

### 主要环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `WECHAT_MSG_SERVER_ENABLE` | 是否启用微信消息服务器 | `true` |
| `WECHAT_MSG_SERVER_PORT` | 微信消息服务器端口 | `3004` |
| `MCP_ENABLE` | 是否启用 MCP 服务器 | `true` |
| `MCP_TRANSPORT` | MCP 传输模式 (stdio/http/sse) | `stdio` |
| `MCP_HOST` | MCP 服务器主机 | `0.0.0.0` |
| `MCP_PORT` | MCP 服务器端口 | `3003` |
| `WECHAT_OFFICIAL_ACCOUNT_NAME` | 微信公众号名称 | `AI助手` |
| `OPENAI_API_URL` | AI API URL | - |
| `OPENAI_API_KEY` | AI API Key | - |
| `OPENAI_MODEL` | AI 模型名称 | `gpt-3.5-turbo` |
| `OPENAI_INTERACTION_MODE` | AI 交互模式 (stream/block) | `block` |
| `OPENAI_WECHAT_API_URL` | 公众号 AI API URL | - |
| `OPENAI_WECHAT_API_KEY` | 公众号 AI API Key | - |
| `OPENAI_WECHAT_MODEL` | 公众号 AI 模型名称 | `gpt-3.5-turbo` |
| `OPENAI_WECHAT_INTERACTION_MODE` | 公众号 AI 交互模式 | `block` |
| `OPENAI_VERIFICATION_CODE_VALID_DAYS` | 验证码有效期（天） | `90` |
| `STORAGE_S3_ENABLE` | 是否启用 S3 存储 | `false` |
| `STORAGE_S3_READ_ONLY` | S3 存储是否为只读模式 | `false` |

### 微信公众号配置

| 变量名 | 说明 |
|--------|------|
| `WECHAT_APP_ID` | 微信公众号 AppID |
| `WECHAT_APP_SECRET` | 微信公众号 AppSecret |
| `WECHAT_TOKEN` | 微信公众号服务器配置 Token |

## 使用指南

### 1. 访问聊天界面

1. 打开浏览器，访问 http://localhost:3004/chat
2. 输入验证码（首次访问需要生成验证码）
3. 开始与 AI 进行聊天

### 2. 生成验证码

**方式 1：通过 Web 界面**

1. 访问 http://localhost:3004
2. 点击"生成验证码"按钮
3. 输入密码（从环境变量 OPENAI_CONFIG_PASSWORD 获取）
4. 生成并复制验证码

**方式 2：通过 MCP 工具**

```python
await user_verification_code(action="generate")
```

**方式 3：自定义验证码**

```python
await user_verification_code(action="generate", custom_code="your_custom_code")
```

### 3. 验证验证码

**通过 MCP 工具**

```python
await user_verification_code(action="validate", custom_code="your_verification_code")
```

### 4. 清理过期验证码

**通过 MCP 工具**

```python
await user_verification_code(action="cleanup")
```

### 5. 微信公众号管理

**配置公众号**

```python
await wechat_auth(action="configure", app_id="your_app_id", app_secret="your_app_secret")
```

**获取 Access Token**

```python
await wechat_auth(action="get_token")
```

**上传临时素材**

```python
await wechat_temporary_media(action="upload", media_type="image", file_path="/path/to/image.jpg")
```

**创建图文草稿**

```python
article = {
    "title": "文章标题",
    "content": "文章内容",
    "thumbMediaId": "media_id_here"
}
await wechat_draft(action="add", article=article)
```

**提交发布**

```python
await wechat_publish(action="submit", media_id="draft_media_id")
```

### 6. 静态网页管理

**生成静态网页**

```python
html_content = "<html><body><h1>Hello World</h1></body></html>"
await static_page(action="generate", html_content=html_content)
```

**使用自定义文件名**

```python
await static_page(action="generate", html_content=html_content, filename="my_page")
```

**列出所有静态网页**

```python
await static_page(action="list")
```

## 项目结构

```
wechat_official_account_mcp/
├── config/                # 配置文件目录
│   └── ai_config.json     # AI 服务配置
├── docs/                  # 文档目录
│   └── template_usage.md  # 模板使用说明
├── shared/                # 共享模块
│   ├── storage/           # 存储管理
│   │   ├── __init__.py
│   │   ├── auth_manager.py        # 认证管理
│   │   └── storage_manager.py     # 存储管理器
│   ├── utils/             # 工具模块
│   │   ├── __init__.py
│   │   ├── ai_service.py          # AI 服务
│   │   ├── web_server.py           # Web 服务器
│   │   └── wechat_api_client.py    # 微信 API 客户端
│   └── __init__.py
├── templates/             # 模板文件
│   ├── chat_template.html         # 聊天界面模板
│   ├── index_template.html        # 首页模板
│   ├── phub_template.html         # P站样式模板
│   └── static_pages_template.html # 静态网页模板
├── tools/                 # 工具模块
│   ├── __init__.py
│   ├── auth.py            # 认证工具
│   ├── draft.py           # 草稿管理
│   ├── media.py           # 素材管理
│   ├── publish.py         # 发布管理
│   ├── static_pages.py    # 静态网页管理
│   ├── template.py        # 模板工具
│   └── wechat_handler.py  # 微信消息处理
├── .env.example           # 环境变量示例
├── .gitignore             # Git 忽略文件
├── Dockerfile             # Docker 构建文件
├── README.md              # 项目说明文档
├── boot.sh                # 启动脚本
├── docker-compose.yml     # Docker Compose 配置
├── favicon.ico            # 网站图标
├── main.py                # 主入口文件
├── mcp_server.py          # MCP 服务器
└── requirements.txt       # 依赖列表
```

## Docker 部署

### 1. 构建镜像

```bash
docker build -t wechat-mcp-server .
```

### 2. 运行容器

```bash
docker run -d \
  --name wechat-mcp \
  -p 3003:3003 \
  -p 3004:3004 \
  -v $(pwd)/.env:/app/.env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  wechat-mcp-server
```

### 3. 使用 Docker Compose

```bash
docker-compose up -d
```

## 开发说明

### 1. 添加新的 MCP 工具

1. 在 `mcp_server.py` 中添加新的工具装饰器
2. 实现工具函数
3. 在 `handle_wechat_tool` 中添加工具处理逻辑

### 2. 修改 AI 服务

1. 编辑 `shared/utils/ai_service.py`
2. 实现或修改 AI 服务逻辑
3. 支持不同服务类型的配置

### 3. 修改 Web 界面

1. 编辑 `templates/chat_template.html`
2. 修改聊天界面样式或功能
3. 实现前端验证逻辑

## 故障排除

### 1. 验证码生成失败

- 检查环境变量 `OPENAI_CONFIG_PASSWORD` 是否配置
- 确保存储目录有写入权限
- 检查存储文件格式是否正确

### 2. AI 服务调用失败

- 检查 `AI_API_URL` 和 `AI_API_KEY` 是否正确配置
- 确保网络连接正常
- 检查 API 服务是否可用

### 3. 微信 API 调用失败

- 检查 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET` 是否正确
- 确保公众号已认证
- 检查网络连接是否正常

### 4. Web 服务器启动失败

- 检查端口是否被占用
- 确保依赖已正确安装
- 检查日志文件获取详细错误信息

## 日志

日志文件位于 `logs/mcp_server.log`，包含服务器启动、运行和错误信息。

## 许可证

MIT
