
import hashlib
import hmac
import os
import secrets
import sqlite3


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "oceanguard.db"))


def get_db_connection():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


PASSWORD_ITERATIONS = 310000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256$" + str(PASSWORD_ITERATIONS) + "$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_text, salt_hex, digest_hex = stored_hash.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations_text),
            )
            return hmac.compare_digest(digest.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, stored_hash)


def ensure_column(cursor, table: str, column: str, definition: str) -> None:
    cursor.execute("PRAGMA table_info(" + table + ")")
    columns = {row[1] for row in cursor.fetchall()}
    if column not in columns:
        cursor.execute(
            "ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition
        )


def init_db() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
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
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT NOT NULL,
            color TEXT NOT NULL,
            description TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_code TEXT UNIQUE,
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
            reporter_contact TEXT DEFAULT '',
            source TEXT DEFAULT 'community',
            is_demo INTEGER DEFAULT 0,
            upvotes INTEGER DEFAULT 0,
            admin_notes TEXT DEFAULT '',
            observed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vessel_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vessel_id TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            speed_knots REAL,
            heading REAL,
            is_demo INTEGER DEFAULT 0,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    ensure_column(cursor, "reports", "report_code", "TEXT")
    ensure_column(cursor, "reports", "reporter_contact", "TEXT DEFAULT ''")
    ensure_column(cursor, "reports", "source", "TEXT DEFAULT 'community'")
    ensure_column(cursor, "reports", "is_demo", "INTEGER DEFAULT 0")
    ensure_column(cursor, "reports", "observed_at", "TIMESTAMP")
    ensure_column(cursor, "reports", "admin_notes", "TEXT DEFAULT ''")
    ensure_column(cursor, "reports", "updated_at", "TIMESTAMP")

    categories = [
        (
            "oil_spill",
            "Oil Spill",
            "droplet",
            "#ef4444",
            "Petroleum, fuel or chemical release into water",
        ),
        (
            "high_waves",
            "High Waves & Surge",
            "waves",
            "#38bdf8",
            "Dangerous sea state, swell or abnormal wave activity",
        ),
        (
            "storm",
            "Storm / Cyclone",
            "cloud-lightning",
            "#fb7185",
            "Storm cells, cyclonic activity or extreme weather",
        ),
        (
            "pollution",
            "Plastic & Waste",
            "trash-2",
            "#f59e0b",
            "Floating plastic, fishing gear or hazardous waste",
        ),
        (
            "debris",
            "Floating Debris",
            "box",
            "#a8a29e",
            "Containers, logs, wreckage or navigation hazards",
        ),
        (
            "marine_animals",
            "Marine Wildlife",
            "fish",
            "#34d399",
            "Stranding, entanglement or vulnerable wildlife sighting",
        ),
        (
            "other",
            "Other Hazard",
            "alert-triangle",
            "#c084fc",
            "Other observed ocean or coastal hazard",
        ),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO categories (id, name, icon, color, description)
        VALUES (?, ?, ?, ?, ?)
        """,
        categories,
    )

    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    users = [
        (
            "admin",
            "admin@oceanguard.local",
            hash_password(admin_password),
            "admin",
            "OceanGuard Administrator",
        ),
        (
            "marine_watcher",
            "watcher@oceanguard.local",
            hash_password("user123"),
            "user",
            "Marine Watcher",
        ),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO users (username, email, password_hash, role, full_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        users,
    )

    # Remove legacy seeded demonstration content from earlier releases.
    # Real community submissions are preserved; only rows explicitly marked as
    # demo/sample data are removed. New installs start with an empty report feed.
    cursor.execute(
        """
        DELETE FROM reports
        WHERE COALESCE(is_demo, 0) = 1
           OR source = 'demo'
           OR report_code LIKE 'OW-DEMO-%'
        """
    )
    cursor.execute(
        "DELETE FROM vessel_locations WHERE COALESCE(is_demo, 0) = 1"
    )
    cursor.execute(
        """
        DELETE FROM notifications
        WHERE lower(title) LIKE '%demo%'
           OR lower(message) LIKE '%demo data%'
        """
    )

    cursor.execute(
        """
        UPDATE reports
        SET report_code = 'OW-' || printf('%06d', id)
        WHERE report_code IS NULL OR report_code = ''
        """
    )
    cursor.execute(
        """
        UPDATE reports
        SET updated_at = COALESCE(updated_at, created_at),
            source = COALESCE(source, 'community'),
            is_demo = COALESCE(is_demo, 0),
            reporter_contact = COALESCE(reporter_contact, ''),
            admin_notes = COALESCE(admin_notes, '')
        """
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("OceanGuard database initialized.")
