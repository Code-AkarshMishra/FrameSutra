"""Small, local SQLite store for FrameSutra jobs, bookmarks and API limits."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "videolens.sqlite3"
_JSON_FIELDS = {"options", "steps", "result", "checkpoints", "stage_times"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                state TEXT NOT NULL,
                source TEXT NOT NULL,
                language TEXT NOT NULL,
                options TEXT NOT NULL DEFAULT '{}',
                steps TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                checkpoints TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                saved INTEGER NOT NULL DEFAULT 0,
                collection_name TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                stage_times TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS jobs_owner_created ON jobs(owner, created_at DESC);
            CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created_at);
            CREATE TABLE IF NOT EXISTS api_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS api_events_key_time ON api_events(event_key, created_at);
            CREATE TABLE IF NOT EXISTS bookmarks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                timestamp TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS bookmarks_job ON bookmarks(job_id, timestamp);
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chat_job_created ON chat_messages(job_id, created_at);
            CREATE TABLE IF NOT EXISTS study_sets (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(job_id, kind)
            );
            CREATE TABLE IF NOT EXISTS answer_cache (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                question_hash TEXT NOT NULL,
                model_id TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                PRIMARY KEY(job_id, question_hash, model_id)
            );
        """)
        # A single-process local worker cannot survive a process restart. Keep
        # the saved record and checkpoints so the user can retry it explicitly.
        conn.execute("UPDATE jobs SET state='interrupted', error='API restarted before this job finished.', updated_at=? WHERE state IN ('queued','running')", (now_iso(),))
        # MCQs are transient browser-session content and are never retained.
        conn.execute("DELETE FROM study_sets WHERE kind='quiz'")


def create_job(job_id: str, owner: str, source: str, language: str, options: dict[str, Any], checkpoints: dict[str, Any] | None = None) -> None:
    stamp = now_iso()
    with _connect() as conn:
        conn.execute("INSERT INTO jobs(id,owner,state,source,language,options,checkpoints,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (job_id, owner, "queued", source, language, json.dumps(options), json.dumps(checkpoints or {}, ensure_ascii=False), stamp, stamp))


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for key in _JSON_FIELDS:
        item[key] = json.loads(item[key]) if item.get(key) else ({} if key != "result" else None)
    item["saved"] = bool(item["saved"])
    item["cancel_requested"] = bool(item["cancel_requested"])
    return item


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return _decode(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def update_job(job_id: str, **changes: Any) -> None:
    if not changes:
        return
    assignments, values = [], []
    for key, value in changes.items():
        if key not in {"state", "steps", "result", "checkpoints", "error", "started_at", "finished_at", "saved", "collection_name", "cancel_requested", "stage_times", "updated_at"}:
            raise ValueError(f"Unsupported job field: {key}")
        assignments.append(f"{key}=?")
        values.append(json.dumps(value, ensure_ascii=False) if key in _JSON_FIELDS and value is not None else int(value) if key in {"saved", "cancel_requested"} else value)
    assignments.append("updated_at=?")
    values.extend([now_iso(), job_id])
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id=?", values)


def set_checkpoint(job_id: str, name: str, value: Any) -> None:
    with _connect() as conn:
        row = conn.execute("SELECT checkpoints FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return
        checkpoint = json.loads(row["checkpoints"] or "{}")
        checkpoint[name] = value
        conn.execute("UPDATE jobs SET checkpoints=?,updated_at=? WHERE id=?", (json.dumps(checkpoint, ensure_ascii=False), now_iso(), job_id))


def list_jobs(owner: str, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT ?", (owner, max(1, min(limit, 200)))).fetchall()
    items = [_decode(row) for row in rows]
    q = query.casefold().strip()
    if q:
        items = [item for item in items if q in str(item.get("source", "")).casefold() or q in str((item.get("result") or {}).get("title", "")).casefold()]
    return items


def count_jobs(states: tuple[str, ...]) -> int:
    marks = ",".join("?" for _ in states)
    with _connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM jobs WHERE state IN ({marks})", states).fetchone()[0])


def count_owner_jobs_since(owner: str, seconds: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND created_at>=?", (owner, cutoff)).fetchone()[0])


def count_other_jobs_for_source(owner: str, source_identity: str, language: str | None, exclude_job: str) -> int:
    with _connect() as conn:
        if language is None:
            rows = conn.execute("SELECT id,source,language,options FROM jobs WHERE id<>?", (exclude_job,)).fetchall()
        else:
            rows = conn.execute("SELECT id,source,language,options FROM jobs WHERE language=? AND id<>?", (language, exclude_job)).fetchall()
    return sum(1 for row in rows if (json.loads(row["options"] or "{}").get("source_hash") or row["source"]) == source_identity)


def has_other_job_with_transcript(transcript: str, exclude_job: str) -> bool:
    with _connect() as conn:
        rows = conn.execute("SELECT id,result,checkpoints FROM jobs WHERE id<>?", (exclude_job,)).fetchall()
    for row in rows:
        result = json.loads(row["result"] or "{}")
        checkpoints = json.loads(row["checkpoints"] or "{}")
        if result.get("transcript") == transcript or checkpoints.get("transcript") == transcript:
            return True
    return False


def allow_event(event_key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        count = int(conn.execute("SELECT COUNT(*) FROM api_events WHERE event_key=? AND created_at>=?", (event_key, cutoff)).fetchone()[0])
        if count >= limit:
            oldest = conn.execute("SELECT created_at FROM api_events WHERE event_key=? AND created_at>=? ORDER BY created_at LIMIT 1", (event_key, cutoff)).fetchone()
            retry = max(1, window_seconds - int((datetime.now(timezone.utc) - datetime.fromisoformat(oldest[0])).total_seconds())) if oldest else window_seconds
            return False, retry
        conn.execute("INSERT INTO api_events(event_key,created_at) VALUES(?,?)", (event_key, now_iso()))
        conn.execute("DELETE FROM api_events WHERE created_at<?", ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),))
        return True, 0


def put_bookmark(bookmark_id: str, job_id: str, timestamp: str, note: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO bookmarks(id,job_id,timestamp,note,created_at) VALUES(?,?,?,?,?)", (bookmark_id, job_id, timestamp, note[:1000], now_iso()))


def get_bookmarks(job_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        return [dict(row) for row in conn.execute("SELECT id,timestamp,note,created_at FROM bookmarks WHERE job_id=? ORDER BY timestamp", (job_id,)).fetchall()]


def delete_bookmark(bookmark_id: str, job_id: str) -> bool:
    with _connect() as conn:
        return conn.execute("DELETE FROM bookmarks WHERE id=? AND job_id=?", (bookmark_id, job_id)).rowcount > 0


def add_chat_message(job_id: str, role: str, content: str, sources: list[dict[str, Any]] | None = None) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO chat_messages(job_id,role,content,sources,created_at) VALUES(?,?,?,?,?)", (job_id, role, content, json.dumps(sources or [], ensure_ascii=False), now_iso()))


def get_chat_messages(job_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT role,content,sources,created_at FROM chat_messages WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
    return [{**dict(row), "sources": json.loads(row["sources"] or "[]")} for row in rows]


def get_study_set(job_id: str, kind: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM study_sets WHERE job_id=? AND kind=?", (job_id, kind)).fetchone()
    return json.loads(row["payload"]) if row else None


def save_study_set(job_id: str, kind: str, payload: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO study_sets(job_id,kind,payload,created_at) VALUES(?,?,?,?) ON CONFLICT(job_id,kind) DO UPDATE SET payload=excluded.payload,created_at=excluded.created_at", (job_id, kind, json.dumps(payload, ensure_ascii=False), now_iso()))


def delete_study_set(job_id: str, kind: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM study_sets WHERE job_id=? AND kind=?", (job_id, kind))


def get_answer_cache(job_id: str, question_hash: str, model_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT answer,sources FROM answer_cache WHERE job_id=? AND question_hash=? AND model_id=?", (job_id, question_hash, model_id)).fetchone()
    return {"answer": row["answer"], "sources": json.loads(row["sources"] or "[]")} if row else None


def save_answer_cache(job_id: str, question_hash: str, model_id: str, answer: str, sources: list[dict[str, Any]]) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO answer_cache(job_id,question_hash,model_id,answer,sources,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(job_id,question_hash,model_id) DO UPDATE SET answer=excluded.answer,sources=excluded.sources,created_at=excluded.created_at", (job_id, question_hash, model_id, answer, json.dumps(sources, ensure_ascii=False), now_iso()))


def delete_job(job_id: str, owner: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        if row is None:
            return None
        item = _decode(row)
        conn.execute("DELETE FROM jobs WHERE id=? AND owner=?", (job_id, owner))
        return item


def set_saved(job_id: str, owner: str, saved: bool) -> bool:
    with _connect() as conn:
        return conn.execute("UPDATE jobs SET saved=?,updated_at=? WHERE id=? AND owner=?", (int(saved), now_iso(), job_id, owner)).rowcount > 0


def jobs_with_collection(collection_name: str) -> int:
    with _connect() as conn:
        rows = conn.execute("SELECT collection_name FROM jobs WHERE state='complete' AND collection_name=?", (collection_name,)).fetchall()
        return len(rows)


def cleanup_expired_jobs(days: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE saved=0 AND updated_at<? AND state IN ('complete','error','cancelled','interrupted')", (cutoff,)).fetchall()
        items = [_decode(row) for row in rows]
        conn.executemany("DELETE FROM jobs WHERE id=?", [(item["id"],) for item in items])
        return items


initialize()
