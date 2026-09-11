# Contributing to JurisNexo

## Branch model

JurisNexo currently uses trunk-based development with short-lived branches.

`main` is the canonical integration and deployable branch. Do not create a permanent `dev` or `development` branch until JurisNexo has a real staging environment whose lifecycle is intentionally different from production.

Create every new work branch from the latest `main`.

Recommended prefixes:

```text
feature/*
fix/*
hardening/*
docs/*
chore/*
```

Do not reuse a branch after its pull request has been merged. If additional work is required, create a fresh branch from the updated `main`.

## Pull requests

All normal changes should enter `main` through a pull request.

Before merge, the required CI aggregate must pass. Individual jobs may evolve over time; `CI aggregate` is the stable release gate.

The intended flow is:

```text
latest main
    -> short-lived branch
    -> pull request
    -> CI aggregate passes
    -> squash/approved merge into main
    -> merged branch is deleted automatically
```

A branch must not be deleted merely because its pull request was closed. Automatic cleanup runs only when GitHub reports that the pull request was actually merged.

## Automatic branch cleanup

`.github/workflows/branch-hygiene.yml` deletes merged head branches automatically when all of the following are true:

- the pull request was merged;
- the head branch belongs to this repository rather than a fork;
- the head branch is not the repository default branch;
- the GitHub Actions token has the required `contents: write` permission.

The cleanup is idempotent: if GitHub or another repository setting already deleted the branch, the workflow treats the branch as clean instead of failing.

## Main branch protection

The desired repository policy for `main` is:

- require a pull request before merge;
- require `CI aggregate` to succeed;
- disallow routine direct pushes;
- keep `main` as the default branch;
- keep force pushes disabled;
- keep branch deletion disabled for `main`;
- require branches to be updated with `main` when a materially stale branch could invalidate the CI result.

These are repository-level GitHub settings/rulesets. They are intentionally separate from application code and must be enabled in GitHub repository settings when administrative mutation access is available.

## When to introduce a `dev` branch

Do not introduce `dev` as ceremony. Add it only when it represents a real operational environment, for example:

```text
feature/* -> dev -> staging
                 -> release PR -> main -> production
```

At that point the branch must have an explicit deployment, QA, promotion, and migration policy. Until then, an additional long-lived integration branch increases drift and Alembic migration-conflict risk without providing a corresponding operational benefit.
