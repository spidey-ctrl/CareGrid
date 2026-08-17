import type { WeightProfile } from "../types";

function pct(value: number): string {
  return `${Math.round(value * 100)}`;
}

export function ProfileBadge({ profile }: { profile: WeightProfile }) {
  return (
    <span className="profile-badge" title="active weight profile">
      {profile.name} ({pct(profile.severity)}/{pct(profile.survival)}/{pct(profile.waiting)})
    </span>
  );
}