import type { EventItem } from "../types";
import { fmtClock } from "../format";

const KIND_CLASS: Record<string, string> = {
  arrival: "kind-arrival",
  removal: "kind-removal",
  "re-rank": "kind-rerank",
  allocation: "kind-allocation",
  "profile-change": "kind-profile",
};

export function EventFeed({
  events,
  dimAfter,
}: {
  events: EventItem[];
  dimAfter?: string;
}) {
  return (
    <ul className="event-feed">
      {events.length === 0 && <li className="event-empty">no events yet</li>}
      {events.map((event) => {
        const dimmed = dimAfter !== undefined && event.occurred_at > dimAfter;
        return (
          <li
            key={event.id}
            className={`event ${KIND_CLASS[event.kind] ?? "kind-other"} ${dimmed ? "event-dim" : ""}`}
          >
            <span className="event-time">{fmtClock(event.occurred_at)}</span>
            <span className="event-kind">{event.kind}</span>
            <span className="event-detail">{event.detail}</span>
          </li>
        );
      })}
    </ul>
  );
}