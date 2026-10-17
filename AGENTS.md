# Local development workflow

The owner requires one working copy: this repository, on `main`.

- Implement, integrate, build and run the app here. Do not create isolated
  successor repositories, candidate workspaces or worktrees unless the owner
  explicitly requests one.
- Routine local integration and restart belong to normal development; do not
  defer completed changes behind a separate installation or release slice.
- Use disposable fixtures/databases for tests without cloning the repository.
- Preserve existing uncommitted work, credentials, settings, user data and
  account/quota/hold records. Do not reset them to simplify development.
- Old candidate manifests and closeouts are historical evidence. Their former
  isolation/handover instructions are superseded by this workflow.
- Recoverable old versions are archived under `.local/dev-consolidation-20261016/`.
  They are not active development checkouts. Do not recreate them for new work.
