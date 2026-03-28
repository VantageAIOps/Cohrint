export interface AgentAdapter {
  name: string;
  displayName: string;
  binary: string;
  defaultModel: string;
  provider: string;
  /** Args for interactive mode (no -p flag) — used by /session */
  interactiveArgs?: string[];
  /** Command to exit the agent's interactive session */
  exitCommand?: string;
  /** Whether this agent supports --continue for conversation context */
  supportsContinue?: boolean;
  /** Build command that continues a previous conversation. sessionId enables --resume. */
  buildContinueCommand?(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs;
  detect(): Promise<boolean>;
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs;
}

export interface AgentConfig {
  command: string;
  args: string[];
  model: string;
  detected: boolean;
}

export interface SpawnArgs {
  command: string;
  args: string[];
  env?: Record<string, string>;
}
