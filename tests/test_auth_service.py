"""Unit tests for backend/modules/auth/service.py

认证服务的纯逻辑部分（密码哈希 + 令牌签发/校验）不需要数据库连接，
但这些函数是系统安全的基石——密码校验一旦出错，要么合法用户登不进去，
要么攻击者可以伪造令牌。

测试覆盖：
- hash_password / verify_password: 正确/错误密码、格式校验、哈希一致性
- create_token / verify_token: 正常签发校验、过期判定、篡改检测、无效格式
"""
import pytest
import time
import json
import base64
import hmac
import hashlib

from backend.modules.auth import service as auth


class TestHashPassword:
    def test_hash_format(self):
        """哈希格式：pbkdf2_sha256$iterations$salt_hex$hash_hex"""
        h = auth.hash_password("test123")
        parts = h.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) == auth.PBKDF2_ITERATIONS
        # salt 和 hash 都是合法的 hex 字符串
        bytes.fromhex(parts[2])
        bytes.fromhex(parts[3])

    def test_different_salts(self):
        """同一密码两次哈希应产生不同结果（随机 salt）"""
        h1 = auth.hash_password("test123")
        h2 = auth.hash_password("test123")
        assert h1 != h2

    def test_hash_contains_no_plaintext(self):
        """哈希中不能包含明文密码"""
        password = "mySecretPassword123!"
        h = auth.hash_password(password)
        assert password not in h


class TestVerifyPassword:
    def test_correct_password(self):
        password = "test123"
        stored = auth.hash_password(password)
        assert auth.verify_password(password, stored) is True

    def test_wrong_password(self):
        stored = auth.hash_password("correct")
        assert auth.verify_password("wrong", stored) is False

    def test_empty_password(self):
        stored = auth.hash_password("real")
        assert auth.verify_password("", stored) is False

    def test_empty_stored(self):
        assert auth.verify_password("test", "") is False

    def test_malformed_stored(self):
        """格式错误的哈希返回 False 而非抛异常"""
        assert auth.verify_password("test", "not$a$valid$hash") is False

    def test_wrong_algo(self):
        """非 pbkdf2_sha256 算法的哈希返回 False"""
        fake = f"bcrypt$10000$abcd$efgh"
        assert auth.verify_password("test", fake) is False


class TestCreateToken:
    def test_token_format(self):
        """令牌格式：base64(payload).base64(sig)"""
        token = auth.create_token("admin")
        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2

    def test_token_contains_username(self):
        """令牌 payload 中包含用户名"""
        token = auth.create_token("operator1")
        body = token.split(".")[0]
        # 补齐 base64 padding
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        assert payload["sub"] == "operator1"

    def test_token_has_expiry(self):
        """令牌包含过期时间"""
        token = auth.create_token("admin")
        body = token.split(".")[0]
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        assert "exp" in payload
        assert payload["exp"] > int(time.time())


class TestVerifyToken:
    def test_valid_token(self):
        token = auth.create_token("admin")
        assert auth.verify_token(token) == "admin"

    def test_expired_token(self):
        """过期令牌返回 None"""
        # 构造一个已过期的令牌
        old_payload = {"sub": "admin", "exp": int(time.time()) - 3600}
        body = auth._b64e(json.dumps(old_payload, separators=(",", ":")).encode("utf-8"))
        token = f"{body}.{auth._sign(body)}"
        assert auth.verify_token(token) is None

    def test_tampered_payload(self):
        """篡改 payload 后签名校验失败"""
        token = auth.create_token("admin")
        body, sig = token.split(".")
        # 篡改 payload（替换为另一个用户）
        tampered_body = auth._b64e(json.dumps({"sub": "root", "exp": int(time.time()) + 3600}).encode("utf-8"))
        tampered_token = f"{tampered_body}.{sig}"
        assert auth.verify_token(tampered_token) is None

    def test_tampered_signature(self):
        """篡改签名后校验失败"""
        token = auth.create_token("admin")
        body, _ = token.split(".")
        fake_sig = auth._b64e(b"invalidsignature")
        assert auth.verify_token(f"{body}.{fake_sig}") is None

    def test_empty_token(self):
        assert auth.verify_token("") is None
        assert auth.verify_token(None) is None

    def test_malformed_token(self):
        """格式错误的令牌返回 None"""
        assert auth.verify_token("not.a.valid.token.at.all") is None

    def test_no_dot(self):
        """没有分隔符的令牌返回 None"""
        assert auth.verify_token("nodots") is None
