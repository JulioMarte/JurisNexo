# JurisNexo — MVP User Workflow and API Contract

## 1. Purpose

The MVP needs one unambiguous vertical slice from user action to finished research report. This document defines that slice so UI, API, workers, and research runtime converge on the same product behavior.

## 2. Primary user workflow

The default workflow is:

```text
sign in
 -> choose/create organization
 -> submit research question/fact pattern
 -> optionally attach private context
 -> choose standard/deep mode when enabled
 -> review interpreted research brief
 -> start research
 -> observe factual progress
 -> receive report
 -> open cited primary sources
 -> submit feedback
```

The product is report-first. Chat may later be added as a refinement surface, not as the primary workflow.

## 3. Research request form

Minimum fields:

- free-form legal question/fact pattern;
- optional title;
- optional date/court constraints;
- optional private uploads;
- optional notes on what the user is trying to establish or challenge.

The system may infer missing legal issues but must show the interpreted research question in the report.

## 4. Research modes

The MVP may begin with one mode. If two modes are exposed later:

### Standard

- smaller candidate/subagent budget;
- limited citation expansion;
- adverse search still required for material legal propositions;
- faster/cheaper.

### Deep

- larger candidate pool;
- broader citation/later-treatment expansion;
- more subagent review;
- stronger completion checklist.

"Standard" must never mean unsupported one-shot generation.

## 5. API resource model

Suggested top-level resources:

```text
POST   /organizations
GET    /organizations/:id

POST   /research-jobs
GET    /research-jobs/:id
POST   /research-jobs/:id/cancel
GET    /research-jobs/:id/events
GET    /research-jobs/:id/report

POST   /uploads
GET    /uploads/:id
DELETE /uploads/:id

GET    /cases/:id
GET    /cases/:id/pages
GET    /cases/:id/source

POST   /feedback
```

Exact framework/path conventions are replaceable; resource semantics are not.

## 6. Create research job contract

Conceptual request:

```json
{
  "organization_id": "...",
  "title": "optional",
  "query": "...",
  "constraints": {
    "courts": [],
    "date_from": null,
    "date_to": null
  },
  "upload_ids": [],
  "mode": "standard"
}
```

Conceptual response:

```json
{
  "job_id": "...",
  "state": "QUEUED",
  "created_at": "...",
  "resource_budget": {}
}
```

Authorization is evaluated server-side using the authenticated principal and active organization.

## 7. Research job representation

A research job should expose user-safe fields such as:

- ID;
- organization;
- creator;
- title;
- interpreted question/brief when available;
- state;
- progress counters;
- corpus scope;
- limitations encountered;
- created/started/completed times;
- report version;
- cost/usage summary where appropriate.

Do not expose hidden reasoning traces or raw secrets/provider payloads.

## 8. Progress events

Events should be factual, for example:

```text
brief.created
search.completed
case.reviewed
citation.expanded
adverse_search.completed
evidence.verified
research.limit_reached
report.completed
```

The UI may translate these into human language.

## 9. Case/source navigation

When the report cites a decision, the user should be able to:

- open the JurisNexo case record;
- see canonical metadata;
- navigate to cited page(s);
- view normalized text;
- open/download the primary source when permitted;
- distinguish source text from JurisNexo interpretation.

This interaction is core product functionality, not a later polish item.

## 10. Report representation

The canonical report should first exist as structured data plus rendered HTML.

Suggested sections:

- research question;
- short conclusion;
- strongest/highest authority;
- supporting authorities;
- adverse/conflicting authorities;
- material distinctions;
- jurisprudential evolution when supported;
- unresolved issues;
- research limitations;
- evidence table;
- corpus/freshness disclosure.

PDF export is a renderer of the canonical report, not the source of truth.

## 11. Evidence links

Every report claim that asserts a material legal proposition should reference one or more evidence IDs.

Evidence IDs resolve to:

- case;
- source artifact version;
- page(s)/passage;
- evidence role;
- verification state.

The frontend must not reconstruct citations from prose heuristically.

## 12. Feedback contract

After a report, users should be able to provide structured feedback:

- useful/not useful;
- expected authority missing;
- citation/interpretation incorrect;
- adverse authority missing;
- material distinction missed;
- estimated time saved;
- amount of additional research required;
- willingness to use again/pay;
- free-text notes.

Feedback should be attached to job/report version.

## 13. Demo quotas

Quota enforcement belongs in the API/application layer.

Potential counters:

- standard jobs/month;
- deep jobs/month;
- upload bytes;
- concurrent jobs;
- maximum document count per job;
- organization-level provider budget.

The UI should display remaining entitlement without revealing internal provider secrets/cost formulas.

## 14. Private uploads

Uploads must complete validation before use.

Suggested states:

- `UPLOADING`;
- `VALIDATING`;
- `PROCESSING`;
- `READY`;
- `REJECTED`;
- `DELETED`.

A research job should reference immutable upload versions. Deleting an upload must follow the retention/deletion contract while preserving only metadata necessary for audit where legally/operationally justified.

## 15. No hidden blocking UX

The system should not repeatedly require clarification for ordinary ambiguity.

When possible:

- infer a reasonable research interpretation;
- record it;
- proceed;
- disclose assumptions/limitations.

Block only when ambiguity makes meaningful research impossible or could materially cross jurisdiction/data-access boundaries.

## 16. MVP Definition of Done

The vertical slice is complete when a user in Organization A can submit a real question, receive observable progress, obtain an auditable report, open every material citation to primary evidence, provide feedback, and no resource in that flow is readable by Organization B.
