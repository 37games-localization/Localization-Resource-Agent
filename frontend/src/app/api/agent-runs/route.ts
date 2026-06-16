import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { NextRequest } from "next/server";
import type { AgentRunEvent, AgentRunRequest } from "@/lib/agent-runner";
import { getSkillRoot } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SKILL_ROOT = getSkillRoot();
const RUN_DIALOG = `${SKILL_ROOT}/scripts/run_dialog.py`;

type CliJsonlEvent = {
  type?: string;
  event_type?: string;
  run_id?: string;
  event_id?: string;
  ts?: string;
  source?: string;
  action?: string;
  step?: string;
  candidate?: { name?: string; record_id?: string };
  error?: { message?: string; code?: string; recoverable?: boolean; raw_output?: string };
  [key: string]: unknown;
};

function encodeEvent(event: AgentRunEvent) {
  return new TextEncoder().encode(`${JSON.stringify(event)}\n`);
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

function requestedCommand(request: AgentRunRequest) {
  const action = request.action;
  const commandByAction: Record<string, string> = {
    chat: "chat",
    "resume-evaluate": "score",
    score: "score",
    "test-email": "test-email",
    "test-email-mark-sent": "test-email-mark-sent",
    "contract-info-email": "contract-info-email",
    "contract-info-mark-sent": "contract-info-mark-sent",
    "contract-generate": "contract",
    "signed-contract-check": "signed-contract",
    "update-status": "update-status",
    "rejection-email": "rejection-email",
    "badcase": "badcase"
  };
  return action ? commandByAction[action] : "";
}

function locatorArgs(request: AgentRunRequest) {
  const locator = request.candidateLocator;
  if (!locator?.value) return [];
  if (locator.type === "record_id") return ["--record-id", locator.value];
  if (locator.type === "name" || locator.type === "nickname" || locator.type === "email") {
    return ["--name", locator.value];
  }
  return [];
}

function cliArgs(request: AgentRunRequest, runId: string) {
  const command = requestedCommand(request);
  if (!command) return [];
  const args = [RUN_DIALOG, command, "--jsonl", "--run-id", runId, ...locatorArgs(request)];
  if (command === "chat") {
    args.push("--message", request.message);
  }
  const attachment = request.attachments?.find(Boolean);
  if (attachment && (command === "test-email" || command === "signed-contract" || command === "chat")) {
    args.push("--file", attachment);
  }
  if (command === "update-status" && request.targetStatus) {
    args.push("--status", request.targetStatus);
  }
  return args;
}

function payloadFromCli(event: CliJsonlEvent) {
  const {
    type,
    event_type,
    run_id,
    event_id,
    ts,
    source,
    candidate,
    ...payload
  } = event;
  return payload;
}

function eventTypeFromCli(event: CliJsonlEvent): AgentRunEvent["event_type"] {
  const type = event.type ?? event.event_type;
  if (type === "tool_output") return "tool_call_output";
  if (type === "error") return "step_failed";
  return (type ?? "agent_message") as AgentRunEvent["event_type"];
}

function eventFromCli(event: CliJsonlEvent, fallbackRunId: string, sequence: number): AgentRunEvent {
  return {
    event_id: event.event_id || `evt_${String(sequence).padStart(4, "0")}`,
    run_id: event.run_id || fallbackRunId,
    event_type: eventTypeFromCli(event),
    timestamp: event.ts || new Date().toISOString(),
    candidate_record_id: event.candidate?.record_id,
    candidate_name: event.candidate?.name,
    step_name: typeof event.step === "string" ? event.step : undefined,
    payload: payloadFromCli(event)
  };
}

function systemEvent(
  runId: string,
  sequence: number,
  event_type: AgentRunEvent["event_type"],
  payload: Record<string, unknown>
): AgentRunEvent {
  return {
    event_id: `evt_sys_${String(sequence).padStart(4, "0")}`,
    run_id: runId,
    event_type,
    timestamp: new Date().toISOString(),
    payload
  };
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as AgentRunRequest;
  const runId = `run_${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}`;
  const args = cliArgs(body, runId);

  const stream = new ReadableStream({
    start(controller) {
      let sequence = 0;

      function send(event: AgentRunEvent) {
        controller.enqueue(encodeEvent(event));
      }

      function sendSystem(event_type: AgentRunEvent["event_type"], payload: Record<string, unknown>) {
        sequence += 1;
        send(systemEvent(runId, sequence, event_type, payload));
      }

      if (!existsSync(RUN_DIALOG)) {
        sendSystem("step_failed", {
          reason: "CLI 入口不存在，无法启动资源管理 Agent。",
          script: RUN_DIALOG,
          expected_root: SKILL_ROOT
        });
        sendSystem("run_done", { status: "failed" });
        controller.close();
        return;
      }

      if (args.length === 0) {
        sendSystem("step_failed", {
          reason: "当前前端请求没有提供可映射到 CLI 的固定 action。",
          next: "Thin GUI Wrapper 阶段 server 不做意图识别；请由前端按钮或 CLI chat 入口提供明确命令。"
        });
        sendSystem("run_done", { status: "failed" });
        controller.close();
        return;
      }

      const child = spawn("python3", args, {
        cwd: SKILL_ROOT,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1"
        }
      });
      let stdoutBuffer = "";
      let stderrBuffer = "";

      child.stdout.on("data", (chunk: Buffer) => {
        stdoutBuffer += chunk.toString("utf8");
        const lines = stdoutBuffer.split("\n");
        stdoutBuffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const cliEvent = JSON.parse(line) as CliJsonlEvent;
            sequence += 1;
            send(eventFromCli(cliEvent, runId, sequence));
          } catch {
            sequence += 1;
            send(
              systemEvent(runId, sequence, "tool_call_output", {
                stream: "stdout",
                text: redactSensitiveText(line)
              })
            );
          }
        }
      });

      child.stderr.on("data", (chunk: Buffer) => {
        const text = redactSensitiveText(chunk.toString("utf8"));
        stderrBuffer += text;
        sendSystem("tool_call_output", { stream: "stderr", text });
      });

      child.on("error", (error) => {
        sendSystem("step_failed", {
          reason: "CLI 进程启动失败。",
          error: error.message
        });
        sendSystem("run_done", { status: "failed" });
        controller.close();
      });

      child.on("close", (code) => {
        if (stdoutBuffer.trim()) {
          try {
            const cliEvent = JSON.parse(stdoutBuffer.trim()) as CliJsonlEvent;
            sequence += 1;
            send(eventFromCli(cliEvent, runId, sequence));
          } catch {
            sendSystem("tool_call_output", {
              stream: "stdout",
              text: redactSensitiveText(stdoutBuffer)
            });
          }
        }
        if (code !== 0) {
          sendSystem("step_failed", {
            reason: "CLI 进程返回非零退出码。",
            exit_code: code,
            stderr: stderrBuffer.slice(-2000)
          });
          sendSystem("run_done", { status: "failed" });
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
