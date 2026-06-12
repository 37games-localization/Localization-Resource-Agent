import type { ChangeEvent, FormEvent } from "react";
import type { AgentRunEvent } from "@/lib/agent-runner";
import type { CandidateResource, UploadedAttachment } from "./types";

type ChatInputPanelProps = {
  draft: string;
  isRunning: boolean;
  isUploading: boolean;
  uploadedAttachment?: UploadedAttachment;
  error: string;
  candidate?: AgentRunEvent;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onUploadAttachment: (file: File) => void;
  onClearAttachment: () => void;
};

export function ChatInputPanel({
  draft,
  isRunning,
  isUploading,
  uploadedAttachment,
  error,
  candidate,
  onDraftChange,
  onSubmit,
  onUploadAttachment,
  onClearAttachment
}: ChatInputPanelProps) {
  function handleAttachmentChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onUploadAttachment(file);
    event.target.value = "";
  }

  return (
    <>
      <form className="chat-input-row" onSubmit={onSubmit}>
        <input className="input" onChange={(event) => onDraftChange(event.target.value)} placeholder="输入：给候选人全名准备合同 / 看下某某简历" value={draft} />
        <button className="button" disabled={isRunning} type="submit">
          {isRunning ? "执行中" : "发送"}
        </button>
      </form>
      <div className="attachment-inline">
        <div className="upload-row">
          <label className="upload-button">
            <input accept=".xlsx,.pdf,.docx" disabled={isUploading || isRunning} onChange={handleAttachmentChange} type="file" />
            {isUploading ? "上传中" : "选择附件"}
          </label>
          {uploadedAttachment ? (
            <button className="button secondary" onClick={onClearAttachment} type="button">
              移除
            </button>
          ) : null}
        </div>
        <p className="meta">
          {uploadedAttachment
            ? `已选择：${uploadedAttachment.filename}（${Math.ceil(uploadedAttachment.size / 1024)} KB）`
            : "测试题邮件和签字合同核查可上传附件；会用本地路径的人也可以直接在对话框粘贴本机文件路径。"}
        </p>
      </div>
      {error && <div className="next-box">{error}</div>}
      {candidate && (
        <p className="meta chat-context">
          最近执行对象：{candidate.candidate_name ?? "未识别"} / {candidate.candidate_record_id ?? "未提供 record_id"}
        </p>
      )}
    </>
  );
}
