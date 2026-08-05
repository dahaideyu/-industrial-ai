#!/usr/bin/env python3
"""
提示词加密脚本。

用法：设置 PROMPT_ENCRYPT_KEY，或在 deploy/docker/.env 中配置后执行
python scripts/encrypt_prompts.py。

功能:
1. 扫描所有 backend/modules/*/prompts/*.txt 文件
2. 使用 AES 加密
3. 生成 backend/prompts_encrypted.json
4. 使用构建环境提供的固定密钥，不生成、不输出、不落盘密钥
"""

import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from cryptography.fernet import Fernet
except ImportError:
    print("请先安装 cryptography: pip install cryptography")
    sys.exit(1)


def get_env_file_path() -> Path:
    """获取提示词加密使用的部署环境文件路径。

    Returns:
        环境变量指定的路径；未指定时回退到默认 `.env`。
    """
    configured_path = os.environ.get("PROMPT_ENV_FILE", "").strip()
    if not configured_path:
        return PROJECT_ROOT / "deploy" / "docker" / ".env"

    env_file = Path(configured_path)
    if env_file.is_absolute():
        return env_file

    return PROJECT_ROOT / env_file


def get_env_file_key() -> str:
    """从部署环境文件中读取提示词加密密钥。

    Returns:
        `.env` 中的密钥；文件或配置项不存在时返回空字符串。
    """
    env_file = get_env_file_path()
    if not env_file.is_file():
        return ""

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", maxsplit=1)
        if name.strip() != "PROMPT_ENCRYPT_KEY":
            continue

        return value.strip().strip('"').strip("'")

    return ""


def get_encryption_key() -> bytes:
    """读取并校验提示词加密密钥。

    Returns:
        可直接传给 Fernet 的 UTF-8 编码密钥。

    Raises:
        RuntimeError: 未配置或密钥格式无效时抛出，避免生成无法部署的镜像。
    """
    # Jenkins Credentials 注入的环境变量优先，服务器本地构建则回退到 .env。
    key = os.environ.get("PROMPT_ENCRYPT_KEY", "").strip() or get_env_file_key()
    if not key:
        raise RuntimeError(
            f"缺少 PROMPT_ENCRYPT_KEY，请设置环境变量或在 {get_env_file_path()} 中配置"
        )

    try:
        Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("PROMPT_ENCRYPT_KEY 不是有效的 Fernet 密钥") from exc

    return key.encode("utf-8")


def encrypt_prompts() -> int:
    """使用固定密钥加密所有提示词，并原子写入构建产物。

    Returns:
        成功加密的提示词文件数量。

    Raises:
        RuntimeError: 未找到可加密的提示词文件时抛出。
    """
    cipher = Fernet(get_encryption_key())

    # 扫描所有提示词文件
    prompts_dir = PROJECT_ROOT / "backend" / "modules"
    encrypted: dict[str, str] = {}

    for txt_file in sorted(prompts_dir.rglob("prompts/*.txt")):
        # 使用相对路径作为 key
        # 统一使用 / 分隔符，确保 Linux 服务器上 pathlib 能正确解析文件名
        relative_path = str(txt_file.relative_to(PROJECT_ROOT)).replace('\\', '/')
        content = txt_file.read_text(encoding="utf-8")
        encrypted[relative_path] = cipher.encrypt(content.encode()).decode()
        print(f"  加密: {relative_path}")

    if not encrypted:
        raise RuntimeError(f"未在 {prompts_dir} 下找到 prompts/*.txt 文件")

    # 使用临时文件替换，避免构建中断时留下半写入的加密产物。
    output_file = PROJECT_ROOT / "backend" / "prompts_encrypted.json"
    temp_output_file = output_file.with_suffix(".json.tmp")
    temp_output_file.write_text(
        json.dumps(encrypted, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_output_file.replace(output_file)

    print(f"\n完成! 共加密 {len(encrypted)} 个文件")
    print(f"加密文件: {output_file}")

    return len(encrypted)


def main() -> int:
    """执行提示词加密并将错误转换为非零退出码。

    Returns:
        成功时返回 0，失败时返回 1。
    """
    try:
        encrypt_prompts()
    except Exception as exc:
        print(f"提示词加密失败: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
