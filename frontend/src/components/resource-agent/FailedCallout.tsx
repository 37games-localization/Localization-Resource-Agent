import type { AgentRunEvent } from "@/lib/agent-runner";
import { stringifyPayload } from "./agent-console-utils";

type FailedCalloutProps = {
  failed?: AgentRunEvent;
};

export function FailedCallout({ failed }: FailedCalloutProps) {
  if (!failed) return null;

  return (
    <div className="checkpoint-callout checkpoint-callout-failed">
      <span>需要人工处理</span>
      <strong>步骤执行失败</strong>
      <p>系统已停止继续执行，请先处理下方失败原因。</p>
      <pre>{stringifyPayload(failed.payload)}</pre>
    </div>
  );
}
