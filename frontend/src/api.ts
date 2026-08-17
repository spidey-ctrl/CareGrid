import type { DashboardState, RankPoint, TrailRecord } from "./types";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} → ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getState(): Promise<DashboardState> {
  return fetchJson<DashboardState>("/api/state");
}

export function getRecord(id: number): Promise<TrailRecord> {
  return fetchJson<TrailRecord>(`/api/record/${id}`);
}

export function getHistory(patientId: string): Promise<RankPoint[]> {
  return fetchJson<RankPoint[]>(`/api/patient/${patientId}/history`);
}