# JurisNexo — Product Vision and MVP

## 1. Product thesis

JurisNexo exists to reduce the time and uncertainty involved in Dominican jurisprudential research.

The MVP is intentionally narrower than a general legal AI platform. It should solve one economically meaningful problem well:

> Given a legal question, fact pattern, pleading, or decision, investigate relevant jurisprudence, identify supporting and adverse authority, compare material facts and holdings, verify every important proposition against primary sources, and return an auditable research report.

The product should behave like a research workflow, not like a conversational toy.

## 2. Initial positioning

JurisNexo should begin as an experimental product under QuisqueyaTech rather than as an independent company or brand requiring its own full go-to-market machinery.

Suggested initial delivery surface:

- `quisqueyatech.com/jurisnexo`, or
- `jurisnexo.quisqueyatech.com`.

The first release should be a controlled demo. Early users may receive free or tightly limited research credits in exchange for structured feedback.

The purpose of this stage is not scale. It is evidence.

We need to learn:

- Do lawyers trust the reports enough to use them as a starting point?
- How much research time is actually saved?
- How often does JurisNexo miss a materially important precedent?
- How often are citations and descriptions correct?
- Which legal matters produce the clearest value?
- Do users prefer reports, search, chat, API access, or integrations?
- Will firms pay for repeated usage?
- What price is justified by demonstrated time savings?

A standalone brand, domain, dedicated sales operation, and broader feature set should come later only if these questions produce favorable evidence.

## 3. The MVP customer

Primary early users:

- solo practitioners;
- small and medium law firms;
- in-house legal teams with recurring Dominican legal research needs;
- legal researchers or advanced law students acting under professional supervision.

The MVP should not attempt to satisfy every legal workflow. It should optimize for professionals who currently spend meaningful time searching, opening, reading, comparing, and citing jurisprudence.

## 4. The first job to be done

The first high-value job is:

> "Before I rely on a legal position, show me the strongest current precedent supporting it, the strongest precedent against it, how the relevant cases differ, and where each proposition is stated in the official source."

That job combines time savings and risk reduction.

The user is not merely buying search results. The user is buying a reduction in manual research effort and a lower probability of overlooking important adverse authority.

## 5. Primary MVP output

### Precedent & Adverse Authority Report

A completed report should contain, when evidence exists:

1. Research question and interpreted legal issues.
2. Scope and filters used.
3. Current apparent jurisprudential position.
4. Highest-authority relevant decisions.
5. Supporting decisions.
6. Adverse or conflicting decisions.
7. Material factual or legal distinctions.
8. Relevant citation chain or origin of the doctrine.
9. Evolution over time when material.
10. Open questions or unresolved conflicts.
11. Confidence assessment.
12. Evidence table with source, page/paragraph when available, and link to the primary document.
13. Explicit statement of research limitations.

The report should distinguish clearly between:

- facts stated in a decision;
- arguments made by parties;
- holdings or conclusions of the court;
- model inference;
- unresolved interpretation.

## 6. MVP corpus

The first corpus should be deliberately constrained.

Recommended initial priority:

- Supreme Court of Justice (SCJ);
- Constitutional Court (TC).

A narrower legal domain should be selected for the earliest evaluation set if full-corpus ingestion becomes an obstacle. Breadth must not come at the expense of provenance and retrieval quality.

Future sources may include:

- Courts of Appeal;
- Courts of First Instance;
- Superior Administrative Court;
- legislation and regulations;
- administrative resolutions;
- doctrine and secondary sources.

These are explicitly post-MVP unless required by the first validated use case.

## 7. What the MVP is not

The MVP is not:

- a replacement for a lawyer;
- an autonomous legal adviser to the public;
- a case outcome predictor;
- a pleading generator as its primary product;
- a CRM;
- a billing platform;
- a practice-management suite;
- a generic chat interface over PDFs;
- a promise of exhaustive legal coverage before coverage has been measured.

## 8. Free demo and commercial progression

### Stage A — private validation

Users: trusted lawyers and close professional contacts.

Access: free.

Goal: observe actual research tasks and collect qualitative feedback.

### Stage B — public controlled demo

Access: limited free research jobs per user or organization.

Possible constraints:

- monthly research credits;
- restricted corpus;
- limited deep-research jobs;
- no API or integrations;
- retained reports for a limited period.

Goal: measure activation, repeated use, completion rate, report usefulness, and demand.

### Stage C — paid validation

Potential paid value:

- additional research credits;
- deeper research runs;
- larger uploaded case files;
- team workspaces;
- persistent research history;
- exports;
- API access;
- integrations;
- organization-specific document collections;
- priority processing.

Pricing should be derived from real usage and time saved, not selected before validation.

## 9. Multi-tenant requirement

Even the demo should model organizations explicitly.

A user may belong to one or more organizations. Research jobs, uploads, generated reports, private notes, and billing entitlements belong to an organization.

Public jurisprudence can be shared globally. Private customer data cannot.

The system must never use one tenant's private documents, queries, annotations, or research outputs to answer another tenant's request unless there is an explicit future opt-in mechanism.

## 10. Product success criteria

The MVP succeeds only if evidence shows that it creates professional value.

Primary success signals:

- lawyers complete real research work with it;
- repeat usage occurs without prompting;
- reports materially reduce manual research time;
- users verify rather than rebuild the research from scratch;
- citation correctness is high;
- critical precedent misses are acceptably low;
- some users are willing to pay for additional usage or integrations.

Vanity metrics such as total documents indexed, total prompts, or generated words are secondary.

## 11. Product principle

The core promise should remain:

> JurisNexo helps a legal professional discover, compare, challenge, and verify jurisprudential authority. It does not ask the professional to trust the model; it shows the evidence.
