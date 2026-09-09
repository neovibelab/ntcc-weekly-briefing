#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""보류된 수집분을 나중에 일괄 판정한다.

왜 있나 (2026-09-10)
  Anthropic 계정의 지출 한도에 도달해 판정이 전부 400으로 죽었다(복구 10-01).
  수집은 RSS라 공짜이고 룩백이 3일뿐이라 멈추면 그 사이 기사를 영영 못 줍는다.
  그래서 gnews_ingest에 --no-gate를 넣어 판정 없이 적재하게 했고,
  이 스크립트가 한도가 풀린 뒤 그 행들을 다시 게이트에 태운다.

무엇을 고치나
  filter_verdict가 gate_deferred(판정 보류) 또는 classify_failed(판정 실패)인
  행을 읽어 gnews_ingest의 게이트를 그대로 다시 돌린다. 게이트 로직을
  복제하지 않고 import한다 - 두 벌이 되면 반드시 어긋난다.

  통과하면 title(한국어)·region·is_entertainment·status=pending으로 올린다.
  떨어지면 filtered_out에 non_ent로 남긴다.

  **status가 pending·filtered_out일 때만 건드린다.** picked·archived처럼
  사람이 손댄 상태는 텍스트도 상태도 그대로 둔다.

환경변수: SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY
사용:
  python scripts/regate.py --scan-only
  python scripts/regate.py --dry-run [--limit N]
  python scripts/regate.py [--limit N]
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gnews_ingest import GATE_DEFERRED, REGION_GUIDE, VALID_REGIONS, classify  # noqa: E402

# stdout 재래핑은 main()에서만 한다 - gnews_ingest가 import 시점에 이미 감싸므로
# 여기서 또 감싸면 앞 래퍼가 닫혀 I/O 오류가 난다(classify_tense가 같은 이유로 그렇게 한다).
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("regate")

TARGET_VERDICTS = (GATE_DEFERRED, "classify_failed")
# 사람이 손댄 상태는 안 건드린다. 판정이 없어 묻혀 있던 것만 되살린다.
TOUCHABLE_STATUS = ("pending", "filtered_out")


def _base():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        log.error("SUPABASE_URL / SUPABASE_KEY 없음")
        sys.exit(1)
    return url.rstrip("/"), key


def fetch() -> list[dict]:
    url, key = _base()
    h = {"apikey": key, "Authorization": "Bearer " + key}
    out, step, off = [], 1000, 0
    verdicts = ",".join(TARGET_VERDICTS)
    status = ",".join(TOUCHABLE_STATUS)
    while True:
        r = requests.get(url + "/rest/v1/radar_items", headers=h, timeout=25, params={
            "select": "id,title,source,region,status,filter_verdict,collector",
            "collector": "eq.gnews",
            "filter_verdict": "in.(%s)" % verdicts,
            "status": "in.(%s)" % status,
            "order": "created_at.desc", "limit": step, "offset": off,
        })
        r.raise_for_status()
        page = r.json()
        out += page
        if len(page) < step:
            return out
        off += step


def patch(item_id: str, fields: dict) -> int:
    url, key = _base()
    h = {"apikey": key, "Authorization": "Bearer " + key,
         "Content-Type": "application/json", "Prefer": "return=minimal"}
    r = requests.patch(url + "/rest/v1/radar_items?id=eq." + item_id,
                       headers=h, json=fields, timeout=20)
    return r.status_code


def main() -> int:
    ap = argparse.ArgumentParser(description="보류·실패한 gnews 수집분 재판정")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    items = fetch()
    tally = {}
    for it in items:
        tally[it.get("filter_verdict")] = tally.get(it.get("filter_verdict"), 0) + 1
    log.info("재판정 대상 %d건 %s", len(items), tally)
    if args.scan_only:
        return 0
    if args.limit:
        items = items[:args.limit]
    if not items:
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        log.error("ANTHROPIC_API_KEY 없음")
        return 1
    import anthropic
    client = anthropic.Anthropic(api_key=key)

    passed = dropped = failed = patch_fail = 0
    consec = 0
    for i, it in enumerate(items, 1):
        title = it.get("title") or ""
        try:
            d = classify(client, title, it.get("source") or "")
            consec = 0
        except Exception as e:
            failed += 1
            consec += 1
            log.warning("판정 실패(%d/%d · 연속 %d): %s", i, len(items), consec, str(e)[:70])
            if consec >= 3:
                log.error("연속 3회 실패 - 중단. 통과 %d · 탈락 %d", passed, dropped)
                return 2
            continue

        ie = bool(d.get("is_entertainment"))
        tko = (d.get("title_ko") or "").strip()
        reg = (d.get("region") or "").strip()
        fields = {
            "is_entertainment": ie,
            "status": "pending" if ie else "filtered_out",
            "filter_verdict": "pass" if ie else "non_ent",
        }
        if tko:
            fields["title"] = tko[:500]
        if reg in VALID_REGIONS:
            fields["region"] = reg

        if ie:
            passed += 1
        else:
            dropped += 1

        if args.dry_run:
            log.info("[dry %d/%d] %s %s | %s", i, len(items),
                     "O" if ie else "-", reg or "?", (tko or title)[:56])
            continue
        code = patch(it["id"], fields)
        if code not in (200, 204):
            patch_fail += 1
            log.warning("PATCH 실패 %s :: %s", code, it["id"][:8])

    log.info("재판정 완료 - 통과 %d · 탈락 %d · 실패 %d · 적재실패 %d%s",
             passed, dropped, failed, patch_fail, " (dry-run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
