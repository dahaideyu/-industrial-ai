# cython: annotation_typing=False, infer_types=False, language_level=3
"""MinIO 文件存储客户端"""
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from backend.core.knowledge_management.config import settings


class MinIOClient:
    """MinIO 对象存储客户端，用于知识库文档的上传、下载和管理。"""

    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
        self.bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        """确保 bucket 存在，不存在则创建。"""
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def upload_file(self, object_name: str, file_path: str, content_type: str = "application/octet-stream") -> str:
        """上传文件到 MinIO。

        Args:
            object_name: 存储对象名称（路径）。
            file_path: 本地文件路径。
            content_type: 文件 MIME 类型。

        Returns:
            对象名称。
        """
        self.client.fput_object(self.bucket, object_name, file_path, content_type=content_type)
        return object_name

    def upload_fileobj(self, object_name: str, file_obj, length: int, content_type: str = "application/octet-stream") -> str:
        """上传文件对象到 MinIO。

        Args:
            object_name: 存储对象名称（路径）。
            file_obj: 文件对象（支持 read() 方法）。
            length: 文件大小（字节）。
            content_type: 文件 MIME 类型。

        Returns:
            对象名称。
        """
        self.client.put_object(self.bucket, object_name, file_obj, length, content_type=content_type)
        return object_name

    def download_file(self, object_name: str, file_path: str) -> str:
        """从 MinIO 下载文件到本地。

        Args:
            object_name: 存储对象名称（路径）。
            file_path: 本地目标文件路径。

        Returns:
            本地文件路径。
        """
        self.client.fget_object(self.bucket, object_name, file_path)
        return file_path

    def delete_file(self, object_name: str):
        """删除 MinIO 中的文件，文件不存在时静默处理。

        Args:
            object_name: 存储对象名称（路径）。
        """
        try:
            self.client.remove_object(self.bucket, object_name)
        except S3Error:
            pass

    def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        """获取文件的预签名 URL。

        Args:
            object_name: 存储对象名称（路径）。
            expires: 过期时间（秒），默认 3600。

        Returns:
            预签名 URL 字符串。
        """
        return self.client.presigned_get_object(
            self.bucket, object_name, expires=timedelta(seconds=expires)
        )


# 模块级单例
minio_client = MinIOClient()
