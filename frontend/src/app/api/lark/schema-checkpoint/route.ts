import { spawnSync } from "node:child_process";
import { NextRequest, NextResponse } from "next/server";
import { getSkillRoot } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type SchemaCheckpointRequest = {
  action: "propose" | "adjust" | "confirm";
  token?: string;
  table?: "candidate" | "pricing_rules" | "workflow_log" | "contract_info" | "all";
  note?: string;
  set?: string[];
  createMissingFields?: boolean;
};

function runSchemaCheckpoint(args: string[]) {
  const skillRoot = getSkillRoot();
  const result = spawnSync("python3", [`${skillRoot}/scripts/schema_mapping_checkpoint.py`, ...args], {
    cwd: skillRoot,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    encoding: "utf8",
    timeout: 120_000
  });
  const stdout = result.stdout || "";
  const stderr = result.stderr || "";
  try {
    const payload = JSON.parse(stdout);
    return { ok: result.status === 0, payload, stderr };
  } catch {
    return {
      ok: false,
      payload: {
        status: "failed",
        message: "schema checkpoint 输出不是合法 JSON",
        stdout: stdout.slice(-4000),
        stderr: stderr.slice(-4000)
      },
      stderr
    };
  }
}

export async function POST(request: NextRequest) {
  const body = (await request.json()) as SchemaCheckpointRequest;
  const action = body.action || "propose";
  const args: string[] = [action, "--json"];

  if (action === "propose") {
    args.push("--table", body.table || "all");
    if (body.createMissingFields) args.push("--create-missing-fields", "--yes");
  }

  if (action === "adjust") {
    if (!body.token) {
      return NextResponse.json({ ok: false, error: "缺少 schema checkpoint token" }, { status: 400 });
    }
    args.push("--token", body.token);
    for (const item of body.set || []) args.push("--set", item);
    if (body.note) args.push("--note", body.note);
  }

  if (action === "confirm") {
    if (!body.token) {
      return NextResponse.json({ ok: false, error: "缺少 schema checkpoint token" }, { status: 400 });
    }
    args.push("--token", body.token);
  }

  const result = runSchemaCheckpoint(args);
  return NextResponse.json(
    {
      ok: result.ok,
      data: result.payload,
      error: result.ok ? "" : result.payload.message || result.stderr || "schema checkpoint 执行失败"
    },
    { status: result.ok ? 200 : 422 }
  );
}
