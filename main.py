import os
import enum
import time
from dotenv import load_dotenv

load_dotenv()

# --- Security & Auth ---
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends, Form, status, UploadFile, File
from pydantic import BaseModel

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
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Enum, text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.orm.session import Session

# --- Cloudinary Setup ---
import cloudinary
import cloudinary.uploader

cloudinary.config( 
  cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.environ.get('CLOUDINARY_API_KEY'), 
  api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

# --- File Size Limit Middleware ---
class FileSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, size_limit: int = 100 * 1024 * 1024):  # 100MB default
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
SECRET_KEY = os.environ.get("SECRET_KEY", "fallback_secret_key_change_this")
ALGORITHM = "HS256"  # FIXED: was "HS266"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Enums for Roles and Statuses ---
class UserRole(str, enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"

class VideoStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

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
    videos = relationship("Video", back_populates="lesson", cascade="all, delete-orphan")

class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True, index=True)
    video_url = Column(String, index=True)
    language = Column(String, default="English")    
    public_id = Column(String)
    lesson_id = Column(Integer, ForeignKey("lessons.id"))
    lesson = relationship("Lesson", back_populates="videos")
    approval_status = Column(Enum(VideoStatus), default=VideoStatus.pending, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(Enum(UserRole), default=UserRole.student)

# --- Database Initialization with Migration Check ---
def initialize_database():
    """Initialize database and handle migrations if needed"""
    try:
        # Create tables
        Base.metadata.create_all(bind=engine)
        
        # Check if approval_status column exists and add if missing
        with engine.connect() as conn:
            try:
                # Test if the column exists by trying to query it
                result = conn.execute(text("SELECT approval_status FROM videos LIMIT 1"))
                print("✅ Database schema is up to date")
            except Exception:
                # Column doesn't exist, add it
                print("🔄 Adding missing approval_status column...")
                try:
                    conn.execute(text("ALTER TABLE videos ADD COLUMN approval_status TEXT DEFAULT 'pending'"))
                    # Set existing videos to approved so they remain visible
                    conn.execute(text("UPDATE videos SET approval_status = 'approved' WHERE approval_status IS NULL OR approval_status = ''"))
                    conn.commit()
                    print("✅ Database migration completed successfully!")
                except Exception as e:
                    print(f"⚠️  Migration error (might be normal if column exists): {e}")
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise

# Initialize database
initialize_database()

# --- Pydantic model for status updates ---
class VideoStatusUpdate(BaseModel):
    status: VideoStatus

# --- App Configuration ---
app = FastAPI(title="Educational Video Platform")
app.add_middleware(FileSizeLimitMiddleware, size_limit=100 * 1024 * 1024)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Auth Helper Functions ---
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
    if current_user is None or current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this page. Admin access required."
        )
    return current_user

# --- FIXED: Dependency to allow teachers or admins to upload ---
async def get_current_teacher_or_admin_user(current_user: User = Depends(get_current_user)):
    if current_user is None or current_user.role not in [UserRole.admin, UserRole.teacher]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a teacher or admin to upload videos."
        )
    return current_user

# --- File Upload Validation ---
async def validate_file_size(file: UploadFile, max_size: int = 200 * 1024 * 1024):
    content = await file.read()
    await file.seek(0)
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail=f"File too large. Max size: {max_size / (1024 * 1024):.0f}MB")
    return True

def validate_file_type(file: UploadFile):
    allowed_types = ["video/mp4", "video/webm", "video/quicktime"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(allowed_types)}")
    return True

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user), lang: str = None):
    if not user:
        return RedirectResponse(url="/login")

    try:
        # Only show APPROVED videos to all users (including students)
        base_query = db.query(Lesson).join(Video).filter(Video.approval_status == VideoStatus.approved)
        
        languages_query = db.query(Video.language).filter(Video.approval_status == VideoStatus.approved).distinct().all()
        languages = [lang[0] for lang in languages_query if lang[0] is not None]

        if lang and lang != "All":
            lessons_data = base_query.filter(Video.language == lang).distinct().all()
        else:
            lessons_data = base_query.distinct().all()

        return templates.TemplateResponse("index.html", {
            "request": request, "lessons": lessons_data, "user": user, 
            "languages": languages, "current_lang": lang or "All"
        })
    except Exception as e:
        logger.error(f"Error loading index page: {e}")
        # Fallback to show all lessons if approval_status queries fail
        try:
            lessons_data = db.query(Lesson).all()
            languages = db.query(Video.language).distinct().all()
            languages = [lang[0] for lang in languages if lang[0] is not None]
            
            return templates.TemplateResponse("index.html", {
                "request": request, "lessons": lessons_data, "user": user, 
                "languages": languages, "current_lang": "All"
            })
        except Exception as fallback_error:
            logger.error(f"Fallback query also failed: {fallback_error}")
            return templates.TemplateResponse("index.html", {
                "request": request, "lessons": [], "user": user, 
                "languages": [], "current_lang": "All", "error": "Database error occurred"
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
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})
    
    hashed_password = get_password_hash(password)
    # New users default to student role
    new_user = User(username=username, hashed_password=hashed_password, role=UserRole.student)
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie(key="access_token")
    return response

# --- FIXED: Upload Routes (Now accessible to teachers too) ---
@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, user: User = Depends(get_current_teacher_or_admin_user)):
    return templates.TemplateResponse("upload.html", {"request": request, "user": user})

@app.post("/upload")
async def handle_video_upload(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_teacher_or_admin_user),
    title: str = Form(...),
    category: str = Form(...),
    language: str = Form(...),
    video_file: UploadFile = File(...)
):
    try:
        validate_file_type(video_file)
        await validate_file_size(video_file, max_size=100 * 1024 * 1024)
        
        lesson = db.query(Lesson).filter(Lesson.title == title).first()
        if not lesson:
            lesson = Lesson(title=title, category=category)
            db.add(lesson)
            db.commit()
            db.refresh(lesson)

        file_content = await video_file.read()
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        upload_result = cloudinary.uploader.upload(
            file_content, resource_type="video", folder="educational_videos",
            use_filename=True, unique_filename=True, overwrite=False
        )
        
        video_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")
        if not video_url or not public_id:
            raise Exception("Failed to get URL or public_id from Cloudinary")

        # Create new video record. The approval_status will automatically default to 'pending'
        new_video = Video(
            video_url=video_url, language=language,
            public_id=public_id, lesson_id=lesson.id
        )
        db.add(new_video)
        db.commit()
        
        if user.role == UserRole.teacher:
            logger.info(f"Teacher '{user.username}' uploaded video '{title}' - pending admin approval")
            return templates.TemplateResponse("upload.html", {
                "request": request, "user": user, 
                "success": "Video uploaded successfully! It will be visible after admin approval."
            })
        else:
            logger.info(f"Admin '{user.username}' uploaded video '{title}' - pending approval")
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        db.rollback()
        return templates.TemplateResponse("upload.html", {
            "request": request, "user": user, "error": f"Upload failed: {str(e)}"
        })

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

# --- ADMIN DASHBOARD ROUTES ---
@app.get("/admin/dashboard", response_class=HTMLResponse, tags=["Admin"])
async def admin_dashboard(request: Request, user: User = Depends(get_current_admin_user)):
    return FileResponse("admin.html")  # Serve the admin.html file directly

@app.get("/api/admin/pending-videos", tags=["Admin"])
async def get_pending_videos(db: Session = Depends(get_db), user: User = Depends(get_current_admin_user)):
    pending_videos = db.query(Video).join(Lesson).filter(Video.approval_status == VideoStatus.pending).all()
    
    # Convert to dict format for JSON response
    videos_data = []
    for video in pending_videos:
        videos_data.append({
            "id": video.id,
            "video_url": video.video_url,
            "language": video.language,
            "approval_status": video.approval_status.value,
            "lesson": {
                "id": video.lesson.id,
                "title": video.lesson.title,
                "category": video.lesson.category
            }
        })
    
    return videos_data

@app.patch("/api/admin/videos/{video_id}/status", tags=["Admin"])
async def update_video_status(
    video_id: int,
    update: VideoStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_admin_user)
):
    video_to_update = db.query(Video).filter(Video.id == video_id).first()
    if not video_to_update:
        raise HTTPException(status_code=404, detail="Video not found")
    
    old_status = video_to_update.approval_status
    video_to_update.approval_status = update.status
    db.commit()
    
    logger.info(f"Admin '{user.username}' updated video {video_id} from '{old_status}' to '{update.status}'")
    return {"message": f"Video status updated to {update.status}"}

# --- DELETE LESSON (Admin only) ---
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
        for video in lesson_to_delete.videos:
            if video.public_id:
                cloudinary.uploader.destroy(video.public_id, resource_type="video")
        db.delete(lesson_to_delete)
        db.commit()
        logger.info(f"Admin '{user.username}' deleted lesson '{lesson_to_delete.title}'")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete lesson: {e}")
    
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

# --- Health check ---
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)