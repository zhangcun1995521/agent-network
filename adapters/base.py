"""
AgentAdapter 基类
每个外部工具（CodeBuddy、Claude Code、OpenClaw）继承此类，
统一处理 PeerMind 注册、消息路由和技能分发。

注意：本模块依赖 agent_network 包，必须从仓库根目录用 `python -m` 运行，
例如 `python -m examples.demo_codebuddy_adapter`。
"""
import asyncio

from agent_network.agent_server import AgentServer  # P2P 通信服务端
from agent_network.models import Capability, AgentMessage  # 数据模型


class AgentAdapter:
    """
    基类：封装 PeerMind 注册 + 消息路由
    子类只需实现 _execute_skill() 即可接入 PeerMind 网络
    """

    def __init__(
        self,
        agent_id: str,        # PeerMind 身份，如 peermind://personal/zhangcun/codebuddy-adapter
        agent_type: str,      # 类型：individual_verified / organization
        display_name: str,    # 显示名
        port: int,            # 监听端口
        registry_url: str,    # Registry 地址
        capabilities: dict,   # {skill_name: description}
    ):
        # 把 dict 格式的能力声明转为 Capability 对象列表
        caps = [Capability(skill=k, description=v) for k, v in capabilities.items()]

        # 复用 PeerMind 的 AgentServer，它会生成密钥对 + 启动 HTTP/WS 服务
        self.server = AgentServer(
            agent_id=agent_id,
            agent_type=agent_type,
            display_name=display_name,
            port=port,
            registry_url=registry_url,
            capabilities=caps,
        )

        # 注册消息回调：收到其他 Agent 的消息时自动调用
        self.server.on_message = self._handle_message

    # ── 生命周期 ──

    async def start(self):
        """启动 Adapter：后台服务 + 向 Registry 注册 + 等待就绪"""
        self.server.start_background()               # Uvicorn 在后台线程启动
        self.server.wait_ready(timeout=5)            # 等 HTTP 服务就绪
        profile = await self.server.register()       # 向 Registry 注册身份+能力
        print(f"[Adapter] 已注册: {self.server.agent_id}")
        return profile

    # ── 消息路由 ──

    async def _handle_message(self, msg: AgentMessage):
        """
        收到 PeerMind 消息时的入口
        根据 intent 分发：
          - skill_request → 调用对应技能 → 返回 skill_response
          - info_query     → 返回自身状态
          - ping           → 返回 pong
        """
        intent = msg.intent

        if intent == "skill_request":
            skill = msg.payload.get("skill", "")
            params = msg.payload.get("params", {})
            print(f"[Adapter] 收到技能请求: {skill} 来自 {msg.from_agent}")

            try:
                result = await self._execute_skill(skill, params)
                return {"status": "ok", "result": result}
            except Exception as e:
                return {"status": "error", "error": str(e)}

        elif intent == "info_query":
            return {
                "agent": self.server.agent_id,
                "display_name": self.server.display_name,
                "capabilities": list(self.capabilities.keys()) if hasattr(self, 'capabilities') else [],
            }

        elif intent == "ping":
            return {"status": "pong"}

        return {"status": "received", "message_id": msg.id}

    # ── 子类覆盖这个方法 ──

    async def _execute_skill(self, skill: str, params: dict) -> str:
        """子类实现：根据 skill 名称执行具体操作，返回结果字符串"""
        raise NotImplementedError
