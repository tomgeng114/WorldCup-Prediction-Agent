import { DashboardSummary, HistoryRow, MatchCard } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export function getTodayMatches(): Promise<MatchCard[]> {
  return fetchJson<MatchCard[]>("/api/matches/today");
}

export function getAllMatches(): Promise<MatchCard[]> {
  return fetchJson<MatchCard[]>("/api/matches");
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return fetchJson<DashboardSummary>("/api/dashboard/summary");
}

export function getHistory(): Promise<HistoryRow[]> {
  return fetchJson<HistoryRow[]>("/api/history");
}
