import type { AgentRunEvent } from "@/lib/agent-runner";
import type { CandidateResourcesPayload } from "@/lib/resource-agent-api";

export type CandidateResource = CandidateResourcesPayload["resources"][number];

export type Message = {
  id: string;
  role: "vm" | "agent";
  text: string;
};

export type ConsoleTuning = {
  leftWidth: number;
  eventPreviewLines: number;
  density: "compact" | "comfortable";
  checkpointMode: "inline" | "sticky";
  showRawPayload: boolean;
};

export type UploadedAttachment = {
  filename: string;
  path: string;
  size: number;
};

export type CheckpointSummary = {
  totalScore: string;
  tier: string;
  aiSuggestion: string;
  comment: string;
  confidence: string;
  confidenceReason: string;
  subject: string;
  recipient: string;
  attachment: string;
  selectedTemplate: string;
  filledVariables: string;
  requiredVariables: string;
};

export type AgentRunStatusEvent = AgentRunEvent;
