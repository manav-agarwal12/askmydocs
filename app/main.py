from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.debug import router as debug_router
from app.api.documents import router as documents_router
from app.core.database import get_db

app = FastAPI(title="AskMyDocs", version="0.1.0")

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(debug_router)


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}