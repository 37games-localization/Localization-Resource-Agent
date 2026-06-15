import { spawnSync } from "node:child_process";
import { NextResponse } from "next/server";
import { larkTableConfig } from "@/lib/lark-data-access";

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
  upsertRecord("workflowLog", {
    run_id: fields.runId,
    candidate_record_id: fields.candidateRecordId,
    candidate_name: fields.candidateName || "",
    step_name: fields.stepName,
    step_type: fields.stepType,
    status: fields.status,
    input_summary: fields.inputSummary,
    output_summary: fields.outputSummary,
    decision: fields.decision,
    created_at: larkDatetime()
  });
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

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return undefined;
  const normalized = value.replace(/,/g, "").trim();
  const match = normalized.match(/[+-]?\d+(?:\.\d+)?/);
  if (!match) return undefined;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) ? parsed : undefined;
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
      updateCandidate(body.recordId, {
        "初始评级": body.rating || "A",
        "AI建议": body.aiSuggestion || "人工复核",
        "是否Badcase": "⚠️ 是",
        "期望结果": body.reason,
        "招募状态": "初筛中"
      });
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
          updatedFields: ["初始评级", "AI建议", "Badcase 标记", "期望结果"]
        }
      });
    }

    if (!summary.total_score || !summary.final_tier) {
      return NextResponse.json(
        { ok: false, error: "简历评估 checkpoint 缺少总分或评级，不能写回" },
        { status: 400 }
      );
    }
    const confirmedFields: Record<string, unknown> = {
      "招募状态": "初筛通过",
      "是否Badcase": null,
      "期望结果": null
    };

    const totalScore = numberValue(summary.total_score);
    if (totalScore !== undefined) confirmedFields["Agent总分"] = totalScore;
    if (summary.final_tier) confirmedFields["初始评级"] = summary.final_tier;
    if (summary.ai_suggestion) confirmedFields["AI建议"] = summary.ai_suggestion;
    if (summary.comment) confirmedFields["点评"] = summary.comment;
    if (summary.valid_resume) confirmedFields["有效简历"] = summary.valid_resume;
    const wordCount = numberValue(summary.extracted_word_count);
    if (wordCount !== undefined) confirmedFields["解析字数"] = wordCount;
    const years = numberValue(summary.years);
    if (years !== undefined) confirmedFields["解析年限"] = years;
    const projectCount = numberValue(summary.project_count);
    if (projectCount !== undefined) confirmedFields["解析项目数"] = projectCount;

    updateCandidate(body.recordId, confirmedFields);
    writeWorkflowLog({
      runId: checkpointRunId(body, summary),
      candidateRecordId: body.recordId,
      candidateName: checkpointCandidateName(body, summary),
      stepName: "resume-score-confirm",
      stepType: "checkpoint",
      status: "decided",
      inputSummary: `mode=${body.mode || "dry_run"}；VM 确认简历评估 checkpoint`,
      outputSummary: `写回字段：${Object.keys(confirmedFields).join("、")}`,
      decision: summaryText(summary)
    });
    return NextResponse.json({
      ok: true,
      data: {
        status: "confirmed",
        updatedFields: Object.keys(confirmedFields)
      }
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "checkpoint 写回失败" },
      { status: 500 }
    );
  }
}
