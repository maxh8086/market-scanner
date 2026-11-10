# Rollback procedure

Applies to every task merged by the orchestrator loop. Read this before any merge.

## Rules

1. **Tag before every merge.** Before merging a task PR, tag the current `main` so there is a fixed point to return to:
   ```bash
   git tag pre-task-<N> origin/main
   git push origin pre-task-<N>
   ```
   `<N>` is the task number in `docs/progress/execution-ledger.md`.

2. **Merge commits only.** Use `gh pr merge <PR> --merge --delete-branch`. Never squash or rebase, because `git revert -m 1` needs a merge commit.

3. **Migrations and encrypted data need a down-step.** A task that adds a database migration, changes a table, or writes secrets under a new key or format must:
   - include a down-migration file or a documented manual reversal in its PR description;
   - take a database backup before the migration runs (`pg_dump` against the `scanner-postgres` container) and record the backup path in the ledger;
   - keep the master key file unchanged. Never regenerate it during a task.

4. **Record the rollback point in the ledger.** Each task entry in `execution-ledger.md` must list: the tag name, the merge commit sha, the PR number, and the backup path if one was taken.

## Undo a merged task (code only)

Replace `<MERGE_SHA>` with the merge commit on `main` (for example `579e9c9`):

```bash
git checkout main
git pull --ff-only origin main
git revert -m 1 <MERGE_SHA> --no-edit
git push origin main
```

This adds a new commit that undoes the PR. Nothing is force-pushed.

Then:
- reindex synaptree (`index_repository` with `/workspace/Market-Scanner`) and confirm the reverted symbols are gone;
- mark the task `reverted` in the ledger, with the revert commit sha and the reason.

## Recover the deleted branch

Deleting a branch does not delete its commits. The PR's commits stay reachable through the merge commit's second parent:

```bash
git branch recover/<name> <MERGE_SHA>^2
git push -u origin recover/<name>
```

## Re-apply a reverted task

Revert the revert once the fix is in. Find the revert commit sha in the ledger, then:

```bash
git revert <REVERT_SHA> --no-edit
```

Run the full offline suite before pushing.

## Full rollback to a tag

Only when several tasks must be undone together. Create a new branch from the tag and fast-forward `main` to it through a reviewed PR. Do not force-push `main`:

```bash
git checkout -b rollback/to-pre-task-<N> pre-task-<N>
git push -u origin rollback/to-pre-task-<N>
```

Open a PR from `rollback/to-pre-task-<N>` to `main` and merge it with `--merge`.

## What reverting code does not undo

- **Database tables and rows.** The revert removes the code, not the schema. Apply the task's down-migration, or restore from the backup in the ledger.
- **Encrypted rows.** Rows written under a new format can become unreadable by the reverted code. Restore from the backup if this happens.
- **External state.** Upstox, Screener and Telegram calls already made are not reversed.
- **The master key file.** Not in git. Do not delete or replace it as part of a rollback.
