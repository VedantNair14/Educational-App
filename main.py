import os
import cv2
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.logger import logger

# --- Database Setup (SQLAlchemy) ---
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base

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

Base.metadata.create_all(bind=engine) # This creates the table

# --- Configuration ---
app = FastAPI()
VIDEO_DIR = Path("videos")
THUMBNAIL_DIR = Path("static/thumbnails")
VIDEO_DIR.mkdir(exist_ok=True)
THUMBNAIL_DIR.mkdir(exist_ok=True)

# --- Mount Static Files & Templates ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Thumbnail Generation ---
def generate_thumbnail(video_path: Path, thumb_path: Path):
    if thumb_path.exists(): return
    try:
        logger.info(f"Generating thumbnail for {video_path.name}...")
        vid = cv2.VideoCapture(str(video_path))
        success, image = vid.read()
        if success:
            cv2.imwrite(str(thumb_path), image)
            logger.info(f"Successfully created thumbnail: {thumb_path.name}")
        vid.release()
    except Exception as e:
        logger.error(f"Failed to create thumbnail for {video_path.name}: {e}")

# --- App Startup: Sync filesystem with database ---
@app.on_event("startup")
def sync_videos_and_thumbnails():
    logger.info("Syncing videos with database and generating thumbnails...")
    db = SessionLocal()
    video_files_in_dir = {f.name for f in VIDEO_DIR.iterdir() if f.is_file()}
    
    # Add new videos from folder to DB
    for filename in video_files_in_dir:
        db_video = db.query(Video).filter(Video.filename == filename).first()
        if not db_video:
            # Create a default entry if not in DB
            new_video = Video(
                filename=filename,
                title=filename.replace('_', ' ').replace('.mp4', '').title(),
                category="General" # Default category
            )
            db.add(new_video)
            logger.info(f"Added '{filename}' to the database.")
    db.commit()

    # Generate thumbnails for all videos in DB
    all_videos_in_db = db.query(Video).all()
    for video in all_videos_in_db:
        video_path = VIDEO_DIR / video.filename
        thumbnail_path = THUMBNAIL_DIR / f"{video_path.stem}.jpg"
        if video_path.exists():
            generate_thumbnail(video_path, thumbnail_path)
    db.close()
    logger.info("Sync complete.")

# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db = SessionLocal()
    # Fetch all video data from the database
    videos_data = db.query(Video).all()
    db.close()
    return templates.TemplateResponse("index.html", {"request": request, "videos": videos_data})

@app.get("/video/{filename}")
async def video(filename: str):
    file_path = VIDEO_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)