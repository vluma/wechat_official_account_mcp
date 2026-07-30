"""
微信公众号消息处理模块
处理微信公众号的服务器验证、消息接收和回复等功能
"""
import hashlib
import xml.etree.ElementTree as ET
import logging
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from urllib.parse import parse_qs
import asyncio
import httpx

from shared.storage.storage_manager import StorageManager

logger = logging.getLogger(__name__)


class WechatMessageHandler:
    """微信公众号消息处理器"""
    
    def __init__(self, storage_dir: str = "data/wechat_messages", db_file: str = "data/storage.db"):
        """
        初始化微信消息处理器
        
        Args:
            storage_dir: 消息存储目录
            db_file: 存储管理器数据库文件路径
        """
        self.storage_dir = os.path.join(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        
        # 初始化存储管理器
        self.storage_manager = StorageManager(db_file)
        
        # 从环境变量获取配置
        self.token = os.getenv('WECHAT_TOKEN', '')
        self.save_log = os.getenv('IS_SAVE_LOG', 'false').lower() in ['true', '1', 'yes']
    
    def verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str) -> Dict[str, Any]:
        """
        验证微信服务器配置签名
        
        Args:
            signature: 微信加密签名
            timestamp: 时间戳
            nonce: 随机数
            echostr: 随机字符串
            
        Returns:
            验证结果字典
        """
        try:
            # 参数完整性校验
            if not all([signature, timestamp, nonce, echostr]):
                return {'success': False, 'error': '缺少验证参数'}
            
            # Token配置检查
            if not self.token:
                return {'success': False, 'error': '服务器未配置Token'}
            
            # 按照微信加密规则进行验证
            # 1. 将token、timestamp、nonce三个参数进行字典序排序并拼接
            sorted_params = ''.join(sorted([self.token, timestamp, nonce]))
            # 2. 对拼接后的字符串进行SHA1加密
            signature_compare = hashlib.sha1(sorted_params.encode('utf-8')).hexdigest()
            
            # 3. 加密后的字符串与signature对比，匹配则验证成功
            if signature == signature_compare:
                logger.info(f"微信服务器验证成功: {echostr}")
                return {'success': True, 'echostr': echostr}
            else:
                logger.warning(f"微信服务器验证失败: 期望 {signature_compare}, 实际 {signature}")
                return {'success': False, 'error': '签名验证失败'}
                
        except Exception as e:
            logger.error(f"验证签名时发生错误: {e}")
            return {'success': False, 'error': f'验证失败: {str(e)}'}
    
    def parse_xml_message(self, xml_data: str) -> Optional[Dict[str, Any]]:
        """
        解析XML格式的微信消息
        
        Args:
            xml_data: XML格式的消息数据
            
        Returns:
            解析后的消息字典，如果解析失败返回None
        """
        try:
            root = ET.fromstring(xml_data)
            msg_data = {}
            
            for child in root:
                msg_data[child.tag] = child.text or ''
            
            return msg_data
        except ET.ParseError as e:
            logger.error(f"XML解析失败: {e}")
            return None
    
    def build_reply_message(self, to_user: str, from_user: str, content: str) -> str:
        """
        构建回复消息的XML格式
        
        Args:
            to_user: 接收者OpenID
            from_user: 发送者微信号
            content: 回复内容
            
        Returns:
            XML格式的回复消息
        """
        create_time = int(datetime.now().timestamp())
        
        xml_template = '''<xml>
    <ToUserName><![CDATA[{to_user}]]></ToUserName>
    <FromUserName><![CDATA[{from_user}]]></FromUserName>
    <CreateTime>{create_time}</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[{content}]]></Content>
</xml>'''
        
        return xml_template.format(
            to_user=to_user,
            from_user=from_user,
            create_time=create_time,
            content=content
        )
    
    async def get_ai_reply(self, user_message: str) -> str:
        """
        获取AI回复
        
        Args:
            user_message: 用户消息
            
        Returns:
            AI回复内容
        """
        try:
            # 使用全局AI服务实例
            from shared.utils.ai_service import get_ai_service
            ai_service = get_ai_service()
            
            # 从环境变量获取交互模式，默认为stream
            import os
            interaction_mode = os.getenv('OPENAI_INTERACTION_MODE', 'stream')
            
            # 根据交互模式调用AI服务
            if interaction_mode == 'stream':
                # 流式模式，使用AI服务默认的超时时间（OPENAI_TIMEOUT）
                return await ai_service.simple_chat(user_message, stream=True)
            else:
                # 阻塞模式
                return await ai_service.simple_chat(user_message, stream=False)
                    
        except Exception as e:
            logger.error(f"获取AI回复时发生错误: {e}")
            return f"服务器开小差了: {str(e)}"
    
    async def process_message(self, xml_data: str) -> str:
        """
        处理接收到的微信消息
        
        Args:
            xml_data: XML格式的消息数据
            
        Returns:
            回复消息的XML字符串
        """
        try:
            # 解析消息
            msg_data = self.parse_xml_message(xml_data)
            if not msg_data:
                return "success"
            
            # 提取消息基本信息
            to_user_name = msg_data.get('ToUserName', '')
            from_user_name = msg_data.get('FromUserName', '')
            msg_type = msg_data.get('MsgType', '')
            content = msg_data.get('Content', '')
            
            # 保存消息日志
            if self.save_log:
                await self.save_message(msg_data)
            
            # 根据消息类型处理
            if msg_type == 'text':
                # 文本消息，调用AI回复
                ai_reply = await self.get_ai_reply(content)
                return self.build_reply_message(from_user_name, to_user_name, ai_reply)
                
            elif msg_type == 'image':
                # 图片消息，暂时不支持
                return self.build_reply_message(
                    from_user_name, to_user_name, 
                    "暂时不支持解析图片，晚点再来吧"
                )
                
            elif msg_type == 'video':
                # 视频消息，暂时不支持
                return self.build_reply_message(
                    from_user_name, to_user_name, 
                    "暂时不支持解析视频，晚点再来吧"
                )
            
            else:
                # 其他类型消息
                return "success"
                
        except Exception as e:
            logger.error(f"处理消息时发生错误: {e}")
            return "success"
    
    async def save_message(self, msg_data: Dict[str, Any]):
        """
        保存消息到存储管理器
        
        Args:
            msg_data: 消息数据
        """
        try:
            message_info = {
                'from_user': msg_data.get('FromUserName', ''),
                'to_user': msg_data.get('ToUserName', ''),
                'msg_type': msg_data.get('MsgType', ''),
                'content': msg_data.get('Content', ''),
                'timestamp': msg_data.get('CreateTime', ''),
                'raw_data': json.dumps(msg_data, ensure_ascii=False),
                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 保存到存储管理器
            self.storage_manager.save_wechat_message(message_info)
            
        except Exception as e:
            logger.error(f"保存消息时发生错误: {e}")
    
    def get_message_history(self, limit: int = 50) -> Dict[str, Any]:
        """
        获取消息历史记录
        
        Args:
            limit: 返回记录数量限制
            
        Returns:
            消息历史记录
        """
        try:
            messages = self.storage_manager.list_wechat_messages(limit)
            return {
                'success': True,
                'total': len(messages),
                'messages': messages
            }
        except Exception as e:
            logger.error(f"获取消息历史失败: {e}")
            return {
                'success': False,
                'error': str(e),
                'total': 0,
                'messages': []
            }


# ========== 工具函数 ==========

def handle_wechat_tool(arguments: dict, wechat_handler: WechatMessageHandler) -> str:
    """
    处理微信工具调用
    
    Args:
        arguments: 工具参数
        wechat_handler: 微信消息处理器实例
        
    Returns:
        处理结果文本
    """
    try:
        action = arguments.get('action')
        
        if action == 'verify':
            signature = arguments.get('signature', '')
            timestamp = arguments.get('timestamp', '')
            nonce = arguments.get('nonce', '')
            echostr = arguments.get('echostr', '')
            
            result = wechat_handler.verify_signature(signature, timestamp, nonce, echostr)
            
            if result['success']:
                return f"验证成功！\nechostr: {result['echostr']}"
            else:
                return f"验证失败: {result['error']}"
        
        elif action == 'process_message':
            xml_data = arguments.get('xml_data', '')
            if not xml_data:
                return "错误: 请提供XML消息数据"
            
            # 使用asyncio运行异步处理
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                reply = loop.run_until_complete(wechat_handler.process_message(xml_data))
                return f"消息处理成功\n回复内容:\n{reply}"
            finally:
                loop.close()
        
        elif action == 'get_history':
            limit = arguments.get('limit', 50)
            result = wechat_handler.get_message_history(limit)
            
            if result['success']:
                if result['total'] == 0:
                    return "暂无消息记录"
                
                lines = [f"消息历史记录 (共 {result['total']} 条):\n"]
                for i, msg in enumerate(result['messages'], 1):
                    lines.append(f"{i}. 时间: {msg.get('created_at', 'N/A')}")
                    lines.append(f"   类型: {msg.get('msg_type', 'N/A')}")
                    lines.append(f"   内容: {msg.get('content', 'N/A')}")
                    lines.append("")
                
                return "\n".join(lines)
            else:
                return f"获取历史记录失败: {result['error']}"
        
        elif action == 'test_ai':
            message = arguments.get('message', '你好')
            
            # 使用asyncio运行异步处理
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                ai_reply = loop.run_until_complete(wechat_handler.get_ai_reply(message))
                return f"用户消息: {message}\nAI回复: {ai_reply}"
            finally:
                loop.close()
        
        elif action == 'config_status':
            # 使用全局AI服务实例获取配置状态
            from shared.utils.ai_service import get_ai_service
            ai_service = get_ai_service()
            
            return (f"微信处理器配置状态:\n"
                   f"Token已配置: {'是' if wechat_handler.token else '否'}\n"
                   f"AI API已配置: {'是' if ai_service.is_configured() else '否'}\n"
                   f"AI模型: {ai_service.model}\n"
                   f"保存日志: {'是' if wechat_handler.save_log else '否'}")
        
        else:
            return f"未知操作: {action}"
    
    except Exception as e:
        error_msg = f"处理微信工具失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg