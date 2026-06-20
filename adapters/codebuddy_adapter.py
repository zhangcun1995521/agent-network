"""
CodeBuddy Adapter：把 CodeBuddy 注册为 PeerMind agent
通过 subprocess 调用 codebuddy CLI 执行代码任务
"""
import sys
import subprocess
sys.path.insert(0, "D:/projects/agent-network")

from adapters.base import AgentAdapter  # 继承基类


class CodeBuddyAdapter(AgentAdapter):
    """CodeBuddy 工具适配器"""

    # ── 能力声明：PeerMind 黄页里搜到时会展示这些 ──
    SKILLS = {
        "code_review": "审查代码：检测 bug、安全漏洞、风格问题，返回改进建议",
        "code_generate": "根据自然语言描述生成代码",
        "bug_fix": "根据错误信息诊断并修复代码 bug",
        "file_read": "读取本地文件内容（指定绝对路径）",
    }

    def __init__(
        self,
        port: int = 8560,
        registry_url: str = "http://127.0.0.1:8000",
        agent_id: str = None,
    ):
        super().__init__(
            agent_id=agent_id or "peermind://local.dev/codebuddy-adapter",
            agent_type="individual_verified",
            display_name="CodeBuddy Adapter",
            port=port,
            registry_url=registry_url,
            capabilities=self.SKILLS,
        )

    # ── 技能实现 ──

    async def _execute_skill(self, skill: str, params: dict) -> str:
        """根据 skill 名称路由到具体实现"""
        if skill == "code_review":
            return await self._code_review(params)
        elif skill == "code_generate":
            return await self._code_generate(params)
        elif skill == "bug_fix":
            return await self._bug_fix(params)
        elif skill == "file_read":
            return await self._file_read(params)
        else:
            raise ValueError(f"未知技能: {skill}，支持: {list(self.SKILLS.keys())}")

    async def _code_review(self, params: dict) -> str:
        """审查代码"""
        code = params["code"]                           # 要审查的代码
        language = params.get("language", "")            # 语言（可选，如 python）
        prompt = (
            f"Review the following {language} code for bugs, security issues, "
            f"and style improvements. Reply concisely in Chinese.\n\n"
            f"```{language}\n{code}\n```"
        )
        return await self._call_codebuddy(prompt)

    async def _code_generate(self, params: dict) -> str:
        """根据描述生成代码"""
        description = params["description"]              # 功能描述
        language = params.get("language", "python")      # 目标语言
        prompt = (
            f"Write {language} code for: {description}. "
            f"Output only the code with brief inline comments in Chinese."
        )
        return await self._call_codebuddy(prompt)

    async def _bug_fix(self, params: dict) -> str:
        """修复 bug"""
        code = params["code"]                            # 有 bug 的代码
        error = params.get("error", "")                  # 错误信息
        prompt = (
            f"Fix the bug in this code. The error is: {error}\n\n"
            f"```\n{code}\n```\n\n"
            f"Explain the root cause in Chinese and show the corrected code."
        )
        return await self._call_codebuddy(prompt)

    async def _file_read(self, params: dict) -> str:
        """读取本地文件（不调 AI，直接读）"""
        path = params["path"]
        import os
        if not os.path.exists(path):
            return f"错误：文件不存在 - {path}"
        if not os.path.isfile(path):
            return f"错误：不是普通文件 - {path}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"--- {path} ---\n{content}"
        except Exception as e:
            return f"读取失败: {e}"

    # ── CLI 调用 ──

    async def _call_codebuddy(self, prompt: str) -> str:
        """
        调用 CodeBuddy CLI 子进程处理 prompt
        如果 CLI 不可用，返回模拟响应（Demo 模式）
        """
        import os as _os

        # CodeBuddy CLI 完整路径（npm 全局安装）
        _cli_paths = [
            r"C:\Users\86183\AppData\Roaming\npm\codebuddy.cmd",
            r"C:\Users\86183\AppData\Roaming\npm\codebuddy",
        ]
        cli = None
        for p in _cli_paths:
            if _os.path.exists(p):
                cli = p
                break

        try:
            if not cli:
                raise FileNotFoundError("CodeBuddy CLI")

            # 通过 stdin 传入 prompt（避免 -p 参数对多行文本截断）
            # shell=True 是 Windows 运行 .cmd 的需要
            proc = subprocess.run(
                f'"{cli}" -p -y',
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
                cwd="D:/projects/agent-network",
                shell=True,
            )
            if proc.returncode != 0:
                raise Exception(proc.stderr or f"退出码 {proc.returncode}")
            return proc.stdout.strip()

        except FileNotFoundError:
            # CLI 未安装 → Demo 模式返回模拟结果
            return (
                f"[Demo模式] CodeBuddy CLI 未找到。\n"
                f"在实际环境中会处理以下 prompt：\n"
                f"{prompt[:200]}..."
            )
        except subprocess.TimeoutExpired:
            return "错误：CodeBuddy 调用超时（超过120秒）"
