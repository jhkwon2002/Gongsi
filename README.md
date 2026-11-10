# 주요사항공시 — Oracle · GitHub · Telegram

최종 갱신: 2026-11-10 (한국시간)

GitHub: https://github.com/jhkwon2002/Gongsi

전체 기업의 OpenDART 공시를 5분마다 확인하고, 텔레그램 메뉴에서 선택한 보고서만 개인 대화방(@auto_dart_gongsi_bot)에 보낸다. 알림에는 공시 유형별 주요 항목을 OpenDART 구조화 API와 같은 접수번호의 원문 표에서 발췌해 함께 싣는다.

## 현재 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| Oracle 서버 실행 | 가동 확인 (Oracle Linux 9.8, Python 3.9.25, Git 없이 커밋 압축파일 배포) | docs/DEPLOYMENT.md 2026-10-26 기록 |
| 자동 배포 | 서버의 gongsi-update.timer가 약 3분마다 main을 확인하고 CI 통과 커밋만 반영 | docs/DEPLOYMENT.md 2026-10-26 11:18 기록 |
| 실제 DART 조회·텔레그램 발송 | 서버 헬스 테스트 통과, 실공시 재전송 테스트 진행 | docs/DEPLOYMENT.md, gongsi/test_requests.json |
| 보고서 선택 메뉴 | 10개 분류, 주요사항보고서 36종 세부 선택, 미분류 항목 | gongsi/catalog.py |
| 자산총액 필터 | 구현 (/assets) | gongsi/assets.py |
| 주요 항목 추출·요약 | 구현 (API 우선, 원문 표·HTML 보완, 63종 발송 양식) | docs/API_FIRST_V5.md, docs/NOTIFICATION_CONTRACTS_63.md |
| 실행 결과 GitHub 기록 | 코드 구현. 서버 쓰기 토큰 설정 전에는 업로드하지 않음 | docs/RUNTIME_REPORTS.md |

현재 서버에서 실행 중인 커밋은 텔레그램 /status의 버전으로 확인한다. 이 문서의 상태는 위 근거 문서의 기록이며, 문서 갱신만으로 서버 상태를 확인한 것으로 간주하지 않는다.

## 사용 방법

1. 봇 대화방 입력창 옆 메뉴 → ‘받을 보고서 선택’(/reports 또는 /start).
2. 분류를 고르고 ☐ 버튼을 누르면 ☑로 바뀌며 즉시 저장된다. 분류 전체 선택·해제가 가능하다.
3. 주요사항보고서는 경영·계약 → 주요사항보고서에서 전체 또는 36종을 개별 선택한다.
4. 필요하면 /assets로 자산총액 범위를 정한다. 예: `/assets 1000억 5조`, 제한 없음은 `-`.
5. /status로 선택 목록, 마지막 조회 성공 시각, 실행 버전을 확인한다.

| 명령 | 기능 |
|---|---|
| /reports, /start | 보고서 선택 메뉴 |
| /assets | 자산총액 최소·최대 설정 |
| /status | 선택 목록과 감시 상태 |
| /pause, /resume | 알림 일시정지·재개 |

전체 선택 해제는 확인 화면에서 한 번 더 눌러야 적용된다.

### 보고서 분류

경영·계약, 자금조달·증권발행, 자산·사업구조, 자기주식·주식구조, 실적·재무보고, 주주·지배구조, 보증·관계회사 거래, 소송·시장조치, IR·기업가치, 기타·미분류.

분류는 보고서명으로 판단한다. 2,307건 전수검사 스냅샷(tests/fixtures)의 제목은 모두 분류되지만, 앞으로 나올 모든 제목을 보장하지는 않는다. 새 제목은 ‘새 유형·미분류 공시’를 선택하면 받는다. 항목 추가는 gongsi/catalog.py에서 한다.

### 자산총액 필터

선택한 보고서와 자산 조건을 모두 만족해야 발송한다. 최근 조회 가능한 정기보고서의 자산총계를 사용하며 연결 기준을 우선하고 없으면 별도 기준을 쓴다. 원화 기준이며 경계값을 포함한다. 자산 자료가 없는 기업의 포함 여부를 메뉴에서 정한다. 알림의 기업명 옆에 자산총액을 표시한다.

## 알림 내용

- 기업명(굵게), 보고서명, 접수일, 유형별 주요 항목, 원문 링크. 접수번호는 링크에만 사용한다.
- 추출 순서: OpenDART 구조화 API → 핵심 항목이 부족하면 같은 접수번호의 원문 ZIP 표 → 실패하면 같은 접수번호의 DART HTML 본문 1회 재시도.
- API 값을 원문 값으로 덮어쓰지 않는다. 다른 접수번호의 데이터, 값이 충돌하거나 대응이 모호한 표는 쓰지 않는다. 없는 항목을 만들어 채우지 않는다.
- 단위가 확인된 금액만 억원 등으로 바꾸고 외화는 원화로 환산하지 않는다. 값이 없거나 0인 항목은 숨긴다.
- 추출에 실패하면 ‘추출 불가 · 원문 확인’과 원문 링크를 보낸다.

자세한 규칙: docs/API_FIRST_V5.md, docs/ORIGINAL_HTML_FALLBACK.md, docs/NOTIFICATION_CONTRACTS_63.md, docs/MAJOR_REPORT_MENU.md.

## 알림·저장 정책

- 최초 실행 시 오늘과 전일 공시를 기준으로만 저장하며 과거 공시를 일괄 전송하지 않는다.
- 새 선택은 다음 조회에서 처음 발견되는 공시부터 적용한다. 이미 저장한 공시를 재전송하지 않는다.
- ‘전체’와 세부 항목이 겹쳐도 접수번호가 같으면 한 번만 보낸다. 정정 공시는 새 접수번호이므로 별도 알림 대상이다.
- 일시정지 중에도 조회는 계속한다. 정지 중 처음 발견한 공시는 재개 후 몰아서 보내지 않는다.
- 전송 실패는 대기열에 남겨 재시도한다. 선택 해제한 보고서의 대기 알림은 보내지 않는다.
- 텔레그램은 중복 방지 키가 없어, 전송 직후 DB 기록 전에 프로세스가 종료되면 같은 알림이 반복될 수 있다.
- 장기 중단 후에는 한 번에 최대 31일씩 따라잡는다.
- 기본 조회 예산은 하루 18,000 API 호출(DART_DAILY_LIMIT)이며 추출용 추가 요청도 포함한다.
- 5분은 조회 간격이다. 처리량과 재시도에 따라 도착은 더 늦을 수 있다.
- 텔레그램 getUpdates(long polling)를 사용한다. 같은 봇을 다른 프로그램에서 동시에 실행하거나 웹훅과 병행하면 안 되며, 웹훅이 있으면 기동을 거부한다.

## 저장 위치와 비밀값

| 위치 | 내용 |
|---|---|
| /etc/gongsi/gongsi.env (서버, root 600) | 봇 토큰, DART 키, 선택적 GitHub 결과 업로드 토큰 |
| /var/lib/gongsi/store.db (서버) | 선택, 발송 대기열, 추출 캐시, 발송 이력. 배포해도 유지 |
| /var/backups/gongsi (서버) | 배포 시 DB 백업. 배포 성공 후 최근 10개만 유지 |
| .env.example (저장소) | 비밀값 없는 설정 예시 |

비밀값은 GitHub와 대화에 올리지 않는다. 로그에는 원시 예외 대신 예외 종류나 고정 사유 코드만 남긴다.

## 저장소 구조

| 경로 | 역할 |
|---|---|
| gongsi/__main__.py | 진입점. 메뉴 수신 루프와 DART 조회·발송 루프 |
| gongsi/api.py | Telegram·OpenDART 호출, 일일 호출 예산 |
| gongsi/storage.py | SQLite 상태 저장 |
| gongsi/bot.py | 텔레그램 명령·메뉴 |
| gongsi/catalog.py | 보고서 분류·선택 항목 |
| gongsi/assets.py | 자산총액 조회·필터 |
| gongsi/extraction.py, acquisition.py, original_source.py | API·원문 표·HTML 추출 |
| gongsi/presentation.py, concise.py | 유형별 발송 양식·요약 |
| gongsi/extraction_schemas.json | 구조화 API 44종 스키마 |
| gongsi/runtime_reports.py, api_diagnostics.py | 발송 이력 GitHub 기록, 읽기 전용 진단 |
| gongsi/test_replay.py, test_requests.json | 소유자가 요청한 날짜 한정 재전송 테스트 |
| deploy/ | 서버 설치·배포·자동 배포·헬스체크 스크립트, systemd 유닛 |
| .github/workflows/ci-deploy.yml | 검사(Python 3.9·3.11). 서버 타이머가 이 결과를 보고 배포 |
| tests/ | 외부 호출 없는 자동 검사 |
| docs/ | 설계·배포·검증 문서 |
| dart_alert.ps1, docs/HISTORY_2026-10-23.md | 이전 Windows 실행본과 기록. 현재 운영 경로가 아님 |

## 개발과 검사

Python 3.9 이상, 외부 패키지 없음.

~~~bash
python3 -m unittest discover -s tests
~~~

GitHub CI는 Python 3.9·3.11 검사, 커밋 압축파일 검증, PowerShell·셸 문법, systemd 유닛 검사를 실행한다. 단위 검사 통과는 실제 서버·실공시 동작 확인과 구분한다.

## 배포

main에 반영 → GitHub CI 통과 → 서버 타이머가 같은 커밋을 /opt/gongsi/releases에 받아 검사 후 전환한다. 새 프로세스가 30초 안에 준비되지 않으면 이전 코드로 복귀를 시도한다. 성공하면 오래된 릴리스와 DB 백업을 정리한다. 서버에서 소스를 직접 수정하지 않는다.

설치·복구·자동 배포 설정 절차는 docs/DEPLOYMENT.md, 실행 결과 기록은 docs/RUNTIME_REPORTS.md를 따른다.
