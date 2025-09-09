# quick_fix.py
import sqlite3
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def fix_database_and_users():
    try:
        conn = sqlite3.connect('videos.db')
        cursor = conn.cursor()
        
        print("🔧 FIXING DATABASE ISSUES...")
        
        # 1. Fix missing approval_status column
        try:
            cursor.execute("ALTER TABLE videos ADD COLUMN approval_status TEXT DEFAULT 'pending'")
            print("✅ Added approval_status column to videos table")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("✅ approval_status column already exists")
            else:
                print(f"⚠️ Column issue: {e}")
        
        # 2. Delete all existing users and recreate them properly
        cursor.execute("DELETE FROM users")
        print("🗑️ Cleared existing users")
        
        # 3. Create users with correct passwords
        users = [
            ('JAYAN', 'admin_jayan123', 'admin'),
            ('Vedant', 'admin_vedant123', 'admin'),  # This is the correct password
            ('Jubin', 'jubin_teacher123', 'teacher'),
            ('Shreeram', 'shreeram_student123', 'student')
        ]
        
        for username, password, role in users:
            hashed_password = pwd_context.hash(password)
            
            cursor.execute(
                "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
                (username, hashed_password, role)
            )
            
            # Verify password works
            cursor.execute("SELECT hashed_password FROM users WHERE username = ?", (username,))
            stored_hash = cursor.fetchone()[0]
            
            if pwd_context.verify(password, stored_hash):
                print(f"✅ Created {username} ({role}) - Password verified")
            else:
                print(f"❌ Created {username} ({role}) - Password verification failed!")
        
        # 4. Update any existing videos to have pending status
        cursor.execute("UPDATE videos SET approval_status = 'pending' WHERE approval_status IS NULL")
        updated = cursor.rowcount
        if updated > 0:
            print(f"🔄 Updated {updated} videos to pending status")
        
        conn.commit()
        
        # 5. Final verification
        cursor.execute("SELECT username, role FROM users ORDER BY role")
        final_users = cursor.fetchall()
        
        print(f"\n📊 USERS CREATED:")
        for username, role in final_users:
            print(f"   {username} ({role})")
        
        conn.close()
        
        print(f"\n🔐 LOGIN CREDENTIALS:")
        print("   Vedant: admin_vedant123")
        print("   JAYAN: admin_jayan123")
        print("   Jubin: jubin_teacher123")
        print("   Shreeram: shreeram_student123")
        
        print(f"\n✅ Database fixed successfully!")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    fix_database_and_users()
