"""通过 WebSocket 连接 OpenClaw Gateway 配对协议，批准 CLI 设备。

认证流程：
1. 连接 WebSocket → 收到 connect.challenge（含 nonce）
2. 用 Ed25519 私钥签名 nonce → 发回 connect.response  
3. 发送 connect 消息（含 token + device identity）→ 收到 connect.hello
4. 发送 device.pair.approve → 批准完成
"""
import asyncio
import json
import hashlib
import os
import sys
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import websockets

# 从环境变量读取 token，避免明文写在源码里被泄露到公开仓库
TOKEN = os.getenv("AGENT_NETWORK_TOKEN", "")
if not TOKEN:
    sys.exit("请先设置环境变量 AGENT_NETWORK_TOKEN")


def generate_device_identity():
    """生成临时的 Ed25519 设备密钥对"""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    
    # 用公钥的 hex 作为 deviceId
    device_id = public_bytes.hex()
    
    return {
        "deviceId": device_id,
        "publicKey": public_bytes.hex(),
        "privateKey": private_bytes
    }


def sign_message(private_key_bytes: bytes, message: str) -> str:
    """用 Ed25519 私钥签名消息，返回 hex 签名"""
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_key.sign(message.encode("utf-8"))
    return signature.hex()


async def main():
    device = generate_device_identity()
    print(f"Device ID: {device['deviceId'][:16]}...")
    
    async with websockets.connect("ws://127.0.0.1:18789") as ws:
        # === 第1步：等待 challenge ===
        msg = json.loads(await ws.recv())
        print(f"收到: {json.dumps(msg, ensure_ascii=False)}")
        
        if msg.get("event") != "connect.challenge":
            print(f"预期 challenge，收到: {msg}")
            return
        
        nonce = msg["payload"]["nonce"]
        
        # === 第2步：签名 nonce，发送 challenge response ===
        signature = sign_message(device["privateKey"], nonce)
        
        response_msg = json.dumps({
            "connect.response": {
                "nonce": nonce,
                "signature": signature,
                "deviceId": device["deviceId"],
                "publicKey": device["publicKey"]
            }
        })
        await ws.send(response_msg)
        print(f"发送: connect.response (signature={signature[:16]}...)")
        
        # === 第3步：发送 connect 消息 ===
        connect_msg = json.dumps({
            "connect": {
                "role": "operator",
                "scopes": ["operator.read", "operator.write", "operator.approvals", "operator.pairing"],
                "auth": {"token": TOKEN},
                "client": {
                    "id": "peermind-bridge",
                    "mode": "cli",
                    "version": "1.0.0"
                },
                "device": {
                    "id": device["deviceId"],
                    "publicKey": device["publicKey"],
                    "signature": signature,
                    "signedAt": int(time.time() * 1000),
                    "nonce": nonce
                }
            }
        })
        await ws.send(connect_msg)
        print(f"发送: connect")
        
        # === 第4步：等待 hello ===
        hello = json.loads(await ws.recv())
        print(f"Hello: {json.dumps(hello, ensure_ascii=False)[:300]}")
        
        if "error" in hello:
            print(f"连接失败: {hello}")
            return
        
        # === 第5步：列出设备 ===
        list_msg = json.dumps({
            "id": "req-list",
            "method": "device.pair.list",
            "params": {}
        })
        await ws.send(list_msg)
        resp = json.loads(await ws.recv())
        print(f"\n设备列表: {json.dumps(resp, ensure_ascii=False)[:500]}")
        
        pending = resp.get("result", {}).get("pending", [])
        if not pending:
            print("\n没有待审批请求。")
            return
        
        for p in pending:
            req_id = p["requestId"]
            print(f"\n批准: {req_id}")
            approve_msg = json.dumps({
                "id": "req-approve",
                "method": "device.pair.approve",
                "params": {"requestId": req_id}
            })
            await ws.send(approve_msg)
            resp = json.loads(await ws.recv())
            print(f"批准结果: {json.dumps(resp, ensure_ascii=False)}")
        
        print("\n完成！")

if __name__ == "__main__":
    asyncio.run(main())
