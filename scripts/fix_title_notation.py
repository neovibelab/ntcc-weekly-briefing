#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""제목 표기 정규화 - 이미 적재된 radar_items의 한국어 제목만 고친다.

왜 필요한가 (2026-09-10 대시보드 실측)
  표기가 흔들려 둘이 망가졌다.
    읽기 - 推し活가 한 화면에서 추덕질·추시활·추시·추응 활동 넷으로 번역됐다
    사건 묶기 - 구글 Lyria 3.5 발표가 카드 두 장이다. Lyria와 라이리아로
      갈려 고유명사가 안 겹쳤다. 묶기는 제목 고유명사 3개 공유로 판정하므로
      표기가 곧 묶기 정확도다

왜 backfill_translate를 안 쓰나
  그쪽은 newsroom·newsletter 전용이고 summary를 summary_ko로 덮어쓴다.
  구글 뉴스 카드의 summary에는 시제 판정의 why가 들어 있어(2026-09-10)
  덮으면 카드 한 줄이 사라진다. 이 스크립트는 title만 PATCH한다.

원문이 없다는 한계
  gnews는 번역본만 저장하고 원문 제목을 안 남긴다. 그래서 원문에서 다시
  번역하지 못하고, 한국어 제목 안의 표기만 고친다. 무슨 말인지 확신이 안
  서면 그대로 둔다(고치기보다 두는 쪽이 안전하다).

환경변수: SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY
사용:
  python scripts/fix_title_notation.py --scan-only
  python scripts/fix_title_notation.py --dry-run [--limit N]
  python scripts/fix_title_notation.py [--limit N] [--collectors gnews,newsletter]
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys

import requests

from llm_json import parse_obj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              line_buffering=True)
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("notation")

DEFAULT_COLLECTORS = ["gnews"]

PROMPT = """아래는 이미 한국어로 번역된 뉴스 제목이다. **표기만** 바로잡아라.

고칠 것
1. 제품·서비스·회사·플랫폼 이름이 음차돼 있으면 원문 표기로 되돌린다.
   라이리아 3.5 -> Lyria 3.5 / 수노 -> Suno / 튠코어 -> TuneCore
2. 일본어·중국어 고유 개념어는 「통용 음차(원문)」 형태로 통일한다.
   추시활·추덕질·추시·추응 활동 -> 오시카츠(推し活)
   구쯔경제·곡자경제 -> 구쯔경제(谷子经济)
   웨이돤쥐·마이크로숏드라마 -> 마이크로 숏드라마(微短剧)
   이미 「오시카츠(推し活)」처럼 맞게 돼 있으면 그대로 둔다.
3. 가운데 줄표가 있으면 쉼표나 하이픈으로 바꾼다.

고치지 말 것
- 문장 구조·어순·내용은 손대지 않는다. 요약하지 않는다.
- 무슨 개념어인지 확신이 안 서면 **그대로 둔다.** 지어내지 않는다.
- 한국 고유명사·아티스트명은 그대로 둔다.

제목: {title}

바꿀 것이 없으면 changed=false로 답한다.
{{"changed": true, "title": "..."}}"""


def _base():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        log.error("SUPABASE_URL / SUPABASE_KEY 없음")
        sys.exit(1)
    return url.rstrip("/"), key


def fetch(collector: str) -> list[dict]:
    url, key = _base()
    h = {"apikey": key, "Authorization": "Bearer " + key}
    out, step, off = [], 1000, 0
    while True:
        r = requests.get(url + "/rest/v1/radar_items", headers=h, timeout=25, params={
            "select": "id,title,collector",
            "collector": "eq." + collector,
            "status": "in.(pending,picked)",
            "order": "created_at.desc", "limit": step, "offset": off,
        })
        r.raise_for_status()
        page = r.json()
        out += page
        if len(page) < step:
            return out
        off += step


def patch_title(item_id: str, title: str) -> int:
    url, key = _base()
    h = {"apikey": key, "Authorization": "Bearer " + key,
         "Content-Type": "application/json", "Prefer": "return=minimal"}
    r = requests.patch(url + "/rest/v1/radar_items?id=eq." + item_id,
                       headers=h, json={"title": title[:500]}, timeout=20)
    return r.status_code


def fix(client, title: str) -> str | None:
    m = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=300,
        messages=[{"role": "user", "content": PROMPT.format(title=title)}],
    )
    # 3층 방어 = scripts/llm_json.py. 모델이 JSON 뒤에 설명을 붙이면 통짜 파싱이
    # 「Extra data」로 깨진다(2026-09-10 실측 - 586건 중 84건째에서 연속 3회 중단).
    d = parse_obj(m.content[0].text.strip(),
                  {"changed": "bool", "title": "str"})
    if not d.get("changed"):
        return None
    new = (d.get("title") or "").strip()
    return new or None


def main() -> int:
    ap = argparse.ArgumentParser(description="제목 표기 정규화 (title만 갱신)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan-only", action="store_true", help="API 호출 없이 대상만 집계")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--collectors", default=",".join(DEFAULT_COLLECTORS))
    args = ap.parse_args()

    colls = [c.strip() for c in args.collectors.split(",") if c.strip()]
    items: list[dict] = []
    for c in colls:
        items += fetch(c)
    log.info("대상 %d건 %s", len(items),
             {c: sum(1 for i in items if i.get("collector") == c) for c in colls})
    if args.scan_only:
        return 0
    if args.limit:
        items = items[:args.limit]

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        log.error("ANTHROPIC_API_KEY 없음")
        return 1
    import anthropic
    client = anthropic.Anthropic(api_key=key)

    changed = same = failed = patch_fail = 0
    consec = 0
    for i, it in enumerate(items, 1):
        old = it.get("title") or ""
        try:
            new = fix(client, old)
            consec = 0
        except Exception as e:
            failed += 1
            consec += 1
            log.warning("실패(%d/%d · 연속 %d): %s", i, len(items), consec, str(e)[:60])
            if consec >= 3:
                log.error("연속 3회 실패 - 중단. 고침 %d · 동일 %d", changed, same)
                return 2
            continue
        if not new or new == old:
            same += 1
            continue
        if args.dry_run:
            log.info("[dry %d/%d]\n  전: %s\n  후: %s", i, len(items), old[:70], new[:70])
            changed += 1
            continue
        code = patch_title(it["id"], new)
        if code in (200, 204):
            changed += 1
            log.info("[%d/%d] %s", i, len(items), new[:64])
        else:
            patch_fail += 1
            log.warning("PATCH 실패 %s :: %s", code, it["id"][:8])

    log.info("표기 정규화 완료 - 고침 %d · 동일 %d · 분류실패 %d · 적재실패 %d%s",
             changed, same, failed, patch_fail, " (dry-run)" if args.dry_run else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
