import type { ColType } from './db-dates';

export const DATE_COLUMN_TYPE = {
  // INTEGER unixepoch columns
  events:               'int',
  orgs:                 'int',
  org_members:          'int',
  alert_configs:        'int',
  team_budgets:         'int',
  sessions:             'int',
  alert_log:            'int',
  platform_pageviews:   'int',
  platform_sessions:    'int',
  audit_events:         'int',
  budget_policies:      'int',
  provider_connections: 'int',
  // TEXT 'YYYY-MM-DD HH:MM:SS' columns
  cross_platform_usage:   'text',
  otel_events:            'text',
  benchmark_snapshots:    'text',
  copilot_connections:    'text',
  datadog_connections:    'text',
  prompts:                'text',
  prompt_versions:        'text',
  prompt_usage:           'text',
  semantic_cache_entries: 'text',
  org_cache_config:       'text',
} as const satisfies Record<string, ColType>;

export type TableName = keyof typeof DATE_COLUMN_TYPE;
