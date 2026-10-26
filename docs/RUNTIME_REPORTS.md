# Oracle 실행 결과 → GitHub

코드와 실행 데이터는 각각 main과 runtime-reports 브랜치로 관리한다. 결과 브랜치 갱신은 main 배포를 유발하지 않는다.

## 결과

runtime-reports 브랜치의 runtime/latest.json에 최근 200건의 발송 시도와 실행 버전을 기록한다. 최근 로컬 1,000건은 SQLite delivery_history에 보관한다. GitHub 파일의 변경 기록은 Git 커밋으로 남는다.

기업명, 공시명, 공개 접수번호, 공시일, 추출 방식, 발송 결과, 실행 버전, 기록 시각, 추출 보류 여부만 내보낸다. API 토큰, 채팅·메시지 ID, 필터 설정, 원문 내용, 서버 주소·경로, 원시 오류는 올리지 않는다.

telegram_accepted는 Telegram API의 메시지 ID 반환을 확인했다는 뜻이다. 사용자의 수신·열람 증명은 아니다. send_failed와 send_returned_without_id는 성공으로 표시하지 않는다.

이전 테스트는 DB에 남은 계획과 메시지 ID의 존재만 복구한다. historical_api_acknowledged는 과거 체크포인트, method_evidence=extraction_cache_only는 현재 남은 캐시의 출처이며 과거 메시지에 사용된 추출 방식의 확정 증거가 아니다. 과거 일반 알림은 새 기록 기능 이전 결과를 소급해 만들어 넣지 않는다.

## 최초 인증 연결 — Oracle 터미널에서 1회

현재 배포 연결은 공개 GitHub 읽기만 사용하므로 결과 쓰기에는 별도 인증이 필요하다. GitHub fine-grained personal access token은 Gongsi 저장소만 선택하고 Contents read/write 권한을 부여한다. 토큰을 채팅·커밋에 넣지 않는다.

새 코드 배포 후 Oracle SSH 터미널에서 실행한다.

```bash
sudo /opt/gongsi/python3 /opt/gongsi/current/deploy/configure-reporting.py
```

토큰은 숨김 입력으로 받아 기존 root 전용 환경 파일에 저장하고 봇 서비스를 재시작한다. 스크립트는 읽기 접근을 확인하며 실제 쓰기 권한의 성공 여부는 첫 업로드로 확인한다.

## 상태와 실패

Telegram /status의 GitHub 결과 동기화 상태:

- credential_required: 서버 쓰기 토큰이 아직 설정되지 않음
- synced: 업로드 성공
- failed: 재시도 대기. 코드 403은 권한·정책, 409는 변경 충돌 등 점검 필요

5분마다 변경 내용을 확인한다. 업로드 실패는 발송을 중단하지 않으며 로컬 기록을 유지하고 다음 주기에 재시도한다. GitHub에 최신 기록이 없으면 성공으로 추정하지 않는다.

인증 연결 전에 결과만 확인하려면 Oracle 터미널에서 실행할 수 있다.

```bash
sudo /opt/gongsi/python3 /opt/gongsi/current/deploy/export-runtime-report.py
```

## 검증 한계

합성 테스트로 기록·출처·개인정보 제외·별도 브랜치·실패 후 재시도·과거 자료 표시를 검증한다. Oracle 실제 설치와 GitHub 실업로드 완료는 별도 확인이 필요하다.