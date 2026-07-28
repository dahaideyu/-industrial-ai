# cython: annotation_typing=False, infer_types=False, language_level=3
"""LibreOffice 文件转 PDF 客户端"""
import logging
import os
import shutil
import subprocess
from pathlib import Path

from backend.core.knowledge_management.exceptions import TaskError

logger = logging.getLogger(__name__)

# Docker 容器名（用于 fallback 模式）
_DOCKER_CONTAINER = "knb-libreoffice"


class LibreOfficeClient:
    """LibreOffice 客户端，用于将文档转换为 PDF 格式。

    优先使用本地 libreoffice，不可用时自动回退到 Docker 容器。
    """

    def convert_to_pdf(self, input_path: str, output_dir: str) -> str:
        """调用 LibreOffice 将文件转换为 PDF。"""
        # 先试本地
        try:
            return self._convert_local(input_path, output_dir)
        except (FileNotFoundError, TaskError):
            logger.info("本地 LibreOffice 不可用，回退到 Docker 容器")
            return self._convert_docker(input_path, output_dir)

    def _convert_local(self, input_path: str, output_dir: str) -> str:
        """本地 libreoffice 命令转换。"""
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

    def _convert_docker(self, input_path: str, output_dir: str) -> str:
        """通过 Docker 容器执行转换。

        docker cp 文件进容器 → 执行 libreoffice → docker cp 文件出来。
        """
        input_file = Path(input_path)
        output_directory = Path(output_dir)
        output_directory.mkdir(parents=True, exist_ok=True)

        # 容器内临时路径
        container_input = f"/tmp/{input_file.name}"
        pdf_name = input_file.stem + ".pdf"
        container_output = f"/tmp/{pdf_name}"

        try:
            # 1. 复制文件进容器
            subprocess.run(
                ["docker", "cp", str(input_file), f"{_DOCKER_CONTAINER}:{container_input}"],
                check=True, capture_output=True, text=True, timeout=30,
            )

            # 2. 在容器内转换
            result = subprocess.run(
                [
                    "docker", "exec", _DOCKER_CONTAINER,
                    "libreoffice", "--headless",
                    "--convert-to", "pdf",
                    "--outdir", "/tmp",
                    container_input,
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                raise TaskError(
                    f"Docker LibreOffice 转换失败 (exit={result.returncode}): {result.stderr.strip()}"
                )

            # 3. 复制结果出来
            local_output = str(output_directory / pdf_name)
            subprocess.run(
                ["docker", "cp", f"{_DOCKER_CONTAINER}:{container_output}", local_output],
                check=True, capture_output=True, text=True, timeout=30,
            )

            # 4. 清理容器内临时文件
            subprocess.run(
                ["docker", "exec", _DOCKER_CONTAINER, "rm", "-f", container_input, container_output],
                capture_output=True, text=True, timeout=15,
            )

        except subprocess.CalledProcessError as e:
            raise TaskError(f"Docker LibreOffice 转换失败: {e.stderr.strip() if e.stderr else str(e)}")

        if not Path(local_output).exists():
            raise TaskError(f"转换完成但未找到输出文件: {local_output}")

        return local_output


# 模块级单例
libreoffice_client = LibreOfficeClient()
