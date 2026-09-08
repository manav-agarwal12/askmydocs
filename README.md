# AskMyDocs

Upload a PDF, ask questions about it in plain English, get answers with page citations.

**Stack:** FastAPI · Celery · Redis · PostgreSQL · ChromaDB · Gemini

## Setup

    docker compose up -d
    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copy `.env.example` to `.env` and fill in the values.