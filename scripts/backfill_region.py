#!/usr/bin/env python3
"""백필 - 소스 고정 힌트로 region이 매겨진 기존 항목(기본 newsletter·newsroom·feed)의
region을 기사 내용 기준으로 재분류한다. 발신 매체 국적과 기사 내용 지역이 다른 문제 해결
(예: 한국 뉴스레터 Longblack의 글로벌·일본 기사가 전부 'korea'로 찍히던 것, 2026-06-23).

2026-09-10 지역 축 개편 이후로는 레거시 global-en 값을 12종으로 옮기는 통로이기도 하다.
vibe_search는 검색 프로파일 이름이 그대로 region으로 들어가 global-en이 남으므로,
`--collectors vibe_search`로 따로 훑어 재판정한다. region이 바뀌는 항목만 PATCH하고
status·title·summary·topics 등 다른 필드는 안 건드린다.

견고화: 단발 분류오류는 건너뛰고, 연속 3회 실패(크레딧 소진·키 누락)면 중단.

환경변수: SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY
사용:
  python scripts/backfill_region.py --scan-only          # API 호출 없이 대상 집계
  python scripts/backfill_region.py --dry-run [--limit N] # 재분류만, 쓰기 없음
  python scripts/backfill_region.py [--limit N]           # 실제 갱신
  python scripts/backfill_region.py --collectors vibe_search,gnews --dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# 기본 대상은 소스 힌트 기반 수집기다. vibe_search·gnews는 자기 시점에 지역을 정하지만
# 그 판정이 지역 축 개편(2026-09-10) 이전 값이거나 검색 프로파일 이름(global-en)에
# 묶여 있을 수 있어 --collectors로 명시 지정해 함께 훑을 수 있다.
DEFAULT_COLLECTORS = ["newsletter", "newsroom", "feed"]
KNOWN_COLLECTORS = ["newsletter", "newsroom", "feed", "interview", "vibe_search", "gnews"]
# 지역 12종 (2026-09-10 개편). 구 global-en이 살아있는 풀의 80%를 삼키는 잔여 범주였다.
# 표본 66건 재분류 - 북미 62% · 유럽 17% · 다국적 9% · 아시아 오분류 6%.
# global-en은 신규 저장하지 않는다. 재판정 결과로도 쓰지 않는다.
VALID = {
    "korea", "japan", "china", "southeast-asia",
    "north-america", "europe", "latin", "mena",
    "africa-ssa", "india-sa", "oceania", "multinational",
}
# 프롬프트 공통 문구 - newsletter_ingest·newsroom_ingest·interview_ingest·gnews_ingest와 같은 문장.
REGION_GUIDE = (
    "region: 이 기사가 주로 다루는 시장·지역을 내용 기준으로 하나만 고른다.\n"
    "  korea 한국 / japan 일본 / china 중국 / southeast-asia 동남아\n"
    "  north-america 북미(미국·캐나다) / europe 유럽(영국·독일·프랑스·북유럽·동유럽 등)\n"
    "  latin 라틴아메리카(스페인어권·브라질) / mena 중동·북아프리카\n"
    "  africa-ssa 사하라이남 아프리카 / india-sa 인도·남아시아 / oceania 호주·뉴질랜드\n"
    "  multinational 특정 국가 귀속 없는 다국적 발표·업계 일반론·글로벌 통계\n"
    "  기준 - 매체 국적이나 기업 본사가 아니라 기사 내용의 시장이다. "
    "한 기사에 여러 시장이면 비중이 큰 쪽 하나만 고른다. "
    "모르겠다고 multinational에 넣지 않는다. 이 칸이 잔여 범주가 되면 지역 축이 무의미해진다.\n"
)
MODEL = "claude-haiku-4-5-20251001"


def _base() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        log.error("SUPABASE_URL/SUPABASE_KEY 미설정")
        raise SystemExit(1)
    return url, key


def fetch_collector(collector: str, scope: str = "live") -> list[dict]:
    """scope="live"면 살아있는 것(pending·picked)만.

    기본을 live로 두는 이유 - radar_items 대부분이 filtered_out·archived이고
    그것들은 이미 걸러졌거나 소멸해 재판정할 값이 없다. classify_tense.py가
    같은 이유로 같은 기본값을 쓴다. 전수가 필요하면 --scope every.
    """
    url, key = _base()
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    out, step, off = [], 1000, 0
    while True:
        r = requests.get(f"{url}/rest/v1/radar_items", headers=h, timeout=20, params={
            "select": "id,title,summary,region,collector", "collector": f"eq.{collector}",
            "order": "created_at.desc", "limit": step, "offset": off,
            **({"status": "in.(pending,picked)"} if scope == "live" else {}),
        })
        r.raise_for_status()
        batch = r.json()
        out += batch
        if len(batch) < step:
            break
        off += step
    return out


def classify_region(title: str, summary: str) -> tuple[str | None, bool]:
    """제목·요약 → 내용 기준 지역 1개. 반환 (region|None, failed)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, True
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            "다음 기사가 주로 다루는 시장·지역을 하나만 골라 JSON으로만 응답.\n\n"
            + REGION_GUIDE +
            "  예 - 한국 매체가 전한 소니뮤직 도쿄 소식은 japan. "
            "빌보드의 스웨덴 레이블 인수 기사는 europe. "
            "IFPI 세계 음반시장 연간 집계는 multinational.\n\n"
            f"제목: {title}\n요약: {summary[:600]}\n\n"
            '{"region": "..."}'
        )
        msg = client.messages.create(model=MODEL, max_tokens=60,
                                     messages=[{"role": "user", "content": prompt}])
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        reg = (data.get("region") or "").strip()
        return (reg if reg in VALID else None), False
    except Exception as e:
        log.warning("region 분류 실패: %s", e)
        return None, True


def patch_region(item_id: str, region: str) -> int:
    url, key = _base()
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json", "Prefer": "return=minimal"}
    r = requests.patch(f"{url}/rest/v1/radar_items?id=eq.{item_id}", headers=h,
                       json={"region": region}, timeout=20)
    return r.status_code


def main() -> int:
    ap = argparse.ArgumentParser(description="newsletter·newsroom·feed region 내용 기준 재분류")
    ap.add_argument("--dry-run", action="store_true", help="재분류만, Supabase 쓰기 없음")
    ap.add_argument("--scan-only", action="store_true", help="API 호출 없이 대상 집계만")
    ap.add_argument("--limit", type=int, default=0, help="처리 상한(0=무제한)")
    ap.add_argument("--scope", choices=("live", "every"), default="live",
                    help="live=살아있는 것(pending·picked)만, every=전수")
    ap.add_argument("--collectors", default=",".join(DEFAULT_COLLECTORS),
                    help="쉼표 구분 수집기 목록. 알려진 값: " + ", ".join(KNOWN_COLLECTORS))
    args = ap.parse_args()

    collectors = [c.strip() for c in args.collectors.split(",") if c.strip()]
    unknown = [c for c in collectors if c not in KNOWN_COLLECTORS]
    if unknown:
        log.warning("모르는 수집기 %s - 그대로 조회한다", unknown)

    items: list[dict] = []
    for c in collectors:
        items += fetch_collector(c, args.scope)
    log.info("재분류 후보 %d건 | 수집기별 %s", len(items),
             {c: sum(1 for i in items if i.get("collector") == c) for c in collectors})

    if args.scan_only:
        return 0
    if args.limit:
        items = items[:args.limit]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY 미설정")
        return 1

    changed = same = skipped = patch_fail = 0
    consec_fail = 0
    for i, it in enumerate(items, 1):
        title = it.get("title") or ""
        summary = it.get("summary") or ""
        new_reg, failed = classify_region(title, summary)
        if failed:
            consec_fail += 1
            skipped += 1
            log.warning("분류 실패 건너뜀 (%d/%d · 연속 %d): %s", i, len(items), consec_fail, title[:42])
            if consec_fail >= 3:
                log.error("연속 %d회 실패 - 크레딧 소진/키 문제로 보고 중단. 변경 %d · 동일 %d",
                          consec_fail, changed, same)
                return 2
            continue
        consec_fail = 0
        cur = it.get("region")
        if not new_reg or new_reg == cur:
            same += 1
            continue
        if args.dry_run:
            log.info("[dry %d/%d] %s: %s → %s", i, len(items), title[:40], cur, new_reg)
            changed += 1
            continue
        code = patch_region(it["id"], new_reg)
        if code in (200, 204):
            changed += 1
            log.info("변경 %d/%d  %s → %s | %s", i, len(items), cur, new_reg, title[:42])
        else:
            patch_fail += 1
            log.warning("갱신 실패 HTTP %d: %s", code, title[:42])

    log.info("region 백필 완료 - 변경 %d · 동일 %d · 분류건너뜀 %d · 적재실패 %d%s",
             changed, same, skipped, patch_fail, " (dry-run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
