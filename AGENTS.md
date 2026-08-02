# Repository Working Agreement

## Repository boundary

- This repository is the only write target.
- `C:\Users\jjk00\Documents\GitHub\horse_racing` is read-only reference material.
- Never create, modify, delete, commit, or push files in the reference repository.

## Continuity documents

When the current project state is needed to plan or perform a task, read:

1. `docs/progress.md`
2. `docs/decision_log.md`
3. `docs/experiment_log.md`

After completing a major project milestone, update the relevant documents:

- `progress.md`: completed work, current work, and recommended next work
- `decision_log.md`: important decisions or design changes, rationale, and date
- `experiment_log.md`: experiment, result, interpretation, and next experiment idea

Append new dated decisions and experiments. Do not rewrite historical entries merely because a later
decision supersedes them.

## Git push authorization

- Commit completed work when requested or when the agreed workflow calls for a milestone commit.
- Push to a remote only when the user explicitly instructs Codex to push.
- A request to commit does not imply permission to push.

## Autonomous scope and proportional implementation

- Preserve immutable Raw evidence, API-key secrecy, Point-in-Time rules, lineage, and existing
  dataset grains.
- Within those safety boundaries, choose the simplest implementation that fully satisfies the
  task without requiring the user to approve routine technical details.
- Reuse existing SQL, Canonical tables, marts, functions, and analysis paths before adding a new
  layer or abstraction.
- Do not add a new data layer, document, CLI command, or test mechanically for every task. Add one
  only when it materially improves correctness, reproducibility, maintainability, or handoff.
- Keep analysis work minimal and decision-focused. Avoid unrelated refactoring and scope expansion.
- Match validation effort to the change's risk and surface area.
- Treat artifacts and data contracts that were sufficiently validated in an earlier completed stage
  as trusted inputs. Do not revalidate them from first principles in every downstream task.
- In follow-up work, focus validation on newly introduced behavior, regression risk, and the direct
  impact boundary of the current change. Reopen an inherited assumption only when new evidence or a
  detected inconsistency gives a concrete reason to do so.
- Update `progress.md`, `decision_log.md`, and `experiment_log.md` only for a major milestone or an
  actual project decision or experiment, not for routine edits.

## Discussion versus implementation

When the user raises a design or idea question, first state which route is more efficient:

- Recommend ChatGPT-first discussion for project direction, model selection, feature ideas,
  experiment design, portfolio planning, and decisions.
- Recommend direct Codex work for implementation, refactoring, SQL, tests, document generation,
  and bug fixes.

Use a concise statement such as:

- `이 내용은 ChatGPT에서 먼저 설계한 후 구현하는 것이 효율적입니다.`
- `바로 구현을 진행하는 것이 효율적입니다.`

Then continue according to the selected route and the user's instruction.
