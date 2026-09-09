#!/usr/bin/env python3
"""인터뷰 수집기 - allowlist 매체 RSS·유튜브 채널 RSS에서 최신 항목을 가져와
분류(is_interview 게이트)한 뒤 인터뷰만 Supabase radar_items(collector='interview')에 적재.
GitHub Actions 화·금 주 2회 cron. Discord 미포스팅 - 대시보드 전용.

vibe_search·newsletter·newsroom과 같은 풀(radar_items)을 공유하는 네 번째 수집기.
용처: @nvl.seoul 'insight/quote/reels' 소재 파이프라인 + Icon Lab 인물 발굴 레이더.

런타임 의존: requests, anthropic (피드 파싱은 stdlib xml.etree - 외부 feedparser 불필요).
환경변수:
  SUPABASE_URL / SUPABASE_KEY
  ANTHROPIC_API_KEY           분류용(없으면 미분류 filtered_out 적재)
  YOUTUBE_API_KEY             영상 소스용(2026-07-10 추가). 없으면 RSS 폴백 시도(대개 실패).
  INTERVIEW_LOOKBACK_DAYS     기본 14 (주 2회 스케줄 + 여유. RSS 특성상 최신만 잡힘)

2026-07-10 수정: YouTube 채널 RSS(`/feeds/videos.xml`)가 GitHub Actions 러너 IP에서
전량 404(로컬에서는 200 - IP 차단/제한으로 추정, UA는 이미 브라우저 값이라 무관).
영상 소스는 YouTube Data API v3(`playlistItems`, uploads 재생목록 = 채널ID의 UC→UU
치환)로 전환. 텍스트 소스(매체 RSS)는 기존 방식 그대로.
사용: python scripts/interview_ingest.py [--dry-run]
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
ALLOWLIST_PATH = os.path.join(os.path.dirname(HERE), "sources_interviews.json")
# 지역 12종 (2026-09-10 개편). 구 global-en이 살아있는 풀의 80%를 삼키는 잔여
# 범주였다. 이름이 아니라 기준을 쪼갠다. global-en은 신규 저장하지 않는다.
VALID_REGIONS = {
    "korea", "japan", "china", "southeast-asia",
    "north-america", "europe", "latin", "mena",
    "africa-ssa", "india-sa", "oceania", "multinational",
}
# 프롬프트 공통 문구 - newsletter_ingest·newsroom_ingest·backfill_region·gnews_ingest와 같은 문장.
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
LOOKBACK_DAYS = int(os.environ.get("INTERVIEW_LOOKBACK_DAYS", "14"))
FETCH_CAP = 8  # 피드당 최대 처리 건수
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")


def extract_channel_id(feed_url: str) -> str | None:
    m = re.search(r"channel_id=([\w-]+)", feed_url)
    return m.group(1) if m else None


def fetch_youtube_api(channel_id: str) -> list[dict]:
    """YouTube Data API v3(playlistItems)로 채널 최신 업로드 조회.
    uploads 재생목록 ID = 채널ID의 'UC' 접두를 'UU'로 치환(공식 규칙) - channels.list
    호출 없이 1회 요청으로 끝남(쿼터 1 unit/채널)."""
    if not channel_id.startswith("UC"):
        return []
    playlist_id = "UU" + channel_id[2:]
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={"part": "snippet", "playlistId": playlist_id,
                    "maxResults": 15, "key": YOUTUBE_API_KEY},
            timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as e:
        log.warning("YouTube API fetch 실패 %s: %s", channel_id, e)
        return []
    out = []
    for it in items:
        sn = it.get("snippet", {})
        vid = (sn.get("resourceId") or {}).get("videoId")
        if not vid or not sn.get("title"):
            continue
        out.append({
            "title": sn["title"],
            "link": f"https://www.youtube.com/watch?v={vid}",
            "date": sn.get("publishedAt", ""),
            "summary": sn.get("description", ""),
        })
    return out


# ── 피드 fetch / 파싱 (RSS·Atom·YouTube 공통) ──────────────────────────────────

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
    """RSS(item)·Atom/YouTube(entry) 공통 파서 → {title, link, date, summary} 리스트."""
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
                if href:  # Atom/YouTube <link href= rel=>
                    if ch.get("rel", "alternate") == "alternate" or "link" not in d:
                        d["link"] = href
                elif txt:  # RSS <link>text</link>
                    d["link"] = txt
            elif ln in ("pubdate", "published", "updated", "date") and txt:
                d.setdefault("date", txt)
            elif ln in ("description", "summary", "content") and txt:
                d.setdefault("summary", txt)
            elif ln == "group":  # YouTube <media:group> - 제목·설명이 여기 중첩
                for g in ch:
                    gln = _local(g.tag)
                    gtxt = (g.text or "").strip()
                    if gln == "description" and gtxt:
                        d.setdefault("summary", gtxt)
                    elif gln == "title" and gtxt and "title" not in d:
                        d["title"] = gtxt
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

def classify(title: str, text: str, media: str) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    # _failed: 하드 실패(키 없음·API 예외). main이 이걸 보고 미분류 원문을 인터뷰로 오적재하지 않고
    # filtered_out + classify_failed로 적재한다(is_interview 판정 불가 → 풀 노출 안 함).
    fallback = {"is_interview": False, "is_music_ent": False, "person_ko": "", "summary_ko": "",
                "title_ko": "", "region": None, "_failed": True}
    if not key:
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            "아래는 음악·엔터 매체의 글 또는 유튜브 영상이다. 인터뷰 수집기용으로 분류해 JSON으로만 응답.\n\n"
            f"형태 힌트: {media}\n제목: {title}\n본문/설명 발췌: {text[:1500]}\n\n"
            "**두 축을 따로 판정한다. 형태와 주제다.**\n"
            "is_interview(형태): 아티스트·창작자 **본인의 발화(인터뷰·대담·Q&A·라운드테이블·본인 해설/코멘터리)가 중심**이면 true. "
            "false=뉴스·보도·리뷰/평점·차트/순위·라이브/퍼포먼스 단독·뮤직비디오·리스트클릭베이트·부고·행사 공지·홍보. "
            "애매하면 false(정밀 우선, 인터뷰만 통과).\n"
            "is_music_ent(주제): 발화 내용이 **음악·엔터 창작이나 그 산업**에 관한 것이면 true. "
            "곡·앨범·프로덕션·공연·팬덤·레이블·계약·플랫폼·IP·업계 구조 등. "
            "false=연애·육아·건강·심리·창업·테크·정치·요리·잡담. "
            "**말하는 사람이 아티스트여도 주제가 음악·엔터가 아니면 false다.** "
            "실제로 걸러야 했던 예 - 배우가 팟캐스트에서 임신 이야기를 한다, "
            "창작자가 TED에서 우주론을 강연한다, 뮤지션이 예능에서 매운 음식을 먹는다.\n"
            "person_ko: 인터뷰 주 인물(아티스트/창작자)의 이름을 한국어 표기로. 여럿이면 대표 1인, "
            "불명확하거나 인물 중심이 아니면 빈 문자열.\n"
            "title_ko: 제목을 자연스러운 한국어로 번역(고유명사·작품명·아티스트명은 적절히 유지, 한국어면 그대로).\n"
            "**title_ko·summary_ko에 가운데 줄표(—)를 쓰지 않는다.** 쉼표나 하이픈(-)으로 바꾸거나 문장을 끊는다.\n"
            "summary_ko: 한국어 120자 이내 핵심 요약(누가 무엇을 말했는지).\n"
            + REGION_GUIDE +
            "  인터뷰는 '기사 내용의 시장' = 인물이 주로 활동하는 시장으로 읽는다.\n"
            "  예 - 미국 매체가 실은 나이지리아 아프로비츠 뮤지션 인터뷰는 africa-ssa. "
            "영국 밴드의 신보 인터뷰는 europe. "
            "여러 나라 출신이 섞인 업계 좌담은 multinational.\n\n"
            '{"is_interview": true, "is_music_ent": true, "person_ko": "...", "title_ko": "...", "summary_ko": "...", "region": "..."}'
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
        def _b(v):
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes", "y", "예")
            return bool(v)

        ii = _b(data.get("is_interview"))
        # 주제 축은 신설(2026-09-02)이라 모델이 키를 빠뜨리면 통과시킨다.
        # 형태 축까지 같이 죽으면 수집이 통째로 멈춘다.
        me = _b(data.get("is_music_ent")) if "is_music_ent" in data else True
        reg = (data.get("region") or "").strip()
        return {
            "is_interview": ii,
            "is_music_ent": me,
            "person_ko": (data.get("person_ko") or "").strip(),
            "summary_ko": (data.get("summary_ko") or "").strip(),
            "title_ko": (data.get("title_ko") or "").strip(),
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


def recent_urls(days: int = 60) -> set[str]:
    # 인터뷰는 에버그린이라 나이컷이 없어 재적재 위험이 큼 → dedup 창을 60일로 넓게.
    try:
        url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/radar_items"
        key = os.environ["SUPABASE_KEY"]
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        r = requests.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                         params={"select": "url", "collector": "eq.interview",
                                 "created_at": f"gte.{cutoff}"}, timeout=15)
        r.raise_for_status()
        return {x["url"] for x in r.json() if x.get("url")}
    except Exception:
        return set()


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> int:
    dry = "--dry-run" in sys.argv
    with open(ALLOWLIST_PATH, encoding="utf-8") as f:
        sources = json.load(f)["sources"]

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOOKBACK_DAYS)
    seen = recent_urls() if not dry else set()
    rows = []
    kept_interview = 0

    for src in sources:
        if src.get("feed", "").startswith("_"):
            continue
        media = src.get("media", "text")
        items: list[dict] = []
        if media == "video":
            cid = extract_channel_id(src["feed"])
            if cid and YOUTUBE_API_KEY:
                items = fetch_youtube_api(cid)
            if not items:  # API 키 없음·실패 시 RSS 폴백 시도(대개 GH Actions에서 404)
                data = fetch_feed(src["feed"])
                if data:
                    items = parse_feed(data)
        else:
            data = fetch_feed(src["feed"])
            if not data:
                continue
            items = parse_feed(data)
        kept = 0
        for it in items:
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
                    continue  # 룩백 밖(오래된 글) - RSS라 어차피 최신만 잡힘
                pub = dt.astimezone(datetime.timezone.utc).isoformat()
            else:
                pub = datetime.datetime.now(datetime.timezone.utc).isoformat()
            title = it["title"][:500]
            summary_raw = html_to_text(it.get("summary", ""))[:2000]
            cls = classify(title, summary_raw, media)
            failed = cls.get("_failed", False)
            # 형태와 주제 둘 다 통과해야 적재한다 (2026-09-02 주제 축 신설).
            is_int = cls.get("is_interview", False) and cls.get("is_music_ent", True)
            person = cls.get("person_ko", "")
            # summary 관례: "인물 - 요지" (인물 있으면 접두)
            base_sum = cls.get("summary_ko") or summary_raw[:200]
            summary = f"{person} - {base_sum}" if person and base_sum else base_sum
            rows.append({
                "id": str(uuid.uuid4()),
                "title": (cls.get("title_ko") or title)[:500],
                "url": url,
                "source": src["name"],
                "category": "interview",
                "collector": "interview",
                "summary": summary,
                "topics": [],
                "tags": [media],  # text|video - 대시보드에서 형태 구분용
                "is_entertainment": True,  # 인터뷰 소스는 엔터 직결
                # 분류 값 우선, 없으면 소스 고정 힌트. 힌트가 레거시 global-en이면
                # 미판정인 채로 남고 backfill_region.py가 재판정한다.
                "region": cls.get("region") or src.get("region", LEGACY_UNJUDGED),
                "published_date": pub,
                # 인터뷰 아님(not_interview) · 분류 실패(classify_failed)는 filtered_out으로
                # 풀·인터뷰탭에서 숨김(대시보드 기본 뷰 status!=filtered_out / inPool).
                "status": "filtered_out" if (failed or not is_int) else "pending",
                "filter_verdict": ("classify_failed" if failed else "not_interview" if not is_int else "pass"),
                "total_score": 0,
            })
            seen.add(url)
            kept += 1
            if is_int and not failed:
                kept_interview += 1
            log.info("[%s] %s%s | %s", src["name"],
                     "🎙" if (is_int and not failed) else "·",
                     f" ({person})" if person else "", title[:55])

    log.info("수집 %d건 (인터뷰 %d건 · 소스 %d개, 최근 %d일)",
             len(rows), kept_interview, len(sources), LOOKBACK_DAYS)
    if dry:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"\n[is_interview=true] {kept_interview}건 / 총 {len(rows)}건")
        return 0
    saved = 0
    for row in rows:
        code = supa_upsert(row)
        if code in (200, 201, 204):
            saved += 1
        else:
            log.warning("Supabase 적재 실패 HTTP %d: %s", code, row["title"][:40])
    log.info("Supabase 적재 완료: %d/%d (인터뷰 %d)", saved, len(rows), kept_interview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
