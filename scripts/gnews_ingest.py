#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""구글 뉴스 RSS 수집기 (collector='gnews', 2026-09-02 신설).

대표가 브라우저 첫 화면으로 쓰던 구글 뉴스 커스텀 검색을 자동 수집으로 옮긴다.
질의 정본 = nvl-vibe-radar/google-news-queries.md (18질의 실측 확정
+ 2026-09-10 신흥시장 5질의 = 23).

**vibe_search와 다른 것** - vibe_search는 Anthropic web_search 도구로 검색+분석을
한 번에 하고, 이쪽은 RSS를 그대로 받는다. 키가 필요 없고 쿼터가 없다.
대신 분류(엔터 여부·좌표·시제)는 따로 붙여야 한다.

**질의는 2단어 이내** - 실측에서 다단어 AND가 통째로 죽었다.
  music catalog                                30건
  music catalog acquisition                     2건
  music catalog acquisition merger investment    0건
질의를 정교하게 쓰면 수확이 사라진다. 넓게 걷고 판정에서 좁힌다.

환경변수:
  SUPABASE_URL / SUPABASE_KEY
  ANTHROPIC_API_KEY        엔터 게이트용(없으면 미분류로 filtered_out)
  GNEWS_LOOKBACK_DAYS      기본 3 (매일 실행 + URL upsert 중복제거라 겹쳐도 안전)

사용: python scripts/gnews_ingest.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import datetime
import html
import io
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
import uuid

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                              line_buffering=True)
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("gnews")

LOOKBACK = int(os.environ.get("GNEWS_LOOKBACK_DAYS", "3"))
UA = "Mozilla/5.0 (compatible; NVLVibeRadar/1.0)"

# (요인, 이름, 질의, hl, gl, ceid) - 정본은 nvl-vibe-radar/google-news-queries.md
# 요인 힌트는 radar의 GRID_FACTORS(IP·포맷·테크·자본·정책·교차산업·교차정체성) + 넓은 산업
# 스캔용 "기존"뿐이다. 2026-09-10에 붙인 신흥시장 5질의도 요인 없는 넓은 산업 스캔이라
# "기존"을 쓴다. 새 요인 어휘를 만들면 radar 격자와 어긋난다.
QUERIES = [
    ("기존",       "미국·레이블", "record label",                   "en-US", "US", "US:en"),
    ("기존",       "일본·IP",       "音楽 IP",                          "ja",    "JP", "JP:ja"),
    ("IP",         "IP·영어",       "music IP licensing catalog",       "en-US", "US", "US:en"),
    ("IP",         "IP·한국",       "음악 IP 라이선스",                 "ko",    "KR", "KR:ko"),
    ("포맷",       "포맷·한국",     "숏폼 음악",                        "ko",    "KR", "KR:ko"),
    ("테크",       "테크·영어",     "AI music technology tools",        "en-US", "US", "US:en"),
    ("테크",       "테크·중국",     "AI 音乐",                     "zh-CN", "CN", "CN:zh-Hans"),
    ("자본",       "자본·영어",     "music catalog",                    "en-US", "US", "US:en"),
    ("자본",       "자본·일본",     "音楽 買収",                        "ja",    "JP", "JP:ja"),
    ("정책",       "정책·중국",     "音乐 版权",                        "zh-CN", "CN", "CN:zh-Hans"),
    ("IP",         "IP·중국",       "文创 IP",                          "zh-CN", "CN", "CN:zh-Hans"),
    ("포맷",       "포맷·중국",     "微短剧",                           "zh-CN", "CN", "CN:zh-Hans"),
    ("자본",       "자본·중국",     "音乐 融资",                        "zh-CN", "CN", "CN:zh-Hans"),
    ("정책",       "정책·한국",     "음악 저작권 정책",                 "ko",    "KR", "KR:ko"),
    ("테크",       "테크·한국",     "AI 음악",                          "ko",    "KR", "KR:ko"),
    ("교차산업",   "교차·한국",     "웹툰 IP",                          "ko",    "KR", "KR:ko"),
    ("교차정체성", "정체성·한국",   "팬덤 경제",                        "ko",    "KR", "KR:ko"),
    ("정책",       "정책·영어",     "music copyright policy regulation","en-US", "US", "US:en"),
    ("정책",       "정책·일본",     "音楽 著作権 政策",                 "ja",    "JP", "JP:ja"),
    ("포맷",       "포맷·일본",     "TikTok 音楽",                      "ja",    "JP", "JP:ja"),
    ("테크",       "테크·일본",     "AI 音楽",                          "ja",    "JP", "JP:ja"),
    ("교차정체성", "정체성·일본",   "推し活",                           "ja",    "JP", "JP:ja"),
    ("교차산업",   "교차·일본",     "ゲーム 音楽",                      "ja",    "JP", "JP:ja"),
    ("교차산업",   "교차·중국",     "潮玩 市场",                        "zh-CN", "CN", "CN:zh-Hans"),
    ("교차정체성", "정체성·중국1",  "虚拟偶像",                         "zh-CN", "CN", "CN:zh-Hans"),
    ("교차정체성", "정체성·영어",   "music fandom",                     "en-US", "US", "US:en"),
    ("포맷",       "포맷·영어",     "TikTok music",                     "en-US", "US", "US:en"),
    ("교차산업",   "교차·영어",     "game soundtrack",                  "en-US", "US", "US:en"),
    ("교차정체성", "정체성·중국2",  "谷子经济",                         "zh-CN", "CN", "CN:zh-Hans"),
    # 신흥시장 5질의 (2026-09-10 추가). 전부 현지어다. 영어 `music industry`를 지역
    # 에디션에 넣으면 같은 국제 기사가 복제되는 것을 실측으로 확인해 넣지 않았다.
    # 괄호는 2026-09-10 실측 최근 2개월 건수.
    ("기존",       "신흥·중동아랍어", "صناعة الموسيقى",                 "ar",    "AE", "AE:ar"),        # 63
    ("기존",       "신흥·나이지리아", "Afrobeats",                       "en-NG", "NG", "NG:en"),       # 66
    ("기존",       "신흥·멕시코",     "industria musical",               "es-419", "MX", "MX:es-419"),  # 49
    ("기존",       "신흥·인도",       "music label India",               "en-IN", "IN", "IN:en"),       # 37
    ("기존",       "신흥·브라질",     "indústria musical",               "pt-BR", "BR", "BR:pt-419"),   # 34
]

# 폴백 전용 (2026-09-10). 원래는 이 표가 region을 정했는데, 구글 뉴스 에디션(gl)은
# 독자의 위치지 기사 내용의 시장이 아니다. 미국판 결과에 유럽·다국적 기사가 섞여 있어
# 틀렸다. 지금은 엔터 게이트 haiku가 내용 기준으로 판정하고(호출 수 불변),
# 그 판정이 없거나 값이 이상할 때만 이 표로 떨어진다.
REGION_BY_GL = {
    "US": "north-america", "KR": "korea", "JP": "japan", "CN": "china",
    "AE": "mena", "NG": "africa-ssa", "MX": "latin", "IN": "india-sa", "BR": "latin",
}

# 지역 12종 (2026-09-10 개편). 구 global-en이 살아있는 풀의 80%를 삼키는 잔여 범주였다.
# global-en은 신규 저장하지 않는다.
VALID_REGIONS = {
    "korea", "japan", "china", "southeast-asia",
    "north-america", "europe", "latin", "mena",
    "africa-ssa", "india-sa", "oceania", "multinational",
}
# 프롬프트 공통 문구 - newsletter_ingest·newsroom_ingest·interview_ingest·backfill_region과 같은 문장.
REGION_GUIDE = (
    "region: 이 기사가 주로 다루는 시장·지역을 하나만 고른다.\n"
    "  korea 한국 / japan 일본 / china 중국 / southeast-asia 동남아\n"
    "  north-america 북미(미국·캐나다) / europe 유럽(영국·독일·프랑스·북유럽·동유럽 등)\n"
    "  latin 라틴아메리카(스페인어권·브라질) / mena 중동·북아프리카\n"
    "  africa-ssa 사하라이남 아프리카 / india-sa 인도·남아시아 / oceania 호주·뉴질랜드\n"
    "  multinational 여러 시장에 동시에 걸리는 발표이거나 전 세계 집계·업계 일반론\n"
    "  판정 순서 - (1) 기사에 시장이 드러나면(발매국·규제·행사 장소·소비자) 그 시장. "
    "(2) 안 드러나고 한 기업·인물·작품의 소식이면 그 주체의 본거지를 쓴다. "
    "OpenAI·엔비디아·넷플릭스·워너뮤직의 자체 소식은 north-america, "
    "빌리빌리는 china, 스포티파이는 europe이다. "
    "(3) (1)(2)로 못 정할 때만 multinational.\n"
    "  매체 국적은 근거가 아니다. 한국 뉴스레터가 쓴 일본 기사는 japan이다. "
    "multinational을 모르겠다는 뜻으로 쓰지 않는다. 이 칸이 잔여 범주가 되면 "
    "지역 축이 무의미해진다.\n"
)


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def fetch(q, hl, gl, ceid) -> list[dict]:
    url = ("https://news.google.com/rss/search?q=%s&hl=%s&gl=%s&ceid=%s"
           % (urllib.parse.quote(q), hl, gl, ceid))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    out = []
    for it in re.findall(r"<item>(.*?)</item>", raw, re.S):
        g = lambda tag: (re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), it, re.S) or [None, ""])[1]
        out.append({"title": strip_tags(g("title")), "link": strip_tags(g("link")),
                    "source": strip_tags(g("source")), "date": strip_tags(g("pubDate"))})
    return out


def parse_date(s: str):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = datetime.datetime.strptime(s.strip(), fmt)
            return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)
        except Exception:
            continue
    return None


GATE = """엔터·문화 산업 신호로 수집할 가치가 있는지 판정해 JSON으로만 응답.

is_entertainment 판정 질문은 하나다.
**이 사건이 음악·엔터의 생산·유통·소비 중 하나를 바꾸는가.**

  생산 - 누가 무엇을 만드나 (창작·제작·권리·자본)
  유통 - 어떻게 닿나 (플랫폼·포맷·유통망·정책)
  소비 - 어떻게 쓰이나 (팬덤·소비 행태·취향·정체성)

셋 중 하나라도 바꾸면 true.

**소재가 음악이 아니어도 된다.** 굿즈·완구·서브컬처·패션·뷰티 소비가 엔터
소비 행태를 바꾸면 true다. **반대로 소재가 음악이어도 바꾸는 것이 없으면
false다** - 지역 공연 고지, 채용 공고, 행사 등록 안내, 시상식 결과 나열,
단순 주가·실적 숫자, 개인 신변 잡기가 그렇다.

**소재 목록으로 판정하지 않는다.** 목록은 늘 샌다. 위 질문 하나로만 본다.
순수 SaaS·B2B·반도체·엔터프라이즈 IT·핀테크·정치·군사는 셋 중 무엇도
바꾸지 않으므로 false다. 온라인 도박·카지노 광고성 기사도 false다.

title_ko: 제목을 자연스러운 한국어로(한국어면 그대로). 제품·서비스·회사·플랫폼 이름은 **원문 표기 그대로** 둔다(Lyria·Suno·Gemini·TuneCore를 음역하지 않는다). 일본어·중국어 고유 개념어는 **음차(원문)** 형태로 쓴다(오시카츠(推し活) · 구쯔경제(谷子经济) · 마이크로 숏드라마(微短剧)). 같은 대상을 매번 같은 표기로 쓴다 - 표기가 흔들리면 같은 사건이 안 묶인다.
**가운데 줄표를 쓰지 않는다** - 쉼표나 하이픈으로.

{region_guide}  예 - 나이지리아 아프로비츠 레이블 계약 기사는 africa-ssa.
  스웨덴 레이블 인수 기사는 europe. IFPI 세계 음반시장 연간 집계는 multinational.

제목: {title}
출처: {source}

{{"is_entertainment": true, "title_ko": "...", "region": "..."}}"""


# 판정 보류 표식 (2026-09-10). classify_failed(판정하려다 실패)와 다르다.
# 이쪽은 「판정을 미뤘다」이고, scripts/regate.py가 나중에 이 값을 찾아 처리한다.
GATE_DEFERRED = "gate_deferred"


def _is_usage_limit(exc) -> bool:
    """Anthropic 지출 한도 오류인가. 한도면 재시도해도 소용없으니 즉시 보류로 돌린다."""
    s = str(exc)
    return "usage limit" in s.lower() or "regain access" in s.lower()


def classify(client, title: str, source: str) -> dict:
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=300,
        # temperature는 2026-09-10에 뺐다. 최신 SDK(anthropic 1.x)가 이 인자를
        # 받지 않아 2026-09-02 신설 이후 수집분 530건이 전건 classify_failed로
        # 떨어졌다. 같은 사고를 09-06에 app.py·classify_tense.py에서 고쳤는데
        # 이 파일만 다른 저장소라 빠져 있었다.
        messages=[{"role": "user", "content": GATE.format(
            title=title, source=source, region_guide=REGION_GUIDE)}],
    )
    raw = msg.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    d = json.loads(raw)
    return d if isinstance(d, dict) else {}


def existing_urls(sb_url: str, key: str) -> set:
    """최근 30일 gnews URL - RSS는 매일 같은 기사를 다시 준다."""
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=30)).isoformat()
    h = {"apikey": key, "Authorization": "Bearer " + key}
    out, offset = set(), 0
    while True:
        p = {"select": "url", "collector": "eq.gnews", "created_at": "gte." + since,
             "order": "url.asc", "limit": "1000", "offset": str(offset)}
        r = requests.get(sb_url.rstrip("/") + "/rest/v1/radar_items", headers=h, params=p, timeout=30)
        r.raise_for_status()
        page = r.json()
        out |= {x.get("url") for x in page if x.get("url")}
        if len(page) < 1000:
            return out
        offset += len(page)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="질의당 상한(시험용)")
    ap.add_argument("--no-gate", action="store_true",
                    help="판정을 건너뛰고 수집만 한다(한도 소진 시)")
    args = ap.parse_args()

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_KEY", "")
    if not (sb_url and sb_key):
        log.error("SUPABASE_URL / SUPABASE_KEY 없음")
        return 1

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK)
    seen = set() if args.dry_run else existing_urls(sb_url, sb_key)
    log.info("최근 30일 기수집 gnews URL %d건", len(seen))

    picked, per = [], []
    for factor, name, q, hl, gl, ceid in QUERIES:
        try:
            items = fetch(q, hl, gl, ceid)
        except Exception as e:
            per.append((name, q, 0, 0, str(e)[:40]))
            continue
        fresh = []
        for x in items:
            d = parse_date(x.get("date") or "")
            if not d or d < cutoff:
                continue
            u = x.get("link") or ""
            if not u or u in seen:
                continue
            seen.add(u)
            x["factor_hint"] = factor
            # 게이트 haiku가 내용 기준으로 판정한 값으로 나중에 덮인다. 여기 값은 폴백.
            x["region_fallback"] = REGION_BY_GL.get(gl, "multinational")
            fresh.append(x)
        if args.limit:
            fresh = fresh[:args.limit]
        picked += fresh
        per.append((name, q, len(items), len(fresh), ""))

    print("%-14s %-30s %6s %6s" % ("질의", "검색어", "전체", "신규"))
    print("-" * 62)
    for name, q, a, f, err in per:
        print("%-14s %-30s %6d %6d %s" % (name, q[:29], a, f, err))
    print("-" * 62)
    print("룩백 %d일 · 신규 %d건" % (LOOKBACK, len(picked)))

    if not picked:
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = None
    if args.no_gate:
        log.warning("--no-gate - 판정을 건너뛰고 수집만 한다")
    elif key:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    else:
        log.warning("ANTHROPIC_API_KEY 없음 - 게이트 없이 filtered_out으로 적재")

    rows, kept, gl_fallback = [], 0, 0
    deferred = bool(args.no_gate)
    for x in picked:
        ie, tko, reg = None, "", ""
        if client:
            try:
                d = classify(client, x["title"], x.get("source") or "")
                ie = d.get("is_entertainment")
                tko = (d.get("title_ko") or "").strip()
                reg = (d.get("region") or "").strip()
            except Exception as e:
                if _is_usage_limit(e):
                    # 한도는 재시도해도 안 풀린다. 보류로 돌리고 수집은 계속한다.
                    if not deferred:
                        log.warning("지출 한도 도달 - 이후 전건 판정 보류로 적재한다")
                    deferred = True
                    client = None
                else:
                    log.warning("분류 실패: %s", str(e)[:70])
        if reg not in VALID_REGIONS:
            reg = x["region_fallback"]
            gl_fallback += 1
        is_ent = bool(ie) if ie is not None else False
        if is_ent:
            kept += 1
        rows.append({
            "id": str(uuid.uuid4()),
            "title": (tko or x["title"])[:500],
            "url": x["link"],
            "source": x.get("source") or "Google News",
            "category": "gnews",
            "collector": "gnews",
            "summary": "",
            "region": reg,
            "topics": [],
            "tags": [x["factor_hint"]],
            "is_entertainment": is_ent,
            "status": "pending" if is_ent else "filtered_out",
            "filter_verdict": ("pass" if is_ent else (GATE_DEFERRED if (deferred and ie is None) else ("non_ent" if ie is not None else "classify_failed"))),
            "total_score": 0,
        })

    failed = sum(1 for r in rows if r["filter_verdict"] == "classify_failed")
    print("게이트 통과 %d / %d건 (분류 실패 %d · region gl 폴백 %d)"
          % (kept, len(rows), failed, gl_fallback))
    # 게이트가 통째로 죽으면 실패로 끝낸다 (2026-09-10 신설). 전건 실패인데도
    # exit 0이라 워크플로가 매일 success로 찍혔고, 530건이 쌓이는 동안 아무도 몰랐다.
    # 보류(--no-gate·한도)는 의도된 상태라 실패로 치지 않는다.
    gate_dead = (not deferred) and client is not None and rows and failed == len(rows)
    if args.dry_run:
        for r in rows[:20]:
            print("  [%s] %-14s %s" % ("O" if r["is_entertainment"] else "-",
                                       r["region"], r["title"][:52]))
        print("\n--dry-run - 쓰지 않았다")
        return 0

    h = {"apikey": sb_key, "Authorization": "Bearer " + sb_key,
         "Content-Type": "application/json",
         "Prefer": "resolution=merge-duplicates,return=minimal"}
    wrote = 0
    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        r = requests.post(sb_url.rstrip("/") + "/rest/v1/radar_items",
                          headers=h, json=chunk, timeout=60)
        if r.status_code >= 300:
            log.error("적재 실패 %s :: %s", r.status_code, r.text[:160])
            continue
        wrote += len(chunk)
    print("%d건 적재 (pending %d · filtered_out %d)"
          % (wrote, kept, wrote - kept))
    if gate_dead:
        log.error("엔터 게이트 전건 실패 - 분류가 죽었다. 적재는 했으나 전부 filtered_out이다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
