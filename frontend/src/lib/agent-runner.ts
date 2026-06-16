export type AgentAction =
  | "chat"
  | "resume-evaluate"
  | "score"
  | "test-email"
  | "test-email-mark-sent"
  | "contract-info-email"
  | "contract-info-mark-sent"
  | "contract-generate"
  | "signed-contract-check"
  | "update-status"
  | "unknown";

export type AgentRunRequest = {
  message: string;
  candidateLocator?: {
    type: "record_id" | "name" | "nickname" | "email";
    value: string;
  };
  attachments?: string[];
  mode?: "dry_run" | "production" | "test_mode";
  action?: AgentAction;
};

export type AgentRunMode = "dry_run" | "production";

export type AgentRunEvent = {
  event_id: string;
  run_id: string;
  event_type:
    | "run_started"
    | "candidate_resolved"
    | "agent_message"
    | "step_started"
    | "step_input"
    | "tool_call_started"
    | "tool_call_output"
    | "warning"
    | "waiting_input"
    | "checkpoint"
    | "checkpoint_confirmed"
    | "vm_decision"
    | "lark_writeback"
    | "workflow_log_written"
    | "usage_report"
    | "step_done"
    | "step_failed"
    | "run_done"
    | "run_cancelled";
  timestamp: string;
  candidate_record_id?: string;
  candidate_name?: string;
  step_name?: string;
  payload: Record<string, unknown>;
};
