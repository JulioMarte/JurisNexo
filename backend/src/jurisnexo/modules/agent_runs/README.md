# agent_runs

Owns durable agent-run intent and reproducibility metadata: agent profile, dataset snapshot, run configuration, budget/configuration references and resulting execution records.

Agent frameworks and provider SDKs are replaceable adapters. Agents consume supported API/corpus capabilities; they do not receive unrestricted SQL or general S3 credentials.
