#!/usr/bin/env bash
# launch.sh — 一键启动 Agent Team 可视化服务
# 用法: ./launch.sh [选项] [teams-目录路径]
# 选项:
#   --port <端口>    指定服务端口（默认 8765）
#   --poll           使用轮询模式监听文件变化（适用于 NFS/Docker）
#   --no-browser     不自动打开浏览器
#   -h, --help       显示帮助信息
#
# 如果不指定 teams 目录，脚本会自动向上查找 .codebuddy/teams/ 目录。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PORT=8765
POLL=""
TEAMS_DIR=""
NO_BROWSER=0

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

show_help() {
    echo "用法: ./launch.sh [选项] [teams-目录路径]"
    echo ""
    echo "启动 Agent Team 可视化 Web 服务"
    echo ""
    echo "如果不指定 teams 目录，脚本会自动向上查找 .codebuddy/teams/ 目录。"
    echo ""
    echo "选项:"
    echo "  --port <端口>    指定服务端口（默认 8765）"
    echo "  --poll           使用轮询模式监听文件变化"
    echo "  --no-browser     不自动打开浏览器"
    echo "  -h, --help       显示帮助信息"
    echo ""
    echo "示例:"
    echo "  ./launch.sh                                     # 自动检测 teams 目录"
    echo "  ./launch.sh /path/to/.codebuddy/teams/          # 指定 teams 目录"
    echo "  ./launch.sh --port 9000                         # 自定义端口"
    echo "  ./launch.sh --poll                              # 轮询模式（Docker 环境）"
    echo "  ./launch.sh --no-browser /path/to/teams/        # 不自动打开浏览器"
}

# 自动检测 .codebuddy/teams/ 目录
# 从当前目录开始，逐级向上查找，最多 10 级
auto_detect_teams_dir() {
    local search_dir="$PWD"
    local max_depth=10
    local depth=0

    while [[ "$depth" -lt "$max_depth" ]]; do
        local candidate="$search_dir/.codebuddy/teams"
        if [[ -d "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
        local parent="$(dirname "$search_dir")"
        # 已到根目录
        if [[ "$parent" == "$search_dir" ]]; then
            break
        fi
        search_dir="$parent"
        depth=$((depth + 1))
    done

    return 1
}

# 尝试打开浏览器
open_browser() {
    local url="$1"
    # 延迟 1.5 秒等服务启动
    (
        sleep 1.5
        if command -v xdg-open &> /dev/null; then
            xdg-open "$url" 2>/dev/null || true
        elif command -v open &> /dev/null; then
            open "$url" 2>/dev/null || true
        elif command -v start &> /dev/null; then
            start "$url" 2>/dev/null || true
        fi
    ) &
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --poll)
            POLL="--poll"
            shift
            ;;
        --no-browser)
            NO_BROWSER=1
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo -e "${RED}❌ 未知选项: $1${NC}"
            show_help
            exit 1
            ;;
        *)
            TEAMS_DIR="$1"
            shift
            ;;
    esac
done

# 如果未指定 teams 目录，自动检测
if [[ -z "$TEAMS_DIR" ]]; then
    echo -e "${CYAN}🔍 未指定 teams 目录，自动检测中...${NC}"
    detected_dir="$(auto_detect_teams_dir || true)"
    if [[ -n "$detected_dir" ]]; then
        TEAMS_DIR="$detected_dir"
        echo -e "${GREEN}✅ 检测到 teams 目录: $TEAMS_DIR${NC}"
    else
        echo -e "${YELLOW}⚠️  未检测到 .codebuddy/teams/ 目录${NC}"
        echo -e "${YELLOW}   将使用当前目录下的 .codebuddy/teams/（启动后等待数据）${NC}"
        TEAMS_DIR="$PWD/.codebuddy/teams"
    fi
fi

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 未找到 python3，请先安装 Python 3.8+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${CYAN}🐍 Python 版本: $PYTHON_VERSION${NC}"

# 检查 teams 目录是否存在
if [[ ! -d "$TEAMS_DIR" ]]; then
    echo -e "${YELLOW}⚠️  指定的目录不存在: $TEAMS_DIR，将在该路径上等待数据...${NC}"
fi

# 创建虚拟环境（如果不存在）
if [[ ! -d "$VENV_DIR" ]]; then
    echo -e "${CYAN}📦 创建虚拟环境...${NC}"
    python3 -m venv "$VENV_DIR"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 安装依赖（如果 requirements.txt 比 .installed 标记文件新）
INSTALLED_MARKER="$VENV_DIR/.installed"
if [[ ! -f "$INSTALLED_MARKER" ]] || [[ "$SCRIPT_DIR/requirements.txt" -nt "$INSTALLED_MARKER" ]]; then
    echo -e "${CYAN}📦 安装依赖...${NC}"
    pip install -q -r "$SCRIPT_DIR/requirements.txt"
    touch "$INSTALLED_MARKER"
fi

# 优雅停止
cleanup() {
    echo ""
    echo -e "${GREEN}👋 服务已停止${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# 启动服务
echo -e "${GREEN}🚀 启动 Agent Team 可视化服务...${NC}"
echo -e "${GREEN}🌐 访问地址: http://localhost:${PORT}${NC}"
echo -e "${CYAN}📂 监听目录: $TEAMS_DIR${NC}"
echo ""

# 自动打开浏览器
if [[ "$NO_BROWSER" -eq 0 ]]; then
    open_browser "http://localhost:${PORT}"
fi

python3 "$SCRIPT_DIR/server/main.py" \
    --teams-dir "$TEAMS_DIR" \
    --port "$PORT" \
    $POLL
