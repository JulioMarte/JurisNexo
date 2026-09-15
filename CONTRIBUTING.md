# Contributing to JurisNexo

## Canonical branch model

JurisNexo uses the same two-stage integration model as Request Engine:

```text
current development
        |
        v
one feature / fix / docs / hardening branch
        |
        v
PR -> development
        |
        v
CI aggregate passes
        |
        v
merge + delete branch
        |
        v
next branch starts from NEW development
        |
        v
release promotion PR
        |
        v
development -> main
```

`development` is the canonical integration branch. `main` is the validated release branch.

## `development`

All ordinary work starts from the latest `origin/development` and targets `development` through a pull request.

Recommended branch prefixes:

```text
feature/*
fix/*
hardening/*
docs/*
chore/*
```

Before starting work:

```bash
git fetch origin
git switch development
git pull --ff-only origin development
git switch -c <branch-name>
```

Do not infer the development base from GitHub's default branch. Agents and automation must resolve `development` explicitly.

Do not reuse a branch after its pull request has been merged. Start the next change from the new `development` HEAD.

## `main`

`main` is the release branch, not the normal development base.

Normal feature, fix, refactor, benchmark, documentation, ingestion, migration, and agent pull requests must not target `main` directly.

The normal promotion path to `main` is:

```text
development -> main
```

That promotion should happen only after the integrated `development` state has passed the required release evidence.

## Pull requests and CI

For ordinary work:

```text
latest development
    -> short-lived branch
    -> pull request to development
    -> CI aggregate passes
    -> merge
    -> merged branch is deleted automatically
```

CI also runs on pushes to `development` and `main`, so the exact integrated commit receives its own canonical run after merge.

`CI aggregate` is the stable required gate. Individual CI jobs may evolve, but the aggregate must represent the required repository checks.

## Development integration lane

`.github/development-integration-lane` records the short-lived branch currently claiming the ordinary integration lane.

A work branch that is being prepared for merge should set this file to exactly its own branch name, one line only. This makes the intended integration owner explicit and gives architecture tests a durable value to validate.

Exploratory parallel branches may exist, but they are provisional. They must reconcile with the newest `development` before being presented as merge-ready.

## Automatic branch cleanup

`.github/workflows/branch-hygiene.yml` deletes successfully merged short-lived branches automatically.

Cleanup must never delete:

- an unmerged branch;
- a branch from a fork;
- `main`;
- `development`.

The workflow is idempotent: if GitHub or another cleanup mechanism already removed the branch, cleanup succeeds without treating that state as an error.

## Expected GitHub repository policy

The intended rules are:

### `development`

- require pull requests for ordinary changes;
- require `CI aggregate` to pass;
- disallow routine direct pushes;
- disable force pushes;
- disable branch deletion.

### `main`

- accept normal promotion only from `development`;
- require the release/integration checks selected for promotion;
- disallow routine direct pushes;
- disable force pushes;
- disable branch deletion.

These protections are GitHub repository settings/rulesets and are separate from application code.

## Canonical topology

Allowed:

```text
feature-x -> development
# merge and delete feature-x
fix-y     -> development
# merge and delete fix-y

development -> main
```

Not allowed for normal work:

```text
feature-x -> main
fix-y     -> main
main      -> feature-x
```

The purpose of the model is simple: `development` is where changes are integrated and proven together; `main` is the clean release line.
