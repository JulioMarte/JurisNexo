# jobs

Owns durable job definitions, schedules, execution runs, retry/failure state and operational history.

The scheduler creates work; it does not own acquisition, ingestion or agent semantics. Workers execute supported application commands and record durable run facts. A successful process exit is not proof of semantic/legal success.
