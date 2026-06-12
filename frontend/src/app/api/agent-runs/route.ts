import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { NextRequest } from "next/server";
import { createEventFactory, planAgentRun, type AgentRunEvent, type AgentRunRequest } from "@/lib/agent-runner";

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
        `${dryRun ? "当前是 dry-run，未生成文件、未发送邮件、未写回飞书。" : "当前已执行合同生成动作。"} VM 确认后，正式流程会生成合同草稿/预览，并写入 workflow_log；发送合同仍需人工确认。`,
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
      writeback_fields_after_confirm: ["合同草稿文件", "workflow_log"]
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
  const validLine = outputText.match(/有效简历判定:\s*([^\n]+?)\s*（(.+?)）/);
  const dryRunLine = outputText.match(/\[DRY-RUN\]\s*record=([^\s]+)\s+总分=(\d+)\s+初始评级=([A-Z])/);
  const pdfLine = outputText.match(/PDF 解析成功（(\d+)字符）/);
  const evaluationSummary = outputText.match(
    /PDF\s+(\d+)\s+字符[\s\S]*?总分=([0-9.]+)\s+档位=([A-Z])\s+有效=([^\s]+)\s+字数来源=\[([^\]]+)\]\s+置信度=\[([^\]]+)\]/
  );
  const llmStructuredLine = outputText.match(/✅\s*字数=([^\s]+)\s+年限=([^\s]+)\s+项目数=([^\s]+)[\s\S]*?总分=([0-9.]+)\s+档位=([A-Z])\s+有效=([^\s]+)\s+字数来源=\[([^\]]+)\]\s+置信度=\[([^\]]+)\]/);
  const aiSuggestionLine = outputText.match(/AI建议=(.+)/);
  const commentLine = outputText.match(/点评=(.+)/);

  const totalScore = evaluationSummary?.[2] ?? llmStructuredLine?.[4] ?? scoreLine?.[6] ?? dryRunLine?.[2] ?? "未识别";
  const finalTier = evaluationSummary?.[3] ?? llmStructuredLine?.[5] ?? scoreLine?.[5] ?? dryRunLine?.[3] ?? "未识别";
  const initialTier = scoreLine?.[4] ?? finalTier;
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
      `${candidateName ?? "该候选人"} 的简历附件已完成下载、文本提取、LLM 结构化评估和评分${isDryRun ? "预览" : "写回"}：总分 ${totalScore}，评级 ${finalTier}，有效简历=${validResume}。\n` +
      `本次读取 record_id=${recordId}，PDF 文本 ${parsedChars} 字符；字数来源=${wordCountSource}，置信度=${confidence}。\n` +
      (isDryRun
        ? "VM 确认后，正式执行会写回 Lark 字段：解析字数、解析年限、解析项目数、总分、初始评级、评分依据、AI建议、点评、有效简历、评分置信度。"
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
      "解析字数",
      "解析年限",
      "解析项目数",
      "总分",
      "初始评级",
      "评分依据",
      "AI建议",
      "点评",
      "有效简历",
      "评分置信度"
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
            expected_root: process.env.LOC_AGENT_SKILL_ROOT ?? "/Users/dataozi/.agents/skills/loc-resume-screening"
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
        cwd: process.env.LOC_AGENT_SKILL_ROOT ?? "/Users/dataozi/.agents/skills/loc-resume-screening",
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
        if (code === 0) {
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
                recent_output: recentOutput,
                next: "请根据 stderr/stdout 修复配置、附件路径或 Lark 映射后重试。"
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
