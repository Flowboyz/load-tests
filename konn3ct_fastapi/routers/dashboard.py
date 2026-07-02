import os
import jwt
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import SECRET_KEY

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "templates"))

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("token")
    if not token:
        return RedirectResponse(url="/login", status_code=307)
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user = db.query(User).filter(User.id == payload.get("user_id")).first()
        if not user:
            return RedirectResponse(url="/login", status_code=307)
    except Exception:
        return RedirectResponse(url="/login", status_code=307)
        
    return templates.TemplateResponse(request=request, name="dashboard.html")

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("token")
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user = db.query(User).filter(User.id == payload.get("user_id")).first()
            if user:
                return RedirectResponse(url="/", status_code=307)
        except Exception:
            pass
            
    return templates.TemplateResponse(request=request, name="login.html")
