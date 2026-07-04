// Shared helper for Live Breach Events Phase 4 (ArenaEventsPage /
// ArenaEventDetailPage): the backend serializes naive UTC datetime columns
// (e.g. ArenaEvent.starts_at/ends_at via `.isoformat()`, with no trailing
// "Z"/offset) — `new Date(iso)` would otherwise parse that string as LOCAL
// time, skewing every countdown/relative-time display by the viewer's UTC
// offset. Mirrors the exact fix FreshIncidentTicker.tsx's `timeAgo` already
// applies inline, pulled out here since two new pages need the identical
// normalization.
export function parseUtc(iso: string): Date {
  const utcIso = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  return new Date(utcIso);
}
