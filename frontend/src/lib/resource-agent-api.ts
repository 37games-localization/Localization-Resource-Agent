import type { CandidateResource } from "@/lib/lark-data-access";

export type ApiResult<T> =
  | {
      ok: true;
      data: T;
    }
  | {
      ok: false;
      error: string;
    };

export type CandidateResourcesPayload = {
  resources: CandidateResource[];
};

export type LarkConfigTable = {
  key: string;
  label: string;
  purpose: string;
  baseToken: string;
  tableId: string;
  source?: string;
  sourceNote?: string;
  url: string;
  fieldCount: number;
  fields: Array<{
    key: string;
    fieldName: string;
    fieldId: string;
    expectedType: string;
  }>;
};

export type LarkConfigPayload = {
  configPath: string;
  mappingPath: string;
  tables: LarkConfigTable[];
};

export type WorkflowTraceEntry = {
  recordId: string;
  runId: string;
  candidateRecordId: string;
  candidateName: string;
  stepName: string;
  stepType: string;
  status: string;
  inputSummary: string;
  outputSummary: string;
  decision: string;
  createdAt: string;
};

export async function fetchCandidateResources(fetcher: typeof fetch = fetch) {
  const response = await fetcher("/api/lark/candidates", {
    cache: "no-store"
  });
  const payload = (await response.json()) as ApiResult<CandidateResourcesPayload>;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.ok ? "候选人列表读取失败" : payload.error);
  }
  return payload.data.resources;
}

export async function fetchLarkConfig(fetcher: typeof fetch = fetch) {
  const response = await fetcher("/api/lark/config", {
    cache: "no-store"
  });
  const payload = (await response.json()) as ApiResult<LarkConfigPayload>;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.ok ? "Lark 配置读取失败" : payload.error);
  }
  return payload.data;
}

export async function fetchWorkflowTraces(
  input: { candidateRecordId: string; candidateName: string },
  fetcher: typeof fetch = fetch
) {
  const params = new URLSearchParams();
  if (input.candidateRecordId) params.set("candidateRecordId", input.candidateRecordId);
  if (input.candidateName) params.set("candidateName", input.candidateName);
  const response = await fetcher(`/api/lark/workflow-traces?${params.toString()}`, {
    cache: "no-store"
  });
  const payload = (await response.json()) as ApiResult<{ traces: WorkflowTraceEntry[] }>;
  if (!response.ok || !payload.ok) {
    throw new Error(payload.ok ? "workflow trace 读取失败" : payload.error);
  }
  return payload.data.traces;
}
