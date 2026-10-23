# Oracle와 GitHub 배포 절차

2026-10-23. 기본 대상: Oracle Cloud Ubuntu 24.04, Python 3.11 이상, systemd.
저장소는 https://github.com/jhkwon2002/Gongsi 로 확정했다. Oracle 서버 생성은 사용자가 확인했으며 SSH 연결과 실제 배포는 아직이다.

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

현재 로컬 Python 검사는 23개 통과했다. Windows의 Git Bash 실행 제한으로 셸 검사는 수행하지 못했다. GitHub CI와 실제 Oracle에서 셸·서비스·네트워크 검증을 마쳐야 한다.

한 서버·본인 개인 채팅 1개를 위한 초기 구현이다. 모든 DART 보고서 분류, 다중 사용자, 원문 추출·요약은 포함하지 않는다. 새 선택은 새로 발견한 공시부터 적용하며, 첫 실행에 과거 공시를 일괄 전송하지 않는다.

수신 지연과 드문 중복이 발생할 수 있다. 전송 실패는 재시도하며, 전송 직후 DB 저장 전에 중단되면 반복 전송될 수 있다. 조회 범위를 겹쳐 확인하고 장기 중단 후 최대 31일씩 따라잡는다. 호출 예산 DART_DAILY_LIMIT는 본인 실제 할당량에 맞춘다. 접수 이력은 보관하므로 디스크 사용량도 확인한다.

## 공식 문서

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [OpenDART 공시 검색](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [GitHub Actions 트리거](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Oracle 인스턴스 접속](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/accessinginstance.htm)

