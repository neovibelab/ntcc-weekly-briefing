#!/usr/bin/env python3
"""
Supabase writer — vibe_search 결과를 radar_items 테이블에 저장.
nvl-vibe-radar의 REST API 패턴을 사용 (supabase-py 불필요, requests만 사용).

환경변수:
  SUPABASE_URL   Supabase 프로젝트 URL
  SUPABASE_KEY   Supabase anon key
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import uuid

import requests

log = logging.getLogger(__name__)

# 지역 12종 + 레거시 (2026-09-10 개편). send_report_drop.py의 _REGION_LABELS와
# 같은 문자열을 쓴다. global-en은 신규 저장하지 않지만 과거 archived 행이 수천 건이라
# 라벨은 살려 둔다.
REGION_LABELS = {
    "korea": "한국",
    "japan": "일본",
    "china": "중국",
    "southeast-asia": "동남아",
    "north-america": "북미",
    "europe": "유럽",
    "latin": "라틴아메리카",
    "mena": "중동·북아프리카",
    "africa-ssa": "아프리카",
    "india-sa": "인도·남아시아",
    "oceania": "오세아니아",
    "multinational": "다국적",
    "global-en": "글로벌(구)",  # 레거시
}


def _url(table: str = "radar_items") -> str:
    base = os.environ.get("SUPABASE_URL", "")
    return f"{base}/rest/v1/{table}"


def _headers(extra: dict | None = None) -> dict:
    key = os.environ.get("SUPABASE_KEY", "")
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    if extra:
        h.update(extra)
    return h


def _to_row(item: dict, region: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "title": (item.get("title") or "")[:500],
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "category": REGION_LABELS.get(region, region),
        "summary": (item.get("summary") or "")[:1000],
        "filter_verdict": "pass",
        "status": "pending",
        "tags": item.get("topics", []),
        "collector": "vibe_search",
        "region": region,
        "topics": item.get("topics", []),
        "is_entertainment": item.get("is_entertainment", True),
        "newsletter_fit": item.get("newsletter_fit", 0),
        "carousel_fit": item.get("carousel_fit", 0),
        "reliability_score": item.get("reliability", 0),
        "total_score": item.get("total_score", 0),
        # 기사 실제 발행일 (vibe_search가 검증해 넘김). 없으면 수집 시각 폴백.
        "published_date": item.get("published_date")
        or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def save_items(items: list[dict], region: str) -> int:
    """항목 리스트를 Supabase radar_items에 upsert. 저장 건수 반환."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        log.warning("SUPABASE_URL/KEY 미설정 — Supabase 저장 생략")
        return 0

    saved = 0
    for item in items:
        if not item.get("url"):
            continue
        row = _to_row(item, region)
        try:
            resp = requests.post(
                _url(), headers=_headers(), json=row, timeout=10
            )
            if resp.status_code in (200, 201):
                saved += 1
                log.info("Supabase 저장: %s", row["title"][:60])
            elif resp.status_code == 409:
                log.info("Supabase 중복 스킵: %s", row["url"][:80])
            else:
                log.warning(
                    "Supabase 저장 실패 (HTTP %d): %s",
                    resp.status_code, resp.text[:200],
                )
        except requests.RequestException as exc:
            log.warning("Supabase 연결 실패: %s", exc)

    log.info("[%s] Supabase 저장 완료: %d/%d건", region, saved, len(items))
    return saved


def fetch_recent_titles(days: int = 7) -> list[str]:
    """최근 N일 저장된 제목 목록 조회 (중복 제거용)."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        return []

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=days)
    ).isoformat()

    try:
        resp = requests.get(
            _url(),
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
            },
            params={
                "select": "title",
                "created_at": f"gte.{cutoff}",
                "collector": "eq.vibe_search",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return [r["title"] for r in resp.json() if r.get("title")]
    except Exception as exc:
        log.warning("Supabase 제목 조회 실패: %s", exc)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if "--test" in sys.argv:
        print("=== Supabase Writer 테스트 ===")
        test_item = {
            "title": "[TEST] Signal Collector 통합 테스트",
            "url": f"https://test.example.com/signal-test-{uuid.uuid4().hex[:8]}",
            "source": "테스트",
            "topics": ["tech-issues"],
            "summary": "통합 테스트 항목입니다.",
            "newsletter_fit": 1,
            "carousel_fit": 1,
            "reliability": 2,
            "total_score": 4,
        }
        n = save_items([test_item], "korea")
        print(f"저장: {n}건")

        titles = fetch_recent_titles(1)
        print(f"최근 1일 제목: {len(titles)}건")
        if titles:
            print(f"  최근: {titles[0][:60]}")
        print("=== 테스트 완료 ===")
