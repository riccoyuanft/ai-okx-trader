"""Logging configuration"""

import sys
import os
from datetime import datetime
from loguru import logger
from src.config.settings import settings


def _is_price_monitor(record):
    """判断是否为高频价格监控日志（不写入文件）"""
    msg = record["message"]
    return "💹 价格监控" in msg or "价格监控 |" in msg


def _not_price_monitor(record):
    """文件日志过滤器：排除高频价格监控"""
    return not _is_price_monitor(record)


def setup_logger():
    """Configure loguru logger
    
    - 控制台：全量输出（含价格监控）
    - 文件：排除高频价格监控，每次启动新文件，按100MB轮转
    """
    
    # Remove default handler
    logger.remove()
    
    # Console handler（全量输出）
    logger.add(
        sys.stdout,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # File handler（排除价格监控高频日志，每次启动新文件）
    log_dir = os.path.dirname(settings.log_file)
    os.makedirs(log_dir, exist_ok=True)
    startup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"ai_trader_{startup_time}.log")
    
    logger.add(
        log_filename,
        level=settings.log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        filter=_not_price_monitor,
        rotation="100 MB",
        retention="30 days",
        compression="zip",
    )
    
    logger.info(f"Logger initialized (file: {log_filename})")
    return logger
