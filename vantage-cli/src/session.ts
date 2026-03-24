import { randomUUID } from "node:crypto";
import { bus } from "./event-bus.js";

export interface PromptRecord {
  agent: string;
  model: string;
  prompt: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  savedTokens: number;
  savedUsd: number;
  durationMs: number;
  timestamp: number;
}

export interface SessionState {
  sessionId: string;
  startedAt: number;
  promptCount: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCostUsd: number;
  totalSavedTokens: number;
  totalSavedUsd: number;
  history: PromptRecord[];
}

class Session {
  private state: SessionState;
  private currentPrompt: string = "";
  private currentSavedTokens: number = 0;

  constructor() {
    this.state = {
      sessionId: randomUUID(),
      startedAt: Date.now(),
      promptCount: 0,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalCostUsd: 0,
      totalSavedTokens: 0,
      totalSavedUsd: 0,
      history: [],
    };
    this.setupListeners();
  }

  private setupListeners(): void {
    bus.on("prompt:submitted", (data) => {
      this.currentPrompt = data.prompt;
    });

    bus.on("prompt:optimized", (data) => {
      this.currentSavedTokens = data.savedTokens;
      this.state.totalSavedTokens += data.savedTokens;
    });

    bus.on("cost:calculated", (data) => {
      this.state.promptCount++;
      this.state.totalInputTokens += data.inputTokens;
      this.state.totalOutputTokens += data.outputTokens;
      this.state.totalCostUsd += data.costUsd;
      this.state.totalSavedUsd += data.savedUsd;

      const record: PromptRecord = {
        agent: data.agent,
        model: data.model,
        prompt: this.currentPrompt,
        inputTokens: data.inputTokens,
        outputTokens: data.outputTokens,
        costUsd: data.costUsd,
        savedTokens: this.currentSavedTokens,
        savedUsd: data.savedUsd,
        durationMs: 0,
        timestamp: Date.now(),
      };

      this.state.history.push(record);
      this.currentSavedTokens = 0;

      bus.emit("session:updated", {
        totalCost: this.state.totalCostUsd,
        totalSaved: this.state.totalSavedUsd,
        promptCount: this.state.promptCount,
      });
    });
  }

  getSession(): SessionState {
    return { ...this.state, history: [...this.state.history] };
  }
}

let sessionInstance: Session | null = null;

export function initSession(): Session {
  if (!sessionInstance) {
    sessionInstance = new Session();
  }
  return sessionInstance;
}

export function getSession(): SessionState {
  if (!sessionInstance) {
    sessionInstance = new Session();
  }
  return sessionInstance.getSession();
}
