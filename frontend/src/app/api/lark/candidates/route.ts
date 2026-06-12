import { NextResponse } from "next/server";
import { listCandidateResources } from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json({
      ok: true,
      data: {
        resources: listCandidateResources()
      }
    });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "Lark 候选人列表读取失败"
      },
      { status: 500 }
    );
  }
}
