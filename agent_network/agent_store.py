"""
Agent 存储层：注册、查询、搜索
"""
import json
from datetime import datetime, timezone
from .database import get_connection
from .models import AgentProfile, Capability


def register_agent(
    agent_id: str,
    agent_type: str,
    display_name: str,
    public_key: str,
    endpoint: str,
    capabilities: list[Capability],
) -> AgentProfile:
    """
    注册新 Agent
    返回完整的 AgentProfile
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute(
            """INSERT INTO agents (agent_id, agent_type, display_name, public_key, endpoint, registered_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, agent_type, display_name, public_key, endpoint, now, now),
        )

        # 插入技能
        for cap in capabilities:
            conn.execute(
                """INSERT OR REPLACE INTO capabilities (agent_id, skill, description)
                   VALUES (?, ?, ?)""",
                (agent_id, cap.skill, cap.description),
            )

        conn.commit()
    finally:
        conn.close()

    return get_agent(agent_id)


def get_agent(agent_id: str) -> AgentProfile:
    """
    通过 Agent ID 查询完整信息
    不存在时抛出 ValueError
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM agents WHERE agent_id = ? AND is_active = 1",
            (agent_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"Agent 不存在: {agent_id}")

        caps = conn.execute(
            "SELECT skill, description FROM capabilities WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()

        return AgentProfile(
            agent_id=row["agent_id"],
            agent_type=row["agent_type"],
            display_name=row["display_name"],
            public_key=row["public_key"],
            endpoint=row["endpoint"],
            capabilities=[
                Capability(skill=c["skill"], description=c["description"])
                for c in caps
            ],
            is_active=bool(row["is_active"]),
            registered_at=row["registered_at"],
            updated_at=row["updated_at"],
        )
    finally:
        conn.close()


def search_agents(
    q: str = None,
    skill: str = None,
    organization: str = None,
    agent_type: str = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[AgentProfile], int]:
    """
    搜索 Agent 黄页
    支持关键词、技能、组织、类型过滤
    返回 (Agent列表, 总数)
    """
    conn = get_connection()
    try:
        where_clauses = ["a.is_active = 1"]
        params = []

        if q:
            where_clauses.append(
                "(a.agent_id LIKE ? OR a.display_name LIKE ?)"
            )
            params.extend([f"%{q}%", f"%{q}%"])

        if organization:
            where_clauses.append("a.agent_id LIKE ?")
            params.append(f"peermind://{organization}%")

        if agent_type:
            where_clauses.append("a.agent_type = ?")
            params.append(agent_type)

        if skill:
            # 按技能过滤需要 JOIN capabilities 表
            where_clauses.append("a.agent_id IN (SELECT agent_id FROM capabilities WHERE skill = ?)")
            params.append(skill)

        where_sql = " AND ".join(where_clauses)

        # 查询总数
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM agents a WHERE {where_sql}", params
        ).fetchone()
        total = count_row[0]

        # 分页查询
        offset = (page - 1) * limit
        rows = conn.execute(
            f"SELECT a.* FROM agents a WHERE {where_sql} ORDER BY a.registered_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        agents = []
        for row in rows:
            caps = conn.execute(
                "SELECT skill, description FROM capabilities WHERE agent_id = ?",
                (row["agent_id"],),
            ).fetchall()
            agents.append(
                AgentProfile(
                    agent_id=row["agent_id"],
                    agent_type=row["agent_type"],
                    display_name=row["display_name"],
                    public_key=row["public_key"],
                    endpoint=row["endpoint"],
                    capabilities=[
                        Capability(skill=c["skill"], description=c["description"])
                        for c in caps
                    ],
                    is_active=bool(row["is_active"]),
                    registered_at=row["registered_at"],
                    updated_at=row["updated_at"],
                )
            )

        return agents, total
    finally:
        conn.close()
