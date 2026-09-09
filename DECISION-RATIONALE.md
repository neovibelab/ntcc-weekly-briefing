# weekly-vibe 결정 근거·사고 이력 아카이브

> [`CLAUDE.md`](CLAUDE.md)에서 분리한 "왜 그렇게 됐나" 기록이다(2026-09-04 분리, NVL 루트 [`agents/DECISION-RATIONALE.md`](../agents/DECISION-RATIONALE.md)와 같은 방식). CLAUDE.md는 매 턴 컨텍스트에 상주하므로 "지금 무엇이 규칙인가"만 남기고, 결정 경위·실측·사고 이력은 여기로 내렸다. **원문을 요약하지 않고 그대로 옮겼다** - 압축 시점의 CLAUDE.md 문장을 규칙별 소제목 아래 보존한다.
>
> **효력은 동일하다.** 여기 적힌 사고 이력은 규칙의 존재 이유라서, 규칙을 고치려 할 때 반드시 먼저 읽는다. 규칙만 보고 "불필요해 보인다"고 판단하면 같은 사고를 반복한다.
>
> 절 번호는 CLAUDE.md의 절을 가리킨다.

---

## 헤더 - 역할 전환·주간 브리핑 폐기·Vercel 배포 삭제

> **역할 (2026-06-09 전환)**: 엔터·문화 산업 뉴스의 **일일 자동 수집 엔진**. 매일 5개 지역을 현지 발행 리듬에 맞춰 3개 시간대로 나눠(오전 한국·일본 / 오후 중국·동남아 / 저녁 글로벌, 2026-06-17) 수집해 Discord 5개 지역 채널에 알리고 Supabase `radar_items`에 적재한다.
>
> **주간 브리핑(NEWSPAPER HTML) 발행은 2026-06-09 폐기.** 과거 발행물(`NEWSPAPER_*.html` · `SPECIAL_*.html` · `index.html` · `preview/`)은 역사 아카이브로만 보존한다. 제작 스킬(`.claude/skills/weekly-vibe/`)은 2026-06-10 삭제. 구 제작 가이드(태그 시스템·디자인 시스템·검증 체크리스트)가 필요하면 이 파일의 git 히스토리(2026-06-10 이전) 참조.
>
> **`weeklybriefing.vercel.app` 공개 배포는 2026-07-28 대표 결정으로 삭제** - 워크플로만 지운 상태로 2개월간 05-30에 얼어붙은 페이지가 ECRI 브랜딩으로 공개돼 있었다(07-28 실측 HTTP 200). 발행 뉴스레터가 이 URL을 링크한 곳은 없어 끊어질 독자 경로는 없다(md-archive 5편의 매치는 메일리 태그 `weeklybriefing`이지 URL 아님). **이 수집 엔진 자체는 계속 돈다** - 삭제 대상은 Vercel 프로젝트 하나뿐이다.

---

## §1 - 격일 전환·나이컷 (2026-06-29)

- 2026-06-29: **vibe_search 격일 전환** (`ai-news-daily.yml` cron 3개 `*/2` + step if 동기화). Sonnet web_search가 토큰 비용 주범인데 수확은 풀의 20%뿐 → 격일로 ~절반 절감. newsletter·newsroom(haiku·고수확·robots.txt 우회)은 **매일 유지**. 한·글·일 나이컷 72→120h(격일 갭+주말 보강), 중·동남아는 168h 유지. ※커버리지 정공법은 차단 일간지(조선·중앙·FT·Reuters 등 robots.txt 막힘)를 newsletter 구독으로 흡수 - 발신자만 `sources_newsletters.json`에 추가.

## §1 - 수집 시간대 분산 (2026-06-17)

- 2026-06-17: 수집 시간대 분산 - `ai-news-daily.yml` 단일 cron(07:00 일괄)에서 cron 3개로(07:00 한·일 / 14:00 중·동남아 / 21:00 글로벌). 지역별 현지 발행 리듬에 맞춰 신선도↑. 단일 워크플로 유지(각 step `if`가 `github.event.schedule`·수동 region input 분기), skip 지역은 outcome=skipped라 실패 경보 무영향.

## §1 - 적재: radar 자체 수집기 폐기 (2026-06-09)

원문(§1 적재 항목): nvl-vibe-radar 자체 수집기는 2026-06-09 폐기 - 풀을 채우는 수집기는 **vibe_search(웹)·newsletter_ingest(구독 뉴스레터, §1-1)·newsroom_ingest(기업 뉴스룸 RSS, §1-2) 3개**이고 radar는 조회·큐레이션 대시보드(collector/region 필터).

(2026-09-04 주: 이후 interview_ingest(2026-07-09)·gnews_ingest(2026-09-02)가 추가돼 CLAUDE.md는 "다섯"으로 적는다.)

## §1 - 풀 유지보수: PostgREST 1,000행 캡 (2026-07-14) · 묶음 2종 수명제 (2026-07-15)

- 2026-07-15: **pool_maintenance에 묶음 2종 수명제 반영** (nvl-vibe-radar v12 `clusters.evergreen`과 세트, 대표 결정). ① 정리 ③ 신설 - 시의성 묶음(evergreen=false, open·synthesized)이 10일(updated_at) 방치되면 묶음+멤버링크 삭제. ② 픽 20일 시효의 묶음 면제를 **에버그린·to_draft/drafted 묶음 멤버로 축소** - 구 "모든 묶음 멤버 면제"는 대시보드 추천이 매 실행 같은 옛 픽으로 묶음을 재생성해 옛 픽이 시효를 영원히 피하는 루프였음(추천 신선도 하락의 근원). v12 미적용 시 ③ 생략·전 묶음 보호로 안전 폴백. interview 픽 면제는 별개로 유지.
- 2026-07-14: **pool_maintenance PostgREST 1,000행 캡 버그 수정** - `fetch_all`이 `limit=10000`을 넘겨도 서버 max-rows(1,000)에 잘려, 테이블 1,304행 시점에 pending 227건 중 74건만 보고 "정리 대상 0건"으로 통과(풀 50 상한이 침묵 무력화, 관리 대상 pending 131건까지 누적 실측). `_fetch_paged`(Range 헤더 + id 정렬 페이지 순회) 신설로 `fetch_all`·`fetch_cluster_member_ids` 전 행 조회 전환, 수정 직후 apply로 초과분 81건 archived → 관리 풀 50건 복구.

## §1 - 태깅: `cross-industry` 당일 도입·회수 (2026-07-09)

원문(§1 태깅 항목): **`cross-industry` 태그는 만들지 않는다**(2026-07-09 당일 도입·회수, 대표 결정) - 엔터 레퍼런스 프레임에서 레퍼런스는 일부 신호의 속성이 아니라 전 콘텐츠의 해석 렌즈. 타 업종 이전 원리 판정은 수집 태깅이 아니라 **대시보드 보조·추천 프롬프트(nvl-vibe-radar `REF_FRAME`)** 담당.

- 2026-07-09: **`cross-industry` 병기 태그 당일 도입·회수** (대표 결정). 포지셔닝 재정의(엔터=타 산업 레퍼런스) 캐스케이드로 수집기 3종+대시보드에 태그를 실장했다가 같은 날 회수 - 레퍼런스는 일부 신호의 속성이 아니라 전 콘텐츠의 해석 렌즈라 태그 분리가 프레임과 모순(태그 없는 신호=교차 아님 역메시지). 프레임 적용은 nvl-vibe-radar 보조·추천 프롬프트(`REF_FRAME`)로 일원화. OPERATING-MODEL §0의 구 "cross-industry 플래그 병기" 문구(2026-06-08, 옛 프레임 유산)도 동시 폐기.

## §1 - 태깅: 세대 축 → 취향·가치 축 (2026-06-17)

원문(§1 태깅 항목): `taste-values`(취향·가치)는 **세대를 가로지르는** 취향/가치 신호 - 지속가능·로컬·디깅 문화·시티팝/Y2K 리바이벌·앰비언트·취향 공동체 등(엔터 밖 패션·뷰티·F&B·여행·리테일 포함). 구 `gen-z-lifestyle`(Z세대 인구통계 축)을 2026-06-17 재정의(메타 마케팅 서밋 "세대 말고 취향·가치관" 명제 반영). **키 동기화 필수** - 같은 풀(`radar_items.topics`)을 쓰는 `newsletter_ingest.py`·`newsroom_ingest.py`의 `TOPIC_KEYS`, `nvl-vibe-radar` 대시보드(`app.py` VALID_TOPICS·`dashboard.html` 필터/TOPICS/CROSS_CUL)도 함께 변경. 대시보드는 과거 누적 `gen-z-lifestyle` 항목을 alias로 호환(마이그레이션 무용).

- 2026-06-17: **세대 축 → 취향·가치 축 개편**(메타 마케팅 서밋 "세대 말고 취향·가치관" 명제 반영, 근거 `ecri-marketing/26.06.17-메타-마케팅-서밋-2026-인사이트.md` §4). ① 7번째 렌즈 `gen-z-lifestyle`(Z세대)→`taste-values`(취향·가치): TOPIC_LABELS·5지역 search_terms(각 지역 언어)·프롬프트 문단 모두 세대 라벨에서 세대 횡단 취향/가치 신호로 교체. ② 폐기된 `z_lifestyle_digest.py`의 ③교차정체성 지표를 4번째 스코어링 지표(`cross_identity`, 0~2)로 부활 - SCORE_KEYS 4개·만점 8·`MIN_TOTAL_SCORE` 3→4(env 조정)·Discord 배지 5→6·`_score_indicators` 반영. ③ 같은 풀 공유하는 `newsletter_ingest`·`newsroom_ingest`·`nvl-vibe-radar` 대시보드 키 동기화(대시보드는 구 키 alias 호환). 미해결: `radar_items`에 `cross_identity` 개별 컬럼 없음(total_score엔 합산 반영, 개별 표시 필요 시 마이그레이션 후속). 미배포(대표 검토 대기).

## §1 - 실패 경보 (2026-06-17)

원문(§1 실패 경보 항목): **실패 경보 (2026-06-17 신설)**: 지역 스텝이 검색 실패(web_search API·코드 에러)로 끝나면 `scripts/notify_region_failure.py`가 woojin@에 메일. **0건(정상)과 실패를 종료코드로 구분** - vibe_search가 검색 실패만 `exit 1`, 워크플로가 각 지역 `outcome`을 모아 `failure`만 통지(정상 0건엔 메일 안 감). 지역 스텝이 `continue-on-error`라 잡 전체는 success로 떠서 `gh run`·디스코드에 침묵 실패가 안 보이던 문제(06-15~16 글로벌 이틀 공백)의 능동 경보 장치. 구 `|| echo`(항상 exit 0으로 실패를 가리던 것)는 제거.

---

## §1-1 - 뉴스레터 수집기 신설·스케줄 근거 (2026-06-15)

원문(§1-1 제목·스케줄 항목): 뉴스레터 수집기 (collector='newsletter', 2026-06-15 신설). 스케줄 - **09:30 KST**(아침 클러스터: 빌보드·롱블랙·국내 일간 08시) + **23:00 KST**(저녁 클러스터: SCMP·Jing 2판·Nanjing·Marion) + `workflow_dispatch`(lookback_days). 받은편지함 실측 도착 시각 기반(2026-06-15). lookback 2일+URL dedup이라 2회 겹쳐도 안전(각 런은 직전 런 이후 신규만 적재).

## §1-1 - allowlist 스윕 이력·`broad` 도입 (2026-06-29 · 2026-07-16)

원문(§1-1 allowlist 항목): `sources_newsletters.json` - 발신자 47곳(2026-07-16 신규 구독 스윕 +19) = 엔터·문화·소비 직결 35(2026-06-29 스윕 보강 8 + 2026-07-16: Trapital·MUSIC x·WIN·Copyright Lately·InvestGame·The Pudding·ContentAsia·Gig Life Pro·22세기위성·Animenomics·DIME·문화편의점·오픈서베이 + MBW 보조 도메인 musicbusinessworldwide.com) + **`broad` 12**(Bloomberg·The Information·WIRED·New Yorker·Vox·NPR·Stratechery + 2026-07-16: 세컨드브러시·뉴닉·슬로우뉴스·Tech in Asia·HBR - 일반·테크·비즈 종합 매체). **`broad:true`** 소스는 `classify`가 is_entertainment 게이트를 넓혀 *다른 영역의 교차 신호*까지 채택(순수 하드뉴스만 제외) - "음악·엔터 밖에서 교차성·인사이트 발굴" 대표 지시(2026-06-29). vibe_search의 도메인 화이트리스트 철학과 동일 - **발신자**로 고신호 유지(받은편지함 대부분이 노이즈라 탭 통째 수집 안 함).

- 2026-07-16: **뉴스레터 allowlist 28→47 (신규 구독 스윕)**. Gmail 최근 10일 실측 대조로 신규 구독 발신자 반영 - 직결 13(Trapital·MUSIC x·WIN·Copyright Lately·InvestGame·The Pudding·ContentAsia·Gig Life Pro·22세기위성[ghost 공유 도메인이라 전체 주소]·Animenomics[substack +tag 변형 대응 substring]·DIME·문화편의점[maily 공유 도메인 전체 주소]·오픈서베이) + broad 5(세컨드브러시·뉴닉·슬로우뉴스·Tech in Asia·HBR) + **MBW 보조 도메인 발견**(musicbusinessworldwide.com - 기존 musicbizworldwide.com과 별개 문자열이라 IMAP FROM 미매칭이던 갭). 보류: NYT·Economist·Fast Company·ITmedia·Lexology·시사IN(06-29 스윕 이전부터 수신 → 당시 제외 추정, 대표 지정 시 추가)·WIPO·오픈애즈·josh@maily.so·Max Power Gaming·note.com 다이제스트·기타 beehiiv/substack 불명 소스.
- 2026-06-29: 뉴스레터 allowlist 12→27 (Gmail 전수 스윕). ① 고신호 8(MBW·CMU·NME·Consequence·Luminate·Media Innovation·Tokyo Weekender·캐릿). ② **교차성 `broad` 7**(Bloomberg·The Information·WIRED·New Yorker·Vox·NPR·Stratechery) - `classify(broad=True)`로 is_entertainment 게이트 확대(엔터·소비·문화 함의 또는 교차성 있으면 채택, 순수 하드뉴스만 제외). 대표 "음악 집중 X, 무관한 영역에서 교차성·인사이트" 지시. §1-1 참조.

## §1-1 - 캐치올 제목 게이트·주간 발신자 스캔 (2026-07-16)

원문(§1-1 항목): **캐치올 제목 게이트 (2026-07-16 신설, 대표 지시 "발신자가 아니라 제목 기준으로도")** ... `catchall_ignore`(JSON 최상위 키) = 트랜잭션·서비스 알림 제외 목록 - **편집 매체는 넣지 않는다**(NYT류 종합지의 음악 코너처럼 allowlist 등재는 과해도 개별 신호는 유효 - 제목 게이트가 개별 판정). / **주간 발신자 스캔 (2026-07-16 신설)** ... 대표가 새 뉴스레터를 구독해도 조용히 새던 문제의 자동 감지 - **등재 판단은 사람**(세션 "뉴스레터 스윕"), 무시는 catchall_ignore 추가. 캐치올=개별 신호 안전망 / 스캔=발신자 승격 제안으로 역할 분담.

- 2026-07-16: **캐치올 제목 게이트 + 주간 발신자 스캔 신설** (§1-1, 대표 지시). ① allowlist 밖 발신자도 제목이 엔터·콘텐츠·미디어 신호면 수집 - haiku 제목 배치 판정(런당 1콜) → 통과분만 본문 strict classify, 상한 8/런, `catchall_ignore`로 트랜잭션 제외(편집 매체는 안 넣음). `build_row` 헬퍼로 allowlist·캐치올 행 생성 일원화. ② 월 09:00 KST 미등재 발신자 리포트(woojin@) - 새 구독을 말 안 해도 자동 감지, 등재 판단은 사람. 게이트 실판정 테스트 PASS(NYT 음악 코너 통과·프로모/알림/법률 다이제스트 차단).

---

## §1-2 - 뉴스룸 수집기 신설 (2026-06-16) · allowed_domains 사고 (2026-06-16~17)

원문(§1-2 항목): **피드 없는 IP홀더: allowed_domains 사고 → 검색 키워드 흡수로 전환 (2026-06-17)**: Sony·WBD·NBCU·Nintendo·Bandai·Crunchyroll·Pokémon·Paramount를 `vibe_search.py` global-en `allowed_domains`에 넣어 웹검색으로 흡수하려 했으나(2026-06-16), `sony.com` 등이 Anthropic 크롤러 차단 도메인이라 **차단 도메인이 하나만 끼어도 web_search API가 요청 전체를 400 거부** → 글로벌 검색이 06-15~16 이틀 전량 실패(`continue-on-error`라 잡은 success로 가려짐). 8개 전부 제거해 원복. **차단 도메인은 `allowed_domains`에 넣을 수 없다 - 재시도하려면 `probe_domains.py`로 사전 검증 후 통과분만.** 피드 있는 IP홀더(Sony Music 등)는 newsroom 수집기가 흡수. **피드 없는 곳(Sony 그룹·Nintendo·Bandai·Crunchyroll·WBD·NBCU·Paramount)은 `vibe_search.py` `search_terms`에 회사 키워드 추가로 흡수**(2026-06-17 전환, global-en ent-deals·ip-business + japan ip-business). domains 아니라 400 안전 - 회사 자체 PR이 아니라 신뢰 매체 내 해당 기업 보도(분석·딜)를 적극 검색.

원문(§1-2 스케줄 항목): 매일 **10:00 KST**(01:00 UTC - 미국 뉴스룸 전일분 흡수) + `workflow_dispatch`(lookback_days). 뉴스룸은 저빈도 발행이라 **lookback 7일**(뉴스레터 2일보다 김).

---

## §1-3 - 인터뷰 수집기 신설 (2026-07-09)

- 2026-07-09: **인터뷰 수집기 신설**(collector='interview', §1-3). 매체 RSS 6 + 유튜브 채널 RSS 5(활성 11·비활성 1) → haiku `is_interview` 게이트 분류 → 인터뷰만 `radar_items` 적재. 화·금 11:00 KST 주 2회(`interview-ingest.yml`), 룩백 14일·나이컷 없음(에버그린), dedup 60일. 대시보드 인터뷰 탭·배지 추가, pool_maintenance 픽 20일 시효에서 interview 픽 면제. 용처=@nvl.seoul insight/quote/reels 소재 + Icon Lab 인물 레이더(루→아스토나지 dev-queue).

원문(§1-3 스케줄 항목): 인터뷰는 저빈도·에버그린이라 주 2회로 충분. **룩백 14일·나이컷 없음**(에버그린 - RSS 특성상 최신만 잡힘).

원문(§1-3 픽 시효 면제·중복 제거 항목): `collector='interview'` 픽은 **면제**(에버그린 - 소스 뱅크 이관 전까지 보존). 중복 제거 창은 최근 **60일**(에버그린이라 dedup 창을 뉴스룸 30일보다 넓게).

원문(§1-1 엔진 항목): 지역은 발신자별 고정 힌트(본문 분류 비의존 - 매체별 지역이 고정). / 원문(§4 포스팅 항목): 매주 월요일 **10:17 KST** cron(정시 :00 회피).

## §1-3 - 분류 게이트 주제 축 신설 (2026-09-02)

원문(§1-3 분류 게이트 항목): **분류 게이트 (2026-09-02 주제 축 신설)**: haiku가 **두 축을 따로** 판정하고 **둘 다 true여야 적재**한다. ... **형태만 묻던 게이트가 배우의 임신 팟캐스트와 TED 우주론 강연을 통과시켜 왔다** - 2026-09-02 실측이 계기다. 모델이 `is_music_ent` 키를 빠뜨리면 통과시킨다(주제 축 하나로 수집이 통째로 멈추지 않게).

## §1-3 - 소스 30 → 활성 8 축소 (2026-09-02)

원문(§1-3 allowlist 항목): `sources_interviews.json` - **30소스 중 활성 8**(2026-09-02 대표 지시로 26 → 8 축소). 영상 7(Music Tectonics·And The Writer Is...·Tape Notes·Broken Record·Apple Music·Zach Sang Show·MMTG 문명특급) + 텍스트 1(Pitchfork Features). **근거 = 2개월 실측** - 1,992건 수집·픽 3건이고 그 3건이 Music Tectonics(2)·And The Writer Is...(1)에서 나왔다. 나머지 26소스는 전부 0픽. **남긴 기준** = 실적 → 영상(용처가 릴스라 영상이 본체) → 음악·창작 주제 → 국내 1 → 텍스트 1. **뺀 사유는 각 항목 `_reason`에** 적혀 있다(되살릴 때 왜 뺐는지 보이게). 세 갈래 - ⓐ 엔터가 아님(TED·TechCrunch·Call Her Daddy·Masters of Scale·Neighborhood Art Supply·Hot Ones) ⓑ 인터뷰가 아니라 보도·시상(The Ankler·THR·The Town·GRAMMYS·SXSW·Genius) ⓒ 텍스트 음악 매체 중복이고 릴스가 안 됨(FADER·Stereogum·Guardian Music·NME·Rolling Stone). **축소의 비용을 안다** - 게이트 검증에서 뺀 소스도 30%는 통과했다(FADER의 칠레 펑크 씬, GRAMMYS의 장비·창작 이야기). 게이트만으로도 뺀 소스 노이즈의 60%가 걸리므로, 유입이 부족해지면 FADER·GRAMMYS부터 되살린다.

---

## §1-4 - 지역 축 5 → 12 (2026-09-10)

구 `global-en`이 살아있는 풀의 **80%**를 삼켰다. 잔여 범주라 지역 축으로 걸러내는 것이 없었다.
표본 66건을 손으로 재분류한 실측 - **북미 62% · 유럽 17% · 다국적 9% · 아시아 오분류 6% ·
라틴/아프리카/오세아니아 6%**.

「미국」이나 「영어권」으로 **개명**하는 안은 버렸다. 스웨덴·오스트리아·독일·동유럽
기사가 그대로 잘못 분류된다. **이름이 아니라 기준을 쪼갰다** - 저장 값 12종.

세 가지를 같이 정했다.

- **검색 프로파일과 저장 지역을 분리했다.** `vibe_search.py`의 5종은 cron 슬롯·webhook·`allowed_domains`에 묶여 있고, `allowed_domains`는 차단 도메인 하나만 끼어도 요청 전체가 400으로 죽는다(2026-06-16 사고). 그래서 프로파일은 안 건드리고 이름만 「영어권 검색」으로 바꿈. 그 결과의 region은 저장 시점엔 미판정이고 `backfill_region.py`가 사후 재판정한다.
- **모르겠으면 `multinational`에 넣지 않는다.** 이 칸이 다시 잔여가 되면 개편이 무의미해진다. 분류가 실패했을 때는 레거시 `global-en`을 **미판정 표식**으로 남기고 백필로 넘긴다. 즉 `global-en`은 이제 지역이 아니라 「아직 안 봤다」는 뜻이다.
- **gnews의 `REGION_BY_GL` 매핑을 폐기했다.** 구글 뉴스 에디션(gl)은 독자의 위치지 기사의 시장이 아니라, 미국판 결과에 유럽·다국적 기사가 섞여 있었다. 이미 부르던 엔터 게이트 haiku 응답에 `region` 필드를 하나 더 받는다 - **호출 수는 그대로**다. 폴백으로만 gl 표를 남겼다.

**신흥시장 5질의**(중동·나이지리아·멕시코·인도·브라질)를 같은 날 붙였다. 전부 **현지어**다 -
영어 `music industry`를 지역 에디션에 넣으면 같은 국제 기사가 복제되는 것을 실측했다.
요인 힌트는 「신흥」이 아니라 **「기존」**을 붙였다 - radar의 `GRID_FACTORS`는 7종(IP·포맷·
테크·자본·정책·교차산업·교차정체성)이고, 넓은 산업 스캔 질의는 이미 「기존」으로 묶여
있다. 새 요인 어휘를 만들면 다른 저장소의 격자와 어긋난다. 신흥시장이라는 정보는 질의
이름(`신흥·나이지리아` 등)에 남겨 둔다.

---

## §2 - 품질 게이트 도입 (2026-06-10) · 도메인 다양성 (2026-06-17) · 4지표

원문(§2 항목 주석): 출처 화이트리스트 - (AI타임스·에너지신문류 보도자료 재가공 매체 차단, 2026-06-10 대표 지시). / 교차정체성 지표는 2026-06-17 추가. / **발행일 미상은 제외**(신뢰성 - 2026-06-10 대표 지시). / **도메인당 2건 상한**(`MAX_PER_DOMAIN`, 1차 패스 - 한 매체 독식 방지·동남아 방콕포스트 편중 대응, 2026-06-17. 미달 시 2차 패스에서 상한 풀어 건수 보존).

- 2026-06-10: 품질 게이트 추가(48시간 컷·URL 생존 확인). CLAUDE.md 재작성 - 구 주간 브리핑 제작 가이드 제거, 수집 엔진 정본으로 전환.
- 2026-06-17: 도메인 다양성 - `select_candidates`에 도메인당 2건 상한(`MAX_PER_DOMAIN`) 추가. 한 매체(동남아 방콕포스트)가 점수순 5건을 독식하던 구조 차단. 2-패스(1차 상한 적용 → 미달 시 2차 상한 해제)로 도메인 얕은 지역 건수 보존. `test_quality_gate.py` 케이스 추가.

(4지표·`cross_identity` 개편 원문은 위 「§1 - 태깅: 세대 축 → 취향·가치 축」 2026-06-17 항목.)

---

## §4 - 리포트 드롭 격주 결정 (2026-06-29) · 마스터 색인 동결 해제

원문(§4 생성 항목): `/report-scan` 스킬(미네바) - **격주(2주 1회) 운영**(2026-06-29 대표 결정, 토큰 대비 수확·발행처 월간성). 4언어 검증 → `drops/YY.MM.DD-주간리포트드롭.md` 2곳 저장 + **마스터 색인 반영**(06-04 동결 해제, 색인 본래 SSOT 목적).

## §4 - YAML heredoc startup_failure → 스크립트 분리 (2026-06-15)

- 2026-06-15: 리포트 드롭 워크플로 YAML 깨짐(인라인 heredoc) 수정 - 6/4부터 startup_failure로 미발송이던 것 복구. 발송 로직을 `scripts/send_report_drop.py`로 분리, cron 10:00→10:17(정시 고부하 회피), 백업 감시 워크플로(`report-drop-watchdog.yml`, 월 10:40) 신설 - 정시 누락 시 자동 재발송 + 메일 알림.

## §4 - 403 진짜 원인 = User-Agent (2026-06-29)

원문(§4 발송 로직 항목): **① 명시 User-Agent 필수**(2026-06-29 - urllib 기본 UA는 Discord Cloudflare가 403/`error 1010` 차단).

- 2026-06-29: **리포트 드롭 403 진짜 원인 = User-Agent** (≠ 죽은 웹훅). `send_report_drop.py`가 urllib 기본 UA(`Python-urllib`)로 POST → Discord Cloudflare가 `error 1010`으로 차단(06-22 이후 규칙 강화 추정). 명시 UA(`Mozilla/…`) 헤더 추가로 해결, 게시→삭제 실전송으로 end-to-end 검증. 웹훅 자체는 유효였음(대표 신규 발급분으로 `DISCORD_REPORT_WEBHOOK_URL` secret 갱신). vibe_search `send_to_discord`는 `requests`(python-requests UA)라 현재 통과 중 - 차단 강화 대비 명시 UA는 후속 권장(현재 미적용).

## §4 - 격주 가드 경계값 8 → 7 (2026-07-06)

원문(§4 발송 로직 항목): **② 격주 중복방지: 드롭이 `DROP_MAX_AGE_DAYS`(기본 7)일↑ 지나면 발송 생략**(기본 8이던 것을 2026-07-06 7로 - 쉬는 주 월요일에 드롭이 정확히 7일 경과라 7<8로 통과, 6/29 드롭이 7/6 중복 발송된 실측 버그)(`return 0` → 정시 워크플로 success 유지 → watchdog 오경보 없음).

- 2026-07-06: **리포트 드롭 격주 가드 경계값 수정** - `DROP_MAX_AGE_DAYS` 기본 8→7. 격주 리듬에서 쉬는 주 월요일에 최신 드롭이 정확히 7일 경과인데 7<8로 가드를 통과, 6/29 드롭이 7/6 디스코드에 그대로 재발송됨(대시보드 적재는 URL dedup으로 0/6 정상 스킵). `age >= 7`이면 생략으로 변경 - 당일 발송(age 0)은 통과, 쉬는 주(age 7)는 차단.

## §4 - 대시보드 적재 (2026-06-29)

원문(§4 발송 로직 항목): **③ 대시보드 적재(2026-06-29): 발송 직후 드롭의 🥇+신규 리포트를 파싱(`parse_drop_items`)해 Supabase `radar_items`에 `collector='newsroom'`으로 적재 → 대시보드 뉴스룸 탭 노출**(다시보기=기보유는 제외, URL 중복 merge-duplicates, `SUPABASE_URL/KEY` env 필요·정시+백업 워크플로 양쪽 주입). 정시·백업 공용 모듈(stdlib). 과거 YAML heredoc startup_failure → 스크립트 분리로 차단(2026-06-15).

---

## §6 변경 이력 (CLAUDE.md에서 통째로 이관, 2026-09-04)

- 2026-07-16: **캐치올 제목 게이트 + 주간 발신자 스캔 신설** (§1-1, 대표 지시). ① allowlist 밖 발신자도 제목이 엔터·콘텐츠·미디어 신호면 수집 - haiku 제목 배치 판정(런당 1콜) → 통과분만 본문 strict classify, 상한 8/런, `catchall_ignore`로 트랜잭션 제외(편집 매체는 안 넣음). `build_row` 헬퍼로 allowlist·캐치올 행 생성 일원화. ② 월 09:00 KST 미등재 발신자 리포트(woojin@) - 새 구독을 말 안 해도 자동 감지, 등재 판단은 사람. 게이트 실판정 테스트 PASS(NYT 음악 코너 통과·프로모/알림/법률 다이제스트 차단).
- 2026-07-16: **뉴스레터 allowlist 28→47 (신규 구독 스윕)**. Gmail 최근 10일 실측 대조로 신규 구독 발신자 반영 - 직결 13(Trapital·MUSIC x·WIN·Copyright Lately·InvestGame·The Pudding·ContentAsia·Gig Life Pro·22세기위성[ghost 공유 도메인이라 전체 주소]·Animenomics[substack +tag 변형 대응 substring]·DIME·문화편의점[maily 공유 도메인 전체 주소]·오픈서베이) + broad 5(세컨드브러시·뉴닉·슬로우뉴스·Tech in Asia·HBR) + **MBW 보조 도메인 발견**(musicbusinessworldwide.com - 기존 musicbizworldwide.com과 별개 문자열이라 IMAP FROM 미매칭이던 갭). 보류: NYT·Economist·Fast Company·ITmedia·Lexology·시사IN(06-29 스윕 이전부터 수신 → 당시 제외 추정, 대표 지정 시 추가)·WIPO·오픈애즈·josh@maily.so·Max Power Gaming·note.com 다이제스트·기타 beehiiv/substack 불명 소스.
- 2026-07-15: **pool_maintenance에 묶음 2종 수명제 반영** (nvl-vibe-radar v12 `clusters.evergreen`과 세트, 대표 결정). ① 정리 ③ 신설 - 시의성 묶음(evergreen=false, open·synthesized)이 10일(updated_at) 방치되면 묶음+멤버링크 삭제. ② 픽 20일 시효의 묶음 면제를 **에버그린·to_draft/drafted 묶음 멤버로 축소** - 구 "모든 묶음 멤버 면제"는 대시보드 추천이 매 실행 같은 옛 픽으로 묶음을 재생성해 옛 픽이 시효를 영원히 피하는 루프였음(추천 신선도 하락의 근원). v12 미적용 시 ③ 생략·전 묶음 보호로 안전 폴백. interview 픽 면제는 별개로 유지.
- 2026-07-14: **pool_maintenance PostgREST 1,000행 캡 버그 수정** - `fetch_all`이 `limit=10000`을 넘겨도 서버 max-rows(1,000)에 잘려, 테이블 1,304행 시점에 pending 227건 중 74건만 보고 "정리 대상 0건"으로 통과(풀 50 상한이 침묵 무력화, 관리 대상 pending 131건까지 누적 실측). `_fetch_paged`(Range 헤더 + id 정렬 페이지 순회) 신설로 `fetch_all`·`fetch_cluster_member_ids` 전 행 조회 전환, 수정 직후 apply로 초과분 81건 archived → 관리 풀 50건 복구.
- 2026-07-09: **인터뷰 수집기 신설**(collector='interview', §1-3). 매체 RSS 6 + 유튜브 채널 RSS 5(활성 11·비활성 1) → haiku `is_interview` 게이트 분류 → 인터뷰만 `radar_items` 적재. 화·금 11:00 KST 주 2회(`interview-ingest.yml`), 룩백 14일·나이컷 없음(에버그린), dedup 60일. 대시보드 인터뷰 탭·배지 추가, pool_maintenance 픽 20일 시효에서 interview 픽 면제. 용처=@nvl.seoul insight/quote/reels 소재 + Icon Lab 인물 레이더(루→아스토나지 dev-queue).
- 2026-07-09: **`cross-industry` 병기 태그 당일 도입·회수** (대표 결정). 포지셔닝 재정의(엔터=타 산업 레퍼런스) 캐스케이드로 수집기 3종+대시보드에 태그를 실장했다가 같은 날 회수 - 레퍼런스는 일부 신호의 속성이 아니라 전 콘텐츠의 해석 렌즈라 태그 분리가 프레임과 모순(태그 없는 신호=교차 아님 역메시지). 프레임 적용은 nvl-vibe-radar 보조·추천 프롬프트(`REF_FRAME`)로 일원화. OPERATING-MODEL §0의 구 "cross-industry 플래그 병기" 문구(2026-06-08, 옛 프레임 유산)도 동시 폐기.
- 2026-07-06: **리포트 드롭 격주 가드 경계값 수정** - `DROP_MAX_AGE_DAYS` 기본 8→7. 격주 리듬에서 쉬는 주 월요일에 최신 드롭이 정확히 7일 경과인데 7<8로 가드를 통과, 6/29 드롭이 7/6 디스코드에 그대로 재발송됨(대시보드 적재는 URL dedup으로 0/6 정상 스킵). `age >= 7`이면 생략으로 변경 - 당일 발송(age 0)은 통과, 쉬는 주(age 7)는 차단.
- 2026-06-29: **리포트 드롭 403 진짜 원인 = User-Agent** (≠ 죽은 웹훅). `send_report_drop.py`가 urllib 기본 UA(`Python-urllib`)로 POST → Discord Cloudflare가 `error 1010`으로 차단(06-22 이후 규칙 강화 추정). 명시 UA(`Mozilla/…`) 헤더 추가로 해결, 게시→삭제 실전송으로 end-to-end 검증. 웹훅 자체는 유효였음(대표 신규 발급분으로 `DISCORD_REPORT_WEBHOOK_URL` secret 갱신). vibe_search `send_to_discord`는 `requests`(python-requests UA)라 현재 통과 중 - 차단 강화 대비 명시 UA는 후속 권장(현재 미적용).
- 2026-06-29: 뉴스레터 allowlist 12→27 (Gmail 전수 스윕). ① 고신호 8(MBW·CMU·NME·Consequence·Luminate·Media Innovation·Tokyo Weekender·캐릿). ② **교차성 `broad` 7**(Bloomberg·The Information·WIRED·New Yorker·Vox·NPR·Stratechery) - `classify(broad=True)`로 is_entertainment 게이트 확대(엔터·소비·문화 함의 또는 교차성 있으면 채택, 순수 하드뉴스만 제외). 대표 "음악 집중 X, 무관한 영역에서 교차성·인사이트" 지시. §1-1 참조.
- 2026-06-29: **vibe_search 격일 전환** (`ai-news-daily.yml` cron 3개 `*/2` + step if 동기화). Sonnet web_search가 토큰 비용 주범인데 수확은 풀의 20%뿐 → 격일로 ~절반 절감. newsletter·newsroom(haiku·고수확·robots.txt 우회)은 **매일 유지**. 한·글·일 나이컷 72→120h(격일 갭+주말 보강), 중·동남아는 168h 유지. ※커버리지 정공법은 차단 일간지(조선·중앙·FT·Reuters 등 robots.txt 막힘)를 newsletter 구독으로 흡수 - 발신자만 `sources_newsletters.json`에 추가.
- 2026-06-08: vibe_search v3 - 주제 기반(6토픽)에서 지역·언어 기반(5지역)으로 재설계. 구 RSS 워크플로 5개 삭제.
- 2026-06-09: Discord 5지역 웹훅 통합, Supabase 동시 적재, radar 자체 수집기 폐기, 주간 브리핑 발행 폐기(`weekly-briefing.yml`·`discord-notify.yml` 삭제).
- 2026-06-10: 품질 게이트 추가(48시간 컷·URL 생존 확인). CLAUDE.md 재작성 - 구 주간 브리핑 제작 가이드 제거, 수집 엔진 정본으로 전환.
- 2026-06-15: 리포트 드롭 워크플로 YAML 깨짐(인라인 heredoc) 수정 - 6/4부터 startup_failure로 미발송이던 것 복구. 발송 로직을 `scripts/send_report_drop.py`로 분리, cron 10:00→10:17(정시 고부하 회피), 백업 감시 워크플로(`report-drop-watchdog.yml`, 월 10:40) 신설 - 정시 누락 시 자동 재발송 + 메일 알림.
- 2026-06-17: 수집 시간대 분산 - `ai-news-daily.yml` 단일 cron(07:00 일괄)에서 cron 3개로(07:00 한·일 / 14:00 중·동남아 / 21:00 글로벌). 지역별 현지 발행 리듬에 맞춰 신선도↑. 단일 워크플로 유지(각 step `if`가 `github.event.schedule`·수동 region input 분기), skip 지역은 outcome=skipped라 실패 경보 무영향.
- 2026-06-17: 도메인 다양성 - `select_candidates`에 도메인당 2건 상한(`MAX_PER_DOMAIN`) 추가. 한 매체(동남아 방콕포스트)가 점수순 5건을 독식하던 구조 차단. 2-패스(1차 상한 적용 → 미달 시 2차 상한 해제)로 도메인 얕은 지역 건수 보존. `test_quality_gate.py` 케이스 추가.
- 2026-06-17: **세대 축 → 취향·가치 축 개편**(메타 마케팅 서밋 "세대 말고 취향·가치관" 명제 반영, 근거 `ecri-marketing/26.06.17-메타-마케팅-서밋-2026-인사이트.md` §4). ① 7번째 렌즈 `gen-z-lifestyle`(Z세대)→`taste-values`(취향·가치): TOPIC_LABELS·5지역 search_terms(각 지역 언어)·프롬프트 문단 모두 세대 라벨에서 세대 횡단 취향/가치 신호로 교체. ② 폐기된 `z_lifestyle_digest.py`의 ③교차정체성 지표를 4번째 스코어링 지표(`cross_identity`, 0~2)로 부활 - SCORE_KEYS 4개·만점 8·`MIN_TOTAL_SCORE` 3→4(env 조정)·Discord 배지 5→6·`_score_indicators` 반영. ③ 같은 풀 공유하는 `newsletter_ingest`·`newsroom_ingest`·`nvl-vibe-radar` 대시보드 키 동기화(대시보드는 구 키 alias 호환). 미해결: `radar_items`에 `cross_identity` 개별 컬럼 없음(total_score엔 합산 반영, 개별 표시 필요 시 마이그레이션 후속). 미배포(대표 검토 대기).
