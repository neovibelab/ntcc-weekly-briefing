#!/usr/bin/env python3
"""지역 수집 스텝이 검색 실패(API/코드 에러)로 끝나면 대표에게 메일 경보.

ai-news-daily.yml 전용. 각 지역 스텝의 outcome을 OUTCOME_<REGION> env로 받아
'failure'인 지역만 모아 woojin@에 알린다.

왜 필요한가: 지역 스텝이 continue-on-error라 한 지역이 죽어도 잡 전체는
success로 떠서 gh run·디스코드에 티가 안 난다. 글로벌이 sony.com 400으로
이틀 침묵 실패한 사고(2026-06-15~16)가 며칠 뒤에야 발견됐다. 이 메일이
침묵 실패에 대한 유일한 능동 경보다.

0건과 실패의 구분: 정상적인 '후보 0건'은 vibe_search가 exit 0 → outcome
success → 여기 안 잡힌다. web_search API 호출 자체가 실패한 경우만
vibe_search가 exit 1 → outcome failure → 알림. 정상 0건엔 메일이 안 간다.

메일 발송 실패가 워크플로를 죽이지 않도록 항상 0으로 끝낸다.

env:
  GMAIL_USER, GMAIL_APP_PASS   Gmail 계정 + 앱비밀번호 (IMAP 수집·드롭 경보와 동일)
  OUTCOME_<REGION>             각 지역 스텝 outcome (success/failure/skipped/'')
  RUN_URL                      (선택) 해당 GitHub Actions 실행 URL
  DRY_RUN=1                    발송 없이 본문만 출력
"""
import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText
from email.utils import formatdate

# Windows 콘솔(cp949)에서 이모지·em-dash 출력 시 UnicodeEncodeError 방지.
# GitHub Actions(Linux)는 UTF-8 기본이라 무영향 — 로컬 DRY_RUN 테스트 호환용.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TO_ADDR = "woojin@neovibelab.com"

# env 키 → 한국어 지역명 (워크플로 알림 스텝의 OUTCOME_* 와 일치시킬 것)
REGIONS = [
    ("OUTCOME_KOREA", "한국"),
    ("OUTCOME_GLOBAL", "영어권 검색"),  # 검색 프로파일 이름 (2026-09-10)
    ("OUTCOME_CHINA", "중국"),
    ("OUTCOME_JAPAN", "일본"),
    ("OUTCOME_SEA", "동남아"),
]


def failed_regions() -> list[str]:
    """outcome이 'failure'인 지역명 목록. skipped/success/미설정은 무시."""
    return [name for env, name in REGIONS if os.environ.get(env) == "failure"]


def read_failure_reasons() -> list[tuple[str, str, str]]:
    """vibe_search가 남긴 실패 사유 마커 파일(같은 잡 내 작성) → (지역, 분류, 메시지) 목록.
    분류 'credit'이 하나라도 있으면 메일에 크레딧 충전 안내를 명시한다."""
    path = os.environ.get("FAILURE_REASON_FILE", "region-failures.txt")
    out: list[tuple[str, str, str]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    except OSError:
        pass
    return out


def build_message(failed: list[str], reasons: list[tuple[str, str, str]] | None = None) -> tuple[str, str]:
    joined = ", ".join(failed)
    reasons = reasons or []
    is_credit = any(cat == "credit" for _, cat, _ in reasons)
    subject = f"[NVL] ⚠️ Vibe 수집 실패 — {joined}"
    if is_credit:
        subject += " (크레딧 잔액 부족)"
    lines = [
        "오늘 Vibe 후보 수집에서 다음 지역이 검색 실패(API/코드 에러)로 끝났습니다:",
        f"  → {joined}",
        "",
        "이는 '후보 0건'(정상)이 아니라 web_search API 호출 자체가 실패한 경우입니다.",
        "해당 지역 Discord 채널은 오늘 비어 있습니다.",
    ]
    if is_credit:
        lines += [
            "",
            "■ 확인된 원인: Anthropic API 크레딧 잔액 부족 (400 invalid_request_error)",
            "  → https://console.anthropic.com 의 Plans & Billing에서 크레딧을 충전하세요.",
            "  충전하면 다음 예약 수집부터 자동 정상화됩니다.",
            "  ※ 뉴스룸·뉴스레터 기사 미번역도 같은 원인 — 충전 후",
            "    scripts/backfill_translate.py 로 누적분 일괄 재번역.",
        ]
    else:
        lines += [
            "",
            "점검:",
            "  - allowed_domains에 Anthropic 크롤러 차단 도메인이 끼었는지 (400 거부)",
            "  - ANTHROPIC_API_KEY 유효성·사용 한도·크레딧 잔액",
            "  - GitHub Actions 로그의 '[지역] 검색 실패:' 라인",
        ]
    run_url = os.environ.get("RUN_URL", "").strip()
    if run_url:
        lines += ["", f"실행 로그: {run_url}"]
    return subject, "\n".join(lines)


def main() -> int:
    failed = failed_regions()
    if not failed:
        print("[info] 실패 지역 없음 — 알림 생략")
        return 0

    subject, body = build_message(failed, read_failure_reasons())
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASS")

    if os.environ.get("DRY_RUN") == "1":
        print(f"[dry-run] To: {TO_ADDR}\n[dry-run] Subject: {subject}\n\n{body}")
        return 0
    if not user or not pw:
        print("[warn] GMAIL_USER/GMAIL_APP_PASS 미설정 — 메일 생략")
        return 0

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = TO_ADDR
    msg["Date"] = formatdate(localtime=True)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.sendmail(user, [TO_ADDR], msg.as_string())
        print(f"[info] Vibe 실패 경보 메일 발송 완료 → {TO_ADDR} ({', '.join(failed)})")
    except Exception as e:  # noqa: BLE001 — 메일 실패는 워크플로를 죽이지 않음
        print(f"[warn] 메일 발송 실패(무시): {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
