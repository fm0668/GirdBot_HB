# dual_grid_bot/strategy_controller.py

import asyncio
import logging
import time
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime

from config import ALL_CONFIG, get_account_config, validate_config
from data_models import GridExecutorConfig, TradeType, OrderType
from binance_connector import BinanceConnector
from grid_executor import GridExecutor, RunnableStatus


class StrategyController:
    """
    策略控制器 - 双账户对冲网格策略的总指挥
    负责管理两个币安连接器和两个网格执行器的生命周期和同步
    """
    
    def __init__(self):
        """初始化策略控制器"""
        # 验证配置
        validate_config()
        
        # 设置日志
        self.logger = logging.getLogger("StrategyController")
        
        # 状态管理
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.stop_time: Optional[datetime] = None
        
        # 初始化连接器
        self.connector_a: Optional[BinanceConnector] = None
        self.connector_b: Optional[BinanceConnector] = None
        
        # 初始化执行器
        self.executor_long: Optional[GridExecutor] = None
        self.executor_short: Optional[GridExecutor] = None
        
        # 监控任务
        self.monitor_task: Optional[asyncio.Task] = None
        self.executor_tasks: Dict[str, asyncio.Task] = {}
        
        self.logger.info("StrategyController initialized")
    
    async def initialize_connectors(self):
        """初始化两个币安连接器"""
        try:
            self.logger.info("Initializing Binance connectors...")
            
            # 获取配置
            account_a_config = get_account_config("A")
            account_b_config = get_account_config("B")
            trading_config = ALL_CONFIG["trading"]
            exchange_config = ALL_CONFIG["exchange"]
            
            # 初始化账户A连接器（多头）
            self.connector_a = BinanceConnector(
                api_key=account_a_config["api_key"],
                api_secret=account_a_config["api_secret"],
                trading_pair=trading_config["pair"],
                contract_type=trading_config["contract_type"],
                leverage=trading_config["leverage"],
                sandbox=exchange_config["sandbox"],
                account_name=account_a_config["name"]
            )
            
            # 初始化账户B连接器（空头）
            self.connector_b = BinanceConnector(
                api_key=account_b_config["api_key"],
                api_secret=account_b_config["api_secret"],
                trading_pair=trading_config["pair"],
                contract_type=trading_config["contract_type"],
                leverage=trading_config["leverage"],
                sandbox=exchange_config["sandbox"],
                account_name=account_b_config["name"]
            )
            
            # 验证连接
            if not self.connector_a.is_connected():
                raise Exception("Failed to connect to Account A")
            
            if not self.connector_b.is_connected():
                raise Exception("Failed to connect to Account B")
            
            self.logger.info("Binance connectors initialized successfully")

            # 启动WebSocket连接以提高性能
            self.logger.info("Starting WebSocket connections...")
            await self.connector_a.start_websocket()
            await self.connector_b.start_websocket()
            self.logger.info("WebSocket connections started")

        except Exception as e:
            self.logger.error(f"Failed to initialize connectors: {e}")
            raise
    
    async def cleanup_accounts(self):
        """清理双账户：撤销所有挂单并平掉所有持仓"""
        try:
            self.logger.info("Starting account cleanup...")
            
            # 并行清理两个账户（注意：cleanup是同步方法）
            loop = asyncio.get_event_loop()
            results = await asyncio.gather(
                loop.run_in_executor(None, self.connector_a.cleanup),
                loop.run_in_executor(None, self.connector_b.cleanup),
                return_exceptions=True
            )
            
            # 检查清理结果
            success_a = results[0] if not isinstance(results[0], Exception) else False
            success_b = results[1] if not isinstance(results[1], Exception) else False
            
            if isinstance(results[0], Exception):
                self.logger.error(f"Account A cleanup failed: {results[0]}")
            
            if isinstance(results[1], Exception):
                self.logger.error(f"Account B cleanup failed: {results[1]}")
            
            if not (success_a and success_b):
                raise Exception("Account cleanup failed")
            
            self.logger.info("Account cleanup completed successfully")
            
        except Exception as e:
            self.logger.error(f"Account cleanup failed: {e}")
            raise
    
    async def balance_funds(self):
        """平衡两个账户的资金"""
        try:
            self.logger.info("Starting fund balancing...")
            
            # 获取两个账户的余额
            balance_a = self.connector_a.get_balance()
            balance_b = self.connector_b.get_balance()
            
            free_a = balance_a["free"]
            free_b = balance_b["free"]
            
            self.logger.info(f"Account A balance: {free_a}")
            self.logger.info(f"Account B balance: {free_b}")
            
            # 计算平均余额
            total_balance = free_a + free_b
            target_balance = total_balance / 2
            
            # 计算需要转移的金额
            diff = abs(free_a - free_b)
            transfer_amount = diff / 2
            
            # 如果差异很小，不需要转移
            if transfer_amount < Decimal("1"):  # 小于1 USDC的差异忽略
                self.logger.info("Fund balances are already balanced")
                return
            
            # 确定转移方向
            if free_a > free_b:
                # 从A转移到B
                self.logger.info(f"Need to transfer {transfer_amount} from A to B")
                # 注意：实际的资金划转需要根据币安API实现
                # 这里暂时记录日志，实际实现需要调用transfer_funds方法
                self.logger.warning("Fund transfer not implemented yet")
            else:
                # 从B转移到A
                self.logger.info(f"Need to transfer {transfer_amount} from B to A")
                self.logger.warning("Fund transfer not implemented yet")
            
            self.logger.info("Fund balancing completed")
            
        except Exception as e:
            self.logger.error(f"Fund balancing failed: {e}")
            raise
    
    async def initialize_executors(self):
        """初始化两个网格执行器"""
        try:
            self.logger.info("Initializing grid executors...")
            
            # 获取配置
            grid_config = ALL_CONFIG["grid"]
            trading_config = ALL_CONFIG["trading"]
            monitor_config = ALL_CONFIG["monitor"]
            
            # 创建多头网格执行器配置
            long_config = GridExecutorConfig(
                id="long_grid",
                timestamp=time.time(),
                trading_pair=trading_config["pair"],
                side=TradeType.BUY,
                start_price=grid_config["start_price"],
                end_price=grid_config["end_price"],
                total_amount_quote=grid_config["total_amount_quote"],
                max_open_orders=grid_config["max_open_orders"],
                min_spread_between_orders=grid_config["min_spread_between_orders"],
                min_order_amount_quote=grid_config["min_order_amount_quote"],
                order_type=OrderType.LIMIT,
                order_frequency=grid_config["order_frequency"],
                activation_bounds=grid_config["activation_bounds"],
                safe_extra_spread=grid_config["safe_extra_spread"],
                take_profit_pct=grid_config["take_profit_pct"],
                leverage=trading_config["leverage"]
            )
            
            # 创建空头网格执行器配置
            short_config = GridExecutorConfig(
                id="short_grid",
                timestamp=time.time(),
                trading_pair=trading_config["pair"],
                side=TradeType.SELL,
                start_price=grid_config["start_price"],
                end_price=grid_config["end_price"],
                total_amount_quote=grid_config["total_amount_quote"],
                max_open_orders=grid_config["max_open_orders"],
                min_spread_between_orders=grid_config["min_spread_between_orders"],
                min_order_amount_quote=grid_config["min_order_amount_quote"],
                order_type=OrderType.LIMIT,
                order_frequency=grid_config["order_frequency"],
                activation_bounds=grid_config["activation_bounds"],
                safe_extra_spread=grid_config["safe_extra_spread"],
                take_profit_pct=grid_config["take_profit_pct"],
                leverage=trading_config["leverage"]
            )
            
            # 创建执行器实例
            self.executor_long = GridExecutor(
                config=long_config,
                connector=self.connector_a,
                update_interval=monitor_config["update_interval"],
                max_retries=monitor_config["max_retries"]
            )
            
            self.executor_short = GridExecutor(
                config=short_config,
                connector=self.connector_b,
                update_interval=monitor_config["update_interval"],
                max_retries=monitor_config["max_retries"]
            )
            
            self.logger.info("Grid executors initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize executors: {e}")
            raise

    async def start(self):
        """启动双账户对冲网格策略"""
        try:
            self.logger.info("Starting dual account hedge grid strategy...")
            self.start_time = datetime.now()

            # 1. 初始化连接器
            await self.initialize_connectors()

            # 2. 清理账户
            await self.cleanup_accounts()

            # 3. 平衡资金
            await self.balance_funds()

            # 4. 初始化执行器
            await self.initialize_executors()

            # 5. 验证双账户余额
            await self.validate_dual_account_balance()

            # 6. 启动执行器
            await self.start_executors()

            # 7. 启动监控
            await self.start_monitoring()

            self.is_running = True
            self.logger.info("Dual account hedge grid strategy started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start strategy: {e}")
            await self.stop()
            raise

    async def validate_dual_account_balance(self):
        """验证双账户余额（考虑杠杆倍数）"""
        try:
            self.logger.info("Validating dual account balance with leverage...")

            # 获取两个账户的余额
            balance_a = self.connector_a.get_balance()
            balance_b = self.connector_b.get_balance()

            available_a = balance_a["free"]
            available_b = balance_b["free"]

            # 获取配置
            trading_config = ALL_CONFIG["trading"]
            grid_config = ALL_CONFIG["grid"]

            # 获取杠杆倍数
            leverage = trading_config["leverage"]

            # 计算名义价值（余额 × 杠杆）
            nominal_value_a = available_a * leverage
            nominal_value_b = available_b * leverage

            # 获取配置要求的资金
            required_amount = grid_config["total_amount_quote"]

            # 取两个账户中较小的名义价值
            min_nominal_value = min(nominal_value_a, nominal_value_b)

            self.logger.info(f"Account A: balance={available_a}, leverage={leverage}, nominal_value={nominal_value_a}")
            self.logger.info(f"Account B: balance={available_b}, leverage={leverage}, nominal_value={nominal_value_b}")
            self.logger.info(f"Required amount: {required_amount}")
            self.logger.info(f"Minimum nominal value: {min_nominal_value}")

            # 验证最小名义价值是否满足要求
            if min_nominal_value < required_amount:
                error_msg = f"名义价值不足: 最小名义价值 {min_nominal_value} < 要求 {required_amount}"
                self.logger.error(error_msg)
                self.logger.error(f"账户A名义价值: {nominal_value_a} (余额: {available_a} × 杠杆: {leverage})")
                self.logger.error(f"账户B名义价值: {nominal_value_b} (余额: {available_b} × 杠杆: {leverage})")
                raise ValueError(error_msg)

            self.logger.info(f"✅ 双账户余额验证通过: 最小名义价值 {min_nominal_value} >= 要求 {required_amount}")

        except Exception as e:
            self.logger.error(f"双账户余额验证失败: {e}")
            raise

    async def start_executors(self):
        """同步启动两个网格执行器"""
        try:
            self.logger.info("Starting grid executors...")

            # 并行启动两个执行器
            start_tasks = [
                self.executor_long.start(),
                self.executor_short.start()
            ]

            results = await asyncio.gather(*start_tasks, return_exceptions=True)

            # 检查启动结果
            if isinstance(results[0], Exception):
                self.logger.error(f"Long executor start failed: {results[0]}")
                raise results[0]

            if isinstance(results[1], Exception):
                self.logger.error(f"Short executor start failed: {results[1]}")
                raise results[1]

            # 创建执行器控制任务
            self.executor_tasks["long"] = asyncio.create_task(self._run_executor_loop(self.executor_long))
            self.executor_tasks["short"] = asyncio.create_task(self._run_executor_loop(self.executor_short))

            self.logger.info("Grid executors started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start executors: {e}")
            raise

    async def _run_executor_loop(self, executor: GridExecutor):
        """运行执行器的控制循环"""
        try:
            while executor.is_active and self.is_running:
                await executor.control_task()
                await asyncio.sleep(executor.update_interval)

        except Exception as e:
            self.logger.error(f"Executor loop error for {executor.config.id}: {e}")
            # 如果一个执行器出错，停止整个策略
            await self.stop()

    async def start_monitoring(self):
        """启动监控任务"""
        try:
            self.logger.info("Starting monitoring...")

            # 创建监控任务
            self.monitor_task = asyncio.create_task(self._monitor_loop())

            self.logger.info("Monitoring started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start monitoring: {e}")
            raise

    async def _monitor_loop(self):
        """监控循环"""
        try:
            monitor_config = ALL_CONFIG["monitor"]
            sync_interval = monitor_config["sync_interval"]
            heartbeat_interval = monitor_config["heartbeat_interval"]

            last_sync_time = 0
            last_heartbeat_time = 0

            while self.is_running:
                current_time = time.time()

                # 定期同步状态
                if current_time - last_sync_time >= sync_interval:
                    await self._sync_status()
                    last_sync_time = current_time

                # 定期心跳检查
                if current_time - last_heartbeat_time >= heartbeat_interval:
                    await self._heartbeat_check()
                    last_heartbeat_time = current_time

                # 检查执行器状态
                await self._check_executor_health()

                await asyncio.sleep(1)  # 每秒检查一次

        except Exception as e:
            self.logger.error(f"Monitor loop error: {e}")
            await self.stop()

    async def _sync_status(self):
        """同步状态"""
        try:
            # 更新连接器状态
            if self.connector_a:
                self.connector_a.update_order_status()
                self.connector_a.get_positions()

            if self.connector_b:
                self.connector_b.update_order_status()
                self.connector_b.get_positions()

            # 记录状态信息
            self._log_status()

        except Exception as e:
            self.logger.error(f"Status sync error: {e}")

    async def _heartbeat_check(self):
        """心跳检查"""
        try:
            # 检查连接器连接状态
            if self.connector_a and not self.connector_a.is_connected():
                self.logger.error("Account A connection lost")
                await self.stop()
                return

            if self.connector_b and not self.connector_b.is_connected():
                self.logger.error("Account B connection lost")
                await self.stop()
                return

            # 检查执行器健康状态
            if self.executor_long and not self.executor_long.is_healthy():
                self.logger.error("Long executor is unhealthy")
                await self.stop()
                return

            if self.executor_short and not self.executor_short.is_healthy():
                self.logger.error("Short executor is unhealthy")
                await self.stop()
                return

        except Exception as e:
            self.logger.error(f"Heartbeat check error: {e}")

    async def _check_executor_health(self):
        """检查执行器健康状态"""
        try:
            # 检查执行器是否因止损等原因停止
            if self.executor_long and self.executor_long.status == RunnableStatus.SHUTTING_DOWN:
                self.logger.warning("Long executor is shutting down, stopping strategy")
                await self.stop()
                return

            if self.executor_short and self.executor_short.status == RunnableStatus.SHUTTING_DOWN:
                self.logger.warning("Short executor is shutting down, stopping strategy")
                await self.stop()
                return

            # 检查执行器任务是否完成
            for name, task in self.executor_tasks.items():
                if task.done():
                    self.logger.warning(f"Executor task {name} completed unexpectedly")
                    await self.stop()
                    return

        except Exception as e:
            self.logger.error(f"Executor health check error: {e}")

    def _log_status(self):
        """记录状态信息"""
        try:
            if self.executor_long and self.executor_short:
                long_status = self.executor_long.get_status_info()
                short_status = self.executor_short.get_status_info()

                # 获取连接状态
                conn_a_status = self.connector_a.is_connected() if self.connector_a else False
                conn_b_status = self.connector_b.is_connected() if self.connector_b else False

                # 获取详细连接信息
                conn_a_details = self.connector_a.get_connection_status() if self.connector_a else {}
                conn_b_details = self.connector_b.get_connection_status() if self.connector_b else {}

                self.logger.info(
                    f"Strategy Status - "
                    f"Long: {long_status['status']} (Position: {long_status['position_size_base']:.2f}), "
                    f"Short: {short_status['status']} (Position: {short_status['position_size_base']:.2f}), "
                    f"Grid Levels: {long_status['grid_levels']}, "
                    f"Connections: A={conn_a_status}, B={conn_b_status}"
                )

                # 如果连接不健康，记录详细信息
                if not conn_a_status:
                    self.logger.warning(f"Account A WebSocket连接异常: {conn_a_details}")
                if not conn_b_status:
                    self.logger.warning(f"Account B WebSocket连接异常: {conn_b_details}")

        except Exception as e:
            self.logger.error(f"Status logging error: {e}")

    async def stop(self):
        """停止双账户对冲网格策略"""
        try:
            self.logger.info("Stopping dual account hedge grid strategy...")
            self.is_running = False
            self.stop_time = datetime.now()

            # 1. 停止监控任务
            if self.monitor_task and not self.monitor_task.done():
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass

            # 2. 停止执行器任务
            for name, task in self.executor_tasks.items():
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            # 3. 停止执行器
            await self.stop_executors()

            # 4. 最终清理账户
            await self.final_cleanup()

            # 5. 验证清理结果
            await self.verify_final_cleanup()

            self.logger.info("Dual account hedge grid strategy stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping strategy: {e}")
            # 即使出错也要尝试清理
            try:
                await self.emergency_cleanup()
            except Exception as cleanup_error:
                self.logger.error(f"Emergency cleanup failed: {cleanup_error}")

    async def stop_executors(self):
        """同步停止两个网格执行器"""
        try:
            self.logger.info("Stopping grid executors...")

            stop_tasks = []

            if self.executor_long:
                stop_tasks.append(self.executor_long.stop())

            if self.executor_short:
                stop_tasks.append(self.executor_short.stop())

            if stop_tasks:
                results = await asyncio.gather(*stop_tasks, return_exceptions=True)

                # 检查停止结果
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        executor_name = "long" if i == 0 else "short"
                        self.logger.error(f"{executor_name} executor stop failed: {result}")

            self.logger.info("Grid executors stopped")

        except Exception as e:
            self.logger.error(f"Failed to stop executors: {e}")

    async def final_cleanup(self):
        """最终清理账户"""
        try:
            self.logger.info("Performing final cleanup...")

            cleanup_tasks = []

            if self.connector_a:
                loop = asyncio.get_event_loop()
                cleanup_tasks.append(loop.run_in_executor(None, self.connector_a.cleanup))

            if self.connector_b:
                loop = asyncio.get_event_loop()
                cleanup_tasks.append(loop.run_in_executor(None, self.connector_b.cleanup))

            if cleanup_tasks:
                results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)

                # 检查清理结果
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        account_name = "A" if i == 0 else "B"
                        self.logger.error(f"Account {account_name} final cleanup failed: {result}")

            self.logger.info("Final cleanup completed")

        except Exception as e:
            self.logger.error(f"Final cleanup failed: {e}")

    async def verify_final_cleanup(self):
        """验证最终清理结果"""
        try:
            self.logger.info("Verifying final cleanup...")

            verification_tasks = []

            if self.connector_a:
                loop = asyncio.get_event_loop()
                verification_tasks.append(loop.run_in_executor(None, self.connector_a.verify_cleanup))

            if self.connector_b:
                loop = asyncio.get_event_loop()
                verification_tasks.append(loop.run_in_executor(None, self.connector_b.verify_cleanup))

            if verification_tasks:
                results = await asyncio.gather(*verification_tasks, return_exceptions=True)

                # 检查验证结果
                all_verified = True
                for i, result in enumerate(results):
                    if isinstance(result, Exception) or not result:
                        account_name = "A" if i == 0 else "B"
                        self.logger.error(f"Account {account_name} cleanup verification failed")
                        all_verified = False

                if all_verified:
                    self.logger.info("Final cleanup verification passed")
                else:
                    self.logger.warning("Final cleanup verification failed")

        except Exception as e:
            self.logger.error(f"Cleanup verification failed: {e}")

    async def emergency_cleanup(self):
        """紧急清理"""
        try:
            self.logger.info("Performing emergency cleanup...")

            # 强制取消所有订单和平掉所有持仓
            if self.connector_a:
                try:
                    self.connector_a.cancel_all_orders()
                    self.connector_a.close_all_positions()
                except Exception as e:
                    self.logger.error(f"Emergency cleanup Account A failed: {e}")

            if self.connector_b:
                try:
                    self.connector_b.cancel_all_orders()
                    self.connector_b.close_all_positions()
                except Exception as e:
                    self.logger.error(f"Emergency cleanup Account B failed: {e}")

            self.logger.info("Emergency cleanup completed")

        except Exception as e:
            self.logger.error(f"Emergency cleanup failed: {e}")

    def get_strategy_status(self) -> Dict[str, Any]:
        """获取策略状态信息"""
        try:
            status = {
                "is_running": self.is_running,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "stop_time": self.stop_time.isoformat() if self.stop_time else None,
                "uptime": str(datetime.now() - self.start_time) if self.start_time else None,
                "connectors": {
                    "account_a": self.connector_a.get_account_info() if self.connector_a else None,
                    "account_b": self.connector_b.get_account_info() if self.connector_b else None,
                },
                "executors": {
                    "long": self.executor_long.get_status_info() if self.executor_long else None,
                    "short": self.executor_short.get_status_info() if self.executor_short else None,
                },
                "tasks": {
                    "monitor_running": self.monitor_task and not self.monitor_task.done() if self.monitor_task else False,
                    "executor_tasks": {
                        name: not task.done() for name, task in self.executor_tasks.items()
                    }
                }
            }

            return status

        except Exception as e:
            self.logger.error(f"Error getting strategy status: {e}")
            return {"error": str(e)}

    def is_healthy(self) -> bool:
        """检查策略是否健康"""
        try:
            if not self.is_running:
                return False

            # 检查连接器
            if not (self.connector_a and self.connector_a.is_connected()):
                return False

            if not (self.connector_b and self.connector_b.is_connected()):
                return False

            # 检查执行器
            if not (self.executor_long and self.executor_long.is_healthy()):
                return False

            if not (self.executor_short and self.executor_short.is_healthy()):
                return False

            # 检查任务
            if self.monitor_task and self.monitor_task.done():
                return False

            for task in self.executor_tasks.values():
                if task.done():
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Health check error: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            self.logger.info("Starting cleanup...")

            # 停止网格执行器
            if hasattr(self, 'executor_a') and self.executor_a:
                await self.executor_a.stop()

            if hasattr(self, 'executor_b') and self.executor_b:
                await self.executor_b.stop()

            # 清理账户：撤销挂单并平仓
            self.logger.info("Cleaning up accounts...")
            await self.cleanup_accounts()

            # 停止WebSocket连接
            if hasattr(self, 'connector_a') and self.connector_a:
                await self.connector_a.stop_websocket()

            if hasattr(self, 'connector_b') and self.connector_b:
                await self.connector_b.stop_websocket()

            self.logger.info("Cleanup completed")

        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")
