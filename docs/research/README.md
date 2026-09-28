# JurisNexo Research Library

This directory is the repository-owned bibliography for the agent, ingestion, retrieval, and legal-reasoning architecture.

The purpose is not to copy paper architectures wholesale. Each paper is mapped to one concrete JurisNexo hypothesis, one boundary that must remain deterministic, and one benchmark that can justify or reject the added complexity.

## Non-negotiable architectural interpretation

Research papers may influence how a model explores evidence, decomposes a task, retrieves candidates, verifies claims, or represents legal structure.

They do **not** grant an LLM database authority.

Production boundary:

    LLM / agent
        -> typed read capability or Document Workspace / Corpus API contract
        -> application service
        -> authorized persistence adapter
        -> PostgreSQL / object storage

Agents must never receive generic SQL, a database connection, ORM sessions, database credentials, or unrestricted repository objects. Benchmarks must exercise the same boundary.

## Paper set

The canonical machine-readable list is papers.json. Run download_papers.py to materialize PDFs into docs/research/papers/ and generate checksums.sha256.

### 1. Recursive Language Models

- **Paper:** Alex L. Zhang, Tim Kraska, Omar Khattab. *Recursive Language Models*. arXiv:2512.24601, 2025.
- **Source:** https://arxiv.org/abs/2512.24601
- **JurisNexo use:** large-document and deep-research exploration with external state, bounded tool calls, and recursive delegation.
- **Do not copy blindly:** arbitrary code/database access is not required for RLM-style behavior. JurisNexo should expose narrow capabilities over external state.
- **Benchmark:** quality/cost/latency/evidence traceability versus a non-recursive baseline.

### 2. DocETL

- **Paper:** Shreya Shankar, Tristan Chambers, Tarak Shah, Aditya G. Parameswaran, Eugene Wu. *DocETL: Agentic Query Rewriting and Evaluation for Complex Document Processing*. arXiv:2410.12189, 2024.
- **Source:** https://arxiv.org/abs/2410.12189
- **JurisNexo use:** staged document transformation and evaluator-driven optimization for difficult heterogeneous legal documents.
- **Do not copy blindly:** deterministic source identity, provenance, authorization, and commit gates stay outside the model optimizer.
- **Benchmark:** extraction completeness, precision, cost, throughput, and failure recovery against the current worker pipeline.

### 3. LOTUS / Semantic Operators

- **Paper:** Liana Patel, Siddharth Jha, Parth Asawa, Melissa Pan, Carlos Guestrin, Matei Zaharia. *Semantic Operators: A Declarative Model for Rich, AI-based Analytics Over Text Data*. arXiv:2407.11418, 2024.
- **Source:** https://arxiv.org/abs/2407.11418
- **JurisNexo use:** later, for bounded semantic filter/join/top-k operations over already-authorized normalized corpus slices.
- **Do not copy blindly:** semantic operators are not a reason to let an LLM issue arbitrary SQL or enumerate private tenant data.
- **Benchmark:** quality/cost/reproducibility versus deterministic retrieval + reranking and bounded agent loops.

### 4. KELLER

- **Paper:** Chenlong Deng, Kelong Mao, Zhicheng Dou. *Learning Interpretable Legal Case Retrieval via Knowledge-Guided Case Reformulation*. arXiv:2406.19760, 2024.
- **Source:** https://arxiv.org/abs/2406.19760
- **JurisNexo use:** decompose a long legal fact pattern into legally meaningful sub-facts before retrieval.
- **Do not copy blindly:** decomposition proposes search formulations; the Search/Corpus API still owns executable query semantics.
- **Benchmark:** critical/adverse authority recall and Recall@K versus a single-query baseline.

### 5. LegalSearchLM

- **Paper:** Chaeeun Kim, Jinu Lee, Wonseok Hwang. *LegalSearchLM: Rethinking Legal Case Retrieval as Legal Elements Generation*. arXiv:2505.23832, 2025.
- **Source:** https://arxiv.org/abs/2505.23832
- **JurisNexo use:** test whether legal-element-oriented query representations improve retrieval over lexical/embedding baselines.
- **Do not copy blindly:** generated legal elements are hypotheses with evidence/version metadata, not canonical source facts.
- **Benchmark:** critical/adverse authority recall, robustness, and false-relevance rate.

### 6. Legal Element-oriented Modeling

- **Paper:** Zhaowei Wang et al. *Legal Element-oriented Modeling with Multi-view Contrastive Learning for Legal Case Retrieval*. arXiv:2210.05188, 2022.
- **Source:** https://arxiv.org/abs/2210.05188
- **JurisNexo use:** motivate evidence-backed legal-element enrichment and structured case comparison.
- **Do not copy blindly:** do not require a closed legal-element ontology before the Dominican pilot proves value.
- **Benchmark:** analogous-case retrieval, distinction accuracy, and reviewer usefulness.

### 7. CaseGNN

- **Paper:** Yanran Tang, Ruihong Qiu, Yilun Liu, Xue Li, Zi Huang. *CaseGNN: Graph Neural Networks for Legal Case Retrieval with Text-Attributed Graphs*. arXiv:2312.11229, 2023.
- **Source:** https://arxiv.org/abs/2312.11229
- **JurisNexo use:** treat facts, issues, arguments, reasoning, holdings, outcome, and citations as distinct structural roles.
- **Do not copy blindly:** structural representation does not imply that JurisNexo needs a graph neural network.
- **Benchmark:** structured representation versus whole-case/chunk retrieval and role-confusion rate.

### 8. CaseLink

- **Paper:** Yanran Tang, Ruihong Qiu, Hongzhi Yin, Xue Li, Zi Huang. *CaseLink: Inductive Graph Learning for Legal Case Retrieval*. arXiv:2403.17780, 2024.
- **Source:** https://arxiv.org/abs/2403.17780
- **JurisNexo use:** citation/case-connectivity signals as retrieval and exploration features.
- **Do not copy blindly:** PostgreSQL citation edges and explicit traversal are the MVP baseline; learned graph ranking must earn its complexity.
- **Benchmark:** multi-hop discovery, later-treatment discovery, and critical-authority recall.

### 9. RAPTOR

- **Paper:** Parth Sarthi, Salman Abdullah, Aditi Tuli, Shubh Khanna, Anna Goldie, Christopher D. Manning. *RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval*. arXiv:2401.18059, 2024.
- **Source:** https://arxiv.org/abs/2401.18059
- **JurisNexo use:** possible hierarchical navigation for very long decisions where flat passage retrieval loses global context.
- **Do not copy blindly:** summaries are derived navigation aids and must point back to immutable source pages.
- **Benchmark:** within-case passage recall, evidence correctness, token use, latency, and cost.

### 10. LegalGraphRAG

- **Paper:** Zerui Chen et al. *LegalGraphRAG: Multi-Agent Graph Retrieval-Augmented Generation for Reliable Legal Reasoning*. arXiv:2605.28120, 2026.
- **Source:** https://arxiv.org/abs/2605.28120
- **JurisNexo use:** modern comparison point for hierarchical legal graphs and researcher/auditor/adjudicator separation.
- **Do not copy blindly:** this is an evaluation target, not permission to introduce a graph database or autonomous multi-agent swarm.
- **Benchmark:** compare only after simpler citation traversal and evidence auditing show measured gaps.

## How to use this library

A research-driven implementation proposal should answer four questions:

1. Which measured JurisNexo failure does this paper address?
2. What is the smallest adaptation that tests the idea?
3. Which deterministic/security boundaries remain unchanged?
4. Which frozen benchmark would prove that the adaptation is worth keeping?

If those questions cannot be answered, the paper belongs in the bibliography, not in the production architecture.

## Download policy

The downloader stores papers under docs/research/papers/ using stable arXiv IDs as filenames and writes SHA-256 checksums.

The PDF is reference material. The normative architecture remains the repository's own docs, tests, API contracts, migrations, and benchmarks.

Do not make CI depend on live arXiv availability. PDFs may be vendored for offline reference, but routine deterministic CI should not fetch the internet.
