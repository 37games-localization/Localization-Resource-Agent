"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import {
  eventSummary,
  inferAttachmentPaths,
  stringifyPayload
} from "@/components/resource-agent/agent-console-utils";
import type { AgentRunEvent, AgentRunRequest } from "@/lib/agent-runner";
import {
  fetchCandidateResources,
  fetchLarkConfig,
  fetchWorkflowTraces,
  runSchemaCheckpoint,
  type LarkConfigPayload,
  type SchemaCheckpointPayload,
  type WorkflowTraceEntry
} from "@/lib/resource-agent-api";

type CandidateStatus = "waiting" | "done" | "running" | "alert";

type Candidate = {
  id: string;
  recordId: string;
  name: string;
  languagePair: string;
  service: string;
  status: CandidateStatus;
  rating: string;
  confidence: number;
  lastRun: string;
  source: string;
  wordCount: string;
  currentNode: string;
  ruleHit: string;
  risk: string;
  score: string;
  priceScore: string;
  qualificationScore: string;
  aiSuggestion: string;
  comment: string;
  confidenceReason: string;
  nextStep: string;
  hasScore: boolean;
};

type ChatMessage = {
  id: string;
  role: "vm" | "agent";
  text: string;
};

type LarkCandidateResource = {
  recordId: string;
  supplierId?: string;
  name?: string;
  nickname?: string;
  email?: string;
  languagePair?: string;
  services?: string;
  tier?: string;
  score?: string;
  priceScore?: string;
  qualificationScore?: string;
  status?: string;
  aiSuggestion?: string;
  validResume?: string;
  scoreBasis?: string;
  priceScoreBasis?: string;
  qualificationScoreBasis?: string;
  comment?: string;
  parsedWordCount?: string;
  parsedYears?: string;
  parsedProjectCount?: string;
  parsedKnownEntities?: string;
  location?: string;
  priceNegotiation?: string;
  badcaseFlag?: string;
  expectedResult?: string;
  vmNote?: string;
};

type CheckpointMode = "pending" | "confirmed" | "editing" | "badcaseRecorded";
type ActiveTab = "overview" | "config";
type RunMode = NonNullable<AgentRunRequest["mode"]>;

function statusFromLark(status: string, badcaseFlag: string): CandidateStatus {
  if (badcaseFlag.includes("⚠️")) return "alert";
  if (/不通过|失败|失联/.test(status)) return "alert";
  if (/通过|完成|合同已发送/.test(status)) return "done";
  if (/测试中|签约中|财务/.test(status)) return "running";
  return "waiting";
}

function statusToNode(status: string, hasScore: boolean) {
  if (/测试中/.test(status)) return "test_email.sent";
  if (/测试通过|合同已发送|签约/.test(status)) return "contract.ready";
  if (/不通过/.test(status)) return "rejection.ready";
  if (/初筛中/.test(status)) return hasScore ? "checkpoint.waiting_confirmation" : "resume.waiting_evaluation";
  if (/新投递|待筛选|待解析/.test(status)) return "resume.waiting_evaluation";
  return status || "candidate.located";
}

function nextStepFromStatus(status: string, badcaseFlag: string) {
  if (badcaseFlag.includes("⚠️")) return "Badcase 归因";
  if (/测试通过/.test(status)) return "准备合同";
  if (/初筛通过/.test(status)) return "发送测试题";
  if (/初筛中/.test(status)) return "确认初筛结论";
  if (/不通过/.test(status)) return "发送婉拒邮件";
  if (/测试中/.test(status)) return "等待测试结果";
  return "人工确认";
}

function formatNumberText(value: string, suffix = "") {
  const num = Number(value);
  if (!Number.isFinite(num)) return value || "未写入";
  return `${num.toLocaleString("en-US")}${suffix}`;
}

function formatUsageNumber(value: unknown) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0";
  return num.toLocaleString("en-US");
}

function formatCurrency(value: unknown, prefix: string) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "未配置";
  return `${prefix}${num.toLocaleString("en-US", { maximumFractionDigits: prefix === "$" ? 6 : 4 })}`;
}

function scoreToConfidence(score: string) {
  const num = Number(score);
  if (!Number.isFinite(num)) return 62;
  if (num >= 90) return 96;
  if (num >= 80) return 86;
  if (num >= 70) return 76;
  if (num >= 60) return 68;
  return 52;
}

function hasScoreFields(resource: LarkCandidateResource) {
  return Boolean(resource.score || resource.priceScore || resource.qualificationScore || resource.tier || resource.aiSuggestion);
}

function toVisualCandidate(resource: LarkCandidateResource): Candidate {
  const supplierId = resource.supplierId || resource.recordId;
  const status = resource.status || "初筛中";
  const scored = hasScoreFields(resource);
  const wordCount = formatNumberText(resource.parsedWordCount || "", " 字");
  const priceBasis = scored ? resource.priceScoreBasis || "报价规则待确认" : "等待解析后生成";
  const qualificationBasis = scored ? resource.qualificationScoreBasis || resource.scoreBasis || "资历规则待确认" : "等待解析后生成";
  const badcaseRisk = resource.badcaseFlag
    ? `${resource.badcaseFlag}${resource.expectedResult ? `：${resource.expectedResult}` : ""}`
    : "";

  return {
    id: supplierId,
    recordId: resource.recordId,
    name: resource.name || resource.nickname || supplierId,
    languagePair: resource.languagePair || "语言对未写入",
    service: resource.services || "服务类型未写入",
    status: statusFromLark(status, resource.badcaseFlag || ""),
    rating: resource.tier || "-",
    confidence: scored ? scoreToConfidence(resource.score || "") : 0,
    lastRun: "Lark 当前状态",
    source: "Lark 候选人表",
    wordCount: scored ? wordCount : "待解析",
    currentNode: statusToNode(status, scored),
    ruleHit: `${priceBasis} / ${qualificationBasis}`,
    risk: badcaseRisk || (resource.validResume === "否" ? "有效简历=否，建议人工复核" : "无高风险告警"),
    score: resource.score || "-",
    priceScore: resource.priceScore || "-",
    qualificationScore: resource.qualificationScore || "-",
    aiSuggestion: resource.aiSuggestion || "等待 Agent 生成建议",
    comment: resource.comment || resource.scoreBasis || "等待 Agent 解析简历后生成点评。",
    confidenceReason: scored && resource.parsedWordCount
      ? `字数来源：Lark 解析字数 ${wordCount}`
      : "字数来源缺失，建议人工确认",
    nextStep: scored ? nextStepFromStatus(status, resource.badcaseFlag || "") : "运行简历评估",
    hasScore: scored
  };
}

const statusLabel: Record<CandidateStatus, string> = {
  waiting: "Lark待处理",
  done: "Lark已完成",
  running: "Lark处理中",
  alert: "Lark风险"
};

const runModeCopy: Record<RunMode, { label: string; note: string; tone: "safe" | "dry" | "prod" }> = {
  dry_run: {
    label: "DRY-RUN",
    note: "调用真实脚本并展示事件流；脚本参数含 dry-run 时不会写回 Lark。",
    tone: "dry"
  },
  test_mode: {
    label: "TEST MODE",
    note: "保留测试收件人/测试路径语义；仍需从事件里确认是否写回。",
    tone: "safe"
  },
  production: {
    label: "PRODUCTION",
    note: "允许真实写回入口显示；只有事件流证明非 dry-run 时才开放确认。",
    tone: "prod"
  }
};

export default function AgentVisualPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [runMode, setRunMode] = useState<RunMode>("dry_run");
  const [selectedId, setSelectedId] = useState("");
  const [checkpointMode, setCheckpointMode] = useState<CheckpointMode>("pending");
  const [reviewRating, setReviewRating] = useState("A");
  const [reviewSuggestion, setReviewSuggestion] = useState("人工复核");
  const [reviewReason, setReviewReason] = useState("");
  const [toast, setToast] = useState("");
  const [dataSource, setDataSource] = useState("正在读取 Lark");
  const [config, setConfig] = useState<LarkConfigPayload | null>(null);
  const [configSource, setConfigSource] = useState("正在读取配置");
  const [workflowTraces, setWorkflowTraces] = useState<WorkflowTraceEntry[]>([]);
  const [traceSource, setTraceSource] = useState("尚未读取 trace");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [isCheckpointWriting, setIsCheckpointWriting] = useState(false);
  const [runEvents, setRunEvents] = useState<AgentRunEvent[]>([]);
  const [isRunningAgent, setIsRunningAgent] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const selected = candidates.find((candidate) => candidate.id === selectedId) ?? candidates[0] ?? null;
  const waitingCount = candidates.filter((candidate) => candidate.status === "waiting").length;
  const alertCount = candidates.filter((candidate) => candidate.status === "alert").length;
  const doneCount = candidates.filter((candidate) => candidate.status === "done").length;
  const latestRunCheckpoint = [...runEvents].reverse().find((event) => event.event_type === "checkpoint");
  const latestUsageReport = [...runEvents].reverse().find((event) => event.event_type === "usage_report");
  const latestUsage = latestUsageReport?.payload;
  const latestCheckpointSummary = latestRunCheckpoint?.payload.summary as Record<string, unknown> | undefined;
  const latestRunStarted = runEvents.find((event) => event.event_type === "run_started");
  const latestStepInput = [...runEvents].reverse().find((event) => event.event_type === "step_input");
  const latestRunMode =
    (latestRunStarted?.payload.execution_mode as RunMode | undefined) ??
    (latestRunStarted?.payload.mode as RunMode | undefined) ??
    runMode;
  const latestRunHasDryRunFlag = runEvents.some((event) => {
    if (event.payload.dry_run === true) return true;
    if (event.payload.note && String(event.payload.note).toLowerCase().includes("dry-run")) return true;
    if (event.payload.safety && String(event.payload.safety).toLowerCase().includes("dry-run")) return true;
    if (Array.isArray(event.payload.args) && event.payload.args.some((arg) => String(arg).includes("dry-run"))) return true;
    return stringifyPayload(event.payload).toLowerCase().includes("[dry-run]");
  });
  const latestRunWritebackState = latestRunCheckpoint
    ? latestRunHasDryRunFlag
      ? "dry-run，事件流显示未写回"
      : latestRunMode === "production"
        ? "production，可进入真实写回确认"
        : "非 production，保持只读/预览"
    : "尚无 checkpoint";
  const latestCheckpointKind = latestCheckpointSummary
    ? "total_score" in latestCheckpointSummary || "final_tier" in latestCheckpointSummary
      ? "resume"
      : "subject" in latestCheckpointSummary || "attachment" in latestCheckpointSummary
        ? "test-email"
        : "selected_template" in latestCheckpointSummary || "filled_variables" in latestCheckpointSummary
          ? "contract"
          : "generic"
    : undefined;
  const kpis = [
    ["Lark 候选人记录", String(candidates.length), "blue"],
    ["已写回评分", String(candidates.filter((candidate) => candidate.hasScore).length), "green"],
    ["等待人工确认", String(waitingCount), "amber"],
    ["Badcase / 风险", String(alertCount), "orange"],
    ["Lark 已完成", String(doneCount), "green"],
    ["Lark 处理中", String(candidates.filter((candidate) => candidate.status === "running").length), "purple"]
  ];
  const canConfirmAdvance =
    Boolean(latestRunCheckpoint) &&
    latestCheckpointKind === "resume" &&
    latestRunMode === "production" &&
    !latestRunHasDryRunFlag &&
    !isCheckpointWriting;
  const confirmDisabledReason = !latestRunCheckpoint
    ? "请先运行并生成 checkpoint"
    : latestCheckpointKind !== "resume"
      ? "当前 checkpoint 不是简历评估写回"
      : latestRunMode !== "production"
        ? "当前运行模式不是 production"
        : latestRunHasDryRunFlag
          ? "事件流显示本次为 dry-run/未写回"
          : "";
  const canEditReview = canConfirmAdvance && checkpointMode !== "confirmed";
  const usageTotalTokens = formatUsageNumber(latestUsage?.total_tokens);
  const usageInputTokens = formatUsageNumber(latestUsage?.input_tokens);
  const usageOutputTokens = formatUsageNumber(latestUsage?.output_tokens);
  const usageCostCny = formatCurrency(latestUsage?.cost_cny, "¥");
  const usageCostUsd = formatCurrency(latestUsage?.cost_usd, "$");
  const usageSource = typeof latestUsage?.usage_source === "string" ? latestUsage.usage_source : "尚未运行";
  const usagePricingStatus = typeof latestUsage?.pricing_status === "string" ? latestUsage.pricing_status : "pending";
  const usageNote = typeof latestUsage?.note === "string" ? latestUsage.note : "运行 Agent 后会展示本次 AI token 和成本口径。";

  async function refreshCandidates() {
    const resources = await fetchCandidateResources();
    const mapped = (resources as LarkCandidateResource[]).map(toVisualCandidate);
    setCandidates(mapped);
    setDataSource("Lark 实时读取");
    return mapped;
  }

  async function refreshWorkflowTraces(candidate: Candidate) {
    setTraceSource("正在读取 workflow_log");
    const traces = await fetchWorkflowTraces({
      candidateRecordId: candidate.recordId,
      candidateName: candidate.name
    });
    setWorkflowTraces(traces);
    setTraceSource(traces.length > 0 ? "workflow_log 实时读取" : "暂无 workflow_log");
    return traces;
  }

  useEffect(() => {
    let cancelled = false;
    refreshCandidates()
      .then((mapped) => {
        if (cancelled || mapped.length === 0) return;
        setCandidates(mapped);
        setSelectedId(mapped[0]?.id ?? "");
      })
      .catch((error) => {
        setDataSource(`Lark 读取失败：${error instanceof Error ? error.message : "未知错误"}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    refreshWorkflowTraces(selected)
      .then((traces) => {
        if (cancelled) return;
      })
      .catch((error) => {
        if (cancelled) return;
        setWorkflowTraces([]);
        setTraceSource(`trace 读取失败：${error instanceof Error ? error.message : "未知错误"}`);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  useEffect(() => {
    let cancelled = false;
    fetchLarkConfig()
      .then((payload) => {
        if (cancelled) return;
        setConfig(payload);
        setConfigSource("配置已读取");
      })
      .catch((error) => {
        setConfigSource(`配置读取失败：${error instanceof Error ? error.message : "未知错误"}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    const scrollToBottom = () => {
      el.scrollTop = el.scrollHeight;
    };
    requestAnimationFrame(scrollToBottom);
    const timer = window.setTimeout(scrollToBottom, 80);
    return () => window.clearTimeout(timer);
  }, [chatMessages.length, selectedId, checkpointMode]);

  function handleCandidateClick(id: string) {
    setSelectedId((current) => (current === id ? "" : id));
    setCheckpointMode("pending");
    setReviewReason("");
    setRunEvents([]);
  }

  function handleToast(action: string) {
    setToast(action);
    window.setTimeout(() => setToast(""), 2400);
  }

  function appendChat(role: ChatMessage["role"], text: string) {
    setChatMessages((current) => [
      ...current,
      {
        id: `${Date.now()}-${role}-${current.length}`,
        role,
        text
      }
    ]);
  }

  function findCandidateFromText(text: string) {
    const normalized = text.trim().toLowerCase();
    return candidates.find((candidate) => {
      const keys = [candidate.name, candidate.id, candidate.recordId]
        .filter(Boolean)
        .map((value) => value.toLowerCase());
      return keys.some((key) => normalized.includes(key));
    });
  }

  function summarizeCandidate(candidate: Candidate) {
    if (candidate.hasScore) {
      return `已定位 ${candidate.name}（${candidate.id}）。Lark 当前已有评分：总分 ${candidate.score}/100，评级 ${candidate.rating}，AI 建议：${candidate.aiSuggestion}。如需推进，请先运行本轮简历评估并在 checkpoint 中确认。`;
    }
    return `已定位 ${candidate.name}（${candidate.id}）。当前 Lark 尚未写入评分结果，下一步是简历评估节点：下载简历附件、解析信息、计算评分并写回 Lark。评分结果写回后，工作台会进入人工确认。`;
  }

  function workflowLocator(text: string, candidate?: Candidate): AgentRunRequest["candidateLocator"] {
    if (!candidate) return undefined;
    if (/合同|签字|核查|检查/.test(text)) {
      return { type: "name", value: candidate.name };
    }
    return { type: "record_id", value: candidate.recordId };
  }

  async function runAgentCommand(text: string, candidate?: Candidate) {
    if (isRunningAgent) return;
    setRunEvents([]);
    setIsRunningAgent(true);
    appendChat("agent", candidate
      ? `收到。已定位 ${candidate.name}（${candidate.id}），现在调用现有 Agent 脚本执行。`
      : "收到。现在调用现有 Agent 脚本执行。"
    );

    const requestBody: AgentRunRequest = {
      message: text,
      candidateLocator: workflowLocator(text, candidate),
      attachments: inferAttachmentPaths(text),
      mode: runMode
    };

    try {
      const response = await fetch("/api/agent-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody)
      });
      if (!response.ok || !response.body) {
        throw new Error(`后端执行入口返回异常：${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line) as AgentRunEvent;
          setRunEvents((items) => [...items, event]);
          if (event.event_type === "checkpoint") {
            appendChat("agent", String(event.payload.title ?? "需要人工确认"));
          }
          if (event.event_type === "step_failed") {
            appendChat("agent", `执行失败：${stringifyPayload(event.payload)}`);
          }
        }
      }
    } catch (error) {
      appendChat("agent", `前端请求失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setIsRunningAgent(false);
    }
  }

  async function runCommand(command: string) {
    const text = command.trim();
    if (!text) return;
    appendChat("vm", text);

    if (/所有|全部|批量/.test(text) && /未解析|没解析|未评分|待解析|还没解析/.test(text)) {
      const pending = candidates.filter((candidate) => !candidate.hasScore);
      if (pending.length === 0) {
        appendChat("agent", "当前 Lark 候选人表没有待解析简历。");
        return;
      }
      appendChat(
        "agent",
        `当前共有 ${pending.length} 份简历尚未写入评分结果：${pending
          .map((candidate) => `${candidate.name}（${candidate.id}）`)
          .join("、")}。你可以选择单个候选人继续处理。`
      );
      return;
    }

    if (/发测试题|准备合同|生成合同|检查签字合同|签字合同|修改结果/.test(text)) {
      const matched = findCandidateFromText(text) || selected;
      if (matched) setSelectedId(matched.id);
      if (!matched) {
        appendChat("agent", "该节点需要先定位候选人。请在指令里带上候选人姓名、编号或 record_id。");
        return;
      }
      await runAgentCommand(text, matched);
      return;
    }

    const matched = findCandidateFromText(text) || selected;
    if (matched && /看|查|简历|处理|评估/.test(text)) {
      setSelectedId(matched.id);
      await runAgentCommand(text, matched);
      return;
    }

    appendChat("agent", "无法识别要执行的资源管理动作。请明确说明：看简历/评估、发测试题、准备合同、检查签字合同，或查看待解析简历。");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = chatInput;
    setChatInput("");
    void runCommand(text);
  }

  async function uploadAttachment(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch("/api/uploads", {
        method: "POST",
        body: formData
      });
      const data = (await response.json()) as { ok: boolean; path?: string; filename?: string; error?: string };
      if (!response.ok || !data.ok || !data.path) {
        throw new Error(data.error || "附件上传失败");
      }
      setChatInput((current) => `${current}${current ? " " : ""}${data.path}`);
      appendChat("agent", `附件已上传：${data.filename ?? file.name}。发送指令时会带上本地路径。`);
    } catch (error) {
      appendChat("agent", `附件上传失败：${error instanceof Error ? error.message : "未知错误"}`);
    }
  }

  async function writeCheckpoint(payload: Record<string, unknown>) {
    if (!selected) throw new Error("请先选择候选人");
    const response = await fetch("/api/lark/candidate-checkpoint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recordId: selected.recordId, ...payload })
    });
    const result = (await response.json()) as { ok: boolean; error?: string };
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Lark 写回失败");
    }
  }

  async function confirmAdvance() {
    if (!canConfirmAdvance) {
      const message = `确认推进已禁用：${confirmDisabledReason || "当前执行未闭环"}。`;
      appendChat("agent", message);
      handleToast(message);
      return;
    }
    if (latestRunCheckpoint && latestCheckpointKind !== "resume") {
      const message = "当前确认点不是简历评估结果，前端暂未接入该节点的确认写回。为避免误推进状态，请先在命令行或 Lark 中按原流程确认。";
      appendChat("agent", message);
      handleToast("该确认点暂未接写回");
      return;
    }
    if (!latestRunCheckpoint || latestCheckpointKind !== "resume") {
      const message = "请先运行本轮简历评估，并在生成的简历评估 checkpoint 中确认推进。";
      appendChat("agent", message);
      handleToast(message);
      return;
    }
    if (isCheckpointWriting) return;
    setIsCheckpointWriting(true);
    try {
      await writeCheckpoint({
        action: "confirm",
        checkpointSummary: latestCheckpointSummary,
        checkpointKind: latestCheckpointKind,
        runId: latestRunCheckpoint.run_id,
        candidateName: selected.name,
        mode: latestRunMode
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Lark 写回失败";
      appendChat("agent", `确认推进失败：${message}`);
      handleToast(message);
      setIsCheckpointWriting(false);
      return;
    }
    setCandidates((current) =>
      current.map((candidate) =>
        candidate.id === selected.id
          ? {
              ...candidate,
              status: "running",
              currentNode: "test_email.ready",
              nextStep: "发送测试题",
              hasScore: true,
              score: String(latestCheckpointSummary?.total_score ?? candidate.score),
              rating: String(latestCheckpointSummary?.final_tier ?? candidate.rating),
              aiSuggestion: String(latestCheckpointSummary?.ai_suggestion ?? candidate.aiSuggestion)
            }
          : candidate
      )
    );
    setCheckpointMode("confirmed");
    appendChat("agent", `已确认 ${selected.name} 的评分结果，并将招募状态推进到初筛通过。`);
    handleToast("评分结果已确认，状态已推进");
    await refreshCandidates();
    await refreshWorkflowTraces(selected);
    setIsCheckpointWriting(false);
  }

  async function submitReview() {
    if (latestCheckpointKind !== "resume") {
      handleToast("请先运行本轮简历评估");
      return;
    }
    if (!canEditReview) {
      handleToast(confirmDisabledReason || "当前执行未闭环，不能提交真实写回");
      return;
    }
    if (!reviewReason.trim()) {
      handleToast("请填写调整原因");
      return;
    }
    try {
      await writeCheckpoint({
        action: "modify",
        rating: reviewRating,
        aiSuggestion: reviewSuggestion,
        reason: reviewReason,
        checkpointKind: latestCheckpointKind,
        runId: latestRunCheckpoint?.run_id,
        candidateName: selected.name,
        mode: latestRunMode
      });
    } catch (error) {
      handleToast(error instanceof Error ? error.message : "Lark 写回失败");
      return;
    }
    setCandidates((current) =>
      current.map((candidate) =>
        candidate.id === selected.id
          ? {
              ...candidate,
              rating: reviewRating,
              aiSuggestion: reviewSuggestion,
              status: "alert",
              risk: `人工调整：${reviewReason}`,
              currentNode: "badcase.recorded",
              nextStep: "Badcase 归因",
              hasScore: true
            }
          : candidate
      )
    );
    setCheckpointMode("badcaseRecorded");
    handleToast("已记录人工修改并生成 Badcase");
  }

  if (!selected && activeTab === "overview") {
    return (
      <main className="agent-visual">
        <header className="visual-nav">
          <div className="visual-brand-mark">RA</div>
          <strong>Resource Agent Console</strong>
          <ModePill mode={runMode} isRunning={isRunningAgent} />
          <Nav activeTab={activeTab} onChange={setActiveTab} />
          <div className="visual-agent-state">
            <span />
            Agent · {isRunningAgent ? "Running" : "Idle"}
          </div>
        </header>
        <section className="visual-empty-state">
          <strong>{dataSource === "正在读取 Lark" ? "正在读取 Lark 候选人表" : "暂无候选人记录"}</strong>
          <p>{dataSource}</p>
        </section>
      </main>
    );
  }

  if (!selected && activeTab === "config") {
    return (
      <main className="agent-visual">
        <header className="visual-nav">
          <div className="visual-brand-mark">RA</div>
          <strong>Resource Agent Console</strong>
          <ModePill mode={runMode} isRunning={isRunningAgent} />
          <Nav activeTab={activeTab} onChange={setActiveTab} />
          <div className="visual-agent-state">
            <span />
            Agent · {isRunningAgent ? "Running" : "Idle"}
          </div>
        </header>
        <ConfigView config={config} configSource={configSource} />
      </main>
    );
  }

  return (
    <main className="agent-visual">
      <header className="visual-nav">
        <div className="visual-brand-mark">RA</div>
        <strong>Resource Agent Console</strong>
        <ModePill mode={runMode} isRunning={isRunningAgent} />
          <Nav activeTab={activeTab} onChange={setActiveTab} />
        <ModeSwitch mode={runMode} onChange={setRunMode} disabled={isRunningAgent} />
        <div className="visual-agent-state">
          <span />
          Agent · {isRunningAgent ? "Running" : "Idle"}
        </div>
      </header>

      {activeTab === "overview" ? (
        <>
        <section className="visual-kpi-row">
          <article className={`visual-kpi visual-mode-card visual-mode-${runModeCopy[runMode].tone}`}>
            <span>当前运行模式</span>
            <strong>{runModeCopy[runMode].label}</strong>
            <p>{runModeCopy[runMode].note}</p>
          </article>
          {kpis.map(([label, value, tone]) => (
            <article className={`visual-kpi visual-tone-${tone}`} key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </article>
          ))}
        </section>

        <section className="visual-workspace">
        <aside className="visual-candidates">
          <div className="visual-panel-title">
            <span>候选人资源列表</span>
            <strong>{dataSource === "Lark 实时读取" ? "Lark" : candidates.length}</strong>
          </div>
          <div className="visual-candidate-stack">
            {candidates.map((candidate) => {
              const isSelected = selectedId === candidate.id;
              return (
                <article className={`visual-candidate-card ${isSelected ? "selected" : ""}`} key={candidate.id}>
                  <button className="candidate-card-head" onClick={() => handleCandidateClick(candidate.id)} type="button">
                    <div className="candidate-main">
                      <strong>{candidate.name}</strong>
                      <span>{candidate.id}</span>
                    </div>
                    <div className="candidate-badges">
                      <span className={`status status-${candidate.status}`}>{statusLabel[candidate.status]}</span>
                      <span className="rating">{candidate.rating}</span>
                      <span className="confidence">{candidate.confidence}%</span>
                      <span className="chevron">{isSelected ? "-" : "+"}</span>
                    </div>
                    <div className="candidate-subline">
                      <span title={candidate.languagePair}>{candidate.languagePair}</span>
                      <span title={candidate.service}>{candidate.service}</span>
                      <span>{candidate.lastRun}</span>
                    </div>
                  </button>
                  {isSelected && (
                    <div className="candidate-detail">
                      <Info label="简历来源" value={candidate.source} />
                      <Info label="解析字数" value={candidate.wordCount} mono />
                      <Info label="当前节点" value={candidate.currentNode} mono accent />
                      <Info label="报价规则" value={candidate.ruleHit} />
                      <Info label="最近运行" value={candidate.lastRun} />
                      <Info label="风险提示" value={candidate.risk} warning={candidate.status === "alert"} />
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </aside>

        <section className="visual-chat">
          <div className="visual-chat-header">
            <div>
              <span>对话流 · Agent 执行</span>
              <strong>{selected.name} · {selected.id}</strong>
              <small>候选人状态来自 Lark 字段，不等同于本次 trace。</small>
            </div>
              <button
              disabled={!canEditReview}
              onClick={() => setCheckpointMode("editing")}
              title={canEditReview ? "进入真实写回修改" : confirmDisabledReason}
              type="button"
            >
              修改结果
            </button>
          </div>

          <div className="visual-chat-scroll" ref={chatScrollRef}>
            {chatMessages.length === 0 ? (
              <section className="visual-chat-empty">
                <strong>等待 VM 指令</strong>
                <p>可以输入「看一下所有还没解析的简历」或「看下候选人姓名的简历」。对话流只展示真实指令和 Lark 当前数据。</p>
              </section>
            ) : (
              chatMessages.map((message) => <ChatBubble key={message.id} role={message.role} text={message.text} />)
            )}

            {runEvents.length > 0 && (
              <div className="visual-trace-stack">
                {runEvents
                  .filter((event) => event.event_type !== "checkpoint")
                  .map((event) => (
                    <details className="visual-trace" key={event.event_id}>
                      <summary>
                        <span className={`trace-state trace-${event.event_type === "step_failed" ? "waiting" : "done"}`}>
                          {event.event_type === "step_failed" ? "ERR" : isRunningAgent ? "RUN" : "OK"}
                        </span>
                        <strong>{eventSummary(event)}</strong>
                        <span>{event.event_type}</span>
                        {event.payload.dry_run === true || stringifyPayload(event.payload).toLowerCase().includes("dry-run") ? (
                          <em>dry-run / 未写回</em>
                        ) : null}
                      </summary>
                      <p>{stringifyPayload(event.payload)}</p>
                    </details>
                  ))}
              </div>
            )}

            {(latestRunCheckpoint || checkpointMode !== "pending") && (
              <section className="visual-checkpoint">
                <div className="checkpoint-head">
                  <span>{checkpointMode === "editing" ? "CHECKPOINT · 修改结果" : "CHECKPOINT · 等待人工确认"}</span>
                  <strong>{checkpointMode === "confirmed" ? "CONFIRMED" : checkpointMode === "badcaseRecorded" ? "BADCASE" : "PENDING"}</strong>
                </div>
                <div className={`checkpoint-run-state ${canConfirmAdvance ? "ready" : "blocked"}`}>
                  <strong>{latestRunWritebackState}</strong>
                  <span>{canConfirmAdvance ? "真实写回入口已开放" : confirmDisabledReason || "等待 production 非 dry-run 事件"}</span>
                </div>
                <div className="checkpoint-grid">
                  <Info label="总分" value={String(latestCheckpointSummary?.total_score ?? "待生成")} mono accent />
                  <Info label="评级" value={String(latestCheckpointSummary?.final_tier ?? "待生成")} mono accent />
                  <Info label="AI 建议" value={String(latestCheckpointSummary?.ai_suggestion ?? "待生成")} accent />
                  <Info label="置信度" value={String(latestCheckpointSummary?.confidence ?? "待生成")} mono />
                  <Info label="置信度原因" value={selected.confidenceReason} />
                  <Info label="下一步建议" value={selected.nextStep} accent />
                </div>
                <div className="checkpoint-evidence">
                  {selected.comment}
                </div>
                {checkpointMode === "editing" ? (
                  <div className="checkpoint-edit-form">
                    <label>
                      调整评级
                      <select value={reviewRating} onChange={(event) => setReviewRating(event.target.value)}>
                        {["S", "A", "B", "C"].map((rating) => (
                          <option key={rating} value={rating}>{rating}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      调整建议
                      <select value={reviewSuggestion} onChange={(event) => setReviewSuggestion(event.target.value)}>
                        {["优先录用", "进入测试", "人工复核", "建议婉拒"].map((item) => (
                          <option key={item} value={item}>{item}</option>
                        ))}
                      </select>
                    </label>
                    <label className="checkpoint-reason">
                      调整原因
                      <textarea
                        value={reviewReason}
                        onChange={(event) => setReviewReason(event.target.value)}
                        placeholder="请填写为什么调整 Agent 结论，例如：简历未体现游戏项目，需人工复核。"
                      />
                    </label>
                    <div className="checkpoint-actions">
                      <button disabled={!canEditReview} onClick={submitReview} title={canEditReview ? "提交真实写回" : confirmDisabledReason} type="button">提交修改并记录 Badcase</button>
                      <button onClick={() => setCheckpointMode("pending")} type="button">取消</button>
                    </div>
                  </div>
                ) : (
                  <div className="checkpoint-actions">
                    <button disabled={!canConfirmAdvance} onClick={confirmAdvance} title={canConfirmAdvance ? "确认真实写回" : confirmDisabledReason} type="button">
                      {isCheckpointWriting ? "推进中" : "确认推进"}
                    </button>
                    <button disabled={!canEditReview} onClick={() => setCheckpointMode("editing")} title={canEditReview ? "进入真实写回修改" : confirmDisabledReason} type="button">修改结果</button>
                  </div>
                )}
              </section>
            )}
          </div>

          <div className="visual-chat-input">
          <div className="quick-actions">
              <button disabled={isRunningAgent} onClick={() => void runCommand("看一下所有还没解析的简历")} type="button">待解析简历</button>
              <button disabled={isRunningAgent} onClick={() => selected && void runCommand(`看下${selected.name}的简历`)} type="button">看当前简历</button>
              {["发测试题", "准备合同", "检查签字合同"].map((item) => (
                <button disabled={isRunningAgent} key={item} onClick={() => selected && void runCommand(`${item}：${selected.name}`)} type="button">{item}</button>
              ))}
              <button disabled={!canEditReview} onClick={() => setCheckpointMode("editing")} title={canEditReview ? "进入真实写回修改" : confirmDisabledReason} type="button">修改结果</button>
            </div>
            <form onSubmit={handleSubmit}>
              <button onClick={() => uploadInputRef.current?.click()} type="button">上传附件</button>
              <input
                accept=".xlsx,.pdf,.docx"
                hidden
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void uploadAttachment(file);
                  event.currentTarget.value = "";
                }}
                ref={uploadInputRef}
                type="file"
              />
              <input
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="告诉 Agent 要处理什么，例如：看一下所有还没解析的简历"
                value={chatInput}
              />
              <button disabled={isRunningAgent} type="submit">{isRunningAgent ? "执行中" : "发送"}</button>
            </form>
          </div>
        </section>

        <aside className="visual-execution">
          <div className="visual-panel-title">
            <span>Trace 观测</span>
            <strong>RUN</strong>
          </div>
          <MetricGroup
            title="动作边界"
            items={[
              ["只读查询", "候选人列表 / 配置 / workflow_log"],
              ["dry-run执行", "Agent 脚本事件流"],
              ["真实写回", canConfirmAdvance ? "已开放确认" : "已禁用"]
            ]}
          />
          <MetricGroup
            title="Trace 来源"
            items={[
              ["状态", traceSource],
              ["日志数", String(workflowTraces.length)],
              ["数据源", "Lark workflow_log"],
              ["本次运行", latestStepInput ? latestRunWritebackState : "尚未执行"]
            ]}
          />
          <section className="execution-section">
            <h3>AI 成本</h3>
            <div className="token-grid">
              <div>
                <span>总 TOKEN</span>
                <strong>{usageTotalTokens}</strong>
              </div>
              <div>
                <span>估算成本</span>
                <strong>{usageCostCny}</strong>
              </div>
              <div>
                <span>输入 TOKEN</span>
                <strong>{usageInputTokens}</strong>
              </div>
              <div>
                <span>输出 TOKEN</span>
                <strong>{usageOutputTokens}</strong>
              </div>
            </div>
            <div className="token-bar">
              <span
                style={{
                  width: `${Math.min(100, Math.max(4, Number(latestUsage?.total_tokens ?? 0) / 80))}%`
                }}
              />
            </div>
            <p className="usage-note">
              {usageSource} · {usagePricingStatus} · {usageCostUsd}
            </p>
            <p className="usage-note">{usageNote}</p>
          </section>
          <MetricGroup title="当前记录" items={[["record_id", selected.recordId], ["供应商编号", selected.id], ["Lark状态节点", selected.currentNode], ["风险提示", selected.risk]]} />
          <MetricGroup title="最近写回字段" items={[["rating", selected.rating], ["score", selected.score], ["aiSuggestion", selected.aiSuggestion], ["confidence", `${selected.confidence}%`]]} />
          <section className="execution-section">
            <h3>真实 Trace</h3>
            {workflowTraces.length > 0 ? (
              <ol className="timeline-list">
                {workflowTraces.map((trace) => (
                <li className={/fail|error|失败/.test(trace.status) ? "pending" : ""} key={trace.recordId}>
                  <span />
                  <div>
                    <strong>{trace.stepName || trace.stepType || trace.runId || "workflow.step"}</strong>
                    <small>{trace.status || "unknown"}</small>
                    {(trace.inputSummary || trace.outputSummary || trace.decision) && (
                      <p>{[trace.inputSummary, trace.outputSummary, trace.decision].filter(Boolean).join(" / ")}</p>
                    )}
                  </div>
                </li>
                ))}
              </ol>
            ) : (
              <p className="trace-empty">当前候选人暂无 workflow_log。工作台不会生成推测 trace。</p>
            )}
          </section>
        </aside>
        </section>
        </>
      ) : (
        <ConfigView config={config} configSource={configSource} />
      )}

      {toast && <div className="visual-toast">{toast}</div>}
    </main>
  );
}

function Nav({ activeTab, onChange }: { activeTab: ActiveTab; onChange: (tab: ActiveTab) => void }) {
  return (
    <nav>
      <button className={activeTab === "overview" ? "active" : ""} onClick={() => onChange("overview")} type="button">概览</button>
      <button className={activeTab === "config" ? "active" : ""} onClick={() => onChange("config")} type="button">配置</button>
    </nav>
  );
}

function ModePill({ mode, isRunning }: { mode: RunMode; isRunning: boolean }) {
  return (
    <span className={`visual-live visual-live-${runModeCopy[mode].tone}`}>
      {isRunning ? "RUNNING" : runModeCopy[mode].label}
    </span>
  );
}

function ModeSwitch({
  mode,
  onChange,
  disabled
}: {
  mode: RunMode;
  onChange: (mode: RunMode) => void;
  disabled: boolean;
}) {
  return (
    <div className="visual-mode-switch" aria-label="运行模式">
      {(["dry_run", "test_mode", "production"] as RunMode[]).map((item) => (
        <button
          className={mode === item ? "active" : ""}
          disabled={disabled}
          key={item}
          onClick={() => onChange(item)}
          title={runModeCopy[item].note}
          type="button"
        >
          {runModeCopy[item].label}
        </button>
      ))}
    </div>
  );
}

function ConfigView({ config, configSource }: { config: LarkConfigPayload | null; configSource: string }) {
  const [schemaCheckpoint, setSchemaCheckpoint] = useState<SchemaCheckpointPayload | null>(null);
  const [schemaNote, setSchemaNote] = useState("");
  const [schemaBusy, setSchemaBusy] = useState(false);
  const [schemaMessage, setSchemaMessage] = useState("");
  const schemaMissingCount = schemaCheckpoint?.tables?.reduce((sum, table) => sum + table.missing.length, 0) ?? 0;

  const runSchemaAction = async (action: "propose" | "adjust" | "confirm", createMissingFields = false) => {
    setSchemaBusy(true);
    setSchemaMessage("");
    try {
      const payload = await runSchemaCheckpoint({
        action,
        createMissingFields,
        note: action === "adjust" ? schemaNote : undefined,
        table: "all",
        ...(action === "propose" ? {} : { ["token"]: schemaCheckpoint?.checkpoint_token })
      });
      setSchemaCheckpoint(payload);
      if (action === "adjust") setSchemaNote("");
      setSchemaMessage(payload.message || (action === "confirm" ? "字段映射已确认保存。" : "字段映射 checkpoint 已生成。"));
    } catch (error) {
      setSchemaMessage(error instanceof Error ? error.message : "字段映射 checkpoint 执行失败");
    } finally {
      setSchemaBusy(false);
    }
  };

  return (
    <section className="visual-config-page">
      <div className="config-hero">
        <div>
          <span>数据来源</span>
          <h1>Lark 表与字段映射</h1>
          <p>工作台只读取下列数据表和字段映射。需要核对原始数据时，可以直接打开对应 Lark 表。</p>
        </div>
        <strong>{configSource}</strong>
      </div>

      <div className="config-paths">
        <Info label="本机配置" value={config?.configPath ?? "读取中"} mono />
        <Info label="字段映射" value={config?.mappingPath ?? "读取中"} mono />
      </div>

      <section className="schema-checkpoint-card">
        <div className="schema-checkpoint-head">
          <div>
            <span>SCHEMA CHECKPOINT</span>
            <h2>换表前字段映射确认</h2>
            <p>Agent 会读取当前 Lark 表头，生成字段映射建议。VM 确认后才会保存映射；如需调整，可以用自然语言说明。</p>
          </div>
          <strong className={`schema-status ${schemaCheckpoint?.status || "idle"}`}>
            {schemaCheckpoint?.status || "未检查"}
          </strong>
        </div>
        <div className="schema-actions">
          <button disabled={schemaBusy} onClick={() => runSchemaAction("propose")} type="button">
            检查字段映射
          </button>
          <button
            disabled={schemaBusy || !schemaCheckpoint?.checkpoint_token || schemaMissingCount === 0}
            onClick={() => runSchemaAction("propose", true)}
            title="先检查字段映射并核对缺失字段清单，确认需要新增后再点击。"
            type="button"
          >
            确认新增缺失列并重新检查
          </button>
          <button disabled={schemaBusy || !schemaCheckpoint?.checkpoint_token} onClick={() => runSchemaAction("confirm")} type="button">
            确认保存映射
          </button>
        </div>
        <div className="schema-adjust-row">
          <textarea
            onChange={(event) => setSchemaNote(event.target.value)}
            placeholder="例如：把 candidate.resume 映射到 简历附件；将 contract.email 改成 常用工作邮箱"
            value={schemaNote}
          />
          <button disabled={schemaBusy || !schemaCheckpoint?.checkpoint_token || !schemaNote.trim()} onClick={() => runSchemaAction("adjust")} type="button">
            提交调整
          </button>
        </div>
        {schemaMessage && <p className="schema-message">{schemaMessage}</p>}
        {schemaCheckpoint && (
          <div className="schema-result">
            <div className="schema-token">
              <Info label="checkpoint" value={schemaCheckpoint.checkpoint_token || "-"} mono accent />
              <Info label="缺口" value={`${schemaCheckpoint.hard_failures?.length ?? 0}`} mono warning={(schemaCheckpoint.hard_failures?.length ?? 0) > 0} />
              <Info label="映射文件" value={schemaCheckpoint.mapping_path || config?.mappingPath || "-"} mono />
            </div>
            {schemaCheckpoint.hard_failures && schemaCheckpoint.hard_failures.length > 0 && (
              <div className="schema-failures">
                {schemaCheckpoint.hard_failures.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            )}
            <div className="schema-table-list">
              {(schemaCheckpoint.tables ?? []).map((table) => (
                <details key={table.table_key} open={table.status !== "ready"}>
                  <summary>
                    <strong>{table.table_key}</strong>
                    <span>{table.status}</span>
                    <em>已映射 {table.mapped.length} / 疑似 {table.fuzzy.length} / 缺失 {table.missing.length}</em>
                  </summary>
                  {table.error && <p className="schema-error">{table.error}</p>}
                  {table.fuzzy.length > 0 && (
                    <div className="schema-mini-list">
                      <h3>需要 VM 确认的疑似映射</h3>
                      {table.fuzzy.slice(0, 10).map((item) => (
                        <p key={`${table.table_key}-${item.logical_key}`}>
                          <code>{item.logical_key}</code> → {item.field_name} <span>score={item.score}</span>
                        </p>
                      ))}
                    </div>
                  )}
                  {table.missing.length > 0 && (
                    <div className="schema-mini-list">
                      <h3>缺失字段</h3>
                      {table.missing.slice(0, 10).map((item) => (
                        <p key={`${table.table_key}-${item.logical_key}`}>
                          <code>{item.logical_key}</code> / {item.expected_name} / {item.required ? "必需" : "建议"}
                        </p>
                      ))}
                    </div>
                  )}
                  <div className="schema-mini-list">
                    <h3>当前映射</h3>
                    {table.mapped.slice(0, 16).map((item) => (
                      <p key={`${table.table_key}-${item.logical_key}`}>
                        <code>{item.logical_key}</code> → {item.field_name} <span>{item.match_type}</span>
                      </p>
                    ))}
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}
      </section>

      <div className="config-table-grid">
        {(config?.tables ?? []).map((table) => (
          <article className="config-table-card" key={table.key}>
            <div className="config-card-head">
              <div>
                <span>{table.key}</span>
                <h2>{table.label}</h2>
              </div>
              {table.url ? (
                <a href={table.url} rel="noreferrer" target="_blank">打开 Lark</a>
              ) : (
                <strong>未配置</strong>
              )}
            </div>
            <p>{table.purpose}</p>
            <div className="config-id-grid">
              <Info label="base_token" value={table.baseToken || "未配置"} mono />
              <Info label="table_id" value={table.tableId || "未配置"} mono />
              {table.source && <Info label="来源" value={table.source} mono />}
              <Info label="映射字段数" value={`${table.fieldCount}`} mono accent />
            </div>
            {table.sourceNote && <p>{table.sourceNote}</p>}
            {table.fields.length > 0 && (
              <details>
                <summary>查看字段映射</summary>
                <div className="config-field-list">
                  {table.fields.map((field) => (
                    <div key={field.key}>
                      <span>{field.key}</span>
                      <strong>{field.fieldName || "-"}</strong>
                      <code>{field.expectedType || "-"}</code>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function ChatBubble({ role, text }: { role: "vm" | "agent"; text: string }) {
  return (
    <div className={`visual-bubble-row ${role}`}>
      <div className="bubble-avatar">{role === "vm" ? "VM" : "AI"}</div>
      <div className="visual-bubble">
        <span>{role === "vm" ? "VM" : "Agent"}</span>
        <p>{text}</p>
      </div>
    </div>
  );
}

function Info({
  label,
  value,
  mono,
  accent,
  warning
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: boolean;
  warning?: boolean;
}) {
  return (
    <div className={`visual-info ${mono ? "mono" : ""} ${accent ? "accent" : ""} ${warning ? "warning" : ""}`}>
      <span>{label}</span>
      <strong title={value}>{value}</strong>
    </div>
  );
}

function MetricGroup({ title, items }: { title: string; items: string[][] }) {
  return (
    <section className="execution-section">
      <h3>{title}</h3>
      <div className="metric-list">
        {items.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong title={value}>{value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
