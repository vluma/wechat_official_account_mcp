"""
微信 API 客户端 - 封装微信公众平台 API 调用
"""
import json
import logging
import os
import re
import httpx
from typing import Dict, Any, Optional, List, Union
from io import BytesIO

logger = logging.getLogger(__name__)

# 常量定义
BASE_URL = os.getenv('WECHAT_OFFICIAL_API_URL', 'https://api.weixin.qq.com')
MAX_IMAGE_SIZE = 1024 * 1024  # 1MB
JPEG_HEADER = bytes([0xFF, 0xD8, 0xFF])
PNG_HEADER = bytes([0x89, 0x50, 0x4E, 0x47])
GIF_HEADER = b'GIF89a'  # GIF89a格式
GIF_HEADER_87 = b'GIF87a'  # GIF87a格式
BMP_HEADER = b'BM'  # BMP格式
SUPPORTED_IMAGE_FORMATS = ['jpg', 'jpeg', 'png', 'gif', 'bmp']


class WechatApiError(Exception):
    """微信 API 错误异常"""
    def __init__(self, error_code: int, error_msg: str):
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"微信 API 错误: {error_code} - {error_msg}")


class WechatApiClient:
    """微信 API 客户端"""
    
    BASE_URL = BASE_URL
    
    def __init__(self, access_token: str):
        """
        初始化 API 客户端
        
        Args:
            access_token: Access Token
        """
        self.access_token = access_token
    
    @classmethod
    async def from_auth_manager(cls, auth_manager) -> 'WechatApiClient':
        """
        从认证管理器创建客户端（异步方法）
        
        Args:
            auth_manager: AuthManager 实例
            
        Returns:
            WechatApiClient 实例
        """
        token_info = await auth_manager.get_access_token()
        return cls(token_info['accessToken'])
    
    def _build_url(self, endpoint: str) -> str:
        """
        构建带 access_token 的 URL
        
        Args:
            endpoint: API 端点
            
        Returns:
            完整的 URL
        """
        url = f"{self.BASE_URL}{endpoint}"
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}access_token={self.access_token}"
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, 
                     files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送 HTTP 请求
        
        Args:
            method: HTTP 方法 (GET/POST)
            data: 请求数据
            files: 文件数据
            
        Returns:
            响应 JSON 数据
            
        Raises:
            WechatApiError: API 返回错误时
            Exception: 网络请求失败时
        """
        url = self._build_url(endpoint)
        
        try:
            async with httpx.AsyncClient() as session:
                if method.upper() == 'GET':
                    response = await session.get(url, params=data)
                    result = await self._parse_response(response)
                elif method.upper() == 'POST':
                    if files:
                        result = await self._post_with_files(session, url, data, files)
                    else:
                        result = await self._post_json(session, url, data)
                else:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")
                
                # 检查错误
                if 'errcode' in result and result['errcode'] != 0:
                    error_msg = result.get('errmsg', '未知错误')
                    error_code = result.get('errcode', -1)
                    raise WechatApiError(error_code, error_msg)
                
                return result
        
        except WechatApiError:
            raise
        except httpx.RequestError as e:
            raise Exception(f"网络请求失败: {str(e)}")
    
    async def _post_with_files(self, session: httpx.AsyncClient, url: str,
                               data: Optional[Dict[str, Any]], files: Dict[str, Any]) -> Dict[str, Any]:
        """POST 请求（带文件）"""
        # 准备表单数据
        form_data = data or {}
        # 准备文件数据
        file_data = {}
        for key, (content, filename) in files.items():
            file_data[key] = (filename, content)
        
        response = await session.post(url, data=form_data, files=file_data)
        return await self._parse_response(response)
    
    async def _post_json(self, session: httpx.AsyncClient, url: str,
                        data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """POST 请求（JSON 数据）"""
        if data:
            response = await session.post(url, json=data)
            return await self._parse_response(response)
        else:
            response = await session.post(url)
            return await self._parse_response(response)
    
    async def _parse_response(self, response: httpx.Response) -> Dict[str, Any]:
        """
        解析HTTP响应
        
        Args:
            response: httpx响应对象
            
        Returns:
            解析后的JSON数据
            
        Raises:
            Exception: 解析失败时
        """
        text = response.text
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if response.status != 200:
                raise Exception(f"HTTP错误 {response.status}: {text}")
            
            # 尝试提取JSON部分
            try:
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except (json.JSONDecodeError, AttributeError):
                pass
            
            content_type = response.headers.get('Content-Type', 'unknown')
            raise Exception(
                f"无法解析响应为JSON。状态码: {response.status}, "
                f"Content-Type: {content_type}, 响应内容: {text[:500]}"
            )
    
    def _validate_image_format(self, file_content: bytes, filename: Optional[str] = None) -> str:
        """
        验证图片格式并返回扩展名
        
        支持的格式：JPG/JPEG, PNG, GIF, BMP
        注意：微信公众号不支持SVG格式
        
        Args:
            file_content: 文件内容
            filename: 文件名（可选）
            
        Returns:
            文件扩展名
            
        Raises:
            ValueError: 格式不支持或文件无效时
        """
        if len(file_content) < 4:
            raise ValueError("文件内容无效")
        
        # 检查文件头
        is_jpeg = file_content[:3] == JPEG_HEADER
        is_png = file_content[:4] == PNG_HEADER
        is_gif = file_content[:6] == GIF_HEADER or file_content[:6] == GIF_HEADER_87
        is_bmp = file_content[:2] == BMP_HEADER
        
        if is_jpeg:
            return 'jpg'
        elif is_png:
            return 'png'
        elif is_gif:
            return 'gif'
        elif is_bmp:
            return 'bmp'
        elif filename:
            ext = filename.lower().split('.')[-1]
            # 检查是否为SVG（明确拒绝）
            if ext == 'svg':
                raise ValueError(
                    "SVG格式不支持。微信公众号仅支持 JPG/JPEG、PNG、GIF、BMP 格式。"
                    "请将SVG转换为PNG或JPG格式后再上传。"
                )
            if ext in SUPPORTED_IMAGE_FORMATS:
                return ext
            raise ValueError(
                f"不支持的图片格式: {ext}，仅支持 {', '.join(SUPPORTED_IMAGE_FORMATS)} 格式。"
                "注意：SVG格式不支持，请转换为PNG或JPG格式。"
            )
        else:
            raise ValueError(
                f"无法识别图片格式，仅支持 {', '.join(SUPPORTED_IMAGE_FORMATS)} 格式。"
                "注意：SVG格式不支持，请转换为PNG或JPG格式。"
            )
    
    async def upload_media(self, media_type: str, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        上传临时素材
        
        Args:
            media_type: 素材类型 (image/voice/video/thumb)
            file_content: 文件内容
            filename: 文件名
            
        Returns:
            上传结果
        """
        url = f"{self.BASE_URL}/cgi-bin/media/upload?access_token={self.access_token}&type={media_type}"
        
        # 使用 httpx.AsyncClient 处理异步文件上传
        async with httpx.AsyncClient() as session:
            response = await session.post(url, files={'media': (filename, file_content)})
            result = response.json()
        
        if 'errcode' in result and result['errcode'] != 0:
            error_msg = result.get('errmsg', '未知错误')
            error_code = result.get('errcode', -1)
            raise WechatApiError(error_code, error_msg)
        return result
    
    async def get_media(self, media_id: str) -> bytes:
        """
        获取临时素材
        
        Args:
            media_id: 素材ID
            
        Returns:
            素材内容（字节）
        """
        url = f"{self.BASE_URL}/cgi-bin/media/get?access_token={self.access_token}&media_id={media_id}"
        
        async with httpx.AsyncClient() as session:
            response = await session.get(url)
            content_type = response.headers.get('Content-Type', '')
            
            if 'application/json' in content_type:
                result = response.json()
                if 'errcode' in result:
                    error_msg = result.get('errmsg', '未知错误')
                    error_code = result.get('errcode', -1)
                    raise WechatApiError(error_code, error_msg)
            return response.content
    
    async def upload_permanent_media(self, media_type: str, file_content: bytes, 
                                    title: Optional[str] = None, 
                                    introduction: Optional[str] = None,
                                    filename: Optional[str] = None) -> Dict[str, Any]:
        """
        上传永久素材
        
        Args:
            media_type: 素材类型 (image/voice/video/thumb)
            file_content: 文件内容
            title: 视频标题（video 类型时必填）
            introduction: 视频描述（video 类型时可选）
            filename: 文件名（可选，用于确定文件类型）
            
        Returns:
            上传结果，包含 media_id 和 url（仅图片类型返回url）
        """
        endpoint = "/cgi-bin/material/add_material"
        url = f"{self.BASE_URL}{endpoint}?access_token={self.access_token}&type={media_type}"
        
        # 根据素材类型确定文件名和扩展名
        if media_type == 'image':
            # 验证图片格式并获取扩展名
            ext = self._validate_image_format(file_content, filename)
            if not filename:
                filename = f'image.{ext}'
            elif not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                # 如果文件名扩展名不正确，使用验证后的扩展名
                filename = f"{filename.rsplit('.', 1)[0]}.{ext}"
        elif media_type == 'thumb':
            # 缩略图也是图片格式
            ext = self._validate_image_format(file_content, filename)
            if not filename:
                filename = f'thumb.{ext}'
            elif not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                filename = f"{filename.rsplit('.', 1)[0]}.{ext}"
        elif media_type == 'voice':
            if not filename:
                filename = 'voice.mp3'
            elif not filename.lower().endswith(('.mp3', '.wma', '.wav', '.amr')):
                raise ValueError("语音素材仅支持 mp3, wma, wav, amr 格式")
        elif media_type == 'video':
            if not filename:
                filename = 'video.mp4'
            elif not filename.lower().endswith(('.mp4', '.avi', '.wmv', '.flv', '.mov', '.mkv')):
                raise ValueError("视频素材仅支持 mp4, avi, wmv, flv, mov, mkv 格式")
        
        # 使用正确的文件格式：元组 (filename, content)
        files = {'media': (filename, file_content)}
        data = {}
        
        if media_type == 'video':
            if not title:
                raise ValueError("上传视频素材时 title 是必需的")
            data['description'] = json.dumps({
                'title': title,
                'introduction': introduction or ''
            }, ensure_ascii=False)
        
        async with httpx.AsyncClient() as session:
            response = await session.post(url, files=files, data=data)
            result = response.json()
        
        if 'errcode' in result and result['errcode'] != 0:
            error_msg = result.get('errmsg', '未知错误')
            error_code = result.get('errcode', -1)
            raise WechatApiError(error_code, error_msg)
        return result
    
    async def get_permanent_media(self, media_id: str) -> Union[Dict[str, Any], bytes]:
        """
        获取永久素材
        
        Args:
            media_id: 素材ID
            
        Returns:
            图文/视频素材：返回字典（包含 news_item 或 title/description/down_url）
            其他类型素材：返回字节内容
        """
        url = f"{self.BASE_URL}/cgi-bin/material/get_material?access_token={self.access_token}"
        
        async with httpx.AsyncClient() as session:
            response = await session.post(url, json={'media_id': media_id})
            content_type = response.headers.get('Content-Type', '')
            
            if 'application/json' in content_type:
                result = response.json()
                if 'errcode' in result:
                    error_msg = result.get('errmsg', '未知错误')
                    error_code = result.get('errcode', -1)
                    raise WechatApiError(error_code, error_msg)
            
            return response.content
    
    async def delete_permanent_media(self, media_id: str) -> Dict[str, Any]:
        """
        删除永久素材
        
        Args:
            media_id: 要删除的素材media_id
            
        Returns:
            删除结果，包含 errcode 和 errmsg（errcode为0表示成功）
        """
        return await self._request('POST', '/cgi-bin/material/del_material', {
            'media_id': media_id
        })
    
    async def upload_img(self, file_content: bytes, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        上传图文消息内的图片
        
        Args:
            file_content: 图片文件内容（仅支持jpg/png格式，大小必须在1MB以下）
            filename: 文件名（可选，用于确定文件类型）
            
        Returns:
            上传结果，包含 url、errcode 和 errmsg（errcode为0表示成功）
        """
        # 验证文件大小
        if len(file_content) > MAX_IMAGE_SIZE:
            raise ValueError(
                f"图片大小超过限制：{len(file_content)} 字节，"
                f"最大允许 1MB ({MAX_IMAGE_SIZE} 字节)"
            )
        
        # 验证并获取文件扩展名
        ext = self._validate_image_format(file_content, filename)
        
        url = f"{self.BASE_URL}/cgi-bin/media/uploadimg?access_token={self.access_token}"
        files = {'media': (f'image.{ext}', file_content, f'image/{ext}')}
        
        async with httpx.AsyncClient() as session:
            response = await session.post(url, files=files)
            result = response.json()
        
        if 'errcode' in result and result['errcode'] != 0:
            error_msg = result.get('errmsg', '未知错误')
            error_code = result.get('errcode', -1)
            raise WechatApiError(error_code, error_msg)
        return result
    
    async def add_draft(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        创建草稿
        
        Args:
            articles: 文章列表
            
        Returns:
            创建结果
        """
        return await self._request('POST', '/cgi-bin/draft/add', {
            'articles': articles
        })
    
    async def get_draft(self, media_id: str) -> Dict[str, Any]:
        """
        获取草稿
        
        Args:
            media_id: 草稿ID
            
        Returns:
            草稿内容
        """
        return await self._request('POST', '/cgi-bin/draft/get', {
            'media_id': media_id
        })
    
    async def delete_draft(self, media_id: str) -> Dict[str, Any]:
        """
        删除草稿
        
        Args:
            media_id: 草稿ID
            
        Returns:
            删除结果
        """
        return await self._request('POST', '/cgi-bin/draft/delete', {
            'media_id': media_id
        })
    
    async def publish_draft(self, media_id: str) -> Dict[str, Any]:
        """
        提交发布草稿任务
        
        Args:
            media_id: 要发布的草稿的media_id
            
        Returns:
            发布结果，包含 errcode, errmsg, publish_id, msg_data_id
            注意：errcode为0仅表示发布任务提交成功，不代表发布已完成
            发布结果将通过事件推送通知（PUBLISHJOBFINISH事件）
        """
        return await self._request('POST', '/cgi-bin/freepublish/submit', {
            'media_id': media_id
        })
    
    async def get_published_article(self, article_id: str) -> Dict[str, Any]:
        """
        获取已发布的图文信息
        
        Args:
            article_id: 要获取的文章的article_id
            
        Returns:
            图文信息，包含 news_item 数组
        """
        return await self._request('POST', '/cgi-bin/freepublish/getarticle', {
            'article_id': article_id
        })
    
    async def draft_switch(self, checkonly: bool = False) -> Dict[str, Any]:
        """
        设置或查询草稿箱和发布功能的开关状态
        
        Args:
            checkonly: 是否仅检查状态（True表示仅查询，False表示设置开关）
            
        Returns:
            返回结果，包含 errcode, errmsg, is_open（仅成功时返回，0表示关闭，1表示开启）
        """
        endpoint = '/cgi-bin/draft/switch'
        url = f"{self.BASE_URL}{endpoint}"
        
        params = {'access_token': self.access_token}
        if checkonly:
            params['checkonly'] = '1'
        
        try:
            async with httpx.AsyncClient() as session:
                response = await session.post(url, params=params)
                result = await self._parse_response(response)
                
                if 'errcode' in result and result['errcode'] != 0:
                    error_msg = result.get('errmsg', '未知错误')
                    error_code = result.get('errcode', -1)
                    raise WechatApiError(error_code, error_msg)
                
                return result
        
        except WechatApiError:
            raise
        except httpx.RequestError as e:
            raise Exception(f"网络请求失败: {str(e)}")
