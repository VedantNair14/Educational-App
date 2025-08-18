import os
import cv2
import shutil
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends, Form, status, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.logger import logger

# --- Security & Auth ---
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

# --- Database Setup (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.orm.session import Session

# --- Cloudinary Setup ---
import cloudinary
import cloudinary.uploader

# This securely reads your credentials from Render's Environment Variables
cloudinary.config( 
  cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.environ.get('CLOUDINARY_API_KEY'), 
  api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)
# --- Security Configuration ---
SECRET_KEY = "a_very_secret_key_change_this_later"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Database Models ---
DATABASE_URL = "sqlite:///./videos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, unique=True, index=True) # This will now be the Cloudinary URL
    title = Column(String)
    category = Column(String)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="student") # 'student' or 'admin'

Base.metadata.create_all(bind=engine)

# --- App Configuration ---
app = FastAPI()
VIDEO_DIR = Path("videos")
THUMBNAIL_DIR = Path("static/thumbnails")
VIDEO_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Dependency to get DB session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Auth Helper Functions (Passwords, Tokens) ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- Dependencies to Get Current User and Check Role ---
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: return None
        user = db.query(User).filter(User.username == username).first()
        return user
    except JWTError:
        return None

async def get_current_admin_user(current_user: User = Depends(get_current_user)):
    if current_user is None or current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this page."
        )
    return current_user

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: User = Depends(get_current_user)):
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
async def login_for_access_token(request: Request, db: Session = Depends(get_db), username: str = Form(...), password: str = Form(...)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Incorrect username or password"})
    
    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_user(request: Request, db: Session = Depends(get_db), username: str = Form(...), password: str = Form(...)):
    user_exists = db.query(User).filter(User.username == username).first()
    if user_exists:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})
    
    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password, role="student")
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie(key="access_token")
    return response

# --- Protected Upload Routes ---
@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, user: User = Depends(get_current_admin_user)):
    return templates.TemplateResponse("upload.html", {"request": request, "user": user})

@app.post("/upload")
async def handle_video_upload(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    video_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    try:
        upload_result = cloudinary.uploader.upload(
            video_file.file,
            resource_type="video",
            folder="educational_videos"
        )
        video_url = upload_result.get("secure_url")

        new_video = Video(
            filename=video_url,
            title=title,
            category=category
        )
        db.add(new_video)
        db.commit()
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": "Upload failed. Please try again."})

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
