"""
认证管理器 - 管理微信公众号认证配置和 Access Token
"""
import os
import json
import time
import logging
import httpx
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)
BASE_URL = os.getenv('WECHAT_OFFICIAL_API_URL', 'https://api.weixin.qq.com')


class AuthManager:
    """认证管理器"""
    
    def __init__(self, config_file: str = "data/auth_config.json"):
        """
        初始化认证管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config: Optional[Dict[str, Any]] = None
        self.token_cache: Optional[Dict[str, Any]] = None
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        config_dir = Path(self.config_file).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # 优先从环境变量读取配置
        app_id = os.getenv('WECHAT_APP_ID')
        app_secret = os.getenv('WECHAT_APP_SECRET')
        
        if app_id and app_secret:
            logger.info("从环境变量加载配置")
            self.config = {
                'app_id': app_id,
                'app_secret': app_secret
            }
            # 从配置文件加载 token 缓存（如果存在）
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.token_cache = data.get('token_cache')
                except Exception as e:
                    logger.warning(f"加载 token 缓存失败: {e}")
                    self.token_cache = None
            else:
                self.token_cache = None
            # 保存配置到文件
            self._save_config()
            return
        
        # 如果环境变量不存在，尝试从配置文件读取
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.config = data.get('config')
                    self.token_cache = data.get('token_cache')
                    
                    # 检查配置是否有效（不是占位符）
                    if self.config:
                        app_id = self.config.get('app_id', '')
                        app_secret = self.config.get('app_secret', '')
                        # 如果是占位符或无效配置，清空配置
                        if not app_id or not app_secret or 'placeholder' in app_id.lower() or 'placeholder' in app_secret.lower():
                            logger.warning("配置文件中的配置无效，已清空")
                            self.config = None
                            self.token_cache = None
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self.config = None
                self.token_cache = None
        else:
            self.config = None
            self.token_cache = None
    
    def _save_config(self):
        """保存配置"""
        config_dir = Path(self.config_file).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'config': self.config,
                    'token_cache': self.token_cache
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    def set_config(self, config: Dict[str, Any]):
        """
        设置配置
        
        Args:
            config: 配置字典，包含 appId, appSecret
        """
        # 转换键名为下划线格式
        self.config = {
            'app_id': config.get('appId') or config.get('app_id', ''),
            'app_secret': config.get('appSecret') or config.get('app_secret', '')
        }
        # 清除旧的 token 缓存
        self.token_cache = None
        self._save_config()
        logger.info("配置已保存")
    
    def get_config(self) -> Optional[Dict[str, Any]]:
        """
        获取配置
        
        Returns:
            配置字典，如果未配置则返回 None
        """
        return self.config
    
    async def get_access_token(self) -> Dict[str, Any]:
        """
        获取 Access Token
        
        Returns:
            包含 accessToken 和 expiresAt 的字典
        """
        # 检查缓存的 token 是否有效
        if self.token_cache:
            expires_at = self.token_cache.get('expiresAt', 0)
            # 提前5分钟刷新
            if time.time() * 1000 < expires_at - 5 * 60 * 1000:
                logger.info("使用缓存的 Access Token")
                return self.token_cache
        
        # 需要获取新的 token
        if not self.config or not self.config.get('app_id') or not self.config.get('app_secret'):
            raise ValueError("未配置 AppID 或 AppSecret，请先使用 configure 操作进行配置")
        
        logger.info("正在获取新的 Access Token...")
        return await self.refresh_access_token()
    
    async def refresh_access_token(self) -> Dict[str, Any]:
        """
        刷新 Access Token
        
        Returns:
            包含 accessToken 和 expiresAt 的字典
        """
        if not self.config or not self.config.get('app_id') or not self.config.get('app_secret'):
            raise ValueError("未配置 AppID 或 AppSecret，请先使用 configure 操作进行配置")
        
        app_id = self.config['app_id']
        app_secret = self.config['app_secret']
        
        url = f"{BASE_URL}/cgi-bin/token?grant_type=client_credential&appid={app_id}&secret={app_secret}"
        
        try:
            async with httpx.AsyncClient() as session:
                response = await session.get(url)
                data = response.json()
                
                if 'access_token' in data:
                    # 计算过期时间（微信 token 有效期 7200 秒）
                    expires_in = data.get('expires_in', 7200)
                    expires_at = int(time.time() * 1000) + expires_in * 1000
                    
                    self.token_cache = {
                        'accessToken': data['access_token'],
                        'expiresAt': expires_at
                    }
                    self._save_config()
                    logger.info("Access Token 获取成功")
                    return self.token_cache
                else:
                    error_msg = data.get('errmsg', '未知错误')
                    error_code = data.get('errcode', -1)
                    raise Exception(f"获取 Access Token 失败: {error_code} - {error_msg}")
        
        except httpx.RequestError as e:
            raise Exception(f"网络请求失败: {str(e)}")
        except Exception as e:
            logger.error(f"刷新 Access Token 失败: {e}")
            raise

