import { EventEmitter } from "events";

export type VantageEventMap = {
  "prompt:submitted": { prompt: string; agent: string; timestamp: number };
  "prompt:optimized": {
    original: string;
    optimized: string;
    savedTokens: number;
    savedPercent: number;
  };
  "agent:started": { agent: string; pid: number; command: string };
  "agent:completed": {
    agent: string;
    exitCode: number;
    outputText: string;
    durationMs: number;
    sessionId?: string;
  };
  "cost:calculated": {
    agent: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    costUsd: number;
    savedUsd: number;
    sessionId?: string;
  };
  "cost:reported": { success: boolean };
  "session:updated": {
    totalCost: number;
    totalSaved: number;
    promptCount: number;
  };
};

class VantageEventBus {
  private emitter = new EventEmitter();

  emit<K extends keyof VantageEventMap>(event: K, data: VantageEventMap[K]): void {
    this.emitter.emit(event, data);
  }

  on<K extends keyof VantageEventMap>(
    event: K,
    listener: (data: VantageEventMap[K]) => void
  ): void {
    this.emitter.on(event, listener);
  }

  off<K extends keyof VantageEventMap>(
    event: K,
    listener: (data: VantageEventMap[K]) => void
  ): void {
    this.emitter.off(event, listener);
  }

  once<K extends keyof VantageEventMap>(
    event: K,
    listener: (data: VantageEventMap[K]) => void
  ): void {
    this.emitter.once(event, listener);
  }

  removeAllListeners(): void {
    this.emitter.removeAllListeners();
  }
}

export const bus = new VantageEventBus();
