#!/usr/bin/env bash

# 说明：
# 这个脚本用于统一管理 Wiki 的容器化运行流程。
# 前端、后端与基础依赖都会通过 docker compose 构建或启动，
# 宿主机只映射 Wiki Web 端口，其余服务仅在 Docker 内部网络中互通。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/wiki-backend"
WEB_DIR="${ROOT_DIR}/wiki-web"
COMPOSE_FILE="${BACKEND_DIR}/anythingllm/compose.yml"
DEV_COMPOSE_FILE="${BACKEND_DIR}/anythingllm/compose.dev.yml"

CONFIG_ENV_KEYS=(
  UV_DEFAULT_INDEX
  WEB_PORT
  WEB_BIND_HOST
  WEB_PUBLIC_HOST
  WEB_PUBLIC_ORIGIN
  NEXT_PUBLIC_API_URL
  NEXT_PUBLIC_CHATBOT_ASSISTANT_NAME
  NEXT_PUBLIC_CHATBOT_GREETING
  NEXT_PUBLIC_CHATBOT_PLACEHOLDER
  NEXT_PUBLIC_CHATBOT_DEFAULT_MESSAGES
  NEXT_PUBLIC_CHATBOT_PROMPT
  NEXT_PUBLIC_CHATBOT_MODEL
  NEXT_PUBLIC_CHATBOT_TEMPERATURE
)

load_root_env() {
  local env_file="${ROOT_DIR}/.env"
  local existing_env_keys=()

  if [[ ! -f "${env_file}" ]]; then
    return 0
  fi

  # 说明：
  # 根目录 .env 是统一配置源。加载前记录调用方已经显式传入的变量，
  # 加载后再恢复这些值，保证 `WEB_PORT=3002 ./start.sh start` 这类临时覆盖仍然生效。
  for key in "${CONFIG_ENV_KEYS[@]}"; do
    if [[ "${!key+x}" == "x" ]]; then
      existing_env_keys+=("${key}")
      eval "EXISTING_${key}=\"\${${key}}\""
    fi
  done

  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a

  # 说明：
  # macOS 自带 Bash 版本较旧，在 `set -u` 下展开空数组会触发 unbound variable。
  # 因此只有存在需要恢复的外部变量时才遍历数组。
  if (( ${#existing_env_keys[@]} > 0 )); then
    for key in "${existing_env_keys[@]}"; do
      eval "${key}=\"\${EXISTING_${key}}\""
      export "${key}"
    done
  fi
}

load_root_env

# 说明：
# WEB_BIND_HOST 控制 Docker 监听在哪个宿主机地址上，默认只允许本机访问。
# WEB_PUBLIC_HOST 用于生成浏览器侧访问地址，避免在绑定 0.0.0.0 时把不可访问的地址写进前端构建产物。
WEB_PORT="${WEB_PORT:-3000}"
WEB_BIND_HOST="${WEB_BIND_HOST:-127.0.0.1}"
WEB_PUBLIC_HOST="${WEB_PUBLIC_HOST:-127.0.0.1}"
WEB_PUBLIC_ORIGIN="${WEB_PUBLIC_ORIGIN:-http://${WEB_PUBLIC_HOST}:${WEB_PORT}}"

info() {
  printf '[INFO] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

error() {
  printf '[ERROR] %s\n' "$1" >&2
}

usage() {
  cat <<'EOF'
用法：
  ./start_wiki.sh start      构建镜像并启动 Wiki Web、Wiki Backend 与依赖服务
  ./start_wiki.sh dev        以调试模式启动（当前与 start 行为一致，历史兼容）
  ./start_wiki.sh stop       停止并移除整套 compose 服务
  ./start_wiki.sh restart    重启整套容器环境
  ./start_wiki.sh restart-dev 重启调试模式环境
  ./start_wiki.sh status     查看容器运行状态
  ./start_wiki.sh logs       查看最近容器日志
  ./start_wiki.sh help       查看帮助

可选环境变量：
  根目录 .env                统一配置入口，可从 .env.example 复制后填写
  WEB_PORT=3000              宿主机开放的 Wiki Web 端口
  WEB_BIND_HOST=127.0.0.1    宿主机监听地址
  WEB_PUBLIC_HOST=127.0.0.1  写入前端构建产物的浏览器访问主机
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_compose_cmd() {
  # 说明：
  # 新版 Docker 通常使用 `docker compose`，旧环境可能只有 `docker-compose`。
  # 这里保留两种命令兼容，减少不同开发机之间的启动差异。
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return 0
  fi

  if command_exists docker-compose; then
    COMPOSE_CMD=(docker-compose)
    return 0
  fi

  error "未检测到 docker compose 或 docker-compose，请先安装 Docker。"
  exit 1
}

require_commands() {
  # 说明：
  # 前后端现在都在镜像内构建与运行，宿主机只需要 Docker 与 compose 能力。
  # Python、Node 依赖由各自 Dockerfile 在构建阶段处理。
  if ! command_exists docker; then
    error "缺少必要命令：docker"
    exit 1
  fi

  detect_compose_cmd
}

ensure_project_files() {
  local include_dev="${1:-false}"

  # 说明：
  # 在启动前先检查关键文件，能把路径问题变成明确报错，
  # 避免 compose 构建时输出一长串难定位的上下文错误。
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    error "未找到 compose 文件：${COMPOSE_FILE}"
    exit 1
  fi

  if [[ ! -f "${BACKEND_DIR}/Dockerfile" ]]; then
    error "未找到后端 Dockerfile：${BACKEND_DIR}/Dockerfile"
    exit 1
  fi

  if [[ ! -f "${WEB_DIR}/Dockerfile" ]]; then
    error "未找到前端 Dockerfile：${WEB_DIR}/Dockerfile"
    exit 1
  fi

  if [[ "${include_dev}" == "true" ]] && [[ ! -f "${DEV_COMPOSE_FILE}" ]]; then
    error "未找到 dev compose 文件：${DEV_COMPOSE_FILE}"
    exit 1
  fi
}

prepare_compose_env() {
  # 说明：
  # docker compose 会从当前进程环境读取这些变量。
  # NEXT_PUBLIC_* 需要在镜像构建阶段写入前端产物，因此这里统一导出。
  export WEB_PORT
  export WEB_BIND_HOST
  export WEB_PUBLIC_HOST
  export WEB_PUBLIC_ORIGIN
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-${WEB_PUBLIC_ORIGIN}/wiki-api}"

  # 说明：这些变量会在前端构建阶段写入客户端产物，因此需要显式导出给 compose build args。
  export NEXT_PUBLIC_CHATBOT_ASSISTANT_NAME="${NEXT_PUBLIC_CHATBOT_ASSISTANT_NAME:-}"
  export NEXT_PUBLIC_CHATBOT_GREETING="${NEXT_PUBLIC_CHATBOT_GREETING:-}"
  export NEXT_PUBLIC_CHATBOT_PLACEHOLDER="${NEXT_PUBLIC_CHATBOT_PLACEHOLDER:-}"
  export NEXT_PUBLIC_CHATBOT_DEFAULT_MESSAGES="${NEXT_PUBLIC_CHATBOT_DEFAULT_MESSAGES:-}"
  export NEXT_PUBLIC_CHATBOT_PROMPT="${NEXT_PUBLIC_CHATBOT_PROMPT:-}"
  export NEXT_PUBLIC_CHATBOT_MODEL="${NEXT_PUBLIC_CHATBOT_MODEL:-}"
  export NEXT_PUBLIC_CHATBOT_TEMPERATURE="${NEXT_PUBLIC_CHATBOT_TEMPERATURE:-}"
}

wait_for_http() {
  local url="$1"
  local name="$2"
  local timeout="${3:-120}"
  local elapsed=0

  info "等待 ${name} 健康检查通过：${url}"
  while (( elapsed < timeout )); do
    # 说明：
    # 优先使用 curl 验证 HTTP 响应；没有 curl 时退化为端口连通性检查。
    if command_exists curl && curl -fsS "${url}" >/dev/null 2>&1; then
      info "${name} 已通过健康检查。"
      return 0
    fi

    if ! command_exists curl && command_exists nc; then
      local host_and_port="${url#http://}"
      host_and_port="${host_and_port%%/*}"
      local host="${host_and_port%%:*}"
      local port="${host_and_port##*:}"

      if nc -z "${host}" "${port}" >/dev/null 2>&1; then
        info "${name} 端口已开放。"
        return 0
      fi
    fi

    sleep 1
    elapsed=$((elapsed + 1))
  done

  error "等待 ${name} 健康检查超时。"
  return 1
}

start_all() {
  require_commands
  ensure_project_files false
  prepare_compose_env

  info "构建并启动 Wiki 容器服务 ..."
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" up -d --build

  wait_for_http "${WEB_PUBLIC_ORIGIN}" "Wiki Web" 180

  printf '\n启动完成：\n'
  printf '  前端地址: %s\n' "${WEB_PUBLIC_ORIGIN}"
  printf '  对外开放端口: %s:%s -> wiki-web:3000\n' "${WEB_BIND_HOST}" "${WEB_PORT}"
  printf '  内部后端代理: %s/wiki-api\n' "${WEB_PUBLIC_ORIGIN}"
  printf '  聊天接口: %s/api/chat\n' "${WEB_PUBLIC_ORIGIN}"
}

start_dev() {
  local compose_options=(-f "${COMPOSE_FILE}" -f "${DEV_COMPOSE_FILE}")
  require_commands
  ensure_project_files true
  prepare_compose_env

  info "以 dev 模式构建并启动 Wiki 容器服务 ..."
  "${COMPOSE_CMD[@]}" "${compose_options[@]}" up -d --build

  wait_for_http "${WEB_PUBLIC_ORIGIN}" "Wiki Web" 180

  printf '\nDev 模式启动完成：\n'
  printf '  前端地址: %s\n' "${WEB_PUBLIC_ORIGIN}"
  printf '  对外开放端口: %s:%s -> wiki-web:3000\n' "${WEB_BIND_HOST}" "${WEB_PORT}"
}

stop_all() {
  require_commands
  prepare_compose_env

  info "停止并移除 Wiki 容器服务 ..."
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" down
}

show_status() {
  require_commands
  prepare_compose_env

  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" ps
}

show_logs() {
  require_commands
  prepare_compose_env

  # 说明：
  # 只展示最近一小段日志，便于快速排查启动失败原因。
  # 如需持续跟踪，可直接执行 docker compose logs -f。
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" logs --tail 80
}

main() {
  local action="${1:-help}"

  case "${action}" in
    start)
      start_all
      ;;
    dev)
      start_dev
      ;;
    stop)
      stop_all
      ;;
    restart)
      stop_all
      start_all
      ;;
    restart-dev)
      stop_all
      start_dev
      ;;
    status)
      show_status
      ;;
    logs)
      show_logs
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      error "未知命令：${action}"
      usage
      exit 1
      ;;
  esac
}

main "$@"
