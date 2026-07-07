import type { GrievanceEvent } from "../api/types";
import StatusChip from "./StatusChip";

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export default function StatusTimeline({ events }: { events: GrievanceEvent[] }) {
  if (events.length === 0) {
    return <p className="muted-note">No status history yet.</p>;
  }

  return (
    <ol className="status-timeline">
      {events.map((event, index) => (
        <li className="status-timeline__item" key={`${event.status}-${event.created_at}-${index}`}>
          <div className="status-timeline__marker" aria-hidden="true" />
          <div className="status-timeline__header">
            <StatusChip status={event.status} />
            <time className="status-timeline__time">{formatDateTime(event.created_at)}</time>
          </div>
          {event.note && <p className="status-timeline__note">{event.note}</p>}
        </li>
      ))}
    </ol>
  );
}
