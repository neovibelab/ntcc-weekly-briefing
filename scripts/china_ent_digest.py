"""
China Ent & Culture — Vibe Signal Collector
---------------------------------------------
중국 청년문화·서브컬처·도시 씬 소스에서 Vibe 후보를 수집.
DISCORD_CHINA_ASIA_WEBHOOK
스코어링: Vibe & Signal 밀도 5지표

환경변수:
  ANTHROPIC_API_KEY        Claude API 키
  DISCORD_CHINA_ASIA_WEBHOOK  Discord 웹훅
"""

import os
import re
import html
import json
import logging
import datetime
import time
from difflib import SequenceMatcher
from html.parser import HTMLParser

import feedparser
import requests
from anthropic import Anthropic
from dateutil import parser as dateparser

from llm_json import parse_list

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

RSS_SOURCES = [
    # Radii → z_lifestyle로 이동 (동아시아·동남아 전반 커버, 중국 전용 아님)
    ("Sixth Tone",     "https://www.sixthtone.com/rss"),
    ("Pandaily",       "https://pandaily.com/feed/"),
    ("TechNode",       "https://technode.com/feed/"),
    ("PingWest",       "https://www.pingwest.com/feed"),
    ("r/cpop",         "https://www.reddit.com/r/cpop/.rss"),
    ("r/China_irl",    "https://www.reddit.com/r/China_irl/.rss"),
    ("36kr 문화",      "https://36kr.com/feed"),
    ("Sup China",      "https://supchina.com/feed/"),
]

HOURS_WINDOW = 48
MAX_CANDIDATES = 5
MAX_PER_SOURCE = 3
INDICATOR_CUTOFF = 2
INDICATOR_HIGHLIGHT = 3
DUPLICATE_THRESHOLD = 0.80

VIBE_SCORE_PROMPT = (
    "아래 신호(기사/콘텐츠) 목록을 보고 각각에 대해 Vibe & Signal 밀도 5지표를 채점하라.\n\n"
    "5지표 (각 0~2):\n"
    "① 언급빈도: 커뮤니티·SNS·전문 매체·평론 레이어에서 같은 신호가 반복 등장하는가\n"
    "   (0=단발 또는 첫 등장, 1=일부 레이어에서 언급, 2=여러 레이어에서 반복)\n"
    "② 도시분포: 특정 도시·지역을 명시하는 신호인가\n"
    "   (0=지리 없음, 1=단일 도시/지역 명시, 2=복수 도시·지역에 걸친 신호)\n"
    "③ 교차정체성: 팬덤·세대·서브컬처·라이프스타일 등 정체성 레이어가 몇 개 겹치는가\n"
    "   (0=없음, 1=하나의 정체성 레이어, 2=둘 이상 교차)\n"
    "④ 매개자다양성: 팬·평론가·아티스트·플랫폼·산업 관계자 중 몇 레이어가 함께 관여하는가\n"
    "   (0=없음, 1=하나의 매개자 레이어, 2=둘 이상)\n"
    "⑤ 지속기간: 단발 화제인가 누적·반복 관찰되는가\n"
    "   (0=단발 이벤트, 1=단기 트렌드, 2=누적 관찰 중인 흐름)\n\n"
    "출력: JSON 배열만. 각 항목: id, indicators(작동한 지표명 배열), count(개수).\n"
    "예: [{\"id\":0,\"indicators\":[\"도시분포\",\"교차정체성\"],\"count\":2}]\n\n"
    "신호 목록:\n"
)

SUMMARY_SYSTEM_PROMPT = (
    "당신은 중국·동아시아 청년문화 Vibe 신호 분석가입니다.\n"
    "주어진 신호를 200자 이내 2~3문장으로 기술합니다.\n"
    "레이블·소제목·번호 없이 이어서 씁니다.\n"
    "첫 문장은 사실 중심(과장 없이), 이어지는 문장은 도시·세대·서브컬처 관점의 균열이나 교차.\n"
    "본문에 도시·장소가 실제로 언급될 때만 명시. 없으면 쓰지 않는다.\n"
    "한국어. Signal 후행 분석 금지. 사실에 없는 내용 금지."
)

BATCH_SIZE = 15


def _parse_entry_time(entry) -> datetime.datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        s = getattr(entry, attr, None)
        if s:
            try:
                dt = dateparser.parse(s)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
            except Exception:
                pass
    return None


def fetch_rss_articles() -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=HOURS_WINDOW)
    articles = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VibeBot/1.0)"}

    for source_name, url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url, request_headers=headers)
            count = 0
            for entry in feed.entries:
                if count >= MAX_PER_SOURCE:
                    break
                pub_time = _parse_entry_time(entry)
                if pub_time is None or pub_time < cutoff:
                    continue
                title = entry.get("title", "").strip()
                raw_body = entry.get("summary", "") or ""
                body = re.sub(r"<[^>]+>", " ", raw_body)
                body = html.unescape(re.sub(r"\s+", " ", body)).strip()
                articles.append({
                    "source": source_name,
                    "title": title,
                    "url": entry.get("link", ""),
                    "body": body or title,
                    "published": pub_time.isoformat(),
                    "channel": "vibe/cn-asia",
                })
                count += 1
            if count:
                log.info("[RSS] %s: %d건", source_name, count)
        except Exception as exc:
            log.warning("[RSS] %s 실패: %s", source_name, exc)

    log.info("RSS 전체 수집: %d건", len(articles))
    return articles


def _is_dup(candidate: dict, kept: dict) -> bool:
    title_sim = SequenceMatcher(
        None, candidate["title"].lower(), kept["title"].lower()
    ).ratio()
    if title_sim >= DUPLICATE_THRESHOLD:
        return True
    body_c = candidate.get("body", "")[:200].lower()
    body_k = kept.get("body", "")[:200].lower()
    if len(body_c) > 50 and len(body_k) > 50:
        if SequenceMatcher(None, body_c, body_k).ratio() >= 0.60:
            return True
    return False


def deduplicate(articles: list[dict]) -> list[dict]:
    unique = []
    for candidate in articles:
        if not any(_is_dup(candidate, kept) for kept in unique):
            unique.append(candidate)
    removed = len(articles) - len(unique)
    if removed:
        log.info("중복 제거: %d건 → %d건", len(articles), len(unique))
    return unique


def score_vibe(client: Anthropic, articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    scored = []
    for batch_start in range(0, len(articles), BATCH_SIZE):
        batch_items = articles[batch_start:batch_start + BATCH_SIZE]
        batch = [
            {"id": i, "title": a["title"], "body": a["body"][:300]}
            for i, a in enumerate(batch_items)
        ]
        prompt = VIBE_SCORE_PROMPT + json.dumps(batch, ensure_ascii=False)
        try:
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            # 3층 방어 = scripts/llm_json.py (레이더 llm_json.py와 쌍둥이).
            # 코드펜스 제거도 모듈이 한다.
            results = parse_list(response.content[0].text.strip())
            for item in results:
                idx = item["id"]
                if idx < len(batch_items):
                    a = batch_items[idx].copy()
                    a["indicators"] = item.get("indicators", [])
                    a["indicator_count"] = item.get("count", 0)
                    scored.append(a)
        except Exception as exc:
            log.warning("5지표 스코어링 실패 (batch %d~): %s", batch_start, exc)
            for a in batch_items:
                a["indicators"] = []
                a["indicator_count"] = 0
                scored.append(a)

    for a in scored:
        log.info("  [%d지표] %s | %s",
                 a["indicator_count"],
                 "·".join(a["indicators"]),
                 a["title"][:60])

    scored.sort(key=lambda x: x["indicator_count"], reverse=True)
    return scored


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside"}
        self.texts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            t = data.strip()
            if len(t) > 20:
                self.texts.append(t)


def _fetch_article_body(url: str, max_chars: int = 1200) -> str:
    if not url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = html.unescape(" ".join(extractor.texts))
        return text[:max_chars]
    except Exception:
        return ""


def summarize_article(client: Anthropic, article: dict) -> str:
    body = article["body"]
    if len(body) < 150 and article.get("url"):
        fetched = _fetch_article_body(article["url"])
        if fetched:
            body = fetched

    prompt = (
        f"제목: {article['title']}\n"
        f"출처: {article['source']}\n"
        f"본문: {body[:1000]}"
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            system=SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        log.error("요약 생성 실패: %s", exc)
        return article["title"]


def build_discord_messages(candidates: list[dict], header: str) -> list[str]:
    messages = [header]
    for a in candidates:
        count = a["indicator_count"]
        if count < INDICATOR_CUTOFF:
            continue
        badge = "🟢" if count >= INDICATOR_HIGHLIGHT else "🟡"
        indicators = "·".join(a["indicators"][:3]) if a["indicators"] else "—"
        title = a["title"][:100]
        url = a.get("url", "")
        title_part = f"[**{title}**]({url})" if url else f"**{title}**"
        summary = (a.get("summary", "") or "").strip()[:500]
        msg = f"{badge} {title_part} `{indicators}`"
        if summary:
            msg += f"\n> {summary}"
        messages.append(msg[:1900])
    return messages if len(messages) > 1 else []


def send_to_discord(webhook_url: str, content: str) -> None:
    payload = {"content": content[:2000], "flags": 4}
    response = requests.post(webhook_url, json=payload, timeout=15)
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Discord 웹훅 실패 (HTTP {response.status_code}): {response.text[:200]}")
    log.info("Discord 전송 완료 (HTTP %d)", response.status_code)


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    webhook_url = os.environ.get("DISCORD_CHINA_ASIA_WEBHOOK")

    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if not webhook_url:
        raise EnvironmentError("DISCORD_CHINA_ASIA_WEBHOOK 환경변수가 설정되지 않았습니다.")

    client = Anthropic(api_key=api_key)
    today = datetime.date.today().strftime("%Y-%m-%d")

    articles = fetch_rss_articles()
    if not articles:
        log.info("수집된 신호 없음 — 전송 생략")
        return

    articles = deduplicate(articles)
    articles = score_vibe(client, articles)

    candidates = [a for a in articles if a["indicator_count"] >= INDICATOR_CUTOFF]
    if not candidates:
        log.info("5지표 %d개 이상 신호 없음 — 전송 생략", INDICATOR_CUTOFF)
        return

    seen_file = os.environ.get("SEEN_FILE", ".seen-titles.txt")
    seen_titles: list[str] = []
    if os.path.exists(seen_file):
        with open(seen_file, encoding="utf-8") as f:
            seen_titles = [l.strip() for l in f if l.strip()]
        log.info("채널간 중복 제거: seen_titles %d건 로드", len(seen_titles))

    def _is_cross_dup(title: str) -> bool:
        t = title.lower()
        return any(SequenceMatcher(None, t, s.lower()).ratio() >= 0.75 for s in seen_titles)

    candidates = [a for a in candidates if not _is_cross_dup(a["title"])]

    seen_sources: set[str] = set()
    diverse: list[dict] = []
    for a in candidates:
        src = a["source"]
        if src not in seen_sources:
            seen_sources.add(src)
            diverse.append(a)
        if len(diverse) >= MAX_CANDIDATES:
            break
    if len(diverse) < MAX_CANDIDATES:
        for a in candidates:
            if a not in diverse:
                diverse.append(a)
            if len(diverse) >= MAX_CANDIDATES:
                break
    selected = diverse[:MAX_CANDIDATES]
    log.info("소스 다양성 적용: %d개 소스 → %d건 선택", len(seen_sources), len(selected))

    for a in selected:
        a["summary"] = summarize_article(client, a)
        log.info("선택: [%d지표] %s | %s", a["indicator_count"], a["title"][:60], a.get("url", ""))
        log.info("선택메타: %s", json.dumps({"summary": (a.get("summary") or "")[:200], "indicators": a.get("indicators", [])}, ensure_ascii=False))

    header = f"🀄 **중국 엔터 Vibe | {today}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    messages = build_discord_messages(selected, header)
    if not messages:
        return
    for i, msg in enumerate(messages):
        send_to_discord(webhook_url, msg)
        if i < len(messages) - 1:
            time.sleep(30)

    with open(seen_file, "a", encoding="utf-8") as f:
        for a in selected:
            f.write(a["title"] + "\n")
    log.info("seen-titles 갱신: %d건 추가 → 총 %d건", len(selected), len(seen_titles) + len(selected))


if __name__ == "__main__":
    main()
