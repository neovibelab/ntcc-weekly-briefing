# weekly-vibe - 일일 수집 엔진 (vibe_search v3)

> **역할**: 엔터·문화 산업 뉴스의 일일 자동 수집 엔진. 5개 검색 프로파일을 현지 발행 리듬에 맞춰 3개 시간대(오전 한국·일본 / 오후 중국·동남아 / 저녁 영어권)로 수집해 Discord 5개 채널에 알리고 Supabase `radar_items`에 적재한다. **저장되는 지역 값은 12종이고 검색 프로파일과 다른 층이다**(§1-4).
>
> **주간 브리핑(NEWSPAPER HTML) 발행은 폐기**(2026-06-09). 과거 발행물(`NEWSPAPER_*.html` · `SPECIAL_*.html` · `index.html` · `preview/`)은 역사 아카이브로만 보존하고 신규 생성하지 않는다. 제작 스킬(`.claude/skills/weekly-vibe/`)은 삭제됐다. 구 제작 가이드는 이 파일의 git 히스토리(2026-06-10 이전)에 있다.
>
> **`weeklybriefing.vercel.app` 공개 배포는 삭제**(2026-07-28 대표 결정). 삭제 대상은 Vercel 프로젝트 하나뿐이고 이 수집 엔진은 계속 돈다. (경위 → DR)
>
> **정본 관계**: 운영 워크플로(무엇을·언제·왜)는 [`OPERATING-MODEL.md`](../OPERATING-MODEL.md) §2 · 아키텍처·deprecated는 루트 [`CLAUDE.md`](../CLAUDE.md) §5 · 결정 경위·실측·사고 이력은 [`DECISION-RATIONALE.md`](DECISION-RATIONALE.md)(이하 DR). 이 파일은 매 턴 상주하므로 길이가 곧 비용이다. 여기에는 규칙만 적고, 규칙을 고치려 할 때는 DR을 먼저 읽는다.

---

## 1. 수집 파이프라인

```
격일 3개 시간대 KST (GitHub Actions ai-news-daily.yml - cron 3개 */2. vibe_search만 격일, newsletter·newsroom은 매일)
  오전 07시 한국·일본 / 오후 14시 중국·동남아 / 저녁 21시 글로벌(영어)
    → scripts/vibe_search.py (Claude Sonnet web_search, 해당 시간대 지역 순차)
    → 품질 게이트 (validate_candidates → URL 생존 확인)
    → Discord 5개 지역 채널 알림 + Supabase radar_items upsert
    → 대시보드 큐레이션: https://nvl-vibe-radar.vercel.app/
```

| 지역 | 언어 | Discord 채널 | Secret |
|------|------|-------------|--------|
| 한국 | 한국어 | `#korea_vibe` | `DISCORD_KOREA_WEBHOOK` |
| 영어권 검색 | 영어 | `#global_vibe` | `DISCORD_GLOBAL_EN_WEBHOOK` |
| 중국 | 중국어 | `#vibe-china` | `DISCORD_CHINA_WEBHOOK` |
| 일본 | 일본어 | `#vibe-japan` | `DISCORD_JAPAN_WEBHOOK` |
| 동남아 | 영어+현지 | `#asia_vibe` | `DISCORD_SOUTHEAST_ASIA_WEBHOOK` |

- **엔진**: `scripts/vibe_search.py` - Claude Sonnet `web_search` 서버사이드 도구(스트리밍 호출). 지역당 1~5건, 기준 충족 후보 없으면 그날은 생략. 단일 워크플로에서 각 step `if`가 `github.event.schedule`·수동 region input으로 분기하고, skip 지역은 outcome=skipped라 실패 경보에 걸리지 않는다. (시간대 분산·격일 전환 경위 → DR)
- **나이컷**: 한·글·일 120h, 중·동남아 168h(`MAX_AGE_HOURS`). robots.txt로 막힌 일간지(조선·중앙·FT·Reuters 등)는 뉴스레터 구독으로 흡수한다 - 발신자만 `sources_newsletters.json`에 추가.
- **적재**: `scripts/supabase_writer.py` - REST API upsert → `radar_items`. env `SUPABASE_URL`·`SUPABASE_KEY`(GitHub Secrets). nvl-vibe-radar 자체 수집기는 폐기됐다. 풀을 채우는 수집기는 vibe_search(웹)·newsletter_ingest(§1-1)·newsroom_ingest(§1-2)·interview_ingest(§1-3)·gnews_ingest(구글 뉴스 RSS) 다섯이고, radar는 조회·큐레이션 대시보드(collector/region 필터)다.
- **풀 유지보수**: `scripts/pool_maintenance.py`. 자동수집 pending은 최신순 `POOL_KEEP`(50)개만 남기고 초과분 archived. 픽은 20일 시효(`picked_expiry_targets`, interview 픽 면제). 시의성 묶음은 10일 방치 시 삭제, 에버그린·to_draft/drafted 묶음 멤버만 시효 면제(v12 `clusters.evergreen` 미적용이면 생략·전 묶음 보호. 묶음 자체는 2026-09-02 폐기 - 루트 §5). Supabase 전 행 조회는 반드시 `_fetch_paged`(Range 헤더 + id 정렬 순회) - PostgREST는 `limit`과 무관하게 1,000행에서 자른다. (경위 → DR)
- **중복 제거**: `seen-titles.txt` + Supabase URL 중복 체크.
- **태깅**: 7렌즈 멀티태깅(`fan-behavior` `consumer-behavior` `ent-deals` `ip-business` `artist-ownership` `tech-issues` `taste-values`, `topics` 배열). **`cross-industry` 태그는 만들지 않는다**(대표 결정) - 레퍼런스는 일부 신호의 속성이 아니라 전 콘텐츠의 해석 렌즈다. 타 업종 이전 원리 판정은 대시보드 보조·추천 프롬프트(nvl-vibe-radar `REF_FRAME`)가 한다. `taste-values` = 세대를 가로지르는 취향·가치 신호(지속가능·로컬·디깅·리바이벌·취향 공동체, 엔터 밖 패션·뷰티·F&B·여행·리테일 포함). 구 `gen-z-lifestyle`(Z세대 인구통계 축)의 재정의. **키 동기화 필수** - 같은 풀(`radar_items.topics`)을 쓰는 `newsletter_ingest.py`·`newsroom_ingest.py`의 `TOPIC_KEYS`, `nvl-vibe-radar`(`app.py` VALID_TOPICS·`dashboard.html` 필터/TOPICS/CROSS_CUL)도 함께 바꾼다. 대시보드는 과거 `gen-z-lifestyle`을 alias로 호환(마이그레이션 불필요). (경위 → DR)
- **출력 언어**: 모든 외국어 기사 제목은 한국어 번역. JSON 파싱은 `_parse_json_robust()` 3단계 폴백(원본→수리→개별 객체 추출).
- **개별 테스트**: `ai-news-daily.yml`의 `workflow_dispatch` region input(all/korea/global-en/china/japan/southeast-asia). 이건 **검색 프로파일**이지 저장 지역이 아니다(아래 §1-4).
- **실패 경보**: 지역 스텝이 검색 실패(web_search API·코드 에러)로 끝나면 `scripts/notify_region_failure.py`가 woojin@에 메일. **0건(정상)과 실패를 종료코드로 구분한다** - vibe_search는 검색 실패만 `exit 1`, 워크플로가 각 지역 `outcome`을 모아 `failure`만 통지(정상 0건엔 메일 없음). 실패를 exit 0으로 가리는 `|| echo`는 쓰지 않는다. (경위 → DR)

**§1-1~1-3 공통**: Discord 미포스팅·대시보드 전용, `total_score=0`(사전 큐레이션 소스), 대시보드에 출처 배지. 시크릿은 `SUPABASE_*` + ANTHROPIC `ANTHROPIC_API_KEY_WEEKLY_BRIEFING` 재사용(피드는 무인증이라 신규 시크릿 없음). 피드 URL은 **실제 fetch로 유효 XML을 검증한 뒤 등재**(죽은 피드, 헤더만 주고 본문이 빈 깡통[예: Sanrio] 주의), `_` 접두 = 비활성. 소스 추가·제거는 각 JSON만 편집.

## 1-1. 뉴스레터 수집기 (collector='newsletter')

vibe_search와 같은 풀(`radar_items`)을 공유하는 두 번째 수집기. 대표의 뉴스레터·AI서비스 전용 계정(tmifmdj@gmail.com)으로 구독하는 정예 뉴스레터를 소스 풀에 합친다.

- **엔진**: `scripts/newsletter_ingest.py` - Gmail IMAP 앱비밀번호(stdlib `imaplib`, OAuth·검증 불필요) → allowlist 발신자의 최근 메일 → 본문 추출·추적URL 복원(base64 경로 디코드) → Claude haiku 분류(7렌즈 topics + 한국어 요약) → upsert. 지역은 발신자별 고정 힌트(본문 분류 비의존).
- **allowlist**: `sources_newsletters.json` - 발신자 47곳 = 엔터·문화·소비 직결 35 + `broad` 12(일반·테크·비즈 종합 매체). `broad:true` 소스는 `classify`가 is_entertainment 게이트를 넓혀 다른 영역의 교차 신호까지 채택(순수 하드뉴스만 제외) - "음악·엔터 밖에서 교차성·인사이트 발굴" 대표 지시. 고신호는 **발신자**로 유지한다(받은편지함 대부분이 노이즈라 탭 통째 수집 안 함). (스윕 이력·보류 발신자 → DR)
- **스케줄**: `.github/workflows/newsletter-ingest.yml` 하루 2회 - **09:30 KST**(아침 클러스터) + **23:00 KST**(저녁 클러스터) + `workflow_dispatch`(lookback_days). lookback 2일 + URL dedup이라 2회가 겹쳐도 안전.
- **시크릿**: `GMAIL_USER`·`GMAIL_APP_PASS`(IMAP 앱비밀번호).
- **중복 제거**: 최근 14일 newsletter URL 집합(Supabase 조회) + URL upsert(merge-duplicates).
- **캐치올 제목 게이트**(대표 지시 "발신자가 아니라 제목 기준으로도"): allowlist 밖 발신자의 메일도 제목이 엔터·콘텐츠·미디어·문화·소비 신호면 수집한다. 2단 게이트 - ① 런당 haiku 1콜로 제목 배치 판정(`subject_gate`, 프로모·행사·계정알림·하드뉴스 제외, 애매하면 제외) ② 통과분만 본문 fetch·strict classify(비-broad 규칙). 런당 상한 `NL_CATCHALL_CAP`(기본 8), `NL_CATCHALL=0`으로 끔. `catchall_ignore`(JSON 최상위 키) = 트랜잭션·서비스 알림 제외 목록 - **편집 매체는 넣지 않는다**(제목 게이트가 건별 판정). 캐치올 수집분의 source=발신 도메인.
- **주간 발신자 스캔**: `scripts/newsletter_sender_scan.py` + `newsletter-sender-scan.yml`(**월 09:00 KST** + dispatch dry_run). 최근 7일 발신자를 allowlist(비활성 `_` 포함)·catchall_ignore와 대조해 미등재 발신자를 통수·예시 제목과 함께 woojin@에 리포트(0건이면 메일 없음). **등재 판단은 사람**(세션 "뉴스레터 스윕"), 무시는 catchall_ignore에 추가. 캐치올 = 개별 신호 안전망 / 스캔 = 발신자 승격 제안.

## 1-2. 뉴스룸 수집기 (collector='newsroom')

같은 풀을 공유하는 세 번째 수집기. 주요 엔터·미디어·IP홀더 기업의 뉴스룸/블로그 RSS·Atom 피드에서 1차 발표를 가져온다.

- **엔진**: `scripts/newsroom_ingest.py` - RSS(`item`)·Atom(`entry`) 피드 fetch(stdlib `xml.etree`, 외부 feedparser 불필요) → 룩백 내 항목 → Claude haiku 분류(7렌즈 + 한국어 요약) → upsert. 지역은 소스별 고정 힌트.
- **allowlist**: `sources_newsrooms.json` - 피드 검증된 9소스(Disney·Netflix·Apple·Spotify·YouTube·UMG·WMG·Sony Music·Toei).
- **차단 도메인은 `allowed_domains`에 넣을 수 없다.** Anthropic 크롤러 차단 도메인이 하나만 끼어도 web_search API가 요청 전체를 400으로 거부한다. 추가하려면 `probe_domains.py`로 사전 검증 후 통과분만. 피드 있는 IP홀더(Sony Music 등)는 newsroom 수집기가 흡수하고, **피드 없는 곳(Sony 그룹·Nintendo·Bandai·Crunchyroll·WBD·NBCU·Paramount)은 `vibe_search.py` `search_terms`에 회사 키워드로 흡수**한다(global-en ent-deals·ip-business + japan ip-business). 키워드는 400에 안전하고, 신뢰 매체의 해당 기업 보도(분석·딜)를 찾는다. (사고 경위 → DR)
- **스케줄**: `.github/workflows/newsroom-ingest.yml` 매일 **10:00 KST**(01:00 UTC) + `workflow_dispatch`(lookback_days). **lookback 7일**.
- **중복 제거**: 최근 30일 newsroom URL 집합(Supabase 조회) + URL upsert.

## 1-3. 인터뷰 수집기 (collector='interview')

같은 풀을 공유하는 수집기 다섯 중 하나. 국내외 아티스트·창작자 인터뷰(텍스트·영상)를 모아 대시보드 인터뷰 탭에 노출한다. 용처 = @nvl.seoul "insight/quote/reels" 소재 파이프라인 + Icon Lab 인물 발굴 레이더.

- **엔진**: `scripts/interview_ingest.py` - 매체 RSS·유튜브 채널 RSS(`videos.xml?channel_id=UC…`) fetch(stdlib `xml.etree`) → Claude haiku 분류 → **is_interview=true만** upsert. YouTube Atom의 `<media:group>` 중첩 제목·설명도 파싱(newsroom 파서 확장). 지역은 소스 고정 힌트(분류 값 우선).
- **분류 게이트**: haiku가 두 축을 따로 판정하고 **둘 다 true여야 적재**한다. ① `is_interview`(형태 - 아티스트 본인 발화 중심만 true. 뉴스·리뷰·차트·퍼포먼스 단독·MV·리스트는 false, 애매하면 false = 정밀 우선) ② `is_music_ent`(주제 - 발화 내용이 음악·엔터 창작이나 그 산업이면 true. 연애·육아·건강·심리·창업·테크·정치는 false. **말하는 사람이 아티스트여도 주제가 음악·엔터가 아니면 false**). 모델이 `is_music_ent` 키를 빠뜨리면 통과시킨다. 그 밖에 `person_ko`(주 인물 한국어 표기)·title_ko/summary_ko/region. summary는 "인물 - 요지" 관례. `is_interview=false`·분류실패는 `filtered_out`(verdict `not_interview`/`classify_failed`)로 적재해 풀·인터뷰탭에서 숨긴다. (주제 축 신설 경위 → DR)
- **allowlist**: `sources_interviews.json` - 30소스 중 활성 8(영상 7 + 텍스트 1, 2026-09-02 대표 지시). 남긴 기준 = 실적 → 영상 → 음악·창작 주제 → 국내 1 → 텍스트 1. **뺀 사유는 각 항목 `_reason`에 적는다**(되살릴 때 왜 뺐는지 보이게). 유입이 부족해지면 FADER·GRAMMYS부터 되살린다. 각 소스 `media`("text"|"video") 힌트 → 대시보드 `tags`. (축소 근거·실측 → DR)
- **스케줄**: `.github/workflows/interview-ingest.yml` **화·금 11:00 KST**(02:00 UTC) + `workflow_dispatch`(lookback_days). 주 2회, **룩백 14일·나이컷 없음**. 대시보드 인터뷰 탭 노출. GitHub 신규 예약 워크플로는 첫 예정 발화를 스킵한다 - 첫 자동 수집이 안 보이면 `workflow_dispatch` 1회 수동.
- **중복 제거**: 최근 **60일** interview URL 집합 + URL upsert(merge-duplicates).
- **픽 시효 면제**: `pool_maintenance.py`의 픽 20일 시효(`picked_expiry_targets`)에서 `collector='interview'` 픽은 면제(소스 뱅크 이관 전까지 보존). 뉴스성 픽에만 20일 적용.

## 1-4. 지역 축 (2026-09-10 개편)

**검색 프로파일 5종과 저장 지역 12종은 다른 층이다.** 프로파일은 「어느 언어로 검색해 어느 디스코드 채널에 알리나」이고, 저장 지역은 「그 기사가 다루는 시장이 어디인가」다.

- **저장 값 12종** (`radar_items.region`): `korea` `japan` `china` `southeast-asia` `north-america`(미국·캐나다) `europe`(영국·독일·프랑스·북유럽·동유럽) `latin`(스페인어권·브라질) `mena`(중동·북아프리카) `africa-ssa`(사하라이남) `india-sa`(인도·남아시아) `oceania`(호주·뉴질랜드) `multinational`(특정 국가 귀속 없는 다국적 발표·업계 일반론·글로벌 통계).
- **`global-en`은 신규 저장하지 않는다.** 과거 archived 행이 수천 건이라 라벨 맵에만 「글로벌(구)」로 남는다. 분류가 실패했을 때 소스 힌트로 남는 값도 이 레거시이고, **12종 중 하나를 억지로 찍지 않는다** - `backfill_region.py`가 나중에 내용 기준으로 다시 판정한다.
- **분류 기준(모든 프롬프트 공통 문구)**: 매체 국적이나 기업 본사가 아니라 **기사 내용의 시장**. 여러 시장이면 비중이 큰 쪽 하나. 어느 나라에도 귀속되지 않는 다국적 발표·업계 일반론만 `multinational`이고, **모르겠다고 여기 넣지 않는다.** 각 수집기의 `REGION_GUIDE` 상수가 같은 문장을 쓴다 - 하나를 고치면 다섯을 같이 고친다(`newsletter_ingest`·`newsroom_ingest`·`interview_ingest`·`backfill_region`·`gnews_ingest`).
- **검색 프로파일 5종**은 그대로다(`vibe_search.py` REGIONS 키 = cron 슬롯·webhook·allowed_domains). `global-en` 프로파일 이름만 「영어권 검색」으로 바꿨다. 그 결과의 region은 저장 시점엔 미판정이고 `backfill_region.py --collectors vibe_search`가 재판정한다.
- **gnews는 gl 매핑을 버렸다.** 구글 뉴스 에디션은 독자의 위치지 기사의 시장이 아니다. 지금은 엔터 게이트 haiku가 `region`을 함께 판정하고(**호출 수 불변**), 판정이 없을 때만 gl 표로 떨어진다.
- 라벨은 `supabase_writer.py` `REGION_LABELS` = `send_report_drop.py` `_REGION_LABELS` 두 곳이 같은 문자열을 쓴다.

## 2. 품질 게이트

Anthropic `web_search` 도구에 날짜 필터 파라미터가 없어 코드 레벨로 강제한다.

1. 프롬프트에 오늘 날짜(KST)+컷오프 주입, `published_date` 필드 요구
2. **출처 화이트리스트** - 지역별 `allowed_domains`(주요 일간지·주간지·매거진·전문지)로 web_search 검색 자체를 제한 + 코드 검증에서 목록 외 출처 제외(보도자료 재가공 매체 차단, 대표 지시). `BLOCKED_DOMAINS`(나무위키)는 별개 방어선
3. `validate_candidates()` - 필수 필드·한국어 요약·**4지표 점수 재계산(≥4)**·발행일 48시간 컷(`MAX_AGE_HOURS` env로 조정, 지역별 값은 §1). 점수 4지표 = 소재적합·캐러셀적합·출처신뢰·교차정체성(각 0~2, 만점 8). 임계 `MIN_TOTAL_SCORE` 기본 4(만점의 50%, env 조정 - 0건 반복 시 3으로 완화). **발행일 미상은 제외**(신뢰성, 대표 지시). 0건이 반복되면 `ALLOW_UNDATED=1`로 임시 완화(플래그 게재). `radar_items`에 `cross_identity` 개별 컬럼은 없다(total_score에 합산만, 개별 표시가 필요하면 마이그레이션 후속)
4. 점수순 정렬(동점 시 reliability→발행일 확인분 우선) → 배치 내 중복 제거 → **도메인당 2건 상한**(`MAX_PER_DOMAIN`, 1차 패스로 한 매체 독식 방지. 미달 시 2차 패스에서 상한을 풀어 건수 보존) → URL 생존 확인(`check_url_alive`, 404/없는 도메인 차단) → 최대 5건
5. 드롭 통계를 Discord 헤더 subtext + GitHub Actions Step Summary에 노출

단위 테스트: `scripts/test_quality_gate.py`. (도입 경위·4지표 개편 → DR)

## 3. 절대 금지 (위반 시 작업 중단)

- **기억·지식 기반으로 뉴스를 만들어내지 않는다.** 훈련 데이터의 사실, 그럴듯한 추정, 생성된 가짜 URL 일체 금지.
- 모든 기사는 **세션 내 검색·fetch로 직접 확인한 것**만. URL 검증 불가능하면 제외하고, 건수가 부족해도 채우지 않는다.
- "지식 기반 소스 활용", "URL 검증 생략" 같은 판단을 스스로 내리지 않는다.

## 4. 주간 리포트 드롭 (별개 흐름, 존속)

뉴타입컬처클럽 자료실용 산업 리포트 큐레이션. 일일 뉴스 수집과 별개.

- 생성: `/report-scan` 스킬(미네바) - **격주(2주 1회) 운영**(대표 결정). 4언어 검증 → `drops/YY.MM.DD-주간리포트드롭.md` 2곳 저장(weekly-vibe/drops/ + ecri-ceo-staff/operations/) + 마스터 색인 반영(색인이 SSOT)
- 발송 로직: `scripts/send_report_drop.py` - 최신 드롭 찾기·정제(HTML주석 제거·2000자 컷)·Discord 전송. 정시·백업 공용 모듈(stdlib). 워크플로 YAML 안에 heredoc으로 로직을 넣지 않는다. 세 가지 필수 - **① 명시 User-Agent**(urllib 기본 UA는 Discord Cloudflare가 403/`error 1010`으로 차단. vibe_search `send_to_discord`는 `requests` UA로 통과 중이라 명시 UA는 후속 권장·미적용) **② 격주 중복방지: 드롭이 `DROP_MAX_AGE_DAYS`(기본 7)일 이상 지났으면 발송 생략**(`return 0` → 정시 워크플로 success 유지 → watchdog 오경보 없음) **③ 대시보드 적재: 발송 직후 드롭의 1위 메달+신규 리포트를 파싱(`parse_drop_items`)해 `radar_items`에 `collector='newsroom'`으로 적재 → 대시보드 뉴스룸 탭**(다시보기=기보유는 제외, URL 중복 merge-duplicates, `SUPABASE_URL/KEY` env를 정시+백업 워크플로 양쪽에 주입). (403 원인·경계값 버그 → DR)
- 포스팅(정시): `.github/workflows/discord-report-drop.yml` - 매주 월요일 **10:17 KST** cron. 실제 발송은 위 신선도 가드로 **새 드롭 있을 때만 = 격주 리듬**(cron은 매주지만 stale 드롭은 재발송하지 않는다).
- 백업 감시: `.github/workflows/report-drop-watchdog.yml` - 월 **10:40 KST** 점검 → 정시 누락 시 직접 재발송 + woojin@ 메일 알림(`check_drop_posted.py` 발송판정·`send_drop_alert.py` 메일). GitHub cron best-effort 누락 대비. 중복 발송·지연 레이스 가드 포함.

## 5. 파일 구조

```
weekly-vibe/
├── CLAUDE.md                    ← 이 파일 (규칙만)
├── DECISION-RATIONALE.md        ← 결정 경위·실측·사고 이력 (규칙 수정 전 필독)
├── scripts/
│   ├── vibe_search.py           ← 수집 엔진 v3 (5지역)
│   ├── supabase_writer.py       ← radar_items upsert
│   ├── send_report_drop.py      ← 리포트 드롭 발송 공용 모듈 (정시+백업)
│   ├── check_drop_posted.py     ← 백업: 오늘 발송 여부 판정 (gh 런 이력)
│   ├── send_drop_alert.py       ← 백업: 리포트 드롭 누락 시 woojin@ 메일 알림
│   ├── notify_region_failure.py ← 지역 검색 실패 시 woojin@ 메일 경보
│   ├── newsletter_ingest.py     ← 뉴스레터 IMAP 수집기 (§1-1)
│   ├── newsletter_sender_scan.py ← 미등재 발신자 주간 리포트 (§1-1)
│   ├── newsroom_ingest.py       ← 뉴스룸 RSS 수집기 (§1-2)
│   ├── interview_ingest.py      ← 인터뷰 RSS·유튜브 수집기 (§1-3)
│   ├── gnews_ingest.py          ← 구글 뉴스 RSS 수집기 (collector='gnews')
│   ├── pool_maintenance.py      ← 풀 유지보수(상한 archive + 픽 시효 + 묶음 시의성 시효)
│   ├── probe_domains.py         ← allowed_domains 후보 사전 검증
│   └── test_quality_gate.py     ← 품질 게이트 단위 테스트
├── sources_newsletters.json     ← 뉴스레터 발신자 allowlist
├── sources_newsrooms.json       ← 뉴스룸 피드 allowlist
├── sources_interviews.json      ← 인터뷰 피드·채널 allowlist
├── .github/workflows/
│   ├── ai-news-daily.yml        ← 격일 3시간대 수집
│   ├── newsletter-ingest.yml    ← 매일 09:30·23:00 KST
│   ├── newsletter-sender-scan.yml ← 월 09:00 KST
│   ├── newsroom-ingest.yml      ← 매일 10:00 KST
│   ├── interview-ingest.yml     ← 화·금 11:00 KST
│   ├── gnews-ingest.yml         ← 매일
│   ├── discord-report-drop.yml  ← 월 10:17 KST 정시 리포트 드롭
│   └── report-drop-watchdog.yml ← 월 10:40 KST 백업(누락 시 재발송+메일)
├── drops/                       ← 주간 리포트 드롭 마크다운
├── seen-titles.txt              ← 중복 제거 캐시
└── NEWSPAPER_*.html 등          ← 구 주간 브리핑 발행물 (역사 아카이브, 신규 생성 금지)
```

## 6. 변경 이력

날짜별 변경 이력과 근거는 [`DECISION-RATIONALE.md`](DECISION-RATIONALE.md) §6으로 옮겼다(2026-09-04). 여기에는 더 쌓지 않는다 - 새 변경은 DR에 날짜·근거와 함께 적고, 이 파일에는 바뀐 규칙만 반영한다.
