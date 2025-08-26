import os
from dotenv import load_dotenv

load_dotenv() # This line loads the variables from .env file

# --- Security & Auth ---
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends, Form, status, UploadFile, File

# Load environment variables from .env file
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.logger import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

# --- Security & Auth ---
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

# --- Database Setup (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
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

# --- File Size Limit Middleware ---
class FileSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, size_limit: int = 500 * 1024 * 1024):  # 500MB default
        super().__init__(app)
        self.size_limit = size_limit

    async def dispatch(self, request: StarletteRequest, call_next):
        if request.method == "POST" and "multipart/form-data" in request.headers.get("content-type", ""):
            content_length = request.headers.get("content-length")
            if content_length:
                content_length = int(content_length)
                if content_length > self.size_limit:
                    return Response(
                        content=f"File too large. Maximum size allowed: {self.size_limit / (1024 * 1024):.0f}MB",
                        status_code=413
                    )
        
        response = await call_next(request)
        return response

# --- Security Configuration ---
SECRET_KEY = os.environ.get("SECRET_KEY", "fallback_secret_key_change_this")  # Better to use env var
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Database Models ---
DATABASE_URL = "sqlite:///./videos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, unique=True, index=True)
    category = Column(String)
    # Relationship to videos
    videos = relationship("Video", back_populates="lesson", cascade="all, delete-orphan")

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    video_url = Column(String, index=True)  # Changed from filename to video_url
    language = Column(String, default="English")    
    public_id = Column(String)
    lesson_id = Column(Integer, ForeignKey("lessons.id"))
    # Relationship to lesson
    lesson = relationship("Lesson", back_populates="videos")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="student") # 'student' or 'admin'

Base.metadata.create_all(bind=engine)

# --- App Configuration ---
app = FastAPI(title="Educational Video Platform")

# Add file size limit middleware (500MB limit)
app.add_middleware(FileSizeLimitMiddleware, size_limit=500 * 1024 * 1024)  # 500MB

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

# --- Improved File Upload Validation ---
async def validate_file_size(file: UploadFile, max_size: int = 200 * 1024 * 1024):  # 200MB
    """Validate file size by reading content"""
    content = await file.read()
    await file.seek(0)  # Reset file pointer
    
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {max_size / (1024 * 1024):.0f}MB"
        )
    return True

def validate_file_type(file: UploadFile):
    """Validate file type"""
    allowed_types = [
        "video/mp4", "video/avi", "video/mov", "video/webm", 
        "video/quicktime", "video/x-msvideo", "video/x-ms-wmv"
    ]
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
        )
    return True

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), lang: str = None):
    if not user:
        return RedirectResponse(url="/login")

    # Get all unique languages from the database for the filter links
    languages_query = db.query(Video.language).distinct().all()
    languages = [lang[0] for lang in languages_query if lang[0] is not None]

    # Get lessons with their videos
    if lang and lang != "All":
        lessons_data = db.query(Lesson).join(Video).filter(Video.language == lang).distinct().all()
    else:
        lessons_data = db.query(Lesson).all()

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "lessons": lessons_data, 
        "user": user, 
        "languages": languages, 
        "current_lang": lang or "All"
    })

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

# --- ENHANCED Upload Route with File Validation ---
@app.post("/upload")
async def handle_video_upload(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user),
    title: str = Form(...),
    category: str = Form(...),
    language: str = Form(...),
    video_file: UploadFile = File(...)
):
    try:
        # Validate file type first (before reading content)
        validate_file_type(video_file)
        
        # Validate file size
        await validate_file_size(video_file, max_size=200 * 1024 * 1024)  # 200MB limit per file
        
        # Check if lesson exists, if not create it
        lesson = db.query(Lesson).filter(Lesson.title == title).first()
        if not lesson:
            lesson = Lesson(title=title, category=category)
            db.add(lesson)
            db.commit()
            db.refresh(lesson)

        # Read the file content (file pointer already reset by validate_file_size)
        file_content = await video_file.read()
        
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        # Upload to Cloudinary with enhanced options
        upload_result = cloudinary.uploader.upload(
            file_content, 
            resource_type="video",
            folder="educational_videos",  # Organize in folders
            use_filename=True,
            unique_filename=True,
            overwrite=False,
            video_codec="h264",  # Ensure compatibility
            quality="auto:good"  # Optimize quality/size balance
        )
        
        video_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")

        if not video_url or not public_id:
            raise Exception("Failed to get URL or public_id from Cloudinary")

        # Create new video record
        new_video = Video(
            video_url=video_url,
            language=language,
            public_id=public_id,
            lesson_id=lesson.id
        )
        db.add(new_video)
        db.commit()
        
        logger.info(f"Video uploaded successfully: {video_url}")
        
    except HTTPException:
        # Re-raise HTTP exceptions (validation errors)
        raise
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        db.rollback()
        return templates.TemplateResponse("upload.html", {
            "request": request, 
            "user": user, 
            "error": f"Upload failed: {str(e)}"
        })

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

# --- DELETE Lesson Route ---
@app.post("/lesson/{lesson_id}/delete")
async def delete_lesson(
    request: Request,
    lesson_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    lesson_to_delete = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson_to_delete:
        raise HTTPException(status_code=404, detail="Lesson not found")

    try:
        # Loop through all associated videos and delete them from Cloudinary
        for video in lesson_to_delete.videos:
            if video.public_id:
                cloudinary.uploader.destroy(video.public_id, resource_type="video")
                logger.info(f"Deleted video {video.public_id} from Cloudinary.")

        # Delete the lesson from database (videos will be deleted due to cascade)
        db.delete(lesson_to_delete)
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to delete lesson: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete lesson")
    
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

# Optional: Add a route to serve videos directly (if needed)
@app.get("/video/{filename}")
async def get_video(filename: str):
    video_path = VIDEO_DIR / filename
    if video_path.exists():
        return FileResponse(video_path)
    else:
        raise HTTPException(status_code=404, detail="Video not found")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# Get server info
@app.get("/info")
async def server_info():
    return {
        "max_file_size_mb": 500,
        "supported_video_formats": ["mp4", "avi", "mov", "webm", "quicktime"],
        "cloudinary_configured": bool(os.environ.get('CLOUDINARY_CLOUD_NAME'))
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)