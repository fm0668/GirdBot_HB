#!/bin/bash

# =============================================================================
# 双账户对冲网格策略 - 启动脚本
# 用于在VPS上启动策略并保持后台运行
# =============================================================================

# 脚本配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="DualGridBot"
PYTHON_SCRIPT="main.py"
PID_FILE="$SCRIPT_DIR/${PROJECT_NAME}.pid"
LOG_FILE="$SCRIPT_DIR/logs/dual_grid_bot.log"
STARTUP_LOG="$SCRIPT_DIR/startup.log"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# 检查是否已经在运行
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

# 创建必要的目录
create_directories() {
    print_info "创建必要的目录..."
    mkdir -p "$SCRIPT_DIR/logs"
    mkdir -p "$SCRIPT_DIR/backup"
}

# 检查Python环境和依赖
check_environment() {
    print_info "检查Python环境..."
    
    # 检查Python版本
    if ! python3 --version > /dev/null 2>&1; then
        print_error "Python3 未安装或不在PATH中"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    print_info "Python版本: $PYTHON_VERSION"
    
    # 检查主要依赖
    print_info "检查依赖包..."
    if ! python3 -c "import asyncio, ccxt, websockets, python_dotenv" > /dev/null 2>&1; then
        print_warning "某些依赖包可能缺失，尝试安装..."
        pip3 install -r requirements.txt
    fi
}

# 检查配置文件
check_configuration() {
    print_info "检查配置文件..."
    
    # 检查.env文件
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        print_error ".env文件不存在，请先配置API密钥"
        print_info "请复制.env.example为.env并填入您的API密钥"
        exit 1
    fi
    
    # 检查config.py
    if [ ! -f "$SCRIPT_DIR/config.py" ]; then
        print_error "config.py文件不存在"
        exit 1
    fi
    
    print_success "配置文件检查通过"
}

# 备份日志文件
backup_logs() {
    if [ -f "$LOG_FILE" ]; then
        BACKUP_NAME="dual_grid_bot_$(date +%Y%m%d_%H%M%S).log"
        print_info "备份现有日志文件为: $BACKUP_NAME"
        cp "$LOG_FILE" "$SCRIPT_DIR/backup/$BACKUP_NAME"
        
        # 保留最近10个备份文件
        cd "$SCRIPT_DIR/backup" && ls -t dual_grid_bot_*.log | tail -n +11 | xargs -r rm
    fi
}

# 启动策略
start_strategy() {
    print_info "启动双账户对冲网格策略..."
    
    # 切换到项目目录
    cd "$SCRIPT_DIR"
    
    # 启动Python脚本并获取PID
    nohup python3 "$PYTHON_SCRIPT" > "$STARTUP_LOG" 2>&1 &
    STRATEGY_PID=$!
    
    # 保存PID
    echo "$STRATEGY_PID" > "$PID_FILE"
    
    print_info "策略已启动，PID: $STRATEGY_PID"
    print_info "启动日志: $STARTUP_LOG"
    print_info "运行日志: $LOG_FILE"
    
    # 等待几秒检查启动状态
    sleep 5
    
    if ps -p "$STRATEGY_PID" > /dev/null 2>&1; then
        print_success "策略启动成功！"
        print_info "使用以下命令查看日志:"
        print_info "  实时日志: ./view_logs.sh"
        print_info "  停止策略: ./stop_trading.sh"
        return 0
    else
        print_error "策略启动失败，请检查启动日志: $STARTUP_LOG"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 显示状态信息
show_status() {
    echo ""
    echo "=============================================================="
    echo "  双账户对冲网格策略 - 启动脚本"
    echo "  项目目录: $SCRIPT_DIR"
    echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=============================================================="
    echo ""
}

# 主函数
main() {
    show_status
    
    # 检查是否已经在运行
    if check_if_running; then
        PID=$(cat "$PID_FILE")
        print_warning "策略已经在运行中 (PID: $PID)"
        print_info "如需重启，请先运行: ./stop_trading.sh"
        exit 1
    fi
    
    # 执行启动流程
    create_directories
    check_environment
    check_configuration
    backup_logs
    
    # 启动策略
    if start_strategy; then
        echo ""
        print_success "双账户对冲网格策略已成功启动！"
        echo ""
        print_info "📊 监控命令:"
        print_info "  查看实时日志: ./view_logs.sh"
        print_info "  查看策略状态: ./view_logs.sh status"
        print_info "  停止策略: ./stop_trading.sh"
        echo ""
        print_info "📁 重要文件:"
        print_info "  运行日志: $LOG_FILE"
        print_info "  PID文件: $PID_FILE"
        print_info "  启动日志: $STARTUP_LOG"
        echo ""
    else
        print_error "策略启动失败！"
        exit 1
    fi
}

# 执行主函数
main "$@"
