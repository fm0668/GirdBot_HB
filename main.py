#!/usr/bin/env python3
"""
双账户对冲网格策略交易机器人
基于Hummingbot网格策略的双账户对冲交易机器人
"""

import asyncio
import signal
import sys
import time
from typing import Optional

from strategy_controller import StrategyController
from utils.logger import setup_logging, get_main_logger
from config import validate_config

# 设置全局日志
logger = get_main_logger()


class DualGridBot:
    """双账户对冲网格策略机器人主类"""
    
    def __init__(self):
        """初始化机器人"""
        # 设置日志
        setup_logging()
        self.logger = get_main_logger()
        
        # 策略控制器
        self.controller: Optional[StrategyController] = None
        
        # 运行状态
        self.is_running = False
        self.stop_signal = False
        self.cleanup_completed = False
        
        self.logger.info("DualGridBot initialized")
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"收到停止信号 {signum}，开始优雅停止...")
            self.stop_signal = True
            # 通知策略控制器停止
            if self.controller:
                self.controller.stop_signal = True

        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # 终止信号
        if hasattr(signal, 'SIGBREAK'):  # Windows
            signal.signal(signal.SIGBREAK, signal_handler)
    
    async def startup_cleanup(self):
        """启动时清理账户"""
        self.logger.info("=" * 60)
        self.logger.info("策略启动前清理账户...")
        self.logger.info("=" * 60)

        try:
            # 导入手动清理功能
            from manual_cleanup import manual_cleanup

            # 执行清理
            cleanup_success = await manual_cleanup()

            if cleanup_success:
                self.logger.info("✅ 启动前账户清理成功")
            else:
                self.logger.warning("⚠️ 启动前账户清理不完整，但继续运行")

            # 等待一段时间确保清理完成
            await asyncio.sleep(3)

        except Exception as e:
            self.logger.error(f"❌ 启动前账户清理失败: {e}")
            # 不抛出异常，允许继续运行
            self.logger.warning("继续启动策略，但建议手动检查账户状态")
    
    async def graceful_shutdown(self):
        """优雅停止"""
        if self.cleanup_completed:
            return

        self.logger.info("=" * 60)
        self.logger.info("开始优雅停止策略...")
        self.logger.info("=" * 60)

        try:
            if self.controller:
                # 执行账户清理
                await self.controller.cleanup()
                self.logger.info("✅ 优雅停止完成：所有订单已处理")
            
            self.cleanup_completed = True

        except Exception as e:
            self.logger.error(f"❌ 优雅停止过程中发生错误: {e}")
            self.cleanup_completed = True
    
    async def run(self):
        """启动机器人"""
        # 设置信号处理器
        self.setup_signal_handlers()
        
        # 验证配置
        self.logger.info("Validating configuration...")
        validate_config()
        self.logger.info("Configuration validation passed")
        
        # 创建策略控制器
        self.logger.info("Creating strategy controller...")
        self.controller = StrategyController()
        
        # 启动前清理账户
        await self.startup_cleanup()
        
        self.logger.info("=" * 60)
        self.logger.info("🚀 双账户对冲网格策略正式启动")
        self.logger.info("=" * 60)
        
        try:
            # 启动策略控制器
            strategy_task = asyncio.create_task(self.controller.start())
            
            self.is_running = True
            
            # 监控停止信号
            while not self.stop_signal and self.is_running:
                await asyncio.sleep(1)
            
            # 收到停止信号，优雅关闭
            self.logger.info("收到停止信号，正在优雅关闭...")
            
            # 停止策略控制器
            if self.controller:
                await self.controller.stop()
            
            # 取消任务
            strategy_task.cancel()
            
            try:
                await asyncio.gather(strategy_task, return_exceptions=True)
            except asyncio.CancelledError:
                self.logger.info("所有任务已取消")
                
        except Exception as e:
            if not self.stop_signal:
                self.logger.error(f"策略运行异常: {e}")
                raise
        finally:
            # 确保优雅停止
            await self.graceful_shutdown()


async def main():
    """主程序入口"""
    bot = None
    try:
        # 创建并启动机器人
        bot = DualGridBot()
        await bot.run()

    except KeyboardInterrupt:
        logger.info("程序被用户中断 (Ctrl+C)")
        if bot:
            bot.stop_signal = True
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        if bot:
            bot.stop_signal = True
        raise
    finally:
        if bot and not bot.cleanup_completed:
            logger.info("执行最终清理...")
            await bot.graceful_shutdown()


if __name__ == "__main__":
    # 检查Python版本
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required")
        sys.exit(1)
    
    # 显示启动信息
    print("=" * 60)
    print("  Dual Account Hedge Grid Trading Bot")
    print("  Version: 1.0.0")
    print("  Author: AI Assistant")
    print("=" * 60)
    print()
    
    # 运行机器人
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    except Exception as e:
        print(f"Program failed: {e}")
        sys.exit(1)
