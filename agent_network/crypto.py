"""
密码学工具：Ed25519 密钥生成、消息签名、签名验证
"""
from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import Base64Encoder
import json
from typing import Tuple


def generate_keypair() -> Tuple[str, str]:
    """
    生成 Ed25519 密钥对
    返回 (private_key_base64, public_key_base64)
    """
    sk = SigningKey.generate()
    private_key = sk.encode(encoder=Base64Encoder).decode()
    public_key = sk.verify_key.encode(encoder=Base64Encoder).decode()
    return private_key, public_key


def sign_message(private_key_b64: str, message_bytes: bytes) -> str:
    """
    用私钥签名消息
    参数：
        private_key_b64: Base64 编码的私钥
        message_bytes: 待签名的原始字节
    返回：Base64 编码的签名
    """
    sk = SigningKey(private_key_b64, encoder=Base64Encoder)
    signed = sk.sign(message_bytes)
    # 提取签名部分（去掉原始消息前缀）
    signature = signed.signature
    return Base64Encoder.encode(signature).decode()


def verify_signature(
    public_key_b64: str, message_bytes: bytes, signature_b64: str
) -> bool:
    """
    用公钥验证签名
    参数：
        public_key_b64: Base64 编码的公钥
        message_bytes: 原始消息字节
        signature_b64: Base64 编码的签名
    返回：验证是否通过
    """
    try:
        vk = VerifyKey(public_key_b64, encoder=Base64Encoder)
        signature = Base64Encoder.decode(signature_b64.encode())
        vk.verify(message_bytes, signature)
        return True
    except Exception:
        return False


def build_message_bytes(msg: dict) -> bytes:
    """
    将消息序列化为规范化的签名字节
    签名时排除 signature 字段本身，按字段名排序确保一致性
    """
    data = {k: v for k, v in msg.items() if k != "signature"}
    return json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
