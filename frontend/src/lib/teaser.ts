import { api } from "./api";
import type { NetworkMapEdge, NetworkMapNode } from "../components/NetworkMap";
import type { NodeState } from "../theme/tokens";

export interface TeaserStartResponse {
  teaser_token: string;
  scenario_key: string;
  headline: string;
  countdown_seconds: number;
  nodes: NetworkMapNode[];
  edges: NetworkMapEdge[];
  node_states: Record<string, NodeState>;
  alert_lines: { timestamp: string; text: string }[];
  decision: {
    id: string;
    trigger_alert: string;
    node_choices: string[];
  };
}

export interface TeaserAnswerResponse {
  correct: boolean;
  node_states: Record<string, NodeState>;
  consequence_text: string;
  end_card_text: string;
}

export interface TeaserClaimResponse {
  claimed: boolean;
  achievement_unlocked: boolean;
}

const TEASER_TOKEN_STORAGE_KEY = "br_teaser_token";

export const teaserApi = {
  start: () => api.post<TeaserStartResponse>("/teaser/start", {}),
  answer: (teaserToken: string, chosenNodeId: string) =>
    api.post<TeaserAnswerResponse>("/teaser/answer", {
      teaser_token: teaserToken,
      chosen_node_id: chosenNodeId,
    }),
  claim: (teaserToken: string) =>
    api.post<TeaserClaimResponse>("/teaser/claim", { teaser_token: teaserToken }),
};

/** Conversion continuity (spec section 3): stash the teaser token across the
 * signup flow (including a full-page OAuth redirect, since sessionStorage
 * survives navigation within the same tab) so RegisterPage/AuthCallbackPage
 * can claim it once the visitor has a real account. */
export function stashTeaserToken(token: string): void {
  sessionStorage.setItem(TEASER_TOKEN_STORAGE_KEY, token);
}

export function consumeStashedTeaserToken(): string | null {
  const token = sessionStorage.getItem(TEASER_TOKEN_STORAGE_KEY);
  if (token) sessionStorage.removeItem(TEASER_TOKEN_STORAGE_KEY);
  return token;
}
