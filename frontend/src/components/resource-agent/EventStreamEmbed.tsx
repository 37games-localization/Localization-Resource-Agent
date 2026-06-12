import type { RefObject } from "react";
import type { AgentRunEvent } from "@/lib/agent-runner";
import { eventLabel, eventSummary, statusForEvent, stringifyPayload } from "./agent-console-utils";

type EventStreamEmbedProps = {
  events: AgentRunEvent[];
  isExpanded: boolean;
  showRawPayload: boolean;
  eventStreamRef: RefObject<HTMLDivElement>;
  onToggle: () => void;
};

export function EventStreamEmbed({ events, isExpanded, showRawPayload, eventStreamRef, onToggle }: EventStreamEmbedProps) {
  if (events.length === 0) return null;

  return (
    <div className={`agent-event-embed ${isExpanded ? "expanded" : "collapsed"}`} ref={eventStreamRef}>
      <button className="agent-event-embed-header" onClick={onToggle} type="button">
        <span>执行过程</span>
        <strong>{events.length} 条真实事件，点击{isExpanded ? "收起" : "展开"}</strong>
      </button>
      {!isExpanded && (
        <div className="agent-event-preview">
          {events.slice(-3).map((event) => (
            <p key={`preview-${event.event_id}`}>
              <span>{eventLabel[event.event_type]}</span>
              {eventSummary(event)}
            </p>
          ))}
        </div>
      )}
      {isExpanded && (
        <div className="agent-event-stack">
          {events.map((event) => (
            <details className={`agent-event agent-event-${statusForEvent(event)}`} key={event.event_id}>
              <summary>
                <span>{eventLabel[event.event_type]}</span>
                <strong>{eventSummary(event)}</strong>
              </summary>
              {showRawPayload && <pre className="event-payload">{stringifyPayload(event.payload)}</pre>}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
