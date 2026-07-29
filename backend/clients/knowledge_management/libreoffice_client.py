# cython: annotation_typing=False, infer_types=False, language_level=3
"""LibreOffice 文件转 PDF 客户端"""
import logging
import subprocess
from pathlib import Path

from backend.core.knowledge_management.exceptions import TaskError

logger = logging.getLogger(__name__)


class LibreOfficeClient:
    """LibreOffice 客户端，用于将文档转换为 PDF 格式（调用镜像内置的 libreoffice 命令）。"""

    def convert_to_pdf(self, input_path: str, output_dir: str) -> str:
        """调用 LibreOffice 将文件转换为 PDF。"""
        input_file = Path(input_path)
        output_directory = Path(output_dir)
        output_directory.mkdir(parents=True, exist_ok=True)

        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(output_directory),
            str(input_file),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            raise TaskError("未找到 libreoffice 命令，请确认已安装 LibreOffice")
        except subprocess.TimeoutExpired:
            raise TaskError(f"LibreOffice 转换超时: {input_path}")

        if result.returncode != 0:
            raise TaskError(
                f"LibreOffice 转换失败 (exit={result.returncode}): {result.stderr.strip()}"
            )

        pdf_name = input_file.stem + ".pdf"
        pdf_path = output_directory / pdf_name
        if not pdf_path.exists():
            raise TaskError(f"转换完成但未找到输出文件: {pdf_path}")

        return str(pdf_path)


# 模块级单例
libreoffice_client = LibreOfficeClient()
