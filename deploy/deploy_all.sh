#!/usr/bin/env bash
# ========================================
# deploy_all.sh — 主系统(industrial-ai 全家桶) + RAGFlow 同机一键部署 + 链路自检
#
# 在目标服务器(Linux)上执行。做的事：
#   环境检查 → clone/启动 RAGFlow（自动把跟主项目必撞的 MinIO 9000/9001 改成
#   19000/19001）→ 探测本机 IP，把主项目 deploy/docker/.env 的 RAGFLOW_BASE_URL
#   校正为 http://<本机IP>:<RAGFlow实际API端口> → 启动主系统 → 等健康 →
#   从容器内部实测连 RAGFlow + 校验 API key + 检查 ID 类配置是否已回填。
#
# 用法：./deploy_all.sh [操作]
#   install   首次部署（默认）；幂等，重复执行等价于 up
#   up        同 install
#   check     只自检不启动、不改任何文件：容器状态、RAGFLOW_BASE_URL 指向、
#             容器内连通性、API key 有效性、ID 回填情况（回填完配置后跑这个验证）
#   status    两套栈的容器状态 + 访问地址
#   down      停止两套栈（数据卷保留，永远不带 -v）
#
# 可选环境变量：
#   HOST_IP=10.x.x.x                  跳过自动探测，指定本机对外 IP
#   DEPLOY_PROFILES="local-db mqtt"   主系统要启用的 compose profile（空=默认服务）
#   DEPLOY_BUILD=1                    主系统 up 时加 --build（默认复用已有/已 load 镜像）
#   SKIP_PREFLIGHT=1                  vm.max_map_count 不达标时仍继续
#   RAGFLOW_URL_OVERWRITE=1           RAGFLOW_BASE_URL 指向别的机器时也强制改成本机
#
# 前提：deploy/docker/.env 已按 .env.example 建好（脚本只校正 RAGFLOW_BASE_URL，
# 其它值不动）。离线服务器先按 deploy/ragflow/README.md 用 save-images/load-images
# 把 RAGFlow 镜像 load 进来，主镜像照旧 build.bat 产物 docker load。
#
# 首次部署后仍有几步没法自动化（要在 RAGFlow 网页里点）：注册管理员 → 配模型供应商
# → 生成 API key → 建数据集 + 两个聊天助手 → 回填 .env → ./deploy_all.sh up 重启生效
# → ./deploy_all.sh check 复查。清单见 deploy/ragflow/README.md「部署完成后」。
# ========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCKER_DIR="$SCRIPT_DIR/docker"
RAGFLOW_DIR="$SCRIPT_DIR/ragflow"
MAIN_ENV="$DOCKER_DIR/.env"
RF_ENV="$RAGFLOW_DIR/ragflow-src/docker/.env"

ACTION="${1:-install}"
IP=""

FAILS=0
WARNS=0
ok()   { echo -e "${GREEN}[v] $*${NC}"; }
bad()  { echo -e "${RED}[x] $*${NC}"; FAILS=$((FAILS+1)); }
note() { echo -e "${YELLOW}[!] $*${NC}"; WARNS=$((WARNS+1)); }
say()  { echo -e "${YELLOW}$*${NC}"; }

# ---------- 通用工具 ----------

# 读主项目 .env 里某个变量（最后一次出现为准，容忍 CRLF）
_main_env() {
    grep -E "^[[:space:]]*$1=" "$MAIN_ENV" 2>/dev/null | tail -1 | cut -d= -f2- \
        | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

# 改/追加主项目 .env 的变量（改前备份一次）
_ENV_BACKED_UP=0
_set_main_env() {
    if [ "$_ENV_BACKED_UP" = "0" ]; then
        cp "$MAIN_ENV" "$MAIN_ENV.bak-$(date +%Y%m%d-%H%M%S)"
        _ENV_BACKED_UP=1
    fi
    if grep -qE "^[[:space:]]*$1=" "$MAIN_ENV"; then
        sed -i "s|^[[:space:]]*$1=.*|$1=$2|" "$MAIN_ENV"
    else
        printf '\n%s=%s\n' "$1" "$2" >> "$MAIN_ENV"
    fi
}

# 读 RAGFlow 官方 .env 里某个变量（未 clone/键不存在时用默认值 $2）
_rf_env() {
    local v=""
    if [ -f "$RF_ENV" ]; then
        v=$(grep -E "^[[:space:]]*$1=" "$RF_ENV" | tail -1 | cut -d= -f2- | tr -d '"\r' | tr -d '[:space:]')
    fi
    echo "${v:-$2}"
}

# HTTP 状态码（失败输出 000；--noproxy 防企业代理劫持本机地址）
_http_code() {
    curl --noproxy '*' -s -o /dev/null -w '%{http_code}' -m "${2:-5}" "$1" 2>/dev/null || true
}

_detect_ip() {
    if [ -n "${HOST_IP:-}" ]; then
        IP="$HOST_IP"
    else
        IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}')
        [ -z "$IP" ] && IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    if [ -z "$IP" ]; then
        bad "探测不到本机对外 IP，用 HOST_IP=10.x.x.x ./deploy_all.sh $ACTION 指定"
        exit 1
    fi
    say "本机 IP：$IP（不对就用 HOST_IP= 覆盖）"
}

compose_main() {
    local profiles=() p
    for p in ${DEPLOY_PROFILES:-}; do profiles+=(--profile "$p"); done
    (cd "$DOCKER_DIR" && docker compose "${profiles[@]}" -f docker-compose.yml "$@")
}

_container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$1"
}

# ---------- 检查/步骤 ----------

preflight() {
    if ! command -v docker >/dev/null 2>&1; then
        bad "docker 未安装"; exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        bad "docker compose v2 不可用"; exit 1
    fi
    if [ "$(uname -s)" = "Linux" ]; then
        local mmc
        mmc=$(sysctl -n vm.max_map_count 2>/dev/null || echo 0)
        if [ "${mmc:-0}" -lt 262144 ]; then
            bad "vm.max_map_count=${mmc}，需 >= 262144（RAGFlow 的 Elasticsearch 起不来）"
            echo    "    修复: sudo sysctl -w vm.max_map_count=262144"
            echo    "         echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.conf && sudo sysctl -p"
            if [ "$1" = "strict" ] && [ "${SKIP_PREFLIGHT:-0}" != "1" ]; then
                echo -e "${RED}先修复再跑；确要跳过用 SKIP_PREFLIGHT=1${NC}"
                exit 1
            fi
        else
            ok "vm.max_map_count=${mmc}"
        fi
    fi
}

ensure_main_env() {
    if [ ! -f "$MAIN_ENV" ]; then
        bad "缺 $MAIN_ENV —— 参考同目录 .env.example 创建并填入真实值后重跑"
        exit 1
    fi
    ok "主项目 .env 存在"
}

# RAGFlow 侧端口消歧：MinIO 9000/9001 与主项目 minio 必撞，默认值时自动挪走
patch_rf_ports() {
    [ -f "$RF_ENV" ] || { note "RAGFlow .env 还不存在（未 clone？），跳过端口消歧"; return 0; }
    local spec key def new cur
    for spec in "MINIO_PORT|9000|19000" "MINIO_CONSOLE_PORT|9001|19001"; do
        key="${spec%%|*}"; def="$(echo "$spec" | cut -d'|' -f2)"; new="${spec##*|}"
        cur=$(_rf_env "$key" "")
        if [ "$cur" = "$def" ]; then
            sed -i "s|^[[:space:]]*${key}=.*|${key}=${new}|" "$RF_ENV"
            say "RAGFlow ${key}: ${def} → ${new}（避开主项目 minio 的 ${def}）"
        elif [ -z "$cur" ]; then
            note "RAGFlow .env 里没找到 ${key}（版本差异？），无法自动消歧，手动确认别撞主项目 ${def}"
        fi
    done
}

# 把主项目 .env 的 RAGFLOW_BASE_URL 对齐到本机 RAGFlow。$1: fix=写回 / checkonly=只报告
reconcile_base_url() {
    local mode="$1" port want cur
    port=$(_rf_env SVR_HTTP_PORT 9380)
    want="http://${IP}:${port}"
    cur=$(_main_env RAGFLOW_BASE_URL)

    if [ "$cur" = "$want" ]; then
        ok "RAGFLOW_BASE_URL=$want（已指向本机 RAGFlow）"
        return 0
    fi
    if [ "$mode" = "checkonly" ]; then
        bad "RAGFLOW_BASE_URL=$cur，应为 $want（./deploy_all.sh up 会自动改）"
        return 0
    fi
    case "$cur" in
        ""|*localhost*|*127.0.0.1*|*your-ragflow-host*)
            _set_main_env RAGFLOW_BASE_URL "$want"
            say "RAGFLOW_BASE_URL: '${cur:-<空>}' → $want（原 .env 已备份 .bak-*；容器内 localhost 不通）"
            ;;
        *)
            if [ "${RAGFLOW_URL_OVERWRITE:-0}" = "1" ]; then
                _set_main_env RAGFLOW_BASE_URL "$want"
                say "RAGFLOW_BASE_URL: $cur → $want（RAGFLOW_URL_OVERWRITE=1 强制切到本机）"
            else
                note "RAGFLOW_BASE_URL=$cur 指向别的机器（外部 RAGFlow？），没动它。"
                note "  确定要切到本机自建实例：RAGFLOW_URL_OVERWRITE=1 ./deploy_all.sh up"
                note "  注意切实例后 API key/数据集/助手 ID 要重建回填（deploy/ragflow/README.md）"
            fi
            ;;
    esac
}

# 等 URL 有响应。$3: any=通了就行 / 200=必须 200
wait_http() {
    local url="$1" timeout="$2" expect="$3" name="$4" t=0 code
    while [ "$t" -lt "$timeout" ]; do
        code=$(_http_code "$url" 5)
        if [ "$expect" = "200" ] && [ "$code" = "200" ]; then
            ok "$name 就绪（HTTP 200 @ $url，等了 ${t}s）"; return 0
        elif [ "$expect" = "any" ] && [ -n "$code" ] && [ "$code" != "000" ]; then
            ok "$name 就绪（HTTP $code @ $url，等了 ${t}s）"; return 0
        fi
        sleep 5; t=$((t+5))
    done
    note "$name 等了 ${timeout}s 未就绪（$url）——首次启动拉镜像/下模型可能更久，稍后 ./deploy_all.sh check 复查"
}

# 链路自检：容器内可达性 + API key + ID 回填
link_checks() {
    local base key code c v
    base=$(_main_env RAGFLOW_BASE_URL)
    if [ -z "$base" ]; then
        bad "主 .env 里没有 RAGFLOW_BASE_URL"; return 0
    fi

    # 宿主机 → RAGFlow
    code=$(_http_code "$base/" 5)
    if [ -n "$code" ] && [ "$code" != "000" ]; then
        ok "宿主机可达 $base（HTTP $code）"
    else
        bad "宿主机连不上 $base —— RAGFlow 没起来？端口不对？（./deploy_all.sh status 看容器）"
    fi

    # 容器内 → RAGFlow（这是主项目真正走的链路）
    for c in industrial-ai repair-suggestion; do
        if _container_running "$c"; then
            code=$(docker exec "$c" curl -s -o /dev/null -w '%{http_code}' -m 5 "$base/" 2>/dev/null || true)
            if [ -n "$code" ] && [ "$code" != "000" ]; then
                ok "$c 容器内可达 $base（HTTP $code）"
            else
                bad "$c 容器内连不上 $base —— 多半是防火墙拦了 docker 网段访问宿主机 IP（firewalld/iptables 放行 docker0 网段），或 IP 探测错了（HOST_IP= 覆盖）"
            fi
        else
            note "$c 容器未运行，跳过其链路检查"
        fi
    done

    # API key 有效性（拿 key 调一次 /api/v1/datasets）
    key=$(_main_env RAGFLOW_API_KEY)
    if [ -z "$key" ] || [ "$key" = "your-ragflow-api-key" ]; then
        note "RAGFLOW_API_KEY 未回填 —— 首次部署待办，见 deploy/ragflow/README.md「部署完成后」"
    else
        code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' -m 10 \
               -H "Authorization: Bearer $key" "$base/api/v1/datasets" 2>/dev/null || true)
        case "$code" in
            200)      ok "RAGFLOW_API_KEY 有效（/api/v1/datasets 返回 200）" ;;
            401|403)  bad "RAGFLOW_API_KEY 无效/过期（HTTP $code），去 RAGFlow 网页重新生成并回填" ;;
            *)        note "API key 校验请求异常（HTTP ${code:-000}），RAGFlow 可能还没就绪，稍后 check 复查" ;;
        esac
    fi

    # ID 类配置回填情况（缺哪个哪个功能拿不到知识库结果，不算部署失败）
    for v in RAGFLOW_DATASET_ID RAGFLOW_DOC_ASSISTANT_ID RAGFLOW_HISTORY_ASSISTANT_ID; do
        if [ -n "$(_main_env "$v")" ]; then
            ok "$v 已回填"
        else
            note "$v 未回填（知识库问答/维修建议/报警诊断对应功能会缺知识库结果）"
        fi
    done
}

check_main_health() {
    local app_port code
    app_port=$(_main_env APP_PORT); app_port="${app_port:-9300}"
    code=$(_http_code "http://127.0.0.1:${app_port}/api/health" 5)
    if [ "$code" = "200" ]; then
        ok "主系统健康（http://127.0.0.1:${app_port}/api/health = 200）"
    else
        bad "主系统 /api/health 返回 ${code:-000}（容器没起 / backend 启动失败，看 docker logs industrial-ai）"
    fi
}

summary() {
    local rf_port app_port
    rf_port=$(_rf_env SVR_HTTP_PORT 9380)
    app_port=$(_main_env APP_PORT); app_port="${app_port:-9300}"
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "  主系统:      http://${IP}:${app_port}"
    echo -e "  RAGFlow UI:  http://${IP}   （默认端口 80）"
    echo -e "  RAGFlow API: http://${IP}:${rf_port}"
    if [ "$FAILS" -gt 0 ]; then
        echo -e "  ${RED}失败 ${FAILS} 项（上面 [x]），修完后 ./deploy_all.sh check 复查${NC}"
    elif [ "$WARNS" -gt 0 ]; then
        echo -e "  ${YELLOW}无失败，但有 ${WARNS} 项提醒（上面 [!]，多为首次部署待回填项）${NC}"
    else
        echo -e "  ${GREEN}全部检查通过${NC}"
    fi
    echo -e "${GREEN}========================================${NC}"
}

# ---------- 动作 ----------

case "$ACTION" in
    install|up)
        say "—— [1/6] 环境检查 ——"
        preflight strict
        ensure_main_env
        _detect_ip

        say "—— [2/6] RAGFlow：源码/端口消歧/启动 ——"
        if [ ! -d "$RAGFLOW_DIR/ragflow-src" ]; then
            bash "$RAGFLOW_DIR/setup.sh" fetch
        fi
        patch_rf_ports
        bash "$RAGFLOW_DIR/setup.sh" up

        say "—— [3/6] 校正主项目 .env 的 RAGFLOW_BASE_URL ——"
        reconcile_base_url fix

        say "—— [4/6] 启动主系统 ——"
        BUILD_ARGS=()
        [ "${DEPLOY_BUILD:-0}" = "1" ] && BUILD_ARGS+=(--build)
        compose_main up -d "${BUILD_ARGS[@]}"

        say "—— [5/6] 等待就绪 ——"
        wait_http "http://127.0.0.1:$(_rf_env SVR_HTTP_PORT 9380)/" 300 any "RAGFlow API"
        APP_PORT_VAL=$(_main_env APP_PORT); APP_PORT_VAL="${APP_PORT_VAL:-9300}"
        wait_http "http://127.0.0.1:${APP_PORT_VAL}/api/health" 180 200 "主系统"

        say "—— [6/6] 链路自检 ——"
        link_checks
        summary
        [ "$FAILS" -eq 0 ] || exit 1
        ;;

    check)
        preflight warn
        ensure_main_env
        _detect_ip
        say "—— 容器状态 ——"
        for c in industrial-ai ragflow-server; do
            if _container_running "$c"; then ok "$c 运行中"; else bad "$c 未运行"; fi
        done
        say "—— 配置指向 ——"
        reconcile_base_url checkonly
        say "—— 服务健康 ——"
        check_main_health
        say "—— 链路自检 ——"
        link_checks
        summary
        [ "$FAILS" -eq 0 ] || exit 1
        ;;

    status)
        _detect_ip
        say "—— 主系统 ——"
        compose_main ps || true
        say "—— RAGFlow ——"
        if [ -d "$RAGFLOW_DIR/ragflow-src" ]; then
            bash "$RAGFLOW_DIR/setup.sh" status || true
        else
            note "RAGFlow 未安装（ragflow-src 不存在）"
        fi
        summary
        ;;

    down)
        say "停止主系统..."
        compose_main down
        if [ -d "$RAGFLOW_DIR/ragflow-src" ]; then
            say "停止 RAGFlow..."
            bash "$RAGFLOW_DIR/setup.sh" down
        fi
        echo -e "${GREEN}两套栈已停止（数据卷都保留）${NC}"
        ;;

    *)
        echo -e "${RED}用法：./deploy_all.sh [install|up|check|status|down]${NC}"
        exit 1
        ;;
esac
