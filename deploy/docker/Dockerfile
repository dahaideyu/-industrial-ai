# syntax=docker/dockerfile:1
# Industrial AI — 三个 target 共用同一套构建阶段，按服务实际需要的依赖分层，避免
# repair-suggestion/mqtt-etl 这类轻量服务也背上 nginx+LibreOffice+OCR 的体积：
#   final-base  （默认不用，供下面继承）— 纯后端运行时，repair-suggestion/mqtt-etl 用
#   final-office（默认不用，供下面两个 target 继承）— final-base + LibreOffice + 中文字体
#   final-worker（--target final-worker）— final-office + OCR，knb-celery-worker 用
#   final-app   （默认 target，不加 --target 时构建这个）— final-office + nginx + 前端，industrial-ai 用
# 构建: docker build -f deploy/docker/Dockerfile -t industrial-ai .（从仓库根目录执行，构建 final-app）
# 启动: docker compose -f deploy/docker/docker-compose.yml up

# ---- Stage 1: 前端构建 ----
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
RUN npm config set registry https://registry.npmmirror.com && \
    yarn config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/yarn.lock ./
RUN yarn install --frozen-lockfile
COPY frontend/ ./
ARG VITE_ENABLE_SQL_QA=true
RUN echo "VITE_ENABLE_SQL_QA=$VITE_ENABLE_SQL_QA" > .env.production && yarn build

# ---- Stage 2: 后端依赖（uv） ----
FROM python:3.12-slim AS backend-deps
# 使用 pip 安装 uv（避免从 ghcr.io 拉取，国内访问不稳定）
RUN pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple
WORKDIR /app
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_TRUSTED_HOST=mirrors.aliyun.com
ENV UV_LINK_MODE=copy
# 设置 uv 缓存和临时目录到 /opt 下，避免根分区空间不足
ENV UV_CACHE_DIR=/opt/.uv-cache
ENV TMPDIR=/opt/.tmp
# 不依赖提交的 uv.lock：按 pyproject 解析并仅安装”依赖”，构建期临时生成 lock。
# --no-install-project：此阶段没有 backend/ 源码，只装依赖；最终镜像 COPY backend/
# 后用 uvicorn backend.app:app 运行，无需把本项目 pip 安装成包。
COPY pyproject.toml README.md ./
RUN mkdir -p /opt/.tmp && \
    uv sync --no-install-project --no-dev && \
    # 清理缓存，减少镜像大小
    rm -rf /opt/.uv-cache /opt/.tmp /tmp/*

# ---- Stage 2.5: Cython 编译源码保护（可通过 COMPILE_SOURCE=false 跳过） ----
# 测试环境不编译（构建快、方便调试），生产环境编译（保护源码）
FROM python:3.12-slim AS code-protect
ARG COMPILE_SOURCE=true
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
# 只有生产源码保护构建才需要编译工具链。测试/CI 用 COMPILE_SOURCE=false 时
# 不再白白下载 gcc、Python headers 和 Cython（这几个包不小，且每次都要装）。
RUN if [ "$COMPILE_SOURCE" = "true" ]; then \
        if [ -n "$APT_MIRROR" ]; then \
            sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
        fi && \
        apt-get update && apt-get install -y --no-install-recommends gcc python3-dev build-essential && \
        pip install cython -i https://pypi.tuna.tsinghua.edu.cn/simple && \
        rm -rf /var/lib/apt/lists/*; \
    else \
        echo "=== COMPILE_SOURCE=false，跳过 Cython 编译工具链安装 ==="; \
    fi
WORKDIR /build
COPY --from=backend-deps /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY backend/ ./backend/

# 修复 Cython 兼容性问题：
# 1. 移除 from __future__ import annotations（Cython 不支持）
# 2. 修复 str | None 等类型注解为 Optional[str]
# 3. 转换复杂 f-string 为 .format()
COPY deploy/docker/scripts/fix_cython_compat.py /tmp/fix_cython_compat.py
RUN if [ "$COMPILE_SOURCE" = "true" ]; then \
        python /tmp/fix_cython_compat.py backend; \
    else \
        echo "=== COMPILE_SOURCE=false，跳过 Cython 源码兼容性改写 ==="; \
    fi

# 条件编译：COMPILE_SOURCE=true 时执行 Cython 编译，否则直接跳过
# 并行编译：各文件互不依赖，xargs -P 吃满核数（串行 ~10 分钟 → 并行 1-2 分钟）；
# sysconfig 三个路径在循环外算一次，避免每个文件反复启动 python 进程；
# 并行下子 shell 改不了父进程变量，失败文件改为记入 /tmp/cython_failed.txt（O_APPEND 原子），最后统一判定
RUN if [ "$COMPILE_SOURCE" = "true" ]; then \
        echo "=== 开始 Cython 编译（并行 $(nproc) 线程）===" && \
        PY_INC=$(python -c "import sysconfig; print(sysconfig.get_path('include'))") && \
        PY_LIBDIR=$(python -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))") && \
        EXT_SUFFIX=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))") && \
        export PY_INC PY_LIBDIR EXT_SUFFIX && \
        rm -f /tmp/cython_failed.txt && \
        find backend -name "*.py" -not -name "__init__.py" -print0 | \
        xargs -0 -n1 -P4 sh -c ' \
            f="$1"; \
            echo "Compiling: $f"; \
            cython -3 "$f" -o "${f%.py}.c" && \
            gcc -shared -O2 -fPIC -I"$PY_INC" \
                -o "${f%.py}$EXT_SUFFIX" "${f%.py}.c" \
                -L"$PY_LIBDIR" -lpython3.12 \
            || echo "$f" >> /tmp/cython_failed.txt' _ && \
        if [ -s /tmp/cython_failed.txt ]; then \
            echo "ERROR: 以下文件编译失败，构建中止:" && cat /tmp/cython_failed.txt && exit 1; \
        fi && \
        echo "=== Cython 编译完成 ===" && \
        # 只删除已成功编译（有对应 .so）的 .py 源文件
        for f in $(find backend -name "*.py" -not -name "__init__.py"); do \
            SO_FILE="${f%.py}$EXT_SUFFIX"; \
            if [ -f "$SO_FILE" ]; then rm "$f"; echo "已删除源码: $f"; fi; \
        done && \
        find backend -name "*.c" -delete && \
        find backend -name "__pycache__" -exec rm -rf {} + ; \
    else \
        echo "=== 跳过 Cython 编译（COMPILE_SOURCE=false）===" ; \
    fi

# ---- Stage 3: 精简运行时基座 ----
# 供 repair-suggestion / mqtt-etl 使用：不需要 nginx / LibreOffice / OCR，
# 构建这两个 target 时 frontend-build 阶段不会被引用，直接跳过（省构建时间+体积）。
FROM python:3.12-slim AS final-base
WORKDIR /app

# 设置时区为北京时间
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# apt 换源开关。默认清华源（国内下载 deb 包快 10 倍+），适用于在腾讯云服务器上本地
# 构建的场景；下游 final-office/final-worker/final-app 都 FROM 过来，继承这一层，
# 不必各自重复。
# GitHub Actions 的构建跑在境外 runner 上，走国内源反而更慢，workflow 里传
# APT_MIRROR= （空值）关掉即可，此时用官方 deb.debian.org。
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
ARG KEEP_PLAINTEXT_PROMPTS=false
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources && \
        echo "=== apt 源已切换到 $APT_MIRROR ==="; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 复制 uv 安装的虚拟环境
COPY --from=backend-deps /app/.venv /app/.venv

# 复制后端代码（生产环境为编译后的 .so，测试环境为原始 .py）
COPY --from=code-protect /build/backend/ ./backend/

# 复制 MQTT ETL 服务代码
COPY mqtt_etl/ ./mqtt_etl/

# 生产包默认优先使用加密提示词；测试日报时可传 KEEP_PLAINTEXT_PROMPTS=true，
# 即使工作区残留 prompts_encrypted.json 也保留明文，配合 PROMPT_SOURCE=file 使用。
RUN if [ "$KEEP_PLAINTEXT_PROMPTS" != "true" ] && [ -f backend/prompts_encrypted.json ]; then \
        find backend -name "*.txt" -path "*/prompts/*" -delete && \
        echo "已删除明文提示词文件（使用加密版本）"; \
    else \
        echo "保留明文提示词（测试模式或加密文件不存在）"; \
    fi && \
    # 打印后端文件信息，方便确认是编译版本还是源码版本
    echo "=== 后端文件检查 ===" && \
    find backend -name "*.so" | head -5 && \
    find backend -name "*.py" | head -5

# 创建运行时目录
RUN mkdir -p /app/logs /app/data /app/backend/data

ENV PATH="/app/.venv/bin:$PATH"
# repair-suggestion / mqtt-etl / knb-celery-worker 的启动命令由 compose 的 command: 指定，
# 此 target 不设默认 CMD

# ---- Stage 3.5: LibreOffice + 中文字体公共层 ----
# final-worker 和 final-app 都需要 LibreOffice + fonts-noto-cjk（几百 MB）。原先两个
# 阶段各装一遍，等于同一批包下载安装两次；抽成公共层后只下一次，两个 target 共享同一
# 层缓存。镜像分发时（docker pull）也只需传输一次，跨境拉取尤其明显。
# 不并入 final-base，是为了保持 repair-suggestion/mqtt-etl 的轻量（见文件头注释）。
FROM final-base AS final-office
ARG INSTALL_LIBREOFFICE=true
RUN if [ "${INSTALL_LIBREOFFICE}" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-common libreoffice-writer libreoffice-calc libreoffice-impress \
        fontconfig fonts-noto-cjk fonts-liberation \
        && fc-cache -f \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping LibreOffice for report-only test image"; \
    fi

# ---- Stage 4: 文档处理 worker ----
# 供 knb-celery-worker 使用：final-office（LibreOffice，Office→PDF，见 convert_tasks.py）
# + Tesseract OCR/poppler（扫描件文本提取，见 markitdown_client.py / extract_tasks.py）。
# 不需要 nginx，也不需要前端构建产物。
FROM final-office AS final-worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-chi-sim poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ---- Stage 5: 完整应用（默认 target）----
# 供 industrial-ai 使用：final-office + nginx + 前端静态资源。LibreOffice 供文档预览
# 接口用（见 backend/routes/knowledge_qa/routes.py）。不需要 OCR/poppler——那是
# celery worker 异步抽取任务专用（final-worker），预览接口不做 OCR。
FROM final-office AS final-app
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# 复制 nginx 配置
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

# 复制启动脚本和诊断工具
COPY deploy/docker/scripts/entrypoint.sh /app/entrypoint.sh
COPY deploy/docker/scripts/diagnose_knb.py /app/diagnose_knb.py
# 修复 Windows 换行符（CRLF → LF），避免 Linux 执行报错
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 80

CMD ["/app/entrypoint.sh"]
