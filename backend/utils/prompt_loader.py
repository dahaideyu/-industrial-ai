# cython: annotation_typing=False, infer_types=False, language_level=3
"""
提示词加载器 - 支持加密和明文两种模式

通过环境变量 PROMPT_SOURCE 控制读取来源：
  - "file"      : 仅从磁盘 .txt 明文读取（开发环境）
  - "encrypted" : 仅从 prompts_encrypted.json 解密读取（生产环境）
  - "auto"      : 自动检测，优先文件，兜底加密（默认值）
"""

import json
import os
from pathlib import Path
from typing import Optional, Literal

PromptSource = Literal["auto", "file", "encrypted"]


def _get_prompt_source() -> PromptSource:
    """读取 PROMPT_SOURCE 配置，默认 auto"""
    value = os.environ.get("PROMPT_SOURCE", "auto").strip().lower()
    if value in ("file", "encrypted", "auto"):
        return value  # type: ignore
    return "auto"


class PromptLoader:
    """提示词加载器"""

    def __init__(self):
        self._cipher = None
        self._encrypted_data: Optional[dict] = None
        self._initialized = False

    def _init_cipher(self):
        """初始化解密器"""
        if self._initialized:
            return

        self._initialized = True
        key = os.environ.get("PROMPT_ENCRYPT_KEY")
        if key:
            try:
                from cryptography.fernet import Fernet
                self._cipher = Fernet(key.encode())
            except ImportError:
                print("[警告] cryptography 未安装，无法解密提示词")
            except Exception as e:
                print(f"[警告] 初始化解密器失败: {e}")

    def _load_encrypted_data(self) -> dict:
        """加载加密数据"""
        if self._encrypted_data is None:
            data_file = Path(__file__).parent.parent / "prompts_encrypted.json"
            if data_file.exists():
                try:
                    self._encrypted_data = json.loads(
                        data_file.read_text(encoding="utf-8")
                    )
                except Exception as e:
                    print(f"[警告] 加载加密数据失败: {e}")
                    self._encrypted_data = {}
            else:
                self._encrypted_data = {}
        return self._encrypted_data

    def _try_read_file(self, file_path: str) -> Optional[str]:
        """尝试从磁盘读取明文文件，失败返回 None"""
        plain_path = Path(file_path)
        if plain_path.exists():
            return plain_path.read_text(encoding="utf-8")

        try:
            relative_path = str(plain_path.relative_to(Path.cwd()))
        except ValueError:
            relative_path = file_path

        if Path(relative_path).exists():
            return Path(relative_path).read_text(encoding="utf-8")

        return None

    def _try_decrypt(self, file_path: str) -> Optional[str]:
        """尝试从加密数据中解密，失败返回 None"""
        if not self._cipher:
            return None

        data = self._load_encrypted_data()
        if not data:
            return None

        # 精确匹配
        for path_key in [file_path, str(Path(file_path))]:
            if path_key in data:
                try:
                    return self._cipher.decrypt(data[path_key].encode()).decode("utf-8")
                except Exception as e:
                    print(f"[警告] 解密失败 {path_key}: {e}")

        # 文件名模糊匹配（纯文件名也能匹配，不要求 file_path 包含目录）
        filename = Path(file_path).name
        if filename:
            for path_key, encrypted_value in data.items():
                # 统一用 / 做路径分隔符，兼容 Windows 构建 → Linux 运行的跨平台场景
                normalized_key = path_key.replace('\\', '/')
                if Path(normalized_key).name == filename:
                    try:
                        return self._cipher.decrypt(encrypted_value.encode()).decode("utf-8")
                    except Exception as e:
                        print(f"[警告] 解密失败 {path_key}: {e}")

        return None

    def get_prompt(self, file_path: str) -> str:
        """
        获取提示词内容

        Args:
            file_path: 提示词文件路径（可以是绝对路径、相对路径或纯文件名）

        Returns:
            提示词内容（明文）

        Raises:
            FileNotFoundError: 文件不存在时抛出
        """
        self._init_cipher()
        source = _get_prompt_source()

        # ---- 生产模式：仅从加密读取 ----
        if source == "encrypted":
            result = self._try_decrypt(file_path)
            if result is not None:
                return result
            raise FileNotFoundError(f"提示词不存在于加密数据中: {file_path}")

        # ---- 开发模式：仅从文件读取 ----
        if source == "file":
            result = self._try_read_file(file_path)
            if result is not None:
                return result
            raise FileNotFoundError(f"提示词文件不存在: {file_path}")

        # ---- 自动模式（默认）：先文件，后加密 ----
        result = self._try_read_file(file_path)
        if result is not None:
            return result

        result = self._try_decrypt(file_path)
        if result is not None:
            return result

        raise FileNotFoundError(f"提示词不存在: {file_path}")

    def has_prompt(self, file_path: str) -> bool:
        """检查提示词是否存在"""
        self._init_cipher()
        source = _get_prompt_source()

        if source == "encrypted":
            return self._try_decrypt(file_path) is not None

        if source == "file":
            return self._try_read_file(file_path) is not None

        # auto: 先文件后加密
        if self._try_read_file(file_path) is not None:
            return True
        return self._try_decrypt(file_path) is not None


# 全局实例
prompt_loader = PromptLoader()
