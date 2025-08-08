import os
import cv2
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends, Form, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.logger import logger
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

# --- Security & Authentication ---
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

# --- Database Setup (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base

# --- Security Configuration ---
SECRET_KEY = "a_very_secret_key_change_this_later" # IMPORTANT: Change this!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token") # This is for API docs, not used directly by us

# --- Database Models ---
DATABASE_URL = "sqlite:///./videos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True)
    title = Column(String)
    category = Column(String)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

Base.metadata.create_all(bind=engine)

# --- App Configuration ---
app = FastAPI()
VIDEO_DIR = Path("videos")
THUMBNAIL_DIR = Path("static/thumbnails")
VIDEO_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Password & Token Helper Functions ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Dependency to Get Current User ---
async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        return username
    except JWTError:
        return None

# --- Thumbnail Generation (No changes needed) ---
def generate_thumbnail(video_path: Path, thumb_path: Path):
    if thumb_path.exists(): return
    try:
        logger.info(f"Generating thumbnail for {video_path.name}...")
        vid = cv2.VideoCapture(str(video_path))
        success, image = vid.read()
        if success:
            cv2.imwrite(str(thumb_path), image)
        vid.release()
    except Exception as e:
        logger.error(f"Failed to create thumbnail: {e}")

# --- App Startup (No changes needed) ---
@app.on_event("startup")
def sync_videos_and_thumbnails():
    # This logic remains the same
    pass # You can re-add the sync logic if needed, or manage DB manually

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: str = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login")
    
    db = SessionLocal()
    videos_data = db.query(Video).all()
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "videos": videos_data, "user": user})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login_for_access_token(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).first()
    db.close()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Incorrect username or password"})

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie(key="access_token")
    return response

async def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    user_exists = db.query(User).filter(User.username == username).first()
    if user_exists:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})
    
    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.close()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/video/{filename}")
async def video(filename: str):
    file_path = VIDEO_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)