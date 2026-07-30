"""
Web 服务器 - Flask版本
提供静态网页的HTTP访问服务，集成微信消息处理和聊天界面
"""
import logging
import os
import threading
import json
import hashlib
import re
import asyncio
import time
import requests
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from xml.etree import ElementTree as ET

from flask import Flask, request, Response
from shared.utils.ai_service import get_ai_service, set_ai_service

logger = logging.getLogger(__name__)


def my_render_template(template_path: str, variables: Dict[str, Any]) -> str:
    """
    简单的模板渲染引擎
    
    Args:
        template_path: 模板文件路径
        variables: 模板变量字典
        
    Returns:
        渲染后的HTML字符串
    """
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # 处理带默认值的变量替换
        # 正则表达式匹配 {{ variable or 'default' }} 或 {{ variable or "default" }}
        # 注意：使用负断言确保 or 前后不是单词字符或点号，避免匹配到其他单词的一部分（如 formatted 中的 or）
        def replace_default_var(match):
            var_name = match.group(1).strip()
            default_value = match.group(2).strip()
            # 移除默认值的引号
            if (default_value.startswith("'") and default_value.endswith("'") or \
               (default_value.startswith('"') and default_value.endswith('"'))):
                default_value = default_value[1:-1]
            # 处理点表示法，支持嵌套dict和对象属性
            try:
                value = variables
                for part in var_name.split('.'):
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        value = None
                        break
                    if value is None:
                        break
                return str(value) if value is not None else default_value
            except (AttributeError, TypeError):
                return default_value
        
        # 处理普通变量替换（包括点表示法）
        def replace_regular_var(match):
            var_name = match.group(1).strip()
            # 处理点表示法，如 page.filename，支持嵌套dict和对象属性
            try:
                value = variables
                for part in var_name.split('.'):
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        value = None
                        break
                    if value is None:
                        break
                return str(value) if value is not None else ''
            except (AttributeError, TypeError):
                return ''
        
        # 简单的条件判断处理，支持点表示法
        def replace_if(match):
            condition = match.group(1).strip()
            if_content = match.group(2)
            
            # 处理点表示法的条件变量，例如 pagination_html
            try:
                value = variables
                for part in condition.split('.'):
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = getattr(value, part, None)
                    if value is None:
                        break
                
                # 检查值是否为真（非None、非空字符串、非空列表等）
                if value:
                    return if_content
                return ""
            except (AttributeError, TypeError):
                return ""
        
        # 简单的循环处理（for page in pages_info）
        def replace_for_loop(match):
            loop_var = match.group(1)
            list_var = match.group(2)
            loop_content = match.group(3)
            
            # 获取循环数据
            try:
                items = variables
                for part in list_var.split('.'):
                    if isinstance(items, dict):
                        items = items.get(part)
                    else:
                        items = getattr(items, part, None)
                    if items is None:
                        break
                items = items or []
            except (AttributeError, TypeError):
                items = []
            
            result = ""
            for item in items:
                # 为每个item创建上下文
                item_context = variables.copy()
                item_context[loop_var] = item
                
                # 替换item中的变量
                item_html = loop_content
                
                # 先处理item中的带默认值变量
                # 注意：使用负断言确保 or 前后不是单词字符或点号，避免匹配到其他单词的一部分（如 formatted 中的 or）
                def replace_item_default_var(match):
                    var_name = match.group(1).strip()
                    default_value = match.group(2).strip()
                    # 移除默认值的引号
                    if (default_value.startswith("'") and default_value.endswith("'") or \
                       (default_value.startswith('"') and default_value.endswith('"'))):
                        default_value = default_value[1:-1]
                    # 从item_context中获取值
                    try:
                        value = item_context
                        for part in var_name.split('.'):
                            if isinstance(value, dict):
                                value = value.get(part)
                            elif hasattr(value, part):
                                value = getattr(value, part)
                            else:
                                value = None
                                break
                            if value is None:
                                break
                        return str(value) if value is not None else default_value
                    except (AttributeError, TypeError):
                        return default_value
                
                item_html = re.sub(r'\{\{\s*([\w.]+)\s*(?<![\w.])or(?![\w.])\s*([^}]+)\s*\}\}', replace_item_default_var, item_html)
                
                # 然后处理item中的普通变量（包括点表示法）
                def replace_item_var(match):
                    var_name = match.group(1).strip()
                    try:
                        value = item_context
                        for part in var_name.split('.'):
                            if isinstance(value, dict):
                                value = value.get(part)
                            elif hasattr(value, part):
                                value = getattr(value, part)
                            else:
                                value = None
                                break
                            if value is None:
                                break
                        return str(value) if value is not None else ''
                    except (AttributeError, TypeError):
                        return ''
                
                item_html = re.sub(r'\{\{\s*([\w.]+)\s*\}\}', replace_item_var, item_html)
                
                result += item_html
            
            return result
        
        # 渲染顺序：先处理循环，再处理条件判断，最后处理变量替换
        # 1. 先处理循环
        html = re.sub(r'\{\%\s*for\s+(\w+)\s+in\s+([\w.]+)\s*\%\}(.*?)\{\%\s*endfor\s*\%\}', 
                     replace_for_loop, template, flags=re.DOTALL)
        
        # 2. 处理条件判断（支持点表示法）- 必须先于变量替换处理
        def replace_if_with_else(match):
            condition = match.group(1).strip()
            if_content = match.group(2)
            else_content = match.group(3)
            
            try:
                value = variables
                for part in condition.split('.'):
                    if isinstance(value, dict):
                        value = value.get(part)
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        value = None
                        break
                    if value is None:
                        break
                
                if value:
                    return if_content
                return else_content
            except (AttributeError, TypeError):
                return else_content
        
        def replace_if(match):
            condition = match.group(1).strip()
            if_content = match.group(2)
            
            try:
                value = variables
                for part in condition.split('.'):
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = getattr(value, part, None)
                    if value is None:
                        break
                
                if value:
                    return if_content
                return ""
            except (AttributeError, TypeError):
                return ""
        
        html = re.sub(r'\{\%\s*if\s+([\w.]+)\s*\%\}(.*?)\{\%\s*else\s*\%\}(.*?)\{\%\s*endif\s*\%\}', 
                     replace_if_with_else, html, flags=re.DOTALL)
        html = re.sub(r'\{\%\s*if\s+([\w.]+)\s*\%\}(.*?)\{\%\s*endif\s*\%\}', 
                     replace_if, html, flags=re.DOTALL)
        
        # 3. 处理模板级别的变量（非循环内的）- 最后处理
        html = re.sub(r'\{\{\s*([\w.]+)\s*(?<![\w.])or(?![\w.])\s*([^}]+)\s*\}\}', replace_default_var, html)
        html = re.sub(r'\{\{\s*([\w.]+)\s*\}\}', replace_regular_var, html)
        
        return html
        
    except Exception as e:
        logger.error(f"模板渲染失败 {template_path}: {e}")
        return f"<h1>模板渲染失败</h1><p>错误: {e}</p>"


class StaticPageServer:
    """Web 服务器 - Flask版本"""
    
    def __init__(self, pages_dir: str = "data/static_pages", port: int = 3004):
        """
        初始化Flask服务器
        
        Args:
            pages_dir: 静态网页存储目录
            port: 服务端口
        """
        self.pages_dir = pages_dir
        self.port = port
        self.is_running = False
        self.server_thread = None
        
        # 从环境变量读取配置
        self.context_path = os.environ.get('WECHAT_MSG_CONTEXT_PATH', '').strip()
        # 确保contextPath以/开头，不以/结尾
        if self.context_path:
            if not self.context_path.startswith('/'):
                self.context_path = f'/{self.context_path}'
            if self.context_path.endswith('/'):
                self.context_path = self.context_path[:-1]
        
        # 获取监听地址和端口
        self.host = os.getenv('WECHAT_MSG_SERVER_HOST', '0.0.0.0')
        # 使用WECHAT_MSG_SERVER_PORT作为统一端口
        self.port = int(os.getenv('WECHAT_MSG_SERVER_PORT', str(port)))
        
        # 确保页面目录存在
        Path(self.pages_dir).mkdir(parents=True, exist_ok=True)
        
        # 创建Flask应用实例
        self.app = Flask(__name__)
        
        # 微信消息处理相关配置
        # 微信消息AI响应缓存时间（秒）
        self.wechat_msg_ai_cache_time = int(os.getenv('WECHAT_MSG_AI_CACHE_TIME', '60'))
        # 微信消息AI处理超时时间（秒）
        self.wechat_msg_ai_timeout = float(os.getenv('WECHAT_MSG_AI_TIMEOUT', '15'))
        # 微信消息AI响应长度限制
        self.wechat_msg_ai_len_limit = int(os.getenv('WECHAT_MSG_AI_LEN_LIMIT', '600'))
        # 微信消息AI超时提示
        self.wechat_msg_ai_timeout_prompt = os.getenv('WECHAT_MSG_AI_TIMEOUT_PROMPT', '')
        # 微信消息AI缓存大小限制
        self.wechat_msg_ai_cache_size = int(os.getenv('WECHAT_MSG_AI_CACHE_SIZE', '100'))
        
        # 反向代理配置
        # 从环境变量读取代理目标URL
        self.proxy_target_url = os.getenv('WECHAT_MSG_PROXY_TARGET_URL', '').strip()
        
        # 微信消息缓存结构: {msg_id: {"content": "响应内容", "expire_time": "过期时间"}}
        self.wechat_msg_cache = {}
        # 微信消息锁结构: {msg_id: threading.Lock()}
        self.wechat_msg_locks = {}
        # 锁的锁，用于保护wechat_msg_locks的访问
        self.wechat_msg_locks_lock = threading.Lock()
        
        # 注册路由
        self._setup_routes()
    
    def _setup_routes(self):
        """设置Flask路由"""
        # 路由处理函数 - 接受可变参数以处理Flask路由匹配
        def handle_all_requests(**kwargs):
            """处理所有请求的统一入口"""
            # 始终从request.path获取完整请求路径
            full_path = request.path
            
            # 处理contextPath
            if self.context_path:
                if full_path.startswith(self.context_path):
                    # 如果请求包含contextPath，则移除前缀
                    path = full_path[len(self.context_path):]
                    if not path:
                        path = '/'
                else:
                    # 如果请求不包含contextPath，直接使用完整路径
                    # 允许直接访问根路径文件，如 http://host/cdn_verify.txt
                    path = full_path
            else:
                # 没有contextPath时，直接使用完整路径
                path = full_path
            
            # 根据请求方法分发处理
            if request.method == 'GET':
                return self._handle_get_request(path)
            elif request.method == 'POST':
                return self._handle_post_request(path)
            else:
                return "Method not allowed", 405
        
        # 注册路由：同时支持带contextPath和不带contextPath的请求
        # 1. 带contextPath前缀的路由
        if self.context_path:
            self.app.add_url_rule(f'{self.context_path}/', methods=['GET', 'POST'], view_func=handle_all_requests)
            self.app.add_url_rule(f'{self.context_path}/<path:path>', methods=['GET', 'POST'], view_func=handle_all_requests)
        
        # 2. 不带contextPath前缀的路由（支持直接访问根路径文件）
        self.app.add_url_rule('/', methods=['GET', 'POST'], view_func=handle_all_requests)
        self.app.add_url_rule('/<path:path>', methods=['GET', 'POST'], view_func=handle_all_requests)
    
    def _handle_get_request(self, path):
        """处理GET请求"""
        try:
            # 路由处理
            if path == '/':
                # 首页：显示静态存储信息
                return self._generate_index_page()
            elif path == '/static-pages/':
                # 静态网页列表页面
                return self._generate_static_pages_list()
            elif path.startswith('/pages/'):
                # 访问静态网页：/pages/filename.html
                return self._handle_static_page(path)
            elif path == '/chat/':
                # 聊天界面
                return self._handle_chat_interface()
            elif path == '/api/config' or path == '/chat/api/config':
                # 配置API（支持直接访问和chat下访问）
                return self._handle_config_api()
            elif path == '/api/verification-code' or path == '/chat/api/verification-code':
                # 验证码验证API（支持直接访问和chat下访问）
                return self._handle_verification_code_api()
            elif path == '/api/generate-code' or path == '/chat/api/generate-code':
                # 验证码生成API（支持直接访问和chat下访问）
                return self._handle_generate_code_api()
            elif path == '/api/validate-password':
                # 密码验证API
                return self._handle_validate_password()
            elif path == '/wechat/reply':
                # 微信服务器验证
                return self._handle_wechat_verify()
            elif path.startswith('/proxy/'):
                # 反向代理请求
                return self._handle_proxy_request(path)
            elif path != '/':
                # 处理根目录文件访问：http://host/filename.x 或 http://host/contextPath/filename.x
                # 获取文件名（去掉开头的/）
                filename = path[1:]
                if filename:
                    # 检查data/files目录下是否存在该文件
                    # 使用绝对路径确保正确访问
                    files_dir = Path(__file__).parent.parent.parent / "data" / "files"
                    file_path = files_dir / filename
                    if file_path.exists() and file_path.is_file():
                        # 设置内容类型
                        from mimetypes import guess_type
                        content_type, _ = guess_type(filename)
                        if not content_type:
                            content_type = 'application/octet-stream'
                        
                        # 读取文件内容
                        with open(file_path, 'rb') as f:
                            content = f.read()
                        
                        return content, 200, {'Content-Type': content_type}
            
            # 如果没有匹配到任何路由，返回404
            return "Page not found", 404
                
        except Exception as e:
            logger.error(f"处理GET请求失败: {e}")
            return "Internal server error", 500
    
    def _handle_post_request(self, path):
        """处理POST请求"""
        try:
            # 路由处理
            if path == '/api/chat' or path == '/chat/api/send':
                # 聊天API（支持直接访问和chat下访问）
                return self._handle_chat_api()
            elif path == '/api/config' or path == '/chat/api/config':
                # 配置API，由_handle_config_api统一处理GET和POST
                return self._handle_config_api()
            elif path == '/api/verification-code' or path == '/chat/api/verification-code':
                # 验证码验证API（支持直接访问和chat下访问）
                return self._handle_verification_code_api()
            elif path == '/api/generate-code' or path == '/chat/api/generate-code':
                # 验证码生成API（支持直接访问和chat下访问）
                return self._handle_generate_code_api()
            elif path == '/api/validate-password':
                # 密码验证API
                return self._handle_validate_password()
            elif path == '/api/static-page/delete':
                # 静态页面删除API
                return self._handle_delete_static_page()
            elif path == '/wechat/reply':
                # 微信消息接收
                return self._handle_wechat_message()
            else:
                return "Method not allowed", 405
                
        except Exception as e:
            logger.error(f"处理POST请求失败: {e}")
            return "Internal server error", 500
    
    def _handle_static_page(self, request_path):
        """处理静态页面请求"""
        try:
            filename = request_path[7:]  # 去掉 '/pages/' 前缀
            
            # 安全检查：防止路径遍历攻击
            if '..' in filename or filename.startswith('/'):
                return "Forbidden", 403
            
            file_path = Path(self.pages_dir) / filename
            
            if not file_path.exists() or not file_path.is_file():
                return "File not found", 404
            
            # 设置内容类型
            if filename.endswith('.html'):
                # 读取并返回文件内容
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return content, 200, {'Content-Type': 'text/html; charset=utf-8'}
            else:
                return "Only HTML files are supported", 400
                
        except Exception as e:
            logger.error(f"处理静态页面请求失败: {e}")
            return "Internal server error", 500
    
    def _generate_index_page(self):
        """生成索引页面"""
        try:
            # 获取页面列表和统计信息
            stats = {
                'total_files': 0,
                'total_size': 0,
                'earliest_created': None,
                'latest_created': None
            }
            
            pages = []
            # 优先使用static_page_manager获取数据
            if hasattr(self, 'static_page_manager') and self.static_page_manager:
                pages_info = self.static_page_manager.list_pages()
                pages = pages_info.get('pages', [])
                
                # 使用静态页面管理器获取统计信息
                stats_info = self.static_page_manager.get_storage_stats()
                stats['total_files'] = stats_info['total_files']
                stats['total_size'] = stats_info['total_size_bytes']
                stats['earliest_created'] = stats_info['earliest_created']
                stats['latest_created'] = stats_info['latest_created']
            else:
                # 备用方案：读取元数据
                metadata_file = Path(self.pages_dir) / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        pages = list(metadata.values())
                    
                    stats['total_files'] = len(pages)
                    stats['total_size'] = sum(page.get('file_size', 0) for page in pages)
                    
                    if pages:
                        created_times = [page.get('created_at', '') for page in pages if page.get('created_at')]
                        created_times.sort()
                        if created_times:
                            stats['earliest_created'] = created_times[0]
                            stats['latest_created'] = created_times[-1]
            
            # 格式化文件大小
            def format_file_size(size_bytes):
                if size_bytes == 0:
                    return "0 B"
                units = ['B', 'KB', 'MB', 'GB']
                unit_index = 0
                size = float(size_bytes)
                
                while size >= 1024 and unit_index < len(units) - 1:
                    size /= 1024
                    unit_index += 1
                
                return f"{size:.2f} {units[unit_index]}"
            
            # 获取模板路径
            template_path = Path(__file__).parent.parent.parent / "templates" / "index_template.html"
            
            # 准备模板变量
            template_vars = {
                'title': '静态网页服务',
                'subtitle': '生成和管理静态HTML网页的HTTP访问服务',
                'pages_url': f'{self.context_path}/static-pages/',
                'chat_url': f'{self.context_path}/chat',
                'total_files': stats['total_files'],
                'total_size': format_file_size(stats['total_size']),
                'earliest_created': stats['earliest_created'],
                'latest_created': stats['latest_created']
            }
            
            # 使用模板渲染 - 传递字典参数
            template_vars = {
                'context_path': self.context_path,
                'wechat_official_account': os.getenv('WECHAT_OFFICIAL_ACCOUNT_NAME', 'AI析数助手')
            }
            
            html = my_render_template(str(template_path), template_vars)
            
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
            
        except Exception as e:
            logger.error(f"生成索引页面失败: {e}")
            return "<h1>错误</h1><p>无法加载页面列表</p>", 500
    
    def _handle_chat_interface(self):
        """处理聊天界面请求"""
        try:
            # 获取聊天模板路径
            template_path = Path(__file__).parent.parent.parent / "templates" / "chat_template.html"
            
            # 准备模板变量
            template_vars = {
                'context_path': self.context_path,
                'wechat_official_account': os.getenv('WECHAT_OFFICIAL_ACCOUNT_NAME', 'AI析数助手')
            }
            
            # 使用模板渲染 - 传递字典参数
            html = my_render_template(str(template_path), template_vars)
            
            # 返回渲染后的内容
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
            
        except Exception as e:
            logger.error(f"处理聊天界面失败: {e}")
            return "<h1>错误</h1><p>无法加载聊天界面</p>", 500
    
    def _validate_request_password(self):
        """验证请求中的密码是否正确（支持明文和md5+盐两种方式）
        
        Returns:
            bool: 密码是否正确
        """
        try:
            # 从请求头获取密码
            password = request.headers.get('X-Config-Password')
            logger.debug(f"收到密码验证请求，密码头: {password[:20] if password else 'None'}...")
            
            # 如果请求头中没有，尝试从请求体获取
            if not password:
                try:
                    # 尝试读取原始请求体
                    raw_data = request.get_data(as_text=True)
                    
                    # 尝试解析为JSON，捕获异常并返回空字典
                    try:
                        data = request.get_json()
                    except Exception as e:
                        data = {}
                    
                    password = data.get('password')
                except Exception as e:
                    # 尝试从表单数据获取
                    data = request.form
                    password = data.get('password')
            
            # 从环境变量获取配置密码
            openai_config_password = os.getenv('OPENAI_CONFIG_PASSWORD')
            logger.debug(f"环境变量密码配置存在: {openai_config_password is not None}")
            
            # 验证密码
            if not openai_config_password:
                logger.warning("环境变量中未配置密码")
                return False
            
            # 支持两种验证方式：明文和md5+盐
            if password == openai_config_password:
                # 明文验证（向后兼容）
                logger.debug("密码验证成功：明文匹配")
                return True
            elif password and ':' in password:
                # md5+盐验证（格式：encrypted_password:salt）
                import hashlib
                encrypted_password, salt = password.split(':', 1)
                logger.debug(f"尝试md5+盐验证，salt长度: {len(salt)}")
                if len(salt) >= 8:
                    # 使用相同的盐值对环境变量中的密码进行md5加密
                    expected_password = hashlib.md5(f"{openai_config_password}{salt}".encode('utf-8')).hexdigest()
                    logger.debug(f"期望密码: {expected_password}, 收到密码: {encrypted_password}")
                    result = encrypted_password == expected_password
                    logger.debug(f"md5验证结果: {result}")
                    return result
                else:
                    logger.warning(f"salt长度不足8位: {len(salt)}")
            
            logger.debug("密码验证失败")
            return False
        except Exception as e:
            logger.error(f"验证请求密码失败: {e}")
            return False

    def _handle_config_api(self):
        """处理配置API请求，支持GET获取配置和POST保存配置"""
        try:
            if request.method == 'POST':
                # 验证密码
                if not self._validate_request_password():
                    return json.dumps({'success': False, 'message': 'Invalid password'}), 401, {'Content-Type': 'application/json'}
                    
                # 处理配置保存请求
                data = request.get_json()
                if not data:
                    return json.dumps({'error': '无效的请求数据'}), 400, {'Content-Type': 'application/json'}
                
                # 从请求数据中提取配置参数
                api_url = data.get('api_url', '')
                api_key = data.get('api_key', '')
                model = data.get('model', '')
                system_prompt = data.get('system_prompt', '')
                
                # 验证必要参数
                if not all([api_url, api_key, model]):
                    return json.dumps({'error': '缺少必要的配置参数'}), 400, {'Content-Type': 'application/json'}
                
                # 获取AI服务实例并保存配置
                set_ai_service("web", api_url, api_key, model, system_prompt)
                ai_service = get_ai_service()
                success = ai_service.save_config(api_url, api_key, model, system_prompt)
                
                if success:
                    return json.dumps({'success': True, 'message': '配置保存成功'}), 200, {'Content-Type': 'application/json'}
                else:
                    return json.dumps({'error': '配置保存失败'}), 500, {'Content-Type': 'application/json'}
            else:  # GET请求
                # 从环境变量读取交互模式
                interaction_mode = os.getenv('OPENAI_INTERACTION_MODE', 'block').strip().lower()
                # 验证交互模式
                if interaction_mode not in ['stream', 'block']:
                    interaction_mode = 'block'  # 默认使用阻塞模式
                
                # 获取AI服务实例和配置信息
                ai_service = get_ai_service()
                ai_config = ai_service.get_config_info()
                
                # 返回配置信息
                config = {
                    'aiService': 'openai',
                    'model': ai_config.get('model', 'gpt-3.5-turbo'),
                    'interactionMode': interaction_mode
                }
                return json.dumps(config), 200, {'Content-Type': 'application/json'}
            
        except Exception as e:
            logger.error(f"处理配置API失败: {e}")
            return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _handle_verification_code_api(self):
        """处理验证码验证API请求，不需要密码验证"""
        try:
            if request.method == 'POST':
                # 处理验证码验证请求
                data = request.get_json()
                if not data:
                    return json.dumps({'error': '无效的请求数据'}), 400, {'Content-Type': 'application/json'}
                
                # 只支持验证验证码
                action = data.get('action', 'validate')
                if action != 'validate':
                    return json.dumps({'error': '验证码API只支持验证操作'}), 400, {'Content-Type': 'application/json'}
                
                custom_code = data.get('custom_code')
                
                # 导入存储管理器
                from shared.storage.storage_manager import StorageManager
                storage_manager = StorageManager()
                
                # 验证验证码
                return self._validate_verification_code(storage_manager, custom_code)
            else:
                return json.dumps({'error': '验证码验证API只支持POST请求'}), 405, {'Content-Type': 'application/json'}
            
        except Exception as e:
            logger.error(f"处理验证码验证API失败: {e}")
            return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _handle_generate_code_api(self):
        """处理验证码生成API请求，需要密码验证"""
        try:
            if request.method == 'POST':
                # 验证密码（复用现有的密码验证方法）
                if not self._validate_request_password():
                    return json.dumps({'success': False, 'message': 'Invalid password'}), 401, {'Content-Type': 'application/json'}
                    
                # 处理验证码生成请求
                data = request.get_json()
                if not data:
                    return json.dumps({'error': '无效的请求数据'}), 400, {'Content-Type': 'application/json'}
                
                # 只支持生成验证码
                action = data.get('action', 'generate')
                if action != 'generate':
                    return json.dumps({'error': '验证码生成API只支持生成操作'}), 400, {'Content-Type': 'application/json'}
                
                custom_code = data.get('custom_code')
                
                # 导入存储管理器
                from shared.storage.storage_manager import StorageManager
                storage_manager = StorageManager()
                
                # 生成验证码
                return self._generate_verification_code(storage_manager, custom_code)
            else:  # GET请求
                # 生成验证码（GET方式用于简单生成）
                from shared.storage.storage_manager import StorageManager
                storage_manager = StorageManager()
                return self._generate_verification_code(storage_manager, None)
            
        except Exception as e:
            logger.error(f"处理验证码生成API失败: {e}")
            return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _generate_verification_code(self, storage_manager, custom_code: str = None):
        """生成验证码"""
        import uuid
        from datetime import datetime, timedelta
        
        if custom_code:
            # 验证自定义验证码格式
            if len(custom_code) < 8:
                return json.dumps({'error': '验证码长度必须大于等于8位'}), 400, {'Content-Type': 'application/json'}
            
            # 检查是否包含英文字母和数字
            has_letter = any(c.isalpha() for c in custom_code)
            has_digit = any(c.isdigit() for c in custom_code)
            
            if not (has_letter and has_digit):
                return json.dumps({'error': '验证码必须包含英文字母和数字'}), 400, {'Content-Type': 'application/json'}
            
            # 检查是否已存在
            if storage_manager.get_verification_code(custom_code):
                return json.dumps({'error': '该验证码已存在，请选择其他验证码'}), 400, {'Content-Type': 'application/json'}
            
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
            'source': 'webserver_generated'
        }
        
        storage_manager.save_verification_code(code_info)
        
        return json.dumps({
            'success': True, 
            'code': verification_code,
            'expires_at': expires_at.isoformat(),
            'valid_days': valid_days,
            'message': f'验证码生成成功：{verification_code}'
        }), 200, {'Content-Type': 'application/json'}
    
    def _validate_verification_code(self, storage_manager, code: str):
        """验证验证码"""
        if not code:
            return json.dumps({'error': '请提供验证码'}), 400, {'Content-Type': 'application/json'}
        
        # 获取验证码信息
        code_info = storage_manager.get_verification_code(code)
        
        if not code_info:
            return json.dumps({'valid': False, 'message': '验证码不存在'}), 200, {'Content-Type': 'application/json'}
        
        # 检查是否已过期
        from datetime import datetime
        expires_at = datetime.fromisoformat(code_info['expires_at'])
        if datetime.now() > expires_at:
            return json.dumps({'valid': False, 'message': '验证码已过期'}), 200, {'Content-Type': 'application/json'}
        
        # 检查是否已使用
        if code_info.get('used', False):
            return json.dumps({'valid': False, 'message': '验证码已使用'}), 200, {'Content-Type': 'application/json'}
        
        return json.dumps({'valid': True, 'message': '验证码有效'}), 200, {'Content-Type': 'application/json'}
    
    def _use_verification_code(self, storage_manager, code: str):
        """使用验证码（标记为已使用）"""
        if not code:
            return json.dumps({'error': '请提供验证码'}), 400, {'Content-Type': 'application/json'}
        
        # 先验证验证码是否有效
        code_info = storage_manager.get_verification_code(code)
        
        if not code_info:
            return json.dumps({'error': '验证码不存在'}), 400, {'Content-Type': 'application/json'}
        
        # 检查是否已过期
        from datetime import datetime
        expires_at = datetime.fromisoformat(code_info['expires_at'])
        if datetime.now() > expires_at:
            return json.dumps({'error': '验证码已过期'}), 400, {'Content-Type': 'application/json'}
        
        # 检查是否已使用
        if code_info.get('used', False):
            return json.dumps({'error': '验证码已使用'}), 400, {'Content-Type': 'application/json'}
        
        # 标记为已使用
        success = storage_manager.mark_verification_code_used(code)
        
        if success:
            return json.dumps({'success': True, 'message': '验证码使用成功'}), 200, {'Content-Type': 'application/json'}
        else:
            return json.dumps({'error': '验证码使用失败'}), 500, {'Content-Type': 'application/json'}
    
    def _cleanup_expired_codes(self, storage_manager):
        """清理过期验证码"""
        cleaned_count = storage_manager.cleanup_expired_verification_codes()
        return json.dumps({
            'success': True, 
            'cleaned_count': cleaned_count,
            'message': f'清理完成，删除了 {cleaned_count} 个过期验证码'
        }), 200, {'Content-Type': 'application/json'}
    
    def _handle_proxy_request(self, path):
        """处理反向代理请求"""
        try:
            # 检查代理目标URL是否配置
            if not self.proxy_target_url:
                logger.error("代理目标URL未配置，请设置WECHAT_MSG_PROXY_TARGET_URL环境变量")
                return "Proxy target URL not configured", 500
            
            # 从请求路径中提取代理的路径部分（去掉/proxy/前缀）
            proxy_path = path[7:]  # 去掉/proxy/前缀
            
            # 构建完整的目标URL
            if proxy_path:
                if self.proxy_target_url.endswith('/'):
                    target_url = f"{self.proxy_target_url}{proxy_path}"
                else:
                    target_url = f"{self.proxy_target_url}/{proxy_path}"
            else:
                target_url = self.proxy_target_url
            
            # 转发请求到目标URL
            logger.info(f"代理请求: {path} -> {target_url}")
            
            # 转发请求头
            headers = dict(request.headers)
            # 移除Host头，让requests自动设置
            headers.pop('Host', None)
            # 移除Accept-Encoding头，让requests不使用压缩
            headers.pop('Accept-Encoding', None)
            
            # 发送GET请求到目标URL，禁止压缩以避免解码问题
            response = requests.get(
                target_url,
                headers=headers,
                params=request.args,
                stream=True,  # 使用流式响应，避免加载大文件到内存
                verify=False,  # 忽略SSL验证（根据需要调整）
                timeout=60  # 设置超时
            )
            
            # 构建响应头
            response_headers = dict(response.headers)
            
            # 移除所有可能导致解码问题的头
            problematic_headers = ['Content-Encoding', 'Transfer-Encoding', 'Content-Length']
            for header in problematic_headers:
                if header in response_headers:
                    logger.debug(f"移除响应头: {header} = {response_headers[header]}")
                    response_headers.pop(header)
            
            # 确保Content-Type头存在，避免浏览器猜测
            if 'Content-Type' not in response_headers:
                response_headers['Content-Type'] = 'text/html; charset=utf-8'
                logger.debug("未检测到Content-Type头，设置默认值为text/html; charset=utf-8")
            
            # 返回响应 - 使用iter_content确保内容正确处理
            logger.info(f"代理响应: {target_url} -> 状态码: {response.status_code}")
            return Response(
                response.iter_content(chunk_size=1024, decode_unicode=False),  # 不自动解码，保持原始字节
                status=response.status_code,
                headers=response_headers
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"代理请求失败: {e}")
            return f"Proxy request failed: {e}", 502
        except Exception as e:
            logger.error(f"处理代理请求时发生错误: {e}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return f"Proxy error: {e}", 500
    
    def _verify_wechat_signature(self):
        """验证微信签名"""
        try:
            # 获取参数（GET请求从args获取，POST请求从args获取）
            signature = request.args.get('signature', '')
            timestamp = request.args.get('timestamp', '')
            nonce = request.args.get('nonce', '')
            
            # 从环境变量获取token
            token = os.getenv('WECHAT_TOKEN')
            if not token:
                logger.error("WECHAT_TOKEN环境变量未配置")
                return False
            
            # 验证签名
            temp_list = [token, timestamp, nonce]
            temp_list.sort()
            temp_str = ''.join(temp_list)
            sha1_hash = hashlib.sha1(temp_str.encode('utf-8')).hexdigest()
            
            return sha1_hash == signature
            
        except Exception as e:
            logger.error(f"验证微信签名失败: {e}")
            return False
    
    def _handle_wechat_verify(self):
        """处理微信服务器验证"""
        try:
            # 验证签名
            if self._verify_wechat_signature():
                # 获取echostr并返回
                echostr = request.args.get('echostr', '')
                return echostr, 200, {'Content-Type': 'text/plain; charset=utf-8'}
            else:
                return "Signature verification failed", 403
                
        except Exception as e:
            logger.error(f"处理微信验证失败: {e}")
            return "Internal server error", 500
    
    def _handle_chat_api(self):
        """处理聊天API请求"""
        import time
        start_time = time.time()
        
        try:
            # 获取请求数据 - 这是第一个瓶颈点
            data = request.get_json()
            if not data:
                return json.dumps({'error': '无效的请求数据'}), 400, {'Content-Type': 'application/json'}
            
            # 获取用户消息
            user_message = data.get('message')
            if not user_message:
                return json.dumps({'error': '请提供消息内容'}), 400, {'Content-Type': 'application/json'}
            
            # 获取对话历史（可选）
            conversation_history = data.get('history', [])
            
            # 从环境变量读取交互模式
            interaction_mode = os.getenv('OPENAI_INTERACTION_MODE', 'block').strip().lower()
            # 验证交互模式
            if interaction_mode not in ['stream', 'block']:
                interaction_mode = 'block'  # 默认使用阻塞模式
            
            # 获取AI服务实例 - 全局单例，避免重复创建
            ai_service = get_ai_service()
                        
            if interaction_mode == 'stream':
                # 流式响应处理 - 优化事件循环管理
                def generate():
                    # 确保每个线程都有自己的事件循环
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                                        
                    # 直接调用ai_service.stream_chat，减少中间层嵌套
                    async def stream_wrapper():
                        try:
                            async for chunk in ai_service.stream_chat(
                                user_message=user_message,
                                conversation_history=conversation_history
                            ):
                                yield f"data: {json.dumps({'success': True, 'message': chunk, 'interaction_mode': 'stream'})}\n\n"
                        except Exception as e:
                            logger.error(f"流式响应异常: {e}")
                            yield f"data: {json.dumps({'error': str(e), 'success': False})}\n\n"
                    
                    # 运行异步生成器
                    async_gen = stream_wrapper()
                    
                    while True:
                        try:
                            chunk = loop.run_until_complete(async_gen.__anext__())
                            yield chunk
                        except StopAsyncIteration:
                            break
                        except Exception as e:
                            logger.error(f"流式响应迭代异常: {e}")
                            break
                
                # 返回SSE响应
                return Response(generate(), mimetype='text/event-stream')
            else:
                # 阻塞模式处理 - 确保每个线程都有自己的事件循环
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                try:
                    # 调用AI服务获取回复
                    ai_reply = loop.run_until_complete(
                        ai_service.simple_chat(
                            user_message=user_message,
                            conversation_history=conversation_history,
                            stream=False  # 阻塞模式
                        )
                    )
                except Exception as e:
                    logger.error(f"阻塞模式调用异常: {e}")
                    return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
                
                # 返回AI回复
                return json.dumps({
                    'success': True,
                    'message': ai_reply,
                    'interaction_mode': interaction_mode
                }), 200, {'Content-Type': 'application/json'}
            
        except Exception as e:
            logger.error(f"处理聊天API失败: {e}")
            return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _handle_validate_password(self):
        """处理密码验证请求"""
        try:
            # 直接调用通用密码验证方法
            if self._validate_request_password():
                return json.dumps({'success': True, 'message': 'Password validated'}), 200, {'Content-Type': 'application/json'}
            else:
                return json.dumps({'success': False, 'message': 'Invalid password'}), 401, {'Content-Type': 'application/json'}
        except Exception as e:
            logger.error(f"处理密码验证请求失败: {e}")
            return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _handle_delete_static_page(self):
        """处理静态页面删除请求"""
        try:
            # 验证密码
            if not self._validate_request_password():
                return json.dumps({'success': False, 'message': 'Invalid password'}), 401, {'Content-Type': 'application/json'}
            
            # 获取请求参数
            filename = request.args.get('filename')
            
            if not filename:
                return json.dumps({'success': False, 'error': '请提供文件名'}), 400, {'Content-Type': 'application/json'}
            
            # 检查是否有静态页面管理器
            if not hasattr(self, 'static_page_manager') or not self.static_page_manager:
                return json.dumps({'success': False, 'error': '静态页面管理器未初始化'}), 500, {'Content-Type': 'application/json'}
            
            # 调用静态页面管理器删除页面
            success = self.static_page_manager.delete_page(filename)
            
            if success:
                return json.dumps({'success': True, 'message': '文件删除成功'}), 200, {'Content-Type': 'application/json'}
            else:
                return json.dumps({'success': False, 'error': '文件不存在或删除失败'}), 404, {'Content-Type': 'application/json'}
            
        except Exception as e:
            logger.error(f"处理静态页面删除请求失败: {e}")
            return json.dumps({'success': False, 'error': str(e)}), 500, {'Content-Type': 'application/json'}
    
    def _clean_expired_cache(self):
        """清理过期的缓存项"""
        current_time = time.time()
        expired_keys = [msg_id for msg_id, cache_item in self.wechat_msg_cache.items() 
                      if cache_item['expire_time'] < current_time]
        for msg_id in expired_keys:
            del self.wechat_msg_cache[msg_id]
    
    def _get_cache_item(self, msg_id):
        """获取缓存项，如果不存在或已过期返回None"""
        self._clean_expired_cache()  # 先清理过期缓存
        cache_item = self.wechat_msg_cache.get(msg_id)
        if cache_item and cache_item['expire_time'] > time.time():
            return cache_item['content']
        return None
    
    def _set_cache_item(self, msg_id, content):
        """设置缓存项"""
        # 先清理过期缓存
        self._clean_expired_cache()
        
        # 如果缓存项已存在，先删除它（这样会将其移到字典末尾，相当于更新访问时间）
        if msg_id in self.wechat_msg_cache:
            del self.wechat_msg_cache[msg_id]
        
        # 检查缓存大小是否超过限制
        if len(self.wechat_msg_cache) >= self.wechat_msg_ai_cache_size:
            # 删除最早添加的缓存项（字典保持插入顺序）
            oldest_msg_id = next(iter(self.wechat_msg_cache))
            del self.wechat_msg_cache[oldest_msg_id]
        
        # 添加新的缓存项
        expire_time = time.time() + self.wechat_msg_ai_cache_time
        self.wechat_msg_cache[msg_id] = {
            "content": content,
            "expire_time": expire_time
        }
    
    def _get_or_create_lock(self, msg_id):
        """获取或创建消息锁"""
        with self.wechat_msg_locks_lock:
            if msg_id not in self.wechat_msg_locks:
                self.wechat_msg_locks[msg_id] = threading.Lock()
            return self.wechat_msg_locks[msg_id]
    
    def _build_wechat_response_xml(self, from_user: str, to_user: str, content: str) -> bytes:
        """
        构建微信文本消息响应的XML格式
        
        Args:
            from_user: 消息来源用户（微信用户的OpenID）
            to_user: 消息目标用户（公众号的原始ID）
            content: 回复内容
            
        Returns:
            格式化的XML响应字节数组（UTF-8编码）
        """
        xml_str = f"""<?xml version="1.0" encoding="UTF-8"?>
                    <xml>
                        <ToUserName><![CDATA[{from_user}]]></ToUserName>
                        <FromUserName><![CDATA[{to_user}]]></FromUserName>
                        <CreateTime>{int(time.time())}</CreateTime>
                        <MsgType><![CDATA[text]]></MsgType>
                        <Content><![CDATA[{content}]]></Content>
                    </xml>"""
        return xml_str.encode('utf-8')
    
    def _handle_wechat_message(self):
        """处理微信消息，调用AI服务自动回复"""
        try:
            # 1. 验证微信签名
            if not self._verify_wechat_signature():
                return "Signature verification failed", 403
            
            # 2. 解析微信发来的XML消息
            xml_data = request.data.decode('utf-8')
            
            # 解析XML
            root = ET.fromstring(xml_data)
            
            # 提取消息类型
            msg_type = root.find('MsgType').text if root.find('MsgType') is not None else ''
            
            # 3. 只处理文本消息
            if msg_type == 'text':
                # 提取消息内容和其他必要信息
                to_user = root.find('ToUserName').text if root.find('ToUserName') is not None else ''
                from_user = root.find('FromUserName').text if root.find('FromUserName') is not None else ''
                create_time = root.find('CreateTime').text if root.find('CreateTime') is not None else ''
                content = root.find('Content').text if root.find('Content') is not None else ''
                msg_id = root.find('MsgId').text if root.find('MsgId') is not None else ''
                
                logger.info(f"收到微信消息: 来自{from_user}, 内容: {content}, MsgId: {msg_id}")
                
                # 4. 检查缓存
                cached_response = self._get_cache_item(msg_id)
                if cached_response:
                    logger.info(f"使用缓存的微信消息响应: MsgId={msg_id}")
                    # 5. 生成微信响应XML
                    response_xml = self._build_wechat_response_xml(from_user, to_user, cached_response)
                    return response_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}
                
                # 5. 获取或创建消息锁
                msg_lock = self._get_or_create_lock(msg_id)
                
                # 6. 尝试获取锁，处理超时情况
                if not msg_lock.acquire(timeout=self.wechat_msg_ai_timeout):
                    logger.warning(f"获取微信消息锁超时: MsgId={msg_id}")
                    # 锁超时，返回默认回复
                    default_response = "抱歉，当前请求量较大，请稍后再试"
                    # 缓存默认回复
                    self._set_cache_item(msg_id, default_response)
                    response_xml = self._build_wechat_response_xml(from_user, to_user, default_response)
                    return response_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}
                
                try:
                    # 再次检查缓存，防止在获取锁的过程中其他线程已经处理了该消息
                    cached_response = self._get_cache_item(msg_id)
                    if cached_response:
                        logger.info(f"使用缓存的微信消息响应: MsgId={msg_id}")
                        response_xml = self._build_wechat_response_xml(from_user, to_user, cached_response)
                        return response_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}
                    
                    # 7. 调用AI服务获取回复（使用公众号专用配置）
                    ai_service = get_ai_service(service_type="wechat")
                    
                    # 确保每个线程都有自己的事件循环
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    # 从环境变量获取交互模式，优先使用微信专用配置，默认使用block模式
                    interaction_mode = os.getenv('OPENAI_WECHAT_INTERACTION_MODE', 
                                               os.getenv('OPENAI_INTERACTION_MODE', 'block')).strip().lower()
                    # 验证交互模式
                    if interaction_mode not in ['stream', 'block']:
                        interaction_mode = 'block'  # 默认使用阻塞模式
                    
                    # 根据交互模式调用不同的AI服务方法
                    if interaction_mode == 'stream':
                        # stream模式：使用stream_chat方法
                        def stream_wrapper():
                            async def collect_stream():
                                collected = []
                                try:
                                    # 使用asyncio.wait_for设置超时
                                    async def collect_with_timeout():
                                        async for chunk in ai_service.stream_chat(
                                            user_message=content,
                                            conversation_history=[]  # 微信公众号暂时不支持上下文
                                        ):
                                            collected.append(chunk)
                                            # 检查是否超过长度限制
                                            if len(''.join(collected)) >= self.wechat_msg_ai_len_limit:
                                                collected.append("..." + self.wechat_msg_ai_timeout_prompt)
                                                break
                                    
                                    await asyncio.wait_for(collect_with_timeout(), timeout=self.wechat_msg_ai_timeout)
                                except asyncio.TimeoutError:
                                    logger.warning(f"微信消息AI响应超时: MsgId={msg_id}")
                                    # 添加超时提示
                                    if len(''.join(collected)) < self.wechat_msg_ai_len_limit:
                                        collected.append(self.wechat_msg_ai_timeout_prompt)
                                except Exception as e:
                                    logger.error(f"微信消息AI响应异常: {str(e)}")
                                    collected.append(f"\n\n[响应异常: {str(e)}]")
                                return ''.join(collected)
                            return collect_stream()
                        
                        ai_reply = loop.run_until_complete(stream_wrapper())
                    else:
                        # block模式：使用simple_chat方法
                        try:
                            # 使用asyncio.wait_for设置超时
                            ai_reply = loop.run_until_complete(asyncio.wait_for(
                                ai_service.simple_chat(
                                    user_message=content,
                                    conversation_history=[]  # 微信公众号暂时不支持上下文
                                ),
                                timeout=self.wechat_msg_ai_timeout
                            ))
                        except asyncio.TimeoutError:
                            logger.warning(f"微信消息AI响应超时: MsgId={msg_id}")
                            ai_reply = "抱歉，当前AI服务响应超时，请稍后再试"
                        except Exception as e:
                            logger.error(f"微信消息AI响应异常: {e}")
                            ai_reply = f"抱歉，当前AI服务响应异常: {str(e)}"
                    
                    # 8. 处理响应长度限制
                    if len(ai_reply) > self.wechat_msg_ai_len_limit:
                        ai_reply = ai_reply[:self.wechat_msg_ai_len_limit] + "..." + self.wechat_msg_ai_timeout_prompt
                    
                    # 9. 缓存响应
                    self._set_cache_item(msg_id, ai_reply)
                    
                    # 10. 生成微信响应XML
                    response_xml = self._build_wechat_response_xml(from_user, to_user, ai_reply)
                    
                    return response_xml, 200, {'Content-Type': 'application/xml; charset=utf-8'}
                finally:
                    # 释放锁
                    msg_lock.release()
            else:
                # 非文本消息，返回空响应
                return "success", 200, {'Content-Type': 'text/plain; charset=utf-8'}
            
        except Exception as e:
            logger.error(f"处理微信消息失败: {e}")
            # 微信服务器要求即使出错也返回success，否则会重试
            return "success", 200, {'Content-Type': 'text/plain; charset=utf-8'}
    
    def start(self):
        """启动Flask服务器"""
        try:
            if self.is_running:
                logger.warning("服务器已经在运行中")
                return False
            
            # 在单独的线程中启动服务器
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            logger.info(f"Web 服务器启动成功")
            logger.info(f"服务地址: http://{self.host}:{self.port}{self.context_path}/")
            logger.info(f"静态网页目录: {self.pages_dir}")
            logger.info(f"页面访问格式: http://{self.host}:{self.port}{self.context_path}/pages/文件名.html")
            
            self.is_running = True
            return True
            
        except Exception as e:
            logger.error(f"启动Web服务器失败: {e}")
            self.is_running = False
            return False
    
    def _run_server(self):
        """在独立线程中运行服务器"""
        try:
            logger.info(f"Web服务器线程启动，监听地址 {self.host}，端口 {self.port}")
            
            # 使用pywsgi WSGI服务器运行Flask应用
            try:
                from gevent.pywsgi import WSGIServer
                # 创建WSGI服务器实例
                http_server = WSGIServer((self.host, self.port), self.app)
                # 启动服务器
                http_server.serve_forever()
            except ImportError:
                # 如果pywsgi不可用，回退到Flask开发服务器
                logger.warning("gevent.pywsgi未安装，回退到Flask开发服务器")
                # 禁用Werkzeug的开发服务器警告
                import logging
                werkzeug_logger = logging.getLogger('werkzeug')
                werkzeug_logger.setLevel(logging.ERROR)
                # 设置模块日志级别为DEBUG，以便输出调试信息
                logger.setLevel(logging.DEBUG)
                # 启动Flask服务器
                self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Web服务器运行异常: {e}")
        finally:
            self.is_running = False
    
    def stop(self):
        """停止Web服务器"""
        try:
            if not self.is_running:
                logger.warning("服务器未在运行中")
                return False
            
            # Flask开发服务器无法优雅停止，这里只能设置状态为停止
            self.is_running = False
            logger.info("Web 服务器已停止")
            return True
        except Exception as e:
            logger.error(f"停止Web服务器失败: {e}")
            return False
    
    def get_status(self) -> dict:
        """获取服务器状态"""
        return {
            "is_running": self.is_running,
            "port": self.port,
            "pages_dir": self.pages_dir,
            "server_url": f"http://{self.host}:{self.port}{self.context_path}" if self.is_running else None
        }
    
    def get_page_url(self, filename: str) -> Optional[str]:
        """
        获取页面访问URL
        
        Args:
            filename: 文件名
            
        Returns:
            完整的访问URL，如果服务器未运行则返回None
        """
        if not self.is_running:
            return None
        
        # 确保文件名以.html结尾
        if not filename.endswith('.html'):
            filename += '.html'
        
        return f"http://{self.host}:{self.port}{self.context_path}/pages/{filename}"


class IntegratedStaticPageServer(StaticPageServer):
    """集成Web服务器，支持微信消息处理和聊天界面"""
    
    def __init__(self, pages_dir: str = "data/static_pages", port: int = 3004, static_page_manager=None):
        """
        初始化集成服务器
        
        Args:
            pages_dir: 静态网页存储目录
            port: 服务端口
            static_page_manager: 静态页面管理器实例
        """
        super().__init__(pages_dir=pages_dir, port=port)
        self.static_page_manager = static_page_manager
    
    def _generate_static_pages_list(self):
        """生成静态网页列表页面，包含页面头、分页显示和美化列表"""
        try:
            from pathlib import Path
            
            # 默认分页参数
            page_num = 1
            per_page = 10
            
            # 从请求中获取page参数
            page_param = request.args.get('page')
            if page_param:
                try:
                    page_num = int(page_param)
                    # 确保page_num不小于1
                    page_num = max(1, page_num)
                except (ValueError, TypeError):
                    # 如果page参数不是有效数字，使用默认值
                    page_num = 1
            
            # 获取页面列表
            pages = []
            if self.static_page_manager:
                pages_info = self.static_page_manager.list_pages()
                pages = pages_info.get('pages', [])
            
            # 按创建时间倒序排序，确保created_at始终为字符串，处理None值
            pages.sort(key=lambda x: str(x.get('created_at', '')), reverse=True)
            
            # 计算总页数
            total_pages = (len(pages) + per_page - 1) // per_page
            
            # 确保page_num不超过总页数
            page_num = min(page_num, total_pages)
            
            # 获取当前页的数据
            start = (page_num - 1) * per_page
            end = start + per_page
            current_pages = pages[start:end]
            
            # 格式化文件大小的辅助函数
            def format_file_size(size_bytes):
                if size_bytes == 0:
                    return "0 B"
                units = ['B', 'KB', 'MB', 'GB']
                unit_index = 0
                size = float(size_bytes)
                
                while size >= 1024 and unit_index < len(units) - 1:
                    size /= 1024
                    unit_index += 1
                
                return f"{size:.2f} {units[unit_index]}"
            
            # 计算总文件大小 - 使用 current_size 优先，如果为0则使用 file_size，确保数值类型
            total_file_size = 0
            for page in pages:
                file_size_val = page.get('current_size', page.get('file_size', 0))
                # 确保file_size_val是数字
                if isinstance(file_size_val, (int, float)):
                    total_file_size += file_size_val
                else:
                    try:
                        # 尝试转换为数字
                        total_file_size += float(file_size_val)
                    except (ValueError, TypeError):
                        # 无法转换，跳过此文件的大小
                        pass
            total_size_formatted = format_file_size(total_file_size)
            
            # 格式化每个页面的文件大小 - 使用 current_size 优先，如果为0则使用 file_size
            for page_item in current_pages:
                file_size = page_item.get('current_size', page_item.get('file_size', 0))
                # 确保file_size是数字
                if isinstance(file_size, (int, float)):
                    pass  # 已经是数字，直接使用
                else:
                    try:
                        # 尝试转换为数字
                        file_size = float(file_size)
                    except (ValueError, TypeError):
                        # 无法转换，使用0
                        file_size = 0
                page_item['file_size_formatted'] = format_file_size(file_size)
            
            # 生成分页HTML
            pagination_html = ""
            if total_pages > 1:
                pagination_html = "<div class='pagination'>"
                
                # 上一页
                if page_num > 1:
                    pagination_html += f"<a href='{self.context_path}/static-pages/?page={page_num-1}' class='page-btn prev'>上一页</a>"
                else:
                    pagination_html += "<span class='page-btn prev disabled'>上一页</span>"
                
                # 页码按钮 - 只显示前后3页（共7页）
                max_visible = 7  # 前后3页 + 当前页 = 7页
                start_page = max(1, page_num - 3)
                end_page = min(total_pages, page_num + 3)
                
                # 如果起始页大于1，显示第一页和省略号
                if start_page > 1:
                    pagination_html += f"<a href='{self.context_path}/static-pages/?page=1' class='page-btn'>1</a>"
                    if start_page > 2:
                        pagination_html += "<span class='page-btn ellipsis'>...</span>"
                
                # 显示当前页前后5页
                for i in range(start_page, end_page + 1):
                    if i == page_num:
                        pagination_html += f"<span class='page-btn current'>{i}</span>"
                    else:
                        pagination_html += f"<a href='{self.context_path}/static-pages/?page={i}' class='page-btn'>{i}</a>"
                
                # 如果结束页小于总页数，显示省略号和最后一页
                if end_page < total_pages:
                    if end_page < total_pages - 1:
                        pagination_html += "<span class='page-btn ellipsis'>...</span>"
                    pagination_html += f"<a href='{self.context_path}/static-pages/?page={total_pages}' class='page-btn'>{total_pages}</a>"
                
                # 下一页
                if page_num < total_pages:
                    pagination_html += f"<a href='{self.context_path}/static-pages/?page={page_num+1}' class='page-btn next'>下一页</a>"
                else:
                    pagination_html += "<span class='page-btn next disabled'>下一页</span>"
                
                # 跳转输入框
                pagination_html += f"""
                <div class='page-jump'>
                    <input type='number' id='jumpPage' min='1' max='{total_pages}' placeholder='页码' class='jump-input' />
                    <button onclick="jumpToPage({total_pages})" class='jump-btn'>跳转</button>
                </div>
                <script>
                    function jumpToPage(totalPages) {{
                        var pageNum = document.getElementById('jumpPage').value;
                        pageNum = parseInt(pageNum);
                        if (pageNum >= 1 && pageNum <= totalPages) {{
                            window.location.href = '{self.context_path}/static-pages/?page=' + pageNum;
                        }} else {{
                            alert('请输入有效的页码 (1-' + totalPages + ')');
                        }}
                    }}
                </script>
                """
                
                pagination_html += "</div>"
            
            # 获取模板路径
            template_path = Path(__file__).parent.parent.parent / "templates" / "static_pages_template.html"
            
            # 准备模板变量，确保所有变量都有值
            template_vars = {
                'context_path': self.context_path,
                'total_files': len(pages),
                'total_size': total_size_formatted,
                'pages_info': current_pages,
                'pagination_html': pagination_html
            }
            logger.debug(f"静态网页列表模板变量: {template_vars}")
            
            # 使用模板渲染
            html = my_render_template(str(template_path), template_vars)
            
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
            
        except Exception as e:
            logger.error(f"生成静态网页列表页面失败: {e}")
            return "<h1>错误</h1><p>无法加载静态网页列表</p>", 500
            
    def _generate_index_page(self):
        """生成索引页面 - 集成版本"""
        try:
            # 使用静态页面管理器获取存储统计信息
            stats = {
                'total_files': 0,
                'total_size': '0 B',
                'earliest_created': None,
                'latest_created': None
            }
            
            if self.static_page_manager:
                # 尝试使用静态页面管理器的统计信息方法
                try:
                    stats = self.static_page_manager.get_storage_stats()
                except AttributeError:
                    # 回退方案：如果没有get_storage_stats方法，手动计算
                    pages_info = self.static_page_manager.list_pages()
                    pages = pages_info.get('pages', [])
                    stats = {
                        'total_files': len(pages),
                        'total_size': sum(page.get('current_size', 0) for page in pages),
                        'earliest_created': None,
                        'latest_created': None
                    }
                    
                    if pages:
                        created_times = [page.get('created_at', '') for page in pages if page.get('created_at')]
                        created_times.sort()
                        if created_times:
                            stats['earliest_created'] = created_times[0]
                            stats['latest_created'] = created_times[-1]
                        
                    # 格式化文件大小
                    def format_file_size(size_bytes):
                        if size_bytes == 0:
                            return "0 B"
                        units = ['B', 'KB', 'MB', 'GB']
                        unit_index = 0
                        size = float(size_bytes)
                        
                        while size >= 1024 and unit_index < len(units) - 1:
                            size /= 1024
                            unit_index += 1
                        
                        return f"{size:.2f} {units[unit_index]}"
                    
                    stats['total_size'] = format_file_size(stats['total_size'])
            
            # 获取模板路径
            template_path = Path(__file__).parent.parent.parent / "templates" / "index_template.html"
            
            # 准备模板变量，处理默认值
            template_vars = {
                'title': '静态网页服务',
                'subtitle': '生成和管理静态HTML网页的HTTP访问服务',
                'pages_url': f'{self.context_path}/static-pages/',
                'chat_url': f'{self.context_path}/chat/',
                'total_files': stats['total_files'] if stats['total_files'] is not None else '无',
                'total_size': stats['total_size'] if stats['total_size'] is not None else '无',
                'earliest_created': stats['earliest_created'] if stats['earliest_created'] is not None else '无',
                'latest_created': stats['latest_created'] if stats['latest_created'] is not None else '无'
            }
            
            # 使用模板渲染 - 传递字典参数
            html = my_render_template(str(template_path), template_vars)
            
            return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
            
        except Exception as e:
            logger.error(f"生成索引页面失败: {e}")
            return "<h1>错误</h1><p>无法加载页面列表</p>", 500


# 全局Web服务器实例
_static_page_server = None


def get_static_page_server() -> StaticPageServer:
    """获取全局Web服务器实例"""
    global _static_page_server
    if _static_page_server is None:
        _static_page_server = StaticPageServer()
    return _static_page_server


def start_static_page_server(port: int = 3004, static_page_manager=None) -> bool:
    """
    启动Web 服务器
    
    Args:
        port: 服务端口
        static_page_manager: 静态页面管理器实例
        
    Returns:
        是否启动成功
    """
    global _static_page_server
    
    # 使用与静态页面管理器相同的pages_dir路径
    pages_dir = "data/static_pages"
    if static_page_manager and hasattr(static_page_manager, 'storage_dir'):
        pages_dir = str(static_page_manager.storage_dir)
    
    # 使用集成版本的服务器以支持聊天和微信功能
    _static_page_server = IntegratedStaticPageServer(pages_dir=pages_dir, port=port, static_page_manager=static_page_manager)
    return _static_page_server.start()


def get_static_page_url(filename: str) -> Optional[str]:
    """
    获取静态网页访问URL
    
    Args:
        filename: 文件名
        
    Returns:
        访问URL，如果服务器未运行则返回None
    """
    global _static_page_server
    if _static_page_server is None:
        return None
    
    return _static_page_server.get_page_url(filename)