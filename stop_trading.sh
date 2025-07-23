#!/bin/bash

# =============================================================================
# 双账户对冲网格策略 - 停止脚本
# 用于停止策略并执行手动清理
# =============================================================================

# 脚本配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="DualGridBot"
PID_FILE="$SCRIPT_DIR/${PROJECT_NAME}.pid"
LOG_FILE="$SCRIPT_DIR/logs/dual_grid_bot.log"
CLEANUP_SCRIPT="$SCRIPT_DIR/manual_cleanup.py"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印带颜色的消息
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
    echo -e "${CYAN}$1${NC}"
}

# 检查策略是否在运行
check_if_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # 正在运行
        else
            # PID文件存在但进程不存在，删除PID文件
            rm -f "$PID_FILE"
            return 1  # 没有运行
        fi
    else
        return 1  # 没有运行
    fi
}

# 停止策略进程
stop_strategy_process() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        
        if ps -p "$PID" > /dev/null 2>&1; then
            print_info "正在停止策略进程 (PID: $PID)..."
            
            # 首先尝试优雅停止 (SIGTERM)
            kill -TERM "$PID" 2>/dev/null
            
            # 等待进程停止
            local count=0
            while ps -p "$PID" > /dev/null 2>&1 && [ $count -lt 10 ]; do
                sleep 1
                count=$((count + 1))
                echo -n "."
            done
            echo ""
            
            # 如果进程仍在运行，强制停止 (SIGKILL)
            if ps -p "$PID" > /dev/null 2>&1; then
                print_warning "优雅停止失败，强制停止进程..."
                kill -KILL "$PID" 2>/dev/null
                sleep 2
            fi
            
            # 检查进程是否已停止
            if ! ps -p "$PID" > /dev/null 2>&1; then
                print_success "策略进程已停止"
                rm -f "$PID_FILE"
                return 0
            else
                print_error "无法停止策略进程"
                return 1
            fi
        else
            print_warning "PID文件存在但进程不存在，清理PID文件"
            rm -f "$PID_FILE"
            return 0
        fi
    else
        print_info "策略未运行 (PID文件不存在)"
        return 0
    fi
}

# 执行手动清理
execute_manual_cleanup() {
    print_info "执行手动清理..."
    echo ""
    
    if [ -f "$CLEANUP_SCRIPT" ]; then
        # 切换到项目目录
        cd "$SCRIPT_DIR"
        
        # 执行清理脚本
        python3 "$CLEANUP_SCRIPT"
        local cleanup_result=$?
        
        echo ""
        if [ $cleanup_result -eq 0 ]; then
            print_success "手动清理执行完成"
            return 0
        else
            print_error "手动清理执行失败"
            return 1
        fi
    else
        print_error "手动清理脚本不存在: $CLEANUP_SCRIPT"
        return 1
    fi
}

# 显示停止前状态
show_pre_stop_status() {
    print_header "=============================================================="
    print_header "  双账户对冲网格策略 - 停止脚本"
    print_header "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
    print_header "=============================================================="
    echo ""
    
    # 检查策略状态
    if check_if_running; then
        PID=$(cat "$PID_FILE")
        print_info "策略正在运行 (PID: $PID)"
        
        # 显示最新的策略状态
        if [ -f "$LOG_FILE" ]; then
            echo ""
            print_info "最新策略状态:"
            grep "Strategy Status" "$LOG_FILE" | tail -2 | while read line; do
                echo -e "${CYAN}$line${NC}"
            done
        fi
    else
        print_warning "策略未运行"
    fi
    echo ""
}

# 显示停止后状态
show_post_stop_status() {
    echo ""
    print_header "=============================================================="
    print_header "  停止操作完成"
    print_header "=============================================================="
    echo ""
    
    # 检查进程状态
    if check_if_running; then
        print_warning "策略进程仍在运行，可能需要手动处理"
    else
        print_success "策略进程已完全停止"
    fi
    
    # 显示文件状态
    print_info "文件状态:"
    if [ -f "$PID_FILE" ]; then
        print_warning "  PID文件仍存在: $PID_FILE"
    else
        print_success "  PID文件已清理"
    fi
    
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
        print_info "  日志文件: $LOG_FILE ($LOG_SIZE)"
    fi
    
    echo ""
    print_info "📊 后续操作:"
    print_info "  查看日志: ./view_logs.sh"
    print_info "  重新启动: ./start_live_trading.sh"
    print_info "  手动清理: python3 manual_cleanup.py"
    echo ""
}

# 确认停止操作
confirm_stop() {
    if check_if_running; then
        echo ""
        print_warning "策略正在运行，停止操作将："
        echo "  1. 停止策略进程"
        echo "  2. 取消所有挂单"
        echo "  3. 平掉所有持仓"
        echo ""
        
        # 如果是交互式终端，询问确认
        if [ -t 0 ]; then
            read -p "确认要停止策略吗？(y/N): " -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                print_info "操作已取消"
                exit 0
            fi
        else
            print_info "非交互式模式，直接执行停止操作"
        fi
    fi
}

# 主函数
main() {
    # 解析命令行参数
    FORCE_MODE=false
    CLEANUP_ONLY=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--force)
                FORCE_MODE=true
                shift
                ;;
            -c|--cleanup-only)
                CLEANUP_ONLY=true
                shift
                ;;
            -h|--help)
                echo "用法: $0 [选项]"
                echo ""
                echo "选项:"
                echo "  -f, --force        强制停止，不询问确认"
                echo "  -c, --cleanup-only 仅执行清理，不停止进程"
                echo "  -h, --help         显示此帮助信息"
                echo ""
                echo "示例:"
                echo "  $0                 # 正常停止策略"
                echo "  $0 -f              # 强制停止策略"
                echo "  $0 -c              # 仅执行清理"
                exit 0
                ;;
            *)
                print_error "未知选项: $1"
                exit 1
                ;;
        esac
    done
    
    # 显示停止前状态
    show_pre_stop_status
    
    # 如果仅执行清理
    if [ "$CLEANUP_ONLY" = true ]; then
        print_info "仅执行清理操作..."
        execute_manual_cleanup
        exit $?
    fi
    
    # 确认停止操作 (除非强制模式)
    if [ "$FORCE_MODE" = false ]; then
        confirm_stop
    fi
    
    # 执行停止流程
    local stop_success=true
    local cleanup_success=true
    
    # 1. 停止策略进程
    if ! stop_strategy_process; then
        stop_success=false
    fi
    
    # 2. 执行手动清理
    if ! execute_manual_cleanup; then
        cleanup_success=false
    fi
    
    # 显示停止后状态
    show_post_stop_status
    
    # 返回结果
    if [ "$stop_success" = true ] && [ "$cleanup_success" = true ]; then
        print_success "策略停止和清理操作全部完成！"
        exit 0
    else
        print_error "部分操作失败，请检查上述输出"
        exit 1
    fi
}

# 执行主函数
main "$@"
