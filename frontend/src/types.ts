export interface WeightProfile {
  name: string;
  severity: number;
  survival: number;
  waiting: number;
}

export type Movement = "up" | "down" | "unchanged" | "new";

export interface QueueEntry {
  entry_id: string;
  patient_id: string;
  rank: number;
  score: number;
  severity_factor: number;
  survival_factor: number;
  waiting_factor: number;
  waiting_minutes: number;
  survival_probability: number;
  survival_attribution: Record<string, number>;
  tie_break_reason: string | null;
  movement: Movement | null;
}

export interface TrailSummary {
  id: number;
  type: "snapshot" | "decision";
  occurred_at: string;
  label: string;
}

export type EventKind =
  | "arrival"
  | "removal"
  | "profile-change"
  | "re-rank"
  | "bed-freed"
  | "allocation";

export interface EventItem {
  id: number;
  occurred_at: string;
  kind: EventKind;
  detail: string;
}

export interface DashboardState {
  as_of: string;
  profile: WeightProfile;
  wait_horizon_hours: number;
  queue: QueueEntry[];
  events: EventItem[];
  trail: TrailSummary[];
}

export type TrailRecord = TrailSummary & {
  profile: WeightProfile;
  wait_horizon_hours: number;
  queue: QueueEntry[];
  trigger?: string;
  outcome?: string;
  reasoning?: string;
  note?: string | null;
  recommended?: string;
  allocated?: string;
};

export interface RankPoint {
  snapshot_id: number;
  rank: number;
  occurred_at: string;
  trigger: string;
}