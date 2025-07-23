# dual_grid_bot/config.py

import os
from decimal import Decimal
from typing import Dict, Any
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ==============================================================================
# 双账户API配置
# ==============================================================================

# 账户A配置 (多头网格)
ACCOUNT_A_CONFIG = {
    "api_key": os.getenv("ACCOUNT_A_API_KEY", ""),  # 从环境变量读取
    "api_secret": os.getenv("ACCOUNT_A_API_SECRET", ""),  # 从环境变量读取
    "name": "Account_A_Long"  # 账户标识名称
}

# 账户B配置 (空头网格)
ACCOUNT_B_CONFIG = {
    "api_key": os.getenv("ACCOUNT_B_API_KEY", ""),  # 从环境变量读取
    "api_secret": os.getenv("ACCOUNT_B_API_SECRET", ""),  # 从环境变量读取
    "name": "Account_B_Short"  # 账户标识名称
}

# ==============================================================================
# 网格策略配置
# ==============================================================================

# 基础交易配置
TRADING_PAIR = "DOGE/USDC:USDC"  # 交易对
CONTRACT_TYPE = "USDC"  # 合约类型：USDT 或 USDC
LEVERAGE = 20  # 杠杆倍数

# 网格参数配置
GRID_CONFIG = {
    # 网格边界
    "start_price": Decimal("0.24800"),  # 网格起始价格
    "end_price": Decimal("0.28000"),    # 网格结束价格
    "total_amount_quote": Decimal("1000"),  # 总投入资金(USDC) - 调整为适合当前余额
    
    # 网格行为
    "max_open_orders": 5,  # 最大同时开仓订单数
    "min_spread_between_orders": Decimal("0.0005"),  # 订单间最小价差(0.05%)
    "min_order_amount_quote": Decimal("5"),  # 最小订单金额
    
    # 执行细节
    "order_frequency": 0,  # 两次下单之间的最小秒数 (0=无限制，与Hummingbot一致)
    "activation_bounds": None,  # 动态挂单的激活范围 (None=无限制，与Hummingbot一致)
    "safe_extra_spread": Decimal("0.0001"),  # 防止吃单的安全价差
    
    # 止盈配置
    "take_profit_pct": Decimal("0.001"),  # 每层网格的止盈百分比(0.1%)

    # 边界处理配置
    "boundary_stop_enabled": True,        # 是否启用边界停止功能
    "boundary_check_interval": 5,         # 边界检查间隔（秒）
}

# ==============================================================================
# 系统配置
# ==============================================================================

# 交易所配置
EXCHANGE_CONFIG = {
    "sandbox": False,  # 是否使用沙盒环境
    "timeout": 30000,  # API超时时间(毫秒)
    "rateLimit": 1200,  # API限速(毫秒)
    "enableRateLimit": True,  # 是否启用限速
}

# 风控配置
RISK_CONFIG = {
    "position_threshold": Decimal("500"),  # 持仓阈值
    "max_position_limit": Decimal("1000"),  # 最大持仓限制
    "order_timeout": 300,  # 订单超时时间(秒)
    "balance_check_interval": 60,  # 余额检查间隔(秒)
}

# 监控配置
MONITOR_CONFIG = {
    "update_interval": 1.0,  # 执行器更新间隔(秒)
    "sync_interval": 10,  # 状态同步间隔(秒)
    "heartbeat_interval": 30,  # 心跳检查间隔(秒)
    "max_retries": 3,  # 最大重试次数
}

# 日志配置
LOG_CONFIG = {
    "level": "INFO",  # 日志级别
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file_path": "logs/dual_grid_bot.log",  # 日志文件路径
    "max_file_size": 10 * 1024 * 1024,  # 最大文件大小(10MB)
    "backup_count": 5,  # 备份文件数量
}

# ==============================================================================
# 辅助函数
# ==============================================================================

def get_account_config(account_name: str) -> Dict[str, Any]:
    """获取指定账户的配置"""
    if account_name.upper() == "A":
        return ACCOUNT_A_CONFIG
    elif account_name.upper() == "B":
        return ACCOUNT_B_CONFIG
    else:
        raise ValueError(f"Unknown account name: {account_name}")

def validate_config() -> bool:
    """验证配置的有效性"""
    # 检查API密钥是否已设置
    if not ACCOUNT_A_CONFIG["api_key"] or not ACCOUNT_A_CONFIG["api_secret"]:
        raise ValueError("Account A API credentials not configured")
    
    if not ACCOUNT_B_CONFIG["api_key"] or not ACCOUNT_B_CONFIG["api_secret"]:
        raise ValueError("Account B API credentials not configured")
    
    # 检查网格参数
    if GRID_CONFIG["start_price"] >= GRID_CONFIG["end_price"]:
        raise ValueError("Start price must be less than end price")
    
    if GRID_CONFIG["total_amount_quote"] <= 0:
        raise ValueError("Total amount must be positive")
    
    if GRID_CONFIG["max_open_orders"] <= 0:
        raise ValueError("Max open orders must be positive")
    
    return True

# ==============================================================================
# 配置导出
# ==============================================================================

# 将所有配置合并为一个字典，方便导入使用
ALL_CONFIG = {
    "accounts": {
        "A": ACCOUNT_A_CONFIG,
        "B": ACCOUNT_B_CONFIG
    },
    "trading": {
        "pair": TRADING_PAIR,
        "contract_type": CONTRACT_TYPE,
        "leverage": LEVERAGE
    },
    "grid": GRID_CONFIG,
    "exchange": EXCHANGE_CONFIG,
    "risk": RISK_CONFIG,
    "monitor": MONITOR_CONFIG,
    "log": LOG_CONFIG
}
