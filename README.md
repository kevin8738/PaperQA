# PaperQA (FastAPI + Next.js)

PDF 논문을 업로드해 구조화 요약(JSON), 인덱스 생성, 논문 기반 QA를 수행하는 프로젝트입니다.

## 프로젝트 특징

- 업로드 후 요약/인덱스 생성까지 API 기반 파이프라인으로 처리
- 논문별 페이지/청크/수식/QA 이력 관리
- 인용(ref) 기반 답변 포맷으로 근거 추적 가능
- FastAPI 백엔드 + Next.js 프론트엔드로 로컬에서 바로 실행 가능

## 1. 실행 환경

- Windows 10/11
- Python 3.11+
- Node.js 20+

## 2. 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```powershell
cd frontend
npm install
cd ..
```

## 3. 환경변수 설정 (OpenAI)

```powershell
$env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
```

`.env`를 쓰고 싶다면:

```powershell
Copy-Item .env.example .env
```

프론트엔드 환경변수:

```env
# frontend/.env.local
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## 4. 실행

백엔드:

```powershell
uvicorn backend.app:app --reload
```

프론트엔드:

```powershell
cd frontend
npm run dev
```

- Backend Docs: `http://127.0.0.1:8000/docs`
- Frontend: `http://127.0.0.1:3000`

## 5. 주요 API

- `POST /papers/upload`
- `POST /papers/ingest`
- `POST /papers/{paper_id}/summarize`
- `POST /papers/{paper_id}/build_index`
- `POST /papers/{paper_id}/qa`
- `GET /papers`
- `GET /papers/{paper_id}`
- `GET /papers/{paper_id}/summary`
- `DELETE /papers/{paper_id}`

## 6. Git 업로드 기준

`.gitignore`로 아래 로컬 산출물을 제외합니다.

- `.env`, `frontend/.env.local`
- `.venv/`
- `frontend/node_modules/`, `frontend/.next/`
- `data` 내 DB/로그/논문 원본/페이지 이미지/인덱스 (각 폴더의 `.gitkeep`만 유지)

현재 데이터 폴더 기본 구조:

- `data/papers/.gitkeep`
- `data/pages/.gitkeep`
- `data/index/.gitkeep`
- `data/tmp/.gitkeep`
