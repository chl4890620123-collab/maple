# Maple Craft Analytics

메이플스토리 전문기술 제작품의 **현재 재료 가격 + 완제품 판매가**를 직접 입력하고,
제작비 / 수수료 / 예상 수익 / 마진을 한 번에 계산하는 개인용 데이터 축적 프로젝트입니다.

사용할수록 가격 이력, 제작 기록, 실제 판매 기록이 누적되어 추후 판매율·회전율·가격 추세·추천 모델의 학습 데이터로 사용할 수 있게 설계했습니다.

## V1 기능

- 재료 가격 직접 수정 + 모든 변경 이력 저장
- 완제품 판매가 직접 수정 + 모든 변경 이력 저장
- 레시피 필요 수량은 초기 DB 기본값 사용
- 전체 제작품 제작비/수수료/예상수익/마진 자동 계산
- 3% / 5% 수수료 선택
- 제작 당시 계산값 스냅샷 저장
- 실제 판매가/판매수량/실현수익 저장
- 30일 제작량/판매량/판매율/실현수익 대시보드
- SQLite 영구 볼륨
- Docker Compose 배포
- GitHub Actions CI + 미니PC SSH 배포

## 초기 데이터

초기 seed는 사용자가 제공한 `장신구 제작.xlsx` / PDF 계산식을 구조화한 값입니다.
원본에서 확인 가능한 계산식은 테스트로 회귀 검증합니다.

`익스트림 벨트`는 원본 Excel에서 다크 엔젤릭 블레스 계산식을 그대로 참조하는 오류가 보여 V1 seed에서 의도적으로 제외했습니다. 정확한 전문기술 전체 레시피는 별도 검증 후 seed를 확장합니다.

## 로컬 실행

```bash
cp .env.example .env
# ADMIN_TOKEN을 긴 임의 문자열로 변경

docker compose --env-file .env up -d --build
```

기본 주소:

```text
http://localhost:18080
```

기존 서버의 80/443 도메인 서비스와 충돌하지 않도록 외부 포트는 `APP_PORT`로 변경할 수 있습니다.

예:

```env
APP_PORT=18081
```

## 첫 미니PC 배포: 한 번만 실행

현재 서버에서 SSH 22가 외부 연결을 받지 않는 상태라면 원격 GitHub Actions보다 먼저 서버 자체를 한 번 초기화해야 합니다.

미니PC에서 **PowerShell을 관리자 권한으로 실행**한 뒤 아래를 그대로 실행합니다.

```powershell
$bootstrap = "$env:TEMP\maple-bootstrap.ps1"
Invoke-WebRequest "https://raw.githubusercontent.com/chl4890620123-collab/maple/main/deploy/scripts/bootstrap-server.ps1" -OutFile $bootstrap
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap
```

스크립트가 자동으로 처리하는 내용:

1. Windows OpenSSH Server 설치/시작, 22번 방화벽 허용
2. Docker Desktop/Engine 준비 확인
3. `8000`, `18080`, `18081`, `18082` 중 실제로 비어 있는 첫 포트 선택
4. 선택된 앱 포트 Windows 방화벽 허용
5. `C:\home\maple\app`에 이 저장소 clone/update
6. 서버 전용 `.env.runtime`과 랜덤 `ADMIN_TOKEN` 생성
7. Docker Compose build/up
8. `/api/health`가 `ok`가 될 때까지 검증
9. GitHub CLI가 없으면 설치
10. GitHub 로그인 1회 후 현재 공인 IP/Windows 계정/22번/비밀번호를 GitHub Actions Secret으로 등록
11. `DEPLOY_PATH`, `APP_PORT`, `DEFAULT_FEE_RATE`, `ENABLE_DEPLOY=true` Variables 등록

Windows 비밀번호는 저장소 파일에 기록하지 않고 GitHub Actions Secret 입력으로만 사용합니다.

마지막에 화면에 다음 형태로 실제 접속 주소가 출력됩니다.

```text
Local health: http://127.0.0.1:<선택포트>/api/health
LAN address : http://<미니PC 내부IP>:<선택포트>
```

외부 인터넷 접속은 공유기의 포트포워딩에서도 **선택된 앱 포트 → 미니PC 내부 IP 동일 포트**가 연결되어 있어야 합니다.

## 배포 방식

이 저장소는 기존 도메인을 점유하지 않습니다. 미니PC의 별도 포트에 컨테이너를 노출합니다.

GitHub Repository Variable:

- `APP_PORT`: 예 `18080`
- `DEFAULT_FEE_RATE`: `0.05`

GitHub Actions Secrets:

- `SERVER_HOST`: 미니PC 접속 주소
- `SERVER_USER`: SSH 사용자
- `SERVER_SSH_KEY`: 기존 배포용 private key가 있다면 등록
- `SERVER_PASSWORD`: 키 인증이 안 될 때만 등록하는 SSH 계정 비밀번호
- `SERVER_PORT`: `22`

GitHub Repository Variable:

- `DEPLOY_PATH`: 기본값 `C:\home\maple\app`
- `APP_PORT`: 기존 MOVE AI가 반납한 포트 또는 자동 선택 포트
- `DEFAULT_FEE_RATE`: `0.05`
- `ENABLE_DEPLOY`: 서버 설정이 끝난 뒤 `true`

`ADMIN_TOKEN`은 서버의 `C:\home\maple\app\.env.runtime`에만 보관합니다.

`main` push → CI 성공 → SSH 22번 접속 → 저장소 clone/갱신 → SQLite 백업 → Docker 재빌드/재기동 순서입니다. Windows 미니PC 배포는 `deploy/scripts/deploy.ps1`이 담당합니다.

## 포트 충돌 방지

코드에 포트를 하드코딩하지 않고 `APP_PORT` 환경변수로 외부 포트를 결정합니다.
Docker 내부 포트는 8000으로 고정하고 외부만 변경합니다.

```text
기존 서비스: 80 / 443
Maple Craft: APP_PORT -> container:8000
```

포트가 이미 사용 중이라면 GitHub `Settings > Secrets and variables > Actions > Variables > APP_PORT` 값만 바꾸면 됩니다.

## API

현재 V1에는 외부 API가 필수가 아닙니다.

NEXON Open API는 캐릭터/유니온/길드/랭킹/공지 등은 제공하지만, 2026-08 기준 웹 옥션의 현재 매물가·제작 레시피를 제공하는 공식 API는 확인되지 않았습니다. 따라서 이 프로젝트는 경매장 가격을 직접 입력하는 것을 기준 동작으로 합니다.

내부 REST API 주요 경로:

- `GET /api/health`
- `GET /api/materials`
- `PATCH /api/materials/{id}/price`
- `PATCH /api/items/{id}/sale-price`
- `GET /api/calculations?fee_rate=0.05`
- `POST /api/crafts`
- `GET /api/crafts`
- `POST /api/sales`
- `GET /api/sales`
- `GET /api/dashboard?days=30`

쓰기 API는 `X-Admin-Token` 헤더를 사용합니다.

## 데이터 보존 원칙

삭제 대상과 자산 데이터를 분리합니다.

- 가격 이력: 장기 보존
- 제작/판매 이력: 장기 보존
- 계산 스냅샷: 제작 시 장기 보존
- 백업 파일: 기본 28일 순환
- Docker 로그/임시 파일: 운영 환경에서 별도 rotation 권장

핵심 시장/거래 데이터는 2주마다 삭제하지 않습니다.
