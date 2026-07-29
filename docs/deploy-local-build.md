# 本地打包部署指南（已废弃，内容已迁移）

> ⚠️ 本文档已过时（仍使用改名前的 `chaowei-agent` 镜像名、旧的 `docker/` 路径，且未反映
> 2026-07 Dockerfile 拆分为 `final-app`/`final-worker`/`final-base` 三个 target 后的镜像/打包变化），
> 不再维护。

请改看当前维护的部署说明：

- **[deploy/docker/部署说明.md](../deploy/docker/部署说明.md)** — 完整的离线打包 + 服务器部署流程（build.bat/build.sh 打包三个镜像、docker load、各基地 compose 覆盖文件、常见问题排查）
- **[docs/源码保护改造方案.md](./源码保护改造方案.md)** — Cython 源码编译保护 + 提示词加密的原理和验证方法
