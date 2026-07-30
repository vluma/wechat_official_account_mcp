"""
静态网页管理工具 - 生成和管理静态网页
"""
import os
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# 导入Web服务器
# 导入Web服务器和存储管理器
try:
    from shared.utils.web_server import get_static_page_server, start_static_page_server
except ImportError:
    def get_static_page_server():
        return None


from shared.storage.storage_manager import StorageManager

# 导入微信消息处理和AI服务
try:
    from tools.wechat_handler import handle_wechat_tool, WechatMessageHandler
    from shared.utils.ai_service import AIService
except ImportError as e:
    logger.warning(f"导入微信相关模块失败: {e}")
    handle_wechat_tool = None
    WechatMessageHandler = None
    AIService = None

logger = logging.getLogger(__name__)


def _generate_random_filename() -> str:
    """
    生成UUID格式的随机文件名，确保文件名唯一性
    
    Returns:
        唯一文件名（包含.html扩展名）
    """
    # 使用UUID生成唯一标识符，去掉横线，截取前8位确保文件名不太长
    unique_id = str(uuid.uuid4()).replace('-', '')[:8]
    return f"{unique_id}.html"


def _validate_html_content(html_content: str) -> bool:
    """
    验证HTML内容是否有效
    
    Args:
        html_content: HTML内容
        
    Returns:
        是否有效
    """
    if not html_content or not isinstance(html_content, str):
        return False
    
    # 检查基本HTML结构
    html_content = html_content.strip()
    if not (html_content.startswith('<') and html_content.endswith('>')):
        return False
    
    return True


class StaticPageManager:
    """静态网页管理器"""
    
    def __init__(self, storage_dir: str = "data/static_pages", db_file: str = "data/storage.db", storage_manager: Optional[StorageManager] = None):
        """
        初始化静态网页管理器
        
        Args:
            storage_dir: 静态网页存储目录
            db_file: 存储管理器数据库文件路径
            storage_manager: 外部传入的存储管理器实例（可选）
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用外部传入的存储管理器实例，否则创建新实例
        if storage_manager:
            self.storage_manager = storage_manager
        else:
            self.storage_manager = StorageManager(db_file)
        
        # 加载元数据
        self.metadata_file = self.storage_dir / "metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict[str, Any]:
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载元数据失败: {e}")
                return {}
        return {}
    
    def _save_metadata(self):
        """保存元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")
    
    def _validate_filename(self, filename: str) -> Optional[str]:
        """
        验证自定义文件名
        
        Args:
            filename: 要验证的文件名
            
        Returns:
            验证通过的文件名（不包含.html），如果验证失败则返回None
        """
        if not filename or not isinstance(filename, str):
            return None
        
        # 移除.html扩展名（如果存在）
        if filename.endswith('.html'):
            filename = filename[:-5]
        
        # 检查文件名是否只包含字母、数字、下划线和连字符
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', filename):
            return None
        
        # 检查长度
        if len(filename) < 1 or len(filename) > 50:
            return None
        
        # 检查不能是保留名称
        reserved_names = ['con', 'prn', 'aux', 'nul', 'com1', 'com2', 'com3', 'com4', 
                         'com5', 'com6', 'com7', 'com8', 'com9', 'lpt1', 'lpt2', 
                         'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9']
        if filename.lower() in reserved_names:
            return None
        
        return filename
    
    def generate_static_page(self, html_content: str, custom_filename: Optional[str] = None, type: str = 'html') -> Dict[str, Any]:
        """
        生成静态网页
        
        Args:
            html_content: HTML内容
            custom_filename: 自定义文件名（可选）
            type: 文件类型 (html, other)，默认html
            
        Returns:
            生成结果字典，包含 success, filename, filepath, created_at, file_size 等字段
        """
        try:
            # 验证HTML内容
            if not html_content.strip():
                return {'success': False, 'error': '内容不能为空'}
            
            # 根据文件类型确定存储目录
            if type == 'other':
                # other类型：使用data/files目录，保留原扩展名
                storage_dir = Path("data/files")
                storage_dir.mkdir(parents=True, exist_ok=True)
                
                # 生成文件名
                if custom_filename:
                    # 直接使用自定义文件名（包含扩展名）
                    filename = custom_filename
                else:
                    # 生成随机文件名，不强制.html扩展名
                    unique_id = str(uuid.uuid4()).replace('-', '')[:8]
                    filename = f"{unique_id}"
                
                # 构建文件路径
                file_path = storage_dir / filename
                
                # 检查文件是否已存在
                if file_path.exists():
                    if custom_filename:
                        return {'success': False, 'error': f'文件已存在: {filename}'}
                    else:
                        # 随机文件名冲突，生成新的
                        while file_path.exists():
                            unique_id = str(uuid.uuid4()).replace('-', '')[:8]
                            filename = f"{unique_id}"
                            file_path = storage_dir / filename
                
                # 保存文件（使用二进制模式，适应各种文件类型）
                with open(file_path, 'wb') as f:
                    # 如果是字符串，编码为UTF-8
                    if isinstance(html_content, str):
                        f.write(html_content.encode('utf-8'))
                    else:
                        f.write(html_content)
                
                # 获取文件大小
                file_size = file_path.stat().st_size
                
                # 创建元数据
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                page_info = {
                    'filename': filename,
                    'filepath': str(file_path),
                    'created_at': created_at,
                    'file_size': file_size,
                    'content_type': 'application/octet-stream'
                }
            else:
                # 默认html类型：使用原有逻辑
                # 生成文件名
                if custom_filename:
                    filename_base = self._validate_filename(custom_filename)
                    if not filename_base:
                        return {'success': False, 'error': f'无效的文件名: {custom_filename}'}
                    filename = f"{filename_base}.html"
                else:
                    filename = _generate_random_filename()  # 已包含.html
                
                # 构建文件路径
                file_path = self.storage_dir / filename
                
                # 检查文件是否已存在
                if file_path.exists():
                    if custom_filename:
                        return {'success': False, 'error': f'文件已存在: {filename_base}'}
                    else:
                        # 随机文件名冲突，生成新的
                        while file_path.exists():
                            filename = _generate_random_filename()
                            file_path = self.storage_dir / filename
                
                # 保存HTML文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                # 获取文件大小
                file_size = file_path.stat().st_size
                
                # 创建元数据
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                page_info = {
                    'filename': filename,
                    'filepath': str(file_path),
                    'created_at': created_at,
                    'file_size': file_size,
                    'content_type': 'text/html'
                }
            
            # 保存元数据（本地文件）
            self.metadata[filename] = page_info
            self._save_metadata()
            
            # 保存到存储管理器
            self.storage_manager.save_static_page(page_info)
            
            # 获取Web服务器URL
            page_url = None
            http_server = get_static_page_server()
            if http_server and http_server.is_running:
                page_url = http_server.get_page_url(filename)
            
            result = {
                'success': True,
                'filename': filename,
                'filepath': str(file_path),
                'created_at': created_at,
                'file_size': file_size,
                'page_url': page_url
            }
            
            logger.info(f"生成静态网页成功: {filename}")
            return result
            
        except Exception as e:
            error_msg = f"生成静态网页失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {'success': False, 'error': error_msg}
    
    def get_page_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        获取静态网页信息
        
        Args:
            filename: 文件名
            
        Returns:
            页面信息字典，如果不存在则返回None
        """
        # 先从存储管理器获取
        page_info = self.storage_manager.get_static_page(filename)
        if not page_info:
            # 如果存储管理器中没有，尝试从本地元数据获取
            if filename in self.metadata:
                page_info = self.metadata[filename]
            else:
                return None
        
        # 检查文件是否仍然存在
        # 直接使用元数据中的filepath，因为文件可能存储在不同目录
        file_path = Path(page_info["filepath"])
        
        if file_path.exists():
            page_info["exists"] = True
            page_info["current_size"] = file_path.stat().st_size
        else:
            page_info["exists"] = False
            page_info["current_size"] = 0
        
        return page_info
    
    def delete_page(self, filename: str) -> bool:
        """
        删除静态网页
        
        Args:
            filename: 文件名
            
        Returns:
            是否删除成功
        """
        try:
            page_info = self.get_page_info(filename)
            if not page_info:
                return False
            
            # 删除文件
            file_path = Path(page_info["filepath"])
            if file_path.exists():
                file_path.unlink()
            
            # 从本地元数据中删除
            if filename in self.metadata:
                del self.metadata[filename]
                self._save_metadata()
            
            # 从存储管理器中删除
            self.storage_manager.delete_static_page(filename)
            
            logger.info(f"删除静态网页: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"删除静态网页失败 {filename}: {e}")
            return False
    
    def list_pages(self) -> Dict[str, Any]:
        """
        列出所有静态网页
        
        Returns:
            页面列表信息
        """
        # 优先使用存储管理器的数据
        storage_pages = self.storage_manager.list_static_pages()
        
        pages = []
        for page_info in storage_pages:
            # 检查文件是否仍然存在
            # 直接使用storage_dir和文件名拼接，确保路径正确
            filename = page_info.get("filename")
            if not filename:
                continue
            
            file_path = self.storage_dir / filename
            
            if file_path.exists():
                page_info["exists"] = True
                page_info["current_size"] = file_path.stat().st_size
            else:
                page_info["exists"] = False
                page_info["current_size"] = 0
            pages.append(page_info)
        
        # 按创建时间排序
        pages.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return {
                "success": True,
                "total": len(pages),
                "pages": pages
            }
            
    def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取静态存储统计信息
        
        Returns:
            包含文件数量、总大小、最早创建时间、最新创建时间的字典
        """
        # 从存储管理器获取统计信息
        stats = self.storage_manager.get_static_storage_stats()
        
        # 计算文件大小的友好显示
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
        
        # 格式化统计信息
        formatted_stats = {
            'total_files': stats['total_files'],
            'total_size': format_file_size(stats['total_size']),
            'total_size_bytes': stats['total_size'],
            'earliest_created': stats['earliest_created'],
            'latest_created': stats['latest_created']
        }
        
        return formatted_stats
    
    def start_integrated_server(self, port: int = 3004) -> bool:
        """
        启动集成微信消息处理功能的Web服务器
        
        Args:
            port: 服务端口
            
        Returns:
            是否启动成功
        """
        try:
            from shared.utils.web_server import IntegratedStaticPageServer
            
            # 创建集成服务器实例
            self.integrated_server = IntegratedStaticPageServer(
                pages_dir=str(self.storage_dir),
                port=port,
                static_page_manager=self
            )
            
            success = self.integrated_server.start()
            if success:
                logger.info(f"集成Web服务器启动成功，端口: {port}")
                logger.info(f"静态页面访问: http://localhost:{port}/pages/")
                logger.info(f"微信服务器验证: http://localhost:{port}/wechat/verify")
                logger.info(f"聊天界面: http://localhost:{port}/chat/")
            
            return success
            
        except Exception as e:
            logger.error(f"启动集成服务器失败: {e}")
            return False
    
    def stop_integrated_server(self) -> bool:
        """
        停止集成Web服务器
        
        Returns:
            是否停止成功
        """
        try:
            if hasattr(self, 'integrated_server') and self.integrated_server:
                success = self.integrated_server.stop()
                if success:
                    logger.info("集成Web服务器已停止")
                return success
            return False
        except Exception as e:
            logger.error(f"停止集成服务器失败: {e}")
            return False
    
    def get_server_status(self) -> dict:
        """
        获取集成服务器状态
        
        Returns:
            服务器状态信息
        """
        if hasattr(self, 'integrated_server') and self.integrated_server:
            return self.integrated_server.get_status()
        return {"is_running": False}


# ========== 工具函数 ==========

def handle_static_page_tool(arguments: dict, static_page_manager: StaticPageManager) -> str:
    """
    处理静态网页工具调用
    
    Args:
        arguments: 工具参数
        static_page_manager: 静态网页管理器实例
        
    Returns:
        处理结果文本
    """
    try:
        action = arguments.get('action')
        
        if action == 'generate':
            html_content = arguments.get('htmlContent', '')
            custom_filename = arguments.get('filename')
            file_type = arguments.get('type', 'html')
            
            result = static_page_manager.generate_static_page(html_content, custom_filename, file_type)
            
            if result['success']:
                page_url_info = ""
                if result.get('page_url'):
                    if file_type == 'other':
                        # other类型文件直接通过根目录访问
                        page_url_info = f"文件URL: http://localhost:{http_server.get_port()}/{result['filename']}\n" if (http_server and http_server.is_running) else ""
                    else:
                        page_url_info = f"网页URL: {result['page_url']}\n"
                
                return (f"静态网页生成成功！\n"
                       f"文件名: {result['filename']}\n"
                       f"文件路径: {result['filepath']}\n"
                       f"创建时间: {result['created_at']}\n"
                       f"文件大小: {result['file_size']} 字节\n"
                       f"文件类型: {file_type}\n"
                       f"{page_url_info}\n"
                       f"可通过以下URL访问: {result.get('page_url', '服务器未启动') if file_type != 'other' else f'http://localhost:{http_server.get_port()}/{result["filename"]}' if (http_server and http_server.is_running) else '服务器未启动'}")
            else:
                return f"生成失败: {result['error']}"
        
        elif action == 'info':
            filename = arguments.get('filename', '')
            if not filename:
                return "错误: 请提供文件名"
            
            page_info = static_page_manager.get_page_info(filename)
            if not page_info:
                return f"文件不存在: {filename}"
            
            # 获取访问URL
            http_server = get_static_page_server()
            page_url = None
            if http_server and http_server.is_running:
                page_url = http_server.get_page_url(filename)
            
            return (f"文件信息:\n"
                   f"文件名: {page_info['filename']}\n"
                   f"文件路径: {page_info['filepath']}\n"
                   f"创建时间: {page_info['created_at']}\n"
                   f"文件存在: {'是' if page_info['exists'] else '否'}\n"
                   f"文件大小: {page_info.get('current_size', page_info.get('file_size', 0))} 字节\n"
                   f"访问URL: {page_url or '服务器未启动'}")
        
        elif action == 'list':
            result = static_page_manager.list_pages()
            if result['total'] == 0:
                return "暂无静态网页"
            
            # 获取服务器状态
            http_server = get_static_page_server()
            server_running = http_server and http_server.is_running
            
            lines = [f"静态网页列表 (共 {result['total']} 个):\n"]
            for i, page in enumerate(result['pages'], 1):
                lines.append(f"{i}. {page['filename']}")
                lines.append(f"   创建时间: {page['created_at']}")
                lines.append(f"   文件大小: {page.get('current_size', page.get('file_size', 0))} 字节")
                
                if server_running:
                    page_url = http_server.get_page_url(page['filename'])
                    lines.append(f"   访问URL: {page_url}")
                else:
                    lines.append(f"   访问URL: 服务器未启动")
                lines.append("")
            
            return "\n".join(lines)
        
        elif action == 'delete':
            filename = arguments.get('filename', '')
            if not filename:
                return "错误: 请提供文件名"
            
            success = static_page_manager.delete_page(filename)
            if success:
                return f"删除成功: {filename}"
            else:
                return f"删除失败: 文件不存在或删除出错"
        
        elif action == 'start_server':
            port = arguments.get('port', 3004)
            success = start_static_page_server(port=port, static_page_manager=static_page_manager)
            
            if success:
                return f"Web服务器启动成功！\n端口: {port}\n可通过 http://localhost:{port}/ 访问"
            else:
                # 检查是否已经在运行
                http_server = get_static_page_server()
                if http_server and http_server.is_running:
                    return f"Web服务器已在运行中\n当前端口: {http_server.get_port()}\n可通过 http://localhost:{http_server.get_port()}/ 访问"
                else:
                    return f"启动失败: 无法启动服务器"
        
        elif action == 'server_status':
            http_server = get_static_page_server()
            if http_server and http_server.is_running:
                port = http_server.get_port()
                return f"Web服务器正在运行\n端口: {port}\n可通过 http://localhost:{port}/ 访问"
            else:
                return "Web服务器未启动"
        
        elif action == 'start_integrated_server':
            port = arguments.get('port', 3004)
            success = static_page_manager.start_integrated_server(port=port)
            
            if success:
                return (f"集成Web服务器启动成功！\n"
                       f"端口: {port}\n"
                       f"静态页面: http://localhost:{port}/pages/\n"
                       f"微信验证: http://localhost:{port}/wechat/verify\n"
                       f"聊天界面: http://localhost:{port}/chat/\n"
                       f"服务器首页: http://localhost:{port}/")
            else:
                return f"启动集成服务器失败: 端口 {port} 可能已被占用或启动出错"
        
        elif action == 'stop_integrated_server':
            success = static_page_manager.stop_integrated_server()
            if success:
                return "集成Web服务器已停止"
            else:
                return "停止集成服务器失败或服务器未运行"
        
        elif action == 'integrated_server_status':
            status = static_page_manager.get_server_status()
            if status.get('is_running', False):
                port = status.get('port', 3004)
                return (f"集成Web服务器正在运行\n"
                       f"端口: {port}\n"
                       f"静态页面: http://localhost:{port}/pages/\n"
                       f"微信验证: http://localhost:{port}/wechat/verify\n"
                       f"聊天界面: http://localhost:{port}/chat/\n"
                       f"服务器首页: http://localhost:{port}/")
            else:
                return "集成Web服务器未启动"
        
        else:
            return f"未知操作: {action}"
    
    except Exception as e:
        error_msg = f"处理静态网页工具失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg
