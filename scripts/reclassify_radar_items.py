#!/usr/bin/env python3
"""
radar_items 일괄 재분류 — is_entertainment 1차 게이트 + topics 좁힘
================================================================
2026-06-19 도입. tech-issues가 순수 SaaS·반도체·엔터프라이즈 IT까지 흡수해
대시보드 "기술" 검색 결과가 광범위해진 문제를 누적분까지 정리한다.

수정 필드 (PATCH):
  - is_entertainment (BOOLEAN)
  - topics (TEXT[])  — tech-issues 정의 좁힘에 따라 일부 항목에서 빠질 수 있음
  - tags   (TEXT[])  — topics와 동기

호출:
  python scripts/reclassify_radar_items.py --dry-run
  python scripts/reclassify_radar_items.py --batch-size 50 --sleep-ms 250
  python scripts/reclassify_radar_items.py --only-unclassified
  python scripts/reclassify_radar_items.py --since-date 2026-06-01
  python scripts/reclassify_radar_items.py --collector vibe_search --max-items 100

환경변수:
  SUPABASE_URL · SUPABASE_KEY · ANTHROPIC_API_KEY
"""
from __future__ import annotations

import argparse
import datetime
import io
import logging
import os
import sys
import time
from pathlib import Path

import requests

from llm_json import parse_obj


def _load_local_env() -> None:
    """로컬 실행 시 인접 .env 두 곳에서 키 자동 로드 (GitHub Actions에선 no-op).
    탐색 순서: nvl-vibe-radar/.env(SUPABASE+ANTHROPIC) → claude_API/.env(ANTHROPIC)."""
    root = Path(__file__).resolve().parents[2]  # claude-NeoVibeLab/
    for rel in ("nvl-vibe-radar/.env", "claude_API/.env"):
        p = root / rel
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_local_env()

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TOPIC_KEYS = [
    "fan-behavior", "consumer-behavior", "ent-deals", "ip-business",
    "artist-ownership", "tech-issues", "taste-values",
]


# ── Supabase REST ─────────────────────────────────────────────────────────────

def _sb_base() -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise SystemExit("SUPABASE_URL 미설정")
    return f"{url}/rest/v1/radar_items"


def _sb_headers(extra: dict | None = None) -> dict:
    key = os.environ.get("SUPABASE_KEY", "")
    if not key:
        raise SystemExit("SUPABASE_KEY 미설정")
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def fetch_page(offset: int, limit: int, params_extra: dict) -> list[dict]:
    """range 헤더로 페이지네이션. select는 재분류에 필요한 컬럼만."""
    params = {
        "select": "id,title,summary,topics,tags,is_entertainment,collector,region,published_date",
        "order": "created_at.desc",
    }
    params.update(params_extra)
    headers = _sb_headers({"Range-Unit": "items", "Range": f"{offset}-{offset + limit - 1}"})
    r = requests.get(_sb_base(), headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def patch_item(item_id: str, patch: dict) -> int:
    headers = _sb_headers({"Prefer": "return=minimal"})
    r = requests.patch(
        _sb_base(), headers=headers,
        params={"id": f"eq.{item_id}"}, json=patch, timeout=15,
    )
    return r.status_code


# ── 분류 (Claude haiku) ───────────────────────────────────────────────────────

CLASSIFY_PROMPT = (
    "엔터·문화·소비 산업 기사를 분류해 JSON으로만 응답.\n\n"
    "제목: {title}\n요약: {summary}\n\n"
    "is_entertainment: 엔터·미디어·콘텐츠·팝 산업(음악·영상·게임·웹툰·공연·아티스트·"
    "IP·팬덤·소비 라이프스타일)과 직접 연결되면 true. 순수 SaaS·B2B 협업툴·반도체·"
    "엔터프라이즈 IT·일반 AI 모델/연구·핀테크·정치·일반 거시경제는 false. "
    "패션·뷰티·F&B·여행·리테일 같은 소비 라이프스타일은 true.\n"
    "topics: 해당되는 것 모두 (배열 0~3개) — fan-behavior(팬덤), consumer-behavior(소비), "
    "ent-deals(딜·거래), ip-business(IP비즈), artist-ownership(아티스트 권리), "
    "tech-issues(엔터·미디어·콘텐츠 산업을 흔드는 기술 변화에만 — 순수 SaaS·반도체·"
    "엔터프라이즈 AI는 제외), taste-values(세대 가로지르는 취향·가치)\n\n"
    '{{"is_entertainment": true, "topics": [...]}}'
)


def classify(title: str, summary: str, client) -> dict | None:
    """단건 분류. 실패 시 None 반환(skip — 기존 값 보존)."""
    try:
        prompt = CLASSIFY_PROMPT.format(title=title[:500], summary=(summary or "")[:1500])
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        # 3층 방어 = scripts/llm_json.py (레이더 llm_json.py와 쌍둥이).
        # topics는 배열이라 3층에서 못 건진다 - 그때는 빈 배열로 떨어진다.
        data = parse_obj(msg.content[0].text.strip(), {"is_entertainment": "bool"})
        topics = [t for t in (data.get("topics") or []) if t in TOPIC_KEYS]
        ie = data.get("is_entertainment")
        if isinstance(ie, str):
            ie = ie.strip().lower() in ("true", "1", "yes", "y", "예")
        # 누적분 재분류에선 모델이 명시하지 않으면 None — 보수적으로 변경 안 함이 안전하나,
        # 1차 게이트 도입 의도가 "엔터 여부 명확화"라 누락 시 True로 폴백 (게이트가 막지 않음).
        return {
            "topics": topics,
            "is_entertainment": bool(ie) if ie is not None else True,
        }
    except Exception as e:
        log.warning("분류 실패: %s", e)
        return None


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="radar_items 일괄 재분류")
    parser.add_argument("--batch-size", type=int, default=50, help="페이지 크기 (기본 50)")
    parser.add_argument("--max-items", type=int, default=0, help="최대 처리 건수 (0=무제한)")
    parser.add_argument("--sleep-ms", type=int, default=250, help="API 호출 간 대기 ms (기본 250)")
    parser.add_argument("--only-unclassified", action="store_true",
                        help="is_entertainment IS NULL 항목만")
    parser.add_argument("--since-date", type=str, default="",
                        help="published_date >= YYYY-MM-DD 인 항목만")
    parser.add_argument("--collector", type=str, default="",
                        help="특정 collector만 (vibe_search/newsletter/newsroom/manual)")
    parser.add_argument("--dry-run", action="store_true", help="DB 갱신 없이 분류 결과만 출력")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY 미설정")
        return 1

    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    filters: dict = {}
    if args.only_unclassified:
        filters["is_entertainment"] = "is.null"
    if args.since_date:
        filters["published_date"] = f"gte.{args.since_date}"
    if args.collector:
        filters["collector"] = f"eq.{args.collector}"

    sleep_s = max(0, args.sleep_ms) / 1000
    offset = 0
    processed = 0
    changed = 0
    skipped = 0
    stats = {"true": 0, "false": 0, "topics_shrunk": 0}

    log.info("재분류 시작 — filters=%s dry_run=%s", filters, args.dry_run)

    while True:
        try:
            rows = fetch_page(offset, args.batch_size, filters)
        except requests.HTTPError as e:
            log.error("조회 실패: %s — %s", e, e.response.text[:300] if e.response else "")
            return 1
        if not rows:
            break

        for it in rows:
            if args.max_items and processed >= args.max_items:
                break
            cls = classify(it.get("title", ""), it.get("summary", ""), client)
            processed += 1

            if cls is None:
                skipped += 1
                continue

            old_topics = set(it.get("topics") or [])
            new_topics = set(cls["topics"])
            new_ie = cls["is_entertainment"]
            old_ie = it.get("is_entertainment")

            ie_changed = (old_ie is None) or (bool(old_ie) != bool(new_ie))
            topics_changed = old_topics != new_topics

            if not ie_changed and not topics_changed:
                if sleep_s:
                    time.sleep(sleep_s)
                continue

            patch = {}
            if ie_changed:
                patch["is_entertainment"] = new_ie
                stats["true" if new_ie else "false"] += 1
            if topics_changed:
                patch["topics"] = sorted(new_topics)
                patch["tags"] = sorted(new_topics)
                if new_topics < old_topics:  # 진부분집합 — 좁아짐
                    stats["topics_shrunk"] += 1

            log.info(
                "[%s] %s | ie %s→%s | topics %s→%s",
                (it.get("collector") or "?")[:10],
                (it.get("title") or "")[:55],
                old_ie, new_ie,
                "·".join(sorted(old_topics)) or "-",
                "·".join(sorted(new_topics)) or "-",
            )

            if not args.dry_run:
                code = patch_item(it["id"], patch)
                if code in (200, 204):
                    changed += 1
                else:
                    log.warning("PATCH 실패 HTTP %d — %s", code, it["id"])

            if sleep_s:
                time.sleep(sleep_s)

        if args.max_items and processed >= args.max_items:
            log.info("max-items %d 도달 — 종료", args.max_items)
            break
        if len(rows) < args.batch_size:
            break
        offset += args.batch_size

    log.info(
        "완료 — 처리 %d · 변경 %d · 분류실패 스킵 %d · ent→true %d · ent→false %d · topics 축소 %d",
        processed, changed, skipped,
        stats["true"], stats["false"], stats["topics_shrunk"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
