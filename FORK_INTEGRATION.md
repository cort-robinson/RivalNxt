# Community fork integration

Integrated functional improvements from [EdwinSmayich/RivalNxt](https://github.com/EdwinSmayich/RivalNxt/tree/8140fc6e26ecd57e42f21d017c7ca67a8b1da37d), reviewed against our `e1bd53b` and their `8140fc6`. The original application is Rounak77382's work; the imported community features and their regression tests are EdwinSmayich's work, adapted here.

## Included

- Rebuild-safe manual Nexus IDs, preservation of previously identified downloads, and ISO-date filename parsing.
- Filename-based character tag lookup; sorting installed PAK/UTOC/UCAS files without re-extracting the library.
- SQLite-native restore, full snapshots, bounded JSON artwork exports, restore-point history and named loadouts.
- Persistent hidden files/tags, per-file notes, archive artwork import, image ordering, deduplication and storage normalization; linking preserves local artwork and tags, with orphan-recovery migrations.
- Bulk enable/disable/tag/delete and activity history; Nexus browsing and mod-ID suggestions.
- Incremental extraction fingerprints, Nexus freshness caching, paced concurrent metadata fetches, bounded parallel archive processing and accurate completed/skipped progress.
- Generated Tailwind CSS, responsive backup controls, light/dark contrast corrections, Windows virtual-environment builds, shared Python version constants, and actual-executable package verification.

## Adaptations and safeguards

- Our patch-compatibility API, panel, verified repair worker, source-preservation behavior and repair tests remain present. File mutations introduced by this integration use the same serialization lock as repair.
- Retention initially keeps all snapshots. The Backup dialog can select an automatic-snapshot limit; manual and unknown snapshot kinds are never automatically pruned. The active restore source and the new safety snapshot are protected during restore cleanup.
- Restore matches downloads by path across changed IDs and removes managed files introduced since the saved snapshot, including downloads absent from the restored database. Files still requested by another restored download and unmanaged files are preserved. Partial failures are reported.
- Snapshot schema upgrades happen before the live database is replaced. Failure to create the safety snapshot aborts the restore.
- Bulk enable preserves an active variant selection. Inactive multi-variant downloads require explicit choices; the UI reports these and keeps the selection visible. Hidden and invalid selections cannot be enabled through this endpoint.
- Folder sorting preflights the entire bundle, refuses duplicate destinations and incomplete IoStore pairs, validates paths and rolls back earlier moves if a later companion move fails.
- Extraction defaults to at most two concurrent downloads, with an eight-worker ceiling and bounded pending results. Database writes remain serial. Nexus request starts honor the rate-delay option.
- CI/release use Node 22. Packaging verification reads the executable itself, checking required Python modules, cryptography and the PAK repair worker; it does not trust an unrelated or stale build manifest.
- Application version remains 0.8.0. This integration does not create a release or adopt the other fork's repository branding.

## Validation

- Full Python suite: **696 passed** (one dependency deprecation warning).
- Frontend: **264 tests passed across 18 files**, including bundle splitting and the existing compatibility panel tests.
- TypeScript checking and Ruff passed; production Vite build passed.
- Tauri/Rust `cargo check --locked` passed (existing native-code warnings).
- PyInstaller backend build passed. Actual executable inspection confirmed required modules and the repair worker; a non-executable input was correctly rejected.
- Synthetic browser checks at 1280px and 800px in light/dark mode confirmed the backup retention control and compatibility/bulk surfaces, with no page exceptions or horizontal overflow. Screenshots are under `.codex/review-ui/` (local, ignored).
- Workflow YAML parsed successfully. Game execution, live Nexus behavior and installer deployment were not exercised.
- `graphify update .` was attempted but unavailable: Graphify is not installed and no `graphify-out` graph exists in this checkout.

Tests use temporary databases and synthetic files; no migration was applied to the user's live library during implementation and validation.
