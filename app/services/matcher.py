from __future__ import annotations

import re
import sqlite3

from app.models.schemas import MatchCandidate
from app.storage.database import list_creator_rows, load_analysis_from_row


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    english_terms = re.findall(r"[a-z0-9]+", lowered)
    return set(chinese_terms + english_terms)


def match_brief(conn: sqlite3.Connection, brand_brief: str, limit: int = 5) -> list[MatchCandidate]:
    brief_tokens = tokenize(brand_brief)
    candidates: list[MatchCandidate] = []

    for row in list_creator_rows(conn):
        analysis = load_analysis_from_row(row)
        searchable_parts = [
            analysis.nickname,
            analysis.bio,
            analysis.summary,
            " ".join(analysis.content_categories),
            " ".join(analysis.brand_fit_tags),
            " ".join(analysis.recent_post_titles),
        ]
        creator_tokens = tokenize(" ".join(searchable_parts))
        overlap = sorted(brief_tokens & creator_tokens)
        risk_penalty = min(len(analysis.risk_flags) * 0.08, 0.3)
        score = min(1.0, (len(overlap) * 0.18) + (0.12 if analysis.brand_fit_tags else 0.0))
        score = max(0.0, round(score - risk_penalty, 3))

        candidates.append(
            MatchCandidate(
                creator_id=int(row["creator_id"]),
                nickname=analysis.nickname,
                platform=analysis.platform,
                profile_url=analysis.profile_url,
                score=score,
                matched_signals=overlap[:8],
                risk_flags=analysis.risk_flags,
                summary=analysis.summary,
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:limit]
