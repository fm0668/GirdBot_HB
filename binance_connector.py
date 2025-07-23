# dual_grid_bot/binance_connector.py

import asyncio
import ccxt
import logging
import math
import time
import json
import websockets
import hmac
import hashlib
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple

from data_models import TradingRule, OrderCandidate, TradeType, OrderType, PositionAction

# WebSocket配置
WEBSOCKET_URL = "wss://fstream.binance.com/ws"
SYNC_TIME = 10  # 同步时间（秒）


class CustomBinance(ccxt.binance):
    """自定义Binance交易所类，继承自ccxt.binance"""
    
    def fetch(self, url, method='GET', headers=None, body=None):
        if headers is None:
            headers = {}
        return super().fetch(url, method, headers, body)


class BinanceConnector:
    """
    币安交易所连接器，封装所有与交易所的交互操作
    从grid_binance.py提取和重构的交易所交互代码
    """
    
    def __init__(self, api_key: str, api_secret: str, trading_pair: str,
                 contract_type: str = "USDC", leverage: int = 20,
                 sandbox: bool = False, account_name: str = "",
                 event_queue: Optional['asyncio.Queue'] = None):
        """
        初始化币安连接器
        
        Args:
            api_key: API密钥
            api_secret: API密钥
            trading_pair: 交易对，如 "XRP/USDC:USDC"
            contract_type: 合约类型，USDT或USDC
            leverage: 杠杆倍数
            sandbox: 是否使用沙盒环境
            account_name: 账户名称，用于日志标识
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pair = trading_pair
        self.contract_type = contract_type
        self.leverage = leverage
        self.account_name = account_name

        # 设置日志（必须在其他操作之前）
        self.logger = logging.getLogger(f"BinanceConnector_{account_name}")

        # 初始化交易所连接
        self.exchange = self._initialize_exchange(sandbox)

        # 获取交易规则
        self.trading_rules = self._get_trading_rules()

        # 价格和持仓数据
        self.latest_price = Decimal("0")
        self.best_bid_price = Decimal("0")
        self.best_ask_price = Decimal("0")

        # 持仓数据
        self.long_position = Decimal("0")
        self.short_position = Decimal("0")

        # 挂单数据
        self.buy_long_orders = Decimal("0")
        self.sell_long_orders = Decimal("0")
        self.sell_short_orders = Decimal("0")
        self.buy_short_orders = Decimal("0")

        # 时间戳
        self.last_position_update_time = 0
        self.last_orders_update_time = 0
        self.last_ticker_update_time = 0

        # 事件队列（用于事件驱动模式）
        self.event_queue = event_queue

        # WebSocket相关
        self.listenKey = None
        self.user_data_stream_task: Optional['asyncio.Task'] = None
        self._listen_key: Optional[str] = None
        self._listen_key_last_update = 0
        self.websocket_task = None
        self.websocket_running = False
        self.lock = asyncio.Lock()

        # 重连配置
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # 初始重连延迟（秒）
        self.max_reconnect_delay = 60  # 最大重连延迟（秒）
        self.connection_healthy = True
        self.last_heartbeat_time = 0

        # 跳过双向持仓模式设置（用户已在账户后台设置）
        # self._check_and_enable_hedge_mode()

        # listenKey将在start_event_listening时获取
        
    def _initialize_exchange(self, sandbox: bool = False) -> CustomBinance:
        """初始化交易所API连接 - 参考grid_binance.py的简化方法"""
        exchange = CustomBinance({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "options": {
                "defaultType": "future",  # 使用永续合约
            },
            "sandbox": sandbox,
        })

        # 参考代码的方法：直接加载市场数据，但不做复杂处理
        exchange.load_markets(reload=False)
        self.logger.info("交易所连接已建立")

        return exchange
    
    def _get_trading_rules(self) -> TradingRule:
        """获取交易对的交易规则"""
        try:
            markets = self.exchange.fetch_markets()
            symbol_info = next(market for market in markets if market["symbol"] == self.trading_pair)
            
            # 获取价格精度
            price_precision = symbol_info["precision"]["price"]
            if isinstance(price_precision, float):
                price_increment = Decimal(str(price_precision))
            elif isinstance(price_precision, int):
                price_increment = Decimal("0.1") ** price_precision
            else:
                raise ValueError(f"Unknown price precision type: {price_precision}")
            
            # 获取数量精度
            amount_precision = symbol_info["precision"]["amount"]
            if isinstance(amount_precision, float):
                amount_increment = Decimal(str(amount_precision))
            elif isinstance(amount_precision, int):
                amount_increment = Decimal("0.1") ** amount_precision
            else:
                raise ValueError(f"Unknown amount precision type: {amount_precision}")
            
            # 获取最小下单数量和最小名义价值
            min_order_size = Decimal(str(symbol_info["limits"]["amount"]["min"]))
            min_notional_size = Decimal(str(symbol_info["limits"]["cost"]["min"]))
            
            trading_rule = TradingRule(
                trading_pair=self.trading_pair,
                min_price_increment=price_increment,
                min_base_amount_increment=amount_increment,
                min_notional_size=min_notional_size,
                min_order_size=min_order_size
            )
            
            self.logger.info(f"交易规则已加载: {trading_rule}")
            return trading_rule

        except Exception as e:
            self.logger.error(f"获取交易规则失败: {e}")
            raise
    
    def _check_and_enable_hedge_mode(self):
        """检查并启用双向持仓模式 - 参考grid_binance.py的简化方法"""
        try:
            # 参考代码的方法：直接尝试启用，减少API调用
            params = {'dualSidePosition': 'true'}
            response = self.exchange.fapiPrivatePostPositionSideDual(params)
            self.logger.info(f"双向持仓模式已启用: {response}")
        except Exception as e:
            # 如果失败，可能已经是双向持仓模式，记录警告但不抛出异常
            self.logger.warning(f"启用双向持仓模式失败（可能已启用）: {e}")
            # 不抛出异常，继续执行
    
    def get_mid_price(self) -> Decimal:
        """获取中间价格"""
        # 如果WebSocket连接健康且有最新价格，直接返回（快速路径）
        if self.is_connected() and self.latest_price > 0:
            return Decimal(str(self.latest_price))

        # 否则通过REST API获取（慢速路径）
        max_retries = 2  # 减少重试次数
        for attempt in range(max_retries):
            try:
                ticker = self.exchange.fetch_ticker(self.trading_pair)

                # 尝试多种价格获取方式
                bid = None
                ask = None
                last = None

                if ticker.get('bid') is not None:
                    bid = Decimal(str(ticker['bid']))
                if ticker.get('ask') is not None:
                    ask = Decimal(str(ticker['ask']))
                if ticker.get('last') is not None:
                    last = Decimal(str(ticker['last']))

                # 优先使用买卖价计算中间价
                if bid and ask and bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2
                    self.latest_price = float(mid_price)  # 更新缓存
                    self.best_bid_price = bid
                    self.best_ask_price = ask
                    return mid_price

                # 如果买卖价无效，使用最新价
                elif last and last > 0:
                    self.latest_price = float(last)  # 更新缓存
                    return last

                else:
                    if attempt < max_retries - 1:
                        time.sleep(0.5)  # 减少等待时间
                        continue
                    else:
                        # 如果有历史价格，返回历史价格
                        if self.latest_price > 0:
                            return Decimal(str(self.latest_price))
                        else:
                            raise ValueError("无法获取有效的价格数据")

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(0.5)  # 减少等待时间
                    continue
                else:
                    # 最后一次尝试失败，返回历史价格或抛出异常
                    if self.latest_price > 0:
                        return Decimal(str(self.latest_price))
                    else:
                        raise ValueError(f"获取中间价格失败: {e}")

        # 不应该到达这里
        raise ValueError("获取中间价格失败")
    
    def get_balance(self, asset: str = None) -> Dict[str, Decimal]:
        """获取账户余额"""
        try:
            if asset is None:
                asset = self.contract_type
                
            balance = self.exchange.fetch_balance()
            
            # 获取指定资产的余额信息
            if asset in balance:
                return {
                    "free": Decimal(str(balance[asset]["free"])),
                    "used": Decimal(str(balance[asset]["used"])),
                    "total": Decimal(str(balance[asset]["total"]))
                }
            else:
                return {
                    "free": Decimal("0"),
                    "used": Decimal("0"),
                    "total": Decimal("0")
                }
                
        except Exception as e:
            self.logger.error(f"获取余额失败: {e}")
            return {"free": Decimal("0"), "used": Decimal("0"), "total": Decimal("0")}
    
    def get_positions(self) -> Tuple[Decimal, Decimal]:
        """获取当前持仓 (多头持仓, 空头持仓)"""
        try:
            params = {'type': 'future'}
            positions = self.exchange.fetch_positions(params=params)
            
            long_position = Decimal("0")
            short_position = Decimal("0")
            
            for position in positions:
                if position['symbol'] == self.trading_pair:
                    contracts = Decimal(str(position.get('contracts', 0)))
                    side = position.get('side', None)
                    
                    if side == 'long':
                        long_position = contracts
                    elif side == 'short':
                        short_position = abs(contracts)
            
            # 更新内部状态
            self.long_position = long_position
            self.short_position = short_position
            self.last_position_update_time = time.time()
            
            return long_position, short_position
            
        except Exception as e:
            self.logger.error(f"获取持仓失败: {e}")
            return self.long_position, self.short_position

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """获取当前所有挂单"""
        try:
            orders = self.exchange.fetch_open_orders(self.trading_pair)
            return orders
        except Exception as e:
            self.logger.error(f"获取挂单失败: {e}")
            return []

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """获取订单状态"""
        try:
            order = self.exchange.fetch_order(order_id, self.trading_pair)
            return order
        except Exception as e:
            self.logger.error(f"获取订单状态失败 {order_id}: {e}")
            return None

    def get_multiple_order_status(self, order_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取多个订单状态"""
        results = {}
        for order_id in order_ids:
            try:
                order = self.exchange.fetch_order(order_id, self.trading_pair)
                results[order_id] = order
            except Exception as e:
                self.logger.error(f"获取订单状态失败 {order_id}: {e}")
                results[order_id] = None
        return results

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的成交记录"""
        try:
            trades = self.exchange.fetch_my_trades(self.trading_pair, limit=limit)
            return trades
        except Exception as e:
            self.logger.error(f"获取成交记录失败: {e}")
            return []

    def _get_listen_key(self):
        """获取listenKey"""
        try:
            response = self.exchange.fapiPrivatePostListenKey()
            self.listenKey = response.get("listenKey")
            if not self.listenKey:
                raise ValueError("获取的listenKey为空")
            self.logger.info(f"成功获取listenKey: {self.listenKey[:10]}...")
        except Exception as e:
            self.logger.error(f"获取listenKey失败: {e}")
            self.listenKey = None

    async def _keep_listen_key_alive(self):
        """定期更新listenKey"""
        while self.websocket_running:
            try:
                await asyncio.sleep(1800)  # 每30分钟更新一次
                if self.websocket_running:
                    self.exchange.fapiPrivatePutListenKey()
                    self._get_listen_key()
                    self.logger.info("listenKey已更新")
            except Exception as e:
                self.logger.error(f"更新listenKey失败: {e}")
                await asyncio.sleep(60)

    async def start_websocket(self):
        """启动WebSocket连接"""
        if self.websocket_running:
            return

        self.websocket_running = True

        # 启动listenKey保活任务
        asyncio.create_task(self._keep_listen_key_alive())

        # 启动WebSocket连接任务
        self.websocket_task = asyncio.create_task(self._websocket_loop())

        self.logger.info("WebSocket连接已启动")

    async def stop_websocket(self):
        """停止WebSocket连接"""
        self.websocket_running = False

        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass

        self.logger.info("WebSocket连接已停止")

    def is_connected(self) -> bool:
        """检查WebSocket连接健康状态"""
        if not self.websocket_running:
            return False

        # 检查连接健康标志
        if not self.connection_healthy:
            return False

        # 检查心跳时间（如果超过90秒无心跳，认为连接不健康）
        current_time = time.time()
        if self.last_heartbeat_time > 0 and current_time - self.last_heartbeat_time > 90:
            self.logger.warning("WebSocket连接心跳超时，连接可能不健康")
            return False

        return True

    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态详情"""
        current_time = time.time()
        return {
            "websocket_running": self.websocket_running,
            "connection_healthy": self.connection_healthy,
            "reconnect_attempts": self.reconnect_attempts,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "last_heartbeat_time": self.last_heartbeat_time,
            "seconds_since_heartbeat": current_time - self.last_heartbeat_time if self.last_heartbeat_time > 0 else -1,
            "is_connected": self.is_connected()
        }

    async def _websocket_loop(self):
        """增强的WebSocket连接循环，支持指数退避重连"""
        while self.websocket_running:
            try:
                await self._connect_websocket()
                # 连接成功，重置重连计数
                self.reconnect_attempts = 0
                self.connection_healthy = True
                self.logger.info("WebSocket连接已建立")

            except Exception as e:
                self.connection_healthy = False
                self.logger.error(f"WebSocket连接失败: {e}")

                if self.websocket_running:
                    # 检查是否达到最大重连次数
                    if self.reconnect_attempts >= self.max_reconnect_attempts:
                        self.logger.error(f"达到最大重连次数({self.max_reconnect_attempts})，停止重连")
                        self.websocket_running = False
                        break

                    # 指数退避重连
                    delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts),
                              self.max_reconnect_delay)
                    self.reconnect_attempts += 1

                    self.logger.info(f"将在{delay}秒后重连 (尝试 {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                    await asyncio.sleep(delay)

    async def _connect_websocket(self):
        """连接WebSocket并订阅数据"""
        if not self.listenKey:
            self.logger.error("listenKey为空，无法连接WebSocket")
            return

        try:
            async with websockets.connect(
                WEBSOCKET_URL,
                ping_interval=20,  # 每20秒发送ping
                ping_timeout=10,   # ping超时时间
                close_timeout=10   # 关闭超时时间
            ) as websocket:
                self.logger.info("WebSocket连接已建立，开始订阅数据...")

                # 订阅ticker数据
                await self._subscribe_ticker(websocket)

                # 订阅订单数据
                await self._subscribe_orders(websocket)

                # 更新心跳时间
                self.last_heartbeat_time = time.time()

                # 处理消息
                while self.websocket_running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=30)
                        await self._handle_websocket_message(message)

                        # 更新心跳时间
                        self.last_heartbeat_time = time.time()

                    except asyncio.TimeoutError:
                        # 检查连接健康状态
                        current_time = time.time()
                        if current_time - self.last_heartbeat_time > 60:  # 60秒无消息认为连接异常
                            self.logger.warning("WebSocket连接超时，准备重连")
                            raise ConnectionError("WebSocket连接超时")

                        # 发送ping保持连接
                        try:
                            await websocket.ping()
                            self.logger.debug("发送WebSocket ping")
                        except Exception as ping_error:
                            self.logger.error(f"发送ping失败: {ping_error}")
                            raise

                    except Exception as e:
                        self.logger.error(f"WebSocket消息处理失败: {e}")
                        raise

        except Exception as e:
            self.logger.error(f"WebSocket连接异常: {e}")
            raise

    async def _subscribe_ticker(self, websocket):
        """订阅ticker数据"""
        symbol = self.trading_pair.replace('/', '').replace(':USDC', 'USDC').lower()
        payload = {
            "method": "SUBSCRIBE",
            "params": [f"{symbol}@bookTicker"],
            "id": 1
        }
        await websocket.send(json.dumps(payload))
        self.logger.info(f"已订阅ticker数据: {symbol}")

    async def _subscribe_orders(self, websocket):
        """订阅订单数据"""
        if not self.listenKey:
            self.logger.error("listenKey为空，无法订阅订单更新")
            return

        payload = {
            "method": "SUBSCRIBE",
            "params": [self.listenKey],
            "id": 2
        }
        await websocket.send(json.dumps(payload))
        self.logger.info("已订阅订单数据")

    async def _handle_websocket_message(self, message):
        """处理WebSocket消息"""
        try:
            data = json.loads(message)

            if data.get("e") == "bookTicker":
                await self._handle_ticker_update(data)
            elif data.get("e") == "ORDER_TRADE_UPDATE":
                await self._handle_order_update(data)

        except Exception as e:
            self.logger.error(f"处理WebSocket消息失败: {e}")

    async def _handle_ticker_update(self, data):
        """处理ticker更新"""
        current_time = time.time()
        if current_time - self.last_ticker_update_time < 0.1:  # 限制更新频率到100ms
            return

        self.last_ticker_update_time = current_time

        try:
            best_bid = float(data.get("b", 0))
            best_ask = float(data.get("a", 0))

            if best_bid > 0 and best_ask > 0:
                self.latest_price = (best_bid + best_ask) / 2
                # self.logger.debug(f"价格更新: {self.latest_price:.5f}")

        except (ValueError, TypeError) as e:
            self.logger.error(f"解析ticker数据失败: {e}")

    async def _handle_order_update(self, data):
        """处理订单更新"""
        async with self.lock:
            try:
                order = data.get("o", {})
                symbol = order.get("s")

                # 检查是否是我们关注的交易对
                expected_symbol = self.trading_pair.replace('/', '').replace(':USDC', 'USDC')
                if symbol != expected_symbol:
                    return

                order_id = order.get("i")
                status = order.get("X")  # 订单状态

                self.logger.info(f"订单更新: {order_id}, 状态: {status}")

                # 这里可以添加更详细的订单状态处理逻辑
                # 例如更新内部的订单跟踪状态

            except Exception as e:
                self.logger.error(f"处理订单更新失败: {e}")

    def update_order_status(self):
        """更新挂单状态统计"""
        try:
            orders = self.get_open_orders()

            # 重置计数器
            buy_long_orders = Decimal("0")
            sell_long_orders = Decimal("0")
            buy_short_orders = Decimal("0")
            sell_short_orders = Decimal("0")

            for order in orders:
                orig_quantity = Decimal(str(abs(float(order.get('info', {}).get('origQty', 0)))))
                side = order.get('side')
                position_side = order.get('info', {}).get('positionSide')

                if side == 'buy' and position_side == 'LONG':
                    buy_long_orders += orig_quantity
                elif side == 'sell' and position_side == 'LONG':
                    sell_long_orders += orig_quantity
                elif side == 'buy' and position_side == 'SHORT':
                    buy_short_orders += orig_quantity
                elif side == 'sell' and position_side == 'SHORT':
                    sell_short_orders += orig_quantity

            # 更新内部状态
            self.buy_long_orders = buy_long_orders
            self.sell_long_orders = sell_long_orders
            self.buy_short_orders = buy_short_orders
            self.sell_short_orders = sell_short_orders
            self.last_orders_update_time = time.time()

            self.logger.debug(f"订单状态已更新: 多头买单={buy_long_orders}, 多头卖单={sell_long_orders}, "
                            f"空头买单={buy_short_orders}, 空头卖单={sell_short_orders}")

        except Exception as e:
            self.logger.error(f"更新订单状态失败: {e}")

    def place_order(self, order_candidate: OrderCandidate) -> Optional[Dict[str, Any]]:
        """下单"""
        try:
            # 量化价格和数量
            price = self._quantize_price(order_candidate.price)
            amount = self._quantize_amount(order_candidate.amount)

            # 确保满足最小订单要求
            if amount < self.trading_rules.min_order_size:
                amount = self.trading_rules.min_order_size

            # 检查最小名义价值
            if order_candidate.order_type == OrderType.MARKET:
                # 市价单使用当前市场价格计算名义价值
                current_price = self.get_mid_price()
                notional = amount * current_price
            else:
                # 限价单使用订单价格计算名义价值
                notional = amount * price if not price.is_nan() else amount * self.latest_price

            if notional < self.trading_rules.min_notional_size:
                self.logger.warning(f"订单名义价值 {notional} 低于最小值 {self.trading_rules.min_notional_size}")
                return None

            # 构建订单参数
            side = order_candidate.order_side.value.lower()
            order_type = order_candidate.order_type.value.lower()

            # 生成唯一的客户端订单ID
            import uuid
            client_order_id = f"DualGridBot_{uuid.uuid4().hex[:8]}"

            params = {
                'newClientOrderId': client_order_id,
                'reduce_only': order_candidate.position_action == PositionAction.CLOSE,
            }

            # 设置持仓方向
            if order_candidate.order_side == TradeType.BUY:
                params['positionSide'] = 'LONG' if order_candidate.position_action == PositionAction.OPEN else 'SHORT'
            else:
                params['positionSide'] = 'SHORT' if order_candidate.position_action == PositionAction.OPEN else 'LONG'

            # 下单
            if order_type == 'market':
                order = self.exchange.create_order(
                    self.trading_pair, 'market', side, float(amount), params=params
                )
            else:
                order = self.exchange.create_order(
                    self.trading_pair, 'limit', side, float(amount), float(price), params
                )

            # 确保返回的订单信息包含client_order_id
            if 'clientOrderId' not in order:
                order['clientOrderId'] = client_order_id

            self.logger.info(f"订单已下达: {order['id']} {side} {amount} @ {price} (clientOrderId: {client_order_id})")
            return order

        except Exception as e:
            self.logger.error(f"下单失败: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单"""
        try:
            self.exchange.cancel_order(order_id, self.trading_pair)
            self.logger.info(f"订单已取消: {order_id}")
            return True
        except Exception as e:
            self.logger.error(f"取消订单 {order_id} 失败: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """撤销所有挂单"""
        try:
            orders = self.get_open_orders()
            success_count = 0

            for order in orders:
                if self.cancel_order(order['id']):
                    success_count += 1

            self.logger.info(f"已取消 {success_count}/{len(orders)} 个订单")
            return success_count == len(orders)

        except Exception as e:
            self.logger.error(f"取消所有订单失败: {e}")
            return False

    def close_all_positions(self) -> bool:
        """市价平掉所有持仓"""
        try:
            long_pos, short_pos = self.get_positions()
            success = True

            # 平多头持仓
            if long_pos > 0:
                order_candidate = OrderCandidate(
                    trading_pair=self.trading_pair,
                    order_type=OrderType.MARKET,
                    order_side=TradeType.SELL,
                    amount=long_pos,
                    position_action=PositionAction.CLOSE
                )
                if not self.place_order(order_candidate):
                    success = False

            # 平空头持仓
            if short_pos > 0:
                order_candidate = OrderCandidate(
                    trading_pair=self.trading_pair,
                    order_type=OrderType.MARKET,
                    order_side=TradeType.BUY,
                    amount=short_pos,
                    position_action=PositionAction.CLOSE
                )
                if not self.place_order(order_candidate):
                    success = False

            self.logger.info(f"平掉所有持仓: 多头={long_pos}, 空头={short_pos}, 成功={success}")
            return success

        except Exception as e:
            self.logger.error(f"平掉所有持仓失败: {e}")
            return False

    def cleanup(self) -> bool:
        """清理账户：撤销所有挂单并平掉所有持仓"""
        try:
            self.logger.info("开始清理账户...")

            # 先撤销所有挂单
            cancel_success = self.cancel_all_orders()

            # 等待一下确保撤单完成
            time.sleep(2)

            # 再平掉所有持仓
            close_success = self.close_all_positions()

            # 等待一下确保平仓完成
            time.sleep(2)

            # 验证清理结果
            verification_success = self.verify_cleanup()

            success = cancel_success and close_success and verification_success
            self.logger.info(f"账户清理完成: 成功={success}")
            return success

        except Exception as e:
            self.logger.error(f"清理账户失败: {e}")
            return False

    def verify_cleanup(self) -> bool:
        """验证账户清理结果：确保没有挂单和持仓"""
        try:
            # 检查挂单
            orders = self.get_open_orders()
            if orders:
                self.logger.warning(f"清理后仍有 {len(orders)} 个挂单")
                return False

            # 检查持仓
            long_pos, short_pos = self.get_positions()
            if long_pos > 0 or short_pos > 0:
                self.logger.warning(f"清理后仍有持仓: 多头={long_pos}, 空头={short_pos}")
                return False

            self.logger.info("账户清理验证通过")
            return True

        except Exception as e:
            self.logger.error(f"验证清理结果失败: {e}")
            return False

    def transfer_funds(self, asset: str, amount: Decimal, from_account: str, to_account: str) -> bool:
        """资金划转（如果需要跨账户划转）"""
        try:
            # 注意：这个方法需要根据具体的划转需求实现
            # 币安的划转API比较复杂，需要根据实际情况调整
            self.logger.warning("资金划转方法尚未实现")
            return False

        except Exception as e:
            self.logger.error(f"资金划转失败: {e}")
            return False

    def _quantize_price(self, price: Decimal) -> Decimal:
        """量化价格到交易所要求的精度"""
        if price.is_nan():
            return price

        increment = self.trading_rules.min_price_increment
        return (price // increment) * increment

    def _quantize_amount(self, amount: Decimal) -> Decimal:
        """量化数量到交易所要求的精度"""
        increment = self.trading_rules.min_base_amount_increment
        return (amount // increment) * increment

    def get_trading_rules(self) -> TradingRule:
        """获取交易规则"""
        return self.trading_rules

    def is_connected(self) -> bool:
        """检查连接状态"""
        try:
            # 尝试获取服务器时间来测试连接
            self.exchange.fetch_time()
            return True
        except Exception as e:
            self.logger.error(f"连接检查失败: {e}")
            return False

    def get_account_info(self) -> Dict[str, Any]:
        """获取账户信息"""
        try:
            account = self.exchange.fetch_account()
            balance = self.get_balance()
            long_pos, short_pos = self.get_positions()

            return {
                "account_name": self.account_name,
                "trading_pair": self.trading_pair,
                "balance": balance,
                "positions": {
                    "long": long_pos,
                    "short": short_pos
                },
                "latest_price": self.latest_price,
                "connected": self.is_connected()
            }

        except Exception as e:
            self.logger.error(f"获取账户信息失败: {e}")
            return {}

    # ==================== 事件驱动相关方法 ====================

    async def start_event_listening(self):
        """启动事件监听（如果配置了事件队列）"""
        if self.event_queue is not None:
            self.user_data_stream_task = asyncio.create_task(self._user_data_stream_loop())
            self.logger.info("用户数据流事件监听已启动")

    async def stop_event_listening(self):
        """停止事件监听"""
        if self.user_data_stream_task:
            self.user_data_stream_task.cancel()
            try:
                await self.user_data_stream_task
            except asyncio.CancelledError:
                pass
            self.logger.info("用户数据流事件监听已停止")

    async def _get_listen_key(self) -> Optional[str]:
        """获取用户数据流的listen key"""
        try:
            # 使用ccxt的私有API获取listen key
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.fapiPrivatePostListenKey()
            )
            listen_key = response.get('listenKey')
            if listen_key:
                self._listen_key = listen_key
                self._listen_key_last_update = time.time()
                self.logger.debug(f"获取到listen key: {listen_key[:10]}...")
                return listen_key
        except Exception as e:
            self.logger.error(f"获取listen key失败: {e}")
        return None

    async def _keep_listen_key_alive(self):
        """保持listen key活跃"""
        try:
            if self._listen_key:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.exchange.fapiPrivatePutListenKey({'listenKey': self._listen_key})
                )
                self._listen_key_last_update = time.time()
                self.logger.debug("Listen key已续期")
        except Exception as e:
            self.logger.error(f"续期listen key失败: {e}")

    async def _user_data_stream_loop(self):
        """用户数据流监听循环"""
        retry_count = 0
        max_retries = 10

        while retry_count < max_retries:
            try:
                # 获取listen key
                listen_key = await self._get_listen_key()
                if not listen_key:
                    await asyncio.sleep(5)
                    retry_count += 1
                    continue

                # 构建WebSocket URL
                ws_url = f"wss://fstream.binance.com/ws/{listen_key}"

                # 连接WebSocket
                async with websockets.connect(ws_url) as websocket:
                    self.logger.info("用户数据流WebSocket连接已建立")
                    retry_count = 0  # 重置重试计数

                    # 启动心跳任务
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    try:
                        while True:
                            # 接收消息
                            message = await asyncio.wait_for(websocket.recv(), timeout=30)
                            data = json.loads(message)

                            # 处理消息
                            await self._handle_user_data_message(data)

                    except asyncio.TimeoutError:
                        self.logger.warning("用户数据流接收超时，准备重连")
                        break
                    except websockets.exceptions.ConnectionClosed:
                        self.logger.warning("用户数据流连接关闭，准备重连")
                        break
                    finally:
                        heartbeat_task.cancel()

            except Exception as e:
                self.logger.error(f"用户数据流连接异常: {e}")
                retry_count += 1
                await asyncio.sleep(min(retry_count * 2, 30))  # 指数退避

        self.logger.error("用户数据流连接达到最大重试次数，停止监听")

    async def _heartbeat_loop(self):
        """心跳循环，定期续期listen key"""
        try:
            while True:
                await asyncio.sleep(1800)  # 每30分钟续期一次
                await self._keep_listen_key_alive()
        except asyncio.CancelledError:
            pass

    async def _handle_user_data_message(self, data: Dict[str, Any]):
        """处理用户数据流消息"""
        try:
            event_type = data.get('e')

            if event_type == 'ORDER_TRADE_UPDATE':
                # 订单更新事件
                order_data = data.get('o', {})
                await self._handle_order_update(order_data)

            elif event_type == 'ACCOUNT_UPDATE':
                # 账户更新事件
                account_data = data.get('a', {})
                self._handle_account_update(account_data)

            elif event_type == 'listenKeyExpired':
                # Listen key过期事件
                self.logger.warning("Listen key已过期，需要重新获取")

        except Exception as e:
            self.logger.error(f"处理用户数据消息失败: {e}")

    async def _handle_order_update(self, order_data: Dict[str, Any]):
        """处理订单更新事件"""
        try:
            if self.event_queue:
                # 构建事件对象
                event = {
                    "event_type": "ORDER_UPDATE",
                    "account_name": self.account_name,
                    "data": order_data,
                    "timestamp": time.time()
                }

                # 将事件放入队列
                await self.event_queue.put(event)

                # 记录日志
                client_order_id = order_data.get('c', 'unknown')
                status = order_data.get('X', 'unknown')
                self.logger.debug(f"订单事件已推送: {client_order_id} -> {status}")

        except Exception as e:
            self.logger.error(f"处理订单更新事件失败: {e}")

    def _handle_account_update(self, account_data: Dict[str, Any]):
        """处理账户更新事件"""
        try:
            # 更新持仓信息
            positions = account_data.get('P', [])
            for pos in positions:
                symbol = pos.get('s', '')
                if symbol == self.trading_pair.replace('/', '').replace(':USDC', ''):
                    position_amt = Decimal(str(pos.get('pa', '0')))
                    if position_amt > 0:
                        self.long_position = position_amt
                        self.short_position = Decimal("0")
                    elif position_amt < 0:
                        self.short_position = abs(position_amt)
                        self.long_position = Decimal("0")
                    else:
                        self.long_position = Decimal("0")
                        self.short_position = Decimal("0")

                    self.logger.debug(f"持仓更新: 多头={self.long_position}, 空头={self.short_position}")
                    break

        except Exception as e:
            self.logger.error(f"处理账户更新事件失败: {e}")
