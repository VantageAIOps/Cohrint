-- Remove the kv_key column from copilot_connections.
-- The cron always reconstructs the KV key deterministically via
-- kvTokenKey(orgId, githubOrg) = "copilot:token:<orgId>:<githubOrg>"
-- and never reads this column from D1. Keeping it is a maintenance trap:
-- if the key derivation function changes, the column silently diverges.
ALTER TABLE copilot_connections DROP COLUMN kv_key;
