"""
消息存储层：发送、接收、查询
"""
import json
from .database import get_connection
from .models import AgentMessage


def store_message(msg: AgentMessage) -> AgentMessage:
    """
    存储消息到收件箱
    参数：完整的 AgentMessage（已含签名）
    返回：存储后的消息
    """
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO messages (id, from_agent, to_agent, intent, payload, in_reply_to, signature, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
                msg.intent,
                json.dumps(msg.payload, ensure_ascii=False),
                msg.in_reply_to,
                msg.signature,
                msg.timestamp,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return msg


def get_inbox(agent_id: str, limit: int = 50) -> list[AgentMessage]:
    """
    查询指定 Agent 的收件箱
    按时间倒序，最近的消息在前
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE to_agent = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (agent_id, limit),
        ).fetchall()

        messages = []
        for row in rows:
            messages.append(
                AgentMessage(
                    id=row["id"],
                    from_agent=row["from_agent"],
                    to_agent=row["to_agent"],
                    intent=row["intent"],
                    payload=json.loads(row["payload"]),
                    in_reply_to=row["in_reply_to"],
                    timestamp=row["timestamp"],
                    signature=row["signature"],
                )
            )
        return messages
    finally:
        conn.close()


def get_conversation(agent_a: str, agent_b: str, limit: int = 50) -> list[AgentMessage]:
    """
    查询两个 Agent 之间的对话历史
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE (from_agent = ? AND to_agent = ?)
                  OR (from_agent = ? AND to_agent = ?)
               ORDER BY timestamp DESC
               LIMIT ?""",
            (agent_a, agent_b, agent_b, agent_a, limit),
        ).fetchall()

        messages = []
        for row in rows:
            messages.append(
                AgentMessage(
                    id=row["id"],
                    from_agent=row["from_agent"],
                    to_agent=row["to_agent"],
                    intent=row["intent"],
                    payload=json.loads(row["payload"]),
                    in_reply_to=row["in_reply_to"],
                    timestamp=row["timestamp"],
                    signature=row["signature"],
                )
            )
        return messages
    finally:
        conn.close()
