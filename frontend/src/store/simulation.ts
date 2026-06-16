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
  countdown_seconds?: number;
  urgency_level?: string;
}

export interface PressureInjection {
  id: string;
  trigger_timestamp: string;
  type: "email" | "call" | "news" | "sms" | "slack";
  from: string;
  subject?: string;
  body: string;
  countdown_seconds?: number;
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
  activePressureInjection: PressureInjection | null;
  isPaused: boolean;
  isComplete: boolean;
  error: string | null;
  chatMessages: { user_id: string; name?: string; role?: string; text: string; ts: string }[];
  participants: Participant[];
  votes: Record<string, number>;
  setSession: (id: string) => void;
  addAlert: (alert: Alert) => void;
  setGate: (gate: DecisionGate | null) => void;
  setActivePressureInjection: (inj: PressureInjection | null) => void;
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
  activePressureInjection: null,
  isPaused: false,
  isComplete: false,
  error: null,
  chatMessages: [],
  participants: [],
  votes: {},
  setSession: (id) => set({ sessionId: id }),
  addAlert: (alert) => set((s) => ({ alerts: [...s.alerts, alert] })),
  setGate: (gate) => set({ currentGate: gate, isPaused: !!gate }),
  setActivePressureInjection: (inj) => set({ activePressureInjection: inj }),
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
    activePressureInjection: null,
    isPaused: false,
    isComplete: false,
    error: null,
    chatMessages: [],
    participants: [],
    votes: {}
  }),
}));

