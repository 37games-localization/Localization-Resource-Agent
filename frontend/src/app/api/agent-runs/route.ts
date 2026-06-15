import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { NextRequest } from "next/server";
import { createEventFactory, planAgentRun, type AgentRunEvent, type AgentRunRequest } from "@/lib/agent-runner";
import { readConfigNestedValue } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function encodeEvent(event: AgentRunEvent) {
  return new TextEncoder().encode(`${JSON.stringify(event)}\n`);
}

function safeCommandForDisplay(script: string, args: string[]) {
  return ["python3", script, ...args].join(" ");
}

function redactSensitiveText(text: string) {
  return text
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, (email) => {
      const [name, domain] = email.split("@");
      return `${name.slice(0, 2)}***@${domain}`;
    })
    .replace(/\b\d{6}(?:19|20)\d{2}\d{2}\d{2}\d{3}[\dXx]\b/g, "[证件号已脱敏]")
    .replace(/\b(?:\d[ -]?){12,22}\b/g, "[银行账号已脱敏]")
    .replace(/(乙方地址\s*→\s*).+/g, "$1[个人地址已脱敏]");
}

function numberFromConfig(section: string, key: string) {
  const raw = readConfigNestedValue(section, key);
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

function configuredLlmInfo() {
  return {
    provider: readConfigNestedValue("llm", "provider") || "unknown",
    model: readConfigNestedValue("llm", "model") || "unknown",
    inputUsdPerMillion:
      numberFromConfig("llm", "input_cost_per_1m_usd") ??
      numberFromConfig("llm", "input_cost_usd_per_1m"),
    outputUsdPerMillion:
      numberFromConfig("llm", "output_cost_per_1m_usd") ??
      numberFromConfig("llm", "output_cost_usd_per_1m"),
    cnyPerUsd: numberFromConfig("llm", "cny_per_usd") ?? 7.2
  };
}

function estimateTokensFromChars(chars: number) {
  if (!Number.isFinite(chars) || chars <= 0) return 0;
  return Math.ceil(chars / 2.2);
}

function parseUsageFromOutput(outputText: string) {
  const promptTokens =
    outputText.match(/["']prompt_tokens["']\s*:\s*(\d+)/)?.[1] ??
    outputText.match(/["']input_tokens["']\s*:\s*(\d+)/)?.[1] ??
    outputText.match(/\binput_tokens\s*[=:]\s*(\d+)/i)?.[1];
  const completionTokens =
    outputText.match(/["']completion_tokens["']\s*:\s*(\d+)/)?.[1] ??
    outputText.match(/["']output_tokens["']\s*:\s*(\d+)/)?.[1] ??
    outputText.match(/\boutput_tokens\s*[=:]\s*(\d+)/i)?.[1];
  if (!promptTokens && !completionTokens) return undefined;
  return {
    inputTokens: Number(promptTokens ?? 0),
    outputTokens: Number(completionTokens ?? 0)
  };
}

function estimateAiUsage({
  action,
  outputText,
  message,
  runId,
  candidateName,
  candidateRecordId
}: {
  action: string;
  outputText: string;
  message: string;
  runId: string;
  candidateName?: string;
  candidateRecordId?: string;
}) {
  const llm = configuredLlmInfo();
  const apiUsage = parseUsageFromOutput(outputText);
  const hasLlmSignal =
    action === "score" ||
    /LLM|OpenAI-compatible|DeepSeek|Claude|GPT|解析简历|PDF\s+\d+\s+字符/i.test(outputText);
  const parsedPdfChars = Number(outputText.match(/PDF\s+(\d+)\s+字符/)?.[1] ?? outputText.match(/PDF 解析成功（(\d+)字符）/)?.[1]);
  const estimatedInputChars = Number.isFinite(parsedPdfChars)
    ? Math.min(parsedPdfChars, 8000) + 1200
    : message.length + 1200;
  const estimatedOutputChars = Math.min(outputText.length, 4000);
  const inputTokens = apiUsage?.inputTokens ?? (hasLlmSignal ? estimateTokensFromChars(estimatedInputChars) : 0);
  const outputTokens = apiUsage?.outputTokens ?? (hasLlmSignal ? estimateTokensFromChars(estimatedOutputChars) : 0);
  const totalTokens = inputTokens + outputTokens;
  const canPrice = llm.inputUsdPerMillion !== undefined && llm.outputUsdPerMillion !== undefined;
  const costUsd = canPrice
    ? (inputTokens / 1_000_000) * llm.inputUsdPerMillion! + (outputTokens / 1_000_000) * llm.outputUsdPerMillion!
    : undefined;

  return {
    run_id: runId,
    candidate_name: candidateName,
    candidate_record_id: candidateRecordId,
    action,
    provider: llm.provider,
    model: llm.model,
    usage_source: apiUsage ? "api_returned" : hasLlmSignal ? "estimated" : "not_applicable",
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: totalTokens,
    cost_usd: costUsd === undefined ? null : Number(costUsd.toFixed(6)),
    cost_cny: costUsd === undefined ? null : Number((costUsd * llm.cnyPerUsd).toFixed(4)),
    input_cost_per_1m_usd: llm.inputUsdPerMillion ?? null,
    output_cost_per_1m_usd: llm.outputUsdPerMillion ?? null,
    pricing_status: canPrice ? "priced" : hasLlmSignal ? "missing_unit_price" : "not_applicable",
    note: canPrice
      ? "成本按 config.local.yaml 中 llm 单价估算。"
      : hasLlmSignal
        ? "已统计 token；未配置 llm.input_cost_per_1m_usd / output_cost_per_1m_usd，因此不估算金额。"
        : "本步骤未检测到 LLM 调用信号，AI token 记为 0。"
  };
}

type BusinessResult =
  | { status: "success"; reason?: string; error_type?: string }
  | { status: "failed" | "partial_failed"; reason: string; error_type: string; next: string };

function analyzeBusinessResult(outputText: string): BusinessResult {
  const normalized = outputText.replace(/\r/g, "");

  const summary =
    normalized.match(/(?:全部)?完成：成功\s*(\d+)\s*\|\s*跳过\s*(\d+)\s*\|\s*失败\s*(\d+)/) ??
    normalized.match(/完成：成功\s*(\d+)\s*\|\s*跳过\s*(\d+)\s*\|\s*失败\s*(\d+)/);
  if (summary) {
    const ok = Number(summary[1]);
    const failed = Number(summary[3]);
    if (failed > 0 && ok === 0) {
      return {
        status: "failed",
        reason: `脚本进程已结束，但业务结果为失败：成功 ${ok}，失败 ${failed}。`,
        error_type: "business_summary_failed",
        next: "请先处理上方 tool 输出中的失败原因；系统不会生成成功 checkpoint 或继续推进。"
      };
    }
    if (failed > 0) {
      return {
        status: "partial_failed",
        reason: `脚本进程已结束，但业务结果为部分失败：成功 ${ok}，失败 ${failed}。`,
        error_type: "business_summary_partial_failed",
        next: "请复核失败记录；本次不会生成统一成功 checkpoint。"
      };
    }
  }

  const failurePatterns: Array<[RegExp, string]> = [
    [/LLM\s*返回失败|调用异常.*LLM|OpenAI-compatible LLM HTTP|invalid_api_key|Authentication Fails/i, "llm_call_failed"],
    [/重试\s*\d+\s*次(?:均)?失败|尝试\s*\d+\s*次失败/i, "retry_failed"],
    [/表结构读取失败|not_found|缺失字段/i, "lark_schema_failed"],
    [/未找到\s*(?:record_id|姓名|候选人)|候选人主表未找到|合同信息表未找到/i, "record_resolve_failed"]
  ];
  for (const [pattern, errorType] of failurePatterns) {
    if (pattern.test(normalized)) {
      return {
        status: "failed",
        reason: "脚本输出中包含明确失败信号，不能按成功流程继续。",
        error_type: errorType,
        next: "请根据失败信号修复配置、LLM key、Lark 映射或候选人定位后重试。"
      };
    }
  }

  return { status: "success" };
}

function buildCheckpointPayload(
  action: string,
  fallback: { title: string; detail: string },
  outputText: string,
  runId: string,
  requestedMode: string,
  effectiveMode: string,
  candidateName?: string,
  candidateRecordId?: string
) {
  const isDryRun = effectiveMode === "dry_run";
  if (action === "test-email") {
    const recipient = outputText.match(/收件人：(.+)/)?.[1]?.trim() ?? "未识别";
    const attachment = outputText.match(/附\s+件：(.+)/)?.[1]?.trim() ?? "未识别";
    const subject = outputText.match(/主\s+题：(.+)/)?.[1]?.trim() ?? "未识别";
    const testModeRecipient = outputText.match(/实际发到：(.+?)（/)?.[1]?.trim();
    const dryRun = isDryRun || outputText.includes("[DRY-RUN]");

    return {
      title: "测试题邮件待确认",
      detail:
        `${candidateName ?? "该候选人"} 的测试题邮件已生成预览：主题「${subject}」，附件「${attachment}」。\n` +
        `当前收件人显示为 ${recipient}${testModeRecipient ? `；TEST_MODE 实际会发到 ${testModeRecipient}` : ""}。\n` +
        `${dryRun ? "当前是 dry-run，未发送邮件、未写回飞书。" : "当前已执行发送动作。"} VM 确认后，正式流程会发送/生成草稿，并写回 Lark 字段：招募状态、测试发送时间、workflow_log。`,
      required: true,
      summary: {
        run_id: runId,
        requested_mode: requestedMode,
        execution_mode: effectiveMode,
        candidate_name: candidateName,
        candidate_record_id: candidateRecordId,
        subject,
        recipient,
        test_mode_recipient: testModeRecipient,
        attachment,
        dry_run: dryRun,
        email_sent: !dryRun
      },
      writeback_fields_after_confirm: ["招募状态", "测试发送时间", "workflow_log"]
    };
  }

  if (action === "contract-generate") {
    const contractRecordId = outputText.match(/=== 候选人：.+?\s+\((rec[^)]+)\)/)?.[1] ?? "未识别";
    const selectedTemplate = outputText.match(/已选模板：(.+)/)?.[1]?.trim() ?? "未识别";
    const requiredVars = outputText.match(/所需变量（(\d+) 个）/)?.[1] ?? "未识别";
    const filledVars = outputText.match(/已成功填充（(\d+) 个）/)?.[1] ?? "未识别";
    const bankNameWarning = outputText.match(/银行账户名：(.+)/)?.[1]?.trim();
    const dryRun = isDryRun || outputText.includes("[DRY-RUN]");

    return {
      title: "合同草稿待确认",
      detail:
        `${candidateName ?? "该候选人"} 的合同信息已完成 dry-run 检查：使用合同信息表 record_id=${contractRecordId}。\n` +
        `已选择模板「${selectedTemplate}」，变量填充 ${filledVars}/${requiredVars}。${bankNameWarning ? `风险提示：${bankNameWarning}。` : ""}\n` +
        `${dryRun ? "当前是 dry-run，未生成文件、未发送邮件、未写回飞书。" : "当前已执行合同生成动作。"} VM 确认后，正式流程会生成合同草稿/预览，并写入 workflow_log；合同 docx 不回传 Lark，发送合同仍需人工确认。`,
      required: true,
      summary: {
        run_id: runId,
        requested_mode: requestedMode,
        execution_mode: effectiveMode,
        candidate_name: candidateName,
        candidate_record_id: candidateRecordId,
        contract_record_id: contractRecordId,
        selected_template: selectedTemplate,
        required_variables: requiredVars,
        filled_variables: filledVars,
        warning: bankNameWarning,
        dry_run: dryRun,
        contract_file_generated: !dryRun
      },
      writeback_fields_after_confirm: ["workflow_log", "合同编号/签约状态（后续节点）"]
    };
  }

  if (action !== "score") {
    return {
      title: fallback.title,
      detail: fallback.detail,
      required: true,
      summary: {
        run_id: runId,
        requested_mode: requestedMode,
        execution_mode: effectiveMode,
        candidate_name: candidateName,
        candidate_record_id: candidateRecordId,
        dry_run: isDryRun
      }
    };
  }

  const scoreLine = outputText.match(/价格:\s*(\d+\/\d+)\s+资历:\s*(\d+\/\d+)\s+微调:\s*([+-]?\d+)\s+初始档:\s*([A-Z])\s*→\s*最终档:\s*([A-Z])\s+总分:\s*(\d+)/);
  const v2ScoreLine = outputText.match(/总分:\s*([0-9.]+)\/100\s+档位:\s*([A-Z])\s*→\s*([A-Z])\s+价格:\s*(\d+\/\d+)\s+资历:\s*(\d+\/\d+)\s+微调:\s*([+-]?\d+)/);
  const validLine = outputText.match(/有效简历判定:\s*([^\n]+?)\s*（(.+?)）/);
  const dryRunLine = outputText.match(/\[DRY-RUN\]\s*record=([^\s]+)\s+总分=(\d+)\s+初始评级=([A-Z])/);
  const pdfLine = outputText.match(/PDF 解析成功（(\d+)字符）/);
  const evaluationSummary = outputText.match(
    /PDF\s+(\d+)\s+字符[\s\S]*?总分=([0-9.]+)\s+档位=([A-Z])\s+有效=([^\s]+)\s+字数来源=\[([^\]]+)\]\s+置信度=\[([^\]]+)\]/
  );
  const llmStructuredLine = outputText.match(/✅\s*字数=([^\s]+)\s+年限=([^\s]+)\s+项目数=([^\s]+)[\s\S]*?总分=([0-9.]+)\s+档位=([A-Z])\s+有效=([^\s]+)\s+字数来源=\[([^\]]+)\]\s+置信度=\[([^\]]+)\]/);
  const aiSuggestionLine = outputText.match(/AI建议[:=]\s*(.+)/);
  const commentLine = outputText.match(/点评[:=]\s*(.+)/);

  const totalScore = evaluationSummary?.[2] ?? llmStructuredLine?.[4] ?? v2ScoreLine?.[1] ?? scoreLine?.[6] ?? dryRunLine?.[2] ?? "未识别";
  const finalTier = evaluationSummary?.[3] ?? llmStructuredLine?.[5] ?? v2ScoreLine?.[3] ?? scoreLine?.[5] ?? dryRunLine?.[3] ?? "未识别";
  const initialTier = v2ScoreLine?.[2] ?? scoreLine?.[4] ?? finalTier;
  const validResume = evaluationSummary?.[4] ?? llmStructuredLine?.[6] ?? validLine?.[1]?.trim() ?? "未识别";
  const evidence = validLine?.[2]?.trim() ?? "未识别";
  const parsedChars = evaluationSummary?.[1] ?? pdfLine?.[1] ?? "未识别";
  const recordId = dryRunLine?.[1] ?? candidateRecordId ?? "未识别";
  const wordCountSource = evaluationSummary?.[5] ?? llmStructuredLine?.[7] ?? "未识别";
  const confidence = evaluationSummary?.[6] ?? llmStructuredLine?.[8] ?? "未识别";
  const extractedWordCount = llmStructuredLine?.[1] ?? "未识别";
  const years = llmStructuredLine?.[2] ?? "未识别";
  const projectCount = llmStructuredLine?.[3] ?? "未识别";
  const aiSuggestion = aiSuggestionLine?.[1]?.trim() ?? "未识别";
  const comment = commentLine?.[1]?.trim() ?? "未识别";

  return {
    title: "简历评估结果待确认",
    detail:
      `${candidateName ?? "该候选人"} 的简历评估节点已完成${isDryRun ? "预览" : "写回"}：总分 ${totalScore}，评级 ${finalTier}，有效简历=${validResume}。\n` +
      `本次读取 record_id=${recordId}，PDF 文本 ${parsedChars} 字符；字数来源=${wordCountSource}，置信度=${confidence}。\n` +
      (isDryRun
        ? "VM 确认后，正式执行会写回 Lark 字段：总分、初始评级、评分依据、AI建议、有效简历和 workflow_log。"
        : "本次已由底层脚本按 production 写回评分字段；该 checkpoint 只用于复核和审计留痕。"),
    required: true,
    summary: {
      run_id: runId,
      requested_mode: requestedMode,
      execution_mode: effectiveMode,
      candidate_name: candidateName,
      candidate_record_id: recordId,
      total_score: totalScore,
      final_tier: finalTier,
      initial_tier: initialTier,
      valid_resume: validResume,
      parsed_pdf_chars: parsedChars,
      extracted_word_count: extractedWordCount,
      years,
      project_count: projectCount,
      word_count_source: wordCountSource,
      confidence,
      ai_suggestion: aiSuggestion,
      comment,
      evidence
    },
    writeback_fields_after_confirm: [
      "总分",
      "初始评级",
      "评分依据",
      "AI建议",
      "有效简历",
      "workflow_log"
    ]
  };
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as AgentRunRequest;
  const runId = `run_${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`;
  const plan = planAgentRun(body);
  const event = createEventFactory(runId, plan);

  const stream = new ReadableStream({
    start(controller) {
      const recentOutput: Array<{ stream: "stdout" | "stderr"; text: string }> = [];
      const outputChunks: string[] = [];

      function send(nextEvent: AgentRunEvent) {
        controller.enqueue(encodeEvent(nextEvent));
      }

      function rememberOutput(stream: "stdout" | "stderr", text: string) {
        recentOutput.push({ stream, text });
        if (recentOutput.length > 8) recentOutput.shift();
      }

      send(
        event("run_started", {
          message: body.message,
          mode: plan.effectiveMode,
          requested_mode: plan.requestedMode,
          execution_mode: plan.effectiveMode,
          mode_note: plan.modeNote,
          note: "本次执行由后端适配层调用现有 Agent 脚本，前端只展示真实事件。"
        })
      );

      if (plan.action === "unknown") {
        send(
          event("step_failed", {
            reason: "无法从 VM 指令中识别要执行的单点动作。",
            next: "请明确说明：评分、发测试题、准备合同、检查签字合同、推进状态或导出 Badcase。"
          })
        );
        send(event("run_done", { status: "failed" }));
        controller.close();
        return;
      }

      send(
        event("candidate_resolved", {
          candidate_name: plan.candidateName ?? "未从指令中识别姓名",
          candidate_record_id: plan.candidateRecordId ?? "未提供 record_id",
          locator_policy: "优先 record_id，其次姓名/昵称/邮箱；若多条命中，生产版必须暂停让 VM 选择。"
        })
      );

      if (plan.validationErrors && plan.validationErrors.length > 0) {
        send(
          event("step_failed", {
            reason: "执行前置条件不满足。",
            validation_errors: plan.validationErrors,
            next: "请补充候选人定位、附件路径或目标状态后重试；系统不会用猜测结果继续执行。"
          })
        );
        send(event("run_done", { status: "failed" }));
        controller.close();
        return;
      }

      if (!plan.script || !existsSync(plan.script)) {
        send(
          event("step_failed", {
            reason: "现有 Agent 脚本不存在或路径不可访问。",
            script: plan.script,
            expected_root: process.env.LOC_AGENT_SKILL_ROOT ?? "~/.agents/skills/loc-resume-screening"
          })
        );
        send(event("run_done", { status: "failed" }));
        controller.close();
        return;
      }

      for (const warning of plan.warnings ?? []) {
        send(event("warning", { message: warning }, plan.action));
      }

      send(
        event(
          "step_started",
          {
            action: plan.action,
            source: "existing_agent_script",
            workflow_version: plan.workflowVersion,
            script_role: plan.scriptRole,
            is_legacy: plan.isLegacy ?? false,
            note: "本步骤只调用现有脚本，不在前端或 API 层重写业务逻辑。"
          },
          plan.action
        )
      );

      send(
        event(
          "step_input",
          {
            script: plan.script,
            args: plan.args,
            command_preview: safeCommandForDisplay(plan.script, plan.args),
            workflow_version: plan.workflowVersion,
            script_role: plan.scriptRole,
            is_legacy: plan.isLegacy ?? false,
            safety:
              plan.effectiveMode === "dry_run"
                ? "当前实际执行为 dry-run：不会发送邮件、不会写业务主表、不会生成正式合同文件。"
                : "当前实际执行为 production：底层脚本可能写回业务主表；事件流会按真实副作用展示。"
          },
          plan.action
        )
      );

      send(
        event(
          "tool_call_started",
          {
            tool: "existing_agent_script",
            command_preview: safeCommandForDisplay(plan.script, plan.args)
          },
          plan.action
        )
      );

      const child = spawn("python3", [plan.script, ...plan.args], {
        cwd: process.env.LOC_AGENT_SKILL_ROOT ?? `${process.env.HOME || "~"}/.agents/skills/loc-resume-screening`,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1"
        }
      });

      child.stdout.on("data", (chunk: Buffer) => {
        const text = redactSensitiveText(chunk.toString("utf8"));
        outputChunks.push(text);
        rememberOutput("stdout", text);
        send(event("tool_call_output", { stream: "stdout", text }, plan.action));
      });

      child.stderr.on("data", (chunk: Buffer) => {
        const text = redactSensitiveText(chunk.toString("utf8"));
        outputChunks.push(text);
        rememberOutput("stderr", text);
        send(event("tool_call_output", { stream: "stderr", text }, plan.action));
      });

      child.on("error", (error) => {
        send(event("step_failed", { reason: error.message }, plan.action));
        send(event("run_done", { status: "failed" }));
        controller.close();
      });

      child.on("close", (code) => {
        const outputText = outputChunks.join("");
        const businessResult = analyzeBusinessResult(outputText);
        send(
          event(
            "usage_report",
            estimateAiUsage({
              action: plan.action,
              outputText,
              message: body.message,
              runId,
              candidateName: plan.candidateName,
              candidateRecordId: plan.candidateRecordId
            }),
            plan.action
          )
        );
        if (code === 0 && businessResult.status === "success") {
          send(
            event(
              "step_done",
              {
                exit_code: code,
                requested_mode: plan.requestedMode,
                execution_mode: plan.effectiveMode,
                business_writeback: plan.effectiveMode === "production" && plan.action === "score",
                email_sent: plan.effectiveMode === "production" && plan.action === "test-email",
                contract_file_generated: plan.effectiveMode === "production" && plan.action === "contract-generate"
              },
              plan.action
            )
          );
          if (plan.checkpointAfterSuccess) {
            send(
              event(
                "checkpoint",
                buildCheckpointPayload(
                  plan.action,
                  plan.checkpointAfterSuccess,
                  outputChunks.join(""),
                  runId,
                  plan.requestedMode,
                  plan.effectiveMode,
                  plan.candidateName,
                  plan.candidateRecordId
                ),
                plan.action
              )
            );
          }
          send(event("run_done", { status: "done" }));
        } else {
          send(
            event(
              "step_failed",
              {
                exit_code: code,
                business_status: businessResult.status,
                reason:
                  businessResult.status === "success"
                    ? "脚本进程返回非零退出码。"
                    : businessResult.reason,
                error_type:
                  businessResult.status === "success"
                    ? "process_exit_failed"
                    : businessResult.error_type,
                recent_output: recentOutput,
                next:
                  businessResult.status === "success"
                    ? "请根据 stderr/stdout 修复配置、附件路径或 Lark 映射后重试。"
                    : businessResult.next
              },
              plan.action
            )
          );
          send(event("run_done", { status: "failed" }));
        }
        controller.close();
      });
    }
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-cache, no-transform"
    }
  });
}
