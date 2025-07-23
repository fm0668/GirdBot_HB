# dual_grid_bot/grid_executor.py

import asyncio
import logging
import math
import time
from decimal import Decimal
from typing import Dict, List, Optional, Any
from enum import Enum

from data_models import (
    GridExecutorConfig, GridLevel, GridLevelStates, TrackedOrder,
    TradeType, OrderType, PositionAction, OrderCandidate
)
from binance_connector import BinanceConnector


class RunnableStatus(Enum):
    """执行器运行状态"""
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    TERMINATED = "TERMINATED"


class CloseType(Enum):
    """关闭类型"""
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    MANUAL = "MANUAL"


class GridExecutor:
    """
    网格执行器 - 完整复刻Hummingbot的GridExecutor核心逻辑
    负责网格策略的计算和决策，通过BinanceConnector与交易所交互
    """
    
    def __init__(self, config: GridExecutorConfig, connector: BinanceConnector, 
                 update_interval: float = 1.0, max_retries: int = 10):
        """
        初始化网格执行器
        
        Args:
            config: 网格执行器配置
            connector: 币安连接器实例
            update_interval: 更新间隔(秒)
            max_retries: 最大重试次数
        """
        self.config = config
        self.connector = connector
        self.update_interval = update_interval
        self.max_retries = max_retries
        
        # 设置日志
        self.logger = logging.getLogger(f"GridExecutor_{config.side.value}_{config.id}")
        
        # 状态管理
        self._status = RunnableStatus.NOT_STARTED
        self.close_type: Optional[CloseType] = None
        self._current_retries = 0
        
        # 获取交易规则
        self.trading_rules = connector.get_trading_rules()
        
        # 生成网格层级
        self.grid_levels = self._generate_grid_levels()
        self.levels_by_state = {state: [] for state in GridLevelStates}
        
        # 订单追踪
        self._filled_orders = []

        # 网格参数
        self.step = Decimal("0")

        # 基础持仓数据
        self.position_size_base = Decimal("0")

        # 时间戳
        self.max_open_creation_timestamp = 0
        
        self.logger.info(f"网格执行器已初始化: {config.side.value} 方向, {len(self.grid_levels)} 个层级")
    
    @property
    def status(self) -> RunnableStatus:
        """获取执行器状态"""
        return self._status
    
    @property
    def is_active(self) -> bool:
        """检查执行器是否活跃"""
        return self._status in [RunnableStatus.RUNNING, RunnableStatus.NOT_STARTED, RunnableStatus.SHUTTING_DOWN]
    
    @property
    def is_trading(self) -> bool:
        """检查是否正在交易"""
        return self._status == RunnableStatus.RUNNING and self.position_size_base > Decimal("0")
    
    @property
    def mid_price(self) -> Decimal:
        """获取中间价格"""
        return self.connector.get_mid_price()
    
    def _generate_grid_levels(self) -> List[GridLevel]:
        """
        生成网格层级 - 完整复刻Hummingbot的逻辑
        """
        grid_levels = []
        
        # 获取当前价格
        price = self.connector.get_mid_price()
        if price <= 0:
            raise ValueError("网格生成时获取到无效的中间价格")
        
        # 获取最小名义价值和基础数量增量
        min_notional = max(
            self.config.min_order_amount_quote,
            self.trading_rules.min_notional_size
        )
        min_base_increment = self.trading_rules.min_base_amount_increment
        
        # 添加安全边际
        min_notional_with_margin = min_notional * Decimal("1.05")  # 5%安全边际
        
        # 计算满足最小名义价值和量化要求的最小基础数量
        min_base_amount = max(
            min_notional_with_margin / price,
            min_base_increment * Decimal(str(math.ceil(float(min_notional) / float(min_base_increment * price))))
        )
        
        # 量化最小基础数量
        min_base_amount = Decimal(
            str(math.ceil(float(min_base_amount) / float(min_base_increment)))) * min_base_increment
        
        # 验证量化后的数量满足最小名义价值
        min_quote_amount = min_base_amount * price
        
        # 计算网格范围和最小步长
        grid_range = (self.config.end_price - self.config.start_price) / self.config.start_price
        min_step_size = max(
            self.config.min_spread_between_orders,
            self.trading_rules.min_price_increment / price
        )
        
        # 基于总金额计算最大可能层级数
        max_possible_levels = int(self.config.total_amount_quote / min_quote_amount)
        
        if max_possible_levels == 0:
            # 如果连一个层级都创建不了，创建一个最小金额的层级
            n_levels = 1
            quote_amount_per_level = min_quote_amount
        else:
            # 计算最优层级数
            max_levels_by_step = int(grid_range / min_step_size)
            n_levels = min(max_possible_levels, max_levels_by_step)
            
            # 计算每层级的报价金额，确保量化后满足最小要求
            base_amount_per_level = max(
                min_base_amount,
                Decimal(str(math.floor(float(self.config.total_amount_quote / (price * n_levels)) /
                                       float(min_base_increment)))) * min_base_increment
            )
            quote_amount_per_level = base_amount_per_level * price
            
            # 如果总金额会被超出，调整层级数
            n_levels = min(n_levels, int(float(self.config.total_amount_quote) / float(quote_amount_per_level)))
        
        # 确保至少有一个层级
        n_levels = max(1, n_levels)
        
        # 生成价格层级，均匀分布
        if n_levels > 1:
            prices = self._linear_distribution(n_levels, float(self.config.start_price), float(self.config.end_price))
            self.step = grid_range / (n_levels - 1)
        else:
            # 单层级使用范围中点
            mid_price_range = (self.config.start_price + self.config.end_price) / 2
            prices = [mid_price_range]
            self.step = grid_range
        
        # 计算止盈
        take_profit_pct = self.config.take_profit_pct
        
        # 创建网格层级
        for i, level_price in enumerate(prices):
            grid_levels.append(
                GridLevel(
                    id=f"L{i}",
                    price=Decimal(str(level_price)),
                    amount_quote=quote_amount_per_level,
                    side=self.config.side,
                    order_type=self.config.order_type,
                    take_profit_pct=take_profit_pct,
                )
            )
        
        # 记录网格创建详情
        self.logger.info(
            f"已创建 {len(grid_levels)} 个网格层级，"
            f"每层级金额: {quote_amount_per_level:.4f} {self.config.trading_pair.split('/')[1]}，"
            f"基础数量: {(quote_amount_per_level / price):.8f} {self.config.trading_pair.split('/')[0]}"
        )
        
        return grid_levels
    
    def _linear_distribution(self, n: int, start: float, end: float) -> List[float]:
        """线性分布生成价格点"""
        if n == 1:
            return [(start + end) / 2]

        step = (end - start) / (n - 1)
        return [start + i * step for i in range(n)]

    async def control_task(self):
        """
        主控制循环 - 完整版本，包含订单状态监控和生命周期管理
        """
        try:
            # 1. 批量更新所有订单状态
            self.update_all_order_status()

            # 2. 更新网格层级状态
            self.update_grid_levels()

            # 3. 更新基础指标
            self.update_basic_metrics()

            if self._status == RunnableStatus.RUNNING:
                # 4. 获取需要创建和取消的订单 - 完全参考Hummingbot逻辑
                open_orders_to_create = self.get_open_orders_to_create()
                close_orders_to_create = self.get_close_orders_to_create()
                open_order_ids_to_cancel = self.get_open_order_ids_to_cancel()
                close_order_ids_to_cancel = self.get_close_order_ids_to_cancel()

                # 5. 创建开仓订单（逐个检查，避免超过限制）
                for level in open_orders_to_create:
                    # 在每次下单前重新检查当前挂单数量
                    current_open_orders = len([l for l in self.grid_levels
                                             if l.state == GridLevelStates.OPEN_ORDER_PLACED])

                    if current_open_orders >= self.config.max_open_orders:
                        self.logger.debug(f"已达到最大挂单数量 {self.config.max_open_orders}，停止下单")
                        break

                    await self.adjust_and_place_open_order(level)

                # 6. 创建平仓订单（止盈单）
                for level in close_orders_to_create:
                    await self.adjust_and_place_close_order(level)

                # 7. 取消开仓订单
                for order_id in open_order_ids_to_cancel:
                    await self.cancel_order(order_id)

                # 8. 取消平仓订单
                for order_id in close_order_ids_to_cancel:
                    await self.cancel_order(order_id)

            elif self._status == RunnableStatus.SHUTTING_DOWN:
                # 关闭状态下，确保所有订单都被取消和所有持仓都被平掉
                await self.cancel_open_orders()
                await self.close_open_positions()
                self._status = RunnableStatus.TERMINATED

        except Exception as e:
            self.logger.error(f"控制任务执行错误: {e}")
            self._current_retries += 1
            if self._current_retries >= self.max_retries:
                self.logger.error(f"达到最大重试次数 ({self.max_retries})，正在关闭")
                self._status = RunnableStatus.SHUTTING_DOWN

    def update_grid_levels(self):
        """更新网格层级状态"""
        self.levels_by_state = {state: [] for state in GridLevelStates}

        # 更新每个层级的状态
        for level in self.grid_levels:
            # 检查开仓订单状态
            if level.active_open_order:
                self._update_order_status(level.active_open_order)

            # 检查平仓订单状态
            if level.active_close_order:
                self._update_order_status(level.active_close_order)

            # 更新层级状态
            level.update_state()
            self.levels_by_state[level.state].append(level)

        # 处理完成的层级
        completed = self.levels_by_state[GridLevelStates.COMPLETE]
        for level in completed:
            if (level.active_open_order and level.active_open_order.is_filled and
                level.active_close_order and level.active_close_order.is_filled):

                # 计算这个层级的收益
                open_cost = level.active_open_order.executed_amount_quote
                close_revenue = level.active_close_order.executed_amount_quote
                fees = level.active_open_order.cum_fees_quote + level.active_close_order.cum_fees_quote
                net_profit = close_revenue - open_cost - fees
                profit_pct = (net_profit / open_cost * 100) if open_cost > 0 else Decimal("0")

                self.logger.info(f"网格层级 {level.id} 交易完成: "
                               f"开仓成本={open_cost:.4f}, 平仓收入={close_revenue:.4f}, "
                               f"手续费={fees:.4f}, 净收益={net_profit:.4f} ({profit_pct:.2f}%)")

                # 记录已完成的订单
                self._filled_orders.append(level.active_open_order)
                self._filled_orders.append(level.active_close_order)

                # 重置层级以便复用
                level.reset_level()

                self.logger.info(f"网格层级 {level.id} 已重置，可重新使用")

        # 处理失败的订单
        self._handle_failed_orders()

    def _handle_failed_orders(self):
        """处理失败或取消的订单"""
        try:
            for level in self.grid_levels:
                # 处理失败的开仓订单
                if (level.active_open_order and
                    level.active_open_order.is_done and
                    not level.active_open_order.is_filled):

                    order_status = level.active_open_order.status
                    self.logger.warning(f"层级 {level.id} 开仓订单失败: {level.active_open_order.order_id}, 状态: {order_status}")

                    # 重置开仓订单，使层级可以重新尝试
                    level.reset_open_order()

                # 处理失败的平仓订单
                if (level.active_close_order and
                    level.active_close_order.is_done and
                    not level.active_close_order.is_filled):

                    order_status = level.active_close_order.status
                    self.logger.warning(f"层级 {level.id} 平仓订单失败: {level.active_close_order.order_id}, 状态: {order_status}")

                    # 重置平仓订单，使层级可以重新尝试止盈
                    level.reset_close_order()

        except Exception as e:
            self.logger.error(f"处理失败订单时出错: {e}")

    def _update_order_status(self, tracked_order: TrackedOrder):
        """更新订单状态"""
        try:
            # 查询交易所获取订单最新状态
            order_status = self.connector.get_order_status(tracked_order.order_id)
            if order_status:
                # 更新订单状态
                old_status = tracked_order.is_filled
                success = tracked_order.update_from_exchange_data(order_status)

                if success and not old_status and tracked_order.is_filled:
                    # 订单从未成交变为已成交
                    self.logger.info(f"订单 {tracked_order.order_id} 已成交: "
                                   f"数量={tracked_order.executed_amount_base}, "
                                   f"金额={tracked_order.executed_amount_quote}")

        except Exception as e:
            self.logger.error(f"更新订单状态失败: {e}")

    def update_all_order_status(self):
        """批量更新所有活跃订单状态"""
        try:
            # 收集所有需要更新的订单ID
            order_ids = []
            order_map = {}

            for level in self.grid_levels:
                if level.active_open_order and not level.active_open_order.is_done:
                    order_ids.append(level.active_open_order.order_id)
                    order_map[level.active_open_order.order_id] = level.active_open_order

                if level.active_close_order and not level.active_close_order.is_done:
                    order_ids.append(level.active_close_order.order_id)
                    order_map[level.active_close_order.order_id] = level.active_close_order

            if not order_ids:
                return

            # 批量查询订单状态
            order_statuses = self.connector.get_multiple_order_status(order_ids)

            # 更新订单状态
            for order_id, order_data in order_statuses.items():
                if order_data and order_id in order_map:
                    tracked_order = order_map[order_id]
                    old_status = tracked_order.is_filled
                    success = tracked_order.update_from_exchange_data(order_data)

                    if success and not old_status and tracked_order.is_filled:
                        self.logger.info(f"订单 {order_id} 已成交: "
                                       f"数量={tracked_order.executed_amount_base}, "
                                       f"金额={tracked_order.executed_amount_quote}")

        except Exception as e:
            self.logger.error(f"批量更新订单状态失败: {e}")

    def update_basic_metrics(self):
        """更新基础指标"""
        try:
            # 更新持仓信息
            long_pos, short_pos = self.connector.get_positions()

            if self.config.side == TradeType.BUY:
                self.position_size_base = long_pos
            else:
                self.position_size_base = short_pos

        except Exception as e:
            self.logger.error(f"更新基础指标时出错: {e}")



    def get_open_orders_to_create(self) -> List[GridLevel]:
        """
        获取需要创建开仓订单的网格层级
        复刻Hummingbot的逻辑
        """
        # 检查当前开仓订单数量
        n_open_orders = len(self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED])

        # 检查订单频率限制
        current_time = time.time()
        if (self.max_open_creation_timestamp > current_time - self.config.order_frequency or
                n_open_orders >= self.config.max_open_orders):
            return []

        # 过滤激活边界内的层级
        levels_allowed = self._filter_levels_by_activation_bounds()

        # 按接近中间价排序
        sorted_levels_by_proximity = self._sort_levels_by_proximity(levels_allowed)

        # 返回可以创建的层级（限制数量）
        max_new_orders = self.config.max_open_orders - n_open_orders
        return sorted_levels_by_proximity[:max_new_orders]

    def get_close_orders_to_create(self) -> List[GridLevel]:
        """获取需要创建平仓订单的网格层级 - 完全参考Hummingbot逻辑"""
        close_orders_proposal = []
        open_orders_filled = self.levels_by_state[GridLevelStates.OPEN_ORDER_FILLED]

        for level in open_orders_filled:
            if self.config.activation_bounds:
                # 计算止盈价格到中间价的距离
                take_profit_price = self._get_take_profit_price(level)
                mid_price = self.connector.get_mid_price()
                tp_to_mid = abs(take_profit_price - mid_price) / mid_price

                if tp_to_mid < self.config.activation_bounds:
                    close_orders_proposal.append(level)
            else:
                close_orders_proposal.append(level)

        if close_orders_proposal:
            self.logger.debug(f"发现 {len(close_orders_proposal)} 个层级需要创建止盈订单")

        return close_orders_proposal

    def get_open_order_ids_to_cancel(self) -> List[str]:
        """获取需要取消的开仓订单ID - 完全参考Hummingbot逻辑"""
        if self.config.activation_bounds:
            open_orders_to_cancel = []
            open_orders_placed = [level.active_open_order for level in
                                self.levels_by_state[GridLevelStates.OPEN_ORDER_PLACED]]

            mid_price = self.connector.get_mid_price()

            for order in open_orders_placed:
                if order and order.price:
                    # 计算订单价格与中间价的距离百分比
                    distance_pct = abs(order.price - mid_price) / mid_price
                    if distance_pct > self.config.activation_bounds:
                        open_orders_to_cancel.append(order.order_id)
                        self.logger.debug(f"取消开仓订单 {order.order_id}: 距离={distance_pct:.3f} > 边界={self.config.activation_bounds:.3f}")

            return open_orders_to_cancel

        return []

    def get_close_order_ids_to_cancel(self) -> List[str]:
        """获取需要取消的平仓订单ID - 完全参考Hummingbot逻辑"""
        if self.config.activation_bounds:
            close_orders_to_cancel = []
            close_orders_placed = [level.active_close_order for level in
                                 self.levels_by_state[GridLevelStates.CLOSE_ORDER_PLACED]]

            mid_price = self.connector.get_mid_price()

            for order in close_orders_placed:
                if order and order.price:
                    # 计算订单价格与中间价的距离百分比
                    distance_to_mid = abs(order.price - mid_price) / mid_price
                    if distance_to_mid > self.config.activation_bounds:
                        close_orders_to_cancel.append(order.order_id)
                        self.logger.debug(f"取消平仓订单 {order.order_id}: 距离={distance_to_mid:.3f} > 边界={self.config.activation_bounds:.3f}")

            return close_orders_to_cancel

        return []



    def _filter_levels_by_activation_bounds(self) -> List[GridLevel]:
        """根据激活边界过滤层级 - 完全参考Hummingbot逻辑"""
        not_active_levels = self.levels_by_state[GridLevelStates.NOT_ACTIVE]

        if self.config.activation_bounds:
            mid_price = self.connector.get_mid_price()
            if self.config.side == TradeType.BUY:
                # 多头网格：价格高于下边界的层级可以激活
                activation_bounds_price = mid_price * (1 - self.config.activation_bounds)
                filtered_levels = [level for level in not_active_levels if level.price >= activation_bounds_price]
                self.logger.debug(f"多头网格激活边界: 中间价={mid_price:.5f}, 下边界={activation_bounds_price:.5f}, 过滤后层级数={len(filtered_levels)}")
            else:
                # 空头网格：价格低于上边界的层级可以激活
                activation_bounds_price = mid_price * (1 + self.config.activation_bounds)
                filtered_levels = [level for level in not_active_levels if level.price <= activation_bounds_price]
                self.logger.debug(f"空头网格激活边界: 中间价={mid_price:.5f}, 上边界={activation_bounds_price:.5f}, 过滤后层级数={len(filtered_levels)}")

            return filtered_levels

        return not_active_levels

    def _get_take_profit_price(self, level: GridLevel) -> Decimal:
        """计算止盈价格 - 参考Hummingbot逻辑"""
        if not level.active_open_order:
            return Decimal("0")

        open_price = level.active_open_order.price

        if self.config.side == TradeType.BUY:
            # 多头止盈：卖出价格高于开仓价格
            return open_price * (1 + level.take_profit_pct)
        else:
            # 空头止盈：买入价格低于开仓价格
            return open_price * (1 - level.take_profit_pct)

    def _sort_levels_by_proximity(self, levels: List[GridLevel]) -> List[GridLevel]:
        """按接近中间价排序层级"""
        current_price = self.connector.get_mid_price()
        return sorted(levels, key=lambda level: abs(level.price - current_price))



    async def adjust_and_place_open_order(self, level: GridLevel):
        """调整并下达开仓订单"""
        try:
            # 计算订单数量（基础资产）
            base_amount = level.amount_quote / level.price

            # 创建订单候选
            order_candidate = OrderCandidate(
                trading_pair=self.config.trading_pair,
                order_type=level.order_type,
                order_side=self.config.side,
                amount=base_amount,
                price=level.price,
                position_action=PositionAction.OPEN
            )

            # 下单
            order_result = self.connector.place_order(order_candidate)

            if order_result:
                # 创建追踪订单
                tracked_order = TrackedOrder(
                    order_id=order_result['id'],
                    order_type=level.order_type,
                    price=level.price,
                    amount=base_amount,
                    raw_info=order_result
                )

                # 更新层级状态
                level.active_open_order = tracked_order
                level.state = GridLevelStates.OPEN_ORDER_PLACED

                # 更新时间戳
                self.max_open_creation_timestamp = time.time()

                self.logger.info(f"层级 {level.id} 开仓订单已下达: {order_result['id']}")
            else:
                self.logger.error(f"层级 {level.id} 开仓订单下达失败")

        except Exception as e:
            self.logger.error(f"层级 {level.id} 下达开仓订单时出错: {e}")

    async def adjust_and_place_close_order(self, level: GridLevel):
        """调整并下达平仓订单（止盈单）- 完全参考Hummingbot逻辑"""
        try:
            if not level.active_open_order or not level.active_open_order.is_filled:
                self.logger.debug(f"层级 {level.id} 开仓订单未成交，跳过平仓订单创建")
                return

            # 如果已有平仓订单，先取消旧订单（参考Hummingbot逻辑）
            if level.active_close_order:
                self.logger.debug(f"层级 {level.id} 已有平仓订单 {level.active_close_order.order_id}，先取消")
                try:
                    await self.cancel_order(level.active_close_order.order_id)
                    level.active_close_order = None
                except Exception as e:
                    self.logger.warning(f"取消旧平仓订单失败: {e}")
                    # 继续执行，让新订单替换旧订单

            # 获取当前市场价格用于安全价差计算
            current_price = self.connector.get_mid_price()

            # 计算止盈价格
            if self.config.side == TradeType.BUY:
                # 多头止盈：卖出价格高于开仓价格
                base_close_price = level.active_open_order.price * (1 + level.take_profit_pct)
                close_side = TradeType.SELL

                # 应用安全价差，确保不会立即成交
                if base_close_price <= current_price:
                    close_price = current_price * (1 + self.config.safe_extra_spread)
                    self.logger.debug(f"调整多头止盈价格: {base_close_price:.5f} -> {close_price:.5f}")
                else:
                    close_price = base_close_price

            else:
                # 空头止盈：买入价格低于开仓价格
                base_close_price = level.active_open_order.price * (1 - level.take_profit_pct)
                close_side = TradeType.BUY

                # 应用安全价差，确保不会立即成交
                if base_close_price >= current_price:
                    close_price = current_price * (1 - self.config.safe_extra_spread)
                    self.logger.debug(f"调整空头止盈价格: {base_close_price:.5f} -> {close_price:.5f}")
                else:
                    close_price = base_close_price

            # 使用开仓订单的实际成交数量
            close_amount = level.active_open_order.executed_amount_base

            # 检查是否需要扣除手续费（如果手续费是用基础资产支付）
            if level.active_open_order.cum_fees_quote > 0:
                # 简化处理：如果有手续费，稍微减少平仓数量
                fee_adjustment = close_amount * Decimal("0.001")  # 0.1%的调整
                close_amount = close_amount - fee_adjustment
                self.logger.debug(f"调整平仓数量以考虑手续费: -{fee_adjustment:.8f}")

            # 量化价格和数量
            close_price = self.connector._quantize_price(close_price)
            close_amount = self.connector._quantize_amount(close_amount)

            # 检查最小订单要求
            if close_amount < self.trading_rules.min_order_size:
                self.logger.warning(f"层级 {level.id} 平仓数量 {close_amount} 小于最小订单大小 {self.trading_rules.min_order_size}")
                return

            # 创建平仓订单候选
            order_candidate = OrderCandidate(
                trading_pair=self.config.trading_pair,
                order_type=OrderType.LIMIT,
                order_side=close_side,
                amount=close_amount,
                price=close_price,
                position_action=PositionAction.CLOSE
            )

            # 下单
            order_result = self.connector.place_order(order_candidate)

            if order_result:
                # 创建追踪订单
                tracked_order = TrackedOrder(
                    order_id=order_result['id'],
                    order_type=OrderType.LIMIT,
                    price=close_price,
                    amount=close_amount,
                    raw_info=order_result
                )

                # 更新层级状态
                level.active_close_order = tracked_order
                level.state = GridLevelStates.CLOSE_ORDER_PLACED

                self.logger.info(f"层级 {level.id} 止盈订单已下达: {order_result['id']}, "
                               f"价格={close_price:.5f}, 数量={close_amount:.8f}, "
                               f"预期收益={level.take_profit_pct*100:.2f}%")
            else:
                self.logger.error(f"层级 {level.id} 止盈订单下达失败")

        except Exception as e:
            self.logger.error(f"层级 {level.id} 下达止盈订单时出错: {e}")

    async def cancel_order(self, order_id: str):
        """取消订单"""
        try:
            success = self.connector.cancel_order(order_id)
            if success:
                # 找到对应的层级并更新状态
                for level in self.grid_levels:
                    if (level.active_open_order and level.active_open_order.order_id == order_id):
                        level.reset_open_order()
                        self.logger.info(f"层级 {level.id} 的开仓订单 {order_id} 已取消")
                        break
                    elif (level.active_close_order and level.active_close_order.order_id == order_id):
                        level.reset_close_order()
                        self.logger.info(f"层级 {level.id} 的平仓订单 {order_id} 已取消")
                        break
            else:
                self.logger.error(f"取消订单 {order_id} 失败")

        except Exception as e:
            self.logger.error(f"取消订单 {order_id} 时出错: {e}")

    async def cancel_open_orders(self):
        """取消所有开仓订单"""
        try:
            success = self.connector.cancel_all_orders()
            if success:
                # 重置所有层级的订单状态
                for level in self.grid_levels:
                    if level.active_open_order and not level.active_open_order.is_filled:
                        level.reset_open_order()
                    if level.active_close_order and not level.active_close_order.is_filled:
                        level.reset_close_order()

                self.logger.info("所有开仓订单已取消")
            else:
                self.logger.error("取消所有订单失败")

        except Exception as e:
            self.logger.error(f"取消所有订单时出错: {e}")

    async def close_open_positions(self):
        """平掉所有开仓"""
        try:
            success = self.connector.close_all_positions()
            if success:
                self.logger.info("所有持仓已平仓")
            else:
                self.logger.error("平掉所有持仓失败")

        except Exception as e:
            self.logger.error(f"平掉所有持仓时出错: {e}")





    async def start(self):
        """启动网格执行器"""
        try:
            self.logger.info("正在启动网格执行器...")

            # 余额验证已在StrategyController层面完成，这里跳过
            # await self.validate_sufficient_balance()

            # 设置状态为运行中
            self._status = RunnableStatus.RUNNING

            # 启动控制任务 - 使用完整版本的control_task
            self.control_task_handle = asyncio.create_task(self._main_control_loop())

            self.logger.info("网格执行器启动成功")

        except Exception as e:
            self.logger.error(f"启动网格执行器时出错: {e}")
            self._status = RunnableStatus.TERMINATED
            raise

    async def _main_control_loop(self):
        """主控制循环 - 定期调用完整版本的control_task"""
        try:
            while self._status == RunnableStatus.RUNNING:
                await self.control_task()
                await asyncio.sleep(1)  # 每秒执行一次控制逻辑
        except Exception as e:
            self.logger.error(f"主控制循环异常: {e}")
            self._status = RunnableStatus.TERMINATED



    async def stop(self):
        """停止网格执行器"""
        try:
            self.logger.info("正在停止网格执行器...")

            # 设置状态为关闭中
            self._status = RunnableStatus.SHUTTING_DOWN

            # 停止控制任务
            if hasattr(self, 'control_task_handle') and self.control_task_handle:
                self.control_task_handle.cancel()
                try:
                    await self.control_task_handle
                except asyncio.CancelledError:
                    pass

            # 取消所有订单
            await self.cancel_open_orders()

            # 平掉所有持仓
            await self.close_open_positions()

            # 设置状态为已终止
            self._status = RunnableStatus.TERMINATED

            self.logger.info("网格执行器停止成功")

        except Exception as e:
            self.logger.error(f"停止网格执行器时出错: {e}")
            self._status = RunnableStatus.TERMINATED
            raise

    async def validate_sufficient_balance(self):
        """验证余额是否充足"""
        try:
            # 获取账户余额
            balance = self.connector.get_balance()
            available_balance = balance["free"]

            # 检查余额是否足够
            if available_balance < self.config.total_amount_quote:
                self.close_type = CloseType.INSUFFICIENT_BALANCE
                error_msg = f"余额不足: {available_balance} < {self.config.total_amount_quote}"
                self.logger.error(error_msg)
                raise ValueError(error_msg)

            self.logger.info(f"余额验证通过: {available_balance} >= {self.config.total_amount_quote}")

        except Exception as e:
            self.logger.error(f"余额验证失败: {e}")
            raise

    def get_status_info(self) -> Dict[str, Any]:
        """获取执行器状态信息"""
        return {
            "id": self.config.id,
            "side": self.config.side.value,
            "status": self._status.value,
            "close_type": self.close_type.value if self.close_type else None,
            "grid_levels": len(self.grid_levels),
            "levels_by_state": {
                state.value: len(levels) for state, levels in self.levels_by_state.items()
            },
            "position_size_base": float(self.position_size_base),
            "current_retries": self._current_retries,
            "max_retries": self.max_retries,
        }

    def is_healthy(self) -> bool:
        """检查执行器是否健康"""
        return (
            self._status in [RunnableStatus.RUNNING, RunnableStatus.NOT_STARTED] and
            self._current_retries < self.max_retries and
            self.connector.is_connected()
        )
