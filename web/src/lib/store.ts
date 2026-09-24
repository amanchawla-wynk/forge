import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

import type { AssessmentResponse, LLMConfig, Question, UploadResponse } from "@/lib/types";

export interface ConversationTurn {
  question: Question;
  answer: string;
}

interface AppState {
  llm: LLMConfig | null;
  document: UploadResponse | null;
  assessment: AssessmentResponse | null;
  history: ConversationTurn[];

  setLLM: (llm: LLMConfig) => void;
  setDocument: (document: UploadResponse) => void;
  setAssessment: (assessment: AssessmentResponse) => void;
  appendHistory: (turn: ConversationTurn) => void;
  reset: () => void;
  resetAssessmentOnly: () => void;
}

// The API key lives only in sessionStorage: cleared when the tab closes,
// never written by the backend, never sent anywhere except our own local
// FastAPI process per-request. See docs/DECISIONS.md D-033.
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      llm: null,
      document: null,
      assessment: null,
      history: [],

      setLLM: (llm) => set({ llm }),
      setDocument: (document) =>
        set({ document, assessment: null, history: [] }),
      setAssessment: (assessment) => set({ assessment }),
      appendHistory: (turn) =>
        set((state) => ({ history: [...state.history, turn] })),
      reset: () => set({ document: null, assessment: null, history: [] }),
      resetAssessmentOnly: () => set({ assessment: null, history: [] }),
    }),
    {
      name: "forge-dashboard-session",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        llm: state.llm,
        document: state.document,
        assessment: state.assessment,
        history: state.history,
      }),
    },
  ),
);
