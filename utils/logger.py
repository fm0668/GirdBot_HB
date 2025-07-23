# dual_grid_bot/utils/logger.py

import logging
import logging.handlers
import os
from datetime import datetime
from typing import Optional

from config import LOG_CONFIG


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_file_size: Optional[int] = None,
    backup_count: Optional[int] = None,
    format_string: Optional[str] = None
) -> logging.Logger:
    """
    设置日志配置
    
    Args:
        level: 日志级别
        log_file: 日志文件路径
        max_file_size: 最大文件大小（字节）
        backup_count: 备份文件数量
        format_string: 日志格式字符串
    
    Returns:
        配置好的根日志器
    """
    # 使用配置文件中的默认值
    level = level or LOG_CONFIG["level"]
    log_file = log_file or LOG_CONFIG["file_path"]
    max_file_size = max_file_size or LOG_CONFIG["max_file_size"]
    backup_count = backup_count or LOG_CONFIG["backup_count"]
    format_string = format_string or LOG_CONFIG["format"]
    
    # 创建日志目录
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # 创建格式化器
    formatter = logging.Formatter(format_string)
    
    # 获取根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper()))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 创建文件处理器（带轮转）
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 记录启动信息
    root_logger.info("=" * 80)
    root_logger.info(f"Dual Grid Bot logging initialized at {datetime.now()}")
    root_logger.info(f"Log level: {level}")
    root_logger.info(f"Log file: {log_file}")
    root_logger.info("=" * 80)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器
    
    Args:
        name: 日志器名称
    
    Returns:
        日志器实例
    """
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, message: str, exc_info: bool = True):
    """
    记录异常信息
    
    Args:
        logger: 日志器实例
        message: 错误消息
        exc_info: 是否包含异常堆栈信息
    """
    logger.error(message, exc_info=exc_info)


def log_performance(logger: logging.Logger, operation: str, duration: float):
    """
    记录性能信息
    
    Args:
        logger: 日志器实例
        operation: 操作名称
        duration: 持续时间（秒）
    """
    logger.info(f"Performance: {operation} took {duration:.3f} seconds")


class LoggerMixin:
    """
    日志器混入类，为其他类提供日志功能
    """
    
    @property
    def logger(self) -> logging.Logger:
        """获取当前类的日志器"""
        return get_logger(self.__class__.__name__)
    
    def log_info(self, message: str):
        """记录信息日志"""
        self.logger.info(message)
    
    def log_warning(self, message: str):
        """记录警告日志"""
        self.logger.warning(message)
    
    def log_error(self, message: str, exc_info: bool = False):
        """记录错误日志"""
        self.logger.error(message, exc_info=exc_info)
    
    def log_debug(self, message: str):
        """记录调试日志"""
        self.logger.debug(message)
    
    def log_exception(self, message: str):
        """记录异常日志"""
        log_exception(self.logger, message)


# 预定义的日志器
MAIN_LOGGER = "DualGridBot.Main"
STRATEGY_LOGGER = "DualGridBot.Strategy"
CONNECTOR_LOGGER = "DualGridBot.Connector"
EXECUTOR_LOGGER = "DualGridBot.Executor"


def get_main_logger() -> logging.Logger:
    """获取主日志器"""
    return get_logger(MAIN_LOGGER)


def get_strategy_logger() -> logging.Logger:
    """获取策略日志器"""
    return get_logger(STRATEGY_LOGGER)


def get_connector_logger() -> logging.Logger:
    """获取连接器日志器"""
    return get_logger(CONNECTOR_LOGGER)


def get_executor_logger() -> logging.Logger:
    """获取执行器日志器"""
    return get_logger(EXECUTOR_LOGGER)
