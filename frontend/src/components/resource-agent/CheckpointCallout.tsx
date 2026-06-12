import type { AgentRunEvent } from "@/lib/agent-runner";
import { checkpointSummary, checkpointType, sanitizeDemoText, stringifyPayload } from "./agent-console-utils";

type CheckpointCalloutProps = {
  checkpoint?: AgentRunEvent;
  visibleEventCount: number;
  onShowEvents: () => void;
};

export function CheckpointCallout({ checkpoint, visibleEventCount, onShowEvents }: CheckpointCalloutProps) {
  if (!checkpoint) return null;

  const summary = checkpointSummary(checkpoint.payload);
  const type = checkpointType(checkpoint.payload);

  return (
    <div className="checkpoint-callout">
      <span>需要人工确认</span>
      <strong>{sanitizeDemoText(String(checkpoint.payload.title ?? "等待 VM 确认"))}</strong>
      {type === "resume" && (
        <>
          <div className="checkpoint-decision-grid">
            <div>
              <span>总分</span>
              <strong>{summary.totalScore}</strong>
            </div>
            <div>
              <span>评级</span>
              <strong>{summary.tier}</strong>
            </div>
            <div>
              <span>置信度</span>
              <strong>{summary.confidenceReason}</strong>
            </div>
          </div>
          <div className="checkpoint-decision-copy">
            <span>AI建议</span>
            <p>{sanitizeDemoText(summary.aiSuggestion)}</p>
          </div>
          <div className="checkpoint-decision-copy">
            <span>点评</span>
            <p>{sanitizeDemoText(summary.comment)}</p>
          </div>
        </>
      )}
      {type === "email" && (
        <div className="checkpoint-decision-grid">
          <div>
            <span>主题</span>
            <strong>{summary.subject}</strong>
          </div>
          <div>
            <span>收件人</span>
            <strong>{summary.recipient}</strong>
          </div>
          <div>
            <span>附件</span>
            <strong>{summary.attachment}</strong>
          </div>
        </div>
      )}
      {type === "contract" && (
        <div className="checkpoint-decision-grid">
          <div>
            <span>合同模板</span>
            <strong>{summary.selectedTemplate}</strong>
          </div>
          <div>
            <span>已填变量</span>
            <strong>{summary.filledVariables}</strong>
          </div>
          <div>
            <span>所需变量</span>
            <strong>{summary.requiredVariables}</strong>
          </div>
        </div>
      )}
      {type === "generic" && (
        <div className="checkpoint-decision-copy">
          <span>确认内容</span>
          <p>{sanitizeDemoText(String(checkpoint.payload.detail ?? "请查看执行过程后决定是否继续。"))}</p>
        </div>
      )}
      {visibleEventCount > 0 && (
        <button className="checkpoint-link-button" onClick={onShowEvents} type="button">
          查看本次执行过程（{visibleEventCount} 条）
        </button>
      )}
      <details className="checkpoint-raw-detail">
        <summary>查看完整字段与写回说明</summary>
        <pre>{stringifyPayload(checkpoint.payload)}</pre>
      </details>
    </div>
  );
}
