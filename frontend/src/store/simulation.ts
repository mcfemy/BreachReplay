import { create } from "zustand";

export interface Alert {
  timestamp: string;
  severity: string;
  source_system: string;
  rule_id: string;
  description: string;
  raw_log?: string;
}

export interface DecisionGate {
  gate_id: string;
  context_summary: string;
  options: { index: number; text: string }[];
}

export interface Participant {
  user_id: string;
  name: string;
  role: string;
  online: boolean;
}

interface SimulationState {
  sessionId: string | null;
  alerts: Alert[];
  currentGate: DecisionGate | null;
  isPaused: boolean;
  isComplete: boolean;
  error: string | null;
  chatMessages: { user_id: string; name?: string; role?: string; text: string; ts: string }[];
  participants: Participant[];
  votes: Record<string, number>; // user_id -> chosen_index
  setSession: (id: string) => void;
  addAlert: (alert: Alert) => void;
  setGate: (gate: DecisionGate | null) => void;
  setPaused: (v: boolean) => void;
  setComplete: () => void;
  setError: (msg: string | null) => void;
  addChat: (msg: { user_id: string; name?: string; role?: string; text: string }) => void;
  setParticipants: (p: Participant[]) => void;
  upsertParticipant: (p: Participant) => void;
  setVotes: (votes: Record<string, number>) => void;
  clearVotes: () => void;
  reset: () => void;
}

export const useSimStore = create<SimulationState>((set) => ({
  sessionId: null,
  alerts: [],
  currentGate: null,
  isPaused: false,
  isComplete: false,
  error: null,
  chatMessages: [],
  participants: [],
  votes: {},
  setSession: (id) => set({ sessionId: id }),
  addAlert: (alert) => set((s) => ({ alerts: [...s.alerts, alert] })),
  setGate: (gate) => set({ currentGate: gate, isPaused: !!gate }),
  setPaused: (v) => set({ isPaused: v }),
  setComplete: () => set({ isComplete: true }),
  setError: (msg) => set({ error: msg }),
  addChat: (msg) => set((s) => ({ chatMessages: [...s.chatMessages, { ...msg, ts: new Date().toISOString() }] })),
  setParticipants: (p) => set({ participants: p }),
  upsertParticipant: (p) => set((s) => {
    const idx = s.participants.findIndex((x) => x.user_id === p.user_id);
    if (idx >= 0) {
      const updated = [...s.participants];
      updated[idx] = { ...updated[idx], ...p };
      return { participants: updated };
    }
    return { participants: [...s.participants, p] };
  }),
  setVotes: (votes) => set({ votes }),
  clearVotes: () => set({ votes: {} }),
  reset: () => set({
    sessionId: null,
    alerts: [],
    currentGate: null,
    isPaused: false,
    isComplete: false,
    error: null,
    chatMessages: [],
    participants: [],
    votes: {}
  }),
}));

