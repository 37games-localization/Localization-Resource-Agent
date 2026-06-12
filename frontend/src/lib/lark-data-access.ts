import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

export type LarkTableKey = "candidate" | "contract" | "workflowLog" | "pricingRules";

export type LarkRecord = {
  recordId: string;
  fields: Record<string, unknown>;
};

export type CandidateResource = {
  recordId: string;
  supplierId: string;
  name: string;
  nickname: string;
  email: string;
  languagePair: string;
  services: string;
  tier: string;
  score: string;
  priceScore: string;
  qualificationScore: string;
  status: string;
  aiSuggestion: string;
  validResume: string;
  scoreBasis: string;
  priceScoreBasis: string;
  qualificationScoreBasis: string;
  comment: string;
  parsedWordCount: string;
  parsedYears: string;
  parsedProjectCount: string;
  parsedKnownEntities: string;
  location: string;
  priceNegotiation: string;
  badcaseFlag: string;
  expectedResult: string;
  vmNote: string;
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

export type LarkRecordMatch = {
  match?: LarkRecord;
  matches: LarkRecord[];
  records: LarkRecord[];
};

export type LarkRecordLocator = {
  type: "record_id" | "name" | "nickname" | "email";
  value: string;
};

const DEFAULT_SKILL_ROOT = "/Users/dataozi/.agents/skills/loc-resume-screening";

export function getSkillRoot() {
  return process.env.LOC_AGENT_SKILL_ROOT ?? DEFAULT_SKILL_ROOT;
}

export function getSkillConfigPath() {
  const skillRoot = getSkillRoot();
  return (
    process.env.LOC_AGENT_CONFIG ??
    (existsSync(`${skillRoot}/config.local.yaml`) ? `${skillRoot}/config.local.yaml` : `${skillRoot}/config.yaml`)
  );
}

export function readConfigValue(key: string) {
  const configPath = getSkillConfigPath();
  if (!existsSync(configPath)) return "";
  const text = readFileSync(configPath, "utf8");
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = text.match(new RegExp(`^\\s*${escaped}:\\s*['"]?([^'"\\n#]+)['"]?`, "m"));
  return match?.[1]?.trim() ?? "";
}

function readMappedTableConfig(tableKey: string) {
  const mappingPath = `${getSkillRoot()}/config/lark-field-mapping.yaml`;
  if (!existsSync(mappingPath)) return { baseToken: "", tableId: "" };
  const text = readFileSync(mappingPath, "utf8");
  const escaped = tableKey.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const blockMatch = text.match(new RegExp(`^  ${escaped}:\\s*\\n([\\s\\S]*?)(?=^  [a-zA-Z0-9_]+:\\s*$|\\Z)`, "m"));
  const block = blockMatch?.[1] ?? "";
  return {
    baseToken: block.match(/^    base_token:\s*(.+)\s*$/m)?.[1]?.trim() ?? "",
    tableId: block.match(/^    table_id:\s*(.+)\s*$/m)?.[1]?.trim() ?? ""
  };
}

export function larkTableConfig(table: LarkTableKey) {
  if (table === "candidate") {
    const mapped = readMappedTableConfig("candidate");
    return {
      baseToken: readConfigValue("base_token") || mapped.baseToken,
      tableId: readConfigValue("resume_table_id") || mapped.tableId
    };
  }
  if (table === "contract") {
    const mapped = readMappedTableConfig("contract_info");
    return {
      baseToken: readConfigValue("contract_base_token") || mapped.baseToken || readConfigValue("base_token"),
      tableId: readConfigValue("contract_table_id") || mapped.tableId
    };
  }
  if (table === "workflowLog") {
    const mapped = readMappedTableConfig("workflow_log");
    return {
      baseToken: readConfigValue("log_base_token") || mapped.baseToken || readConfigValue("base_token"),
      tableId: readConfigValue("log_table_id") || mapped.tableId
    };
  }
  const mapped = readMappedTableConfig("pricing_rules");
  return {
    baseToken: readConfigValue("rules_base_token") || mapped.baseToken || readConfigValue("base_token"),
    tableId: readConfigValue("rules_table_id") || mapped.tableId
  };
}

export function textValue(value: unknown): string {
  if (typeof value === "string") return value.replace(/\[([^\]]+)\]\(mailto:[^)]+\)/g, "$1");
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string" || typeof item === "number") return String(item);
        if (item && typeof item === "object") {
          const objectValue = item as { text?: unknown; name?: unknown; id?: unknown; value?: unknown };
          return [objectValue.text, objectValue.name, objectValue.value, objectValue.id]
            .map((entry) => (entry ? String(entry) : ""))
            .filter(Boolean)
            .join(" ");
        }
        return "";
      })
      .filter(Boolean)
      .join(", ");
  }
  if (value && typeof value === "object") {
    const objectValue = value as { text?: unknown; name?: unknown; id?: unknown; value?: unknown };
    return [objectValue.text, objectValue.name, objectValue.value, objectValue.id]
      .map((entry) => (entry ? String(entry) : ""))
      .filter(Boolean)
      .join(" ");
  }
  return "";
}

export function pickField(fields: Record<string, unknown>, names: string[]) {
  for (const name of names) {
    const exact = fields[name];
    if (exact !== undefined) return textValue(exact);
    const fuzzy = Object.entries(fields).find(([field]) => field.includes(name));
    if (fuzzy) return textValue(fuzzy[1]);
  }
  return "";
}

function normalizeRecordList(payload: {
  data?: {
    fields?: string[];
    field_id_list?: string[];
    record_id_list?: string[];
    data?: unknown[][];
  };
}): LarkRecord[] {
  const fieldNames = payload.data?.fields ?? [];
  const fieldIds = payload.data?.field_id_list ?? [];
  const recordIds = payload.data?.record_id_list ?? [];
  const rows = payload.data?.data ?? [];
  return recordIds.map((recordId, index) => {
    const row = rows[index] ?? [];
    const fields: Record<string, unknown> = {};
    row.forEach((value, fieldIndex) => {
      const fieldName = fieldNames[fieldIndex];
      const fieldId = fieldIds[fieldIndex];
      if (fieldName) fields[fieldName] = value;
      if (fieldId) fields[fieldId] = value;
    });
    return { recordId, fields };
  });
}

export function listLarkRecords(table: LarkTableKey, limit = 100): LarkRecord[] {
  const cfg = larkTableConfig(table);
  if (!cfg.baseToken || !cfg.tableId) return [];
  const result = spawnSync(
    "lark-cli",
    [
      "base",
      "+record-list",
      "--base-token",
      cfg.baseToken,
      "--table-id",
      cfg.tableId,
      "--format",
      "json",
      "--limit",
      String(limit)
    ],
    { encoding: "utf8" }
  );
  if (result.status !== 0 || !result.stdout) {
    throw new Error(result.stderr || `Lark ${table} 表读取失败`);
  }
  return normalizeRecordList(JSON.parse(result.stdout));
}

export function toCandidateResource(record: LarkRecord): CandidateResource {
  const fields = record.fields;
  return {
    recordId: record.recordId,
    supplierId: pickField(fields, ["供应商编号", "供应商申请单号", "编号"]),
    name: pickField(fields, ["姓名"]),
    nickname: pickField(fields, ["昵称"]),
    email: pickField(fields, ["邮箱"]),
    languagePair: pickField(fields, ["语言对"]),
    services: pickField(fields, ["提供的服务"]),
    tier: pickField(fields, ["LLM初始评级", "初始评级"]),
    score: pickField(fields, ["Agent总分", "总分"]),
    priceScore: pickField(fields, ["LLM单价评分", "单价评分"]),
    qualificationScore: pickField(fields, ["LLM资历评分", "资历评分"]),
    status: pickField(fields, ["招募状态"]),
    aiSuggestion: pickField(fields, ["AI建议"]),
    validResume: pickField(fields, ["有效简历"]),
    scoreBasis: pickField(fields, ["LLM点评", "VM点评", "点评", "评分依据"]),
    priceScoreBasis: pickField(fields, ["LLM单价评分依据", "单价评分依据"]),
    qualificationScoreBasis: pickField(fields, ["LLM资历评分依据", "资历评分依据"]),
    comment: pickField(fields, ["LLM点评", "VM点评", "点评"]),
    parsedWordCount: pickField(fields, ["解析字数"]),
    parsedYears: pickField(fields, ["解析年限"]),
    parsedProjectCount: pickField(fields, ["解析项目数"]),
    parsedKnownEntities: pickField(fields, ["解析知名实体"]),
    location: pickField(fields, ["常居地和所在时区"]),
    priceNegotiation: pickField(fields, ["报价商议空间"]),
    badcaseFlag: pickField(fields, ["是否Badcase"]),
    expectedResult: pickField(fields, ["期望结果"]),
    vmNote: pickField(fields, ["VM备注"])
  };
}

export function listCandidateResources(limit = 100): CandidateResource[] {
  return listLarkRecords("candidate", limit).map(toCandidateResource);
}

export function toWorkflowTraceEntry(record: LarkRecord): WorkflowTraceEntry {
  const fields = record.fields;
  return {
    recordId: record.recordId,
    runId: pickField(fields, ["run_id"]),
    candidateRecordId: pickField(fields, ["candidate_record_id"]),
    candidateName: pickField(fields, ["candidate_name"]),
    stepName: pickField(fields, ["step_name"]),
    stepType: pickField(fields, ["step_type"]),
    status: pickField(fields, ["status"]),
    inputSummary: pickField(fields, ["input_summary"]),
    outputSummary: pickField(fields, ["output_summary"]),
    decision: pickField(fields, ["decision"]),
    createdAt: pickField(fields, ["created_at"])
  };
}

export function listWorkflowTraces(limit = 100): WorkflowTraceEntry[] {
  return listLarkRecords("workflowLog", limit).map(toWorkflowTraceEntry);
}

export function recordSearchTerms(record: LarkRecord, table: "candidate" | "contract") {
  const keywords =
    table === "candidate"
      ? ["姓名", "昵称", "邮箱", "编号"]
      : ["姓名", "邮箱", "自动编号", "关联简历"];
  return Object.entries(record.fields)
    .filter(([field]) => keywords.some((key) => field.includes(key)))
    .map(([, value]) => textValue(value))
    .filter(Boolean);
}

export function findLarkRecord(
  table: "candidate" | "contract",
  input: {
    message: string;
    locator?: LarkRecordLocator;
  }
): LarkRecordMatch {
  const records = listLarkRecords(table);
  const locatorValue = input.locator?.value?.trim();

  if (input.locator?.type === "record_id" && locatorValue?.startsWith("rec")) {
    const exactMatches = records.filter((record) => record.recordId === locatorValue);
    if (exactMatches.length > 0) {
      return {
        match: exactMatches.length === 1 ? exactMatches[0] : undefined,
        matches: exactMatches,
        records
      };
    }
  }

  const query = locatorValue || input.message;
  const matches = records.filter((record) =>
    recordSearchTerms(record, table).some((term) => term && (query.includes(term) || term.includes(query)))
  );
  return { match: matches.length === 1 ? matches[0] : undefined, matches, records };
}
