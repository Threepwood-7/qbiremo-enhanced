# qBiremo Enhanced - Advanced qBittorrent GUI Client

A feature-rich PySide6 desktop client for remote qBittorrent management.

It combines:
- high-density torrent views,
- cancellable background API tasks,
- remote + local filter layering,
- deep details/edit panels,
- and operational tooling (taxonomy management, speed profile management, tracker analytics, session timeline, clipboard ingest, and export).

![qBiremo Enhanced Screenshot](qbiremo_enhanced_screenshot.jpg)

## Current Feature Set

### Main Workspace
- Unified main window with split layout:
  - top quick filter bar,
  - left filter tree,
  - torrent table,
  - bottom details tabs.
- Startup always opens maximized.
- Status bar with:
  - status text,
  - indeterminate progress indicator while background work runs,
  - live torrent count.
- Window title shows aggregate download/upload speeds using configurable format tokens:
  - `{down_text}`
  - `{up_text}`

### Torrent Table and Views
- Extended torrent column model mapped to qBittorrent WebUI fields.
- Built-in presets:
  - `Basic View`
  - `Medium View` (default)
- Per-column visibility toggles from `View -> Torrent Columns`.
- Save current visible-columns + widths as named views.
- Re-apply saved named views from menu.
- Fit visible columns to content (`View -> Fit Columns`).
- Multi-select enabled for bulk actions.
- Numeric-aware sorting for numeric columns.
- Enter/Return on selected torrent opens local torrent directory when path is available.
- Double-click row also opens local torrent directory.

### Filtering
- Quick filters (apply immediately):
  - Private: `All | Yes | No`
  - Name wildcard filter (`*`, `?`, implicit contains)
  - File wildcard filter against cached file paths
- Left filter tree sections:
  - Status
  - Categories
  - Tags
  - Size Groups (dynamic buckets)
  - Trackers
- Active filters are highlighted in the tree.
- Status/category/tag changes trigger fresh API fetches.
- Size/tracker/name/file/private filters apply locally on loaded data.
- File filter uses persistent content cache and updates automatically when cache refresh completes.

### Data Fetch Model
- Uses incremental `/sync/maindata` flow when no remote filters are selected.
- Automatically switches to `torrents_info(...)` when remote filters are selected:
  - `status_filter`
  - `category`
  - `tag`
  - `private`
- Maintains and merges `rid` state for incremental sync updates.
- Tracks and updates alt-speed-mode state from transfer API.

### Details Area (Tabs)
- `General` tab:
  - grouped rich text sections (`GENERAL`, `TRANSFER`, `PEERS`, `METADATA`).
  - one-click copy-to-clipboard.
- `Trackers` tab:
  - full per-torrent tracker rows with sortable dynamic columns.
- `Peers` tab:
  - full per-torrent peers rows with sortable dynamic columns.
  - context menu actions:
    - copy all peers info (TSV),
    - copy selected peer info (TSV),
    - copy selected peer `IP:port`,
    - ban selected peer.
- `Content` tab:
  - cached file/folder tree with size/progress/priority columns.
  - wildcard content filter for selected torrent.
  - Enter/Return and item activation open local file/folder if it exists.
- `Edit` tab (single-selected torrent only):
  - editable fields:
    - name,
    - auto management (tri-state),
    - category,
    - tags,
    - download/upload limits,
    - save path,
    - incomplete/download path.
  - sends only changed fields to API.
  - optional tag picker dialog.
  - local-path browse buttons shown only when target paths exist locally.

### Torrent and Session Actions
- File menu:
  - Add torrent dialog.
  - Export selected torrents to `.torrent` files.
- Edit menu torrent actions:
  - Start
  - Stop
  - Force Start
  - Recheck
  - Increase/Decrease/Top/Minimum queue priority
  - Remove
  - Remove and Delete Data
- Edit menu content submenu:
  - set priority (`Skip`, `Normal`, `High`, `Maximum`)
  - rename selected file/folder inside torrent
- Session-wide actions:
  - Pause Session
  - Resume Session

### Add Torrent Dialog
- Source supports:
  - local `.torrent` file,
  - magnet URL,
  - HTTP/HTTPS URL,
  - multi-line URL/magnet input.
- Basic options:
  - save path,
  - optional download path + `Use Download Path`,
  - category,
  - existing tags + extra tags,
  - rename,
  - cookie.
- Behavior options:
  - paused/stopped,
  - force start,
  - add to top,
  - skip checking,
  - sequential,
  - first/last piece priority,
  - auto torrent management,
  - root folder,
  - content layout,
  - stop condition.
- Limits/options:
  - upload/download limits,
  - ratio limit,
  - seeding time limit,
  - inactive seeding limit,
  - share-limit action.

### Tools Menu
- Clipboard monitor (toggle):
  - detects magnet links or torrent hashes copied to clipboard,
  - auto-queues add-torrent task,
  - deduplicates recently-seen payloads.
- Debug logging toggle:
  - logs API calls, responses, errors with timing.
- Edit `.ini` settings file (opens current QSettings INI path).
- Edit App Preferences dialog:
  - full preference tree editor with type-aware parsing,
  - changed-value highlighting,
  - apply only changed values.
- Manage Speed Limits dialog:
  - view/edit normal + alternative global limits,
  - toggle alt speed mode.
- Manage Tags and Categories dialog:
  - create/edit/delete categories,
  - optional incomplete path support,
  - create/delete tags.
- Tracker Health Dashboard:
  - aggregates trackers across current torrents,
  - shows fail/working counts, fail rate, dead marker, avg next announce, last error.
- Session Timeline:
  - stores rolling timeline samples,
  - graph for DL/UL/active torrents,
  - visual alt-mode bands,
  - refresh and clear history controls.

### Caching, Persistence, and Instance Isolation
- Persistent content cache stored as JSON.
- Cache path defaults to OS temp under `qbiremo_enhanced_temp/`.
- Cache filename is instance-scoped using deterministic host+port hash suffix.
- Cache older than 3 days is deleted on startup.
- `Clear Cache & Refresh` removes cache file and refreshes list.
- QSettings storage is forced to INI backend.
- Settings are instance-scoped by host+port-derived app name suffix.
- Persisted runtime settings include:
  - geometry/state,
  - splitters,
  - table header state,
  - hidden columns,
  - status filter,
  - auto-refresh settings,
  - display mode,
  - clipboard monitor toggle,
  - debug logging toggle,
  - named column views.

### Logging and Error Handling
- File-based logging only (no floating log panel in current build).
- Log file path can be configured and is instance-suffixed.
- Startup fatal exceptions are logged and the log file is opened automatically.
- Global exception hook logs unhandled exceptions and flushes file handler.
- Background task failures surface to status bar and log.

## Menu Reference

### File
- `Add Torrent...` (`Ctrl+O`)
- `Export Torrent...`
- `Exit` (`Ctrl+Q`, `Alt+X`)

### Edit
- `Start` (`Ctrl+S`)
- `Stop` (`Ctrl+P`)
- `Force Start` (`Ctrl+M`)
- `Recheck` (`Ctrl+R`)
- `Increase Priority in Queue` (`Ctrl++`)
- `Decrease Priority in Queue` (`Ctrl+-`)
- `Top Priority in Queue` (`Ctrl+Shift++`)
- `Minimum Priority in Queue` (`Ctrl+Shift+-`)
- `Remove` (`Del`)
- `Remove and Delete Data` (`Shift+Del`)
- `Pause Session` (`Ctrl+Shift+P`)
- `Resume Session` (`Ctrl+Shift+S`)
- `Content` submenu:
  - `Skip`
  - `Normal Priority`
  - `High Priority`
  - `Maximum Priority`
  - `Rename...`

### View
- `Open Log File`
- `Refresh` (`F5`)
- `Clear Cache & Refresh` (`Ctrl+F5`)
- `Human Readable` (toggle)
- `Torrent Columns` submenu (presets + per-column toggles + named views)
- `Fit Columns`
- `Enable Auto-Refresh (<seconds>)` (toggle)
- `Set Auto-Refresh Interval...`
- `Reset View`

### Tools
- `Enable Clipboard Monitor` (toggle)
- `Enable Debug logging` (toggle)
- `Edit .ini file`
- `Edit App Preferences`
- `Manage Speed Limits...`
- `Manage Tags and Categories`
- `Tracker Health Dashboard...`
- `Session Timeline...`

### Help
- `About`

## Installation

### Requirements
```bash
pip install -r requirements.txt
```

### Dev/Test Requirements
```bash
pip install -r requirements-dev.txt
```

### Optional: Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
```

## Configuration

### TOML File
Default file: `qbiremo_enhanced_config.toml`

Supported keys:
```toml
qb_host = "127.0.0.1"
qb_port = 8080
qb_username = "admin"
qb_password = "CHANGE_ME"

# Optional reverse-proxy/basic-auth layer (separate from qb API auth)
http_basic_auth_username = ""
http_basic_auth_password = ""

# Optional title format (tokens: {down_text}, {up_text})
title_bar_speed_format = "[D: {down_text}, U: {up_text}]"

# Optional log file path
# log_file = "qbiremo_enhanced.log"
```

Behavior notes:
- Legacy keys (`host`, `port`, `username`, `password`, `http_user`, `http_password`) are mapped and warned as deprecated.
- Unknown TOML keys are ignored with warnings.
- Runtime UI settings (`auto_refresh`, interval, window size/layout, display mode, default status) are QSettings-managed and not read from TOML.
- If `qb_host` includes a full URL with embedded userinfo, HTTP basic auth is extracted and sent via `Authorization` header.
- Environment fallback for HTTP basic auth:
  - `X_HTTP_USER`
  - `X_HTTP_PASS`

## Usage

### Run
```bash
python qbiremo_enhanced.py
```

### Run with custom config
```bash
python qbiremo_enhanced.py -c path\to\custom.toml
```

### Command-line options
```text
-c, --config-file    Path to config file (default: qbiremo_enhanced_config.toml)
-h, --help           Show help
```

## Testing

Run the test suite:
```bash
python -m pytest -q
```

Current tests cover:
- filters and cache behavior,
- menu wiring and shortcuts,
- table/view persistence,
- add-torrent payload construction,
- config validation and startup failure behavior,
- details/content actions,
- taxonomy/speed/preferences/analytics dialogs.

## Architecture Notes

- Background API operations run through cancellable worker tasks (`APITaskQueue`).
- Main data, details, and analytics use separate queues to reduce UI contention.
- Remote filtering is used when possible to reduce payload size.
- Local post-filtering handles quick text/file/size/tracker filters.
- Content filter accuracy depends on cached `torrents_files` snapshots.

## API Documentation References

- [qBittorrent WebUI API: Get Torrent List (`/api/v2/torrents/info`)](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-5.0)#get-torrent-list)
- [qbittorrent-api: `TorrentsAPIMixIn.torrents_info`](https://qbittorrent-api.readthedocs.io/en/latest/apidoc/torrents.html#qbittorrentapi.torrents.TorrentsAPIMixIn.torrents_info)
- [qbittorrent-api: Client API](https://qbittorrent-api.readthedocs.io/en/latest/apidoc/client.html)

## Credits

Built with:
- PySide6
- qbittorrent-api
- Python

Original qBiremo concept extended with:
- advanced filtering,
- robust table/view management,
- taxonomy/speed/preferences tooling,
- tracker and timeline analytics,
- stronger persistence and debugging workflow.

---

**Tags:** qbittorrent, qbittorrent-api, torrent, pyside6, qt, desktop-app, windows

---

## Legal Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE, INCLUDING, WITHOUT LIMITATION, ANY IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, NON-INFRINGEMENT, ACCURACY, OR QUIET ENJOYMENT. TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE AUTHORS, CONTRIBUTORS, MAINTAINERS, DISTRIBUTORS, AND AFFILIATED PARTIES SHALL NOT BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR ANY LOSS OF DATA, PROFITS, GOODWILL, BUSINESS OPPORTUNITY, OR SERVICE INTERRUPTION, ARISING OUT OF OR RELATING TO THE USE OF, OR INABILITY TO USE, THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. THIS SOFTWARE HAS BEEN DEVELOPED, IN WHOLE OR IN PART, BY "INTELLIGENT TOOLS"; ACCORDINGLY, OUTPUTS MAY CONTAIN ERRORS OR OMISSIONS, AND YOU ASSUME FULL RESPONSIBILITY FOR INDEPENDENT VALIDATION, TESTING, LEGAL COMPLIANCE, AND SAFE OPERATION PRIOR TO ANY RELIANCE OR DEPLOYMENT.
