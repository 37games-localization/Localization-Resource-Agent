#!/usr/bin/env python3
"""
workflow_engine.py
==================
Agent 行动可视化 + Human Decision 暂停-恢复机制

核心概念：
  - WorkflowRun   : 一次工作流执行实例，有唯一 run_id
  - trace()       : 记录 Agent 每一步行动（输入/输出/状态）
  - checkpoint()  : Human Decision 节点，Agent 在此暂停，等待人的指令
  - resume()      : 人给出决策后，从 checkpoint 恢复继续执行

飞书日志表字段（流程日志表由 config.local.yaml 或字段映射提供）：
  run_id / step_name / step_type / input_summary / output_summary /
  status / decision / created_at / candidate_name
"""

import json
import uuid
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Any
import sys

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark
try:
    from field_resolver import load_field_mapping, get_table_mapping, table_ref
except Exception:
    load_field_mapping = None
    get_table_mapping = None
    table_ref = None

# ── 步骤类型 ──────────────────────────────────────────────────────────────────
class StepType:
    ACTION     = "action"      # Agent 自动执行的动作
    CHECKPOINT = "checkpoint"  # Human Decision 节点，需要暂停等待
    DECISION   = "decision"    # 人的决策记录
    ERROR      = "error"       # 异常节点

# ── 步骤状态 ──────────────────────────────────────────────────────────────────
class StepStatus:
    RUNNING   = "running"    # 执行中
    DONE      = "done"       # 完成
    WAITING   = "waiting"    # 等待人决策
    DECIDED   = "decided"    # 人已决策
    SKIPPED   = "skipped"    # 跳过
    FAILED    = "failed"     # 失败

# ── 终端输出样式 ──────────────────────────────────────────────────────────────
ICONS = {
    StepType.ACTION:     "▶",
    StepType.CHECKPOINT: "⏸",
    StepType.DECISION:   "✅",
    StepType.ERROR:      "❌",
}
STATUS_ICONS = {
    StepStatus.RUNNING:  "🔄",
    StepStatus.DONE:     "✅",
    StepStatus.WAITING:  "⏳",
    StepStatus.DECIDED:  "👤",
    StepStatus.SKIPPED:  "⏭",
    StepStatus.FAILED:   "❌",
}


class WorkflowStep:
    """单个工作流步骤的数据结构"""

    def __init__(
        self,
        run_id: str,
        step_name: str,
        step_type: str = StepType.ACTION,
        input_summary: str = "",
        candidate_name: str = "",
        candidate_record_id: str = "",
    ):
        self.step_id       = str(uuid.uuid4())[:8]
        self.run_id        = run_id
        self.step_name     = step_name
        self.step_type     = step_type
        self.input_summary = input_summary
        self.output_summary= ""
        self.status        = StepStatus.RUNNING
        self.decision      = ""
        self.candidate_name= candidate_name
        self.candidate_record_id = candidate_record_id
        self.created_at    = datetime.now().isoformat()
        self.updated_at    = self.created_at
        self._start_ts     = time.time()

    def finish(self, output_summary: str = "", status: str = StepStatus.DONE):
        self.output_summary = output_summary
        self.status         = status
        self.updated_at     = datetime.now().isoformat()

    def elapsed(self) -> str:
        secs = time.time() - self._start_ts
        return f"{secs:.1f}s"

    def to_lark_record(self) -> dict:
        """转为飞书多维表格写入格式（裸 Map）"""
        return {
            "run_id":          self.run_id,
            "candidate_record_id": self.candidate_record_id,
            "step_name":       self.step_name,
            "step_type":       self.step_type,
            "input_summary":   self.input_summary[:500],   # 飞书文本长度限制
            "output_summary":  self.output_summary[:500],
            "status":          self.status,
            "decision":        self.decision,
            "candidate_name":  self.candidate_name,
            "created_at":      int(datetime.fromisoformat(self.created_at).timestamp() * 1000),
        }

    def to_logical_record(self) -> dict:
        """转为 schema_validator.py 使用的逻辑字段键格式。"""
        return {
            "workflow.run_id":              self.run_id,
            "workflow.candidate_record_id": self.candidate_record_id,
            "workflow.candidate_name":      self.candidate_name,
            "workflow.step_name":           self.step_name,
            "workflow.step_type":           self.step_type,
            "workflow.status":              self.status,
            "workflow.input_summary":       self.input_summary[:500],
            "workflow.output_summary":      self.output_summary[:500],
            "workflow.decision":            self.decision,
            "workflow.created_at":          int(datetime.fromisoformat(self.created_at).timestamp() * 1000),
        }


class WorkflowEngine:
    """
    工作流执行引擎

    用法：
        engine = WorkflowEngine(candidate_name="测试候选人A")
        with engine.step("分析简历", input="测试候选人A PDF") as s:
            result = do_analysis()
            s.finish(output=f"总分 {result['score']}")

        # Human Decision 节点
        decision = engine.checkpoint(
            node="初筛结果确认",
            context={"score": 82, "tier": "B+"},
            prompt="请确认是否通过初筛？[通过/拒绝/补充]"
        )
    """

    def __init__(
        self,
        candidate_name: str = "",
        run_id: str = None,
        candidate_record_id: str = "",
        silent: bool = False,
        write_lark: bool = True,
        max_failures: int = 5,
    ):
        self.candidate_name = candidate_name
        self.candidate_record_id = candidate_record_id
        self.run_id         = run_id or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:6]}"
        self.silent         = silent        # True = 不打印终端输出
        self.write_lark     = write_lark    # True = 写飞书日志表
        self.max_failures   = max_failures  # 连续失败上限，超过则强制终止
        self._failure_count = 0             # 当前连续失败次数
        self.steps: list[WorkflowStep] = []
        self._pending_checkpoint: Optional[WorkflowStep] = None

        # 加载飞书配置
        try:
            cfg = load_config()
            lark = get_lark(cfg)
            self._lark_base   = lark.get("base_token", "")
            self._lark_log_tbl= lark.get("log_table_id", "")
        except Exception:
            self._lark_base   = ""
            self._lark_log_tbl= ""
        self._apply_workflow_table_mapping()

        self._print_header()

    # ── 内部打印 ───────────────────────────────────────────────────────────────

    def _print_header(self):
        if self.silent:
            return
        name_part = f" · {self.candidate_name}" if self.candidate_name else ""
        print(f"\n{'─'*60}")
        print(f"  工作流启动{name_part}")
        print(f"  Run ID: {self.run_id}")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'─'*60}")

    def _print_step(self, step: WorkflowStep, extra: str = ""):
        if self.silent:
            return
        icon   = ICONS.get(step.step_type, "▶")
        s_icon = STATUS_ICONS.get(step.status, "")
        indent = "  " if step.step_type != StepType.CHECKPOINT else ""
        elapsed= f" [{step.elapsed()}]" if step.status == StepStatus.DONE else ""

        print(f"{indent}{icon} {step.step_name}{elapsed}  {s_icon}")
        if step.input_summary:
            print(f"    ← 输入：{step.input_summary}")
        if step.output_summary:
            print(f"    → 输出：{step.output_summary}")
        if extra:
            print(f"    {extra}")

    # ── 飞书写入 ───────────────────────────────────────────────────────────────

    def _write_log_to_lark(self, step: WorkflowStep) -> str:
        """把步骤写入飞书流程日志表，失败不中断流程；成功时返回 record_id"""
        self._ensure_lark_config()
        if not self.write_lark or not self._lark_base:
            return ""
        try:
            record = self._map_workflow_record(step.to_logical_record(), step.to_lark_record())
            cmd = [
                "lark-cli", "base", "+record-upsert",
                "--base-token", self._lark_base,
                "--table-id",   self._lark_log_tbl,
                "--json",       json.dumps(record, ensure_ascii=False),
                "--format",     "json",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return ""
            try:
                payload = json.loads(result.stdout or "{}")
            except Exception:
                return ""
            data = payload.get("data", payload)
            record_id = (
                data.get("record_id")
                or data.get("record", {}).get("record_id")
                or data.get("record", {}).get("id")
                or data.get("id", "")
            )
            return record_id or ""
        except Exception:
            return ""  # 日志写失败不影响主流程

    def _map_workflow_record(self, logical_record: dict, fallback_record: dict) -> dict:
        """优先用 lark-field-mapping.yaml 的字段 ID；缺映射时回退旧字段名。"""
        if not load_field_mapping or not get_table_mapping:
            return fallback_record
        try:
            mapping = load_field_mapping()
            table = get_table_mapping("workflow_log", mapping)
            fields = table.get("fields") or {}
            if not fields:
                return fallback_record
            mapped = {}
            for logical_key, value in logical_record.items():
                field = fields.get(logical_key) or {}
                target = field.get("field_id") or field.get("field_name")
                if target:
                    mapped[target] = value
            return mapped or fallback_record
        except Exception:
            return fallback_record

    def _map_workflow_patch(self, logical_patch: dict, fallback_patch: dict) -> dict:
        return self._map_workflow_record(logical_patch, fallback_patch)

    def _update_log_decision(self, checkpoint_token: str, record_id: str, decision: str):
        """把 dialog checkpoint 对应的飞书日志行更新为 decided"""
        self._ensure_lark_config()
        if not self.write_lark or not self._lark_base or not record_id:
            return
        try:
            fallback_patch = {
                "status": StepStatus.DECIDED,
                "decision": decision,
                "output_summary": json.dumps(
                    {"checkpoint_token": checkpoint_token, "decision": decision},
                    ensure_ascii=False,
                ),
            }
            patch = self._map_workflow_patch(
                {
                    "workflow.status": StepStatus.DECIDED,
                    "workflow.decision": decision,
                    "workflow.output_summary": fallback_patch["output_summary"],
                },
                fallback_patch,
            )
            cmd = [
                "lark-cli", "base", "+record-upsert",
                "--base-token", self._lark_base,
                "--table-id", self._lark_log_tbl,
                "--record-id", record_id,
                "--json", json.dumps(patch, ensure_ascii=False),
                "--format", "json",
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception:
            pass

    def _ensure_lark_config(self):
        """兼容 WorkflowEngine.__new__() 创建的轻量 resume 实例"""
        if hasattr(self, "write_lark") and hasattr(self, "_lark_base") and hasattr(self, "_lark_log_tbl"):
            return
        self.write_lark = getattr(self, "write_lark", True)
        try:
            cfg = load_config()
            lark = get_lark(cfg)
            self._lark_base = lark.get("base_token", "")
            self._lark_log_tbl = lark.get("log_table_id", "")
        except Exception:
            self._lark_base = ""
            self._lark_log_tbl = ""
        self._apply_workflow_table_mapping()

    def _apply_workflow_table_mapping(self):
        """若字段映射包含 workflow_log 表引用，优先使用映射中的 base/table。"""
        if not table_ref:
            return
        try:
            base_token, table_id = table_ref("workflow_log")
            if base_token and table_id:
                self._lark_base = base_token
                self._lark_log_tbl = table_id
        except Exception:
            pass

    # ── 核心接口 ───────────────────────────────────────────────────────────────

    def trace(
        self,
        step_name: str,
        input_summary: str = "",
        output_summary: str = "",
        status: str = StepStatus.DONE,
    ) -> WorkflowStep:
        """
        记录一个已完成的 Agent 动作（轻量接口，适合单行记录）

        engine.trace("写回飞书", input="record recXXX", output="✅ 写入成功")
        """
        step = WorkflowStep(
            run_id=self.run_id,
            step_name=step_name,
            step_type=StepType.ACTION,
            input_summary=input_summary,
            candidate_name=self.candidate_name,
            candidate_record_id=getattr(self, "candidate_record_id", ""),
        )
        step.finish(output_summary=output_summary, status=status)
        self.steps.append(step)
        self._print_step(step)
        self._write_log_to_lark(step)
        return step

    def step(self, step_name: str, input_summary: str = "") -> "StepContext":
        """
        上下文管理器，用于包裹一段有开始/结束的动作

        with engine.step("调用评分引擎", input="候选人数据") as s:
            result = do_score()
            s.finish(output=f"总分 {result['score']}")
        """
        return StepContext(self, step_name, input_summary)

    def checkpoint(
        self,
        node: str,
        context: dict = None,
        prompt: str = "",
        options: list[str] = None,
        handler: Callable[[str], Any] = None,
        mode: str = "cli",
    ) -> str:
        """
        Human Decision 节点：打印上下文，等待人输入决策。

        参数：
            node      : 节点名称，如"初筛结果确认"
            context   : 当前上下文数据，dict，用于展示给人看
            prompt    : 提示语，告诉人需要做什么决策
            options   : 可选项列表，如 ["通过", "拒绝", "补充"]
            handler   : 可选的决策后处理函数，接收 decision str
            mode      : "cli"（阻塞终端）或 "dialog"（异步，返回 checkpoint_token）

        返回：
            mode="cli"    → 人输入的决策字符串
            mode="dialog" → checkpoint_token 字符串
        """
        step = WorkflowStep(
            run_id=self.run_id,
            step_name=node,
            step_type=StepType.CHECKPOINT,
            input_summary=json.dumps(context or {}, ensure_ascii=False)[:300],
            candidate_name=self.candidate_name,
            candidate_record_id=getattr(self, "candidate_record_id", ""),
        )
        step.status = StepStatus.WAITING
        self.steps.append(step)
        self._pending_checkpoint = step

        # ── dialog 模式：异步，不阻塞 ──────────────────────────────────────────
        if mode == "dialog":
            return self._checkpoint_dialog(node, context, prompt, options, step)

        self._write_log_to_lark(step)

        # ── cli 模式：打印暂停信息 ──────────────────────────────────────────────
        if not self.silent:
            print(f"\n{'━'*60}")
            print(f"  ⏸  需要你的决策：{node}")
            print(f"{'━'*60}")
            if context:
                for k, v in context.items():
                    print(f"  {k}：{v}")
            if prompt:
                print(f"\n  {prompt}")
            if options:
                opts = " / ".join(f"[{o}]" for o in options)
                print(f"  选项：{opts}")
            print()

        # ── 等待输入 ──
        decision = self._wait_for_decision(prompt, options)

        # ── 记录决策 ──
        step.decision = decision
        step.finish(output_summary=f"决策：{decision}", status=StepStatus.DECIDED)

        dec_step = WorkflowStep(
            run_id=self.run_id,
            step_name=f"决策·{node}",
            step_type=StepType.DECISION,
            input_summary=f"选项：{decision}",
            candidate_name=self.candidate_name,
            candidate_record_id=getattr(self, "candidate_record_id", ""),
        )
        dec_step.finish(output_summary=decision, status=StepStatus.DECIDED)
        self.steps.append(dec_step)
        self._write_log_to_lark(dec_step)

        if not self.silent:
            print(f"  👤 已记录决策：{decision}\n")

        if handler:
            handler(decision)

        self._pending_checkpoint = None
        return decision

    def _checkpoint_dialog(
        self,
        node: str,
        context: dict,
        prompt: str,
        options: list,
        step: "WorkflowStep",
    ) -> str:
        """
        Dialog 模式内部实现：
        - 生成 checkpoint_token
        - 把待决策信息写入 ~/.loc-resume-checkpoints/{token}.json
        - 打印结构化输出
        - 返回 checkpoint_token（不阻塞）
        """
        # 生成唯一 token
        checkpoint_token = f"ckpt-{self.run_id}-{step.step_id}"
        step.output_summary = json.dumps(
            {
                "checkpoint_token": checkpoint_token,
                "prompt": prompt,
                "options": options or [],
            },
            ensure_ascii=False,
        )

        # 确保目录存在
        ckpt_dir = Path.home() / ".loc-resume-checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)

        lark_record_id = self._write_log_to_lark(step)

        # 构建 checkpoint 数据
        ckpt_data = {
            "token":      checkpoint_token,
            "run_id":     self.run_id,
            "candidate_record_id": getattr(self, "candidate_record_id", ""),
            "lark_record_id": lark_record_id,
            "node":       node,
            "context":    context or {},
            "prompt":     prompt,
            "options":    options or [],
            "status":     "waiting",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "decision":   None,
        }

        ckpt_file = ckpt_dir / f"{checkpoint_token}.json"
        ckpt_file.write_text(
            json.dumps(ckpt_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 打印结构化输出（OpenClaw 主 session 读取后转发给用户）
        print(f"\n⏸ [CHECKPOINT] node={node} token={checkpoint_token}")
        if context:
            ctx_parts = []
            for k, v in context.items():
                ctx_parts.append(f"{k}: {v}")
            print(" | ".join(ctx_parts))
        if prompt:
            print(prompt)
        if options:
            print(f"请回复：{' / '.join(options)}")

        self._pending_checkpoint = step
        return checkpoint_token

    def resume(self, checkpoint_token: str, decision: str) -> bool:
        """
        从外部传入决策，更新 checkpoint 文件状态。

        参数：
            checkpoint_token : checkpoint() dialog 模式返回的 token
            decision         : 人的决策字符串

        返回：
            True  → 成功
            False → token 不存在或已过期
        """
        ckpt_file = Path.home() / ".loc-resume-checkpoints" / f"{checkpoint_token}.json"
        if not ckpt_file.exists():
            return False

        try:
            ckpt_data = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except Exception:
            return False

        ckpt_data["status"]   = "decided"
        ckpt_data["decision"] = decision
        self._update_log_decision(
            checkpoint_token=checkpoint_token,
            record_id=ckpt_data.get("lark_record_id", ""),
            decision=decision,
        )
        ckpt_file.write_text(
            json.dumps(ckpt_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def wait_for_resume(self, checkpoint_token: str, timeout_seconds: int = 3600) -> str:
        """
        轮询 checkpoint 文件，直到 status=="decided" 或超时。

        参数：
            checkpoint_token : checkpoint() dialog 模式返回的 token
            timeout_seconds  : 超时秒数，默认 3600（1小时）

        返回：decision 字符串，超时返回 "timeout"
        """
        ckpt_file = Path.home() / ".loc-resume-checkpoints" / f"{checkpoint_token}.json"
        deadline  = time.time() + timeout_seconds

        while time.time() < deadline:
            if ckpt_file.exists():
                try:
                    ckpt_data = json.loads(ckpt_file.read_text(encoding="utf-8"))
                    if ckpt_data.get("status") == "decided":
                        return ckpt_data.get("decision", "")
                except Exception:
                    pass
            time.sleep(2)

        return "timeout"

    def _wait_for_decision(self, prompt: str, options: list[str]) -> str:
        """从终端读取人的决策输入"""
        hint = ""
        if options:
            hint = f"({'/'.join(options)}) "
        while True:
            try:
                raw = input(f"  >>> {hint}").strip()
                if not raw:
                    print("  请输入决策，不能为空")
                    continue
                if options:
                    # 模糊匹配选项
                    matched = [o for o in options if o in raw or raw in o]
                    if matched:
                        return matched[0]
                    print(f"  请从以下选项中选择：{' / '.join(options)}")
                    continue
                return raw
            except (EOFError, KeyboardInterrupt):
                print("\n  ⚠️  输入中断，未记录为业务决策。请改用 dialog checkpoint 或显式输入决策。")
                raise RuntimeError("Human Decision 输入中断：未收到明确人工决策")

    def error(self, step_name: str, error_msg: str, input_summary: str = ""):
        """记录一个错误节点，并检查熔断条件（连续失败超过 max_failures 则强制退出）"""
        step = WorkflowStep(
            run_id=self.run_id,
            step_name=step_name,
            step_type=StepType.ERROR,
            input_summary=input_summary,
            candidate_name=self.candidate_name,
            candidate_record_id=getattr(self, "candidate_record_id", ""),
        )
        step.finish(output_summary=error_msg, status=StepStatus.FAILED)
        self.steps.append(step)
        self._print_step(step)
        self._write_log_to_lark(step)

        # 熔断：连续失败计数
        self._failure_count += 1
        if self._failure_count >= self.max_failures:
            msg = (
                f"\n{'='*60}\n"
                f"  🛑 熔断触发：连续失败 {self._failure_count} 次，已达上限 {self.max_failures}\n"
                f"  Run ID: {self.run_id}\n"
                f"  最后失败步骤：{step_name}\n"
                f"  错误信息：{error_msg}\n"
                f"{'='*60}"
            )
            if not self.silent:
                print(msg)
            raise RuntimeError(
                f"WorkflowEngine 熔断：连续失败 {self._failure_count} 次（上限 {self.max_failures}）"
                f"，最后失败步骤：{step_name}，原因：{error_msg}"
            )

        return step

    def reset_failure_count(self):
        """手动重置失败计数（步骤成功后调用，或人工干预后恢复）"""
        self._failure_count = 0

    def summary(self) -> dict:
        """返回本次工作流的执行摘要"""
        total   = len(self.steps)
        done    = sum(1 for s in self.steps if s.status == StepStatus.DONE)
        decided = sum(1 for s in self.steps if s.status == StepStatus.DECIDED)
        failed  = sum(1 for s in self.steps if s.status == StepStatus.FAILED)

        if not self.silent:
            print(f"\n{'─'*60}")
            print(f"  工作流完成 · Run ID: {self.run_id}")
            print(f"  步骤总计: {total}  完成: {done}  决策: {decided}  失败: {failed}")
            print(f"{'─'*60}\n")

        return {
            "run_id":   self.run_id,
            "total":    total,
            "done":     done,
            "decided":  decided,
            "failed":   failed,
            "steps":    [
                {
                    "name":   s.step_name,
                    "type":   s.step_type,
                    "status": s.status,
                    "input":  s.input_summary,
                    "output": s.output_summary,
                }
                for s in self.steps
            ],
        }


class StepContext:
    """
    WorkflowEngine.step() 返回的上下文管理器

    with engine.step("调用评分引擎", input="候选人数据") as s:
        result = score()
        s.finish(output=str(result))
    """

    def __init__(self, engine: WorkflowEngine, step_name: str, input_summary: str):
        self.engine  = engine
        self._step   = WorkflowStep(
            run_id=engine.run_id,
            step_name=step_name,
            step_type=StepType.ACTION,
            input_summary=input_summary,
            candidate_name=engine.candidate_name,
            candidate_record_id=getattr(engine, "candidate_record_id", ""),
        )
        # 进入时打印 running 状态
        if not engine.silent:
            icon = ICONS.get(StepType.ACTION, "▶")
            print(f"  {icon} {step_name} 🔄")
            if input_summary:
                print(f"    ← 输入：{input_summary}")

    def finish(self, output: str = "", status: str = StepStatus.DONE):
        self._step.finish(output_summary=output, status=status)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._step.finish(
                output_summary=f"异常: {exc_val}",
                status=StepStatus.FAILED,
            )
            self._step.step_type = StepType.ERROR
        elif self._step.status == StepStatus.RUNNING:
            # 没有手动 finish，默认标 done
            self._step.finish(status=StepStatus.DONE)

        self.engine.steps.append(self._step)

        if not self.engine.silent:
            elapsed = self._step.elapsed()
            s_icon  = STATUS_ICONS.get(self._step.status, "")
            print(f"    → 输出：{self._step.output_summary}  {s_icon} [{elapsed}]")

        # 成功步骤重置失败计数（偶发错误不被误判为死循环）
        if self._step.status == StepStatus.DONE:
            self.engine._failure_count = 0

        self.engine._write_log_to_lark(self._step)
        return False  # 不吞异常


# ── 独立运行：自检 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("WorkflowEngine 自检（不写飞书）\n")

    engine = WorkflowEngine(
        candidate_name="测试候选人",
        write_lark=False,
    )

    engine.trace("读取简历", input_summary="test.pdf", output_summary="文本提取成功，4 页")

    with engine.step("调用评分引擎", input_summary="语言对 EN→ZH，经验 3 年") as s:
        time.sleep(0.3)  # 模拟耗时
        s.finish(output="总分 82，初始评级 B+")

    with engine.step("生成 AI 建议", input_summary="评分结果") as s:
        time.sleep(0.2)
        s.finish(output="建议进入测试环节，游戏经验较丰富")

    engine.trace("写回飞书", input_summary="<record_id>", output_summary="✅ 写入成功")

    engine.summary()
    print("✅ 自检通过")
