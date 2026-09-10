# JurisNexo — Tenancy, Authentication, and Access Control

## 1. Purpose

JurisNexo is multi-tenant from the demo stage. This document defines the authorization model required so implementation does not reduce tenancy to a UI convention.

## 2. Core principals

MVP principals:

- `user` — authenticated human;
- `organization` — tenant/security boundary;
- `membership` — relationship between user and organization;
- `service_principal` — optional future machine/API identity;
- `system_worker` — internal bounded execution identity.

A user may belong to multiple organizations.

## 3. Organization-owned resources

The following are tenant-owned unless explicitly public/system-owned:

- research jobs;
- research briefs;
- uploaded documents;
- private corpora;
- evidence derived from private documents;
- reports;
- annotations;
- saved searches;
- exports;
- API credentials;
- usage/quota state;
- organization settings.

Public jurisprudence remains shared system data.

## 4. Initial roles

Keep the MVP role model intentionally small:

### Owner

May:

- manage organization settings;
- invite/remove members;
- view all organization research;
- manage quota/billing-related configuration when introduced;
- delete organization resources.

### Member

May:

- create research jobs;
- upload permitted documents;
- read organization research/results;
- provide feedback.

A future `viewer`, `researcher`, or custom-role model should not be introduced before a real customer requires it.

## 5. Authorization invariant

Every private request must evaluate:

```text
authenticated principal
        +
active organization
        +
membership/role
        +
resource ownership
        +
action permission
```

The model/agent must never determine authorization.

## 6. Database enforcement

Preferred defense in depth:

- tenant-scoped primary/foreign keys;
- `organization_id` on tenant aggregates;
- PostgreSQL row-level security where practical;
- application authorization;
- worker jobs containing explicit immutable tenant context;
- no unscoped repository methods for private entities.

Public legal corpus tables are explicitly global and must not accidentally inherit tenant filtering semantics.

## 7. Object storage

Private storage keys must include non-guessable organization/job ownership and authorization must occur before signed access is issued.

Do not depend on obscurity of object paths.

Public source artifacts may use separate buckets/namespaces from customer data.

## 8. Research execution context

Every research job receives a fixed execution context:

```json
{
  "job_id": "...",
  "organization_id": "...",
  "initiated_by_user_id": "...",
  "public_corpus_scope": {},
  "private_document_scope": [],
  "entitlements": {},
  "resource_budget": {}
}
```

Subagents/workers inherit a narrower or equal context. They may not expand scope.

## 9. Public versus private evidence

A report may combine:

- globally shared public jurisprudence;
- tenant-private uploaded matter documents.

Every evidence item records its data class so the report renderer/exporter knows whether it may expose/share a source link.

Private evidence must never be promoted into globally reusable knowledge by default.

## 10. Sharing and exports

MVP reports are organization-private by default.

If link sharing is introduced later, it must be an explicit resource with:

- creator;
- scope;
- expiration/revocation;
- access policy;
- audit log.

Do not make predictable public report URLs.

## 11. API/integration access

Paid integrations may later use service principals/API credentials.

Requirements:

- organization binding;
- scoped permissions;
- rotation/revocation;
- hashed/secure credential storage;
- rate limits;
- auditability.

Do not reuse human session tokens as long-lived integration credentials.

## 12. Security tests

At minimum, automated tests must prove:

- Org A cannot fetch Org B research by ID;
- Org A cannot fetch Org B upload/object;
- Org A cannot enumerate Org B resources;
- a worker cannot process resources outside its job scope;
- private evidence is never indexed in the global corpus;
- deleting/removing membership changes access immediately;
- public jurisprudence remains readable without exposing private joins.

## 13. Demo account model

For early QuisqueyaTech validation:

- authentication is still required;
- each tester receives or creates an organization;
- quota attaches to user and/or organization explicitly;
- no hidden "single global demo tenant" shortcut.

This avoids a prototype architecture that cannot safely become paid multi-company software.

## 14. MVP Definition of Done

Tenancy is ready when multiple organizations can concurrently submit jobs, uploads, and reports and automated negative tests demonstrate that cross-organization access is blocked below the UI/model layer.
