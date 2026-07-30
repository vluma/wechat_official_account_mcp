#!/usr/bin/env python3
"""
微信公众号 MCP 服务器入口文件 (FastMCP 2.0 版本)
支持多种传输模式：stdio、http、sse
"""
import logging
import os
import sys
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)


def _perform_startup_sync():
    """
    启动时执行 S3 同步 - 仅从远端下载到本地
    """
    import asyncio

    # 检查是否启用了远程存储
    remote_enabled = os.getenv('STORAGE_REMOTE_ENABLE', 'false').lower() == 'true'
    if not remote_enabled:
        logger.debug("远程存储未启用，跳过启动同步")
        return

    logger.info("启动时执行 S3 同步（从远端下载到本地）...")

    try:
        from shared.storage.storage_manager import StorageManager

        # 获取存储管理器实例
        storage_manager = StorageManager()

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 从 S3 同步到本地
            from_remote_result = loop.run_until_complete(storage_manager.sync_from_remote())
            logger.info(f"S3 到本地同步结果: {from_remote_result}")
            logger.info("启动 S3 同步完成")

        finally:
            # 关闭事件循环
            loop.close()

    except Exception as e:
        logger.error(f"启动 S3 同步失败: {e}", exc_info=True)


def main():
    """主函数"""
    try:
        # 添加项目根目录到 Python 路径
        script_dir = Path(__file__).parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))

        # 加载环境变量
        from dotenv import load_dotenv
        env_file = script_dir / '.env'
        if env_file.exists():
            load_dotenv(env_file)

        # 从环境变量获取日志级别
        log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR
        }
        log_level = log_level_map.get(log_level_str, logging.INFO)

        # 重新配置日志级别
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(sys.stderr)],
            force=True  # 强制重新配置
        )
        logger = logging.getLogger(__name__)

        if env_file.exists():
            logger.info(f"已加载环境变量文件: {env_file}")
        else:
            logger.warning(f"未找到环境变量文件，可能已在宿主机加载: {env_file}")

        # 确保数据目录存在
        data_dir = script_dir / 'data'
        data_dir.mkdir(exist_ok=True)

        # 设置日志目录
        logs_dir = script_dir / 'logs'
        logs_dir.mkdir(exist_ok=True)

        # 配置日志到文件
        log_file = logs_dir / 'mcp_server.log'
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logging.getLogger().addHandler(file_handler)

        logger.info(f"日志级别设置为: {log_level_str}")
        logger.info("微信公众号 MCP 服务器启动中...")

        # 启动时执行 S3 同步（仅从远端下载到本地）
        _perform_startup_sync()

        # 检查微信消息服务器启动开关
        wechat_server_enable = os.getenv('WECHAT_MSG_SERVER_ENABLE', 'true').strip().lower() == 'true'

        if wechat_server_enable:
            # 启动Web服务器 - 使用统一的WECHAT_MSG_SERVER_PORT
            static_page_port = int(os.getenv('WECHAT_MSG_SERVER_PORT', '3004'))
            try:
                from shared.utils.web_server import start_static_page_server
                from tools.static_pages import StaticPageManager

                # 获取正确的路径
                script_dir = Path(__file__).parent
                storage_dir = str(script_dir / 'data' / 'static_pages')
                db_file = str(script_dir / 'data' / 'storage.db')

                # 初始化Web页面管理器
                static_page_manager = StaticPageManager(storage_dir=storage_dir, db_file=db_file)

                logger.info(f"启动Web服务器，端口: {static_page_port}")
                success = start_static_page_server(static_page_port, static_page_manager=static_page_manager)
                if success:
                    logger.info(f"Web服务器启动成功")
                    logger.info(f"访问地址: http://localhost:{static_page_port}")
                else:
                    logger.warning("Web服务器启动失败")
            except Exception as e:
                logger.warning(f"Web服务器启动异常: {e}")
                logger.exception(e)
        else:
            logger.info("微信消息服务器已禁用 (WECHAT_MSG_SERVER_ENABLE=false)")

        # 检查MCP服务器启动开关
        mcp_enable = os.getenv('MCP_ENABLE', 'true').strip().lower() == 'true'

        if mcp_enable:
            # 直接导入并运行 MCP 服务器
            logger.info("启动 MCP 服务器...")
            try:
                import mcp_server
                mcp_server.main()
            except Exception as e:
                logger.error(f"MCP 服务器启动失败: {e}")
                sys.exit(1)
        else:
            logger.info("MCP服务器已禁用 (MCP_ENABLE=false)")
            logger.info("所有已启用的服务器启动完成")

    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务器...")
    except Exception as e:
        logger.error(f"MCP 服务器启动异常: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
