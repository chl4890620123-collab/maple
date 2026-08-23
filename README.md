# Maple Craft Analytics

메이플스토리 전문기술 제작품의 현재 재료 가격과 완제품 판매가를 직접 입력하고, 제작비 / 수수료 / 예상 수익 / 마진을 계산하며 가격·제작·판매 이력을 축적하는 FastAPI 프로젝트입니다.

## 현재 구조

- FastAPI + 기존 HTML/JS 화면 유지
- 운영 DB: MariaDB
- SQLite: 가벼운 로컬 회귀 테스트/비상 fallback 용도만 유지
- 운영 배포: `chl4890620123-collab/Server` 저장소가 중앙 관리
- Maple 저장소는 앱 코드, Dockerfile, 로컬 개발용 Compose, CI만 담당
- 미니PC SSH / 운영 Compose / Caddy / 운영 runtime env는 Server 저장소와 서버가 담당

## 주요 기능

- 재료 가격 수정 및 가격 이력 저장
- 완제품 판매가 수정 및 가격 이력 저장
- 레시피 기반 제작비 계산
- 3% / 5% 판매 수수료 계산
- 제작 당시 계산값 스냅샷 저장
- 실제 판매가 / 판매수량 / 실현수익 저장
- 기간별 제작량 / 판매량 / 판매율 / 실현수익 대시보드

## 로컬 실행

```bash
cp .env.example .env
# ADMIN_TOKEN / DB_PASSWORD / DB_ROOT_PASSWORD 값을 변경

docker compose --env-file .env up -d --build
```

기본 주소:

```text
http://localhost:18080
```

로컬 Compose는 다음 두 컨테이너를 실행합니다.

```text
maple-craft  -> FastAPI
maple-db     -> MariaDB 11.4
```

DB는 Docker 내부에서 `maple-db:3306`으로만 연결됩니다. MariaDB 포트는 호스트에 공개하지 않습니다.

## 환경변수

로컬 개발 예시는 `.env.example`을 사용합니다.

```text
APP_PORT
BIND_HOST
ADMIN_TOKEN
DEFAULT_FEE_RATE
CORS_ORIGINS
DB_ENGINE
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
DB_ROOT_PASSWORD
DB_PATH
```

운영 환경에서는 이 저장소의 `.env`를 사용하지 않습니다. 운영 값은 미니PC의 Server 관리 경로에 보관합니다.

```text
D:\server-data\maple\runtime\.env
```

## CI

`main` push 및 Pull Request에서 다음을 검증합니다.

1. SQLite 회귀 테스트
2. Docker 기반 MariaDB 11.4 통합 회귀 테스트
3. `linux/amd64` Docker 이미지 빌드

Maple 저장소는 미니PC에 직접 SSH 배포하지 않습니다.

## 운영 배포

운영 배포는 `chl4890620123-collab/Server` 저장소가 담당합니다.

```text
Maple main
   -> Server 중앙 배포 workflow가 최신 Maple 소스 확인
   -> Maple Docker image build / GHCR push
   -> Server의 기존 SSH Secret으로 미니PC 접속
   -> Server의 Maple production Compose 실행
   -> maple-app + maple-db 기동
   -> /api/health 검증
```

따라서 Maple 저장소에는 `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, `SERVER_PASSWORD`, `SERVER_PORT` 같은 운영 서버 Secret을 중복 등록할 필요가 없습니다.

## API

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

쓰기 API는 `X-Admin-Token` 헤더로 보호합니다.

## 데이터 보존

운영 MariaDB 데이터는 프로젝트 컨테이너와 분리해서 미니PC D 드라이브에 보관합니다.

```text
D:\server-data\maple\mariadb
```

컨테이너를 교체해도 이 디렉터리는 삭제하지 않습니다.
