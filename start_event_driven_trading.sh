#!/bin/bash

# ==================== 事件驱动模式双账户对冲网格交易启动脚本 ====================
# 
# 功能：启动事件驱动版本的双账户对冲网格交易策略
# 特点：
# - 事件驱动为主，轮询为辅的高性能模式
# - WebSocket实时订单状态更新
# - 低延迟响应市场变化
# - 备用轮询确保数据完整性
#
# 使用方法：
#   ./start_event_driven_trading.sh
#
# ==================================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 日志函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${PURPLE}[HEADER]${NC} $1"
}

# 检查是否已有进程在运行
check_existing_process() {
    if [ -f "dual_grid_bot.pid" ]; then
        PID=$(cat dual_grid_bot.pid)
        if ps -p "$PID" > /dev/null 2>&1; then
            print_error "策略已在运行中 (PID: $PID)"
            print_info "如需重启，请先执行: ./stop_trading.sh"
            exit 1
        else
            print_warning "发现残留PID文件，正在清理..."
            rm -f dual_grid_bot.pid
        fi
    fi
}

# 环境检查
check_environment() {
    print_info "检查运行环境..."
    
    # 检查Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 未安装"
        exit 1
    fi
    
    # 检查必要文件
    required_files=("main.py" "config.py" "strategy_controller.py" "grid_executor.py" "binance_connector.py" "data_models.py")
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            print_error "缺少必要文件: $file"
            exit 1
        fi
    done
    
    # 检查日志目录
    if [ ! -d "logs" ]; then
        print_info "创建日志目录..."
        mkdir -p logs
    fi
    
    print_success "环境检查通过"
}

# 备份历史日志
backup_logs() {
    if [ -f "logs/dual_grid_bot.log" ]; then
        timestamp=$(date +"%Y%m%d_%H%M%S")
        backup_file="logs/dual_grid_bot_${timestamp}.log"
        print_info "备份历史日志到: $backup_file"
        mv "logs/dual_grid_bot.log" "$backup_file"
        
        # 只保留最近10个备份文件
        ls -t logs/dual_grid_bot_*.log 2>/dev/null | tail -n +11 | xargs -r rm
    fi
}

# 预启动清理
pre_start_cleanup() {
    print_info "执行预启动清理..."
    
    # 清理可能的残留订单和持仓
    python3 -c "
import asyncio
from strategy_controller import StrategyController

async def cleanup():
    controller = StrategyController()
    try:
        await controller.initialize_connectors()
        print('[INFO] 正在清理残留订单和持仓...')
        
        # 取消所有挂单
        controller.connector_a.cancel_all_orders()
        controller.connector_b.cancel_all_orders()
        
        # 平掉所有持仓
        controller.connector_a.close_all_positions()
        controller.connector_b.close_all_positions()
        
        print('[SUCCESS] 预启动清理完成')
    except Exception as e:
        print(f'[WARNING] 预启动清理出现异常: {e}')
    finally:
        if controller.connector_a:
            await controller.connector_a.stop_websocket()
        if controller.connector_b:
            await controller.connector_b.stop_websocket()

asyncio.run(cleanup())
" 2>/dev/null || print_warning "预启动清理执行异常，继续启动..."
}

# 启动策略
start_strategy() {
    print_header "启动事件驱动模式双账户对冲网格交易策略"
    print_info "模式: 事件驱动为主，轮询为辅"
    print_info "特性: WebSocket实时更新 + 备用轮询保障"
    
    # 使用nohup在后台启动
    nohup python3 main.py > logs/dual_grid_bot.log 2>&1 &
    PID=$!
    
    # 保存PID
    echo $PID > dual_grid_bot.pid
    
    print_success "策略已启动 (PID: $PID)"
    print_info "日志文件: logs/dual_grid_bot.log"
    
    # 等待几秒检查启动状态
    sleep 3
    
    if ps -p "$PID" > /dev/null 2>&1; then
        print_success "策略运行正常"
        print_info "使用以下命令监控策略:"
        echo -e "  ${CYAN}./view_logs.sh status${NC}    # 查看策略状态"
        echo -e "  ${CYAN}./view_logs.sh live${NC}      # 实时查看日志"
        echo -e "  ${CYAN}./stop_trading.sh${NC}        # 停止策略"
    else
        print_error "策略启动失败，请检查日志文件"
        rm -f dual_grid_bot.pid
        exit 1
    fi
}

# 主函数
main() {
    print_header "事件驱动模式双账户对冲网格交易启动器"
    print_info "版本: Event-Driven v2.0"
    print_info "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    check_existing_process
    check_environment
    backup_logs
    pre_start_cleanup
    start_strategy
    
    echo ""
    print_success "事件驱动模式策略启动完成！"
    print_info "策略将以高性能模式运行，实时响应市场变化"
}

# 执行主函数
main "$@"
