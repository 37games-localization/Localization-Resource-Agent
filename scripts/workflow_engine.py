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

飞书日志表字段（流程日志 tblVQvjpJw9CO0kU）：
  run_id / step_name / step_type / input_summary / output_summary /
  status / decision / created_at / candidate_name
"""

import json
import uuid
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any
import sys

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark

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
            "step_name":       self.step_name,
            "step_type":       self.step_type,
            "input_summary":   self.input_summary[:500],   # 飞书文本长度限制
            "output_summary":  self.output_summary[:500],
            "status":          self.status,
            "decision":        self.decision,
            "candidate_name":  self.candidate_name,
            "created_at":      int(datetime.fromisoformat(self.created_at).timestamp() * 1000),
        }


class WorkflowEngine:
    """
    工作流执行引擎

    用法：
        engine = WorkflowEngine(candidate_name="青木遥")
        with engine.step("分析简历", input="青木遥 PDF") as s:
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
        silent: bool = False,
        write_lark: bool = True,
    ):
        self.candidate_name = candidate_name
        self.run_id         = run_id or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:6]}"
        self.silent         = silent        # True = 不打印终端输出
        self.write_lark     = write_lark    # True = 写飞书日志表
        self.steps: list[WorkflowStep] = []
        self._pending_checkpoint: Optional[WorkflowStep] = None

        # 加载飞书配置
        try:
            cfg = load_config()
            lark = get_lark(cfg)
            self._lark_base   = lark.get("base_token", "")
            self._lark_log_tbl= lark.get("log_table_id", "tblVQvjpJw9CO0kU")
        except Exception:
            self._lark_base   = ""
            self._lark_log_tbl= "tblVQvjpJw9CO0kU"

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

    def _write_log_to_lark(self, step: WorkflowStep):
        """把步骤写入飞书流程日志表，失败不中断流程"""
        if not self.write_lark or not self._lark_base:
            return
        try:
            record = step.to_lark_record()
            cmd = [
                "lark-cli", "base", "+record-create",
                "--base-token", self._lark_base,
                "--table-id",   self._lark_log_tbl,
                "--fields",     json.dumps(record, ensure_ascii=False),
                "--format",     "json",
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception:
            pass  # 日志写失败不影响主流程

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
    ) -> str:
        """
        Human Decision 节点：打印上下文，等待人输入决策。

        参数：
            node      : 节点名称，如"初筛结果确认"
            context   : 当前上下文数据，dict，用于展示给人看
            prompt    : 提示语，告诉人需要做什么决策
            options   : 可选项列表，如 ["通过", "拒绝", "补充"]
            handler   : 可选的决策后处理函数，接收 decision str

        返回：人输入的决策字符串
        """
        step = WorkflowStep(
            run_id=self.run_id,
            step_name=node,
            step_type=StepType.CHECKPOINT,
            input_summary=json.dumps(context or {}, ensure_ascii=False)[:300],
            candidate_name=self.candidate_name,
        )
        step.status = StepStatus.WAITING
        self.steps.append(step)
        self._pending_checkpoint = step

        # ── 打印暂停信息 ──
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

        self._write_log_to_lark(step)

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
                print("\n  ⚠️  输入中断，记录为「跳过」")
                return "跳过"

    def error(self, step_name: str, error_msg: str, input_summary: str = ""):
        """记录一个错误节点"""
        step = WorkflowStep(
            run_id=self.run_id,
            step_name=step_name,
            step_type=StepType.ERROR,
            input_summary=input_summary,
            candidate_name=self.candidate_name,
        )
        step.finish(output_summary=error_msg, status=StepStatus.FAILED)
        self.steps.append(step)
        self._print_step(step)
        self._write_log_to_lark(step)
        return step

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

    engine.trace("写回飞书", input_summary="recABC123", output_summary="✅ 写入成功")

    engine.summary()
    print("✅ 自检通过")
