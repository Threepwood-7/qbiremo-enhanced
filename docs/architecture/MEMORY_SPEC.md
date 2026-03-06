# qbiremo_enhanced Memory Spec

This document defines architecture invariants for the `qbiremo_enhanced` package.
It is the reference for dependency direction, controller ownership, and startup/runtime
contracts that must remain stable during refactors.

## 1. Dependency Graph

```text
python -m qbiremo_enhanced
  -> src/qbiremo_enhanced/__main__.py
  -> src/qbiremo_enhanced/main_window.py:main()

src/qbiremo_enhanced/__init__.py
  -> re-exports main() from main_window

src/qbiremo_enhanced/main_window.py
  -> config_runtime
  -> constants
  -> controllers
  -> dialogs
  -> tasking
  -> utils
  -> models.config
  -> models.torrent

src/qbiremo_enhanced/controllers/__init__.py
  -> re-exports domain controller classes

src/qbiremo_enhanced/controllers/network_api.py
  -> constants
  -> tasking
  -> types
  -> utils
  -> models.config
  -> models.torrent

src/qbiremo_enhanced/controllers/filter_table.py
  -> constants
  -> utils

src/qbiremo_enhanced/controllers/details_content.py
  -> utils
  -> models.torrent
  -> widgets

src/qbiremo_enhanced/controllers/actions_taxonomy.py
  -> constants
  -> dialogs
  -> types
  -> utils

src/qbiremo_enhanced/controllers/session_ui.py
  -> constants
  -> dialogs
  -> utils
  -> models.torrent

src/qbiremo_enhanced/controllers/base.py
  -> constants
  -> TYPE_CHECKING import of main_window only

src/qbiremo_enhanced/dialogs.py
  -> utils
  -> models.torrent

src/qbiremo_enhanced/tasking.py
  -> constants
  -> types
  -> TYPE_CHECKING import of main_window only

src/qbiremo_enhanced/config_runtime.py
  -> constants
  -> utils
  -> models.config

src/qbiremo_enhanced/utils.py
  -> constants
  -> models.config

Leaf/shared modules:
  constants.py
  types.py
  models/config.py
  models/torrent.py
  widgets.py
```

## 2. Dependency Direction Rules

1. `main_window.py` is the composition root and owns wiring.
2. `controllers/*` and `dialogs.py` must not import `main_window.py` at runtime.
3. `controllers/base.py` may reference `MainWindow` only under `TYPE_CHECKING`.
4. `config_runtime.py` and `utils.py` must stay UI-agnostic (no widget lifecycle ownership).
5. Shared contracts live in `constants.py`, `types.py`, and `models/*`.
6. New modules must follow the same one-way direction toward shared leaf modules.

## 3. Controller Responsibilities

| Controller | Responsibility |
|---|---|
| `NetworkApiController` | qBittorrent connection setup, API fetch/mutation tasks, cache load/save/refresh flows, API payload normalization. |
| `FilterTableController` | Filter-tree state, filter matching logic, torrent table rendering/sorting/column visibility, filter count/highlight refresh. |
| `DetailsContentController` | Selected-torrent detail rendering, peers/trackers tables, content tree population and content-priority operations. |
| `ActionsTaxonomyController` | User action orchestration: add/remove/pause/resume flows, taxonomy actions, speed/profile dialogs, launch-new-instance actions. |
| `SessionUiController` | Session-level UI state: timers, status/progress updates, timeline sampling, lifecycle hooks (`eventFilter`, `closeEvent`). |

## 4. MainWindow Delegation Contract

1. `MainWindow` constructs controller classes in `_initialize_controllers`.
2. Controller methods are installed onto `MainWindow` via `_install_controller_methods`.
3. `eventFilter` and `closeEvent` are explicit delegates to `SessionUiController`.
4. `MainWindow` remains the owner of widgets and persistent UI state.
5. `WindowControllerBase` proxies attribute access/assignment to the owning `MainWindow`.
6. Controller methods must treat `self` as `MainWindow` state through that proxy model.

## 5. Startup Boundary Contracts

1. Entrypoint chain is fixed:
   `__main__.py` -> `main_window.main()` -> `QApplication` -> `MainWindow`.
2. Startup sequence in `main_window.main()` must remain:
   parse args -> load config/issues -> acquire instance lock -> setup logging ->
   install global exception hook -> validate/normalize config -> create app/window -> event loop.
3. `acquire_instance_lock` may auto-increment `instance_counter` when lock is held.
4. `_setup_logging` must set `config["_log_file_path"]` and return a live `FileHandler`.
5. `_install_exception_hooks` must flush handler output for unhandled exceptions and at exit.
6. `main_window.main()` keeps one process-boundary broad catch to log fatal startup errors and open the log file.

## 6. Runtime Boundary Contracts

1. `APITaskQueue` is latest-wins:
   new tasks cancel the active worker and coalesce to one pending replacement.
2. Stale and cancelled worker completions/errors are ignored by identity checks.
3. Exactly one worker-thread boundary broad catch remains in `Worker.run`.
4. UI updates happen on the Qt thread via queue signal callbacks, not from worker bodies.
5. Controller task methods return normalized envelopes via `api_task_result(...)`.
6. Recoverable runtime failures use narrowed exception sets:
   `RECOVERABLE_CONTROLLER_EXCEPTIONS`, `RECOVERABLE_TASK_QUEUE_EXCEPTIONS`,
   and `RECOVERABLE_API_CALL_EXCEPTIONS`.

## 7. Refactor Guardrails

1. Keep dependency direction unchanged or update this spec in the same change.
2. When moving methods between controllers, preserve the owner/controller boundary and queue semantics.
3. Do not introduce new module-level mutable globals for UI/runtime state.
4. If adding a new domain controller, document:
   module dependencies, owned responsibilities, and boundary behavior in this file.
