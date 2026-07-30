#!/usr/bin/env python3
"""
微信公众号 MCP 服务器 (FastMCP 2.0 版本)
提供微信公众号管理的完整 MCP 工具集
支持 HTTP 模式和 stdio 模式
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Dict

# 修复嵌套异步事件循环问题
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

# 导入 FastMCP 2.0
try:
    from fastmcp import FastMCP
    logger.info("FastMCP 2.0 加载成功")
except ImportError:
    logger.error("无法导入 FastMCP 2.0，请确保已安装: pip install fastmcp>=2.0.0")
    sys.exit(1)

# 创建 FastMCP 服务器实例
mcp = FastMCP("wechat-official-account-mcp")

# 全局变量
auth_manager = None
storage_manager = None

def initialize_managers():
    """初始化认证和存储管理器"""
    global auth_manager, storage_manager
    try:
        from shared.storage.auth_manager import AuthManager
        from shared.storage.storage_manager import StorageManager
        if auth_manager is None:
            auth_manager = AuthManager()
        if storage_manager is None:
            storage_manager = StorageManager()
        return True
    except Exception as e:
        logger.error(f"初始化管理器失败: {e}")
        return False

async def handle_wechat_tool(tool_name: str, arguments: dict = None) -> str:
    """统一的微信工具调用处理函数"""
    global auth_manager, storage_manager
    
    try:
        # 确保存储管理器已初始化
        if not initialize_managers():
            return "初始化失败：无法初始化存储管理器"
        
        if arguments is None:
            arguments = {}
        
        # 认证工具
        if tool_name == "wechat_auth":
            from tools.auth import handle_auth_tool
            result = await handle_auth_tool(arguments, auth_manager)
            return result
        
        # 模板工具（不需要API客户端）
        elif tool_name == "wechat_template":
            from tools.template import handle_template_tool
            result = await handle_template_tool(arguments)
            return result
        
        # 需要 API 客户端的工具
        elif tool_name in ["wechat_temporary_media", "wechat_upload_img", "wechat_permanent_media", 
                          "wechat_draft", "wechat_publish"]:
            from shared.utils.wechat_api_client import WechatApiClient
            api_client = await WechatApiClient.from_auth_manager(auth_manager)
            
            if tool_name == "wechat_temporary_media":
                from tools.media import handle_media_upload_tool
                result = await handle_media_upload_tool(arguments, api_client, storage_manager)
            elif tool_name == "wechat_upload_img":
                from tools.media import handle_upload_img_tool
                result = await handle_upload_img_tool(arguments, api_client)
            elif tool_name == "wechat_permanent_media":
                from tools.media import handle_permanent_media_tool
                result = await handle_permanent_media_tool(arguments, api_client, storage_manager)
            elif tool_name == "wechat_draft":
                from tools.draft import handle_draft_tool
                result = await handle_draft_tool(arguments, api_client)
            elif tool_name == "wechat_publish":
                from tools.publish import handle_publish_tool
                result = await handle_publish_tool(arguments, api_client)
            
            return result
        
        # 静态网页工具
        elif tool_name == "static_page":
            from tools.static_pages import StaticPageManager
            # 使用全局共享的storage_manager实例，确保数据同步
            static_page_manager = StaticPageManager(storage_manager=storage_manager)
            from tools.static_pages import handle_static_page_tool
            result = handle_static_page_tool(arguments, static_page_manager)
            return result
        
        else:
            return f"未知工具: {tool_name}"
    
    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\n详细错误信息:\n{traceback.format_exc()}"
        logger.error(f"调用工具 {tool_name} 时出错: {error_detail}", exc_info=True)
        return f"工具调用失败: {error_detail}"

# ========== FastMCP 2.0 工具定义 ==========

@mcp.tool()
async def wechat_auth(action: str = None, app_id: str = None, app_secret: str = None) -> str:
    """管理微信公众号认证配置和 Access Token

    Args:
        action: 操作类型 (configure, get_token, refresh_token, get_config)
        app_id: 微信公众号 AppID（配置时必需）
        app_secret: 微信公众号 AppSecret（配置时必需）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 配置微信公众号
        >>> await wechat_auth(action="configure", app_id="wx1234567890", app_secret="secret123456")
        
        >>> # 获取 Access Token
        >>> await wechat_auth(action="get_token")
        
        >>> # 刷新 Access Token
        >>> await wechat_auth(action="refresh_token")
        
        >>> # 获取当前配置
        >>> await wechat_auth(action="get_config")
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if app_id:
        arguments['appId'] = app_id
    if app_secret:
        arguments['appSecret'] = app_secret
    return await handle_wechat_tool("wechat_auth", arguments)

@mcp.tool()
async def wechat_temporary_media(action: str = None, media_type: str = None, file_path: str = None) -> str:
    """管理/上传微信公众号临时素材

    Args:
        action: 操作类型 (upload, get, list)
        media_type: 素材类型 (image, voice, video, thumb)
        file_path: 本地文件路径（upload操作时使用）
        file_data: Base64编码的文件数据（upload操作时使用，与file_path二选一）
        file_name: 文件名（upload操作时可选）
        media_id: 媒体文件ID（get操作时必需）
        title: 视频素材的标题（video类型upload操作时可选）
        introduction: 视频素材的描述（video类型upload操作时可选）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 上传图片素材
        >>> await wechat_temporary_media(action="upload", media_type="image", file_path="/path/to/image.jpg")
        
        >>> # 获取临时素材
        >>> await wechat_temporary_media(action="get", media_id="media_id_here")
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if media_type:
        arguments['type'] = media_type
    if file_path:
        arguments['filePath'] = file_path
    return await handle_wechat_tool("wechat_media_upload", arguments)

@mcp.tool()
async def wechat_upload_img(file_path: str = None) -> str:
    """上传图文消息内所需的图片，不占用素材库限制（仅支持jpg/png格式，大小必须在1MB以下）

    Args:
        file_path: 本地文件路径（仅支持jpg/png格式，大小必须在1MB以下）
        file_data: Base64编码的文件数据（与file_path二选一，仅支持jpg/png格式，大小必须在1MB以下）

    Returns:
        操作结果文本，包含图片URL
        
    Examples:
        >>> # 上传图片
        >>> await wechat_upload_img(file_path="/path/to/image.jpg")
    """
    arguments = {}
    if file_path:
        arguments['filePath'] = file_path
    return await handle_wechat_tool("wechat_upload_img", arguments)

@mcp.tool()
async def wechat_permanent_media(action: str = None, media_type: str = None, media_id: str = None, file_path: str = None, file_data: str = None, title: str = None, introduction: str = None, offset: int = None, count: int = None) -> str:
    """管理微信公众号永久素材（添加、根据mediaId获取单个素材、分类型获取永久素材列表、删除、统计）

    Args:
        action: 操作类型 (add, get, delete, list, count)
        media_type: 素材类型 (image, voice, video, thumb, news)
        media_id: 媒体文件ID（get和delete操作时必需）
        file_path: 本地文件路径（add操作时使用）
        file_data: Base64编码的文件数据（add操作时使用，与file_path二选一）
        title: 视频素材的标题（add操作上传video类型时必填）
        introduction: 视频素材的描述（add操作上传video类型时可选）
        offset: 偏移量（list操作时使用，从0开始）
        count: 数量（list操作时使用，取值在1到20之间）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 添加永久图片素材
        >>> await wechat_permanent_media(action="add", media_type="image", file_path="/path/to/image.jpg")
        
        >>> # 获取单个永久素材
        >>> await wechat_permanent_media(action="get", media_id="media_id_here")
        
        >>> # 列出永久素材
        >>> await wechat_permanent_media(action="list", media_type="image", offset=0, count=10)
        
        >>> # 统计永久素材
        >>> await wechat_permanent_media(action="count")
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if media_type:
        arguments['type'] = media_type
    if media_id:
        arguments['mediaId'] = media_id
    if file_path:
        arguments['filePath'] = file_path
    if file_data:
        arguments['fileData'] = file_data
    if title:
        arguments['title'] = title
    if introduction:
        arguments['introduction'] = introduction
    if offset is not None:
        arguments['offset'] = offset
    if count is not None:
        arguments['count'] = count
    return await handle_wechat_tool("wechat_permanent_media", arguments)

@mcp.tool()
async def wechat_draft(action: str = None, media_id: str = None, article: dict = None, checkonly: bool = None, index: int = None, offset: int = None, count: int = None, no_content: bool = None) -> str:
    """管理微信公众号图文草稿

    Args:
        action: 操作类型 (add, get, delete, list, count, update, switch)
        media_id: 草稿 Media ID（获取、删除、更新时必需）
        article: 文章对象，包含以下字段（创建/更新时必需）：
            - title: 文章标题（必需）
            - content: 文章内容（必需）
            - thumbMediaId: 封面图片媒体ID（必需）
            - author: 作者（可选）
            - digest: 摘要（可选）
            - contentSourceUrl: 原文链接（可选）
        checkonly: 仅查询开关状态时传true，设置开关时传false或不传（switch操作时使用）
        index: 要更新的文章在图文消息中的位置（更新时使用，多图文消息时此字段才有意义），第一篇为0
        offset: 偏移量（列表时使用，从0开始）
        count: 数量（列表时使用，取值在1到20之间）
        noContent: 是否不返回content字段，true表示不返回，false或不传表示正常返回（列表时使用）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 创建草稿
        >>> await wechat_draft(action="add", article=article)
            >>> article = {
            ...     "title": "文章标题",
            ...     "content": "文章内容",
            ...     "thumbMediaId": "封面图片媒体ID",
            ...     "author": "作者姓名",
            ...     "digest": "文章摘要",
            ...     "contentSourceUrl": "原文链接"
            ... }
            
        >>> # 获取草稿
        >>> await wechat_draft(action="get", media_id="draft_media_id")
        
        >>> # 删除草稿
        >>> await wechat_draft(action="delete", media_id="draft_media_id")
        
        >>> # 列出草稿
        >>> await wechat_draft(action="list", offset=0, count=10)
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if media_id:
        arguments['mediaId'] = media_id
    if article:
        # 将article对象转换为articles数组格式
        articles = [{
            "title": article.get("title", ""),
            "content": article.get("content", ""),
            "thumbMediaId": article.get("thumbMediaId", ""),
            "author": article.get("author", ""),
            "digest": article.get("digest", ""),
            "contentSourceUrl": article.get("contentSourceUrl", "")
        }]
        arguments['articles'] = articles
    if checkonly is not None:
        arguments['checkonly'] = checkonly
    if index is not None:
        arguments['index'] = index
    if offset is not None:
        arguments['offset'] = offset
    if count is not None:
        arguments['count'] = count
    if no_content is not None:
        arguments['noContent'] = no_content
    return await handle_wechat_tool("wechat_draft", arguments)

@mcp.tool()
async def wechat_publish(action: str = None, media_id: str = None, publish_id: str = None, article_id: str = None, index: int = None, offset: int = None, count: int = None, no_content: bool = None) -> str:
    """管理微信公众号文章发布（提交发布任务、查询发布状态、获取已发布图文信息、删除已发布文章、获取发布列表）

    Args:
        action: 操作类型 (submit, get, delete, list, getarticle)
        mediaId: 草稿 Media ID（发布时必需）
        publishId: 发布任务ID（获取状态时必需）
        articleId: 文章ID（删除发布和获取已发布图文信息时必需，成功发布时返回的 article_id）
        index: 要删除的文章在图文消息中的位置（删除发布时可选，第一篇编号为1，不填或填0会删除全部文章）
        offset: 偏移量（列表时使用，从0开始）
        count: 数量（列表时使用，取值在1到20之间）
        noContent: 是否返回content字段（列表时可选，true表示不返回content字段，false表示正常返回，默认为false）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 提交发布草稿任务
        >>> await wechat_publish(action="submit", media_id="draft_media_id")
        
        >>> # 查询发布任务状态
        >>> await wechat_publish(action="get", publish_id="publish_task_id")
        
        >>> # 删除已发布的文章
        >>> await wechat_publish(action="delete", article_id="published_article_id")
        
        >>> # 获取发布列表（不返回content内容）
        >>> await wechat_publish(action="list", offset=0, count=10, no_content=True)
        
        >>> # 获取已发布图文信息
        >>> await wechat_publish(action="getarticle", article_id="published_article_id")
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if media_id:
        arguments['mediaId'] = media_id
    if publish_id:
        arguments['publishId'] = publish_id
    if article_id:
        arguments['articleId'] = article_id
    if index is not None:
        arguments['index'] = index
    if offset is not None:
        arguments['offset'] = offset
    if count is not None:
        arguments['count'] = count
    if no_content is not None:
        arguments['noContent'] = no_content
    return await handle_wechat_tool("wechat_publish", arguments)

@mcp.tool()
async def static_page(action: str = None, html_content: str = None, filename: str = None, type: str = None) -> str:
    """静态网页管理工具，用于生成和管理静态HTML网页

    Args:
        action: 操作类型 (generate, info, list, delete)
        html_content: HTML网页内容（generate操作时必需）
        filename: 文件名（info、delete操作时必需，可选的自定义文件名）
        type: 文件类型 (html, other)，默认html
        
    Returns:
        操作结果文本
        
    Examples:
        >>> # 生成静态网页
        >>> html_content = "<html><body><h1>Hello World</h1></body></html>"
        >>> await static_page(action="generate", html_content=html_content)
        
        >>> # 使用自定义文件名生成静态网页
        >>> await static_page(action="generate", html_content=html_content, filename="my_page")
        
        >>> # 生成其他类型文件
        >>> file_content = "some content"
        >>> await static_page(action="generate", html_content=file_content, filename="test.txt", type="other")
        
        >>> # 获取文件信息
        >>> await static_page(action="info", filename="abc123.html")
        
        >>> # 列出所有静态网页
        >>> await static_page(action="list")
        
        >>> # 删除静态网页
        >>> await static_page(action="delete", filename="abc123.html")
    """
    arguments = {}
    if action:
        arguments['action'] = action
    if html_content:
        arguments['htmlContent'] = html_content
    if filename:
        arguments['filename'] = filename
    if type:
        arguments['type'] = type
    return await handle_wechat_tool("static_page", arguments)

@mcp.tool()
async def user_verification_code(action: str = None, custom_code: str = None) -> str:
    """管理用户验证码（生成、验证、清理）

    Args:
        action: 操作类型 (generate, validate, cleanup)
        custom_code: 自定义验证码（generate操作时可选，validate操作时必需）

    Returns:
        操作结果文本
        
    Examples:
        >>> # 生成随机验证码
        >>> await user_verification_code(action="generate")
        
        >>> # 生成自定义验证码
        >>> await user_verification_code(action="generate", custom_code="apple123")
        
        >>> # 验证验证码
        >>> await user_verification_code(action="validate", custom_code="apple123")
        
        >>> # 清理过期验证码
        >>> await user_verification_code(action="cleanup")
    """
    global storage_manager
    try:
        # 确保存储管理器已初始化
        if not initialize_managers():
            return "初始化失败：无法初始化存储管理器"
        
        if action == "generate":
            return await generate_verification_code(storage_manager, custom_code)
        elif action == "validate":
            return await validate_verification_code(storage_manager, custom_code)
        elif action == "cleanup":
            return await cleanup_expired_codes(storage_manager)
        else:
            return f"错误：无效的操作类型 '{action}'，支持的操作：generate, validate, cleanup"
    except Exception as e:
        logger.error(f"验证码操作失败: {e}")
        return f"验证码操作失败: {str(e)}"

async def generate_verification_code(storage_manager, custom_code: str = None) -> str:
    """生成验证码"""
    import uuid
    from datetime import datetime, timedelta
    
    if custom_code:
        # 验证自定义验证码格式
        if len(custom_code) < 8:
            return "错误：验证码长度必须大于等于8位"
        
        # 检查是否包含英文字母和数字
        has_letter = any(c.isalpha() for c in custom_code)
        has_digit = any(c.isdigit() for c in custom_code)
        
        if not (has_letter and has_digit):
            return "错误：验证码必须包含英文字母和数字"
        
        # 检查是否已存在
        if storage_manager.get_verification_code(custom_code):
            return "错误：该验证码已存在，请选择其他验证码"
        
        verification_code = custom_code
    else:
        # 生成随机验证码：使用UUID（无-号，小写），不截取，确保包含至少一个字母和一个数字
        while True:
            # 生成UUID并去除-号，转为小写（32位字符）
            verification_code = uuid.uuid4().hex.lower()
            
            # 检查验证码是否包含至少一个字母和一个数字
            has_letter = any(c.isalpha() for c in verification_code)
            has_digit = any(c.isdigit() for c in verification_code)
            
            # 检查是否已存在且格式正确
            if not storage_manager.get_verification_code(verification_code) and has_letter and has_digit:
                break
    
    # 获取验证码有效天数配置
    valid_days = int(os.getenv('OPENAI_VERIFICATION_CODE_VALID_DAYS', '90'))
    
    # 设置过期时间（90天后）
    expires_at = datetime.now() + timedelta(days=valid_days)
    
    # 保存验证码
    code_info = {
        'code': verification_code,
        'created_at': datetime.now().isoformat(),
        'expires_at': expires_at.isoformat(),
        'used': False,
        'source': 'mcp_generated'
    }
    
    storage_manager.save_verification_code(code_info)
    
    return f"验证码生成成功：{verification_code}\n有效期：{valid_days}天\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

async def validate_verification_code(storage_manager, code: str) -> str:
    """验证验证码"""
    if not code:
        return "错误：请提供验证码"
    
    # 获取验证码信息
    code_info = storage_manager.get_verification_code(code)
    
    if not code_info:
        return "验证码不存在"
    
    # 检查是否已过期
    from datetime import datetime
    expires_at = datetime.fromisoformat(code_info['expires_at'])
    if datetime.now() > expires_at:
        return "验证码已过期"
    
    # 检查是否已使用
    if code_info.get('used', False):
        return "验证码已使用"
    
    return "验证码有效"

async def cleanup_expired_codes(storage_manager) -> str:
    """清理过期验证码"""
    cleaned_count = storage_manager.cleanup_expired_verification_codes()
    return f"清理完成，删除了 {cleaned_count} 个过期验证码"

@mcp.tool()
async def storage_sync(direction: str = "from_remote") -> str:
    """远程存储同步工具，用于在本地和S3兼容存储之间同步文件

    Args:
        direction: 同步方向 (from_remote - 从远程同步到本地, to_remote - 从本地同步到远程)
        
    Returns:
        同步结果文本
        
    Examples:
        >>> # 从远程S3存储同步到本地
        >>> await storage_sync(direction="from_remote")
        
        >>> # 从本地同步到远程S3存储
        >>> await storage_sync(direction="to_remote")
    """
    global storage_manager
    try:
        # 确保存储管理器已初始化
        if not initialize_managers():
            return "初始化失败：无法初始化存储管理器"
        
        # 执行同步操作
        if direction == "from_remote":
            result = await storage_manager.sync_from_remote()
        elif direction == "to_remote":
            result = await storage_manager.sync_to_remote()
        else:
            return f"错误：无效的同步方向 '{direction}'，支持的方向：from_remote, to_remote"
        
        if result['status'] == 'success':
            return (f"同步成功！\n" + 
                   f"消息：{result['message']}\n" + 
                   f"同步文件数：{result.get('sync_count', 0)}\n" + 
                   f"覆盖文件数：{result.get('override_count', 0)}" + 
                   (f"\n总对象数：{result.get('total_objects', 0)}" if 'total_objects' in result else ""))
        else:
            return f"同步失败：{result['message']}"
    except Exception as e:
        logger.error(f"同步操作失败: {e}")
        return f"同步操作失败: {str(e)}"

# @mcp.tool()
# async def wechat_template(action: str = None, title: str = None, intro: str = None, image: str = None, warning: str = None, sections: list = None, tags: list = None, action_button: dict = None, footer: list = None, template_name: str = None) -> str:
#     """根据P站样式模板生成公众号文章HTML内容。当用户说'使用p站模板'或'使用phub模板'时，使用此工具根据提供的内容生成符合P站样式的HTML文章。
# 
#     Args:
#         action: 操作类型 (generate, get_template)
#         title: 文章标题
#         intro: 文章介绍段落（可选）
#         image: 顶部图片占位符文本（可选）
#         warning: 警告提示文本（可选）
#         sections: 文章章节列表
#         tags: 标签列表（可选）
#         actionButton: 行动按钮（可选）
#         footer: 页脚文本列表（可选）
#         templateName: 模板文件名（默认为phub_template.html）
# 
#     Returns:
#         生成的HTML内容或模板内容
#         
#     Examples:
#         >>> # 生成HTML内容
#         >>> sections = [{
#         ...     "title": "章节标题",
#         ...     "content": "章节正文内容"
#         ... }]
#         >>> await wechat_template(action="generate", title="文章标题", sections=sections)
#         
#         >>> # 获取模板内容
#         >>> await wechat_template(action="get_template", template_name="phub_template.html")
#     """
#     arguments = {}
#     if action:
#         arguments['action'] = action
#     if title:
#         arguments['title'] = title
#     if intro:
#         arguments['intro'] = intro
#     if image:
#         arguments['image'] = image
#     if warning:
#         arguments['warning'] = warning
#     if sections:
#         arguments['sections'] = sections
#     if tags:
#         arguments['tags'] = tags
#     if action_button:
#         arguments['actionButton'] = action_button
#     if footer:
#         arguments['footer'] = footer
#     if template_name:
#         arguments['templateName'] = template_name
#     return await handle_wechat_tool("wechat_template", arguments)

@mcp.tool()
async def wechat_tool_call(tool_name: str, arguments: dict = None) -> str:
    """通用工具调用接口，可以调用所有已注册的微信工具

    Args:
        tool_name: 工具名称，支持的工具包括：
            - wechat_auth: 管理微信公众号认证配置和 Access Token
            - wechat_temporary_media: 管理微信公众号临时素材
            - wechat_upload_img: 上传图文消息内所需的图片
            - wechat_permanent_media: 管理微信公众号永久素材
            - wechat_draft: 管理微信公众号图文草稿
            - wechat_publish: 管理微信公众号文章发布
            - wechat_template: 根据P站样式模板生成公众号文章HTML内容（已注释）
        arguments: 工具参数，根据不同的tool_name传入相应的参数
        
    Returns:
        操作结果文本
        
    Examples:
        >>> # 调用认证工具配置公众号
        >>> await wechat_tool_call(
        ...     tool_name="wechat_auth", 
        ...     arguments={"action": "configure", "appId": "wx1234567890", "appSecret": "secret123456"}
        ... )
        
        >>> # 调用临时素材工具上传图片
        >>> await wechat_tool_call(
        ...     tool_name="wechat_temporary_media",
        ...     arguments={"action": "upload", "type": "image", "filePath": "/path/to/image.jpg"}
        ... )
        
        >>> # 调用草稿工具创建图文消息
        >>> article = {
        ...     "title": "文章标题",
        ...     "content": "文章内容",
        ...     "thumbMediaId": "media_id_here",
        ...     "author": "作者姓名",
        ...     "digest": "文章摘要"
        ... }
        >>> await wechat_tool_call(
        ...     tool_name="wechat_draft",
        ...     arguments={"action": "add", "article": article}
        ... )
        
        >>> # 调用发布工具提交草稿
        >>> await wechat_tool_call(
        ...     tool_name="wechat_publish",
        ...     arguments={"action": "submit", "mediaId": "draft_media_id"}
        ... )
        
        >>> # 调用发布工具获取列表（不返回content内容）
        >>> await wechat_tool_call(
        ...     tool_name="wechat_publish",
        ...     arguments={"action": "list", "offset": 0, "count": 10, "noContent": True}
        ... )
        
        >>> # 调用模板工具生成HTML内容
        >>> sections = [{
        ...     "title": "章节标题",
        ...     "content": "章节正文内容"
        ... }]
        >>> await wechat_tool_call(
        ...     tool_name="wechat_template",
        ...     arguments={"action": "generate", "title": "文章标题", "sections": sections}
        ... )
    """
    if arguments is None:
        arguments = {}
    return await handle_wechat_tool(tool_name, arguments)

@mcp.resource("template://phub_template")
async def get_phub_template() -> str:
    """P站样式模板资源"""
    try:
        from tools.template import load_template
        template = load_template("phub_template.html")
        if template:
            return template
        else:
            return "错误：无法加载模板文件"
    except Exception as e:
        logger.error(f"加载模板失败: {e}")
        return f"加载模板失败: {str(e)}"



def main():
    """主函数 - 同步入口点"""
    # 使用更健壮的事件循环处理方式
    try:
        # 尝试获取当前运行的事件循环
        loop = asyncio.get_running_loop()
        # 如果有正在运行的事件循环，检查是否已经在运行
        if loop.is_running():
            # 如果事件循环已经在运行，我们需要使用 nest_asyncio 来允许嵌套
            logger.debug("检测到正在运行的事件循环，应用 nest_asyncio 补丁")
            try:
                import nest_asyncio
                nest_asyncio.apply()
                logger.debug("nest_asyncio 补丁应用成功")
            except ImportError:
                logger.warning("nest_asyncio 未安装，尝试直接运行")
        # 使用 loop.run_until_complete 运行主函数
        loop.run_until_complete(mcp_server_main())
    except RuntimeError as e:
        if "no running event loop" in str(e):
            # 如果没有正在运行的事件循环，使用 asyncio.run 创建新的事件循环
            logger.debug("未检测到正在运行的事件循环，创建新的事件循环运行主函数")
            asyncio.run(mcp_server_main())
        else:
            # 重新抛出其他 RuntimeError 异常
            raise

async def mcp_server_main():
    """MCP 服务器主函数（内部实现）"""
    try:
        # 添加项目目录到 Python 路径
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        
        # 加载环境变量（.env 文件）
        if os.path.exists('.env'):
            from dotenv import load_dotenv
            load_dotenv()
        
        # 确保数据目录存在
        Path('data').mkdir(exist_ok=True)
        Path('logs').mkdir(exist_ok=True)
        
        # 导入项目模块
        try:
            initialize_managers()
        except ImportError as e:
            logger.error(f"导入项目模块失败: {e}", exc_info=True)
            raise RuntimeError("无法导入项目模块") from e
        
        logger.info("微信公众号 MCP 服务器启动中...")
        
        # 获取传输模式和配置
        transport = os.getenv('MCP_TRANSPORT', 'stdio')  # 默认使用stdio，支持http和sse
        host = os.getenv('MCP_HOST', '0.0.0.0')
        port = int(os.getenv('MCP_PORT', '3003'))
        
        logger.info(f"使用 FastMCP 2.0 启动服务器...")
        logger.info(f"传输模式: {transport}")
        
        # 创建一个包装函数来运行异步方法
        async def run_mcp():
            if transport.lower() == 'stdio':
                # stdio 模式（传统方式）
                logger.info("启动 stdio 模式")
                await mcp.run_async(transport)
            else:
                # HTTP/SSE 模式（FastMCP 2.0 新功能）
                logger.info(f"HTTP 服务器地址: http://{host}:{port}")
                # 配置uvicorn，设置合理的优雅关闭超时时间
                uvicorn_config = {
                    "timeout_graceful_shutdown": 5  # 5秒优雅关闭超时
                }
                await mcp.run_async(transport, host=host, port=port, uvicorn_config=uvicorn_config)
        
        # 运行 MCP 服务器
        # 直接运行异步函数，让外层的事件循环处理逻辑来决定如何执行
        await run_mcp()
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务器...")
    except Exception as e:
        logger.error(f"MCP 服务器启动异常: {str(e)}", exc_info=True)
        raise RuntimeError("MCP 服务器启动失败") from e


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"启动失败: {e}")
        # 在嵌套异步中不能使用 sys.exit()，我们抛出异常让上层处理
        raise

