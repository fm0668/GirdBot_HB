# VPS部署指南 - 双账户对冲网格策略

## 🚀 **快速开始**

### **1. 启动策略**
```bash
./start_live_trading.sh
```

### **2. 查看日志**
```bash
./view_logs.sh              # 查看策略状态摘要
./view_logs.sh live          # 查看实时日志
./view_logs.sh recent 100    # 查看最近100行日志
```

### **3. 停止策略**
```bash
./stop_trading.sh            # 停止策略并清理
./stop_trading.sh -f         # 强制停止
./stop_trading.sh -c         # 仅执行清理
```

## 📋 **脚本详细说明**

### **🟢 start_live_trading.sh - 启动脚本**

**功能**：
- ✅ 检查Python环境和依赖
- ✅ 验证配置文件(.env, config.py)
- ✅ 备份现有日志文件
- ✅ 启动策略并保持后台运行
- ✅ 生成PID文件用于进程管理

**使用方法**：
```bash
./start_live_trading.sh
```

**输出文件**：
- `DualGridBot.pid` - 进程ID文件
- `logs/dual_grid_bot.log` - 策略运行日志
- `startup.log` - 启动日志
- `backup/` - 日志备份目录

### **🔍 view_logs.sh - 日志查看脚本**

**功能**：
- 📊 显示策略运行状态和重要信息
- 📈 显示网格层数、下单金额、交易统计
- 💰 显示每个账户的执行情况
- ⚠️ 显示错误和警告信息
- 💳 显示账户余额信息

**使用方法**：
```bash
./view_logs.sh                    # 显示策略状态摘要(默认)
./view_logs.sh status             # 显示策略状态摘要
./view_logs.sh live               # 显示实时日志(彩色)
./view_logs.sh recent 50          # 显示最近50行日志
./view_logs.sh search "ERROR"     # 搜索包含ERROR的日志
./view_logs.sh help               # 显示帮助信息
```

**显示内容**：
- ✅ 策略运行状态 (PID, 进程信息)
- 📊 最新策略状态 (持仓、网格层数)
- 🔧 网格配置信息
- 💰 交易统计 (成交、收益)
- ⚠️ 错误信息 (如有)
- 💳 账户余额信息

### **🛑 stop_trading.sh - 停止脚本**

**功能**：
- 🛑 优雅停止策略进程
- 🧹 执行手动清理 (取消挂单、平仓)
- 📋 显示停止前后状态
- 🔒 支持确认模式和强制模式

**使用方法**：
```bash
./stop_trading.sh              # 正常停止(需确认)
./stop_trading.sh -f           # 强制停止(无需确认)
./stop_trading.sh --force      # 强制停止(无需确认)
./stop_trading.sh -c           # 仅执行清理
./stop_trading.sh --cleanup-only # 仅执行清理
./stop_trading.sh -h           # 显示帮助信息
```

**执行流程**：
1. 显示当前策略状态
2. 确认停止操作 (除非强制模式)
3. 优雅停止进程 (SIGTERM → SIGKILL)
4. 执行手动清理脚本
5. 显示停止后状态

## 📊 **监控重要信息**

### **策略运行状态**
```bash
./view_logs.sh status
```
显示：
- ✅ 进程状态 (运行/停止)
- 📊 最新策略状态
- 🔧 网格层数配置
- 💰 交易统计
- ⚠️ 错误信息

### **实时监控**
```bash
./view_logs.sh live
```
实时显示：
- 📈 订单成交信息
- 💰 收益统计
- 🔄 网格层级状态
- ⚠️ 错误和警告

### **关键指标**
- **网格层数**: 当前配置的网格数量
- **单层金额**: 每个网格的投入金额
- **持仓情况**: 多头/空头持仓数量
- **成交统计**: 成交订单数和金额
- **收益情况**: 每笔交易的收益

## 🔧 **故障排除**

### **启动失败**
```bash
# 检查启动日志
cat startup.log

# 检查配置
./start_live_trading.sh
```

### **策略异常**
```bash
# 查看错误日志
./view_logs.sh search "ERROR"

# 查看最近日志
./view_logs.sh recent 100
```

### **清理失败**
```bash
# 仅执行清理
./stop_trading.sh -c

# 手动清理
python3 manual_cleanup.py
```

## 📁 **重要文件**

| 文件 | 说明 |
|------|------|
| `DualGridBot.pid` | 进程ID文件 |
| `logs/dual_grid_bot.log` | 主要运行日志 |
| `startup.log` | 启动日志 |
| `backup/` | 日志备份目录 |
| `.env` | API密钥配置 |
| `config.py` | 策略参数配置 |

## 🎯 **最佳实践**

### **日常监控**
```bash
# 每天检查策略状态
./view_logs.sh status

# 定期查看交易情况
./view_logs.sh search "交易完成"

# 监控错误信息
./view_logs.sh search "ERROR"
```

### **维护操作**
```bash
# 重启策略
./stop_trading.sh -f && ./start_live_trading.sh

# 清理日志 (手动)
mv logs/dual_grid_bot.log backup/dual_grid_bot_$(date +%Y%m%d).log

# 检查磁盘空间
du -h logs/ backup/
```

### **安全建议**
- 🔒 定期更换API密钥
- 📊 监控账户余额变化
- ⚠️ 及时处理错误信息
- 💾 定期备份配置文件
- 🔍 监控异常交易行为

## 📞 **支持**

如遇问题：
1. 查看 `./view_logs.sh status` 了解当前状态
2. 查看 `./view_logs.sh search "ERROR"` 了解错误信息
3. 运行 `./stop_trading.sh -c` 执行清理
4. 联系技术支持并提供日志文件
