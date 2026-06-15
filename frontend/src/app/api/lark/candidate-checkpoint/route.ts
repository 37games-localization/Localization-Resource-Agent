import { spawnSync } from "node:child_process";
import { NextResponse } from "next/server";
import { larkTableConfig, mappedFieldKey } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type CheckpointRequest = {
  recordId?: string;
  action?: "confirm" | "modify";
  rating?: string;
  aiSuggestion?: string;
  reason?: string;
  checkpointSummary?: Record<string, unknown>;
  checkpointKind?: "resume" | "test-email" | "contract" | "signed-contract" | "generic";
  runId?: string;
  candidateName?: string;
  mode?: "dry_run" | "production" | "test_mode";
};

function upsertRecord(
  table: "candidate" | "workflowLog",
  fields: Record<string, unknown>,
  recordId?: string
) {
  const cfg = larkTableConfig(table);
  if (!cfg.baseToken || !cfg.tableId) throw new Error(`Lark ${table} 表配置缺失`);
  const args = [
    "base",
    "+record-upsert",
    "--base-token",
    cfg.baseToken,
    "--table-id",
    cfg.tableId,
    "--json",
    JSON.stringify(fields)
  ];
  if (recordId) args.splice(6, 0, "--record-id", recordId);
  const result = spawnSync(
    "lark-cli",
    args,
    { encoding: "utf8" }
  );
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || "Lark 写回失败");
  }
}

function updateCandidate(recordId: string, fields: Record<string, unknown>) {
  upsertRecord("candidate", fields, recordId);
}

function candidateField(logicalKey: string, fallbackName: string) {
  return mappedFieldKey("candidate", logicalKey, fallbackName);
}

function workflowField(logicalKey: string, fallbackName: string) {
  return mappedFieldKey("workflow_log", logicalKey, fallbackName);
}

function setField(
  fields: Record<string, unknown>,
  tableField: (logicalKey: string, fallbackName: string) => string,
  logicalKey: string,
  fallbackName: string,
  value: unknown
) {
  const key = tableField(logicalKey, fallbackName);
  fields[key] = value;
  return key;
}

function larkDatetime(date = new Date()) {
  return date.getTime();
}

function writeWorkflowLog(fields: {
  runId: string;
  candidateRecordId: string;
  candidateName?: string;
  stepName: string;
  stepType: string;
  status: string;
  inputSummary: string;
  outputSummary: string;
  decision: string;
}) {
  const payload: Record<string, unknown> = {};
  setField(payload, workflowField, "workflow.run_id", "run_id", fields.runId);
  setField(payload, workflowField, "workflow.candidate_record_id", "candidate_record_id", fields.candidateRecordId);
  setField(payload, workflowField, "workflow.candidate_name", "candidate_name", fields.candidateName || "");
  setField(payload, workflowField, "workflow.step_name", "step_name", fields.stepName);
  setField(payload, workflowField, "workflow.step_type", "step_type", fields.stepType);
  setField(payload, workflowField, "workflow.status", "status", fields.status);
  setField(payload, workflowField, "workflow.input_summary", "input_summary", fields.inputSummary);
  setField(payload, workflowField, "workflow.output_summary", "output_summary", fields.outputSummary);
  setField(payload, workflowField, "workflow.decision", "decision", fields.decision);
  setField(payload, workflowField, "workflow.created_at", "created_at", larkDatetime());
  upsertRecord("workflowLog", payload);
}

function summaryText(summary: Record<string, unknown>) {
  return [
    summary.total_score ? `总分=${summary.total_score}` : "",
    summary.final_tier ? `评级=${summary.final_tier}` : "",
    summary.ai_suggestion ? `AI建议=${summary.ai_suggestion}` : "",
    summary.confidence ? `置信度=${summary.confidence}` : ""
  ]
    .filter(Boolean)
    .join("；");
}

function textValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "";
}

function isResumeCheckpointSummary(summary: Record<string, unknown>) {
  const hasNonResumeKeys =
    "subject" in summary ||
    "recipient" in summary ||
    "attachment" in summary ||
    "selected_template" in summary ||
    "filled_variables" in summary ||
    "contract_record_id" in summary;
  const hasResumeKeys =
    "total_score" in summary ||
    "final_tier" in summary ||
    "initial_tier" in summary ||
    "valid_resume" in summary ||
    "confidence" in summary ||
    "extracted_word_count" in summary ||
    "years" in summary ||
    "project_count" in summary;
  return hasResumeKeys && !hasNonResumeKeys;
}

function checkpointRunId(body: CheckpointRequest, summary: Record<string, unknown>) {
  return body.runId || textValue(summary.run_id) || `checkpoint_${Date.now()}`;
}

function checkpointCandidateName(body: CheckpointRequest, summary: Record<string, unknown>) {
  return body.candidateName || textValue(summary.candidate_name);
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as CheckpointRequest;
    if (!body.recordId?.startsWith("rec")) {
      return NextResponse.json({ ok: false, error: "缺少有效 record_id" }, { status: 400 });
    }

    const summary = body.checkpointSummary ?? {};
    if (body.checkpointKind && body.checkpointKind !== "resume") {
      return NextResponse.json(
        { ok: false, error: "当前确认接口只允许处理简历评估 checkpoint；测试题、合同、签字核查不能走简历确认写回。" },
        { status: 400 }
      );
    }
    if (body.action !== "modify" && !isResumeCheckpointSummary(summary)) {
      return NextResponse.json(
        { ok: false, error: "当前确认接口只允许处理简历评估 checkpoint；缺少简历评分摘要或命中了非简历 checkpoint 字段。" },
        { status: 400 }
      );
    }
    if (body.action !== "modify" && summary.execution_mode !== "production") {
      return NextResponse.json(
        { ok: false, error: "当前 checkpoint 不是 production 执行结果，不能通过前端确认写回。请切换 PRODUCTION 后重新运行简历评估。" },
        { status: 400 }
      );
    }

    if (body.action === "modify") {
      if (body.checkpointKind !== "resume" || !body.runId?.startsWith("run_")) {
        return NextResponse.json(
          { ok: false, error: "人工修改必须绑定本轮简历评估 checkpoint" },
          { status: 400 }
        );
      }
      if (!body.reason?.trim()) {
        return NextResponse.json({ ok: false, error: "修改结果必须填写调整原因" }, { status: 400 });
      }
      if (body.mode !== "production" || summary.execution_mode !== "production") {
        return NextResponse.json(
          { ok: false, error: "人工修改只能绑定 production 简历评估 checkpoint，dry-run 不能写回 Badcase。" },
          { status: 400 }
        );
      }
      const modifiedFields: Record<string, unknown> = {};
      const modifiedFieldLabels = ["初始评级", "AI建议", "是否Badcase", "期望结果", "招募状态"];
      setField(modifiedFields, candidateField, "candidate.tier", "初始评级", body.rating || "A");
      setField(modifiedFields, candidateField, "candidate.ai_suggestion", "AI建议", body.aiSuggestion || "人工复核");
      setField(modifiedFields, candidateField, "candidate.badcase_flag", "是否Badcase", "⚠️ 是");
      setField(modifiedFields, candidateField, "candidate.expected_result", "期望结果", body.reason);
      setField(modifiedFields, candidateField, "candidate.status", "招募状态", "初筛中");
      updateCandidate(body.recordId, modifiedFields);
      writeWorkflowLog({
        runId: checkpointRunId(body, summary),
        candidateRecordId: body.recordId,
        candidateName: checkpointCandidateName(body, summary),
        stepName: "resume-score-modify",
        stepType: "checkpoint",
        status: "decided",
        inputSummary: "VM 修改评分结果",
        outputSummary: `评级=${body.rating || "A"}；AI建议=${body.aiSuggestion || "人工复核"}`,
        decision: body.reason
      });
      return NextResponse.json({
        ok: true,
        data: {
          status: "badcase_recorded",
          updatedFields: modifiedFieldLabels
        }
      });
    }

    if (!summary.total_score || !summary.final_tier) {
      return NextResponse.json(
        { ok: false, error: "简历评估 checkpoint 缺少总分或评级，不能写回" },
        { status: 400 }
      );
    }
    const confirmedFields: Record<string, unknown> = {};
    const confirmedFieldLabels = ["招募状态", "是否Badcase", "期望结果"];
    setField(confirmedFields, candidateField, "candidate.status", "招募状态", "初筛通过");
    setField(confirmedFields, candidateField, "candidate.badcase_flag", "是否Badcase", null);
    setField(confirmedFields, candidateField, "candidate.expected_result", "期望结果", null);

    if (summary.total_score) {
      setField(confirmedFields, candidateField, "candidate.score", "Agent总分", Number(summary.total_score) || summary.total_score);
      confirmedFieldLabels.push("Agent总分");
    }
    if (summary.final_tier) {
      setField(confirmedFields, candidateField, "candidate.tier", "初始评级", summary.final_tier);
      confirmedFieldLabels.push("初始评级");
    }
    if (summary.ai_suggestion) {
      setField(confirmedFields, candidateField, "candidate.ai_suggestion", "AI建议", summary.ai_suggestion);
      confirmedFieldLabels.push("AI建议");
    }
    if (summary.comment) {
      setField(confirmedFields, candidateField, "candidate.score_basis", "评分依据", summary.comment);
      confirmedFieldLabels.push("评分依据");
    }
    if (summary.valid_resume) {
      setField(confirmedFields, candidateField, "candidate.valid_resume", "有效简历", summary.valid_resume);
      confirmedFieldLabels.push("有效简历");
    }
    if (summary.extracted_word_count && summary.extracted_word_count !== "未识别") {
      setField(confirmedFields, candidateField, "candidate.parsed_word_count", "解析字数", Number(summary.extracted_word_count) || summary.extracted_word_count);
      confirmedFieldLabels.push("解析字数");
    }
    if (summary.years && summary.years !== "未识别") {
      setField(confirmedFields, candidateField, "candidate.parsed_years", "解析年限", Number(summary.years) || summary.years);
      confirmedFieldLabels.push("解析年限");
    }
    if (summary.project_count && summary.project_count !== "未识别") {
      setField(confirmedFields, candidateField, "candidate.parsed_project_count", "解析项目数", Number(summary.project_count) || summary.project_count);
      confirmedFieldLabels.push("解析项目数");
    }

    updateCandidate(body.recordId, confirmedFields);
    writeWorkflowLog({
      runId: checkpointRunId(body, summary),
      candidateRecordId: body.recordId,
      candidateName: checkpointCandidateName(body, summary),
      stepName: "resume-score-confirm",
      stepType: "checkpoint",
      status: "decided",
      inputSummary: `mode=${body.mode || "dry_run"}；VM 确认简历评估 checkpoint`,
      outputSummary: `写回字段：${confirmedFieldLabels.join("、")}`,
      decision: summaryText(summary)
    });
    return NextResponse.json({
      ok: true,
      data: {
        status: "confirmed",
        updatedFields: confirmedFieldLabels
      }
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "checkpoint 写回失败" },
      { status: 500 }
    );
  }
}
