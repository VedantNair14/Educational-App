import sqlite3

def check_database_structure():
    try:
        # Connect to your database
        conn = sqlite3.connect('videos.db')
        cursor = conn.cursor()
        
        print("=== CHECKING DATABASE STRUCTURE ===\n")
        
        # Check if tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("📋 Tables found:")
        for table in tables:
            print(f"  - {table[0]}")
        
        # Check videos table structure
        if ('videos',) in tables:
            print("\n🎥 VIDEOS table structure:")
            cursor.execute("PRAGMA table_info(videos);")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
        
        # Check lessons table structure
        if ('lessons',) in tables:
            print("\n📚 LESSONS table structure:")
            cursor.execute("PRAGMA table_info(lessons);")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
        
        # Check users table structure
        if ('users',) in tables:
            print("\n👤 USERS table structure:")
            cursor.execute("PRAGMA table_info(users);")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
        
        conn.close()
        
        print("\n" + "="*50)
        print("🔍 What to look for:")
        print("✅ videos table should have: video_url, lesson_id")
        print("❌ If you see 'filename' instead of 'video_url', database needs updating")
        print("✅ lessons table should exist")
        print("✅ users table should exist")
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        print("💡 This might mean the database doesn't exist yet (which is fine!)")

if __name__ == "__main__":
    check_database_structure()