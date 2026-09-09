#!/usr/bin/env python3
"""drops/ 최신 주간 리포트 드롭 1편을 Discord 웹훅으로 전송.

primary(discord-report-drop) · backup(report-drop-watchdog) 워크플로 공용 모듈.
stdlib만 사용(설치 불필요). YAML 인라인 heredoc의 들여쓰기 취약성을 제거하기 위해
발송 로직을 이 파일로 분리한다.

env:
  DISCORD_REPORT_WEBHOOK_URL  전송 대상 웹훅 (필수, DRY_RUN 시 불필요)
  DRY_RUN=1                   전송 없이 찾기·정제까지만 (로컬 검증용)
종료코드: 0 성공 / 1 실패(파일 없음·빈 내용·204 외 응답)
"""
import os
import re
import sys
import glob
import json
import uuid
import datetime
import urllib.request
import urllib.error

DROP_GLOB = "drops/*-주간리포트드롭.md"
DISCORD_LIMIT = 1990  # 2000자 하드리밋 - 안전 마진 10자


def find_latest_drop():
    """파일명(YY.MM.DD) 기준 사전순 최신 드롭 1개."""
    files = sorted(glob.glob(DROP_GLOB))
    return files[-1] if files else None


def clean_content(path):
    """HTML 주석 제거 → 트림 → 2000자 제한."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    if len(text) > DISCORD_LIMIT:
        text = text[:DISCORD_LIMIT] + "\n…(이하 생략)"
    return text


def post_to_discord(webhook, content):
    """POST → (http_status, body). Discord 성공은 204 No Content."""
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data,
        headers={
            "Content-Type": "application/json",
            # Discord Cloudflare가 기본 Python-urllib UA를 403(error 1010)으로 차단 → 명시 UA 필수 (2026-06-29)
            "User-Agent": "Mozilla/5.0 (compatible; NVL-report-drop/1.0; +https://neovibelab.com)",
        }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def drop_age_days(path):
    """파일명 YY.MM.DD에서 드롭 날짜를 파싱해 KST 기준 경과일. 실패 시 None(보수적: 발송 허용)."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", os.path.basename(path))
    if not m:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    try:
        drop_date = datetime.date(2000 + yy, mm, dd)
    except ValueError:
        return None
    today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()
    return (today - drop_date).days


# ── 대시보드(nvl-vibe-radar 뉴스룸 탭) 적재 ──────────────────────────────────
# '리포트를 디스코드에 드랍할 때 대시보드에도'(대표 2026-06-29). 드롭 .md의 신규 리포트
# (🥇 추천 + 🆕 신규, 🔁 다시보기=기보유는 제외)를 파싱해 Supabase radar_items에
# collector='newsroom'으로 적재 → 대시보드 뉴스룸 탭에 노출. URL 중복은 merge-duplicates 스킵.

# 지역 12종 + 레거시 (2026-09-10 개편). supabase_writer.py의 REGION_LABELS와 같은 문자열.
_REGION_LABELS = {
    "korea": "한국", "japan": "일본", "china": "중국", "southeast-asia": "동남아",
    "north-america": "북미", "europe": "유럽", "latin": "라틴아메리카",
    "mena": "중동·북아프리카", "africa-ssa": "아프리카", "india-sa": "인도·남아시아",
    "oceania": "오세아니아", "multinational": "다국적",
    "global-en": "글로벌(구)",  # 레거시
}


def parse_drop_items(text):
    """드롭 .md에서 신규 리포트(🥇+🆕)를 파싱. 🔁 다시보기는 제외.
    각 항목 헤더 '· 도메인 · YYYY-MM-DD'에서 실제 발행일도 추출(없으면 빈 문자열).
    반환: [{pub, title, header, date, summary, url}]"""
    body = re.split(r"##\s*🔁", text)[0]
    items = []
    for m in re.finditer(
        r"\*\*\[(?P<pub>[^\]]+)\]\s*(?P<title>[^*]+?)\*\*(?P<rest>.*?)"
        r"(?=\n##|\n-\s*\*\*\[|\n\*\*\[|\Z)", body, re.DOTALL):
        rest = m.group("rest")
        um = re.search(r"https?://[^\s<>)\]]+", rest)
        if not um:
            continue
        header = re.split(r"[—\n]", rest, 1)[0]            # "· 도메인 · YYYY-MM-DD"
        dt = re.search(r"(\d{4})[-.](\d{2})[-.](\d{2})", header)
        item_date = "-".join(dt.groups()) if dt else ""
        summ = re.sub(r"https?://\S+", "", rest.replace(header, " ", 1))
        summ = re.sub(r"[<>🔗📎✩★*]+", " ", summ)
        summ = re.sub(r"^[\s—–\-·]+", "", re.sub(r"\s+", " ", summ)).strip()[:400]
        items.append({"pub": m.group("pub").strip(), "title": m.group("title").strip(),
                      "header": header, "date": item_date, "summary": summ, "url": um.group(0)})
    return items


def _region_from_text(s):
    """드롭 제목·요약의 키워드로 지역 추정. LLM을 부르지 않는 거친 휴리스틱이라
    잡히지 않으면 레거시 global-en으로 남긴다. 이 행들은 collector='newsroom'이라
    backfill_region.py 기본 대상에 들어가고 거기서 내용 기준으로 다시 판정된다.
    12종 중 하나를 여기서 억지로 찍지 않는다."""
    sl = s.lower()
    if "중국" in s or "china" in sl:
        return "china"
    if "일본" in s or "japan" in sl:
        return "japan"
    if "한국" in s or "korea" in sl:
        return "korea"
    if "북미" in s or "미국" in s or "u.s." in sl or "united states" in sl:
        return "north-america"
    if "유럽" in s or "europe" in sl or "eu " in sl:
        return "europe"
    return "global-en"


def push_items_to_dashboard(items, drop_path):
    """파싱한 리포트를 Supabase radar_items(collector='newsroom')에 적재. stdlib urllib."""
    sb_url = os.environ.get("SUPABASE_URL")
    sb_key = os.environ.get("SUPABASE_KEY")
    if not sb_url or not sb_key:
        print("[info] SUPABASE_URL/KEY 미설정 — 대시보드 적재 생략")
        return 0
    # 발행일 폴백 = 드롭 날짜(파일명). 각 항목에 실제 발행일(it["date"])이 있으면 그걸 우선.
    drop_iso = None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})", os.path.basename(drop_path))
    if m:
        yy, mm, dd = (int(x) for x in m.groups())
        try:
            drop_iso = datetime.date(2000 + yy, mm, dd).isoformat() + "T00:00:00+00:00"
        except ValueError:
            pass
    saved = 0
    for it in items:
        region = _region_from_text(it.get("header", ""))
        item_iso = (it["date"] + "T00:00:00+00:00") if it.get("date") else drop_iso
        row = {
            "id": str(uuid.uuid4()),
            "title": it["title"][:500],
            "url": it["url"],
            "source": it["pub"][:200],
            "category": _REGION_LABELS.get(region, region),
            "summary": it["summary"][:1000],
            "filter_verdict": "pass",
            "status": "pending",
            "tags": [],
            "collector": "newsroom",
            "region": region,
            "topics": [],
            "is_entertainment": True,
            "total_score": 0,
            # 각 리포트 실제 발행일(없으면 드롭 날짜). 수집시각(now) 폴백 금지 — 카드에 수집일 표기 방지.
            "published_date": item_iso or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        req = urllib.request.Request(
            f"{sb_url}/rest/v1/radar_items", data=json.dumps(row).encode("utf-8"),
            method="POST", headers={
                "apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                "Content-Type": "application/json",
                "User-Agent": "NVL-report-drop/1.0",
                # ignore-duplicates: 이미 있는 URL은 건드리지 않음(재발송이 교정된 발행일을 덮지 않게).
                "Prefer": "resolution=ignore-duplicates"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    saved += 1
        except urllib.error.HTTPError as e:
            if e.code != 409:  # 409 = URL 중복(정상 스킵)
                print(f"[warn] 대시보드 적재 실패 ({it['pub']}): HTTP {e.code}")
        except Exception as e:
            print(f"[warn] 대시보드 적재 오류 ({it['pub']}): {e}")
    print(f"[info] 대시보드(뉴스룸 탭) 적재: {saved}/{len(items)}건")
    return saved


def main():
    path = find_latest_drop()
    if not path:
        print("::error::drops/ 폴더에 드롭 파일이 없습니다")
        return 1
    print(f"[info] 드롭 파일: {path}")

    content = clean_content(path)
    if not content:
        print("::error::드롭 파일 내용이 비어 있습니다")
        return 1
    print(f"[info] 전송 내용 길이: {len(content)}자")

    if os.environ.get("DRY_RUN") == "1":
        print("[dry-run] 전송 생략")
        return 0

    # 격주 발송 중복 방지 (2026-06-29): 정시 cron은 매주 월요일 '최신 드롭'을 재발송하므로,
    # 생성 주기(격주)보다 발송이 잦으면 같은 드롭이 반복 발송된다. 드롭 파일명 날짜가
    # DROP_MAX_AGE_DAYS(기본 7) 이상 지났으면 '신규 드롭 없음'으로 보고 발송 생략.
    # 격주의 쉬는 주 월요일에 드롭은 정확히 7일 경과 — 기본 8이면 7<8로 통과해 중복 발송됨(2026-07-06 실측).
    # return 0(정상) → 정시 워크플로 success 유지 → watchdog 오경보 없음(check_drop_posted가 success를 발송으로 판정).
    max_age = int(os.environ.get("DROP_MAX_AGE_DAYS", "7"))
    age = drop_age_days(path)
    if age is not None and age >= max_age:
        print(f"[info] 최신 드롭 {os.path.basename(path)} {age}일 경과(>= {max_age}일) — 신규 드롭 없음, 발송 생략")
        return 0

    webhook = os.environ.get("DISCORD_REPORT_WEBHOOK_URL")
    if not webhook:
        print("::error::DISCORD_REPORT_WEBHOOK_URL 미설정")
        return 1

    code, body = post_to_discord(webhook, content)
    print(f"Discord webhook HTTP: {code}")
    if body:
        print(f"Discord response: {body}")
    if code != 204:
        print(f"::error::Discord webhook 실패 (HTTP {code})")
        return 1
    print("[info] Discord 전송 완료")
    # 대시보드(뉴스룸 탭)에도 적재 — '디스코드 드랍할 때 대시보드에도' (2026-06-29).
    # Discord 발송은 이미 성공했으므로, 적재 실패가 전체 실패가 되지 않게 가드.
    try:
        with open(path, "r", encoding="utf-8") as f:
            push_items_to_dashboard(parse_drop_items(f.read()), path)
    except Exception as e:
        print(f"[warn] 대시보드 적재 단계 오류: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
