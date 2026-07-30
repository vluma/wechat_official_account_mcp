"""
发布管理工具 - 管理微信公众号文章发布
"""
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional
from mcp.types import Tool

logger = logging.getLogger(__name__)

# 常量定义
PUBLISH_STATUS_MAP = {
    0: '成功',
    1: '发布中',
    2: '原创失败',
    3: '常规失败',
    4: '平台审核不通过',
    5: '成功后用户删除所有文章',
    6: '成功后系统封禁所有文章'
}

LIST_COUNT_MIN = 1
LIST_COUNT_MAX = 20
CONTENT_PREVIEW_LENGTH = 200


def _format_timestamp(timestamp: int) -> str:
    """
    格式化时间戳
    
    Args:
        timestamp: Unix时间戳
        
    Returns:
        格式化后的时间字符串
    """
    if not timestamp:
        return '未知'
    
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, OSError):
        return str(timestamp)


def _format_news_item(news_item: Dict[str, Any], include_content: bool = True, indent: str = "    ") -> List[str]:
    """
    格式化图文消息项
    
    Args:
        news_item: 图文消息项数据
        include_content: 是否包含内容信息
        indent: 缩进字符串
        
    Returns:
        格式化后的字符串列表
    """
    lines = []
    lines.append(f"{indent}标题: {news_item.get('title', '无')}")
    lines.append(f"{indent}作者: {news_item.get('author', '未设置')}")
    
    if news_item.get('digest'):
        lines.append(f"{indent}摘要: {news_item.get('digest')}")
    
    if include_content:
        content = news_item.get('content', '')
        if content:
            lines.append(f"{indent}内容长度: {len(content)} 字符")
            lines.append(f"{indent}内容预览: {content[:CONTENT_PREVIEW_LENGTH]}{'...' if len(content) > CONTENT_PREVIEW_LENGTH else ''}")
    
    if news_item.get('content_source_url'):
        lines.append(f"{indent}原文链接: {news_item.get('content_source_url')}")
    
    lines.append(f"{indent}封面图片ID: {news_item.get('thumb_media_id', '无')}")
    
    if news_item.get('thumb_url'):
        lines.append(f"{indent}封面图片URL: {news_item.get('thumb_url')}")
    
    lines.append(f"{indent}开启评论: {'是' if news_item.get('need_open_comment', 0) == 1 else '否'}")
    lines.append(f"{indent}仅粉丝可评论: {'是' if news_item.get('only_fans_can_comment', 0) == 1 else '否'}")
    
    if news_item.get('url'):
        lines.append(f"{indent}临时链接: {news_item.get('url')}")
    
    is_deleted = news_item.get('is_deleted', False)
    lines.append(f"{indent}是否已删除: {'是' if is_deleted else '否'}")
    
    return lines


def _handle_error(e: Exception, operation: str) -> str:
    """
    统一错误处理
    
    Args:
        e: 异常对象
        operation: 操作名称
        
    Returns:
        错误消息
    """
    error_detail = str(e)
    if logger.isEnabledFor(logging.DEBUG):
        error_detail += f"\n详细错误信息:\n{traceback.format_exc()}"
    logger.error(f'{operation}失败: {error_detail}', exc_info=True)
    return f"{operation}失败: {error_detail}"


def register_publish_tools() -> List[Tool]:
    """注册发布工具"""
    return [
        Tool(
            name="wechat_publish",
            description="管理微信公众号文章发布（提交发布任务、查询发布状态、获取已发布图文信息、删除已发布文章、获取发布列表）",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["submit", "get", "delete", "list", "getarticle"],
                        "description": "操作类型：submit(提交发布草稿任务), get(查询发布任务的状态和详情), delete(删除已发布的文章，此操作不可逆), list(获取发布列表), getarticle(获取已发布图文信息)"
                    },
                    "mediaId": {
                        "type": "string",
                        "description": "草稿 Media ID（发布时必需）"
                    },
                    "publishId": {
                        "type": "string",
                        "description": "发布任务ID（获取状态时必需）"
                    },
                    "articleId": {
                        "type": "string",
                        "description": "文章ID（删除发布和获取已发布图文信息时必需，成功发布时返回的 article_id）"
                    },
                    "index": {
                        "type": "integer",
                        "description": "要删除的文章在图文消息中的位置（删除发布时可选，第一篇编号为1，不填或填0会删除全部文章）"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "偏移量（列表时使用，从0开始）"
                    },
                    "count": {
                        "type": "integer",
                        "description": f"数量（列表时使用，取值在{LIST_COUNT_MIN}到{LIST_COUNT_MAX}之间）"
                    },
                    "noContent": {
                        "type": "boolean",
                        "description": "是否返回content字段（列表时可选，true表示不返回content字段，false表示正常返回，默认为false）"
                    }
                },
                "required": ["action"]
            }
        )
    ]


async def _handle_publish_submit(
    media_id: str,
    api_client
) -> str:
    """处理提交发布草稿任务"""
    result = await api_client.publish_draft(media_id)
    
    errcode = result.get('errcode', -1)
    errmsg = result.get('errmsg', '未知错误')
    
    if errcode != 0:
        return f"发布草稿失败：{errcode} - {errmsg}\n草稿ID: {media_id}"
    
    publish_id = result.get('publish_id', '')
    msg_data_id = result.get('msg_data_id', '')
    
    return ('发布任务提交成功！\n'
           f'草稿ID: {media_id}\n'
           f'发布任务ID: {publish_id}\n'
           f'消息数据ID: {msg_data_id}\n\n'
           '注意：\n'
           '- 这仅表示发布任务提交成功，不代表发布已完成\n'
           '- 发布结果将通过事件推送通知（PUBLISHJOBFINISH事件）\n'
           f'- 发布状态：{", ".join([f"{k}-{v}" for k, v in PUBLISH_STATUS_MAP.items()])}')


async def _handle_publish_get(
    publish_id: str,
    api_client
) -> str:
    """处理查询发布任务状态"""
    result = await api_client._request('POST', '/cgi-bin/freepublish/get', data={
        'publish_id': publish_id
    })
    
    errcode = result.get('errcode', 0)
    if errcode != 0:
        errmsg = result.get('errmsg', '未知错误')
        return f"获取发布状态失败：{errcode} - {errmsg}\n发布任务ID: {publish_id}"
    
    publish_status = result.get('publish_status', -1)
    status_text = PUBLISH_STATUS_MAP.get(publish_status, f'未知状态({publish_status})')
    
    result_lines = [
        "发布状态查询结果",
        "=" * 50,
        f"发布任务ID: {result.get('publish_id', publish_id)}",
        f"发布状态: {status_text} ({publish_status})",
        "=" * 50,
        ""
    ]
    
    # 成功时显示文章信息
    if publish_status == 0:
        article_id = result.get('article_id', '')
        if article_id:
            result_lines.append(f"文章ID: {article_id}")
        
        article_detail = result.get('article_detail', {})
        count = article_detail.get('count', 0)
        if count > 0:
            result_lines.append(f"文章数量: {count}")
            items = article_detail.get('item', [])
            for item in items:
                idx = item.get('idx', 0)
                article_url = item.get('article_url', '')
                result_lines.append(f"  文章 {idx}: {article_url}")
    
    # 显示失败的文章编号（如果有）
    fail_idx = result.get('fail_idx', [])
    if fail_idx:
        result_lines.append(f"失败的文章编号: {', '.join(map(str, fail_idx))}")
    elif publish_status != 0:
        result_lines.append("失败的文章编号: 无")
    
    return '\n'.join(result_lines)


async def _handle_publish_delete(
    article_id: str,
    index: Optional[int],
    api_client
) -> str:
    """处理删除已发布文章"""
    data = {'article_id': article_id}
    if index is not None:
        data['index'] = index
    
    result = await api_client._request('POST', '/cgi-bin/freepublish/delete', data=data)
    
    errcode = result.get('errcode', -1)
    errmsg = result.get('errmsg', '未知错误')
    
    if errcode != 0:
        return f"删除发布失败：{errcode} - {errmsg}\n文章ID: {article_id}"
    
    if index is None or index == 0:
        delete_scope = "全部文章"
    else:
        delete_scope = f"第 {index} 篇"
    
    return (f"发布删除成功！\n"
           f"文章ID: {article_id}\n"
           f"删除范围: {delete_scope}\n\n"
           f"⚠️ 警告：此操作不可逆，请谨慎操作！")


async def _handle_publish_list(
    offset: int,
    count: int,
    no_content: int,
    api_client
) -> str:
    """处理获取已发布消息列表"""
    result = await api_client._request('POST', '/cgi-bin/freepublish/batchget', data={
        'offset': offset,
        'count': count,
        'no_content': no_content
    })
    
    total_count = result.get('total_count', 0)
    item_count = result.get('item_count', 0)
    items = result.get('item', [])
    
    result_lines = [
        "已发布消息列表",
        "=" * 50,
        f"总数: {total_count}",
        f"本次获取: {item_count}",
        f"偏移位置: {offset}",
        "=" * 50,
        ""
    ]
    
    if not items:
        result_lines.append("暂无已发布的消息")
    else:
        for idx, item in enumerate(items, 1):
            result_lines.append(f"【消息 {idx}】")
            result_lines.append(f"文章ID: {item.get('article_id', '无')}")
            result_lines.append(f"更新时间: {_format_timestamp(item.get('update_time', 0))}")
            
            content = item.get('content', {})
            news_items = content.get('news_item', [])
            
            if news_items:
                result_lines.append(f"文章数量: {len(news_items)}")
                for news_idx, news_item in enumerate(news_items, 1):
                    result_lines.append(f"  文章 {news_idx}:")
                    result_lines.extend(_format_news_item(news_item, include_content=(no_content == 0)))
            else:
                result_lines.append("文章内容: 无（可能设置了no_content=1）")
            
            result_lines.append("")
    
    return '\n'.join(result_lines)


async def _handle_publish_getarticle(
    article_id: str,
    api_client
) -> str:
    """处理获取已发布图文信息"""
    result = await api_client.get_published_article(article_id)
    
    errcode = result.get('errcode', -1)
    if errcode != 0:
        errmsg = result.get('errmsg', '未知错误')
        return f"获取已发布图文信息失败：{errcode} - {errmsg}\n文章ID: {article_id}"
    
    news_items = result.get('news_item', [])
    
    if not news_items:
        return f"获取已发布图文信息成功！\n文章ID: {article_id}\n但未找到图文信息"
    
    result_lines = [
        "获取已发布图文信息成功！",
        "=" * 50,
        f"文章ID: {article_id}",
        f"文章数量: {len(news_items)}",
        "=" * 50,
        ""
    ]
    
    for idx, item in enumerate(news_items, 1):
        result_lines.append(f"【文章 {idx}】")
        result_lines.extend(_format_news_item(item, include_content=True, indent=""))
        
        if idx < len(news_items):
            result_lines.append("")
    
    return '\n'.join(result_lines)


async def handle_publish_tool(arguments: Dict[str, Any], api_client) -> str:
    """处理发布工具"""
    action = arguments.get('action')
    
    try:
        if action == 'submit':
            media_id = arguments.get('mediaId')
            if not media_id:
                return "错误：发布草稿时 mediaId 是必需的"
            return await _handle_publish_submit(media_id, api_client)
        
        elif action == 'get':
            publish_id = arguments.get('publishId')
            if not publish_id:
                return "错误：获取发布状态时 publishId 是必需的"
            return await _handle_publish_get(publish_id, api_client)
        
        elif action == 'delete':
            article_id = arguments.get('articleId')
            if not article_id:
                return "错误：删除发布时 articleId 是必需的（成功发布时返回的 article_id）"
            index = arguments.get('index')
            return await _handle_publish_delete(article_id, index, api_client)
        
        elif action == 'list':
            offset = arguments.get('offset', 0)
            if offset < 0:
                return "错误：offset 参数必须大于等于 0"
            
            count = arguments.get('count', 20)
            if count < LIST_COUNT_MIN or count > LIST_COUNT_MAX:
                return f"错误：count 参数必须在 {LIST_COUNT_MIN} 到 {LIST_COUNT_MAX} 之间"
            
            no_content = arguments.get('noContent', False)
            # 将布尔值转换为整数：True -> 1, False -> 0
            no_content_int = 1 if no_content else 0
            
            return await _handle_publish_list(offset, count, no_content_int, api_client)
        
        elif action == 'getarticle':
            article_id = arguments.get('articleId')
            if not article_id:
                return "错误：获取已发布图文信息时 articleId 是必需的"
            return await _handle_publish_getarticle(article_id, api_client)
        
        else:
            return f"未知操作: {action}"
    
    except Exception as e:
        return _handle_error(e, '发布操作')
