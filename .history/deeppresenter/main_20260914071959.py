import json
import traceback
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal

from deeppresenter.agents.design import Design
from deeppresenter.agents.env import AgentEnv
from deeppresenter.agents.planner import Planner
from deeppresenter.agents.pptagent import PPTAgent
from deeppresenter.agents.research import Research
from deeppresenter.agents.subagent import SubAgent
from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.constants import WORKSPACE_BASE
from deeppresenter.utils.log import debug, error, set_logger, timer, warning
from deeppresenter.utils.typings import ChatMessage, ConvertType, InputRequest, Role
from deeppresenter.utils.webview import PlaywrightConverter, convert_html_to_pptx


class AgentLoop:
    # 创建AgentLoop后，会自动调用这个函数
    def __init__(
        self,系统缺失民宿站外流量归因能力，搭建民宿业务线专属渠道归因体系，补齐订单收入
•解决交易侧重复请求导致重复归因问题：基于订单ID设计Redis分布式幂等方案，缓存拦截重复请
求、跳过触达日志重复查询，保证多次调用输出统一归因结果。
•下单高峰期大量请求同步查询触达日志，原表全表扫描导致查询阻塞：新建用户ID+触达时间复合
索引，精简查询字段，优化后日志查询耗时从平均80ms降至15ms以内。
•应对营销活动瞬时突刺流量：基于RateLimiter实现单机接口限流，设置单实例QPS上限，超限请求
直接降级返回兜底归因结果。
分销渠道缺少自动化预算管控机制，搭建全渠道佣金预算管控体系，实现佣金额度严格管控、杜绝超支
•解决高并发下单并行执行导致重复扣回、重复告警问题：基于Redis+Lua实现超佣状态幂等判断，预
算累加、超支校验、金额扣回、超佣打标全流程原子化，避免重复更新状态与推送消息。
•解决Redis与MySQL数据一致性问题：设计定时对账回填机制，以数据库订单数据为基准修正缓存，
兼顾实时管控性能与资金数据可靠性。
•解决多渠道佣金通知内容差异化、业务代码臃肿难维护问题：基于策略模式抽象渠道通知处理器，按
渠道类型分发独立消息组装逻辑，新增渠道无需修改核心流程，降低代码耦合与迭代成本。erConfig,
        session_id: str | None = None,
        workspace: Path | None = None,
        language: Literal["zh", "en"] = "en",
    ):
        self.config = config
        self.language = language
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]
        self.workspace = workspace or WORKSPACE_BASE / session_id
        self.intermediate_output: dict[str, str | Path] = {}
        self.agent = None
        set_logger(
            f"deeppresenter-loop-{self.workspace.stem}",
            self.workspace / ".history" / "deeppresenter-loop.log",
        )
        debug(f"Initialized AgentLoop with workspace={self.workspace}")
        debug(f"Config: {self.config.model_dump_json(indent=2)}")

    @timer("DeepPresenter Loop")
    async def run(
        self,
        request: InputRequest,
        check_llms: bool = False,
        soft_parsing: bool = True,
    ) -> AsyncGenerator[str | ChatMessage, None]:
        """Main loop for DeepPresenter generation process.
        Arguments:
            request: InputRequest object containing task details.
            check_llms: Whether to check LLM availability before running.
            soft_parsing: Whether to use soft parsing on html2pptx.
        Yields:
            ChatMessage or final output path (str). Outline path stored in intermediate_output["outline"].
        """
        if not self.config.design_agent.is_multimodal and self.config.heavy_reflect:
            debug(
                "Reflective design requires a multimodal LLM in the design agent, reflection will only enable on textual state."
            )
        if check_llms:
            await self.config.validate_llms()
        request.copy_to_workspace(self.workspace)
        with open(self.workspace / ".input_request.json", "w") as f:
            json.dump(request.model_dump(), f, ensure_ascii=False, indent=2)
        async with AgentEnv(self.workspace, self.config) as agent_env:
            hello_message = f"DeepPresenter running in {self.workspace}, with {len(request.attachments)} attachments, prompt={request.instruction}"
            modes = []
            if self.config.offline_mode:
                modes.append("Offline Mode")
            self.agent_env = agent_env
            if self.config.multiagent_mode:
                self.agent_env.register_tool(
                    SubAgent.delegate(
                        self.config, agent_env, self.workspace, self.language
                    )
                )
                modes.append("Multiagent Mode")
            if modes:
                hello_message += f" [{', '.join(modes)}]"
            debug(hello_message)

            yield ChatMessage(role=Role.SYSTEM, content=hello_message)

            # ── Optional Planner phase ────────────────────────────────────
            if request.enable_planner:
                self.planner = Planner(
                    self.config,
                    agent_env,
                    self.workspace,
                    self.language,
                )
                self.agent = self.planner
                self.planner_gen = self.planner.loop(request)
                try:
                    async for msg in self.planner_gen:
                        if isinstance(msg, str):
                            self.intermediate_output["outline"] = msg
                            yield msg
                            break
                        yield msg
                except Exception as e:
                    error_message = f"Planner agent failed with error: {e}\n{traceback.format_exc()}"
                    error(error_message)
                    raise e
                finally:
                    self.planner.save_history()
                    await self.planner_gen.aclose()
                    self.save_results()

            self.research_agent = Research(
                self.config,
                agent_env,
                self.workspace,
                self.language,
            )
            self.agent = self.research_agent
            try:
                async for msg in self.research_agent.loop(
                    request, self.intermediate_output.get("outline", None)
                ):
                    if isinstance(msg, str):
                        md_file = Path(msg)
                        if not md_file.is_absolute():
                            md_file = self.workspace / md_file
                        self.intermediate_output["manuscript"] = md_file
                        msg = str(md_file)
                        break
                    yield msg
            except Exception as e:
                error_message = (
                    f"Research agent failed with error: {e}\n{traceback.format_exc()}"
                )
                error(error_message)
                raise e
            finally:
                self.research_agent.save_history()
                self.save_results()

            if request.convert_type == ConvertType.PPTAGENT:
                self.pptagent = PPTAgent(
                    self.config,
                    agent_env,
                    self.workspace,
                    self.language,
                )
                self.agent = self.pptagent
                try:
                    async for msg in self.pptagent.loop(request, str(md_file)):
                        if isinstance(msg, str):
                            pptx_file = Path(msg)
                            if not pptx_file.is_absolute():
                                pptx_file = self.workspace / pptx_file
                            self.intermediate_output["pptx"] = pptx_file
                            self.intermediate_output["final"] = pptx_file
                            msg = str(pptx_file)
                            break
                        yield msg
                except Exception as e:
                    error_message = (
                        f"PPTAgent failed with error: {e}\n{traceback.format_exc()}"
                    )
                    error(error_message)
                    raise e
                finally:
                    self.pptagent.save_history()
                    self.save_results()
            else:
                self.designagent = Design(
                    self.config,
                    agent_env,
                    self.workspace,
                    self.language,
                )
                self.agent = self.designagent
                try:
                    async for msg in self.designagent.loop(request, str(md_file)):
                        if isinstance(msg, str):
                            slide_html_dir = Path(msg)
                            if not slide_html_dir.is_absolute():
                                slide_html_dir = self.workspace / slide_html_dir
                            self.intermediate_output["slide_html_dir"] = slide_html_dir
                            break
                        yield msg
                except Exception as e:
                    error_message = (
                        f"Design agent failed with error: {e}\n{traceback.format_exc()}"
                    )
                    error(error_message)
                    raise e
                finally:
                    self.designagent.save_history()
                    self.save_results()
                pptx_path = self.workspace / f"{md_file.stem}.pptx"
                try:
                    # ? this feature is in experimental stage
                    await convert_html_to_pptx(
                        slide_html_dir,
                        pptx_path,
                        aspect_ratio=request.powerpoint_type.value,
                        soft_parsing=soft_parsing,
                    )
                except Exception as e:
                    warning(
                        f"html2pptx conversion failed, falling back to pdf conversion\n{e}"
                    )
                    pptx_path = pptx_path.with_suffix(".pdf")
                    (self.workspace / ".html2pptx-error.txt").write_text(
                        str(e) + "\n" + traceback.format_exc()
                    )
                finally:
                    async with PlaywrightConverter() as pc:
                        await pc.convert_to_pdf(
                            list(slide_html_dir.glob("*.html")),
                            pptx_path.with_suffix(".pdf"),
                            aspect_ratio=request.powerpoint_type.value,
                        )

                self.intermediate_output["final"] = str(pptx_path)
                msg = pptx_path
            self.save_results()
            debug(f"DeepPresenter finished, final output at: {msg}")
            yield msg

    def save_results(self):
        with open(self.workspace / "intermediate_output.json", "w") as f:
            json.dump(
                {k: str(v) for k, v in self.intermediate_output.items()},
                f,
                ensure_ascii=False,
                indent=2,
            )
