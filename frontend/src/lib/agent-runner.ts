import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { findLarkRecord, getSkillConfigPath, getSkillRoot, textValue, type LarkRecord } from "@/lib/lark-data-access";

export type AgentAction =
  | "resume-evaluate"
  | "score"
  | "test-email"
  | "test-email-mark-sent"
  | "contract-info-email"
  | "contract-info-mark-sent"
  | "contract-generate"
  | "signed-contract-check"
  | "update-status"
  | "unknown";

export type AgentRunRequest = {
  message: string;
  candidateLocator?: {
    type: "record_id" | "name" | "nickname" | "email";
    value: string;
  };
  attachments?: string[];
  mode?: "dry_run" | "production" | "test_mode";
  action?: AgentAction;
};

export type AgentRunMode = "dry_run" | "production";

export type AgentRunEvent = {
  event_id: string;
  run_id: string;
  event_type:
    | "run_started"
    | "candidate_resolved"
    | "agent_message"
    | "step_started"
    | "step_input"
    | "tool_call_started"
    | "tool_call_output"
    | "warning"
    | "checkpoint"
    | "vm_decision"
    | "lark_writeback"
    | "workflow_log_written"
    | "usage_report"
    | "step_done"
    | "step_failed"
    | "run_done"
    | "run_cancelled";
  timestamp: string;
  candidate_record_id?: string;
  candidate_name?: string;
  step_name?: string;
  payload: Record<string, unknown>;
};

export type PlannedCommand = {
  action: AgentAction;
  requestedMode: AgentRunMode;
  effectiveMode: AgentRunMode;
  modeNote: string;
  workflowVersion?: string;
  scriptRole?: string;
  isLegacy?: boolean;
  candidateName?: string;
  candidateRecordId?: string;
  script: string;
  args: string[];
  resolvedAttachment?: string;
  validationErrors?: string[];
  checkpointAfterSuccess?: {
    title: string;
    detail: string;
  };
  warnings?: string[];
};

const SKILL_ROOT = getSkillRoot();
const SKILL_CONFIG = getSkillConfigPath();

type CandidateResolution = {
  args: string[];
  recordId?: string;
  name?: string;
  warnings?: string[];
  validationErrors?: string[];
};

function inferAction(message: string): AgentAction {
  const sentSignal = /已发送|已发出|已经发送|已经发出|人工发送|标记.*发送/.test(message);
  const contractInfoSignal = /签约信息|合同信息收集|收集合同信息|签约资料|收款信息/.test(message);
  if (sentSignal && contractInfoSignal) return "contract-info-mark-sent";
  if (contractInfoSignal) return "contract-info-email";
  if (sentSignal && message.includes("测试")) return "test-email-mark-sent";
  if (message.includes("签字") || message.includes("核查") || message.includes("检查")) return "signed-contract-check";
  if (message.includes("合同")) return "contract-generate";
  if (message.includes("测试")) return "test-email";
  if (message.includes("重算评分") || message.includes("重跑评分") || message.includes("重新评分")) return "score";
  if (message.includes("评分") || message.includes("简历") || message.includes("初筛")) return "resume-evaluate";
  if (message.includes("状态") || message.includes("推进") || message.includes("财务登记")) return "update-status";
  return "unknown";
}

function inferCandidateName(message: string, request: AgentRunRequest) {
  if (request.candidateLocator?.type === "name" || request.candidateLocator?.type === "nickname") {
    return request.candidateLocator.value;
  }
  return undefined;
}

function inferRecordId(request: AgentRunRequest) {
  if (request.candidateLocator?.type === "record_id") return request.candidateLocator.value;
  return undefined;
}

function resolveForCandidateTable(request: AgentRunRequest): CandidateResolution {
  const directRecordId = inferRecordId(request);
  if (directRecordId?.startsWith("rec")) return { args: ["--record-id", directRecordId], recordId: directRecordId };

  const { match, matches } = findLarkRecord("candidate", {
    message: request.message,
    locator: request.candidateLocator
  });
  if (match) {
    const nameEntry = Object.entries(match.fields).find(([field]) => field.includes("姓名"));
    return {
      args: ["--record-id", match.recordId],
      recordId: match.recordId,
      name: nameEntry ? textValue(nameEntry[1]) : ""
    };
  }
  if (matches.length > 1) {
    return {
      args: [],
      validationErrors: [`候选人主表命中 ${matches.length} 条记录，请使用 Lark record_id 精确指定。`]
    };
  }
  return {
    args: [],
    name: inferCandidateName(request.message, request),
    validationErrors: ["候选人主表未找到匹配记录：请提供姓名全称、昵称、邮箱、编号或 Lark record_id。"]
  };
}

function resolveForContractTable(request: AgentRunRequest): CandidateResolution {
  const { match, matches } = findLarkRecord("contract", {
    message: request.message,
    locator: request.candidateLocator
  });
  if (match) {
    const nameEntry = Object.entries(match.fields).find(([field]) => field.includes("姓名"));
    const name = nameEntry ? textValue(nameEntry[1]) : "";
    return {
      args: ["--name", name],
      recordId: match.recordId,
      name,
      warnings: [`已在合同信息表匹配到 record_id=${match.recordId}；合同模板选择仍由 generate_contract.py 内部完成。`]
    };
  }
  if (matches.length > 1) {
    return {
      args: [],
      validationErrors: [`合同信息表命中 ${matches.length} 条记录，请使用合同信息表 record_id 精确指定。`]
    };
  }
  return {
    args: [],
    name: inferCandidateName(request.message, request),
    validationErrors: ["合同信息表未找到匹配记录：请提供合同信息表姓名全称、邮箱或 record_id。"]
  };
}

export function normalizeAgentRunMode(mode: AgentRunRequest["mode"]): AgentRunMode {
  return mode === "production" ? "production" : "dry_run";
}

function modeArgs(mode: AgentRunMode) {
  return mode === "dry_run" ? ["--dry-run"] : [];
}

function modeNote(requestedMode: AgentRunMode, effectiveMode: AgentRunMode, action: AgentAction) {
  if (effectiveMode === "dry_run") {
    return "dry_run：只生成真实预览事件；不发送邮件、不写业务主表、不生成正式合同文件。";
  }
  if (action === "score" || action === "resume-evaluate") {
    return "production：调用现有评分脚本正式写回评分字段；本次 checkpoint 只用于审阅，不再重复写回。";
  }
  if (action === "test-email-mark-sent" || action === "contract-info-mark-sent") {
    return "production：只写回“人工已发送”状态和 workflow_log，不由前端直接发送邮件。";
  }
  if (requestedMode === "production") {
    return "production：允许底层脚本执行该节点的真实副作用；不会在事件流中伪装成 dry-run。";
  }
  return "dry_run：默认安全预览模式。";
}

export function planAgentRun(request: AgentRunRequest): PlannedCommand {
  const requestedMode = normalizeAgentRunMode(request.mode);
  const action = request.action && request.action !== "unknown" ? request.action : inferAction(request.message);
  const candidate =
    action === "contract-generate" || action === "signed-contract-check"
      ? resolveForContractTable(request)
      : resolveForCandidateTable(request);
  const effectiveMode =
    requestedMode === "production" &&
    (action === "score" ||
      action === "resume-evaluate" ||
      action === "test-email-mark-sent" ||
      action === "contract-info-mark-sent")
      ? "production"
      : "dry_run";
  const explicitAttachment = request.attachments?.find(Boolean);
  const firstAttachment = explicitAttachment;
  const validationErrors: string[] = [...(candidate.validationErrors ?? [])];

  if (action !== "unknown" && candidate.args.length === 0) {
    validationErrors.push("缺少候选人定位信息：请提供对应表的 record_id、姓名全称、昵称、邮箱或编号。");
  }

  if (action === "resume-evaluate") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      workflowVersion: "v2-resume-evaluate",
      scriptRole: "current_main_path",
      isLegacy: false,
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/evaluate_resume_node.py`,
      args: [...candidate.args, ...modeArgs(effectiveMode)],
      validationErrors,
      checkpointAfterSuccess: {
        title: "简历评估结果确认",
        detail:
          effectiveMode === "dry_run"
            ? "简历解析和评分已完成预览。VM 确认后才允许写回正式字段。"
            : "简历解析和评分已正式写回。该确认点用于人工复核和留痕。"
      }
    };
  }

  if (action === "score") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      workflowVersion: "v2-two-stage-scoring",
      scriptRole: "current_main_path",
      isLegacy: false,
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/rescore_and_write_v2.py`,
      args: [...candidate.args, ...modeArgs(effectiveMode)],
      validationErrors,
      checkpointAfterSuccess: {
        title: "简历评估结果确认",
        detail:
          effectiveMode === "dry_run"
            ? "当前主流程评分已完成预览。VM 确认后才允许写回正式字段。"
            : "当前主流程评分已正式写回。该确认点仅用于人工复核和留痕。"
      }
    };
  }

  if (action === "test-email") {
    if (!firstAttachment) {
      validationErrors.push("测试题邮件缺少附件路径：请提供测试题 xlsx/pdf/docx 文件路径。");
    }
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/send_test_email.py`,
      args: [...candidate.args, ...(firstAttachment ? ["--file", firstAttachment] : []), ...modeArgs(effectiveMode)],
      resolvedAttachment: firstAttachment,
      validationErrors,
      warnings: [
        ...(candidate.warnings ?? []),
        ...(requestedMode === "production"
          ? ["测试题邮件节点暂未接入后端确认发送；本次强制降级为 dry-run，避免未确认即发送邮件。"]
          : [])
      ],
      checkpointAfterSuccess: {
        title: "测试题邮件确认",
        detail: "已使用 VM 提供的附件生成测试题邮件预览。正式发送或 TEST_MODE 发送前必须由 VM 确认。"
      }
    };
  }

  if (action === "test-email-mark-sent") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      workflowVersion: "v2-test-email-mark-sent",
      scriptRole: "current_status_writeback",
      isLegacy: false,
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/send_test_email_v2.py`,
      args: [...candidate.args, "--mark-sent", ...modeArgs(effectiveMode)],
      validationErrors,
      warnings:
        requestedMode !== "production"
          ? ["标记测试题已发送需要 PRODUCTION 模式；当前会以 dry-run 预览。"]
          : candidate.warnings ?? []
    };
  }

  if (action === "contract-info-email") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      workflowVersion: "v2-contract-info-email",
      scriptRole: "current_main_path",
      isLegacy: false,
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/send_contract_info_email_v2.py`,
      args: [...candidate.args, ...modeArgs(effectiveMode)],
      validationErrors,
      warnings: [
        ...(candidate.warnings ?? []),
        ...(requestedMode === "production"
          ? ["签约信息收集邮件节点当前由前端生成预览；正式发送后请用“已发送签约信息收集邮件”写回状态。"]
          : [])
      ],
      checkpointAfterSuccess: {
        title: "签约信息收集邮件确认",
        detail: "已生成签约信息收集邮件预览。正式发送或生成草稿前必须由 VM 确认。"
      }
    };
  }

  if (action === "contract-info-mark-sent") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      workflowVersion: "v2-contract-info-mark-sent",
      scriptRole: "current_status_writeback",
      isLegacy: false,
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/send_contract_info_email_v2.py`,
      args: [...candidate.args, "--mark-sent", ...modeArgs(effectiveMode)],
      validationErrors,
      warnings:
        requestedMode !== "production"
          ? ["标记签约信息收集邮件已发送需要 PRODUCTION 模式；当前会以 dry-run 预览。"]
          : candidate.warnings ?? []
    };
  }

  if (action === "contract-generate") {
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/generate_contract.py`,
      args: [...candidate.args, ...modeArgs(effectiveMode)],
      validationErrors,
      warnings: [
        ...(candidate.warnings ?? []),
        ...(requestedMode === "production"
          ? ["合同生成节点暂未接入后端确认生成/发送；本次强制降级为 dry-run，避免未确认即生成正式材料或发送邮件。"]
          : [])
      ],
      checkpointAfterSuccess: {
        title: "合同草稿确认",
        detail: "合同生成已完成 dry-run。生产流程中只生成草稿/预览，不自动发送。"
      }
    };
  }

  if (action === "signed-contract-check") {
    if (!firstAttachment) {
      validationErrors.push("签字合同核查缺少签回 PDF 路径：请提供已签署合同文件路径。");
    }
    return {
      action,
      requestedMode,
      effectiveMode,
      modeNote: modeNote(requestedMode, effectiveMode, action),
      candidateName: candidate.name,
      candidateRecordId: candidate.recordId,
      script: `${SKILL_ROOT}/scripts/check_signed_contract.py`,
      args: [...candidate.args, ...(firstAttachment ? ["--file", firstAttachment] : []), ...modeArgs(effectiveMode)],
      validationErrors,
      warnings: [
        ...(candidate.warnings ?? []),
        ...(requestedMode === "production"
          ? ["签字合同核查节点暂未接入后端确认推进；本次强制降级为 dry-run，避免未确认即推进合同状态。"]
          : []),
        "签字核查若发现邮箱、姓名、银行信息不一致，必须暂停等待 VM 确认。"
      ],
      checkpointAfterSuccess: {
        title: "签字核查确认",
        detail: "签字核查已完成 dry-run。若存在不一致，VM 确认无异常后才允许推进状态。"
      }
    };
  }

  return {
    action,
    requestedMode,
    effectiveMode,
    modeNote: modeNote(requestedMode, effectiveMode, action),
    candidateName: candidate.name,
    candidateRecordId: candidate.recordId,
    script: "",
    args: [],
    validationErrors:
      action === "update-status"
        ? [...validationErrors, "状态推进需要明确目标状态，并接入 resume/checkpoint 记录后才能执行。"]
        : validationErrors
  };
}

export function createEventFactory(runId: string, plan: PlannedCommand) {
  let count = 0;
  return (
    event_type: AgentRunEvent["event_type"],
    payload: Record<string, unknown>,
    step_name?: string
  ): AgentRunEvent => {
    count += 1;
    return {
      event_id: `evt_${String(count).padStart(4, "0")}`,
      run_id: runId,
      event_type,
      timestamp: new Date().toISOString(),
      candidate_record_id: plan.candidateRecordId,
      candidate_name: plan.candidateName,
      step_name,
      payload
    };
  };
}
