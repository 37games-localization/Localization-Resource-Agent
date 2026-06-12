import type { RefObject, FormEvent } from "react";
import type { AgentRunEvent } from "@/lib/agent-runner";
import { ChatInputPanel } from "./ChatInputPanel";
import { ChatMessages } from "./ChatMessages";
import { CheckpointCallout } from "./CheckpointCallout";
import { FailedCallout } from "./FailedCallout";
import type { CandidateResource, Message, UploadedAttachment } from "./types";

type AgentChatPanelProps = {
  selectedResource?: CandidateResource;
  messages: Message[];
  visibleEvents: AgentRunEvent[];
  isEventExpanded: boolean;
  showRawPayload: boolean;
  chatMessagesRef: RefObject<HTMLDivElement>;
  eventStreamRef: RefObject<HTMLDivElement>;
  latestCheckpoint?: AgentRunEvent;
  failed?: AgentRunEvent;
  draft: string;
  isRunning: boolean;
  isUploading: boolean;
  uploadedAttachment?: UploadedAttachment;
  error: string;
  candidate?: AgentRunEvent;
  onReset: () => void;
  onToggleEvents: () => void;
  onShowEvents: () => void;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onUploadAttachment: (file: File) => void;
  onClearAttachment: () => void;
};

export function AgentChatPanel({
  selectedResource,
  messages,
  visibleEvents,
  isEventExpanded,
  showRawPayload,
  chatMessagesRef,
  eventStreamRef,
  latestCheckpoint,
  failed,
  draft,
  isRunning,
  isUploading,
  uploadedAttachment,
  error,
  candidate,
  onReset,
  onToggleEvents,
  onShowEvents,
  onDraftChange,
  onSubmit,
  onUploadAttachment,
  onClearAttachment
}: AgentChatPanelProps) {
  return (
    <section className="panel workbench-chat-panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">Agent 对话</h2>
          <p className="meta">
            {selectedResource ? `当前选择：${selectedResource.name || selectedResource.recordId}` : "可先点选左侧候选人，也可在输入中直接写姓名或 record_id"}
          </p>
        </div>
        <button className="button secondary" onClick={onReset} type="button">
          清空
        </button>
      </div>
      <ChatMessages
        chatMessagesRef={chatMessagesRef}
        eventStreamRef={eventStreamRef}
        isEventExpanded={isEventExpanded}
        messages={messages}
        onToggleEvents={onToggleEvents}
        showRawPayload={showRawPayload}
        visibleEvents={visibleEvents}
      />
      <CheckpointCallout checkpoint={latestCheckpoint} onShowEvents={onShowEvents} visibleEventCount={visibleEvents.length} />
      {!latestCheckpoint && <FailedCallout failed={failed} />}
      <ChatInputPanel
        candidate={candidate}
        draft={draft}
        error={error}
        isRunning={isRunning}
        isUploading={isUploading}
        onClearAttachment={onClearAttachment}
        onDraftChange={onDraftChange}
        onSubmit={onSubmit}
        onUploadAttachment={onUploadAttachment}
        uploadedAttachment={uploadedAttachment}
      />
    </section>
  );
}
