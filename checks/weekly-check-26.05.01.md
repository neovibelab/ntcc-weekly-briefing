# 주간 자동 발행 점검 — 26.05.01

**점검 일시**: 2026-05-01 20:30 KST (11:30 UTC)  
**점검 주체**: 아스토나지 (Neo Vibe Lab 개발 담당 에이전트)  
**대상 호**: NEWSPAPER_0502.html (2026-05-02 토요일 발행 예정)  
**자동 발행 트리거**: cron `0 11 * * 5` (금 11:00 UTC = 20:00 KST)

---

## 점검 결과 요약

| 항목 | 결과 | 비고 |
|------|------|------|
| 자동 발행 커밋 존재 | ❌ FAIL | 오늘(2026-05-01) 신규 커밋 없음 |
| NEWSPAPER_0502.html 존재 | ❌ FAIL | 파일 미생성 |
| 라이브 사이트 200 응답 | ✅ PASS | HTTP 200, Vercel 정상 |
| 라이브 최신 호 (0502) | ❌ FAIL | last-modified: 2026-04-29 (0425호 기준) |
| index.html 0502 엔트리 | ❌ FAIL | 미추가 |
| NEWSPAPER_0425 마스트헤드 날짜 | ✅ PASS | `2026년 4월 25일 토요일 (4.19–4.25)` |
| NEWSPAPER_0425 Vol. 번호 | ✅ PASS | `Vol. 07` |
| TL;DR 라벨 | ✅ PASS | "이번 주 이슈 요약" (영문 TL;DR 아님) |
| 인사이트 섹션 헤더 | ✅ PASS | "인사이트" |
| 환율 푸터 | ✅ PASS | `$1 = ₩1,481` (2026-04-23 기준) |
| 이전 호 nav `다음 호 →` | ✅ PASS | `nav-disabled` (0502 미발행이므로 정상) |
| TEST_*.html 커밋 제외 | ❌ FAIL | `TEST_0425.html`이 git 추적됨 (commit 08611fd) |
| internal/ 커밋 제외 | ✅ PASS | .gitignore 등록 확인 |
| 딥다이브 내부 파일 생성 | ⚠️ 미확인 | 워크플로우 미실행으로 미생성 추정 |
| GitHub Actions 실행 상태 | ⚠️ 미확인 | MCP 도구에 workflow run 조회 기능 없음 |

**STEP 7 체크리스트: 6/15 통과** (자동 발행 산출물 항목 제외 시 6/9)

---

## 발견 이슈

### 이슈 1: 자동 발행 미완료 (심각도: HIGH)

**현상**: 오늘(2026-05-01 금요일) `NEWSPAPER_0502.html`이 생성되지 않음. cron(`0 11 * * 5`) 기준 11:00 UTC에 트리거됐어야 하나, 11:30 UTC 기준 origin/main에 신규 발행 커밋 없음.

**가능한 원인**:
- GitHub Actions 워크플로우 실행 중 (최대 90분 타임아웃 → 12:30 UTC까지 완료 가능)
- 워크플로우 실패 (최근 `fix(ci)` 커밋 3건이 있어 불안정 가능성)
- Anthropic API 레이트 리밋 (워크플로우에 `STEP_SLEEP: 90` 설정되어 있음)
- 기타 환경 오류

**재현 명령**:
```bash
# 로컬에서 확인
git log --oneline --after="2026-04-30" origin/main
ls NEWSPAPER_0502.html
# GitHub Actions 로그는 웹 UI 또는 gh run list로 확인
```

**권장 조치**:
1. GitHub Actions 웹 UI에서 오늘 실행 상태 확인 (https://github.com/neovibelab/weeklybriefing/actions)
2. 실패 시 `workflow_dispatch` 수동 재트리거 (from_step: A)
3. 90분 경과(12:30 UTC) 후에도 커밋 없으면 수동 발행 진행

---

### 이슈 2: TEST_0425.html이 git에 커밋됨 (심각도: MEDIUM)

**현상**: `.gitignore`에 `TEST_*.html`이 등록되어 있으나, `TEST_0425.html`이 `08611fd` 커밋에 포함되어 현재 git에 추적 중.

**원인**: PR #2(`docs/test-file-rules`) 머지 시점에 `.gitignore` 추가와 파일 생성이 동시에 이루어졌으며, 이미 staged된 파일은 .gitignore로 소급 제외되지 않음.

**재현 명령**:
```bash
git ls-files TEST_0425.html
# 출력: TEST_0425.html (추적 중)
```

**권장 조치**:
```bash
git rm --cached TEST_0425.html
git commit -m "fix: TEST_0425.html git 추적 해제 (.gitignore 소급 적용)"
git push origin main
```

---

### 이슈 3: 딥다이브 내부 파일 미확인 (심각도: LOW)

**현상**: `internal/26.05.02-deepdive-candidates.md` 생성 여부 확인 불가. 자동 발행 워크플로우 미완료로 인해 미생성 추정.

**권장 조치**: 발행 완료 후 워크플로우 artifact 또는 로컬 `internal/` 폴더에서 확인.

---

## 최근 커밋 히스토리 (참고)

```
c7f0ffd fix(ci): Step D 헤더 메타를 sed로 결정적 치환
3155b52 fix(ci): Verify의 마스트헤드 날짜 검증 완화 + staging artifact 누락 수정
20ad86d fix(ci): <title> 날짜 형식을 점 구분(YYYY.MM.DD)으로 통일
dc6885d ci: 주간 브리핑 워크플로우 분할 실행 재설계 (레이트 리밋 회피, 12 step + 모델 분리)
35a6dce style: 호별 제목을 단일 핵심 주제로 압축 (15~25자 통일)
```

최근 5건 중 4건이 CI 관련 수정으로, 워크플로우 안정성 이슈가 지속되고 있음.

---

## 권장 후속 조치 (우선순위 순)

1. **[즉시]** GitHub Actions 웹 UI에서 오늘 실행 상태 확인
2. **[즉시]** 실패 확인 시 수동 `workflow_dispatch` 재트리거
3. **[오늘 중]** 12:30 UTC까지 `NEWSPAPER_0502.html` 미생성 시 수동 발행
4. **[이번 주]** `TEST_0425.html` git 추적 해제 (`git rm --cached`)
5. **[이번 주]** 워크플로우 `fix(ci)` 커밋 시리즈 점검 — 안정화 여부 확인
