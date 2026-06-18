import type { AgentRunEvent } from "@/lib/agent-runner";
import type { CheckpointSummary } from "./types";

export const eventLabel: Record<AgentRunEvent["event_type"], string> = {
  run_started: "执行开始",
  candidate_resolved: "候选人定位",
  agent_message: "Agent 说明",
  step_started: "步骤开始",
  step_input: "步骤输入",
  tool_call_started: "脚本调用",
  tool_call_output: "脚本输出",
  warning: "风险提示",
  waiting_input: "等待输入",
  checkpoint: "人工确认",
  checkpoint_confirmed: "确认完成",
  vm_decision: "人工决策",
  lark_writeback: "Lark 写回",
  workflow_log_written: "日志写入",
  usage_report: "成本统计",
  step_done: "步骤完成",
  step_failed: "步骤失败",
  run_done: "执行结束",
  run_cancelled: "执行取消"
};

export function stringifyPayload(payload: Record<string, unknown>) {
  if (typeof payload.text === "string") return sanitizeDemoText(payload.text);
  return sanitizeDemoText(JSON.stringify(payload, null, 2));
}

export function sanitizeDemoText(text: string) {
  return text
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function statusForEvent(event: AgentRunEvent) {
  if (event.event_type === "step_failed") return "failed";
  if (event.event_type === "waiting_input") return "waiting";
  if (event.event_type === "checkpoint") return "waiting";
  if (event.event_type === "warning") return "warning";
  if (event.event_type === "run_done" || event.event_type === "step_done") return "done";
  return "running";
}

export function eventSummary(event: AgentRunEvent) {
  if (event.event_type === "tool_call_output") {
    const text = typeof event.payload.text === "string" ? sanitizeDemoText(event.payload.text).split("\n")[0] : "";
    return text || "脚本输出";
  }
  if (event.event_type === "step_failed") return "执行失败";
  if (event.event_type === "waiting_input") return sanitizeDemoText(String(event.payload.prompt ?? "等待补充信息"));
  if (event.event_type === "checkpoint") return sanitizeDemoText(String(event.payload.title ?? "等待确认"));
  if (event.event_type === "step_input") return sanitizeDemoText(String(event.payload.command_preview ?? "步骤输入"));
  if (event.event_type === "warning") return sanitizeDemoText(String(event.payload.message ?? "风险提示"));
  return eventLabel[event.event_type];
}

export function inferCandidateLocator(text: string) {
  const recordId = text.match(/rec[a-zA-Z0-9]+/)?.[0];
  if (recordId) return { type: "record_id" as const, value: recordId };
  const businessRecordId = text.match(/\b\d{8}-\d{1,4}\b/)?.[0];
  if (businessRecordId) return { type: "record_id" as const, value: businessRecordId };
  return undefined;
}

export function inferAttachmentPaths(text: string) {
  return Array.from(
    text.matchAll(/(?:\/Users\/|\/tmp\/|\/private\/tmp\/)[^\s"'<>]+?\.(?:xlsx|pdf|docx)/gi)
  ).map((match) => match[0]);
}

function payloadText(payload: Record<string, unknown>, key: string) {
  const summary = payload.summary;
  if (summary && typeof summary === "object" && key in summary) {
    const value = (summary as Record<string, unknown>)[key];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  }
  return "";
}

export function checkpointSummary(payload: Record<string, unknown>): CheckpointSummary {
  const confidence = payloadText(payload, "confidence") || "未识别";
  const wordCountSource = payloadText(payload, "word_count_source");
  return {
    totalScore: payloadText(payload, "total_score") || "未识别",
    tier: payloadText(payload, "final_tier") || payloadText(payload, "tier") || "未识别",
    aiSuggestion: payloadText(payload, "ai_suggestion") || payloadText(payload, "suggestion") || "未识别",
    comment: payloadText(payload, "comment") || "未识别",
    confidence,
    confidenceReason: confidenceReason(confidence, wordCountSource),
    subject: payloadText(payload, "subject") || "未识别",
    recipient: payloadText(payload, "recipient") || "未识别",
    attachment: payloadText(payload, "attachment") || "未识别",
    selectedTemplate: payloadText(payload, "selected_template") || "未识别",
    filledVariables: payloadText(payload, "filled_variables") || "未识别",
    requiredVariables: payloadText(payload, "required_variables") || "未识别"
  };
}

function confidenceReason(confidence: string, wordCountSource: string) {
  if (!wordCountSource) return confidence;
  if (wordCountSource === "明确字数") return `${confidence}（数据来源：明确字数）`;
  if (wordCountSource === "混合估算") return `${confidence} ⚠️ 字数基于混合估算`;
  if (wordCountSource === "年限估算") return `${confidence} ⚠️ 字数基于年限估算`;
  if (wordCountSource === "项目数估算") return `${confidence} ⚠️ 字数基于项目数估算`;
  return `${confidence}（数据来源：${wordCountSource}）`;
}

export function checkpointType(payload: Record<string, unknown>) {
  const summary = payload.summary;
  if (!summary || typeof summary !== "object") return "generic";
  const fields = summary as Record<string, unknown>;
  if ("total_score" in fields || "final_tier" in fields || "confidence" in fields) return "resume";
  if ("subject" in fields || "recipient" in fields || "attachment" in fields) return "email";
  if ("selected_template" in fields || "filled_variables" in fields) return "contract";
  return "generic";
}
