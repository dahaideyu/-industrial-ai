#!/usr/bin/env python3
"""
提示词加密脚本
用法: python scripts/encrypt_prompts.py

功能:
1. 扫描所有 backend/modules/*/prompts/*.txt 文件
2. 使用 AES 加密
3. 生成 backend/prompts_encrypted.json
4. 输出密钥（配置到服务器环境变量 PROMPT_ENCRYPT_KEY）
"""

import json
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


def encrypt_prompts():
    """加密所有提示词文件"""
    # 生成密钥
    key = Fernet.generate_key()
    cipher = Fernet(key)

    # 扫描所有提示词文件
    prompts_dir = PROJECT_ROOT / "backend" / "modules"
    encrypted = {}
    count = 0

    for txt_file in prompts_dir.rglob("prompts/*.txt"):
        # 使用相对路径作为 key
        # 统一使用 / 分隔符，确保 Linux 服务器上 pathlib 能正确解析文件名
        relative_path = str(txt_file.relative_to(PROJECT_ROOT)).replace('\\', '/')
        content = txt_file.read_text(encoding="utf-8")
        encrypted[relative_path] = cipher.encrypt(content.encode()).decode()
        count += 1
        print(f"  加密: {relative_path}")

    # 保存到 JSON 文件
    output_file = PROJECT_ROOT / "backend" / "prompts_encrypted.json"
    output_file.write_text(
        json.dumps(encrypted, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n完成! 共加密 {count} 个文件")
    print(f"加密文件: {output_file}")

    key_str = key.decode()
    print(f"\n请将以下密钥配置到服务器环境变量:")
    print(f"PROMPT_ENCRYPT_KEY={key_str}")

    # 同时写入 build_key.txt，方便 build.bat 读取
    key_file = PROJECT_ROOT / "build_key.txt"
    key_file.write_text(key_str, encoding="utf-8")


if __name__ == "__main__":
    encrypt_prompts()
