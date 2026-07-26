import sqlite3
import os
import hashlib
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "oceanguard.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            full_name TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create categories table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT NOT NULL,
            color TEXT NOT NULL,
            description TEXT
        )
    ''')

    # Create reports table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category_id TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name TEXT NOT NULL,
            image_url TEXT,
            user_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            upvotes INTEGER DEFAULT 0,
            admin_notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # Create notifications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Seed Categories
    categories = [
        ('oil_spill', 'Oil Spill', 'droplet', '#FF5252', 'Petroleum, fuel, or chemical leaks into ocean waters'),
        ('high_waves', 'High Waves & Surge', 'waves', '#00E5FF', 'Dangerous wave heights, rogue waves, or coastal surges'),
        ('pollution', 'Plastic & Trash Pollution', 'trash-2', '#FFB020', 'Floating marine plastic, garbage patches, or hazardous waste'),
        ('debris', 'Floating Debris / Wreckage', 'box', '#E0E0E0', 'Containers, drift logs, submerged hazards, or boat wreckage'),
        ('marine_animals', 'Marine Wildlife Alert', 'fish', '#00D26A', 'Stranded marine life, endangered species sightings, or animal entanglements')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO categories (id, name, icon, color, description)
        VALUES (?, ?, ?, ?, ?)
    ''', categories)

    # Seed Users (Admin & Standard users)
    users = [
        ('admin', 'admin@oceanguard.org', hash_password('admin123'), 'admin', 'Captain Sarah Jenkins (Admin)'),
        ('marine_watcher', 'watcher@ocean.org', hash_password('user123'), 'user', 'Alex Rivera'),
        ('coast_guard_dan', 'dan@coastguard.gov', hash_password('user123'), 'user', 'Lt. Daniel Vance'),
        ('eco_explorer', 'eco@marine.org', hash_password('user123'), 'user', 'Dr. Elena Rostova')
    ]
    cursor.executemany('''
        INSERT OR IGNORE INTO users (username, email, password_hash, role, full_name)
        VALUES (?, ?, ?, ?, ?)
    ''', users)

    # Check if reports exist
    cursor.execute('SELECT COUNT(*) FROM reports')
    if cursor.fetchone()[0] == 0:
        now = datetime.now()
        seed_reports = [
            (
                'Massive Fuel Oil Slick Spotted Near Harbor Gate',
                'oil_spill',
                'Observed a dark iridescent fuel slick spanning over 500 meters near the commercial cargo vessel exit lane. Strong chemical odor detected.',
                'High',
                'Pending',
                37.7749,
                -122.4194,
                'San Francisco Bay Entrance, CA',
                '/uploads/oil_spill_ocean.png',
                2,
                'Alex Rivera',
                14,
                'Coast Guard patrol dispatched to sample water and contain perimeter.',
                (now - timedelta(hours=3)).strftime('%Y-%m-%d %H:%M:%S')
            ),
            (
                'Dense Marine Plastic Waste & Ghost Nets Patch',
                'pollution',
                'Floating collection of discarded plastic containers, abandoned fishing nets, and styrofoam drift hazardous to local seals and boat propellers.',
                'Medium',
                'Verified',
                34.0522,
                -118.2437,
                'Santa Monica Coast, CA',
                '/uploads/plastic_pollution_ocean.png',
                3,
                'Lt. Daniel Vance',
                29,
                'Verified by Port Authority. Marine cleanup barge scheduled for morning collect.',
                (now - timedelta(hours=18)).strftime('%Y-%m-%d %H:%M:%S')
            ),
            (
                'Extreme 6-Meter Breaking Surge Waves Near Pier',
                'high_waves',
                'Abnormally high breaking swells caused by off-shore storm system. Waves overlapping lower walkway and presenting severe danger to pedestrians.',
                'Critical',
                'Verified',
                36.9741,
                -122.0308,
                'Santa Cruz Pier, CA',
                '/uploads/high_waves_hazard.png',
                4,
                'Dr. Elena Rostova',
                42,
                'Coastal warning bulletin published. Pier lower deck closed to public access.',
                (now - timedelta(days=1, hours=4)).strftime('%Y-%m-%d %H:%M:%S')
            ),
            (
                'Submerged Shipping Container Drift Hazard',
                'debris',
                'Semi-submerged blue steel freight container drifting south in the shipping channel. Only top corner visible above waterline.',
                'Critical',
                'Resolved',
                33.7407,
                -118.2731,
                'Long Beach Channel, CA',
                '/uploads/plastic_pollution_ocean.png',
                1,
                'Captain Sarah Jenkins (Admin)',
                35,
                'Tugboat dispatched. Container secured and towed into dry dock for recovery.',
                (now - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
            ),
            (
                'Stranded Humpback Calf Entangled in Cable',
                'marine_animals',
                'Juvenile whale entangled in commercial line floating shallow in bay area. Requiring specialist disentanglement team.',
                'Critical',
                'Verified',
                37.8270,
                -122.4230,
                'Alcatraz Shoal Passage, CA',
                '/uploads/high_waves_hazard.png',
                2,
                'Alex Rivera',
                58,
                'NOAA Marine Mammal Rescue team en route with specialized cutting equipment.',
                (now - timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
            )
        ]
        cursor.executemany('''
            INSERT INTO reports (title, category_id, description, severity, status, latitude, longitude, location_name, image_url, user_id, author_name, upvotes, admin_notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', seed_reports)

        # Seed Notifications
        seed_notifications = [
            (2, 'Report Status Updated', 'Your hazard report "Massive Fuel Oil Slick" was flagged for priority review by Admin.', 'warning', 0),
            (3, 'Verification Complete', 'Report "Dense Marine Plastic Waste" has been Verified by Port Authority.', 'success', 0),
            (1, 'System Alert', 'New Critical report "Stranded Humpback Calf" requires immediate triage review.', 'urgent', 0)
        ]
        cursor.executemany('''
            INSERT INTO notifications (user_id, title, message, type, is_read)
            VALUES (?, ?, ?, ?, ?)
        ''', seed_notifications)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully!")
