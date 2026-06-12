import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ALLOWED_EXTENSIONS = new Set([".xlsx", ".pdf", ".docx"]);
const UPLOAD_DIR = "/tmp/loc-agent-console-uploads";

function safeFilename(name: string) {
  const parsed = path.parse(name);
  const base = parsed.name.replace(/[^\w\u4e00-\u9fa5.-]+/g, "_").slice(0, 80) || "attachment";
  const ext = parsed.ext.toLowerCase();
  return `${base}${ext}`;
}

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const file = formData.get("file");

  if (!(file instanceof File)) {
    return NextResponse.json({ ok: false, error: "没有收到附件文件。" }, { status: 400 });
  }

  const ext = path.extname(file.name).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return NextResponse.json({ ok: false, error: "仅支持 xlsx、pdf、docx 附件。" }, { status: 400 });
  }

  await mkdir(UPLOAD_DIR, { recursive: true });
  const filename = `${new Date().toISOString().replace(/[:.]/g, "-")}_${safeFilename(file.name)}`;
  const savedPath = path.join(UPLOAD_DIR, filename);
  const bytes = Buffer.from(await file.arrayBuffer());
  await writeFile(savedPath, bytes);

  return NextResponse.json({
    ok: true,
    filename: file.name,
    size: file.size,
    path: savedPath
  });
}
