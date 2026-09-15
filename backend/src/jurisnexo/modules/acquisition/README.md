# acquisition

Owns source synchronization and acquisition lifecycle: deciding what source records are eligible to fetch, creating acquisition work, validating fetched bytes and registering immutable artifacts. Source-specific HTTP/browser connectors and object-storage implementations remain adapters.

Acquisition does not decide legal canonical identity, run LLM research, or expose raw bucket credentials to agents.
