import { create } from "zustand";

interface Alert {
  timestamp: string;
  severity: string;
  source_system: string;
  rule_id: string;
  description: string;
  raw_log?: string;
}

interface DecisionGate {
  gate_id: string;
  context_summary: string;
  options: { index: number; text: string }[];
}

interface SimulationState {
  sessionId: string | null;
  alerts: Alert[];
  currentGate: DecisionGate | null;
  isPaused: boolean;
  isComplete: boolean;
  chatMessages: { user_id: string; text: string; ts: string }[];
  setSession: (id: string) => void;
  addAlert: (alert: Alert) => void;
  setGate: (gate: DecisionGate | null) => void;
  setPaused: (v: boolean) => void;
  setComplete: () => void;
  addChat: (msg: { user_id: string; text: string }) => void;
  reset: () => void;
}

export const useSimStore = create<SimulationState>((set) => ({
  sessionId: null,
  alerts: [],
  currentGate: null,
  isPaused: false,
  isComplete: false,
  chatMessages: [],
  setSession: (id) => set({ sessionId: id }),
  addAlert: (alert) => set((s) => ({ alerts: [...s.alerts, alert] })),
  setGate: (gate) => set({ currentGate: gate, isPaused: !!gate }),
  setPaused: (v) => set({ isPaused: v }),
  setComplete: () => set({ isComplete: true }),
  addChat: (msg) => set((s) => ({ chatMessages: [...s.chatMessages, { ...msg, ts: new Date().toISOString() }] })),
  reset: () => set({ sessionId: null, alerts: [], currentGate: null, isPaused: false, isComplete: false, chatMessages: [] }),
}));
