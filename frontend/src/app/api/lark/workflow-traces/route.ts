import { NextResponse } from "next/server";
import { listWorkflowTraces } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const candidateRecordId = url.searchParams.get("candidateRecordId") ?? "";
    const candidateName = url.searchParams.get("candidateName") ?? "";
    const traces = listWorkflowTraces(200).filter((trace) => {
      if (candidateRecordId && trace.candidateRecordId === candidateRecordId) return true;
      if (candidateName && trace.candidateName && candidateName.includes(trace.candidateName)) return true;
      return false;
    });

    return NextResponse.json({
      ok: true,
      data: {
        traces
      }
    });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "workflow trace 读取失败"
      },
      { status: 500 }
    );
  }
}
