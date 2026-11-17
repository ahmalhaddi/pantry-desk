from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, make_token, user_view, verify_password
from app.database import get_session
from app.models import User

app = FastAPI(title="Pantry Desk")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginIn(BaseModel):
    email: str
    password: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(body: LoginIn, session: Session = Depends(get_session)) -> dict:
    email = body.email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"access_token": make_token(user), "token_type": "bearer", "user": user_view(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_view(user)
