#!/usr/bin/env python3
"""뉴스룸 수집기 — allowlist 기업 뉴스룸/블로그의 RSS·Atom 피드에서 최신 글을 가져와
분류 후 Supabase radar_items(collector='newsroom')에 적재. GitHub Actions 일일 cron.

런타임 의존: requests, anthropic (피드 파싱은 stdlib xml.etree — 외부 feedparser 불필요).
환경변수:
  SUPABASE_URL / SUPABASE_KEY
  ANTHROPIC_API_KEY          분류용(없으면 토픽·요약 없이 적재)
  NEWSROOM_LOOKBACK_DAYS     기본 7 (뉴스룸은 매일 발행 아님 — 저빈도 소스 포착 위해 넉넉히. URL dedup이라 겹쳐도 안전)
사용: python scripts/newsroom_ingest.py [--dry-run]
"""
from __future__ import annotations

import datetime
import html
import json
import logging
import os
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWLIST_PATH = os.path.join(os.path.dirname(HERE), "sources_newsrooms.json")
TOPIC_KEYS = [
    "fan-behavior", "consumer-behavior", "ent-deals", "ip-business",
    "artist-ownership", "tech-issues", "taste-values",  # 구 gen-z-lifestyle (2026-06-17 재정의)
]
# 지역 12종 (2026-09-10 개편). 구 global-en이 살아있는 풀의 80%를 삼키는 잔여
# 범주였다. 이름이 아니라 기준을 쪼갠다. global-en은 신규 저장하지 않는다.
VALID_REGIONS = {
    "korea", "japan", "china", "southeast-asia",
    "north-america", "europe", "latin", "mena",
    "africa-ssa", "india-sa", "oceania", "multinational",
}
# 프롬프트 공통 문구 - newsletter_ingest·interview_ingest·backfill_region·gnews_ingest와 같은 문장.
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
# 분류가 실패했을 때만 남는 미판정 표식. 12종 중 하나를 억지로 찍는 대신 레거시 값을 그대로 둬
# backfill_region.py가 나중에 내용 기준으로 다시 판정하게 한다.
LEGACY_UNJUDGED = "global-en"
LOOKBACK_DAYS = int(os.environ.get("NEWSROOM_LOOKBACK_DAYS", "7"))
FETCH_CAP = 8  # 피드당 최대 처리 건수
DISCORD_CAP = 8  # discord 전송 webhook당 최대 (도배 방지)
# discord 전송 토픽 필터 — 엔터·문화·소비 핵심만 전송(순수 tech-issues·ent-deals 거시는 컷).
# 36氪 happy_life(생활소비) 성격 근사 — 신약·항공·로봇 등 엔터·소비와 먼 글 차단.
DISCORD_TOPICS = {"fan-behavior", "consumer-behavior", "taste-values", "ip-business", "artist-ownership"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


# ── 피드 fetch / 파싱 (RSS·Atom 공통) ───────────────────────────────────────────

def fetch_feed(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        })
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("피드 fetch 실패 %s: %s", url, e)
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(data: bytes) -> list[dict]:
    """RSS(item)·Atom(entry) 공통 파서 → {title, link, date, summary} 리스트."""
    try:
        root = ET.fromstring(data)
    except Exception as e:
        log.warning("피드 파싱 실패: %s", e)
        return []
    out: list[dict] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        d: dict = {}
        for ch in el:
            ln = _local(ch.tag)
            txt = (ch.text or "").strip()
            if ln == "title" and txt:
                d["title"] = txt
            elif ln == "link":
                href = ch.get("href")
                if href:  # Atom <link href= rel=>
                    if ch.get("rel", "alternate") == "alternate" or "link" not in d:
                        d["link"] = href
                elif txt:  # RSS <link>text</link>
                    d["link"] = txt
            elif ln in ("pubdate", "published", "updated", "date") and txt:
                d.setdefault("date", txt)
            elif ln in ("description", "summary", "content") and txt:
                d.setdefault("summary", txt)
        if d.get("title") and d.get("link"):
            out.append(d)
    return out


def parse_date(s: str):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)  # RSS RFC822
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))  # Atom ISO8601
    except Exception:
        return None


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


# ── 분류 (Claude haiku) ───────────────────────────────────────────────────────

def classify(title: str, text: str, region_hint: str) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    # _failed: 하드 실패(키 없음·API 예외, 예: 크레딧 잔액 부족 400) 표시.
    # main이 이걸 보고 미번역 원문을 풀에 섞지 않고 filtered_out + classify_failed로 적재한다.
    fallback = {"topics": [], "summary_ko": "", "title_ko": "", "is_gossip": False,
                "is_promo": False, "is_entertainment": True, "_failed": True}
    if not key:
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            "엔터·문화·소비 산업 기업 뉴스룸/블로그 글을 분류해 JSON으로만 응답.\n\n"
            f"제목: {title}\n본문 발췌: {text[:1500]}\n\n"
            "is_entertainment: 엔터·미디어·콘텐츠·팝 산업(음악·영상·게임·웹툰·"
            "공연·아티스트·IP·팬덤·소비 라이프스타일)과 직접 연결되면 true. "
            "순수 SaaS·B2B·반도체·엔터프라이즈 IT·일반 AI·군사·우주·항공·금융/주식·거시경제는 false. "
            "(이 수집기는 엔터 IP홀더 뉴스룸이라 대부분 true지만, 모회사 일반 보도자료·거시경제가 섞이면 false).\n"
            "is_gossip: 연예인 사생활·열애/결혼/이혼·스캔들·루머·신변잡기 등 산업 신호가 아닌 단순 가십이면 true. "
            "작품·산업·비즈니스·정책·데이터는 false. 애매하면 false(보존 우선).\n"
            "topics: 해당되는 것만 (배열 0~3개) — " + ", ".join(TOPIC_KEYS) + "\n"
            "  ※ tech-issues는 '엔터·미디어·콘텐츠 산업을 흔드는 기술 변화'에만 태깅. "
            "일반 IT·SaaS·반도체는 tech-issues 아님.\n"
            "is_promo: 단순 홍보면 true, 산업 신호면 false. "
            "true=신작·시즌 공개, 예고편·트레일러, 출시일/공개일 안내, 자사 콘텐츠·작품 마케팅, 수상 자축 등 보도자료성 홍보. "
            "false=사업 전략·투자·M&A·실적·구독자/이용 데이터·기술·정책·인사·파트너십 등 산업 신호. "
            "애매하면 false(보존 우선).\n"
            "title_ko: 제목을 자연스러운 한국어로 번역(고유명사·작품명·아티스트명은 적절히 유지, 한국어면 그대로).\n"
            "summary_ko: 한국어 150자 이내 핵심 요약 (무엇을 다뤘는지)\n"
            + REGION_GUIDE +
            "  예 - 디즈니 뉴스룸의 일본 전개 발표는 japan. "
            "스포티파이의 브라질 요금제 발표는 latin. "
            "전 세계에 동시 적용되는 정책 변경 발표는 multinational.\n\n"
            '{"is_entertainment": true, "is_gossip": false, "topics": [...], "is_promo": false, "title_ko": "...", "summary_ko": "...", "region": "..."}'
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        if isinstance(data, list):  # 모델이 배열로 응답하는 엣지
            data = next((x for x in data if isinstance(x, dict)), {})
        topics = [t for t in (data.get("topics") or []) if t in TOPIC_KEYS]
        ie = data.get("is_entertainment")
        if isinstance(ie, str):
            ie = ie.strip().lower() in ("true", "1", "yes", "y", "예")
        reg = (data.get("region") or "").strip()
        return {
            "topics": topics,
            "summary_ko": (data.get("summary_ko") or "").strip(),
            "title_ko": (data.get("title_ko") or "").strip(),
            "is_gossip": bool(data.get("is_gossip", False)),
            "is_promo": bool(data.get("is_promo", False)),
            "is_entertainment": bool(ie) if ie is not None else True,
            "region": reg if reg in VALID_REGIONS else None,
        }
    except Exception as e:
        log.warning("분류 실패: %s", e)
        return fallback


# ── Supabase ──────────────────────────────────────────────────────────────────

def supa_upsert(row: dict) -> int:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/radar_items"
    key = os.environ["SUPABASE_KEY"]
    h = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    r = requests.post(url, headers=h, json=row, timeout=15)
    return r.status_code


def recent_urls(days: int = 30) -> set[str]:
    try:
        url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/radar_items"
        key = os.environ["SUPABASE_KEY"]
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        r = requests.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                         params={"select": "url", "collector": "eq.newsroom",
                                 "created_at": f"gte.{cutoff}"}, timeout=15)
        r.raise_for_status()
        return {x["url"] for x in r.json() if x.get("url")}
    except Exception:
        return set()


def send_to_discord(webhook_url: str, content: str) -> int:
    try:
        r = requests.post(webhook_url, json={"content": content[:1900]}, timeout=10)
        return r.status_code
    except Exception as e:
        log.warning("디스코드 전송 실패: %s", e)
        return 0


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> int:
    dry = "--dry-run" in sys.argv
    with open(ALLOWLIST_PATH, encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK_DAYS)
    seen = recent_urls() if not dry else set()
    rows = []
    discord_queue = []  # (webhook_env, name, title, url, pub) — discord 지정 소스의 signal만

    for src in sources:
        if src.get("feed", "").startswith("_"):
            continue
        data = fetch_feed(src["feed"])
        if not data:
            continue
        kept = 0
        for it in parse_feed(data):
            if kept >= FETCH_CAP:
                break
            url = it["link"].strip()
            if not url or url in seen:
                continue
            dt = parse_date(it.get("date", ""))
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                if dt < cutoff:
                    continue  # 룩백 밖(오래된 글)
                pub = dt.astimezone(datetime.timezone.utc).isoformat()
            else:
                pub = datetime.datetime.now(datetime.timezone.utc).isoformat()
            title = it["title"][:500]
            summary_raw = html_to_text(it.get("summary", ""))[:2000]
            cls = classify(title, summary_raw, src.get("region", LEGACY_UNJUDGED))
            failed = cls.get("_failed", False)
            is_ent = cls.get("is_entertainment", True)
            is_gos = cls.get("is_gossip", False)
            is_promo = cls.get("is_promo", False)
            rows.append({
                "id": str(uuid.uuid4()),
                "title": (cls.get("title_ko") or title)[:500],
                "url": url,
                "source": src["name"],
                "category": "newsroom",
                "collector": "newsroom",
                "summary": (cls["summary_ko"] or summary_raw[:200]),
                "topics": cls["topics"],
                "tags": cls["topics"],
                "is_entertainment": is_ent,
                # region: classify 내용 기준 값 우선, 없으면 소스 고정 힌트 폴백 (2026-06-23).
                # 힌트가 레거시 global-en이면 미판정인 채로 남고 backfill_region.py가 재판정한다.
                "region": cls.get("region") or src.get("region", LEGACY_UNJUDGED),
                "published_date": pub,
                # 분류 하드 실패(failed, 크레딧 400 등)는 미번역 원문이라 풀에 안 섞이게 filtered_out +
                # classify_failed 표시 → backfill_translate.py가 정확히 찾아 재번역. promo·비엔터·가십도
                # filtered_out(대시보드 기본 뷰 숨김 — app.py neq.filtered_out · dashboard.html inPool).
                "status": "filtered_out" if (failed or is_promo or not is_ent or is_gos) else "pending",
                "filter_verdict": ("classify_failed" if failed else "promo" if is_promo else "non_ent" if not is_ent else "gossip" if is_gos else "pass"),
                "total_score": 0,
            })
            seen.add(url)
            kept += 1
            log.info("[%s] %s%s | %s", src["name"], "·".join(cls["topics"]) or "-",
                     " [PROMO]" if cls.get("is_promo") else "", title[:55])
            if (src.get("discord") and not failed and not is_promo and is_ent and not is_gos
                    and set(cls.get("topics", [])) & DISCORD_TOPICS):
                discord_queue.append((src["discord"], src["name"], cls.get("title_ko") or title, url, pub))

    log.info("수집 %d건 (소스 %d개, 최근 %d일)", len(rows), len(sources), LOOKBACK_DAYS)
    if dry:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"\n[디스코드 전송 후보(signal)] {len(discord_queue)}건:")
        for env, name, title, url, pub in discord_queue[:12]:
            print(f"  -> {env} | [{name}] {title[:42]}")
        return 0
    saved = 0
    for row in rows:
        code = supa_upsert(row)
        if code in (200, 201, 204):
            saved += 1
        else:
            log.warning("Supabase 적재 실패 HTTP %d: %s", code, row["title"][:40])
    log.info("Supabase 적재 완료: %d/%d", saved, len(rows))

    # discord 전송 — discord 지정 소스의 signal만, webhook당 최신 DISCORD_CAP건(도배 방지).
    # promo·기존 적재분(seen)은 자연 제외. #vibe-china 등 지역 채널 최신성 보강.
    if discord_queue:
        from collections import defaultdict
        by_hook = defaultdict(list)
        for env, name, title, url, pub in discord_queue:
            by_hook[env].append((name, title, url, pub))
        for env, posts in by_hook.items():
            webhook = os.environ.get(env)
            if not webhook:
                log.warning("%s 미설정 — discord 전송 생략", env)
                continue
            posts.sort(key=lambda x: x[3], reverse=True)  # 최신순
            sent = 0
            for name, title, url, _ in posts[:DISCORD_CAP]:
                if send_to_discord(webhook, f"📰 **[{name}]** {title}\n{url}") in (200, 204):
                    sent += 1
            log.info("discord 전송: %s %d/%d건", env, sent, min(len(posts), DISCORD_CAP))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
