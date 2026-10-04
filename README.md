# Maple Craft Analytics

메이플스토리 전문기술 제작품의 현재 재료 가격과 완제품 판매가를 직접 입력하고, 제작비 / 수수료 / 예상 수익 / 마진을 계산하며 가격·제작·판매 이력을 축적하는 FastAPI 프로젝트입니다.

## 현재 구조

- FastAPI + 기존 HTML/JS 화면 유지
- 운영 DB 후보: MariaDB
- SQLite: 가벼운 로컬 회귀 테스트 / fallback 용도
- Maple 저장소는 **앱 코드, Dockerfile, 로컬 개발용 Compose, CI만 담당**
- 미니PC 배포와 공용 인프라는 `chl4890620123-collab/Server` 저장소가 담당할 예정
- 현재는 `Server`의 Self-hosted Runner smoke test가 먼저이며, Maple은 아직 운영 인프라에 연결하지 않음

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

운영 runtime env와 백업 정책은 앱 저장소가 아니라 `Server` 인프라에서 관리합니다.

## CI

`main` push 및 Pull Request에서 다음을 검증합니다.

1. SQLite 회귀 테스트
2. Docker 기반 MariaDB 11.4 통합 회귀 테스트
3. `linux/amd64` Docker 이미지 빌드

Maple 저장소는 미니PC에 직접 SSH 배포하지 않습니다.

## 운영 배포 상태

**현재는 연결 전입니다.** 먼저 `Server` 저장소에서 아래 smoke test가 성공해야 합니다.

```text
GitHub Actions
  -> Self-hosted Windows Runner
  -> Docker Compose
  -> 임시 Nginx 프론트
  -> / 화면 HTTP 200 확인
```

이 테스트가 성공하면 `Server`의 임시 프론트를 삭제하고 다음 단계에서 Maple 저장소를 연결합니다.

예정 구조:

```text
Maple main
   -> CI 성공
   -> Server 중앙 인프라
   -> 미니PC Docker
   -> Maple container
```

SSH Secret, Caddy, GHCR, DB 운영 설정은 smoke test 단계에서는 사용하지 않습니다.

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

운영 데이터 보존과 백업은 `Server` 인프라 연결 이후 중앙 정책으로 관리합니다. 앱 저장소에서는 운영 서버 백업 스크립트를 직접 관리하지 않습니다.


## 경험 기반 자기개선 추천

Maple의 기본 제작비/수수료/예상 수익 계산은 결정론적으로 유지하고, 실제 제작·판매 기록을 별도 학습 신호로 사용합니다.

```text
현재 시세 계산
   -> 예상 순이익
   -> 실제 제작/판매 기록
   -> 예상 대비 실현수익 + 판매율 + 시세 변동성
   -> 경험보정 예상수익
   -> 다음 추천 순위에 자동 반영
```

- 원본 `expected_profit`은 수정하지 않습니다.
- 판매 기록이 없으면 경험보정 예상수익은 원본 예상수익과 같습니다.
- 최근 90일 기록을 기본 학습 구간으로 사용합니다.
- 실제 판매 표본이 쌓일수록 예상 대비 실현수익 비율의 영향이 커집니다.
- 제작 대비 판매율이 낮으면 추천을 완만하게 낮춥니다.
- 저장된 시세 이력이 충분하면 가격 변동성을 위험 요인으로 반영합니다.
- 손실 예상 항목은 학습 결과가 좋아도 이익 추천으로 뒤집지 않습니다.
- 화면에서 경험보정 추천순, 학습 표본 수, 신뢰도, 보정 근거를 확인할 수 있습니다.

이 방식은 AI가 계산 공식을 임의로 변경하는 구조가 아니라, 사용 결과에서 얻은 경험으로 추천 계층만 점진적으로 보정하는 구조입니다.
