import { existsSync, readFileSync } from "node:fs";
import { NextResponse } from "next/server";
import {
  getSkillConfigPath,
  getSkillRoot,
  larkTableConfig,
  readConfigNestedValue,
  readConfigValue
} from "@/lib/lark-data-access";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type MappingTable = {
  baseToken: string;
  tableId: string;
  fields: Array<{
    key: string;
    fieldName: string;
    fieldId: string;
    expectedType: string;
  }>;
};

const LARK_BASE_HOST = "https://g4wt0dn9mss.sg.larksuite.com/base";

function tableUrl(baseToken: string, tableId: string) {
  if (!baseToken || !tableId) return "";
  return `${LARK_BASE_HOST}/${baseToken}?table=${tableId}`;
}

function resolvePricingRulesTable(mapping: Record<string, MappingTable>, candidateBaseToken: string) {
  const pricingBase = readConfigNestedValue("pricing_rules", "base_token");
  const pricingTable = readConfigNestedValue("pricing_rules", "table_id");
  if (pricingBase || pricingTable) {
    return {
      baseToken: pricingBase,
      tableId: pricingTable,
      source: "pricing_rules.base_token/table_id",
      sourceNote: "独立评分规则配置表"
    };
  }

  const legacyBase = readConfigValue("rules_base_token");
  const legacyTable = readConfigValue("rules_table_id");
  if (legacyBase || legacyTable) {
    return {
      baseToken: legacyBase || candidateBaseToken,
      tableId: legacyTable,
      source: legacyBase ? "lark.rules_base_token/rules_table_id" : "lark.rules_table_id",
      sourceNote: "兼容旧配置"
    };
  }

  const mapped = mapping.pricing_rules;
  if (mapped?.baseToken || mapped?.tableId) {
    return {
      baseToken: mapped.baseToken,
      tableId: mapped.tableId,
      source: "config/lark-field-mapping.yaml",
      sourceNote: "字段映射生成结果"
    };
  }

  return {
    baseToken: candidateBaseToken,
    tableId: "",
    source: "fallback",
    sourceNote: "未配置独立评分规则表；生产评分会被门禁阻断"
  };
}

function parseMapping(): Record<string, MappingTable> {
  const mappingPath = `${getSkillRoot()}/config/lark-field-mapping.yaml`;
  if (!existsSync(mappingPath)) return {};
  const lines = readFileSync(mappingPath, "utf8").split(/\r?\n/);
  const tables: Record<string, MappingTable> = {};
  let currentTable = "";
  let currentField = "";

  for (const line of lines) {
    const tableMatch = line.match(/^  ([a-zA-Z0-9_]+):\s*$/);
    if (tableMatch) {
      currentTable = tableMatch[1];
      currentField = "";
      tables[currentTable] = { baseToken: "", tableId: "", fields: [] };
      continue;
    }

    if (!currentTable) continue;

    const baseMatch = line.match(/^    base_token:\s*(.+)\s*$/);
    if (baseMatch) {
      tables[currentTable].baseToken = baseMatch[1].trim();
      continue;
    }

    const tableIdMatch = line.match(/^    table_id:\s*(.+)\s*$/);
    if (tableIdMatch) {
      tables[currentTable].tableId = tableIdMatch[1].trim();
      continue;
    }

    const fieldMatch = line.match(/^      ([a-zA-Z0-9_.]+):\s*$/);
    if (fieldMatch) {
      currentField = fieldMatch[1];
      tables[currentTable].fields.push({
        key: currentField,
        fieldName: "",
        fieldId: "",
        expectedType: ""
      });
      continue;
    }

    const latest = tables[currentTable].fields.at(-1);
    if (!latest || !currentField) continue;

    const fieldIdMatch = line.match(/^        field_id:\s*(.+)\s*$/);
    if (fieldIdMatch) latest.fieldId = fieldIdMatch[1].trim();

    const fieldNameMatch = line.match(/^        field_name:\s*(.+)\s*$/);
    if (fieldNameMatch) latest.fieldName = fieldNameMatch[1].trim();

    const typeMatch = line.match(/^        expected_type:\s*(.+)\s*$/);
    if (typeMatch) latest.expectedType = typeMatch[1].trim();
  }

  return tables;
}

export async function GET() {
  const mapping = parseMapping();
  const candidate = larkTableConfig("candidate");
  const contract = larkTableConfig("contract");
  const workflow = larkTableConfig("workflowLog");
  const pricingRules = resolvePricingRulesTable(mapping, candidate.baseToken);
  const templateBaseToken = readConfigValue("template_base_token");
  const templateTableId = readConfigValue("template_table_id");

  const tables = [
    {
      key: "candidate",
      label: "简历招募表",
      purpose: "候选人基础信息、简历附件、解析字段、评分结果、招募状态、Badcase 标记",
      baseToken: candidate.baseToken || mapping.candidate?.baseToken || "",
      tableId: candidate.tableId || mapping.candidate?.tableId || "",
      fields: mapping.candidate?.fields ?? []
    },
    {
      key: "contract_info",
      label: "合同信息收集表",
      purpose: "签约信息、收款银行信息、合同生成所需变量",
      baseToken: contract.baseToken || mapping.contract_info?.baseToken || "",
      tableId: contract.tableId || mapping.contract_info?.tableId || "",
      fields: mapping.contract_info?.fields ?? []
    },
    {
      key: "pricing_rules",
      label: "评分规则配置表",
      purpose: "各语种单价区间、评级与评分计算依赖规则",
      baseToken: pricingRules.baseToken,
      tableId: pricingRules.tableId,
      source: pricingRules.source,
      sourceNote: pricingRules.sourceNote,
      fields: mapping.pricing_rules?.fields ?? []
    },
    {
      key: "workflow_log",
      label: "Agent 流程日志表",
      purpose: "run_id、step、input/output 摘要、checkpoint、失败原因与审计记录",
      baseToken: workflow.baseToken || mapping.workflow_log?.baseToken || "",
      tableId: workflow.tableId || mapping.workflow_log?.tableId || "",
      fields: mapping.workflow_log?.fields ?? []
    },
    {
      key: "contract_template",
      label: "合同模板表",
      purpose: "合同模板文件与模板变量来源",
      baseToken: templateBaseToken,
      tableId: templateTableId,
      fields: []
    }
  ].map((table) => ({
    ...table,
    url: tableUrl(table.baseToken, table.tableId),
    fieldCount: table.fields.length,
    fields: table.fields.slice(0, 24)
  }));

  return NextResponse.json({
    ok: true,
    data: {
      configPath: getSkillConfigPath(),
      mappingPath: `${getSkillRoot()}/config/lark-field-mapping.yaml`,
      tables
    }
  });
}
