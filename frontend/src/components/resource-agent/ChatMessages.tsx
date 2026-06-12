import type { RefObject } from "react";
import type { AgentRunEvent } from "@/lib/agent-runner";
import { EventStreamEmbed } from "./EventStreamEmbed";
import type { Message } from "./types";

type ChatMessagesProps = {
  messages: Message[];
  visibleEvents: AgentRunEvent[];
  isEventExpanded: boolean;
  showRawPayload: boolean;
  chatMessagesRef: RefObject<HTMLDivElement>;
  eventStreamRef: RefObject<HTMLDivElement>;
  onToggleEvents: () => void;
};

export function ChatMessages({
  messages,
  visibleEvents,
  isEventExpanded,
  showRawPayload,
  chatMessagesRef,
  eventStreamRef,
  onToggleEvents
}: ChatMessagesProps) {
  return (
    <div className="chat-messages" ref={chatMessagesRef}>
      {messages.map((message) => (
        <div className={`chat-message ${message.role}`} key={message.id}>
          <span>{message.role === "vm" ? "VM" : "Agent"}</span>
          <p>{message.text}</p>
        </div>
      ))}
      <EventStreamEmbed
        eventStreamRef={eventStreamRef}
        events={visibleEvents}
        isExpanded={isEventExpanded}
        onToggle={onToggleEvents}
        showRawPayload={showRawPayload}
      />
    </div>
  );
}
