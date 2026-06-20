"""
Agent 服务端：每个 Agent 独立运行的小型 HTTP 服务
接收其他 Agent 的 P2P 直连消息，验签后处理
支持 HTTP (POST /agent/v1) 和 WebSocket (ws://.../ws) 两种通信方式
"""
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import httpx
import uvicorn
import json
import asyncio
from urllib.parse import urlparse

from .crypto import (
    generate_keypair,
    sign_message,
    verify_signature,
    build_message_bytes,
)
from .models import AgentMessage, Capability


class AgentServer:
    """
    Agent 独立服务端
    每个 Agent 实例化时生成自己的密钥对，暴露 /agent/v1 接收消息
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        display_name: str,
        port: int,
        registry_url: str,
        capabilities: list[Capability] = None,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.display_name = display_name
        self.port = port
        self.registry_url = registry_url
        self.capabilities = capabilities or []

        # 每个 Agent 生成自己的密钥对
        self.private_key, self.public_key = generate_keypair()

        # 创建 FastAPI 应用
        self.app = FastAPI(title=f"Agent: {agent_id}")

        # 活跃的 WebSocket 连接：{agent_id: WebSocket}
        self.active_connections: dict[str, WebSocket] = {}

        # 消息处理回调：收到消息时调用（HTTP 和 WS 共用）
        self.on_message = None

        # 注册路由
        self._setup_routes()

    def _setup_routes(self):
        """注册 Agent 服务端的路由"""

        # ── HTTP 端点（保留）──

        @self.app.post("/agent/v1")
        async def receive_message(msg: AgentMessage):
            """
            接收其他 Agent 发来的 P2P 消息（HTTP 方式）
            1. 从 Registry 获取发送方公钥
            2. 验证签名
            3. 调用 on_message 回调处理
            """
            # 验证签名：先从 Registry 查发送方公钥
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    r = await client.get(
                        f"{self.registry_url}/api/v1/agents/{msg.from_agent}"
                    )
                    if r.status_code != 200:
                        raise HTTPException(
                            status_code=400,
                            detail=f"无法获取发送方信息: {r.text}",
                        )
                    sender = r.json()
                except httpx.RequestError as e:
                    raise HTTPException(status_code=502, detail=f"Registry 不可达: {e}")

            # 验证签名
            msg_bytes = build_message_bytes(msg.model_dump(by_alias=True))
            if not verify_signature(sender["public_key"], msg_bytes, msg.signature):
                raise HTTPException(status_code=401, detail="消息签名验证失败，可能被伪造")

            # 调用回调处理消息
            if self.on_message:
                reply = await self.on_message(msg)
                return reply or {"status": "received", "message_id": msg.id}

            return {"status": "received", "message_id": msg.id}

        # ── WebSocket 端点（新增）──

        @self.app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            """
            WebSocket 长连接端点
            握手机制：
              客户端发 → {type:"handshake", agent_id, signature}
              服务端验证身份后回复 → {type:"handshake_ack", agent_id}
            后续消息：
              客户端发 → {type:"message", intent, payload, ...}
              服务端回复 → {type:"message", intent, payload, ...}
              或 → {type:"error", detail}
            """
            await websocket.accept()
            peer_id = None

            try:
                # ── 阶段 1：握手 ──
                data = await websocket.receive_json()

                if data.get("type") != "handshake":
                    await websocket.send_json({
                        "type": "error", "detail": "第一个消息必须是 handshake"
                    })
                    await websocket.close(code=4000)
                    return

                peer_id = data.get("agent_id")
                if not peer_id:
                    await websocket.send_json({
                        "type": "error", "detail": "handshake 缺少 agent_id"
                    })
                    await websocket.close(code=4000)
                    return

                # 验证握手签名：Registry 查公钥
                async with httpx.AsyncClient(timeout=10) as client:
                    try:
                        r = await client.get(
                            f"{self.registry_url}/api/v1/agents/{peer_id}"
                        )
                        if r.status_code != 200:
                            await websocket.send_json({
                                "type": "error",
                                "detail": f"未找到 Agent: {peer_id}"
                            })
                            await websocket.close(code=4001)
                            return
                        sender = r.json()
                    except httpx.RequestError as e:
                        await websocket.send_json({
                            "type": "error", "detail": f"Registry 不可达: {e}"
                        })
                        await websocket.close(code=4500)
                        return

                # 握手签名内容：agent_id={对方}&peer={我}
                hs_bytes = f"agent_id={peer_id}&peer={self.agent_id}".encode()
                hs_sig = data.get("signature", "")
                if not verify_signature(sender["public_key"], hs_bytes, hs_sig):
                    await websocket.send_json({
                        "type": "error", "detail": "握手签名验证失败"
                    })
                    await websocket.close(code=4001)
                    return

                # 握手成功
                self.active_connections[peer_id] = websocket
                await websocket.send_json({
                    "type": "handshake_ack",
                    "agent_id": self.agent_id,
                })

                # ── 阶段 2：消息循环 ──
                while True:
                    msg_data = await websocket.receive_json()

                    if msg_data.get("type") == "ping":
                        # 心跳
                        await websocket.send_json({"type": "pong"})
                        continue

                    if msg_data.get("type") == "message":
                        # 封装为 AgentMessage 后回调
                        am = AgentMessage(
                            from_agent=peer_id,
                            to_agent=self.agent_id,
                            intent=msg_data.get("intent", ""),
                            payload=msg_data.get("payload", {}),
                            in_reply_to=msg_data.get("in_reply_to"),
                        )

                        if self.on_message:
                            reply = await self.on_message(am)
                        else:
                            reply = {"status": "received", "message_id": am.id}

                        # 把回复发回去
                        await websocket.send_json({
                            "type": "message",
                            "intent": "skill_response",
                            "payload": reply or {"status": "received"},
                            "in_reply_to": am.id,
                        })

            except WebSocketDisconnect:
                # 对方断开连接，正常清理
                pass
            except Exception as e:
                try:
                    await websocket.send_json({
                        "type": "error", "detail": str(e),
                    })
                except Exception:
                    pass
            finally:
                if peer_id:
                    self.active_connections.pop(peer_id, None)

        # ── 健康检查（HTTP 和 WS 共用）──

        @self.app.get("/health")
        async def health():
            return {"status": "ok", "agent": self.agent_id}

    async def register(self):
        """向 Registry 注册自己"""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{self.registry_url}/api/v1/agents/register",
                json={
                    "agent_id": self.agent_id,
                    "agent_type": self.agent_type,
                    "display_name": self.display_name,
                    "public_key": self.public_key,
                    "endpoint": f"http://127.0.0.1:{self.port}/agent/v1",
                    "capabilities": [
                        {"skill": c.skill, "description": c.description}
                        for c in self.capabilities
                    ],
                },
            )
            if r.status_code not in (200, 201):
                raise Exception(f"注册失败: {r.status_code} {r.text}")
            return r.json()

    async def connect_ws(self, to_agent: str):
        """
        以 WebSocket 方式连接到目标 Agent（客户端视角）
        1. 查 Registry 获取目标地址
        2. 建立 WebSocket 连接
        3. 发送握手（含签名）
        4. 验证握手确认
        5. 返回 ws 对象供后续收发
        """
        import websockets

        # 1. 查黄页
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.registry_url}/api/v1/agents/{to_agent}")
            if r.status_code != 200:
                raise Exception(f"目标 Agent 不存在: {to_agent}")
            target = r.json()

        # 2. 从 HTTP endpoint 推导 WS 地址
        parsed = urlparse(target["endpoint"])
        ws_url = f"ws://{parsed.hostname}:{parsed.port}/ws"

        # 3. 建立 WebSocket 连接
        ws = await websockets.connect(ws_url)

        # 4. 发送握手（签名）
        hs_bytes = f"agent_id={self.agent_id}&peer={to_agent}".encode()
        signature = sign_message(self.private_key, hs_bytes)
        await ws.send(json.dumps({
            "type": "handshake",
            "agent_id": self.agent_id,
            "signature": signature,
        }))

        # 5. 接收确认
        ack = json.loads(await ws.recv())
        if ack.get("type") != "handshake_ack":
            await ws.close()
            raise Exception(f"握手失败: {ack}")

        # 6. 记录连接
        self.active_connections[to_agent] = ws
        return ws

    async def send_message(
        self, to_agent: str, intent: str, payload: dict, in_reply_to: str = None,
        return_reply: bool = False,
    ):
        """
        P2P 直连发送消息到目标 Agent
        1. 从 Registry 查询目标 Agent 的 endpoint
        2. 构造消息并签名
        3. 直接 POST 到目标 Agent 的 /agent/v1 端点
        如果 return_reply=True，返回 (msg, 对方回复的 dict)
        """
        async with httpx.AsyncClient(timeout=30) as client:
            # 查询目标 Agent 信息
            r = await client.get(f"{self.registry_url}/api/v1/agents/{to_agent}")
            if r.status_code != 200:
                raise Exception(f"目标Agent不存在: {to_agent}")
            target = r.json()

        # 构造消息
        msg = AgentMessage(
            from_agent=self.agent_id,
            to_agent=to_agent,
            intent=intent,
            payload=payload,
            in_reply_to=in_reply_to,
        )

        # 签名
        msg_bytes = build_message_bytes(msg.model_dump(by_alias=True))
        msg.signature = sign_message(self.private_key, msg_bytes)

        # P2P 直连发送到目标 endpoint（超时60s：对方的 on_message 可能要调 LLM）
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                target["endpoint"],
                json=msg.model_dump(mode="json", by_alias=True),
            )
            if r.status_code not in (200, 201):
                raise Exception(f"发送失败: {r.status_code} {r.text}")

            if return_reply:
                reply_data = r.json()
                return msg, reply_data
            return msg

    async def search_agents(self, **kwargs) -> list[dict]:
        """搜索其他 Agent"""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{self.registry_url}/api/v1/directory/search",
                params=kwargs,
            )
            result = r.json()
            return result.get("agents", [])

    def start(self):
        """启动 Agent 服务（阻塞）"""
        uvicorn.run(self.app, host="127.0.0.1", port=self.port, log_level="warning")

    def start_background(self):
        """非阻塞启动（Demo 用，后台线程）"""
        import threading

        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=self.port, log_level="warning"
        )
        server = uvicorn.Server(config)
        self._thread = threading.Thread(target=server.run, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 5.0):
        """等待 Agent 服务就绪"""
        import time

        start = time.time()
        while time.time() - start < timeout:
            try:
                r = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise Exception(
            f"Agent {self.agent_id} on port {self.port} 启动超时"
        )
