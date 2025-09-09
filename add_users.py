# add_users.py
import sqlite3
from passlib.context import CryptContext

# This must be the EXACT same as in your main.py file
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- User Data to Add ---
# Format: (username, plain_text_password, role)
users_to_add = [ 
    # Admin users (supervisors)
    ('JAYAN', 'admin_jayan123', 'admin'),
    ('Vedant', 'admin_vedant123', 'admin'),
    
    # Teacher user
    ('Jubin', 'jubin_teacher123', 'teacher'),
    
    # Student user
    ('Shreeram', 'shreeram_student123', 'student')
]

# --- Database Connection ---
try:
    # Connect to your SQLite database
    conn = sqlite3.connect('videos.db')
    cursor = conn.cursor()
    print("✅ Database connected successfully.")
    
    # First, let's check if the users table exists and has the right structure
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
    if not cursor.fetchone():
        print("❌ Users table doesn't exist. Please run the main application first to create tables.")
        exit()
    
    # Check table structure
    cursor.execute("PRAGMA table_info(users);")
    columns = cursor.fetchall()
    print("\n📋 Users table structure:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    print(f"\n🔄 Processing {len(users_to_add)} users...")
    
    # Loop through the users and add them
    for username, password, role in users_to_add:
        # Securely hash the password
        hashed_password = pwd_context.hash(password)
        
        # Check if user already exists
        cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            print(f"⚠️ User '{username}' already exists. Updating role to '{role}'...")
            # Update existing user's role and password
            cursor.execute(
                "UPDATE users SET hashed_password = ?, role = ? WHERE username = ?",
                (hashed_password, role, username)
            )
            print(f"✔️ Updated user: {username} with role: {role}")
        else:
            # Insert the new user into the 'users' table
            cursor.execute(
                "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
                (username, hashed_password, role)
            )
            print(f"✔️ Added new user: {username} with role: {role}")
    
    # Commit the changes to the database
    conn.commit()
    print("\n✅ All changes have been saved to the database.")
    
    # Display final user summary
    print("\n📊 FINAL USER SUMMARY:")
    cursor.execute("SELECT username, role FROM users ORDER BY role, username")
    all_users = cursor.fetchall()
    
    role_groups = {}
    for username, role in all_users:
        if role not in role_groups:
            role_groups[role] = []
        role_groups[role].append(username)
    
    for role in ['admin', 'teacher', 'student']:
        if role in role_groups:
            print(f"  {role.upper()}S: {', '.join(role_groups[role])}")
    
    print("\n🎯 LOGIN CREDENTIALS:")
    for username, password, role in users_to_add:
        print(f"  {role.upper()} - {username}: {password}")

except sqlite3.Error as e:
    print(f"❌ Database error: {e}")

except Exception as e:
    print(f"❌ Unexpected error: {e}")

finally:
    # Close the connection
    if conn:
        conn.close()
        print("\n🔒 Database connection closed.")