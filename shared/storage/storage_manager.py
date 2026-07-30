"""
存储管理器 - 管理本地素材存储，支持S3兼容存储服务
"""
import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)


class StorageManager:
    """存储管理器 - 支持本地存储和S3兼容存储"""
    
    # 单例模式实现
    _instance = None
    _initialized = False
    
    def __new__(cls, db_file: str = "data/storage.db"):
        if cls._instance is None:
            cls._instance = super(StorageManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, db_file: str = "data/storage.db"):
        """
        初始化存储管理器
        
        Args:
            db_file: 数据库文件路径（使用 JSON 文件存储）
        """
        # 防止重复初始化
        if self._initialized:
            return
        
        self.db_file = db_file
        self.data: Dict[str, Any] = {
            'media': [],  # 素材列表
            'static_pages': [],  # 静态网页列表
            'wechat_messages': [],  # 微信消息列表
            'user_verification_codes': []  # 用户验证码列表
        }
        
        # 初始化S3相关配置
        self._init_s3_config()
        
        # 加载数据
        self._load_data()
        
        # 启动定时同步（如果配置了）
        self._start_scheduled_sync()
        
        # 启动验证码清理定时任务（如果配置了）
        self._start_verification_code_cleanup()
        
        # 标记为已初始化
        self._initialized = True
    
    def _init_s3_config(self):
        """初始化S3相关配置"""
        # 远程存储开关
        self.remote_enabled = os.getenv('STORAGE_REMOTE_ENABLE', 'false').lower() == 'true'
        
        # S3读写权限控制
        self.s3_read_only = os.getenv('STORAGE_S3_READ_ONLY', 'false').lower() == 'true'
        self.s3_write_enabled = os.getenv('STORAGE_S3_WRITE_ENABLED', 'true').lower() == 'true'
        
        # 如果设置了只读模式，则禁用写入
        if self.s3_read_only:
            self.s3_write_enabled = False
            logger.info("S3存储设置为只读模式")
        
        # S3配置
        self.s3_endpoint_url = os.getenv('STORAGE_S3_ENDPOINT', '')
        self.s3_access_key = os.getenv('STORAGE_S3_ACCESS_KEY', '')
        self.s3_secret_key = os.getenv('STORAGE_S3_SECRET_KEY', '')
        self.s3_bucket_name = os.getenv('STORAGE_S3_BUCKET', '')
        self.s3_region_name = os.getenv('STORAGE_S3_REGION', '')
        self.s3_path_prefix = os.getenv('STORAGE_S3_PATH_PREFIX', '')
        
        # 定时同步配置
        self.sync_cron = os.getenv('STORAGE_SYN_CRON', '')
        self.sync_override = os.getenv('STORAGE_SYN_OVERRIDE', 'false').lower() == 'true'
        
        # 初始化S3客户端（如果启用了远程存储）
        self.s3_client = None
        if self.remote_enabled:
            self._init_s3_client()
    
    def _init_s3_client(self):
        """初始化S3客户端"""
        try:
            import boto3
            from botocore.config import Config
            
            # 创建S3客户端配置
            s3_config = Config(
                region_name=self.s3_region_name,
                signature_version='s3v4',
                retries={
                    'max_attempts': 3,
                    'mode': 'standard'
                }
            )
            
            # 初始化S3客户端
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.s3_endpoint_url,
                aws_access_key_id=self.s3_access_key,
                aws_secret_access_key=self.s3_secret_key,
                config=s3_config
            )
            
            # 检查桶是否存在
            self.s3_client.head_bucket(Bucket=self.s3_bucket_name)
            logger.info(f"S3客户端初始化成功，桶: {self.s3_bucket_name}")
        except Exception as e:
            logger.error(f"S3客户端初始化失败: {e}")
            self.s3_client = None
            self.remote_enabled = False
    
    def _start_scheduled_sync(self):
        """
        启动定时同步任务
        """
        if not self.remote_enabled or not self.sync_cron:
            return
        
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            # 创建调度器
            self.scheduler = BackgroundScheduler()
            
            # 定义同步任务的包装函数，将异步函数转换为同步函数
            def sync_from_remote_wrapper():
                # 创建新的事件循环并运行异步任务
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.sync_from_remote())
                loop.close()
            
            # 添加定时任务
            self.scheduler.add_job(
                sync_from_remote_wrapper,
                trigger=CronTrigger.from_crontab(self.sync_cron),
                id='remote_sync_job',
                name='Remote Storage Sync',
                replace_existing=True
            )
            
            # 启动调度器
            self.scheduler.start()
            logger.info(f"定时同步任务已启动，Cron表达式: {self.sync_cron}")
        except Exception as e:
            logger.error(f"启动定时同步任务失败: {e}")
    
    def _load_data(self):
        """加载数据"""
        db_dir = Path(self.db_file).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                if 'media' not in self.data:
                    self.data['media'] = []
                if 'static_pages' not in self.data:
                    self.data['static_pages'] = []
                if 'wechat_messages' not in self.data:
                    self.data['wechat_messages'] = []
                if 'user_verification_codes' not in self.data:
                    self.data['user_verification_codes'] = []
            except Exception as e:
                logger.error(f"加载存储数据失败: {e}")
                self.data = {'media': [], 'static_pages': []}
        else:
            self.data = {'media': [], 'static_pages': []}
    
    def _save_data(self):
        """
        保存数据
        """
        db_dir = Path(self.db_file).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            
            # 如果启用了远程存储且允许写入，将数据文件同步到S3
            if self.remote_enabled and self.s3_client and self.s3_write_enabled:
                # 使用异步方式上传，但不阻塞主线程
                async def upload_data_file():
                    await self._upload_to_s3(self.db_file, self._get_s3_key(self.db_file))
                
                try:
                    # 检查当前线程是否已经有一个运行中的事件循环
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 如果已经有运行中的事件循环，使用create_task将异步任务添加到现有循环中
                        loop.create_task(upload_data_file())
                    else:
                        # 如果没有运行中的事件循环，创建新的事件循环并运行
                        loop.run_until_complete(upload_data_file())
                except RuntimeError:
                    # 如果获取事件循环失败，创建新的事件循环
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(upload_data_file())
                    finally:
                        loop.close()
            elif self.remote_enabled and not self.s3_write_enabled:
                logger.debug("S3写入功能已禁用，跳过文件上传")
        except Exception as e:
            logger.error(f"保存存储数据失败: {e}")
    
    def _get_s3_key(self, file_path: str) -> str:
        """获取S3存储的键名"""
        relative_path = os.path.relpath(file_path, os.getcwd())
        key_parts = []
        if self.s3_path_prefix:
            key_parts.append(self.s3_path_prefix)
        key_parts.append(relative_path.replace('\\', '/'))
        return '/'.join(key_parts)
    
    async def _upload_to_s3(self, file_path: str, s3_key: str) -> bool:
        """
        上传文件到S3存储，支持异步操作和重试机制
        """
        if not self.s3_client or not os.path.exists(file_path):
            return False
        
        # 检查写入权限
        if not self.s3_write_enabled:
            logger.debug(f"S3写入功能已禁用，跳过文件上传: {s3_key}")
            return False
        
        # 重试机制：每间隔5秒重试2次
        max_retries = 2
        retry_interval = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 使用同步客户端的上传方法，通过asyncio.to_thread转换为异步
                await asyncio.to_thread(
                    self.s3_client.upload_file,
                    Filename=file_path,
                    Bucket=self.s3_bucket_name,
                    Key=s3_key
                )
                logger.info(f"文件上传到S3成功: {s3_key}")
                return True
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"文件上传到S3失败，尝试 {attempt + 1}/{max_retries + 1}: {s3_key}, 错误: {e}")
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error(f"文件上传到S3失败，已达到最大重试次数: {s3_key}, 错误: {e}")
                    return False
    
    async def _download_from_s3(self, s3_key: str, file_path: str) -> bool:
        """
        从S3存储下载文件，支持异步操作和重试机制
        """
        if not self.s3_client:
            return False
        
        # 重试机制：每间隔5秒重试2次
        max_retries = 2
        retry_interval = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                
                # 使用同步客户端的下载方法，通过asyncio.to_thread转换为异步
                await asyncio.to_thread(
                    self.s3_client.download_file,
                    Bucket=self.s3_bucket_name,
                    Key=s3_key,
                    Filename=file_path
                )
                logger.info(f"从S3下载文件成功: {s3_key} -> {file_path}")
                return True
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"从S3下载文件失败，尝试 {attempt + 1}/{max_retries + 1}: {s3_key}, 错误: {e}")
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error(f"从S3下载文件失败，已达到最大重试次数: {s3_key}, 错误: {e}")
                    return False
    
    async def _delete_from_s3(self, s3_key: str) -> bool:
        """
        从S3存储删除文件，支持异步操作和重试机制
        """
        if not self.s3_client:
            return False
        
        # 检查写入权限
        if not self.s3_write_enabled:
            logger.debug(f"S3写入功能已禁用，跳过文件删除: {s3_key}")
            return False
        
        # 重试机制：每间隔5秒重试2次
        max_retries = 2
        retry_interval = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 使用同步客户端的删除方法，通过asyncio.to_thread转换为异步
                await asyncio.to_thread(
                    self.s3_client.delete_object,
                    Bucket=self.s3_bucket_name,
                    Key=s3_key
                )
                logger.info(f"从S3删除文件成功: {s3_key}")
                return True
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"从S3删除文件失败，尝试 {attempt + 1}/{max_retries + 1}: {s3_key}, 错误: {e}")
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error(f"从S3删除文件失败，已达到最大重试次数: {s3_key}, 错误: {e}")
                    return False
    
    async def _list_s3_objects(self, prefix: str = '') -> List[str]:
        """
        列出S3存储中的对象，支持异步操作和重试机制
        """
        if not self.s3_client:
            return []
        
        # 重试机制：每间隔5秒重试2次
        max_retries = 2
        retry_interval = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 使用同步客户端的list_objects_v2方法，通过asyncio.to_thread转换为异步
                response = await asyncio.to_thread(
                    self.s3_client.list_objects_v2,
                    Bucket=self.s3_bucket_name,
                    Prefix=prefix
                )
                
                objects = []
                if 'Contents' in response:
                    objects = [obj['Key'] for obj in response['Contents']]
                
                logger.info(f"从S3列出对象成功，找到 {len(objects)} 个对象")
                return objects
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"从S3列出对象失败，尝试 {attempt + 1}/{max_retries + 1}: 错误: {e}")
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error(f"从S3列出对象失败，已达到最大重试次数: 错误: {e}")
                    return []
    
    async def _get_s3_object_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """
        获取S3对象的元信息，支持异步操作和重试机制
        """
        if not self.s3_client:
            return None
        
        # 重试机制：每间隔5秒重试2次
        max_retries = 2
        retry_interval = 5
        
        for attempt in range(max_retries + 1):
            try:
                # 使用同步客户端的head_object方法，通过asyncio.to_thread转换为异步
                response = await asyncio.to_thread(
                    self.s3_client.head_object,
                    Bucket=self.s3_bucket_name,
                    Key=s3_key
                )
                
                return {
                    'last_modified': response['LastModified'],
                    'content_length': response['ContentLength'],
                    'content_type': response.get('ContentType', '')
                }
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"获取S3对象信息失败，尝试 {attempt + 1}/{max_retries + 1}: {s3_key}, 错误: {e}")
                    await asyncio.sleep(retry_interval)
                else:
                    logger.error(f"获取S3对象信息失败，已达到最大重试次数: {s3_key}, 错误: {e}")
                    return None
    
    async def sync_from_remote(self) -> Dict[str, Any]:
        """
        从远程S3存储同步文件到本地，支持异步操作
        """
        if not self.remote_enabled or not self.s3_client:
            return {'status': 'error', 'message': '远程存储未启用'}
        
        try:
            # 列出S3中的所有对象
            s3_objects = await self._list_s3_objects(self.s3_path_prefix)
            
            sync_count = 0
            override_count = 0
            
            for s3_key in s3_objects:
                # 过滤掉不需要同步的对象（如隐藏文件）
                if s3_key.endswith('/'):  # 跳过目录
                    continue
                if s3_key.startswith('.'):  # 跳过隐藏文件
                    continue
                
                # 计算本地文件路径
                relative_key = s3_key.replace(self.s3_path_prefix, '') if self.s3_path_prefix else s3_key
                local_file_path = os.path.join(os.getcwd(), relative_key.lstrip('/'))
                
                # 确保目标目录存在
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                
                # 检查本地文件是否存在
                if os.path.exists(local_file_path):
                    if self.sync_override:
                        # 获取文件的修改时间
                        local_mtime = datetime.fromtimestamp(os.path.getmtime(local_file_path))
                        # 将local_mtime转换为带时区的datetime对象（UTC）
                        from datetime import timezone
                        local_mtime = local_mtime.replace(tzinfo=timezone.utc)
                        s3_obj_info = await self._get_s3_object_info(s3_key)
                        
                        if s3_obj_info and s3_obj_info['last_modified'] > local_mtime:
                            # S3文件更新，覆盖本地文件
                            if await self._download_from_s3(s3_key, local_file_path):
                                sync_count += 1
                                override_count += 1
                                logger.info(f"同步并覆盖本地文件: {local_file_path}")
                    else:
                        logger.info(f"本地文件已存在，跳过同步: {local_file_path}")
                else:
                    # 本地文件不存在，下载
                    if await self._download_from_s3(s3_key, local_file_path):
                        sync_count += 1
                        logger.info(f"从S3下载新文件: {local_file_path}")
            
            # 重新加载数据
            self._load_data()
            
            return {
                'status': 'success',
                'message': f'同步完成',
                'sync_count': sync_count,
                'override_count': override_count,
                'total_objects': len(s3_objects)
            }
        except Exception as e:
            logger.error(f"从远程同步文件失败: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def sync_to_remote(self) -> Dict[str, Any]:
        """
        将本地文件同步到远程S3存储，支持异步操作
        """
        if not self.remote_enabled or not self.s3_client:
            return {'status': 'error', 'message': '远程存储未启用'}
        
        # 检查写入权限
        if not self.s3_write_enabled:
            return {'status': 'error', 'message': 'S3写入功能已禁用'}
        
        try:
            sync_count = 0
            
            # 同步整个data目录
            data_dir = os.path.join(os.getcwd(), 'data')
            
            # 遍历data目录下的所有文件
            for root, dirs, files in os.walk(data_dir):
                for file in files:
                    # 跳过隐藏文件
                    if file.startswith('.'):
                        continue
                    
                    # 构建本地文件路径
                    local_file_path = os.path.join(root, file)
                    
                    # 生成S3键名
                    s3_key = self._get_s3_key(local_file_path)
                    
                    # 上传文件到S3
                    if await self._upload_to_s3(local_file_path, s3_key):
                        sync_count += 1
            
            return {
                'status': 'success',
                'message': '同步到远程成功',
                'sync_count': sync_count
            }
        except Exception as e:
            logger.error(f"同步到远程失败: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def save_media(self, media_info: Dict[str, Any]):
        """
        保存素材信息
        
        Args:
            media_info: 素材信息字典，包含 media_id, type, created_at, url 等
        """
        media_id = media_info.get('media_id')
        if not media_id:
            logger.warning("素材信息缺少 media_id，跳过保存")
            return
        
        # 检查是否已存在
        existing_index = None
        for i, media in enumerate(self.data['media']):
            if media.get('media_id') == media_id:
                existing_index = i
                break
        
        if existing_index is not None:
            # 更新现有记录
            self.data['media'][existing_index].update(media_info)
            logger.info(f"更新素材信息: {media_id}")
        else:
            # 添加新记录
            self.data['media'].append(media_info)
            logger.info(f"保存素材信息: {media_id}")
        
        self._save_data()
    
    def get_media(self, media_id: str) -> Optional[Dict[str, Any]]:
        """
        获取素材信息
        
        Args:
            media_id: 素材ID
            
        Returns:
            素材信息字典，如果不存在则返回 None
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        for media in self.data['media']:
            if media.get('media_id') == media_id:
                return media
        return None
    
    def list_media(self, media_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出素材
        
        Args:
            media_type: 素材类型过滤（可选）
            
        Returns:
            素材列表
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        if media_type:
            return [m for m in self.data['media'] if m.get('type') == media_type]
        return self.data['media'].copy()
    
    def delete_media(self, media_id: str) -> bool:
        """
        删除素材信息
        
        Args:
            media_id: 素材ID
            
        Returns:
            是否删除成功
        """
        for i, media in enumerate(self.data['media']):
            if media.get('media_id') == media_id:
                del self.data['media'][i]
                self._save_data()
                logger.info(f"删除素材信息: {media_id}")
                return True
        return False

    # ========== 微信消息管理方法 ==========

    def save_wechat_message(self, message_info: Dict[str, Any]):
        """
        保存微信消息信息
        
        Args:
            message_info: 微信消息信息字典，包含 from_user, to_user, msg_type, content 等
        """
        # 使用时间戳作为唯一标识
        import time
        message_id = str(int(time.time() * 1000))
        message_info['message_id'] = message_id
        
        # 添加到消息列表开头（最新的在前面）
        self.data['wechat_messages'].insert(0, message_info)
        
        # 限制消息数量，避免文件过大（保留最近1000条）
        if len(self.data['wechat_messages']) > 1000:
            self.data['wechat_messages'] = self.data['wechat_messages'][:1000]
        
        logger.info(f"保存微信消息: {message_id}")
        self._save_data()

    def get_wechat_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        获取微信消息信息
        
        Args:
            message_id: 消息ID
            
        Returns:
            微信消息信息字典，如果不存在则返回 None
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        for message in self.data['wechat_messages']:
            if message.get('message_id') == message_id:
                return message
        return None

    def list_wechat_messages(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        列出微信消息
        
        Args:
            limit: 返回记录数量限制
            
        Returns:
            微信消息列表
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        return self.data['wechat_messages'][:limit]

    def delete_wechat_message(self, message_id: str) -> bool:
        """
        删除微信消息信息
        
        Args:
            message_id: 消息ID
            
        Returns:
            是否删除成功
        """
        for i, message in enumerate(self.data['wechat_messages']):
            if message.get('message_id') == message_id:
                del self.data['wechat_messages'][i]
                self._save_data()
                logger.info(f"删除微信消息: {message_id}")
                return True
        return False

    def clear_wechat_messages(self) -> bool:
        """
        清空所有微信消息
        
        Returns:
            是否清空成功
        """
        try:
            self.data['wechat_messages'] = []
            self._save_data()
            logger.info("清空所有微信消息")
            return True
        except Exception as e:
            logger.error(f"清空微信消息失败: {e}")
            return False

    # ========== 静态网页管理方法 ==========

    def save_static_page(self, page_info: Dict[str, Any]):
        """
        保存静态网页信息
        
        Args:
            page_info: 静态网页信息字典，包含 filename, filepath, created_at 等
        """
        filename = page_info.get('filename')
        if not filename:
            logger.warning("静态网页信息缺少 filename，跳过保存")
            return

        # 检查是否已存在
        existing_index = None
        for i, page in enumerate(self.data['static_pages']):
            if page.get('filename') == filename:
                existing_index = i
                break

        if existing_index is not None:
            # 更新现有记录
            self.data['static_pages'][existing_index].update(page_info)
            logger.info(f"更新静态网页信息: {filename}")
        else:
            # 添加新记录
            self.data['static_pages'].append(page_info)
            logger.info(f"保存静态网页信息: {filename}")

        self._save_data()
        
        # 如果启用了远程存储且允许写入，将静态页面文件同步到S3
        if self.remote_enabled and self.s3_client and self.s3_write_enabled:
            filepath = page_info.get('filepath')
            if filepath and os.path.exists(filepath):
                s3_key = self._get_s3_key(filepath)
                
                # 使用异步方式上传，但不阻塞主线程
                async def upload_static_page():
                    await self._upload_to_s3(filepath, s3_key)
                
                try:
                    # 检查当前线程是否已经有一个运行中的事件循环
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 如果已经有运行中的事件循环，使用create_task将异步任务添加到现有循环中
                        loop.create_task(upload_static_page())
                    else:
                        # 如果没有运行中的事件循环，创建新的事件循环并运行
                        loop.run_until_complete(upload_static_page())
                except RuntimeError:
                    # 如果获取事件循环失败，创建新的事件循环
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(upload_static_page())
                    finally:
                        loop.close()
        elif self.remote_enabled and not self.s3_write_enabled:
            logger.debug("S3写入功能已禁用，跳过静态页面文件上传")

    def get_static_page(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        获取静态网页信息
        
        Args:
            filename: 文件名
            
        Returns:
            静态网页信息字典，如果不存在则返回 None
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        for page in self.data['static_pages']:
            if page.get('filename') == filename:
                return page
        return None

    def list_static_pages(self) -> List[Dict[str, Any]]:
        """
        列出所有静态网页
        
        Returns:
            静态网页列表
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        return self.data['static_pages'].copy()

    def delete_static_page(self, filename: str) -> bool:
        """
        删除静态网页信息
        
        Args:
            filename: 文件名
            
        Returns:
            是否删除成功
        """
        for i, page in enumerate(self.data['static_pages']):
            if page.get('filename') == filename:
                # 获取文件路径
                filepath = page.get('filepath')
                
                # 删除本地文件
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        logger.info(f"删除本地静态网页文件: {filepath}")
                    except Exception as e:
                        logger.error(f"删除本地静态网页文件失败: {filepath}, 错误: {e}")
                
                # 如果启用了远程存储且允许写入，从S3删除文件
                if self.remote_enabled and self.s3_client and self.s3_write_enabled:
                    if filepath:
                        s3_key = self._get_s3_key(filepath)
                    else:
                        # 如果没有filepath，构建默认路径
                        default_filepath = os.path.join(os.getcwd(), 'data', 'static_pages', filename)
                        s3_key = self._get_s3_key(default_filepath)
                    
                    # 使用异步方式删除，但不阻塞主线程
                    async def delete_from_s3_async():
                        await self._delete_from_s3(s3_key)
                    
                    try:
                        # 检查当前线程是否已经有一个运行中的事件循环
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # 如果已经有运行中的事件循环，使用create_task将异步任务添加到现有循环中
                            loop.create_task(delete_from_s3_async())
                        else:
                            # 如果没有运行中的事件循环，创建新的事件循环并运行
                            loop.run_until_complete(delete_from_s3_async())
                    except RuntimeError:
                        # 如果获取事件循环失败，创建新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(delete_from_s3_async())
                        finally:
                            loop.close()
                elif self.remote_enabled and not self.s3_write_enabled:
                    logger.debug("S3写入功能已禁用，跳过S3文件删除")
                
                # 删除记录并保存数据
                del self.data['static_pages'][i]
                self._save_data()
                logger.info(f"删除静态网页信息: {filename}")
                return True
        return False
        
    def get_static_storage_stats(self) -> Dict[str, Any]:
        """
        获取静态存储统计信息
        
        Returns:
            包含文件数量、总大小、最早创建时间、最新创建时间的字典
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        pages = self.data['static_pages']
        total_files = len(pages)
        
        if total_files == 0:
            return {
                'total_files': 0,
                'total_size': 0,
                'earliest_created': None,
                'latest_created': None
            }
        
        # 计算总文件大小
        total_size = sum(page.get('file_size', 0) for page in pages)
        
        # 计算最早和最新创建时间
        created_times = [page.get('created_at', '') for page in pages if page.get('created_at')]
        created_times.sort()
        
        return {
            'total_files': total_files,
            'total_size': total_size,
            'earliest_created': created_times[0] if created_times else None,
            'latest_created': created_times[-1] if created_times else None
        }

    # ========== 用户验证码管理方法 ==========

    def save_verification_code(self, code_info: Dict[str, Any]):
        """
        保存用户验证码信息
        
        Args:
            code_info: 验证码信息字典，包含 code, created_at, expires_at, used, source 等
        """
        code = code_info.get('code')
        if not code:
            logger.warning("验证码信息缺少 code，跳过保存")
            return
        
        # 检查是否已存在
        existing_index = None
        for i, existing_code in enumerate(self.data['user_verification_codes']):
            if existing_code.get('code') == code:
                existing_index = i
                break
        
        if existing_index is not None:
            # 更新现有记录
            self.data['user_verification_codes'][existing_index].update(code_info)
            logger.info(f"更新验证码信息: {code}")
        else:
            # 添加新记录
            self.data['user_verification_codes'].append(code_info)
            logger.info(f"保存验证码信息: {code}")
        
        self._save_data()

    def get_verification_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        获取验证码信息
        
        Args:
            code: 验证码字符串
            
        Returns:
            验证码信息字典，如果不存在则返回 None
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        for code_info in self.data['user_verification_codes']:
            if code_info.get('code') == code:
                return code_info
        return None

    def list_verification_codes(self, only_valid: bool = False) -> List[Dict[str, Any]]:
        """
        列出用户验证码
        
        Args:
            only_valid: 是否只返回有效的验证码
            
        Returns:
            验证码列表
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        
        if not only_valid:
            return self.data['user_verification_codes'].copy()
        
        # 只返回有效的验证码
        from datetime import datetime
        valid_codes = []
        now = datetime.now()
        
        for code_info in self.data['user_verification_codes']:
            # 检查是否过期
            try:
                expires_at = datetime.fromisoformat(code_info.get('expires_at', ''))
                if now <= expires_at and not code_info.get('used', False):
                    valid_codes.append(code_info)
            except (ValueError, TypeError):
                # 如果时间格式错误，跳过该记录
                continue
        
        return valid_codes

    def delete_verification_code(self, code: str) -> bool:
        """
        删除验证码信息
        
        Args:
            code: 验证码字符串
            
        Returns:
            是否删除成功
        """
        for i, code_info in enumerate(self.data['user_verification_codes']):
            if code_info.get('code') == code:
                del self.data['user_verification_codes'][i]
                self._save_data()
                logger.info(f"删除验证码: {code}")
                return True
        return False

    def mark_verification_code_used(self, code: str) -> bool:
        """
        标记验证码为已使用
        
        Args:
            code: 验证码字符串
            
        Returns:
            是否标记成功
        """
        for i, code_info in enumerate(self.data['user_verification_codes']):
            if code_info.get('code') == code:
                self.data['user_verification_codes'][i]['used'] = True
                self.data['user_verification_codes'][i]['used_at'] = datetime.now().isoformat()
                self._save_data()
                logger.info(f"标记验证码已使用: {code}")
                return True
        return False

    def cleanup_expired_verification_codes(self) -> int:
        """
        清理过期的验证码
        
        Returns:
            删除的验证码数量
        """
        from datetime import datetime
        
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        
        now = datetime.now()
        expired_codes = []
        
        # 找出过期的验证码
        for code_info in self.data['user_verification_codes']:
            try:
                expires_at = datetime.fromisoformat(code_info.get('expires_at', ''))
                if now > expires_at:
                    expired_codes.append(code_info.get('code'))
            except (ValueError, TypeError):
                # 如果时间格式错误，也标记为过期
                expired_codes.append(code_info.get('code'))
        
        # 删除过期的验证码
        cleaned_count = 0
        for code in expired_codes:
            if self.delete_verification_code(code):
                cleaned_count += 1
        
        if cleaned_count > 0:
            self._save_data()
            logger.info(f"清理了 {cleaned_count} 个过期验证码")
        
        return cleaned_count
    
    def get_verification_code_valid_days(self) -> int:
        """
        获取验证码有效天数配置
        
        Returns:
            有效天数，默认90天
        """
        return int(os.getenv('OPENAI_VERIFICATION_CODE_VALID_DAYS', '90'))
    
    def get_verification_code_stats(self) -> Dict[str, Any]:
        """
        获取验证码统计信息
        
        Returns:
            包含总数量、有效数量、已使用数量、过期数量的字典
        """
        # 每次都重新从文件加载数据，确保获取最新内容
        self._load_data()
        
        from datetime import datetime
        now = datetime.now()
        
        total_count = len(self.data['user_verification_codes'])
        valid_count = 0
        used_count = 0
        expired_count = 0
        
        for code_info in self.data['user_verification_codes']:
            # 检查是否已使用
            if code_info.get('used', False):
                used_count += 1
                continue
            
            # 检查是否过期
            try:
                expires_at = datetime.fromisoformat(code_info.get('expires_at', ''))
                if now > expires_at:
                    expired_count += 1
                else:
                    valid_count += 1
            except (ValueError, TypeError):
                # 如果时间格式错误，计入过期
                expired_count += 1
        
        return {
            'total_count': total_count,
            'valid_count': valid_count,
            'used_count': used_count,
            'expired_count': expired_count
        }
    
    def _start_verification_code_cleanup(self):
        """启动验证码清理定时任务"""
        # 从环境变量获取验证码清理cron表达式
        cleanup_cron = os.getenv('OPENAI_VERIFICATION_CODE_CLEANUP_CRON', '30 0 * * *')  # 默认每天凌晨0点30分执行
        
        if not cleanup_cron:
            logger.info("验证码清理定时任务未配置（OPENAI_VERIFICATION_CODE_CLEANUP_CRON环境变量未设置）")
            return
        
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            
            # 创建调度器（如果还没有的话）
            if not hasattr(self, 'scheduler'):
                self.scheduler = BackgroundScheduler()
                
                # 如果调度器没有启动，启动它
                if not self.scheduler.running:
                    self.scheduler.start()
                    logger.info("调度器启动成功")
            
            # 添加验证码清理定时任务
            self.scheduler.add_job(
                self._cleanup_expired_verification_codes_job,
                trigger=CronTrigger.from_crontab(cleanup_cron),
                id='verification_code_cleanup_job',
                name='Verification Code Cleanup',
                replace_existing=True
            )
            
            logger.info(f"验证码清理定时任务已启动，Cron表达式: {cleanup_cron}")
        except Exception as e:
            logger.error(f"启动验证码清理定时任务失败: {e}")
    
    def _cleanup_expired_verification_codes_job(self):
        """验证码清理定时任务执行函数"""
        try:
            logger.info("开始执行验证码清理任务")
            cleaned_count = self.cleanup_expired_verification_codes()
            logger.info(f"验证码清理任务完成，清理了 {cleaned_count} 个过期验证码")
            return cleaned_count
        except Exception as e:
            logger.error(f"验证码清理任务执行失败: {e}")
            return 0

