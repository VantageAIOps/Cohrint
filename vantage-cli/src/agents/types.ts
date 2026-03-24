export interface AgentAdapter {
  name: string;
  displayName: string;
  binary: string;
  defaultModel: string;
  provider: string;
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
