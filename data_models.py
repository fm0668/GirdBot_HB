# dual_grid_bot/data_models.py

from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# 基础枚举类型 (从Hummingbot解耦)
# ==============================================================================
class TradeType(Enum):
    """
    BUY 和 SELL 定义了交易方向.
    """
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """
    LIMIT, LIMIT_MAKER, 和 MARKET 定义了订单类型.
    """
    LIMIT = "LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"
    MARKET = "MARKET"

    def is_limit_type(self) -> bool:
        return self in [OrderType.LIMIT, OrderType.LIMIT_MAKER]


class PositionAction(Enum):
    """
    定义仓位操作是开仓还是平仓.
    """
    OPEN = "OPEN"
    CLOSE = "CLOSE"


# ==============================================================================
# 网格执行器 (GridExecutor) 核心数据模型
# ==============================================================================

class GridExecutorConfig(BaseModel):
    """
    网格执行器的配置模型，从Hummingbot版本中解耦和简化。
    移除了对ExecutorConfigBase和TripleBarrierConfig的直接依赖，专注于核心网格参数。
    """
    # 身份标识
    id: str  # 唯一执行器ID
    timestamp: float  # 创建时的时间戳

    # 市场与交易对
    trading_pair: str
    side: TradeType  # 'BUY' for long grid, 'SELL' for short grid

    # 网格边界与资金
    start_price: Decimal
    end_price: Decimal
    total_amount_quote: Decimal

    # 网格行为与性能
    max_open_orders: int = 5
    min_spread_between_orders: Decimal = Field(default=Decimal("0.0005"))
    min_order_amount_quote: Decimal = Field(default=Decimal("5"))

    # 执行细节
    order_type: OrderType = OrderType.LIMIT
    order_frequency: int = 0  # 两次下单之间的最小秒数
    activation_bounds: Optional[Decimal] = None  # 动态挂单的激活范围
    safe_extra_spread: Decimal = Field(default=Decimal("0.0001")) # 防止吃单的安全价差

    # 简化版止盈 (替代TripleBarrierConfig)
    # 每个网格层级的订单成交后，会基于此百分比创建止盈单
    take_profit_pct: Decimal = Field(default=Decimal("0.01")) # 默认1%的止盈

    # 永续合约相关
    leverage: int = 20

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {Decimal: str}


class GridLevelStates(Enum):
    """
    定义网格层级的生命周期状态，与Hummingbot完全一致。
    """
    NOT_ACTIVE = "NOT_ACTIVE"          # 未激活，可以创建开仓单
    OPEN_ORDER_PLACED = "OPEN_ORDER_PLACED"  # 开仓单已挂出
    OPEN_ORDER_FILLED = "OPEN_ORDER_FILLED"  # 开仓单已成交
    CLOSE_ORDER_PLACED = "CLOSE_ORDER_PLACED" # 平仓（止盈）单已挂出
    COMPLETE = "COMPLETE"              # 平仓单已成交，一个完整的循环结束


class TrackedOrder(BaseModel):
    """
    一个简化的订单追踪模型，用于GridLevel。
    它存储了在途或已完成订单的关键信息。
    支持事件驱动的实时状态更新。
    """
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None  # 新增：用于事件匹配
    order_type: Optional[OrderType] = None
    
    # 订单的核心参数
    price: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    
    # 订单的执行状态
    is_done: bool = False
    is_filled: bool = False
    executed_amount_base: Decimal = Decimal("0")
    executed_amount_quote: Decimal = Decimal("0")
    
    # 费用信息
    cum_fees_quote: Decimal = Decimal("0")
    
    # 用于存储从交易所返回的原始订单信息，方便调试
    raw_info: Dict[str, Any] = {}

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def status(self) -> str:
        """获取订单状态"""
        if self.raw_info and 'status' in self.raw_info:
            return self.raw_info['status']
        return "unknown"

    def update_from_exchange_data(self, order_data: Dict[str, Any]) -> bool:
        """从交易所数据更新订单状态，支持REST API和WebSocket事件"""
        try:
            # 处理不同格式的订单数据
            # WebSocket事件格式 vs REST API格式
            if 'X' in order_data:  # WebSocket ORDER_TRADE_UPDATE格式
                status = order_data.get('X', 'UNKNOWN').upper()
                filled_qty = order_data.get('z', '0')  # 累计成交数量
                filled_quote = order_data.get('Z', '0')  # 累计成交金额
                client_order_id = order_data.get('c', '')
            else:  # REST API格式
                status = order_data.get('status', 'unknown').upper()
                filled_qty = order_data.get('filled', '0')
                filled_quote = order_data.get('cost', '0')
                client_order_id = order_data.get('clientOrderId', '')

            # 更新状态
            self.is_filled = status in ['CLOSED', 'FILLED']
            self.is_done = status in ['CLOSED', 'FILLED', 'CANCELED', 'EXPIRED']

            # 更新client_order_id（如果还没有的话）
            if client_order_id and not self.client_order_id:
                self.client_order_id = client_order_id

            # 更新成交数量和金额
            if filled_qty:
                self.executed_amount_base = Decimal(str(filled_qty))
            if filled_quote:
                self.executed_amount_quote = Decimal(str(filled_quote))

            # 更新手续费（WebSocket和REST格式不同）
            if 'fee' in order_data and order_data['fee']:
                fee_info = order_data['fee']
                if 'cost' in fee_info:
                    self.cum_fees_quote = Decimal(str(fee_info['cost']))

            # 更新原始信息
            self.raw_info = order_data
            return True

        except Exception as e:
            # 如果更新失败，记录错误但不抛出异常
            return False

    @property
    def is_partially_filled(self) -> bool:
        """检查订单是否部分成交"""
        return self.executed_amount_base > 0 and not self.is_filled

    @property
    def remaining_amount(self) -> Decimal:
        """获取剩余未成交数量"""
        return self.amount - self.executed_amount_base

    @property
    def fill_percentage(self) -> Decimal:
        """获取成交百分比"""
        if self.amount > 0:
            return (self.executed_amount_base / self.amount) * 100
        return Decimal("0")


class GridLevel(BaseModel):
    """
    代表网格中的单一层级，与Hummingbot模型高度兼容。
    """
    id: str
    price: Decimal
    amount_quote: Decimal
    side: TradeType
    order_type: OrderType
    take_profit_pct: Decimal

    # 追踪与此层级关联的订单
    active_open_order: Optional[TrackedOrder] = None
    active_close_order: Optional[TrackedOrder] = None
    state: GridLevelStates = GridLevelStates.NOT_ACTIVE

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def update_state(self):
        """根据关联订单的状态更新层级的生命周期状态。"""
        old_state = self.state

        if self.active_open_order is None:
            # 没有开仓订单 -> 未激活状态
            self.state = GridLevelStates.NOT_ACTIVE

        elif not self.active_open_order.is_done:
            # 开仓订单存在但未完成 -> 开仓订单已下达状态
            self.state = GridLevelStates.OPEN_ORDER_PLACED

        elif self.active_open_order.is_filled:
            # 开仓订单已成交
            if self.active_close_order is None:
                # 没有平仓订单 -> 开仓订单已成交状态
                self.state = GridLevelStates.OPEN_ORDER_FILLED

            elif not self.active_close_order.is_done:
                # 平仓订单存在但未完成 -> 平仓订单已下达状态
                self.state = GridLevelStates.CLOSE_ORDER_PLACED

            elif self.active_close_order.is_filled:
                # 平仓订单已成交 -> 完成状态
                self.state = GridLevelStates.COMPLETE

            else:
                # 平仓订单被取消或失败 -> 回到开仓订单已成交状态
                self.state = GridLevelStates.OPEN_ORDER_FILLED

        else:
            # 开仓订单被取消或失败 -> 回到未激活状态
            self.state = GridLevelStates.NOT_ACTIVE

        # 记录状态变化
        if old_state != self.state:
            # 这里可以添加状态变化的日志，但为了避免过多日志，暂时注释
            # print(f"层级 {self.id} 状态变化: {old_state.value} -> {self.state.value}")
            pass

    def reset_open_order(self):
        """当开仓单被取消或失败时，重置开仓订单状态。"""
        self.active_open_order = None
        self.state = GridLevelStates.NOT_ACTIVE

    def reset_close_order(self):
        """当平仓单被取消或失败时，重置平仓订单状态。"""
        self.active_close_order = None
        self.state = GridLevelStates.OPEN_ORDER_FILLED

    def reset_level(self):
        """当一个完整的交易周期完成，重置整个层级以便复用。"""
        self.active_open_order = None
        self.active_close_order = None
        self.state = GridLevelStates.NOT_ACTIVE


# ==============================================================================
# 交易所交互 (BinanceConnector) 相关数据模型
# ==============================================================================

class TradingRule(BaseModel):
    """
    封装从交易所获取的交易规则，供GridExecutor在生成网格时使用。
    """
    trading_pair: str
    min_price_increment: Decimal
    min_base_amount_increment: Decimal
    min_notional_size: Decimal
    min_order_size: Decimal

class OrderCandidate(BaseModel):
    """
    一个标准化的订单候选对象。
    GridExecutor创建此对象，然后由BinanceConnector负责量化和执行。
    """
    trading_pair: str
    order_type: OrderType
    order_side: TradeType
    amount: Decimal
    price: Decimal = Decimal("NaN") # 市价单价格可为NaN
    position_action: PositionAction

    model_config = ConfigDict(arbitrary_types_allowed=True)