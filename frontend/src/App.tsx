import { useEffect, useState } from "react";
import { getRecord, getState } from "./api";
import type { DashboardState, TrailRecord } from "./types";
import { fmtClock } from "./format";
import { EventFeed } from "./components/EventFeed";
import { ProfileBadge } from "./components/ProfileBadge";
import { QueueTable } from "./components/QueueTable";
import { ReplayBar } from "./components/ReplayBar";

export default function App() {
  const [state, setState] = useState<DashboardState | null>(null);
  const [record, setRecord] = useState<TrailRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getState()
      .then(setState)
      .catch((err) => setError(String(err)));
  }, []);

  if (error !== null) {
    return <main className="screen message-screen">Dashboard unavailable — {error}</main>;
  }
  if (state === null) {
    return <main className="screen message-screen">Loading dashboard…</main>;
  }

  const trailLength = state.trail.length;
  const live = record === null;
  const position = live
    ? trailLength
    : Math.max(0, state.trail.findIndex((t) => t.id === record.id));

  function onPositionChange(pos: number) {
    if (pos === trailLength) {
      setRecord(null);
      return;
    }
    const target = state!.trail[pos];
    if (!live && record !== null && record.id === target.id) return;
    getRecord(target.id)
      .then(setRecord)
      .catch((err) => setError(String(err)));
  }

  const displayedQueue = live ? state.queue : (record?.queue ?? []);
  const profile = live ? state.profile : record!.profile;
  const waitHorizon = live ? state.wait_horizon_hours : record!.wait_horizon_hours;
  const banner = live
    ? null
    : {
        id: record!.id,
        label: record!.label,
        occurredAt: record!.occurred_at,
      };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CareGrid</span>
          <span className="brand-sub">ICU bed arbitration</span>
        </div>
        <div className="topbar-meta">
          <ProfileBadge profile={profile} />
          <span className="horizon" title="wait horizon in effect">
            horizon {waitHorizon}h
          </span>
          <span className="as-of-time">as of {fmtClock(state.as_of)}</span>
        </div>
      </header>

      <ReplayBar trail={state.trail} position={position} onChange={onPositionChange} />

      {banner !== null && (
        <div className="replay-banner">
          <span>
            Replaying — {banner.label} at {fmtClock(banner.occurredAt)}
          </span>
          <button className="live-button" onClick={() => setRecord(null)}>
            back to live
          </button>
        </div>
      )}

      <main className="layout">
        <section className="queue-panel">
          <div className="panel-heading">
            <h1>{live ? "Live ranked queue" : `Queue at record #${banner?.id}`}</h1>
            <span className="count">{displayedQueue.length} entries</span>
          </div>
          {displayedQueue.length === 0 ? (
            <p className="empty-queue">The queue is empty.</p>
          ) : (
            <QueueTable queue={displayedQueue} showMovement={live} />
          )}
        </section>

        <aside className="side-panel">
          <div className="panel-heading">
            <h1>Event feed</h1>
          </div>
          <EventFeed events={state.events} dimAfter={live ? undefined : record?.occurred_at} />

          {!live && record !== null && record.type === "decision" && (
            <div className="decision-card">
              <h2>Allocation — {record.outcome}</h2>
              <p>
                allocated <strong>{record.allocated}</strong>
                {record.recommended !== record.allocated && (
                  <> (recommended {record.recommended})</>
                )}
              </p>
              <p className="reasoning">{record.reasoning}</p>
              {record.note !== null && <p className="note">note: {record.note}</p>}
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}