import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { NextResponse } from "next/server";
import type { AgentRunEvent } from "@/lib/agent-runner";
import { getSkillRoot } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type CheckpointRequest = {
  checkpointToken?: string;
  action?: "confirm" | "modify" | "skip" | "exit";
  rating?: string;
  aiSuggestion?: string;
  reason?: string;
  runId?: string;
};

type CliJsonlEvent = {
  type?: string;
  event_type?: string;
  run_id?: string;
  event_id?: string;
  ts?: string;
  source?: string;
  candidate?: { name?: string; record_id?: string };
  [key: string]: unknown;
};

const SKILL_ROOT = getSkillRoot();
const RUN_DIALOG = `${SKILL_ROOT}/scripts/run_dialog.py`;

function eventTypeFromCli(event: CliJsonlEvent): AgentRunEvent["event_type"] {
  const type = event.type ?? event.event_type;
  if (type === "tool_output") return "tool_call_output";
  if (type === "error") return "step_failed";
  return (type ?? "agent_message") as AgentRunEvent["event_type"];
}

function payloadFromCli(event: CliJsonlEvent) {
  const { type, event_type, run_id, event_id, ts, source, candidate, ...payload } = event;
  return payload;
}

function eventFromCli(event: CliJsonlEvent, fallbackRunId: string, sequence: number): AgentRunEvent {
  return {
    event_id: event.event_id || `evt_checkpoint_${String(sequence).padStart(4, "0")}`,
    run_id: event.run_id || fallbackRunId,
    event_type: eventTypeFromCli(event),
    timestamp: event.ts || new Date().toISOString(),
    candidate_record_id: event.candidate?.record_id,
    candidate_name: event.candidate?.name,
    step_name: typeof event.step === "string" ? event.step : undefined,
    payload: payloadFromCli(event)
  };
}

function decisionFromRequest(body: CheckpointRequest) {
  if (body.action === "skip") return "跳过";
  if (body.action === "exit") return "退出";
  if (body.action === "modify") {
    return JSON.stringify({
      action: "modify",
      rating: body.rating,
      aiSuggestion: body.aiSuggestion,
      reason: body.reason
    });
  }
  return "写入";
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as CheckpointRequest;
    const token = body.checkpointToken;
    if (!token?.startsWith("ckpt-")) {
      return NextResponse.json({ ok: false, error: "缺少有效 checkpoint token" }, { status: 400 });
    }
    if (body.action === "modify" && !body.reason?.trim()) {
      return NextResponse.json({ ok: false, error: "修改结果必须填写调整原因" }, { status: 400 });
    }
    if (!existsSync(RUN_DIALOG)) {
      return NextResponse.json({ ok: false, error: `CLI 入口不存在：${RUN_DIALOG}` }, { status: 500 });
    }

    const runId = body.runId || `run_checkpoint_${Date.now()}`;
    const args = [
      RUN_DIALOG,
      "resume",
      "--jsonl",
      "--run-id",
      runId,
      "--token",
      token,
      "--decision",
      decisionFromRequest(body)
    ];

    const events: AgentRunEvent[] = [];
    const child = spawn("python3", args, {
      cwd: SKILL_ROOT,
      env: { ...process.env, PYTHONUNBUFFERED: "1" }
    });

    let stdout = "";
    let stderr = "";
    const code = await new Promise<number | null>((resolve, reject) => {
      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", reject);
      child.on("close", resolve);
    });

    stdout
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .forEach((line, index) => {
        try {
          events.push(eventFromCli(JSON.parse(line) as CliJsonlEvent, runId, index + 1));
        } catch {
          events.push({
            event_id: `evt_checkpoint_stdout_${index + 1}`,
            run_id: runId,
            event_type: "tool_call_output",
            timestamp: new Date().toISOString(),
            payload: { stream: "stdout", text: line }
          });
        }
      });

    if (code !== 0) {
      return NextResponse.json(
        {
          ok: false,
          error: stderr || "CLI checkpoint resume 执行失败",
          data: { events }
        },
        { status: 500 }
      );
    }

    return NextResponse.json({ ok: true, data: { events } });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "checkpoint resume 失败" },
      { status: 500 }
    );
  }
}
