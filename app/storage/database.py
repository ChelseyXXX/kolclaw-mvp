from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.core.config import DEFAULT_DB_PATH
from app.models.schemas import CreatorAnalysis


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS creators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            bio TEXT,
            summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS platform_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            profile_url TEXT NOT NULL UNIQUE,
            follower_count TEXT,
            account_status TEXT DEFAULT 'active',
            raw_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );

        CREATE TABLE IF NOT EXISTS content_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            platform_account_id INTEGER,
            title TEXT,
            content_url TEXT,
            category TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id),
            FOREIGN KEY (platform_account_id) REFERENCES platform_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS creator_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            tag_type TEXT NOT NULL,
            tag_value TEXT NOT NULL,
            source TEXT DEFAULT 'llm',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );

        CREATE TABLE IF NOT EXISTS performance_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            platform_account_id INTEGER,
            metric_name TEXT NOT NULL,
            metric_value TEXT NOT NULL,
            metric_period TEXT,
            source TEXT DEFAULT 'scraper',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id),
            FOREIGN KEY (platform_account_id) REFERENCES platform_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS selection_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            brand_brief TEXT NOT NULL,
            decision_status TEXT NOT NULL,
            decision_reason TEXT,
            operator_name TEXT,
            llm_score REAL,
            manual_score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );

        CREATE TABLE IF NOT EXISTS outreach_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            channel TEXT,
            contact_status TEXT NOT NULL,
            next_action TEXT,
            last_contacted_at TEXT,
            owner_name TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );

        CREATE TABLE IF NOT EXISTS risk_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER NOT NULL,
            risk_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            description TEXT,
            source TEXT DEFAULT 'llm',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        );
        """
    )
    conn.commit()


def save_creator_analysis(conn: sqlite3.Connection, analysis: CreatorAnalysis) -> int:
    existing = conn.execute(
        "SELECT creator_id FROM platform_accounts WHERE profile_url = ?",
        (analysis.profile_url,),
    ).fetchone()

    if existing:
        creator_id = int(existing["creator_id"])
        conn.execute(
            """
            UPDATE creators
            SET nickname = ?, bio = ?, summary = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (analysis.nickname, analysis.bio, analysis.summary, creator_id),
        )
        conn.execute(
            """
            UPDATE platform_accounts
            SET platform = ?, follower_count = ?, raw_json = ?
            WHERE profile_url = ?
            """,
            (
                analysis.platform,
                analysis.follower_count,
                analysis.model_dump_json(),
                analysis.profile_url,
            ),
        )
        _replace_related_records(conn, creator_id, analysis)
        conn.commit()
        return creator_id

    cursor = conn.execute(
        "INSERT INTO creators (nickname, bio, summary) VALUES (?, ?, ?)",
        (analysis.nickname or "unknown", analysis.bio, analysis.summary),
    )
    creator_id = int(cursor.lastrowid)
    account_cursor = conn.execute(
        """
        INSERT INTO platform_accounts
        (creator_id, platform, profile_url, follower_count, raw_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            creator_id,
            analysis.platform,
            analysis.profile_url,
            analysis.follower_count,
            analysis.model_dump_json(),
        ),
    )
    platform_account_id = int(account_cursor.lastrowid)
    _insert_related_records(conn, creator_id, platform_account_id, analysis)
    conn.commit()
    return creator_id


def _replace_related_records(conn: sqlite3.Connection, creator_id: int, analysis: CreatorAnalysis) -> None:
    account = conn.execute(
        "SELECT id FROM platform_accounts WHERE creator_id = ? AND profile_url = ?",
        (creator_id, analysis.profile_url),
    ).fetchone()
    platform_account_id = int(account["id"]) if account else None
    for table in ["content_samples", "creator_tags", "risk_records"]:
        conn.execute(f"DELETE FROM {table} WHERE creator_id = ?", (creator_id,))
    _insert_related_records(conn, creator_id, platform_account_id, analysis)


def _insert_related_records(
    conn: sqlite3.Connection,
    creator_id: int,
    platform_account_id: int | None,
    analysis: CreatorAnalysis,
) -> None:
    for title, url in zip_longest(analysis.recent_post_titles, analysis.recent_post_links):
        conn.execute(
            """
            INSERT INTO content_samples
            (creator_id, platform_account_id, title, content_url, category)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                creator_id,
                platform_account_id,
                title or "",
                url or "",
                analysis.content_categories[0] if analysis.content_categories else "",
            ),
        )

    for tag in analysis.content_categories:
        conn.execute(
            "INSERT INTO creator_tags (creator_id, tag_type, tag_value, source) VALUES (?, ?, ?, ?)",
            (creator_id, "content_category", tag, "llm"),
        )
    for tag in analysis.brand_fit_tags:
        conn.execute(
            "INSERT INTO creator_tags (creator_id, tag_type, tag_value, source) VALUES (?, ?, ?, ?)",
            (creator_id, "brand_fit", tag, "llm"),
        )
    for risk in analysis.risk_flags:
        conn.execute(
            """
            INSERT INTO risk_records
            (creator_id, risk_type, severity, description, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (creator_id, "profile_analysis", "medium", risk, "llm"),
        )


def zip_longest(left: Iterable[str], right: Iterable[str]) -> Iterable[tuple[str | None, str | None]]:
    left_list = list(left)
    right_list = list(right)
    size = max(len(left_list), len(right_list))
    for index in range(size):
        yield (
            left_list[index] if index < len(left_list) else None,
            right_list[index] if index < len(right_list) else None,
        )


def list_creator_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            c.id AS creator_id,
            c.nickname,
            c.bio,
            c.summary,
            pa.platform,
            pa.profile_url,
            pa.follower_count,
            pa.raw_json
        FROM creators c
        JOIN platform_accounts pa ON pa.creator_id = c.id
        ORDER BY c.updated_at DESC, c.id DESC
        """
    ).fetchall()


def load_analysis_from_row(row: sqlite3.Row) -> CreatorAnalysis:
    raw = row["raw_json"]
    if raw:
        return CreatorAnalysis.model_validate(json.loads(raw))
    return CreatorAnalysis(
        platform=row["platform"],
        profile_url=row["profile_url"],
        nickname=row["nickname"],
        bio=row["bio"],
        follower_count=row["follower_count"],
        summary=row["summary"],
    )
