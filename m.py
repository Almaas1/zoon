import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import re
import base64
import os
import uuid
import json
from datetime import datetime, timedelta
import random
from geopy.geocoders import Nominatim

# -------------------------------
# Helper: convert rgba/rgb to hex
# -------------------------------
def rgba_to_hex(rgba_str):
    """Convert 'rgba(r,g,b,a)' or 'rgb(r,g,b)' to '#RRGGBB' hex."""
    import re
    match = re.match(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', str(rgba_str))
    if match:
        r, g, b = map(int, match.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return None

# -------------------------------
# 1. DATABASE SETUP (with per‑tab backgrounds)
# -------------------------------

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = sqlite3.connect('social_app.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user',
                  profile_pic TEXT,
                  is_banned INTEGER DEFAULT 0,
                  is_premium INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    existing = [col[1] for col in c.execute("PRAGMA table_info(users)")]
    if 'is_premium' not in existing:
        c.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    
    # Messages table
    c.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    existing = [col[1] for col in c.execute("PRAGMA table_info(messages)")]
    if 'sender_id' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN sender_id INTEGER")
    if 'receiver_id' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN receiver_id INTEGER")
    if 'message' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN message TEXT")
    if 'media_type' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN media_type TEXT DEFAULT 'text'")
    if 'media_path' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN media_path TEXT")
    if 'timestamp' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    if 'is_read' not in existing:
        c.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
    
    # Polls, stories, posts, likes, broadcasts tables
    c.execute('''CREATE TABLE IF NOT EXISTS polls
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id INTEGER NOT NULL,
                  question TEXT NOT NULL,
                  options TEXT NOT NULL,
                  created_by INTEGER NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS poll_votes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  poll_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  option_index INTEGER NOT NULL,
                  voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(poll_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  media_type TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  expires_at TIMESTAMP)''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_stories_expires ON stories(expires_at)")
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  media_type TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  post_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(post_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_broadcasts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER NOT NULL,
                  video_path TEXT NOT NULL,
                  caption TEXT,
                  view_count INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  expires_at TIMESTAMP NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS broadcast_views
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  broadcast_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(broadcast_id, user_id))''')
    
    # App settings table (for per‑tab backgrounds + button styles)
    c.execute('''CREATE TABLE IF NOT EXISTS app_settings
                 (key TEXT PRIMARY KEY,
                  value TEXT NOT NULL)''')

    # Group chats table
    c.execute('''CREATE TABLE IF NOT EXISTS groups
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  description TEXT,
                  created_by INTEGER NOT NULL,
                  avatar TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Group members table
    c.execute('''CREATE TABLE IF NOT EXISTS group_members
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  group_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  role TEXT DEFAULT 'member',
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(group_id, user_id))''')

    # Group messages table
    c.execute('''CREATE TABLE IF NOT EXISTS group_messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  group_id INTEGER NOT NULL,
                  sender_id INTEGER NOT NULL,
                  message TEXT,
                  media_type TEXT DEFAULT 'text',
                  media_path TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    
    # Default admin
    c.execute("SELECT * FROM users")
    if not c.fetchone():
        admin_pass = hash_password("admin123")
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ("admin", admin_pass, "admin"))
        conn.commit()
    
    # Default backgrounds (light gray for all tabs + login)
    default_bg = "#f8f9fa"
    tabs = ["messages", "home", "search", "stories", "profile", "login"]
    for tab in tabs:
        c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                  (f"bg_{tab}", default_bg))

    # Default button styles (including transparency defaults)
    default_btn_style = json.dumps({
        "bg_type": "Solid Color",
        "bg_color": "#4f46e5",
        "text_color": "#ffffff",
        "border_radius": "8",
        "font_size": "14",
        "padding_v": "8",
        "padding_h": "16",
        "border_color": "#4f46e5",
        "hover_bg": "#4338ca",
        "font_weight": "600",
        "shadow": "0 2px 6px rgba(79,70,229,0.3)",
        "transparent": False,
        "opacity": 100,
        "blur": 0
    })
    c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
              ("btn_primary_style", default_btn_style))
    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect('social_app.db')

def get_app_setting(key):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_app_setting(key, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def check_login(username, password):
    hashed = hash_password(password)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, role, is_banned, profile_pic, is_premium FROM users WHERE username=? AND password=?", (username, hashed))
    user = c.fetchone()
    conn.close()
    if user and user[3] == 1:
        return None
    return user

def register_user(username, password, role='user'):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  (username, hash_password(password), role))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_all_users():
    conn = get_db_connection()
    users = pd.read_sql_query("SELECT id, username, role, is_banned, is_premium, created_at FROM users", conn)
    conn.close()
    return users

def update_user_field(user_id, field, value):
    conn = get_db_connection()
    conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
    conn.commit()
    conn.close()

def get_user_by_id(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, role, is_banned, is_premium, profile_pic, created_at FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_conversation_between(user1_id, user2_id):
    conn = get_db_connection()
    query = '''
        SELECT m.id, m.message, m.timestamp, u1.username as sender, u2.username as receiver,
               m.media_type, m.media_path
        FROM messages m
        JOIN users u1 ON m.sender_id = u1.id
        JOIN users u2 ON m.receiver_id = u2.id
        WHERE (m.sender_id = ? AND m.receiver_id = ?)
           OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.timestamp ASC
    '''
    df = pd.read_sql_query(query, conn, params=(user1_id, user2_id, user2_id, user1_id))
    conn.close()
    return df

def get_all_messages():
    conn = get_db_connection()
    df = pd.read_sql_query('''
        SELECT m.id, u1.username as sender, u2.username as receiver, m.message, m.media_type, m.timestamp
        FROM messages m
        JOIN users u1 ON m.sender_id = u1.id
        JOIN users u2 ON m.receiver_id = u2.id
        ORDER BY m.timestamp DESC
    ''', conn)
    conn.close()
    return df

def get_user_message_count(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE sender_id = ? OR receiver_id = ?", (user_id, user_id))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_post_count(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM posts WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_story_count(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stories WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_likes_received(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT COUNT(*) FROM likes 
        WHERE post_id IN (SELECT id FROM posts WHERE user_id = ?)
    ''', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_user_recent_activity(user_id, limit=5):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT 'post' as type, media_type, content, created_at 
        FROM posts WHERE user_id = ? 
        ORDER BY created_at DESC LIMIT ?
    ''', (user_id, limit))
    posts = c.fetchall()
    c.execute('''
        SELECT 'story' as type, media_type, content, created_at 
        FROM stories WHERE user_id = ? 
        ORDER BY created_at DESC LIMIT ?
    ''', (user_id, limit))
    stories = c.fetchall()
    conn.close()
    return posts + stories

# -------------------------------
# 2. AVATAR & FILE HELPERS
# -------------------------------

def get_avatar_color(username):
    random.seed(username)
    r = random.randint(100, 200)
    g = random.randint(100, 200)
    b = random.randint(100, 200)
    random.seed()
    return f"#{r:02x}{g:02x}{b:02x}"

def get_initials(username):
    parts = username.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return username[:2].upper()

def get_profile_pic_html(user_id, username, profile_pic_b64, size=40, with_story_ring=False):
    if profile_pic_b64:
        img_src = profile_pic_b64
    else:
        color = get_avatar_color(username)
        initials = get_initials(username)
        svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="50" cy="50" r="45" fill="{color}" />
                    <text x="50" y="67" font-size="40" text-anchor="middle" fill="white" font-family="Arial">{initials}</text>
                  </svg>'''
        b64_svg = base64.b64encode(svg.encode()).decode()
        img_src = f"data:image/svg+xml;base64,{b64_svg}"
    if with_story_ring:
        ring_html = f'''
        <div style="background: linear-gradient(45deg, #f09433, #d62976, #962fbf); 
                    border-radius: 50%; 
                    padding: 3px; 
                    display: inline-block;">
            <img src="{img_src}" width="{size}" height="{size}" style="border-radius: 50%; display: block;">
        </div>
        '''
        return ring_html
    else:
        return f'<img src="{img_src}" width="{size}" height="{size}" style="border-radius: 50%;">'

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def save_uploaded_file(uploaded_file):
    ext = uploaded_file.name.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return filepath

geolocator = Nominatim(user_agent="social_app")

def get_coordinates(address):
    try:
        location = geolocator.geocode(address)
        if location:
            return location.latitude, location.longitude
    except:
        pass
    return None, None

# -------------------------------
# 3. MESSAGING (with polls)
# -------------------------------

def send_message(sender_id, receiver_id, message, media_type='text', media_path=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO messages (sender_id, receiver_id, message, media_type, media_path, is_read)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (sender_id, receiver_id, message, media_type, media_path, 0))
    msg_id = c.lastrowid
    conn.commit()
    conn.close()
    return msg_id

def get_conversations(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT u.id, u.username, u.profile_pic
        FROM users u
        WHERE u.id != ? 
        AND u.is_banned = 0
        AND (
            u.id IN (SELECT DISTINCT sender_id FROM messages WHERE receiver_id=?)
            OR u.id IN (SELECT DISTINCT receiver_id FROM messages WHERE sender_id=?)
            OR u.role = 'user'
        )
    ''', (user_id, user_id, user_id))
    conversations = c.fetchall()
    conn.close()
    return conversations

def load_messages(user_id, selected_user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT m.id, m.message, m.timestamp, u.username as sender_name,
               CASE WHEN m.sender_id = ? THEN 'sent' ELSE 'received' END as type,
               m.media_type, m.media_path
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE (m.sender_id=? AND m.receiver_id=?)
           OR (m.sender_id=? AND m.receiver_id=?)
        ORDER BY m.timestamp ASC
    ''', (user_id, user_id, selected_user_id, selected_user_id, user_id))
    messages = c.fetchall()
    c.execute('''
        UPDATE messages SET is_read=1 
        WHERE sender_id=? AND receiver_id=? AND is_read=0
    ''', (selected_user_id, user_id))
    conn.commit()
    conn.close()
    return messages

def get_last_message(user_id, other_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT message, timestamp FROM messages
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY timestamp DESC LIMIT 1
    ''', (user_id, other_id, other_id, user_id))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)

# --- Group Chat Helpers ---

def create_group(name, description, created_by, member_ids):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO groups (name, description, created_by) VALUES (?, ?, ?)",
              (name, description, created_by))
    gid = c.lastrowid
    # Add creator as admin
    c.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, role) VALUES (?, ?, ?)",
              (gid, created_by, 'admin'))
    for uid in member_ids:
        if uid != created_by:
            c.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, role) VALUES (?, ?, ?)",
                      (gid, uid, 'member'))
    conn.commit()
    conn.close()
    return gid

def get_user_groups(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT g.id, g.name, g.description, g.created_by,
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
               (SELECT message FROM group_messages WHERE group_id = g.id ORDER BY timestamp DESC LIMIT 1) as last_msg,
               (SELECT timestamp FROM group_messages WHERE group_id = g.id ORDER BY timestamp DESC LIMIT 1) as last_time
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = ?
        ORDER BY last_time DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_group_members(group_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT u.id, u.username, u.profile_pic, gm.role
        FROM users u JOIN group_members gm ON u.id = gm.user_id
        WHERE gm.group_id = ?
    ''', (group_id,))
    members = c.fetchall()
    conn.close()
    return members

def get_group_info(group_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, description, created_by, created_at FROM groups WHERE id = ?", (group_id,))
    row = c.fetchone()
    conn.close()
    return row

def send_group_message(group_id, sender_id, message, media_type='text', media_path=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO group_messages (group_id, sender_id, message, media_type, media_path)
                 VALUES (?, ?, ?, ?, ?)''', (group_id, sender_id, message, media_type, media_path))
    conn.commit()
    conn.close()

def load_group_messages(group_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT gm.id, gm.message, gm.timestamp, u.username, u.profile_pic,
               gm.sender_id, gm.media_type, gm.media_path
        FROM group_messages gm
        JOIN users u ON gm.sender_id = u.id
        WHERE gm.group_id = ?
        ORDER BY gm.timestamp ASC
    ''', (group_id,))
    msgs = c.fetchall()
    conn.close()
    return msgs

def add_member_to_group(group_id, user_id):
    conn = get_db_connection()
    conn.execute("INSERT OR IGNORE INTO group_members (group_id, user_id, role) VALUES (?, ?, ?)",
                 (group_id, user_id, 'member'))
    conn.commit()
    conn.close()

def remove_member_from_group(group_id, user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id))
    conn.commit()
    conn.close()

def is_group_member(group_id, user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id))
    result = c.fetchone()
    conn.close()
    return result is not None

def create_poll(message_id, question, options, created_by):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO polls (message_id, question, options, created_by)
                 VALUES (?, ?, ?, ?)''', (message_id, question, json.dumps(options), created_by))
    conn.commit()
    conn.close()

def get_poll_by_message(message_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, question, options, created_by FROM polls WHERE message_id = ?", (message_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "question": row[1], "options": json.loads(row[2]), "created_by": row[3]}
    return None

def vote_poll(poll_id, user_id, option_index):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
              (poll_id, user_id, option_index))
    conn.commit()
    conn.close()

def get_poll_results(poll_id):
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT option_index, COUNT(*) as votes FROM poll_votes WHERE poll_id = ? GROUP BY option_index", conn, params=(poll_id,))
    conn.close()
    return df

# -------------------------------
# 4. STORIES
# -------------------------------

def add_story(user_id, media_type, content):
    expires = datetime.now() + timedelta(hours=24)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO stories (user_id, media_type, content, expires_at)
                 VALUES (?, ?, ?, ?)''', (user_id, media_type, content, expires))
    conn.commit()
    conn.close()

def get_active_stories(current_user_id):
    now = datetime.now()
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT DISTINCT u.id, u.username, u.profile_pic
        FROM users u
        JOIN stories s ON u.id = s.user_id
        WHERE s.expires_at > ?
          AND u.id != ?
          AND u.is_banned = 0
        ORDER BY s.created_at DESC
    ''', (now, current_user_id))
    users_with_stories = c.fetchall()
    result = []
    for uid, uname, pic in users_with_stories:
        c.execute('''
            SELECT id, media_type, content, created_at
            FROM stories
            WHERE user_id = ? AND expires_at > ?
            ORDER BY created_at ASC
        ''', (uid, now))
        stories = c.fetchall()
        result.append({
            'user_id': uid,
            'username': uname,
            'profile_pic': pic,
            'stories': stories
        })
    conn.close()
    return result

def delete_old_stories():
    conn = get_db_connection()
    conn.execute("DELETE FROM stories WHERE expires_at < ?", (datetime.now(),))
    conn.commit()
    conn.close()

def delete_story_by_id(story_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM stories WHERE id = ?", (story_id,))
    conn.commit()
    conn.close()

def view_stories_modal():
    if "viewing_stories" not in st.session_state or st.session_state.viewing_stories is None:
        return
    user_id = st.session_state.viewing_stories
    active_list = get_active_stories(st.session_state.user_id)
    user_stories_data = None
    for item in active_list:
        if item['user_id'] == user_id:
            user_stories_data = item
            break
    if not user_stories_data:
        st.session_state.viewing_stories = None
        return
    stories = user_stories_data['stories']
    idx = st.session_state.get('story_index', 0)
    if idx >= len(stories):
        st.session_state.viewing_stories = None
        st.rerun()
    story = stories[idx]
    story_id, media_type, content, created_at = story
    created_str = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').strftime('%b %d, %H:%M')
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 8, 1])
    with col2:
        pic_html = get_profile_pic_html(user_stories_data['user_id'], user_stories_data['username'], user_stories_data['profile_pic'], size=60)
        st.markdown(f"<div style='display: flex; align-items: center; gap: 10px;'>{pic_html}<h3 style='color: black;'>{user_stories_data['username']}</h3></div>", unsafe_allow_html=True)
        if media_type == 'text':
            st.markdown(f"""
                <div style='background:#f0f2f6; padding:2rem; border-radius:1rem; text-align:center;'>
                    <h3 style='color: black; margin: 0;'>{content}</h3>
                    <p style='color: #555; margin-top: 10px;'>{created_str}</p>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.image(content, use_column_width=True)
            st.caption(f"Posted: {created_str}")
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            if st.button("◀ Previous") and idx > 0:
                st.session_state.story_index = idx - 1
                st.rerun()
        with c2:
            st.write(f"{idx+1} / {len(stories)}")
        with c3:
            if st.button("Next ▶") and idx < len(stories)-1:
                st.session_state.story_index = idx + 1
                st.rerun()
        if st.button("❌ Close Stories"):
            st.session_state.viewing_stories = None
            st.rerun()
    st.markdown("---")

# -------------------------------
# 5. POSTS, FEED, BROADCASTS
# -------------------------------

def create_post(user_id, media_type, content):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO posts (user_id, media_type, content) VALUES (?, ?, ?)",
              (user_id, media_type, content))
    conn.commit()
    conn.close()

def get_feed_posts(current_user_id):
    conn = get_db_connection()
    query = '''
        SELECT p.id, p.user_id, u.username, u.profile_pic, p.media_type, p.content, p.created_at,
               (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as like_count,
               (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = ?) as user_liked
        FROM posts p
        JOIN users u ON p.user_id = u.id
        WHERE u.is_banned = 0
        ORDER BY p.created_at DESC
    '''
    df = pd.read_sql_query(query, conn, params=(current_user_id,))
    conn.close()
    return df

def toggle_like(post_id, user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    exists = c.fetchone()
    if exists:
        c.execute("DELETE FROM likes WHERE post_id = ? AND user_id = ?", (post_id, user_id))
    else:
        c.execute("INSERT INTO likes (post_id, user_id) VALUES (?, ?)", (post_id, user_id))
    conn.commit()
    conn.close()

def delete_post(post_id, user_id, is_admin=False):
    conn = get_db_connection()
    c = conn.cursor()
    if is_admin:
        c.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    else:
        c.execute("DELETE FROM posts WHERE id = ? AND user_id = ?", (post_id, user_id))
    conn.commit()
    conn.close()

def create_admin_broadcast(admin_id, video_path, caption, hours=24):
    expires = datetime.now() + timedelta(hours=hours)
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO admin_broadcasts 
                 (admin_id, video_path, caption, expires_at)
                 VALUES (?, ?, ?, ?)''',
              (admin_id, video_path, caption, expires))
    conn.commit()
    conn.close()

def get_active_broadcasts():
    now = datetime.now()
    conn = get_db_connection()
    df = pd.read_sql_query('''
        SELECT b.id, u.username as admin_name, b.video_path, b.caption, 
               b.view_count, b.created_at, b.expires_at
        FROM admin_broadcasts b
        JOIN users u ON b.admin_id = u.id
        WHERE b.expires_at > ?
        ORDER BY b.created_at DESC
    ''', conn, params=(now,))
    conn.close()
    return df

def mark_broadcast_viewed(broadcast_id, user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT id FROM broadcast_views 
                 WHERE broadcast_id=? AND user_id=?''', 
              (broadcast_id, user_id))
    if not c.fetchone():
        c.execute('''INSERT INTO broadcast_views (broadcast_id, user_id)
                     VALUES (?, ?)''', (broadcast_id, user_id))
        c.execute('''UPDATE admin_broadcasts 
                     SET view_count = view_count + 1 
                     WHERE id=?''', (broadcast_id,))
        conn.commit()
    conn.close()

# -------------------------------
# 6. ADMIN PANEL (with per‑tab background settings)
# -------------------------------

def show_user_detail_popup():
    if "selected_user_detail" not in st.session_state or st.session_state.selected_user_detail is None:
        return
    user = get_user_by_id(st.session_state.selected_user_detail)
    if not user:
        st.session_state.selected_user_detail = None
        return
    user_id, username, role, is_banned, is_premium, profile_pic, created_at = user
    msg_count = get_user_message_count(user_id)
    post_count = get_user_post_count(user_id)
    story_count = get_user_story_count(user_id)
    likes_received = get_user_likes_received(user_id)
    with st.container():
        st.markdown("---")
        st.markdown(f"### 👤 {username}")
        col1, col2 = st.columns([1, 4])
        with col1:
            pic_html = get_profile_pic_html(user_id, username, profile_pic, size=100)
            st.markdown(pic_html, unsafe_allow_html=True)
        with col2:
            st.markdown(f"**Role:** {role}")
            st.markdown(f"**Premium:** {'✅ Yes' if is_premium else '❌ No'}")
            st.markdown(f"**Status:** {'🚫 Banned' if is_banned else '✅ Active'}")
            st.markdown(f"**Joined:** {created_at[:10]}")
        st.divider()
        st.subheader("📊 Stats")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Messages", msg_count)
        c2.metric("Posts", post_count)
        c3.metric("Stories", story_count)
        c4.metric("Likes Received", likes_received)
        if st.button("Close", key="close_user_detail"):
            st.session_state.selected_user_detail = None
            st.rerun()

def admin_panel():
    st.markdown("## 👑 Admin & Editor Control Panel")
    user_role = st.session_state.user_role
    is_admin = (user_role == 'admin')
    is_editor = (user_role == 'editor')
    
    tabs_list = ["User Management", "Conversation Viewer", "All Messages"]
    if is_admin:
        tabs_list.extend(["Stories", "Posts", "Broadcasts", "Analytics", "Appearance", "Button Styles"])
    tabs = st.tabs(tabs_list)
    
    # Tab 0: User Management
    with tabs[0]:
        st.subheader("Manage Users")
        users_df = get_all_users()
        for idx, row in users_df.iterrows():
            with st.container():
                col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 2, 1, 1, 1.5, 1, 1.5])
                col1.write(row['username'])
                col2.write(row['role'])
                col3.write("🚫" if row['is_banned'] else "✅")
                col4.write("⭐" if row['is_premium'] else "❌")
                col5.write(row['created_at'][:10])
                with col6:
                    if st.button("Edit", key=f"edit_{row['id']}"):
                        st.session_state.edit_user_id = row['id']
                with col7:
                    if st.button("Details", key=f"details_{row['id']}"):
                        st.session_state.selected_user_detail = row['id']
                st.divider()
        
        if "edit_user_id" in st.session_state and st.session_state.edit_user_id:
            user_id = st.session_state.edit_user_id
            user = get_user_by_id(user_id)
            if user:
                st.subheader(f"Editing {user[1]}")
                with st.form(key="edit_user_form"):
                    new_username = st.text_input("Username", value=user[1])
                    new_role = st.selectbox("Role", ["user", "editor", "admin"], 
                                            index=["user", "editor", "admin"].index(user[2]) if user[2] in ["user","editor","admin"] else 0,
                                            disabled=not is_admin)
                    new_ban = st.checkbox("Banned", value=bool(user[3]))
                    new_premium = st.checkbox("Premium", value=bool(user[4]))
                    col1, col2 = st.columns(2)
                    with col1:
                        submitted = st.form_submit_button("Save")
                    with col2:
                        cancel = st.form_submit_button("Cancel")
                    if submitted:
                        if (is_admin or is_editor) and new_username != user[1]:
                            update_user_field(user_id, 'username', new_username)
                        if is_admin and new_role != user[2]:
                            update_user_field(user_id, 'role', new_role)
                        if (is_admin or is_editor) and new_ban != user[3]:
                            update_user_field(user_id, 'is_banned', int(new_ban))
                        if (is_admin or is_editor) and new_premium != user[4]:
                            update_user_field(user_id, 'is_premium', int(new_premium))
                        st.success("User updated!")
                        del st.session_state.edit_user_id
                        st.rerun()
                    if cancel:
                        del st.session_state.edit_user_id
                        st.rerun()
        
        st.subheader("Quick Actions")
        col1, col2 = st.columns(2)
        with col1:
            user_to_ban = st.selectbox("Ban/Unban user", users_df['username'], key="ban_select")
            if st.button("Toggle Ban", key="toggle_ban"):
                user_id = users_df[users_df['username'] == user_to_ban]['id'].values[0]
                current = users_df[users_df['id'] == user_id]['is_banned'].values[0]
                update_user_field(user_id, 'is_banned', 1 if not current else 0)
                st.rerun()
        with col2:
            user_to_premium = st.selectbox("Toggle Premium", users_df['username'], key="premium_select")
            if st.button("Toggle Premium", key="toggle_premium"):
                user_id = users_df[users_df['username'] == user_to_premium]['id'].values[0]
                current = users_df[users_df['id'] == user_id]['is_premium'].values[0]
                update_user_field(user_id, 'is_premium', 1 if not current else 0)
                st.rerun()
    
    # Tab 1: Conversation Viewer
    with tabs[1]:
        st.subheader("View Conversation Between Two Users")
        users = get_all_users()
        user_options = {row['username']: row['id'] for _, row in users.iterrows()}
        user1 = st.selectbox("Select first user", list(user_options.keys()), key="conv_user1")
        user2 = st.selectbox("Select second user", list(user_options.keys()), key="conv_user2")
        if user1 and user2 and user1 != user2:
            if st.button("Show Conversation"):
                conv_df = get_conversation_between(user_options[user1], user_options[user2])
                if conv_df.empty:
                    st.info("No messages between these users.")
                else:
                    st.dataframe(conv_df[['timestamp', 'sender', 'receiver', 'message', 'media_type']])
                    csv = conv_df.to_csv(index=False)
                    b64 = base64.b64encode(csv.encode()).decode()
                    href = f'<a href="data:file/csv;base64,{b64}" download="conversation.csv">Download CSV</a>'
                    st.markdown(href, unsafe_allow_html=True)
        else:
            st.info("Select two different users.")
    
    # Tab 2: All Messages
    with tabs[2]:
        st.subheader("All Messages (Global Log)")
        all_msgs = get_all_messages()
        st.dataframe(all_msgs)
        if st.button("Delete All Messages (Admin Only)") and is_admin:
            conn = get_db_connection()
            conn.execute("DELETE FROM messages")
            conn.commit()
            conn.close()
            st.warning("All messages deleted!")
            st.rerun()
    
    # Admin-only tabs
    if is_admin:
        with tabs[3]:
            st.subheader("Story Moderation")
            conn = get_db_connection()
            stories_df = pd.read_sql_query('''
                SELECT s.id, u.username, s.media_type, 
                       CASE WHEN s.media_type='text' THEN s.content ELSE 'Image' END as preview,
                       s.created_at, s.expires_at
                FROM stories s JOIN users u ON s.user_id = u.id
                ORDER BY s.created_at DESC
            ''', conn)
            conn.close()
            st.dataframe(stories_df)
            story_id = st.number_input("Story ID to delete", min_value=0, step=1)
            if st.button("Delete Story"):
                delete_story_by_id(story_id)
                st.rerun()
            if st.button("Delete All Expired"):
                delete_old_stories()
                st.rerun()
        with tabs[4]:
            st.subheader("Post Moderation")
            conn = get_db_connection()
            posts_df = pd.read_sql_query('''
                SELECT p.id, u.username, p.media_type, 
                       CASE WHEN p.media_type='text' THEN p.content ELSE 'Image' END as content_preview,
                       p.created_at,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id) as likes
                FROM posts p JOIN users u ON p.user_id = u.id
                ORDER BY p.created_at DESC
            ''', conn)
            conn.close()
            st.dataframe(posts_df)
            post_id_del = st.number_input("Post ID to delete", min_value=0, step=1)
            if st.button("Delete Post"):
                delete_post(post_id_del, None, is_admin=True)
                st.rerun()
        with tabs[5]:
            st.subheader("Admin Video Broadcasts")
            with st.form("new_broadcast"):
                caption = st.text_input("Caption")
                video_file = st.file_uploader("Upload video (MP4)", type=["mp4"])
                hours = st.slider("Expiry (hours)", 1, 72, 24)
                submitted = st.form_submit_button("Send to all users")
                if submitted and video_file:
                    file_path = save_uploaded_file(video_file)
                    create_admin_broadcast(st.session_state.user_id, file_path, caption, hours)
                    st.success("Broadcast sent!")
                    st.rerun()
            broadcasts = get_active_broadcasts()
            if not broadcasts.empty:
                for _, row in broadcasts.iterrows():
                    with st.container():
                        st.video(row['video_path'])
                        st.write(f"**Caption:** {row['caption']}")
                        st.write(f"**Views:** {row['view_count']} | **Expires:** {row['expires_at'][:16]}")
                        if st.button(f"Delete broadcast #{row['id']}", key=f"del_bcast_{row['id']}"):
                            conn = get_db_connection()
                            conn.execute("DELETE FROM admin_broadcasts WHERE id=?", (row['id'],))
                            conn.commit()
                            conn.close()
                            st.rerun()
                        st.divider()
            else:
                st.info("No active broadcasts.")
        with tabs[6]:
            st.subheader("System Analytics")
            users = get_all_users()
            conn = get_db_connection()
            total_msgs = pd.read_sql_query("SELECT COUNT(*) as c FROM messages", conn).iloc[0,0]
            total_posts = pd.read_sql_query("SELECT COUNT(*) as c FROM posts", conn).iloc[0,0]
            total_likes = pd.read_sql_query("SELECT COUNT(*) as c FROM likes", conn).iloc[0,0]
            total_broadcasts = pd.read_sql_query("SELECT COUNT(*) as c FROM admin_broadcasts", conn).iloc[0,0]
            conn.close()
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Users", len(users))
            col2.metric("Messages", total_msgs)
            col3.metric("Posts", total_posts)
            col4.metric("Likes", total_likes)
            col5.metric("Broadcasts", total_broadcasts)
        
        # Tab 7: Appearance (per‑tab backgrounds, including login)
        with tabs[7]:
            st.subheader("🎨 Per‑Tab Background Settings")
            tab_names = {
                "messages": "Messages (Chat list)",
                "home": "Home (Feed)",
                "search": "Search Users",
                "stories": "Stories",
                "profile": "Profile",
                "login": "Login Page"
            }
            selected_tab_key = st.selectbox("Select tab to customize", list(tab_names.keys()), format_func=lambda x: tab_names[x])
            current_bg = get_app_setting(f"bg_{selected_tab_key}")
            st.write("Current background:", "Custom image" if current_bg and current_bg.startswith("data:image") else (current_bg if current_bg else "default"))
            bg_type = st.radio("Background type", ["Solid color", "Gradient", "Upload Image", "Image URL"], key=f"bgtype_{selected_tab_key}")
            
            if bg_type == "Solid color":
                new_color = st.color_picker("Choose a color", current_bg if current_bg and not current_bg.startswith(('linear', 'url', 'data:image')) else "#f8f9fa")
                if st.button(f"Apply to {tab_names[selected_tab_key]}"):
                    set_app_setting(f"bg_{selected_tab_key}", new_color)
                    st.success("Background updated!")
                    st.rerun()
            elif bg_type == "Gradient":
                col1, col2 = st.columns(2)
                with col1:
                    grad1 = st.color_picker("Gradient start", "#667eea")
                with col2:
                    grad2 = st.color_picker("Gradient end", "#764ba2")
                direction = st.selectbox("Direction", ["to right", "to bottom", "135deg", "45deg"])
                gradient_css = f"linear-gradient({direction}, {grad1}, {grad2})"
                st.markdown(f"<div style='height:100px; background:{gradient_css}; border-radius:10px;'></div>", unsafe_allow_html=True)
                if st.button(f"Apply Gradient to {tab_names[selected_tab_key]}"):
                    set_app_setting(f"bg_{selected_tab_key}", gradient_css)
                    st.success("Background updated!")
                    st.rerun()
            elif bg_type == "Upload Image":
                uploaded_bg = st.file_uploader("Choose an image (JPG, PNG)", type=["jpg", "jpeg", "png"])
                if uploaded_bg:
                    b64 = base64.b64encode(uploaded_bg.getvalue()).decode()
                    mime = uploaded_bg.type
                    bg_css = f"url('data:{mime};base64,{b64}')"
                    st.markdown(f"<div style='height:200px; background:{bg_css}; background-size:cover; border-radius:10px;'></div>", unsafe_allow_html=True)
                    if st.button(f"Apply Uploaded Image to {tab_names[selected_tab_key]}"):
                        set_app_setting(f"bg_{selected_tab_key}", bg_css)
                        st.success("Background image applied!")
                        st.rerun()
            else:  # Image URL
                img_url = st.text_input("Image URL", placeholder="https://example.com/background.jpg")
                if img_url:
                    st.image(img_url, caption="Preview", width=300)
                if st.button(f"Apply URL to {tab_names[selected_tab_key]}"):
                    set_app_setting(f"bg_{selected_tab_key}", f"url({img_url})")
                    st.success("Background updated!")
                    st.rerun()
            
            if st.button(f"Reset {tab_names[selected_tab_key]} to default (light gray)"):
                set_app_setting(f"bg_{selected_tab_key}", "#f8f9fa")
                st.success("Reset done!")
                st.rerun()

        # Tab 8: Button Styles (with transparency/glassmorphism)
        with tabs[8]:
            st.subheader("🎨 Custom Button Styles")
            st.markdown("Customize how all primary buttons look across the entire app.")
            raw = get_app_setting("btn_primary_style")
            try:
                current_style = json.loads(raw) if raw else {}
            except:
                current_style = {}

            # ── Background type selector ──────────────────────────────────
            st.markdown("#### 🖼 Button Background")
            bg_type_options = ["Solid Color", "Gradient", "Upload Image", "Image URL"]
            saved_bg_type = current_style.get("bg_type", "Solid Color")
            if saved_bg_type not in bg_type_options:
                saved_bg_type = "Solid Color"
            btn_bg_type = st.selectbox(
                "Background type",
                bg_type_options,
                index=bg_type_options.index(saved_bg_type),
                key="btn_bg_type"
            )

            btn_bg_css   = current_style.get("bg_color", "#4f46e5")   # final CSS value stored
            btn_bg_color = "#4f46e5"   # fallback solid

            if btn_bg_type == "Solid Color":
                # Fix: convert stored rgba to hex if needed
                stored_bg = current_style.get("bg_color", "#4f46e5")
                if stored_bg.startswith(("linear","url","data:")):
                    stored_bg = "#4f46e5"
                else:
                    hex_bg = rgba_to_hex(stored_bg)
                    if hex_bg:
                        stored_bg = hex_bg
                    elif not stored_bg.startswith('#'):
                        stored_bg = "#4f46e5"
                btn_bg_color = st.color_picker("Button color", stored_bg, key="btn_solid_color")
                btn_bg_css = btn_bg_color

            elif btn_bg_type == "Gradient":
                col1, col2 = st.columns(2)
                with col1:
                    g1 = st.color_picker("Gradient start", "#667eea", key="btn_grad1")
                with col2:
                    g2 = st.color_picker("Gradient end",   "#764ba2", key="btn_grad2")
                gdir = st.selectbox("Direction", ["to right", "to bottom", "135deg", "45deg"], key="btn_gdir")
                btn_bg_css = f"linear-gradient({gdir}, {g1}, {g2})"
                btn_bg_color = g1
                st.markdown(
                    f"<div style='height:50px;background:{btn_bg_css};border-radius:8px;margin:6px 0;'></div>",
                    unsafe_allow_html=True
                )

            elif btn_bg_type == "Upload Image":
                uploaded_btn_img = st.file_uploader(
                    "Upload button background image (JPG / PNG)",
                    type=["jpg","jpeg","png"],
                    key="btn_bg_upload"
                )
                if uploaded_btn_img:
                    b64 = base64.b64encode(uploaded_btn_img.getvalue()).decode()
                    mime = uploaded_btn_img.type
                    btn_bg_css = f"url('data:{mime};base64,{b64}')"
                    btn_bg_color = "#4f46e5"
                    st.markdown(
                        f"<div style='height:70px;background:{btn_bg_css};background-size:cover;"
                        f"border-radius:8px;margin:6px 0;'></div>",
                        unsafe_allow_html=True
                    )
                else:
                    # keep whatever was saved before
                    prev = current_style.get("bg_color", "#4f46e5")
                    btn_bg_css = prev if prev.startswith("url(") else "#4f46e5"
                    st.info("No image uploaded — existing background will be kept.")

            else:  # Image URL
                img_url = st.text_input(
                    "Image URL",
                    placeholder="https://example.com/texture.png",
                    key="btn_img_url"
                )
                if img_url:
                    btn_bg_css = f"url('{img_url}')"
                    btn_bg_color = "#4f46e5"
                    st.markdown(
                        f"<div style='height:70px;background:{btn_bg_css};background-size:cover;"
                        f"border-radius:8px;margin:6px 0;'></div>",
                        unsafe_allow_html=True
                    )
                else:
                    prev = current_style.get("bg_color", "#4f46e5")
                    btn_bg_css = prev if prev.startswith("url(") else "#4f46e5"
                    st.info("Enter a URL to preview.")

            st.markdown("---")

            # ── Transparency / Glassmorphism settings ────────────────────
            st.markdown("#### 🧊 Transparency & Glass Effect")
            transparent_enabled = st.checkbox(
                "Enable glassmorphism (transparent background)",
                value=current_style.get("transparent", False),
                key="btn_transparent"
            )
            opacity_pct = 100
            blur_px = 0
            if transparent_enabled:
                op_val = current_style.get("opacity", 80)
                if isinstance(op_val, int) or isinstance(op_val, float):
                    opacity_pct = int(op_val)
                else:
                    opacity_pct = 80
                opacity_pct = st.slider("Opacity (%)", 0, 100, opacity_pct, key="btn_opacity")
                blur_val = current_style.get("blur", 8)
                if isinstance(blur_val, int) or isinstance(blur_val, float):
                    blur_px = int(blur_val)
                else:
                    blur_px = 8
                blur_px = st.slider("Blur intensity (px)", 0, 20, blur_px, key="btn_blur")
                st.info("📌 Glass effect works best with Solid Color or Gradient backgrounds. For images, transparency may not apply.")
            else:
                opacity_pct = 100
                blur_px = 0

            st.markdown("---")

            # ── Other style controls ──────────────────────────────────────
            st.markdown("#### 🖌 Text & Border")
            col1, col2, col3 = st.columns(3)
            with col1:
                # Fix hover background color picker: convert rgba to hex if needed
                stored_hover = current_style.get("hover_bg", "#4338ca")
                hex_hover = rgba_to_hex(stored_hover)
                if hex_hover:
                    stored_hover = hex_hover
                elif not stored_hover.startswith('#'):
                    stored_hover = "#4338ca"
                btn_tc = st.color_picker("Text color", current_style.get("text_color", "#ffffff"), key="btn_tc")
            with col2:
                btn_hover = st.color_picker("Hover background", stored_hover, key="btn_hover")
            with col3:
                btn_border = st.color_picker("Border color", current_style.get("border_color", "#4f46e5"), key="btn_border")

            st.markdown("#### 📐 Shape & Spacing")
            col1, col2, col3 = st.columns(3)
            with col1:
                btn_br = st.slider("Border radius (px)", 0, 50, int(current_style.get("border_radius", 8)),  key="btn_br")
            with col2:
                btn_pv = st.slider("Padding vertical (px)", 2, 30, int(current_style.get("padding_v",  8)),  key="btn_pv")
            with col3:
                btn_ph = st.slider("Padding horizontal (px)", 4, 60, int(current_style.get("padding_h", 16)), key="btn_ph")

            st.markdown("#### 🔤 Typography")
            col1, col2 = st.columns(2)
            with col1:
                btn_fs = st.slider("Font size (px)", 10, 24, int(current_style.get("font_size", 14)), key="btn_fs")
            with col2:
                fw_options = ["400","500","600","700","800"]
                fw_default = current_style.get("font_weight","600")
                fw_idx = fw_options.index(fw_default) if fw_default in fw_options else 2
                btn_fw = st.selectbox("Font weight", fw_options, index=fw_idx, key="btn_fw")

            st.markdown("#### ✨ Shadow")
            shadow_preset = st.selectbox("Shadow preset",
                ["None","Subtle (default)","Medium","Strong","Custom"],
                key="btn_shadow_preset"
            )
            shadow_map = {
                "None": "none",
                "Subtle (default)": "0 2px 6px rgba(79,70,229,0.3)",
                "Medium":           "0 4px 12px rgba(0,0,0,0.2)",
                "Strong":           "0 6px 20px rgba(0,0,0,0.35)",
            }
            if shadow_preset == "Custom":
                btn_shadow = st.text_input("Custom CSS shadow", current_style.get("shadow","none"), key="btn_shadow_custom")
            else:
                btn_shadow = shadow_map.get(shadow_preset, "none")

            # ── Prepare background with opacity (if glass enabled) ──────
            final_bg_css = btn_bg_css
            # For solid color we can convert to rgba
            if transparent_enabled and opacity_pct < 100:
                if btn_bg_type == "Solid Color":
                    # Convert hex to rgba
                    def hex_to_rgba(hex_color, opacity):
                        hex_color = hex_color.lstrip('#')
                        if len(hex_color) == 6:
                            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
                        elif len(hex_color) == 3:
                            r, g, b = int(hex_color[0]*2, 16), int(hex_color[1]*2, 16), int(hex_color[2]*2, 16)
                        else:
                            r, g, b = 79, 70, 229
                        return f"rgba({r}, {g}, {b}, {opacity/100.0})"
                    final_bg_css = hex_to_rgba(btn_bg_color, opacity_pct)
                elif btn_bg_type == "Gradient":
                    # Recompute gradient with rgba stops using the current g1,g2 values
                    if 'g1' in locals() and 'g2' in locals():
                        def hex_to_rgba_g(hex_color, opacity):
                            hex_color = hex_color.lstrip('#')
                            if len(hex_color) == 6:
                                r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
                            elif len(hex_color) == 3:
                                r, g, b = int(hex_color[0]*2, 16), int(hex_color[1]*2, 16), int(hex_color[2]*2, 16)
                            else:
                                r, g, b = 102, 126, 234
                            return f"rgba({r}, {g}, {b}, {opacity/100.0})"
                        rgba1 = hex_to_rgba_g(g1, opacity_pct)
                        rgba2 = hex_to_rgba_g(g2, opacity_pct)
                        final_bg_css = f"linear-gradient({gdir}, {rgba1}, {rgba2})"
                    else:
                        # fallback: keep original gradient
                        final_bg_css = btn_bg_css
                else:
                    # For images, we don't apply transparency to background (would be complex)
                    st.warning("Transparency is not applied to image backgrounds. Use solid or gradient for glass effect.")
            else:
                final_bg_css = btn_bg_css

            # For hover background: if transparent, also apply opacity to hover color
            hover_bg_final = btn_hover
            if transparent_enabled and opacity_pct < 100 and btn_bg_type == "Solid Color":
                def hex_to_rgba_hover(hex_color, opacity):
                    hex_color = hex_color.lstrip('#')
                    if len(hex_color) == 6:
                        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
                    elif len(hex_color) == 3:
                        r, g, b = int(hex_color[0]*2, 16), int(hex_color[1]*2, 16), int(hex_color[2]*2, 16)
                    else:
                        r, g, b = 67, 56, 202
                    return f"rgba({r}, {g}, {b}, {opacity/100.0})"
                hover_bg_final = hex_to_rgba_hover(btn_hover, opacity_pct)

            # ── Live preview ──────────────────────────────────────────────
            if btn_bg_type in ("Upload Image", "Image URL"):
                preview_bg_rule = f"background: {final_bg_css} center/cover no-repeat;"
            else:
                preview_bg_rule = f"background: {final_bg_css};"

            # Add backdrop-filter for glass effect
            blur_style = f"backdrop-filter: blur({blur_px}px);" if transparent_enabled and blur_px > 0 else ""

            preview_html = f"""
            <style>
            .btn-preview {{
                display: inline-block;
                {preview_bg_rule}
                {blur_style}
                color: {btn_tc};
                border: 2px solid {btn_border};
                border-radius: {btn_br}px;
                font-size: {btn_fs}px;
                font-weight: {btn_fw};
                padding: {btn_pv}px {btn_ph}px;
                box-shadow: {btn_shadow};
                cursor: pointer;
                margin: 8px 6px;
                font-family: 'Segoe UI', sans-serif;
                transition: all 0.2s;
                text-shadow: 0 1px 2px rgba(0,0,0,0.2);
            }}
            </style>
            <div style="background:#f0f2f6;padding:24px;border-radius:12px;margin:14px 0;text-align:center;">
                <p style="color:#6b7280;margin-bottom:14px;font-size:13px;font-weight:600;">
                    🔍 Live Preview
                </p>
                <button class="btn-preview">💬 Send Message</button>
                <button class="btn-preview">👍 Like</button>
                <button class="btn-preview">📸 Upload</button>
            </div>
            """
            st.markdown(preview_html, unsafe_allow_html=True)

            # ── Apply / Reset ─────────────────────────────────────────────
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Apply Button Style", use_container_width=True, key="apply_btn_style"):
                    new_style = {
                        "bg_type":     btn_bg_type,
                        "bg_color":    final_bg_css if transparent_enabled and btn_bg_type=="Solid Color" else btn_bg_css,
                        "text_color":  btn_tc,
                        "border_radius": str(btn_br),
                        "font_size":   str(btn_fs),
                        "padding_v":   str(btn_pv),
                        "padding_h":   str(btn_ph),
                        "border_color": btn_border,
                        "hover_bg":    hover_bg_final,
                        "font_weight": btn_fw,
                        "shadow":      btn_shadow,
                        "transparent": transparent_enabled,
                        "opacity":     opacity_pct,
                        "blur":        blur_px,
                    }
                    set_app_setting("btn_primary_style", json.dumps(new_style))
                    st.success("✅ Button style applied globally!")
                    st.rerun()
            with col2:
                if st.button("🔄 Reset to Default", use_container_width=True, key="reset_btn_style"):
                    default_style = {
                        "bg_type": "Solid Color",
                        "bg_color": "#4f46e5", "text_color": "#ffffff",
                        "border_radius": "8",  "font_size": "14",
                        "padding_v": "8",      "padding_h": "16",
                        "border_color": "#4f46e5", "hover_bg": "#4338ca",
                        "font_weight": "600",
                        "shadow": "0 2px 6px rgba(79,70,229,0.3)",
                        "transparent": False,
                        "opacity": 100,
                        "blur": 0
                    }
                    set_app_setting("btn_primary_style", json.dumps(default_style))
                    st.success("Reset to default!")
                    st.rerun()

            # ── Quick Themes ──────────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 🎨 Quick Themes")
            theme_cols = st.columns(4)
            themes = {
                "🌊 Ocean Blue":  {"bg_type":"Solid Color","bg_color":"#0ea5e9","text_color":"#ffffff","border_radius":"8","font_size":"14","padding_v":"8","padding_h":"16","border_color":"#0284c7","hover_bg":"#0284c7","font_weight":"600","shadow":"0 2px 8px rgba(14,165,233,0.4)","transparent":False,"opacity":100,"blur":0},
                "🌿 Forest Green":{"bg_type":"Solid Color","bg_color":"#10b981","text_color":"#ffffff","border_radius":"8","font_size":"14","padding_v":"8","padding_h":"16","border_color":"#059669","hover_bg":"#059669","font_weight":"600","shadow":"0 2px 8px rgba(16,185,129,0.4)","transparent":False,"opacity":100,"blur":0},
                "🔥 Sunset Red":  {"bg_type":"Solid Color","bg_color":"#ef4444","text_color":"#ffffff","border_radius":"8","font_size":"14","padding_v":"8","padding_h":"16","border_color":"#dc2626","hover_bg":"#dc2626","font_weight":"700","shadow":"0 2px 8px rgba(239,68,68,0.4)","transparent":False,"opacity":100,"blur":0},
                "🌸 Rose Pink":   {"bg_type":"Solid Color","bg_color":"#ec4899","text_color":"#ffffff","border_radius":"24","font_size":"14","padding_v":"8","padding_h":"20","border_color":"#db2777","hover_bg":"#db2777","font_weight":"600","shadow":"0 2px 8px rgba(236,72,153,0.4)","transparent":False,"opacity":100,"blur":0},
            }
            for col, (tname, tstyle) in zip(theme_cols, themes.items()):
                with col:
                    st.markdown(f"""
                    <div style="background:{tstyle['bg_color']};color:{tstyle['text_color']};
                                padding:10px;border-radius:{tstyle['border_radius']}px;
                                text-align:center;font-weight:{tstyle['font_weight']};
                                font-size:13px;margin-bottom:6px;">
                        {tname}
                    </div>""", unsafe_allow_html=True)
                    if st.button("Apply", key=f"theme_{tname}", use_container_width=True):
                        set_app_setting("btn_primary_style", json.dumps(tstyle))
                        st.success(f"{tname} applied!")
                        st.rerun()

# -------------------------------
# BEAUTIFUL GLOBAL UI CSS (UPGRADED)
# -------------------------------
def get_global_ui_css():
    """Generate modern, glassmorphism UI CSS with custom button styles."""
    raw = get_app_setting("btn_primary_style")
    if raw:
        try:
            s = json.loads(raw)
        except:
            s = {}
    else:
        s = {}
    
    bg     = s.get("bg_color", "#4f46e5")
    tc     = s.get("text_color", "#ffffff")
    br     = s.get("border_radius", "8")
    fs     = s.get("font_size", "14")
    pv     = s.get("padding_v", "8")
    ph     = s.get("padding_h", "16")
    bc     = s.get("border_color", "#4f46e5")
    hbg    = s.get("hover_bg", "#4338ca")
    fw     = s.get("font_weight", "600")
    sh     = s.get("shadow", "0 2px 6px rgba(79,70,229,0.3)")
    bg_type = s.get("bg_type", "Solid Color")
    transparent = s.get("transparent", False)
    opacity = s.get("opacity", 100)
    blur = s.get("blur", 0)

    # Resolve background shorthand
    if bg_type in ("Upload Image", "Image URL") or bg.startswith("url("):
        bg_rule = f"background: {bg} center/cover no-repeat !important;"
        hover_bg_rule = f"background: {bg} center/cover no-repeat !important; filter: brightness(0.88) !important;"
    elif bg_type == "Gradient" or bg.startswith("linear-gradient"):
        bg_rule = f"background: {bg} !important;"
        hover_bg_rule = f"background: {hbg} !important;"
    else:
        bg_rule = f"background: {bg} !important;"
        hover_bg_rule = f"background: {hbg} !important;"

    extra_blur = f"backdrop-filter: blur({blur}px);" if transparent and blur > 0 else ""

    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    :root {{
        --font-family: 'Inter', sans-serif;
        --primary-color: {bg};
        --primary-hover: {hbg};
        --glass-bg: rgba(255, 255, 255, 0.5);
        --glass-border: rgba(255, 255, 255, 0.4);
        --shadow-default: {sh};
    }}
    
    .stApp {{
        font-family: var(--font-family);
        transition: background 0.3s ease;
    }}
    
    /* Sidebar Glass Styling */
    [data-testid="stSidebar"] {{
        background: rgba(255, 255, 255, 0.4) !important;
        backdrop-filter: blur(16px) !important;
        border-right: 1px solid var(--glass-border) !important;
        box-shadow: 4px 0 20px rgba(0,0,0,0.05) !important;
    }}
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stTextInput,
    [data-testid="stSidebar"] .stButton,
    [data-testid="stSidebar"] h1, h2, h3, h4, h5, h6, p, div, span {{
        color: #1f2937 !important;
    }}

    /* Modern Input Fields */
    .stTextInput > div > input,
    .stTextArea > div > textarea,
    .stSelectbox > div > div {{
        background: rgba(255, 255, 255, 0.8) !important;
        border: 1px solid rgba(255, 255, 255, 0.6) !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        font-size: 14px !important;
        font-weight: 500;
        box-shadow: 0 2px 6px rgba(0,0,0,0.02) !important;
        transition: all 0.2s ease;
    }}
    .stTextInput > div > input:focus,
    .stTextArea > div > textarea:focus,
    .stSelectbox > div > div:focus-within {{
        border-color: var(--primary-color) !important;
        box-shadow: 0 0 0 4px {bg}33 !important;
        background: white !important;
    }}

    /* Beautiful Primary Buttons */
    div.stButton > button,
    div.stFormSubmitButton > button,
    div[data-testid="stSidebar"] div.stButton > button {{
        {bg_rule}
        {extra_blur}
        color: {tc} !important;
        border: 2px solid {bc} !important;
        border-radius: {br}px !important;
        font-size: {fs}px !important;
        font-weight: {fw} !important;
        padding: {pv}px {ph}px !important;
        box-shadow: {sh} !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
        letter-spacing: 0.3px;
        text-shadow: 0 1px 2px rgba(0,0,0,0.1);
        position: relative;
        overflow: hidden;
    }}
    div.stButton > button:hover,
    div.stFormSubmitButton > button:hover,
    div[data-testid="stSidebar"] div.stButton > button:hover {{
        {hover_bg_rule}
        transform: translateY(-2px) scale(1.02);
        box-shadow: 0 8px 25px {bg}66 !important;
    }}
    div.stButton > button:active {{
        transform: scale(0.96);
    }}

    /* Chat Bubble Styling (Target Streamlit's internal message structure) */
    [data-testid="stChatMessage"] {{
        background: transparent !important;
        padding: 0 !important;
        margin-bottom: 12px !important;
    }}
    [data-testid="stChatMessage"] > div {{
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }}
    /* User (Sent) Messages */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) > div > div:last-child {{
        background: linear-gradient(135deg, {bg}, {hbg}) !important;
        color: white !important;
        border-radius: 18px 18px 4px 18px !important;
        padding: 12px 18px !important;
        box-shadow: 0 4px 12px {bg}55 !important;
        max-width: 80%;
        margin-left: auto;
        font-weight: 400;
    }}
    /* Assistant (Received) Messages */
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) > div > div:last-child {{
        background: rgba(255, 255, 255, 0.6) !important;
        backdrop-filter: blur(8px);
        color: #1f2937 !important;
        border-radius: 18px 18px 18px 4px !important;
        padding: 12px 18px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
        border: 1px solid rgba(255,255,255,0.5) !important;
        max-width: 80%;
        font-weight: 400;
    }}
    /* Avatar fixes */
    [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-user"],
    [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-assistant"] {{
        border: 2px solid white !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
    }}
    
    /* Glass Cards for Feed/Posts */
    .stContainer {{
        background: rgba(255, 255, 255, 0.4);
        backdrop-filter: blur(12px);
        border-radius: 16px;
        padding: 16px 20px;
        margin-bottom: 16px;
        border: 1px solid rgba(255, 255, 255, 0.6);
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .stContainer:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.06);
    }}

    /* Modern Metrics Cards */
    div[data-testid="stMetric"] {{
        background: rgba(255, 255, 255, 0.5);
        backdrop-filter: blur(8px);
        border-radius: 14px;
        padding: 16px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
        border: 1px solid rgba(255, 255, 255, 0.5);
    }}
    div[data-testid="stMetric"] label {{
        color: #4b5563 !important;
        font-weight: 500 !important;
    }}
    div[data-testid="stMetric"] div {{
        color: #111827 !important;
        font-weight: 700 !important;
        font-size: 1.5rem !important;
    }}

    /* Navigation Pills (Tabs at top) */
    div.stButton button {{
        font-size: 13px !important;
        padding: 6px 14px !important;
        border-radius: 30px !important;
        background: rgba(255, 255, 255, 0.4) !important;
        backdrop-filter: blur(4px) !important;
        border: 1px solid rgba(255,255,255,0.6) !important;
        color: #4b5563 !important;
        box-shadow: none !important;
        font-weight: 500 !important;
        transition: all 0.3s ease !important;
    }}
    div.stButton button:hover {{
        background: {bg} !important;
        color: white !important;
        transform: scale(1.05) !important;
        box-shadow: 0 4px 12px {bg}44 !important;
    }}
    </style>
    """

# -------------------------------
# 7. CHAT UI — DMs + Group Chat + Group Call
# -------------------------------

def show_group_call_ui(group_id, group_name, members):
    """Show an in-page group call panel."""
    tiles_html = ""
    for uid, uname, upic, urole in members:
        color = get_avatar_color(uname)
        initials = get_initials(uname)
        svg = f'''<svg width="48" height="48" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="50" cy="50" r="45" fill="{color}" />
                    <text x="50" y="67" font-size="40" text-anchor="middle" fill="white" font-family="Arial">{initials}</text>
                  </svg>'''
        b64_svg = base64.b64encode(svg.encode()).decode()
        tiles_html += f"""
        <div style="background: rgba(255,255,255,0.12); border-radius: 12px; padding: 16px 20px;
                    text-align: center; min-width: 90px; backdrop-filter: blur(8px);">
            <img src="data:image/svg+xml;base64,{b64_svg}" width="48" height="48"
                 style="border-radius:50%; margin-bottom:8px; border:2px solid rgba(255,255,255,0.3);">
            <div style="font-size:12px; color:white; font-weight:600;">{uname}</div>
            <div style="font-size:10px; color:#86efac; margin-top:2px;">🔊 Connected</div>
        </div>"""

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e1b4b, #312e81);
                border-radius: 16px; padding: 24px; margin: 12px 0; color: white;">
        <div style="text-align: center; margin-bottom: 20px;">
            <div style="font-size: 22px; font-weight: 700;">📞 {group_name}</div>
            <div style="font-size: 13px; color: #a5b4fc; margin-top: 4px;">Group Call · {len(members)} participants</div>
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; margin-bottom: 16px;">
            {tiles_html}
        </div>
        <div style="text-align:center; color:#a5b4fc; font-size:12px; margin-bottom:16px;">
            ⚠️ Live group calls require a WebRTC backend (e.g. Jitsi Meet or Agora). This panel shows the call room UI.
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🎤 Mute / Unmute", key=f"gc_mute_{group_id}", use_container_width=True):
            st.toast("Microphone toggled")
    with col2:
        if st.button("📹 Camera On/Off", key=f"gc_cam_{group_id}", use_container_width=True):
            st.toast("Camera toggled")
    with col3:
        if st.button("📵 Leave Call", key=f"gc_leave_{group_id}", use_container_width=True):
            st.session_state.pop(f"in_call_{group_id}", None)
            st.rerun()


def show_group_chat(group_id):
    """Render the selected group chat with messages + group call."""
    group = get_group_info(group_id)
    if not group:
        st.error("Group not found.")
        return
    gid, gname, gdesc, gcreator, gcreated = group
    members = get_group_members(group_id)
    member_ids = [m[0] for m in members]

    if not is_group_member(group_id, st.session_state.user_id):
        st.warning("You are not a member of this group.")
        return

    # ---- Header bar ----
    hcol1, hcol2, hcol3, hcol4 = st.columns([5, 1, 1, 1])
    with hcol1:
        st.markdown(f"""
        <div style="display:flex; align-items:center; gap:12px; padding:8px 0;">
            <div style="width:46px;height:46px;border-radius:50%;
                        background:linear-gradient(135deg,#f093fb,#f5576c);
                        display:flex;align-items:center;justify-content:center;
                        color:white;font-size:20px;flex-shrink:0;">👥</div>
            <div>
                <div style="font-size:17px;font-weight:700;color:#111;">{gname}</div>
                <div style="font-size:12px;color:#6b7280;">{len(members)} members{(' · ' + gdesc[:40]) if gdesc else ''}</div>
            </div>
        </div>""", unsafe_allow_html=True)
    with hcol2:
        if st.button("👥 Members", key=f"grp_mem_{group_id}", use_container_width=True):
            key = f"show_members_{group_id}"
            st.session_state[key] = not st.session_state.get(key, False)
    with hcol3:
        if st.button("🔊 Voice", key=f"grp_voice_{group_id}", use_container_width=True):
            st.session_state[f"in_call_{group_id}"] = "voice"
    with hcol4:
        if st.button("📹 Video", key=f"grp_video_{group_id}", use_container_width=True):
            st.session_state[f"in_call_{group_id}"] = "video"

    # ---- Members panel ----
    if st.session_state.get(f"show_members_{group_id}", False):
        with st.expander("👥 Group Members", expanded=True):
            for uid, uname, upic, urole in members:
                pic_html = get_profile_pic_html(uid, uname, upic, size=36)
                role_tag = "👑 Admin" if urole == "admin" else "👤 Member"
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:10px;padding:6px 0;
                            border-bottom:1px solid #f3f4f6;">
                    {pic_html}
                    <span style="font-weight:600;">{uname}</span>
                    <span style="font-size:11px;color:#9ca3af;margin-left:auto;">{role_tag}</span>
                </div>""", unsafe_allow_html=True)
            # Admin: add new members
            if st.session_state.user_id == gcreator:
                all_users_df = get_all_users()
                non_members = all_users_df[~all_users_df['id'].isin(member_ids)]
                if not non_members.empty:
                    st.markdown("**Add member:**")
                    add_name = st.selectbox("Select user", non_members['username'].tolist(), key=f"add_mem_{group_id}")
                    if st.button("➕ Add to group", key=f"do_add_{group_id}"):
                        new_uid = non_members[non_members['username'] == add_name]['id'].values[0]
                        add_member_to_group(group_id, int(new_uid))
                        st.success(f"{add_name} added!")
                        st.rerun()

    # ---- Active call panel ----
    call_mode = st.session_state.get(f"in_call_{group_id}")
    if call_mode:
        call_label = "🔊 Voice Call" if call_mode == "voice" else "📹 Video Call"
        st.markdown(f"### {call_label} — {gname}")
        show_group_call_ui(group_id, gname, members)
        st.divider()

    # ---- Message history ----
    msgs = load_group_messages(group_id)
    if not msgs:
        st.markdown("""
        <div style="text-align:center; padding:32px; color:#9ca3af;">
            <div style="font-size:32px;">💬</div>
            <div style="margin-top:8px;">No messages yet — say hello!</div>
        </div>""", unsafe_allow_html=True)
    for msg in msgs:
        mid, mtext, mtime, sender_name, sender_pic, sender_id_val, media_type, media_path = msg
        is_me = sender_id_val == st.session_state.user_id
        with st.chat_message("user" if is_me else "assistant"):
            if not is_me:
                st.markdown(f"<small style='color:#6b7280;font-weight:700;'>{sender_name}</small>", unsafe_allow_html=True)
            if media_type == 'text':
                st.write(mtext)
            elif media_type == 'image':
                st.image(media_path, use_column_width=True)
            elif media_type == 'video':
                st.video(media_path)
            st.caption(mtime[:16] if mtime else "")

    # ---- Message input ----
    with st.form(key=f"grp_msg_form_{group_id}", clear_on_submit=True):
        col_in, col_send, col_upload = st.columns([5, 1, 1])
        with col_in:
            grp_msg = st.text_input("Type a message...", key=f"grp_input_{group_id}", label_visibility="collapsed")
        with col_send:
            grp_send = st.form_submit_button("Send", use_container_width=True)
        with col_upload:
            grp_upload = st.form_submit_button("📎", use_container_width=True)
        if grp_send and grp_msg.strip():
            send_group_message(group_id, st.session_state.user_id, grp_msg.strip())
            st.rerun()
        if grp_upload:
            st.session_state[f"grp_show_upload_{group_id}"] = True

    if st.session_state.get(f"grp_show_upload_{group_id}", False):
        uploaded = st.file_uploader("Upload file", type=["jpg","png","jpeg","mp4","mov"],
                                    key=f"grp_file_{group_id}")
        if uploaded:
            fpath = save_uploaded_file(uploaded)
            ext = uploaded.name.split('.')[-1].lower()
            mtype = 'image' if ext in ['jpg','png','jpeg'] else 'video'
            label = "📷 Image" if mtype == 'image' else "🎥 Video"
            send_group_message(group_id, st.session_state.user_id, label, mtype, fpath)
            st.session_state.pop(f"grp_show_upload_{group_id}", None)
            st.rerun()


def show_messages():
    st.markdown("# 💬 Chats")

    with st.sidebar:
        st.markdown("### 👤 My Profile")
        current_pic = st.session_state.get('profile_pic', None)
        if current_pic:
            st.image(current_pic, width=70)
        else:
            st.markdown(get_profile_pic_html(
                st.session_state.user_id, st.session_state.username, None, size=70
            ), unsafe_allow_html=True)
        st.caption(f"**{st.session_state.username}**")
        uploaded_avatar = st.file_uploader("📷 Update photo", type=["jpg", "png", "jpeg"],
                                           key="sidebar_avatar_upload")
        if uploaded_avatar:
            b64 = base64.b64encode(uploaded_avatar.getvalue()).decode()
            new_pic = f"data:image/jpeg;base64,{b64}"
            update_user_field(st.session_state.user_id, 'profile_pic', new_pic)
            st.session_state.profile_pic = new_pic
            st.success("Updated!")
            st.rerun()
        st.divider()

    # ---- Tab switcher: DMs vs Groups ----
    dm_tab, grp_tab = st.tabs(["💬 Direct Messages", "👥 Group Chats"])

    # ===================== DM TAB =====================
    with dm_tab:
        conversations = get_conversations(st.session_state.user_id)
        chat_list = []
        for cid, cname, cpic in conversations:
            last_msg, last_time = get_last_message(st.session_state.user_id, cid)
            chat_list.append({
                "id": cid, "name": cname, "pic": cpic,
                "last_msg": (last_msg[:40] + "…") if last_msg and len(last_msg) > 40
                             else (last_msg or "No messages yet"),
                "last_time": datetime.strptime(last_time, '%Y-%m-%d %H:%M:%S').strftime('%H:%M')
                              if last_time else "",
            })
        chat_list.sort(key=lambda x: x["last_time"], reverse=True)

        with st.sidebar:
            st.markdown(f"#### 💬 DMs ({len(chat_list)})")
            search_term = st.text_input("🔍 Search", placeholder="Search chats...", key="chat_search")
            filtered_chats = (
                [c for c in chat_list if search_term.lower() in c["name"].lower()]
                if search_term else chat_list
            )
            for chat in filtered_chats:
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.markdown(get_profile_pic_html(chat["id"], chat["name"], chat["pic"], size=40),
                                unsafe_allow_html=True)
                with col2:
                    st.markdown(f"**{chat['name']}**")
                    st.caption(f"{chat['last_msg']}  •  {chat['last_time']}")
                if st.button("Open", key=f"dm_{chat['id']}", use_container_width=True):
                    st.session_state.selected_chat = chat["id"]
                    st.session_state.selected_group = None
                    st.rerun()
                st.markdown("<hr style='margin:4px 0;border-color:#eee;'>", unsafe_allow_html=True)

        # ---- DM conversation view ----
        if st.session_state.get("selected_chat") and not st.session_state.get("selected_group"):
            selected_id = st.session_state.selected_chat
            selected_name, selected_pic = None, None
            for c in chat_list:
                if c["id"] == selected_id:
                    selected_name, selected_pic = c["name"], c["pic"]
                    break
            if not selected_name:
                st.session_state.selected_chat = None
                st.rerun()
                return

            # Header
            col1, col2, col3, col4 = st.columns([1, 5, 1, 1])
            with col1:
                st.markdown(get_profile_pic_html(selected_id, selected_name, selected_pic, size=48),
                            unsafe_allow_html=True)
            with col2:
                st.markdown(f"### {selected_name}")
                st.caption("Active")
            with col3:
                if st.button("🔊 Voice", key="dm_voice"):
                    st.toast(f"Calling {selected_name}… (requires WebRTC)")
            with col4:
                if st.button("📹 Video", key="dm_video"):
                    st.toast(f"Video calling {selected_name}… (requires WebRTC)")

            messages = load_messages(st.session_state.user_id, selected_id)
            for msg in messages:
                msg_id, msg_text, timestamp, sender_name, msg_type, media_type, media_path = msg
                with st.chat_message("user" if msg_type == 'sent' else "assistant"):
                    if media_type == 'text':
                        st.write(msg_text)
                    elif media_type == 'image':
                        st.image(media_path, use_column_width=True)
                    elif media_type == 'video':
                        st.video(media_path)
                    elif media_type == 'location':
                        st.write(f"📍 {msg_text}")
                        lat, lng = map(float, media_path.split(','))
                        st.map(pd.DataFrame({'lat': [lat], 'lon': [lng]}))
                    poll = get_poll_by_message(msg_id)
                    if poll:
                        st.markdown(f"**📊 Poll: {poll['question']}**")
                        results = get_poll_results(poll['id'])
                        total_votes = results['votes'].sum() if not results.empty else 0
                        for i, opt in enumerate(poll['options']):
                            votes = (results[results['option_index'] == i]['votes'].values[0]
                                     if not results.empty and i in results['option_index'].values else 0)
                            percent = (votes / total_votes * 100) if total_votes > 0 else 0
                            st.write(f"{opt}: {votes} votes ({percent:.1f}%)")
                            st.progress(percent / 100)
                        if st.button(f"Vote", key=f"vote_{poll['id']}"):
                            selected_opt = st.selectbox("Choose option", poll['options'],
                                                        key=f"select_{poll['id']}")
                            idx = poll['options'].index(selected_opt)
                            vote_poll(poll['id'], st.session_state.user_id, idx)
                            st.rerun()
                    st.caption(timestamp[:16])

            with st.form(key="message_form", clear_on_submit=True):
                col1, col2, col3, col4 = st.columns([4, 1, 1, 1])
                with col1:
                    new_msg = st.text_input("Type a message...", key="msg_input",
                                            label_visibility="collapsed")
                with col2:
                    send_btn = st.form_submit_button("Send", use_container_width=True)
                with col3:
                    poll_btn = st.form_submit_button("📊 Poll", use_container_width=True)
                with col4:
                    upload_btn = st.form_submit_button("📎 File", use_container_width=True)
                if send_btn and new_msg:
                    send_message(st.session_state.user_id, selected_id, new_msg)
                    st.rerun()
                if upload_btn:
                    st.session_state.show_uploader = True

            if st.session_state.get("show_uploader", False):
                st.markdown("#### 📎 Upload file (max 200 MB)")
                uploaded_file = st.file_uploader("Choose file",
                                                  type=["jpg","png","jpeg","mp4","mov","avi"],
                                                  key="main_upload")
                if uploaded_file:
                    file_size_mb = uploaded_file.size / (1024 * 1024)
                    if file_size_mb > 200:
                        st.error("File exceeds 200 MB limit")
                    else:
                        file_path = save_uploaded_file(uploaded_file)
                        ext = uploaded_file.name.split('.')[-1].lower()
                        if ext in ["jpg","png","jpeg"]:
                            send_message(st.session_state.user_id, selected_id, "📷 Image",
                                         media_type='image', media_path=file_path)
                        elif ext in ["mp4","mov","avi"]:
                            send_message(st.session_state.user_id, selected_id, "🎥 Video",
                                         media_type='video', media_path=file_path)
                        st.session_state.show_uploader = False
                        st.rerun()

            if poll_btn:
                st.session_state.show_poll_creator = True
            if st.session_state.get("show_poll_creator", False):
                st.markdown("### 📊 Create a Poll")
                question = st.text_input("Question")
                options = []
                for i in range(3):
                    opt = st.text_input(f"Option {i+1}", key=f"opt_{i}")
                    if opt:
                        options.append(opt)
                if st.button("Send Poll"):
                    if question and len(options) >= 2:
                        msg_id = send_message(st.session_state.user_id, selected_id,
                                              f"📊 Poll: {question}", media_type='text')
                        create_poll(msg_id, question, options, st.session_state.user_id)
                        st.session_state.show_poll_creator = False
                        st.rerun()
                    else:
                        st.error("Enter question and at least 2 options")

            with st.expander("📷 Shared Photos & Videos"):
                media_messages = [m for m in messages if m[5] in ['image', 'video']]
                if media_messages:
                    cols = st.columns(3)
                    for idx, m in enumerate(media_messages[:9]):
                        with cols[idx % 3]:
                            if m[5] == 'image':
                                st.image(m[6], use_column_width=True)
                            else:
                                st.video(m[6])
                else:
                    st.info("No shared media yet.")

            with st.expander("⚙️ Chat Settings"):
                st.button("🎨 Change Color")
                st.button("😀 Change Emoji")
                st.button("🔗 Links")
        else:
            st.markdown("""
            <div style="text-align:center; padding:60px 20px; color:#9ca3af;">
                <div style="font-size:48px;">💬</div>
                <div style="font-size:18px; font-weight:600; margin-top:12px;">No chat selected</div>
                <div style="font-size:14px; margin-top:6px;">Pick a conversation from the sidebar</div>
            </div>""", unsafe_allow_html=True)

    # ===================== GROUP TAB =====================
    with grp_tab:
        with st.sidebar:
            st.markdown("#### 👥 My Groups")
            my_groups = get_user_groups(st.session_state.user_id)
            if my_groups:
                for g in my_groups:
                    gid, gname, gdesc, gcreator, gmembers, glast, glastt = g
                    last_preview = (glast[:35] + "…") if glast and len(glast) > 35 else (glast or "No messages")
                    st.markdown(f"""
                    <div style="padding:8px 10px; border-radius:10px;
                                background:rgba(249,250,251,0.95);
                                margin-bottom:6px; border-left:3px solid #f093fb;">
                        <div style="font-weight:700; font-size:14px;">👥 {gname}</div>
                        <div style="font-size:11px; color:#6b7280;">
                            {gmembers} members · {last_preview}
                        </div>
                    </div>""", unsafe_allow_html=True)
                    if st.button("Open", key=f"grp_open_{gid}", use_container_width=True):
                        st.session_state.selected_group = gid
                        st.session_state.selected_chat = None
                        st.rerun()
            else:
                st.caption("No groups yet")
            st.divider()
            if st.button("➕ New Group", key="create_grp_btn", use_container_width=True):
                st.session_state.show_create_group = True

        # Create group form
        if st.session_state.get("show_create_group", False):
            st.markdown("### 👥 Create a New Group")
            with st.form("create_group_form"):
                grp_name = st.text_input("Group name *")
                grp_desc = st.text_area("Description (optional)", height=80)
                all_users_df = get_all_users()
                other_users = all_users_df[all_users_df['id'] != st.session_state.user_id]
                selected_members = st.multiselect("Add members", other_users['username'].tolist())
                col1, col2 = st.columns(2)
                with col1:
                    create_sub = st.form_submit_button("✅ Create Group", use_container_width=True)
                with col2:
                    cancel_sub = st.form_submit_button("Cancel", use_container_width=True)
                if create_sub:
                    if not grp_name.strip():
                        st.error("Group name is required.")
                    else:
                        member_ids = []
                        for mname in selected_members:
                            row = other_users[other_users['username'] == mname]
                            if not row.empty:
                                member_ids.append(int(row.iloc[0]['id']))
                        new_gid = create_group(grp_name.strip(), grp_desc.strip(),
                                               st.session_state.user_id, member_ids)
                        st.success(f"Group '{grp_name}' created!")
                        st.session_state.show_create_group = False
                        st.session_state.selected_group = new_gid
                        st.session_state.selected_chat = None
                        st.rerun()
                if cancel_sub:
                    st.session_state.show_create_group = False
                    st.rerun()

        # Group chat view
        elif st.session_state.get("selected_group"):
            show_group_chat(st.session_state.selected_group)
        else:
            st.markdown("""
            <div style="text-align:center; padding:60px 20px; color:#9ca3af;">
                <div style="font-size:48px;">👥</div>
                <div style="font-size:18px; font-weight:600; margin-top:12px;">No group selected</div>
                <div style="font-size:14px; margin-top:6px;">
                    Create a group or select one from the sidebar
                </div>
            </div>""", unsafe_allow_html=True)

# -------------------------------
# 8. OTHER UI TABS
# -------------------------------

def show_feed():
    st.markdown("## 🏠 Home Feed")
    broadcasts = get_active_broadcasts()
    if not broadcasts.empty:
        st.subheader("📢 Admin Live")
        for _, bcast in broadcasts.iterrows():
            with st.container():
                st.video(bcast['video_path'])
                st.caption(f"📢 {bcast['caption']} — {bcast['admin_name']} • Expires {bcast['expires_at'][:16]}")
                mark_broadcast_viewed(bcast['id'], st.session_state.user_id)
                st.write(f"👁️ {bcast['view_count']} views")
                st.divider()
    with st.expander("➕ Create new post"):
        post_type = st.radio("Post type", ["Text", "Image"], key="post_type")
        if post_type == "Text":
            text_content = st.text_area("What's on your mind?")
            if st.button("Share Text Post"):
                if text_content.strip():
                    create_post(st.session_state.user_id, "text", text_content)
                    st.success("Post shared!")
                    st.rerun()
        else:
            uploaded_img = st.file_uploader("Choose image", type=["jpg","png","jpeg"], key="post_img")
            if uploaded_img and st.button("Share Image Post"):
                b64 = base64.b64encode(uploaded_img.getvalue()).decode()
                create_post(st.session_state.user_id, "image", f"data:image/jpeg;base64,{b64}")
                st.success("Image posted!")
                st.rerun()
    st.divider()
    feed_df = get_feed_posts(st.session_state.user_id)
    if feed_df.empty:
        st.info("No posts yet. Be the first to share something!")
        return
    for _, row in feed_df.iterrows():
        with st.container():
            col1, col2, col3 = st.columns([1, 7, 1])
            with col1:
                pic_html = get_profile_pic_html(row['user_id'], row['username'], row['profile_pic'], size=50)
                st.markdown(pic_html, unsafe_allow_html=True)
            with col2:
                st.markdown(f"**{row['username']}**  \n*{row['created_at'][:16]}*")
            with col3:
                if row['user_id'] == st.session_state.user_id or st.session_state.user_role == 'admin':
                    if st.button("🗑️", key=f"del_{row['id']}"):
                        delete_post(row['id'], st.session_state.user_id, st.session_state.user_role=='admin')
                        st.rerun()
            if row['media_type'] == 'text':
                st.write(row['content'])
            else:
                st.image(row['content'], use_column_width=True)
            liked = row['user_liked'] == 1
            like_label = f"❤️ {row['like_count']}" if liked else f"🤍 {row['like_count']}"
            if st.button(like_label, key=f"like_{row['id']}"):
                toggle_like(row['id'], st.session_state.user_id)
                st.rerun()
            st.markdown("---")

def show_search():
    st.header("🔍 Search Users")
    search_term = st.text_input("Enter username")
    if search_term:
        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute(
                "SELECT id, username, profile_pic FROM users WHERE username LIKE ? AND id != ?",
                (f"%{search_term}%", st.session_state.user_id)
            )
            users = c.fetchall()
        except Exception as e:
            st.error(f"Database error: {e}")
            conn.close()
            return
        conn.close()

        if users:
            for row in users:
                user_id, username, profile_pic = row
                col1, col2, col3 = st.columns([1, 3, 1])
                with col1:
                    pic_html = get_profile_pic_html(user_id, username, profile_pic, size=40)
                    st.markdown(pic_html, unsafe_allow_html=True)
                with col2:
                    st.write(username)
                with col3:
                    if st.button("Chat", key=f"chat_{user_id}"):
                        st.session_state.selected_chat = user_id
                        st.session_state.current_tab = "messages"
                        st.rerun()
        else:
            st.info("No users found")

def show_stories():
    st.header("📸 Stories")
    with st.expander("➕ Add your story (expires in 24h)"):
        story_type = st.radio("Story type", ["Text", "Image"], key="story_type")
        if story_type == "Text":
            story_text = st.text_area("What's on your mind?")
            if st.button("Post Text Story"):
                if story_text.strip():
                    add_story(st.session_state.user_id, "text", story_text)
                    st.success("Story posted!")
                    st.rerun()
        else:
            uploaded_file = st.file_uploader("Choose an image", type=["jpg","png","jpeg"], key="story_img")
            if uploaded_file and st.button("Post Image Story"):
                b64 = base64.b64encode(uploaded_file.getvalue()).decode()
                add_story(st.session_state.user_id, "image", f"data:image/jpeg;base64,{b64}")
                st.success("Image story posted!")
                st.rerun()
    st.divider()
    active_stories = get_active_stories(st.session_state.user_id)
    if active_stories:
        for su in active_stories:
            pic_with_ring = get_profile_pic_html(su['user_id'], su['username'], su['profile_pic'], size=60, with_story_ring=True)
            st.markdown(pic_with_ring, unsafe_allow_html=True)
            st.write(f"**{su['username']}** ({len(su['stories'])} stories)")
            if st.button(f"View Stories", key=f"view_{su['user_id']}"):
                st.session_state.viewing_stories = su['user_id']
                st.session_state.story_index = 0
                st.rerun()
            st.divider()
    else:
        st.info("No active stories from other users. Add your own story above!")
    view_stories_modal()

def show_profile():
    st.header(f"👤 {st.session_state.username}")
    pic_html = get_profile_pic_html(st.session_state.user_id, st.session_state.username, 
                                    st.session_state.get('profile_pic', None), size=100)
    st.markdown(pic_html, unsafe_allow_html=True)
    st.write(f"Role: {st.session_state.user_role}")
    user_data = get_user_by_id(st.session_state.user_id)
    if user_data:
        is_premium = user_data[4]
        st.write(f"Premium: {'✅ Yes' if is_premium else '❌ No'}")
    msg_count = get_user_message_count(st.session_state.user_id)
    post_count = get_user_post_count(st.session_state.user_id)
    story_count = get_user_story_count(st.session_state.user_id)
    likes_received = get_user_likes_received(st.session_state.user_id)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Messages", msg_count)
    col2.metric("Posts", post_count)
    col3.metric("Stories", story_count)
    col4.metric("Likes Received", likes_received)
    with st.expander("Change profile picture"):
        uploaded = st.file_uploader("Upload image", type=["jpg","png","jpeg"])
        if uploaded and st.button("Update"):
            b64 = base64.b64encode(uploaded.getvalue()).decode()
            update_user_field(st.session_state.user_id, 'profile_pic', f"data:image/jpeg;base64,{b64}")
            st.session_state.profile_pic = f"data:image/jpeg;base64,{b64}"
            st.rerun()
    if st.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    if st.session_state.user_role in ["admin", "editor"]:
        st.divider()
        st.subheader("🔧 Admin/Editor Panel")
        if st.button("Open Management Panel", use_container_width=True):
            st.session_state.show_admin_panel = True
    if st.session_state.get("show_admin_panel", False):
        admin_panel()
        if st.button("Close Panel"):
            st.session_state.show_admin_panel = False
            st.rerun()

# -------------------------------
# 9. LOGIN PAGE (Enhanced with animated gradient & glass buttons)
# -------------------------------

def login_page():
    # Apply background from app setting (if any)
    bg_value = get_app_setting("bg_login")
    if bg_value:
        if bg_value.startswith(('linear', 'url', 'data:image')):
            bg_css = bg_value
        else:
            bg_css = bg_value
        st.markdown(f"""
        <style>
        .stApp {{
            background: {bg_css};
            background-size: cover;
            background-attachment: fixed;
        }}
        </style>
        """, unsafe_allow_html=True)

    # Inject beautiful global UI + button styles
    st.markdown(get_global_ui_css(), unsafe_allow_html=True)

    st.markdown("""
        <style>
        @keyframes float {
            0% { transform: translateY(0px) rotate(0deg); }
            50% { transform: translateY(-20px) rotate(2deg); }
            100% { transform: translateY(0px) rotate(0deg); }
        }
        .login-title {
            text-align: center;
            font-size: 42px;
            font-weight: 800;
            background: linear-gradient(135deg, #4f46e5, #06b6d4, #8b5cf6);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            margin-bottom: 10px;
            letter-spacing: -0.5px;
            animation: fadeInDown 0.8s ease;
        }
        .login-subtitle {
            text-align: center;
            font-size: 24px;
            margin-bottom: 10px;
            color: #334155;
            font-weight: 500;
        }
        .login-message {
            text-align: center;
            font-size: 16px;
            margin-bottom: 30px;
            color: #64748b;
        }
        .login-container {
            max-width: 450px;
            margin: 0 auto;
            padding: 2.5rem;
            border-radius: 24px;
            background: rgba(255, 255, 255, 0.5);
            backdrop-filter: blur(20px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.6);
            animation: float 6s ease-in-out infinite;
        }
        .forgot-password {
            text-align: right;
            font-size: 12px;
            margin-top: -10px;
            margin-bottom: 15px;
        }
        .forgot-password a { color: #4f46e5; text-decoration: none; }
        .login-footer {
            text-align: center;
            font-size: 12px;
            margin-top: 25px;
            color: #94a3b8;
        }
        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        div[data-testid="stForm"] { background: transparent; padding: 0; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="login-container">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">✨ Terminal Management System ✨</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-subtitle">Selamat Datang</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-message">Silakan login terlebih dahulu</div>', unsafe_allow_html=True)

    if "show_register" not in st.session_state:
        st.session_state.show_register = False

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔑 Login", use_container_width=True, key="login_btn"):
            st.session_state.show_register = False
    with col2:
        if st.button("📝 Create Account", use_container_width=True, key="register_btn"):
            st.session_state.show_register = True

    if not st.session_state.show_register:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            st.markdown('<div class="forgot-password"><a href="#">Lupa password?</a></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                user = check_login(username, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user[0]
                    st.session_state.username = user[1]
                    st.session_state.user_role = user[2]
                    st.session_state.profile_pic = user[4]
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password.")
    else:
        with st.form("register_form"):
            new_username = st.text_input("Username", placeholder="Choose a username")
            new_password = st.text_input("Password", type="password", placeholder="Min. 4 characters")
            confirm = st.text_input("Confirm Password", type="password", placeholder="Repeat password")
            submitted = st.form_submit_button("Register", use_container_width=True)
            if submitted:
                if new_password != confirm:
                    st.error("Passwords do not match")
                elif len(new_password) < 4:
                    st.error("Password must be at least 4 characters")
                elif not re.match("^[a-zA-Z0-9_]+$", new_username):
                    st.error("Username can only contain letters, numbers, underscore")
                else:
                    if register_user(new_username, new_password):
                        st.success("✅ Registration successful! Please login.")
                        st.session_state.show_register = False
                        st.rerun()
                    else:
                        st.error("❌ Username already exists.")
    st.markdown('<div class="login-footer">© 2019 All Rights Reserved | Modern Glass UI</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# -------------------------------
# 10. MAIN APP (with per‑tab background injection)
# -------------------------------

def main():
    init_db()
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "current_tab" not in st.session_state:
        st.session_state.current_tab = "messages"
    
    if not st.session_state.logged_in:
        login_page()
    else:
        # Inject background CSS based on the current tab
        tab_key = st.session_state.current_tab
        bg_value = get_app_setting(f"bg_{tab_key}")
        if bg_value:
            if bg_value.startswith(('linear', 'url', 'data:image')):
                bg_css = bg_value
            else:
                bg_css = bg_value
            st.markdown(f"""
                <style>
                .stApp {{
                    background: {bg_css};
                    background-size: cover;
                    background-attachment: fixed;
                }}
                </style>
            """, unsafe_allow_html=True)

        # Inject custom global UI styles (Buttons, Chat bubbles, Glass cards)
        st.markdown(get_global_ui_css(), unsafe_allow_html=True)

        # ---- Navigation bar ----
        st.markdown("---")
        tab_defs = [
            ("💬", "Messages", "messages"),
            ("🏠", "Home", "home"),
            ("🔍", "Search", "search"),
            ("📸", "Stories", "stories"),
            ("👤", "Profile", "profile"),
        ]
        nav_cols = st.columns(len(tab_defs))
        for col, (icon, label, key) in zip(nav_cols, tab_defs):
            with col:
                active = "✦ " if st.session_state.current_tab == key else ""
                btn_label = f"{active}{icon} {label}"
                if st.button(btn_label, use_container_width=True, key=f"nav_{key}"):
                    st.session_state.current_tab = key
                    st.rerun()
        st.markdown("---")
        
        tab = st.session_state.current_tab
        if tab == "messages":
            show_messages()
        elif tab == "home":
            show_feed()
        elif tab == "search":
            show_search()
        elif tab == "stories":
            show_stories()
        elif tab == "profile":
            show_profile()

if __name__ == "__main__":
    main()