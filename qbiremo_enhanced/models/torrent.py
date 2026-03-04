"""Typed torrent-related payload models."""

from typing import TypedDict


class TorrentFileEntry(TypedDict):
    """One torrent content-file row used by cache/content views."""

    name: str
    size: int
    progress: float
    priority: int


class TorrentCacheEntry(TypedDict):
    """Cached content entry for one torrent hash."""

    state: str
    files: list[TorrentFileEntry]


class TrackerRow(TypedDict, total=False):
    """One tracker row rendered in the Trackers tab."""

    url: str
    status: int
    msg: str
    tier: int
    num_peers: int
    num_seeds: int
    num_leeches: int
    downloaded: int
    next_announce: int


class PeerRow(TypedDict, total=False):
    """One peer row rendered in the Peers tab."""

    peer_id: str
    ip: str
    port: int
    client: str
    flags: str
    progress: float
    dl_speed: int
    up_speed: int
    downloaded: int
    uploaded: int
    relevance: float
    country_code: str
    connection: str


class TrackerHealthRow(TypedDict):
    """Aggregated tracker health metrics for dashboard table rows."""

    tracker: str
    torrent_count: int
    row_count: int
    working_count: int
    failing_count: int
    fail_rate: float
    dead: bool
    avg_next_announce: str
    last_error: str


class SessionTimelineSample(TypedDict):
    """One sampled timeline point used by session graph views."""

    ts: float
    down_bps: int
    up_bps: int
    active_count: int
    alt_enabled: bool
