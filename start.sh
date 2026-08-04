#!/usr/bin/env bash

# 说明：
# 保留一个简短入口，兼容习惯执行 ./start.sh 的场景。
# 真正的启动逻辑集中在 start_wiki.sh，避免两个脚本出现行为分叉。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/start_wiki.sh" "$@"
