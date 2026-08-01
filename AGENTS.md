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
