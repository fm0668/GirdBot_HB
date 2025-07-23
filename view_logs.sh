#!/bin/bash

# =============================================================================
# 双账户对冲网格策略 - 日志查看脚本
# 用于查看策略运行状态和重要信息
# =============================================================================

# 脚本配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="DualGridBot"
PID_FILE="$SCRIPT_DIR/${PROJECT_NAME}.pid"
LOG_FILE="$SCRIPT_DIR/logs/dual_grid_bot.log"
STARTUP_LOG="$SCRIPT_DIR/startup.log"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
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

print_data() {
    echo -e "${PURPLE}$1${NC}"
}

# 检查策略是否在运行
check_strategy_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ 策略正在运行${NC} (PID: $PID)"
            
            # 获取进程信息
            PROCESS_INFO=$(ps -p "$PID" -o pid,ppid,cmd,etime,pcpu,pmem --no-headers)
            echo -e "${BLUE}进程信息:${NC} $PROCESS_INFO"
            
            return 0
        else
            echo -e "${RED}❌ 策略未运行${NC} (PID文件存在但进程不存在)"
            return 1
        fi
    else
        echo -e "${RED}❌ 策略未运行${NC} (PID文件不存在)"
        return 1
    fi
}

# 显示策略状态摘要
show_strategy_summary() {
    print_header "=============================================================="
    print_header "  双账户对冲网格策略 - 运行状态"
    print_header "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
    print_header "=============================================================="
    echo ""
    
    # 检查策略状态
    check_strategy_status
    echo ""
    
    # 检查日志文件
    if [ -f "$LOG_FILE" ]; then
        LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
        LOG_LINES=$(wc -l < "$LOG_FILE")
        print_info "日志文件: $LOG_FILE"
        print_info "日志大小: $LOG_SIZE, 行数: $LOG_LINES"
        
        # 显示最新的策略状态
        echo ""
        print_header "📊 最新策略状态:"
        grep "Strategy Status" "$LOG_FILE" | tail -3 | while read line; do
            echo -e "${PURPLE}$line${NC}"
        done
        
        # 显示网格信息
        echo ""
        print_header "🔧 网格配置信息:"
        grep -E "(网格层数|Grid Levels|实际生成的网格层数)" "$LOG_FILE" | tail -3 | while read line; do
            echo -e "${PURPLE}$line${NC}"
        done
        
        # 显示交易统计
        echo ""
        print_header "💰 交易统计 (最近10条):"
        grep -E "(已成交|交易完成|净收益)" "$LOG_FILE" | tail -10 | while read line; do
            echo -e "${PURPLE}$line${NC}"
        done
        
        # 显示错误信息
        echo ""
        print_header "⚠️  最近错误 (如有):"
        grep -E "(ERROR|CRITICAL)" "$LOG_FILE" | tail -5 | while read line; do
            echo -e "${RED}$line${NC}"
        done
        
        # 显示余额信息
        echo ""
        print_header "💳 账户余额信息:"
        grep -E "(余额|balance|名义价值)" "$LOG_FILE" | tail -5 | while read line; do
            echo -e "${PURPLE}$line${NC}"
        done
        
    else
        print_warning "日志文件不存在: $LOG_FILE"
    fi
}

# 显示实时日志
show_live_logs() {
    if [ -f "$LOG_FILE" ]; then
        print_info "显示实时日志 (按Ctrl+C退出)..."
        echo ""
        tail -f "$LOG_FILE" | while read line; do
            # 根据日志级别着色
            if echo "$line" | grep -q "ERROR"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -q "WARNING"; then
                echo -e "${YELLOW}$line${NC}"
            elif echo "$line" | grep -q "SUCCESS\|成功\|✅"; then
                echo -e "${GREEN}$line${NC}"
            elif echo "$line" | grep -q "Strategy Status\|交易完成\|已成交"; then
                echo -e "${CYAN}$line${NC}"
            else
                echo "$line"
            fi
        done
    else
        print_error "日志文件不存在: $LOG_FILE"
        exit 1
    fi
}

# 显示最近日志
show_recent_logs() {
    local lines=${1:-50}
    
    if [ -f "$LOG_FILE" ]; then
        print_info "显示最近 $lines 行日志:"
        echo ""
        tail -n "$lines" "$LOG_FILE" | while read line; do
            # 根据日志级别着色
            if echo "$line" | grep -q "ERROR"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -q "WARNING"; then
                echo -e "${YELLOW}$line${NC}"
            elif echo "$line" | grep -q "SUCCESS\|成功\|✅"; then
                echo -e "${GREEN}$line${NC}"
            elif echo "$line" | grep -q "Strategy Status\|交易完成\|已成交"; then
                echo -e "${CYAN}$line${NC}"
            else
                echo "$line"
            fi
        done
    else
        print_error "日志文件不存在: $LOG_FILE"
        exit 1
    fi
}

# 搜索日志
search_logs() {
    local keyword="$1"
    
    if [ -z "$keyword" ]; then
        print_error "请提供搜索关键词"
        exit 1
    fi
    
    if [ -f "$LOG_FILE" ]; then
        print_info "搜索关键词: '$keyword'"
        echo ""
        grep -i --color=always "$keyword" "$LOG_FILE" | tail -20
    else
        print_error "日志文件不存在: $LOG_FILE"
        exit 1
    fi
}

# 显示帮助信息
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  status          显示策略状态摘要 (默认)"
    echo "  live            显示实时日志"
    echo "  recent [N]      显示最近N行日志 (默认50行)"
    echo "  search <关键词>  搜索日志中的关键词"
    echo "  help            显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                    # 显示策略状态摘要"
    echo "  $0 live              # 显示实时日志"
    echo "  $0 recent 100        # 显示最近100行日志"
    echo "  $0 search 'ERROR'    # 搜索错误信息"
}

# 主函数
main() {
    case "${1:-status}" in
        "status")
            show_strategy_summary
            ;;
        "live")
            show_live_logs
            ;;
        "recent")
            show_recent_logs "${2:-50}"
            ;;
        "search")
            search_logs "$2"
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            print_error "未知选项: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
