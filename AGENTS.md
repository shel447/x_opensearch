# Project Working Rules

## Repository Boundary

- Treat this directory as the standalone `x_opensearch` project repository.
- Do not stage or commit files from the parent `AI_Projects` repository when working on this project.

## GitHub Sync

- The intended GitHub repository is `shel447/x_opensearch`.
- After completing and verifying future project changes, automatically commit and push them to the GitHub `main` branch unless the user explicitly asks not to sync.
- Before syncing, run the relevant verification command for the touched area and include the result in the handoff.
- Do not commit local caches, dependency folders, temporary files, Docker/OpenSearch runtime data, credentials, or secrets.

## Project Artifacts

- Keep generated validation artifacts under `outputs/` when they are part of the deliverable.
- Keep OpenSearch mappings, mock data, scripts, documentation, and final Excel/JSON reports versioned together so the report can be reproduced.
