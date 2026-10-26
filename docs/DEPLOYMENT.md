# Oracle와 GitHub 배포 절차

2026-10-23. 대상: Oracle Linux 9 (현재 확인된 서버는 9.8), Ubuntu 24.04, Python 3.9 이상, systemd.
저장소는 https://github.com/jhkwon2002/Gongsi 로 확정했다. 사용자 PC에서 SSH 접속 성공과 Oracle Linux Server 9.8을 확인했다. 프로그램 실제 설치·배포는 아직이다.

## 준비할 정보

- GitHub 저장소: https://github.com/jhkwon2002/Gongsi, 기본 브랜치 main.
- Oracle 인스턴스 IP 또는 DNS, 로그인 사용자, 로컬 SSH 키 경로.
- 서버에서 입력할 봇 토큰·OpenDART 인증키.
- GitHub Actions → Oracle 접속용 전용 SSH 키 쌍.
- 비공개 저장소이면 Oracle → GitHub 읽기 전용 Deploy key.

Telegram long polling을 사용하므로 봇용 공개 웹 포트나 도메인은 필요하지 않다. 서버는 Telegram·OpenDART·GitHub로 외부 통신이 가능해야 한다. SSH는 Oracle 네트워크 규칙과 OS 방화벽에서 허용해야 하며, Actions 실행기의 접속 경로도 구성해야 한다.

## 1. GitHub 업로드와 서버 설치

현재 파일을 대상 저장소에 올린다. .gitignore가 환경파일·개인키·DB·로그를 제외한다. 실제 비밀키나 운영 DB는 GitHub에 올리지 않는다.

첫 업로드에서는 검사만 실행하도록 ORACLE_DEPLOY_ENABLED는 아직 켜지 않는다.

Oracle에 SSH로 접속하고 실행한다.

~~~bash
sudo apt-get update
sudo apt-get install -y python3 git openssh-client
python3 --version
~~~

리뷰한 프로젝트 소스를 서버에 내려받아 실행한다.

~~~bash
sudo bash deploy/bootstrap.sh
sudoedit /etc/gongsi/gongsi.env
~~~

환경파일에 봇 토큰과 DART 키를 직접 입력한다. 봇은 auto_dart_gongsi_bot, 개인 수신 ID는 6766930417이다.

bootstrap은 gongsi 전용 사용자와 디렉터리를 만들고 root 소유 배포 도우미를 /usr/local/sbin/deploy-gongsi에 설치한다. 기존 환경파일은 덮어쓰지 않는다. 환경파일은 root 소유, 권한 600을 유지한다. systemd가 이를 읽어 전용 사용자 프로세스에 전달한다.

Windows의 DPAPI credentials.xml은 Linux에서 재사용하지 않는다. 키를 서버에 다시 입력한다.

## 2. Oracle에서 GitHub 읽기

공개 저장소라면 실제 URL로 바꿔 실행한다.

~~~bash
sudo git clone https://github.com/jhkwon2002/Gongsi.git /opt/gongsi/repository
~~~

비공개 저장소는 전용 키를 생성하고 공개키를 해당 GitHub 저장소의 Deploy keys에 읽기 전용으로 등록한다.

~~~bash
sudo ssh-keygen -t ed25519 -f /etc/gongsi/github_deploy_key -N ''
sudo cat /etc/gongsi/github_deploy_key.pub
~~~

GitHub 공식 SSH 지문과 비교해 검증한 호스트키를 /etc/gongsi/github_known_hosts에 저장한다. 검증되지 않은 ssh-keyscan 결과만으로 신뢰하지 않는다.

그 후 실제 URL로 바꿔 실행한다.

~~~bash
sudo env GIT_SSH_COMMAND='ssh -i /etc/gongsi/github_deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/gongsi/github_known_hosts' \
  git clone git@github.com:jhkwon2002/Gongsi.git /opt/gongsi/repository
~~~

repository는 root 소유로 관리한다. 운영 봇 사용자와 저장소 관리 사용자는 분리된다.

## 3. 첫 배포

GitHub main의 전체 40자리 커밋 SHA로 실행한다.

~~~bash
sudo /usr/local/sbin/deploy-gongsi FULL_40_CHARACTER_COMMIT_SHA
~~~

배포 도우미는 origin/main에 포함된 커밋인지 확인하고 해당 커밋을 별도 release에 추출한다. 운영 키 없이 전용 사용자로 검사를 실행하고, 기존 DB가 있으면 SQLite backup API로 백업한다. 이후 기존 서비스를 정지하고 current 링크·서비스 파일을 바꿔 시작한다. 최대 30초 안에 새 프로세스의 메뉴 준비 신호가 없으면 이전 코드와 서비스 파일로 복귀를 시도한다.

첫 배포에는 이전 버전이 없다. DB는 자동 복귀 시에도 보존하며, 향후 DB 스키마 변경에는 이전 코드와의 호환성 검증이 필요하다.

배포 성공 신호는 봇 인증·메뉴 등록·프로세스 기동을 확인한다. DART 조회 성공은 텔레그램 /status의 마지막 성공 시각으로 별도 확인한다.

~~~bash
sudo systemctl status gongsi --no-pager
sudo journalctl -u gongsi -n 50 --no-pager
sudo readlink -f /opt/gongsi/current
~~~

텔레그램에서 /start → 보고서 체크 → /status 순서로 확인한다. 최초 조회는 기준 저장만 한다. 이후 신규 공시로 알림을 확인하고 서버 재부팅 후 자동 시작도 검사한다.

동일 봇의 다른 getUpdates 프로그램은 중지한다. 기존 웹훅이 있으면 프로그램이 임의 삭제하지 않고 기동을 거부하므로 확인 후 해제한다.

## 4. GitHub 자동 배포 연결

Actions용 공개키를 Oracle 로그인 사용자의 authorized_keys에 등록하고 기존 접속을 유지한 채 테스트한다.

로그인 사용자가 ubuntu인 예시다. visudo에서 다음 권한을 설정한다.

~~~text
ubuntu ALL=(root) NOPASSWD: /usr/local/sbin/deploy-gongsi *
~~~

root 소유 도우미는 인수 1개와 SHA 형식을 검사하며 origin/main 이력만 배포한다. main의 코드를 수정할 수 있는 권한은 서버 실행 코드를 바꿀 수 있는 운영 권한이다.

GitHub 저장소에 oracle Environment를 만들고 아래 Secrets를 설정한다.

| Secret | 값 |
|---|---|
| ORACLE_HOST | 서버 IP 또는 DNS, SSH 기본 포트 22 |
| ORACLE_USER | SSH 로그인 사용자 |
| ORACLE_SSH_KEY | Actions 전용 SSH 개인키 |
| ORACLE_KNOWN_HOSTS | 별도 경로로 검증한 Oracle 호스트키의 known_hosts 행 |

저장소 Variables에 ORACLE_DEPLOY_ENABLED=true를 설정한다. DART 키·봇 토큰은 Actions에 필요하지 않다.

이후 main 변경 → GitHub 검사 → 같은 SHA를 Oracle 배포 순서로 작동한다. 서버 소스를 직접 수정하는 양방향 동기화 방식은 사용하지 않는다. 코드 변경은 먼저 저장소에 반영한다.

## 5. 운영·복구·검사

선택·일시정지·중복 방지·전송 대기열은 /var/lib/gongsi/store.db에 있어 배포 후에도 유지된다. 텔레그램 /status의 Build, GitHub 커밋, current 링크를 비교할 수 있다.

설치된 배포 도우미는 root 소유 고정본이다. deploy.sh 자체를 바꾸면 검토 후 이를 별도로 갱신한다.

~~~bash
sudo install -o root -g root -m 0755 /opt/gongsi/current/deploy/deploy.sh /usr/local/sbin/deploy-gongsi
~~~

이전 버전으로 돌아가려면 origin/main 이력에 있는 이전 SHA를 도우미에 전달한다. DB 백업은 /var/backups/gongsi에 쌓인다. 외부 백업·보관 기간 자동화는 아직 없다.

~~~bash
python3 -m unittest discover -s tests -v
bash -n deploy/bootstrap.sh
bash -n deploy/deploy.sh
~~~

이전 GitHub Linux 환경에서 Python 검사 23개가 통과했고 GitHub Linux 셸 문법 검사도 통과했다. 실제 Oracle의 서비스 기동·메뉴 표시·DART 조회·네트워크 검증은 아직이며 서버 접속 후 진행한다.

한 서버·본인 개인 채팅 1개를 위한 초기 구현이다. 모든 DART 보고서 분류, 다중 사용자, 원문 추출·요약은 포함하지 않는다. 새 선택은 새로 발견한 공시부터 적용하며, 첫 실행에 과거 공시를 일괄 전송하지 않는다.

수신 지연과 드문 중복이 발생할 수 있다. 전송 실패는 재시도하며, 전송 직후 DB 저장 전에 중단되면 반복 전송될 수 있다. 조회 범위를 겹쳐 확인하고 장기 중단 후 최대 31일씩 따라잡는다. 호출 예산 DART_DAILY_LIMIT는 본인 실제 할당량에 맞춘다. 접수 이력은 보관하므로 디스크 사용량도 확인한다.

## 공식 문서

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenDART 공시 검색](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [GitHub Actions 트리거](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Oracle 인스턴스 접속](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/accessinginstance.htm)


## Oracle Linux 9에서 간편 설치

로컬 프로젝트의 deploy/setup-oracle.ps1을 실행하면 Git에서 제외된 .env.oracle 설정으로 SSH 접속한다. 이미 확인한 호스트키만 사용하며, 키·계정·주소를 공개 스크립트에 넣지 않는다.

~~~powershell
& .\deploy\setup-oracle.ps1
~~~

1. Oracle Linux 9이면 공식 저장소에서 git과 Python 3.9 이상을 설치한다. Ubuntu이면 apt로 git과 python3을 설치하며 Python 3.9 이상인지 bootstrap에서 검사한다.
2. 서버의 전용 저장소를 가져온다. 이미 있는 경로가 다른 저장소이거나 수정된 상태이면 덮어쓰지 않고 중단한다.
3. bootstrap은 /opt/gongsi/python3을 적절한 Python 실행 파일에 연결한다. 운영체제 기본 /usr/bin/python3은 변경하지 않는다. deploy와 systemd 모두 이 서비스 전용 경로를 쓴다.
4. SSH 터미널에서 deploy/configure.py가 봇 토큰·DART 키를 가려서 입력받는다. 봇 사용자명·개인 수신자·DART API를 검증한 뒤 서버의 권한 600 환경파일을 원자적으로 저장한다. 기존 값은 Enter로 유지한다. 웹훅은 임의로 삭제하지 않는다.
5. 내려받은 정확한 커밋으로 배포하고 서비스 준비 상태를 확인한다.
6. SETUP SUCCESS 후 Telegram /start에서 보고서를 선택하고 /status에서 DART 마지막 조회 성공을 확인한다.

이번 변경의 로컬 Python 검사 29개와 PowerShell 설치 스크립트 문법 검사는 통과했다. Linux 셸 검사와 새 GitHub CI 결과는 해당 커밋에서 확인한다. 실제 패키지 설치·서버 키 입력·기동은 PC에서 위 명령을 실행한 후 검증해야 한다. 이 스크립트는 GitHub Actions용 SSH 키나 Secrets를 생성하지 않으며 자동 배포 연결은 다음 단계다.

공식 Python 설치 안내: https://docs.oracle.com/en/operating-systems/oracle-linux/9/python/python-InstallingPython.html


## 작은 인스턴스의 설치 전 메모리 준비 (2026-10-23)

패키지 설치 뒤 SSH가 배너 교환 단계에서 응답하지 않는 현상이 반복됐다. 직전 진단에서 OS가 인식한 RAM은 약 498 MiB, 스왑은 약 497 MiB였다. 메모리 압박이 의심되지만 커널 로그를 읽지 못해 OOM 종료는 아직 확정하지 않았다. 당시에는 서버 배포가 확인되지 않았으며, 이후 2026-10-26 배포 확인 기록을 참고한다.

서버가 응답하지 않으면 Oracle에서 일반 재부팅 후 SSH가 복구될 때까지 기다린다. 같은 설치를 즉시 반복하지 않는다. Windows PowerShell에서 다음 명령으로 메모리 준비만 먼저 실행한다.

~~~powershell
& .\deploy\setup-oracle.ps1 -PrepareMemoryOnly
~~~

이 단계는 패키지를 설치하지 않는다. 실행 중인 패키지 관리자가 있으면 중단한다. RAM 2 GiB 미만이고 스왑 3 GiB 미만이면 xfs/ext4에서 여유 디스크 4 GiB 이상을 확인한 뒤 별도의 3 GiB 스왑을 만든다. 기존 스왑은 유지하고, 알 수 없는 기존 파일은 덮어쓰지 않는다. 파일은 root 전용이며 활성화에 성공한 뒤 fstab을 백업하고 재부팅 후에도 유지하도록 등록한다. 생성 중 실패한 파일은 자동으로 삭제하거나 덮어쓰지 않으므로 확인 후 복구해야 한다.

MEMORY PREPARATION SUCCESS를 확인한 다음 옵션 없이 설치를 실행한다. 전체 설치도 같은 준비를 자동 실행하며, 이미 설치된 git과 Python 3.9 이상은 다시 설치하지 않는다. dnf는 선택 의존성과 동시 다운로드를 줄인다. 스왑은 RAM보다 느리므로 설치 속도나 서버 안정성을 보장하는 조치는 아니다.

공식 안내: https://docs.oracle.com/en/operating-systems/oracle-linux/9/stordev/stordev-ImplementingSwapSpaces.html


## 새 패키지 없이 배포하기 (2026-10-26)

Oracle Linux 9의 기본 python3는 3.9 계열이다. 이 프로젝트는 외부 Python 패키지를 사용하지 않는다. 기존 Python 3.9 이상과 sqlite3/ssl/fcntl이 있으면 Windows PowerShell에서 다음과 같이 실행한다.

~~~powershell
& .\deploy\setup-oracle.ps1 -NoInstall
~~~

이 옵션은 dnf/apt, Python 설치, pip, 메모리 준비 및 스왑 변경을 실행하지 않는다. 필요한 실행 환경이 없으면 NO-INSTALL STOP으로 중단한다. SSH 연결 확인 뒤 기존 Python으로 GitHub 커밋 압축파일을 내려받고 봇 전용 계정과 환경파일, systemd 서비스를 설정하므로 서버에 봇 파일은 배치된다. API 키는 SSH 터미널에서 숨김 입력한다. 서버의 Python 3.9.25 및 필요한 모듈은 확인됐고 Git은 없는 것으로 확인됐다. 봇 가동은 아래 2026-10-26 배포 확인 기록에서 확인했다.

GitHub 검사는 Python 3.9와 3.11에서 실행한다. 운영체제가 제공하는 Python을 유지하며 기본 Python 경로를 바꾸지 않는다.


### Git 없는 서버의 소스 관리

-NoInstall은 Git을 요구하지 않는다. 로컬 deploy/fetch-release.py를 SSH 표준입력으로 전송하여 서버의 기존 python3로 실행한다. GitHub API로 main의 정확한 커밋을 확인하고 해당 커밋의 압축파일만 받아 /opt/gongsi/releases에 배치한다. 전송/압축 해제 크기를 제한하고 경로 이탈, 링크, 특수 파일, 중복 경로를 거부한다. 기존 릴리스는 덮어쓰지 않는다.

bootstrap.sh --archive는 /etc/gongsi/source-mode를 archive로 설정한다. /usr/local/sbin/deploy-gongsi는 이 모드에서 Git 대신 Python 도우미를 사용하며, 배포 요청 SHA가 현재 main의 이력에 포함되는지 API로 확인한다. 서비스 전환·상태검사·실패 시 이전 코드 복구·DB 백업 절차는 공통이다. 기존 Git 방식도 유지한다. GitHub Actions SSH 연결 설정은 여전히 별도로 필요하다. 비공개 저장소 인증은 압축파일 방식에서 지원하지 않는다.


## 첫 서버 배포 확인 (2026-10-26)

사용자의 배포 결과 화면에서 커밋 e19ccf849da85000703686f4df5c8ddab35bcaa7이 서버에 배포된 것을 확인했다. 서버 검사 47개가 성공했고, 자격정보 설정 단계를 통과했으며, systemd 자동 시작과 active 상태, 메뉴 준비 신호, SETUP SUCCESS가 확인됐다. Python 3.9.25를 사용하고 Git 없는 압축파일 방식으로 진행했다.

이 확인은 실제 신규 공시 알림 수신이나 첫 DART 전체 조회 성공까지 증명하지는 않는다. Telegram에서 /start로 원하는 보고서를 선택하고 /status의 최근 성공 시각을 확인한다. GitHub Actions SSH Secrets 및 ORACLE_DEPLOY_ENABLED 설정은 여전히 후속 작업이다. 문서 갱신만으로 운영 서버가 갱신된 것으로 기록하지 않는다.


## 서버에서 GitHub 자동 반영 (2026-10-26)

Windows PowerShell에서 deploy/setup-autodeploy.ps1 -SendTest를 실행한다. 기존 API 키를 유지하고 추가 패키지는 설치하지 않는다. 서버에 gongsi-update.timer를 등록해 약 3분 간격으로 main을 확인한다. 정확한 커밋의 push 검사 워크플로 성공을 확인한 뒤 기존 배포 도우미로 반영한다. 실패·진행 중 검사, 메모리 부족은 보류한다. 서비스 준비 실패 시 기존 코드 복구 절차를 사용한다. CPU와 메모리 사용량을 제한한다. -SendTest는 서비스 상태와 DART 연결을 확인하고 소유자에게 수신 확인 메시지를 한 번 보낸다. SSH 비밀키를 GitHub에 등록할 필요는 없다. 기존 Actions SSH 배포 변수는 켜지 않는다. 현재는 코드 준비 단계이며 실제 타이머 등록과 메시지 수신은 사용자 실행 결과로 확인해야 한다.


## 자동 배포 및 실제 수신 점검 확인 (2026-10-26 11:18 KST)

사용자 실행 결과에서 gongsi-update.timer 등록과 AUTO DEPLOY ENABLED를 확인했다. GitHub 검사에 통과한 901f4f2487b39db975424e5725c5b8fb308e7651 커밋이 자동 반영됐으며 current와 target이 일치하고 result=deployed였다. 서비스 active, 조회 주기 300초, 일시정지 해제, 보고서 5개 선택, 최근 DART 조회 성공(11:18:11+09:00), 최근 오류 없음, DART API 정상, Telegram 봇 확인 및 테스트 메시지 발송 성공, health_ok=true, monitoring_ready=true, HEALTH TEST PASS를 확인했다. 실제 신규 공시 이벤트를 통한 전체 알림 흐름은 테스트 메시지와 구분한다. 이 문서 기록 커밋은 위 서버 확인 커밋과 별개이며 이후 타이머가 검사 통과 후 반영한다.
