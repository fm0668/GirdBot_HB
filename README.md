# 双账户对冲网格策略交易机器人

一个基于Python的高级量化交易策略，通过两个独立的币安账户实现对冲网格交易（永续合约）。

## 项目特点

- **双账户架构**：一个账户执行多头网格，另一个账户执行空头网格
- **风险对冲**：通过双向持仓实现风险对冲和波动套利
- **完整复刻**：基于Hummingbot的GridExecutor核心逻辑
- **专业架构**：模块化设计，高内聚低耦合
- **安全可靠**：完善的错误处理和状态监控

## 项目架构

```
GirdBot_HB/
├── main.py                     # 项目主入口
├── config.py                   # 配置文件
├── strategy_controller.py      # 策略控制器
├── grid_executor.py            # 网格执行器
├── binance_connector.py        # 币安连接器
├── data_models.py              # 数据模型
├── utils/
│   ├── __init__.py
│   └── logger.py               # 日志模块
├── requirements.txt            # 项目依赖
└── README.md                   # 项目说明
```

## 核心组件

### 1. StrategyController（策略控制器）
- 管理双账户的生命周期
- 执行启动前的账户清理和资金平衡
- 同步启动和停止两个网格执行器
- 监控执行器状态，确保同步运行

### 2. GridExecutor（网格执行器）
- 完整复刻Hummingbot的网格策略逻辑
- 包含网格生成、订单管理、状态控制等核心功能
- 支持多头和空头两种模式

### 3. BinanceConnector（币安连接器）
- 封装所有与币安交易所的交互
- 提供标准化的API接口
- 支持下单、撤单、查询持仓、获取余额等操作

### 4. DataModels（数据模型）
- 使用Pydantic定义标准化数据结构
- 确保数据传递的类型安全和准确性

## 安装和配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

**重要：为了安全起见，API密钥现在通过环境变量配置，不再直接写在代码中。**

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入您的API密钥
nano .env
```

在 `.env` 文件中填入您的API密钥：
```env
# 账户A配置 (多头网格)
ACCOUNT_A_API_KEY=your_account_a_api_key_here
ACCOUNT_A_API_SECRET=your_account_a_api_secret_here

# 账户B配置 (空头网格)
ACCOUNT_B_API_KEY=your_account_b_api_key_here
ACCOUNT_B_API_SECRET=your_account_b_api_secret_here
```

**注意：**
- `.env` 文件已添加到 `.gitignore`，不会被上传到GitHub
- 请确保API密钥具有期货交易权限
- 建议为每个账户创建独立的API密钥

### 3. 配置网格参数

在 `config.py` 中调整网格策略参数：

```python
GRID_CONFIG = {
    "start_price": Decimal("0.2500"),      # 网格起始价格
    "end_price": Decimal("0.2800"),        # 网格结束价格
    "total_amount_quote": Decimal("100"),  # 总投入资金
    "max_open_orders": 3,                  # 最大同时开仓订单数
    "min_order_amount_quote": Decimal("5"), # 最小订单金额
    "min_spread_between_orders": Decimal("0.0005"), # 订单间最小价差
    # ... 其他参数
}
```

#### 🎯 网格层数计算说明

网格层数由以下参数决定：

**影响因素：**
1. **网格范围**: `end_price - start_price`
2. **总投入资金**: `total_amount_quote`
3. **最小订单金额**: `min_order_amount_quote`
4. **最小价差**: `min_spread_between_orders`

**计算公式：**
```
最大层级数 = min(
    总资金 / 最小订单金额,
    网格范围 / 最小价差
)

单层级金额 = 总资金 / 实际层级数
```

**优化建议：**
- 增加层数：增加`total_amount_quote`，减少`min_order_amount_quote`
- 减少层数：减少`total_amount_quote`，增加`min_order_amount_quote`
- 平衡考虑：层数过多单笔金额小，层数过少覆盖不够

## 使用方法

### 启动机器人

```bash
python main.py
```

### 停止机器人

使用 `Ctrl+C` 或发送 `SIGTERM` 信号来优雅地停止机器人。

## 安全注意事项

1. **API权限**：确保API密钥只有必要的交易权限，不要开启提现权限
2. **资金管理**：建议先在测试环境中运行，确认策略正常后再使用真实资金
3. **风险控制**：设置合理的止损参数，避免过度杠杆
4. **监控告警**：建议设置监控告警，及时发现异常情况

## 功能特性

### 已实现功能

- ✅ 双账户API连接和管理
- ✅ 账户清理（撤单、平仓）
- ✅ 网格层级生成和管理
- ✅ 订单下达和撤销
- ✅ 持仓监控和管理
- ✅ 状态同步和监控
- ✅ 优雅关闭和清理
- ✅ 完善的日志记录

### 待实现功能

- ⏳ 跨账户资金划转
- ⏳ 高级风控策略
- ⏳ 性能指标统计
- ⏳ Web界面监控
- ⏳ 数据库存储

## 开发说明

### 代码结构

项目采用模块化设计，各模块职责清晰：

- **变与不变分离**：策略逻辑相对稳定，交易所交互可能变化
- **职责单一**：每个模块只负责一个特定功能
- **高度可测试**：可以独立测试各个模块的功能

### 扩展开发

如需扩展功能，建议：

1. 在对应模块中添加新方法
2. 更新数据模型以支持新功能
3. 添加相应的测试用例
4. 更新配置文件和文档

## 许可证

本项目仅供学习和研究使用，请勿用于非法用途。使用本项目进行交易的风险由用户自行承担。

## 免责声明

本项目为教育和研究目的而创建，不构成投资建议。加密货币交易存在高风险，可能导致资金损失。请在充分了解风险的情况下使用本项目，并建议先在测试环境中验证策略的有效性。
