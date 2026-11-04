from flask import (
    Flask, render_template, request, redirect,
    send_from_directory, session, url_for
)
import sqlite3
import os
import uuid
import re
import math
from collections import Counter
from functools import wraps

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-before-deployment"
)


# ==================================================
# IMAGE UPLOAD SETTINGS
# ==================================================

if os.environ.get("VERCEL"):
    UPLOAD_FOLDER = "/tmp/uploads"
else:
    UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# ==================================================
# DATABASE CONNECTION
# ==================================================

def get_db_connection():
    conn = sqlite3.connect("campusfind.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ==================================================
# LOGIN PROTECTION
# ==================================================

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


# ==================================================
# AI ITEM MATCHING
# ==================================================

def calculate_similarity(text1, text2):

    words1 = re.findall(r"\b\w+\b", (text1 or "").lower())
    words2 = re.findall(r"\b\w+\b", (text2 or "").lower())

    if not words1 or not words2:
        return 0

    all_words = set(words1 + words2)

    tf1 = Counter(words1)
    tf2 = Counter(words2)

    vector1 = []
    vector2 = []

    for word in all_words:

        document_count = (
            1 + int(word in words1) + int(word in words2)
        )

        idf = math.log(3 / document_count) + 1

        vector1.append(
            (tf1[word] / len(words1)) * idf
        )

        vector2.append(
            (tf2[word] / len(words2)) * idf
        )

    dot_product = sum(
        a * b for a, b in zip(vector1, vector2)
    )

    magnitude1 = math.sqrt(
        sum(a * a for a in vector1)
    )

    magnitude2 = math.sqrt(
        sum(b * b for b in vector2)
    )

    if magnitude1 == 0 or magnitude2 == 0:
        return 0

    return (
        dot_product / (magnitude1 * magnitude2)
    ) * 100


def item_text(item):

    return " ".join([
        item["item_name"] or "",
        item["description"] or "",
        item["category"] or "",
        item["location"] or ""
    ])


# ==================================================
# CREATE DATABASE TABLES
# ==================================================

def create_table():

    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fullname TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS lost_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            date_lost TEXT NOT NULL,
            image TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS found_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            date_found TEXT NOT NULL,
            image TEXT NOT NULL
        )
    """)

    # Add user_id to older databases

    for table_name in ("lost_items", "found_items"):

        columns = {
            row["name"]
            for row in conn.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }

        if "user_id" not in columns:

            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER"
            )

    # Notifications table

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            lost_item_id INTEGER NOT NULL,
            found_item_id INTEGER NOT NULL,
            similarity REAL NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(lost_item_id, found_item_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(lost_item_id) REFERENCES lost_items(id),
            FOREIGN KEY(found_item_id) REFERENCES found_items(id)
        )
    """)

    # Messages table

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lost_item_id INTEGER NOT NULL,
            found_item_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id),
            FOREIGN KEY(lost_item_id) REFERENCES lost_items(id),
            FOREIGN KEY(found_item_id) REFERENCES found_items(id)
        )
    """)

    conn.commit()
    conn.close()


# ==================================================
# LOGIN PAGE
# ==================================================

@app.route("/")
def login():

    return render_template("login.html")


# ==================================================
# REGISTRATION
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not fullname or not email or not password:

            return render_template(
                "register.html",
                message="Please fill in all fields."
            )

        if password != confirm_password:

            return render_template(
                "register.html",
                message="Passwords do not match!"
            )

        if len(password) < 8:

            return render_template(
                "register.html",
                message="Password must contain at least 8 characters."
            )

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()

        try:

            conn.execute("""
                INSERT INTO users (fullname, email, password)
                VALUES (?, ?, ?)
            """, (
                fullname,
                email,
                hashed_password
            ))

            conn.commit()

            return render_template(
                "register.html",
                message="Registration successful! Please login."
            )

        except sqlite3.IntegrityError:

            return render_template(
                "register.html",
                message="This email is already registered."
            )

        finally:
            conn.close()

    return render_template("register.html")


# ==================================================
# LOGIN AUTHENTICATION
# ==================================================

@app.route("/login", methods=["POST"])
def login_user():

    email = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    conn = get_db_connection()

    user = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    conn.close()

    if user and check_password_hash(user["password"], password):

        session.clear()

        session["user_id"] = user["id"]
        session["fullname"] = user["fullname"]

        return redirect("/home")

    return render_template(
        "login.html",
        message="Invalid email or password."
    )


# ==================================================
# SETTINGS
# ==================================================

@app.route("/settings")
@login_required
def settings():

    return render_template("settings.html")


# ==================================================
# USER PROFILE
# ==================================================

@app.route("/profile")
@login_required
def profile():

    conn = get_db_connection()

    user = conn.execute(
        "SELECT fullname, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    lost_count = conn.execute(
        "SELECT COUNT(*) FROM lost_items WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0]

    found_count = conn.execute(
        "SELECT COUNT(*) FROM found_items WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()[0]

    conn.close()

    if not user:

        session.clear()

        return redirect(url_for("login"))

    return render_template(
        "profile.html",
        user=user,
        lost_count=lost_count,
        found_count=found_count
    )


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
@login_required
def logout():

    session.clear()

    return redirect(url_for("login"))


# ==================================================
# HOME
# ==================================================

@app.route("/home")
@login_required
def home():

    return render_template("home.html")


# ==================================================
# LOST ITEM
# ==================================================

@app.route("/lost-item", methods=["GET", "POST"])
@login_required
def lost_item():

    if request.method == "POST":

        item_name = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        date_lost = request.form.get("date_lost", "").strip()

        if not all([
            item_name,
            description,
            category,
            location,
            date_lost
        ]):

            return render_template(
                "lost_item.html",
                message="Please fill in all required fields."
            )

        image_name = None

        image = request.files.get("image")

        if image and image.filename:

            if not allowed_file(image.filename):

                return render_template(
                    "lost_item.html",
                    message="Please upload a PNG, JPG, JPEG or WEBP image."
                )

            filename = secure_filename(image.filename)

            unique_filename = str(uuid.uuid4()) + "_" + filename

            image.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    unique_filename
                )
            )

            image_name = unique_filename

        conn = get_db_connection()

        conn.execute("""
            INSERT INTO lost_items
            (item_name, description, category, location,
             date_lost, image, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            item_name,
            description,
            category,
            location,
            date_lost,
            image_name,
            session["user_id"]
        ))

        conn.commit()
        conn.close()

        return render_template(
            "lost_item.html",
            message="Lost item reported successfully!"
        )

    return render_template("lost_item.html")


# ==================================================
# FOUND ITEM
# ==================================================

@app.route("/found-item", methods=["GET", "POST"])
@login_required
def found_item():

    if request.method == "POST":

        item_name = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip()
        location = request.form.get("location", "").strip()
        date_found = request.form.get("date_found", "").strip()

        if not all([
            item_name,
            description,
            category,
            location,
            date_found
        ]):

            return render_template(
                "found_item.html",
                message="Please fill in all required fields."
            )

        image = request.files.get("image")

        if not image or not image.filename:

            return render_template(
                "found_item.html",
                message="Please upload an item image."
            )

        if not allowed_file(image.filename):

            return render_template(
                "found_item.html",
                message="Please upload a PNG, JPG, JPEG or WEBP image."
            )

        filename = secure_filename(image.filename)

        unique_filename = str(uuid.uuid4()) + "_" + filename

        # Save image in the configured upload folder
        image_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            unique_filename
        )

        image.save(image_path)

        conn = get_db_connection()

        cursor = conn.execute("""
            INSERT INTO found_items
            (item_name, description, category, location,
             date_found, image, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            item_name,
            description,
            category,
            location,
            date_found,
            unique_filename,
            session["user_id"]
        ))

        found_id = cursor.lastrowid

        lost_items = conn.execute(
            "SELECT * FROM lost_items WHERE user_id IS NOT NULL"
        ).fetchall()

        found_record = conn.execute(
            "SELECT * FROM found_items WHERE id = ?",
            (found_id,)
        ).fetchone()

        for lost in lost_items:

            if lost["user_id"] == session["user_id"]:
                continue

            score = calculate_similarity(
                item_text(lost),
                item_text(found_record)
            )

            if score >= 15:

                conn.execute("""
                    INSERT OR IGNORE INTO notifications
                    (user_id, lost_item_id, found_item_id,
                     similarity, message)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    lost["user_id"],
                    lost["id"],
                    found_id,
                    round(score, 2),
                    "A found item may match your lost-item report."
                ))

        conn.commit()
        conn.close()

        return render_template(
            "found_item.html",
            message="Found item reported successfully! Matching notifications have been checked."
        )

    return render_template("found_item.html")


# ==================================================
# REPORTS
# ==================================================

@app.route("/reports")
@login_required
def reports():

    conn = get_db_connection()

    lost_items = conn.execute(
        "SELECT * FROM lost_items ORDER BY id DESC"
    ).fetchall()

    found_items = conn.execute(
        "SELECT * FROM found_items ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        lost_items=lost_items,
        found_items=found_items
    )


# ==================================================
# AI MATCHES
# ==================================================

@app.route("/matches")
@login_required
def matches():

    conn = get_db_connection()

    lost_items = conn.execute(
        "SELECT * FROM lost_items"
    ).fetchall()

    found_items = conn.execute(
        "SELECT * FROM found_items"
    ).fetchall()

    conn.close()

    matching_items = []

    for lost in lost_items:

        for found in found_items:

            score = calculate_similarity(
                item_text(lost),
                item_text(found)
            )

            if score >= 15:

                matching_items.append({
                    "lost": lost,
                    "found": found,
                    "score": round(score, 2)
                })

    matching_items.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return render_template(
        "matches.html",
        matching_items=matching_items
    )


# ==================================================
# NOTIFICATIONS
# ==================================================

@app.route("/notifications")
@login_required
def notifications():

    conn = get_db_connection()

    notification_rows = conn.execute("""
        SELECT
            notifications.*,
            lost_items.item_name AS lost_item_name,
            found_items.item_name AS found_item_name
        FROM notifications
        JOIN lost_items ON lost_items.id = notifications.lost_item_id
        JOIN found_items ON found_items.id = notifications.found_item_id
        WHERE notifications.user_id = ?
        ORDER BY notifications.created_at DESC, notifications.id DESC
    """, (session["user_id"],)).fetchall()

    unread_count = conn.execute("""
        SELECT COUNT(*) AS total
        FROM notifications
        WHERE user_id = ? AND is_read = 0
    """, (session["user_id"],)).fetchone()["total"]

    conn.close()

    return render_template(
        "notifications.html",
        notifications=notification_rows,
        unread_count=unread_count
    )


# ==================================================
# CONTACT FINDER - MESSAGING
# ==================================================

@app.route("/messages", methods=["GET", "POST"])
@login_required
def messages():

    lost_id = request.args.get("lost_id", type=int)
    found_id = request.args.get("found_id", type=int)

    if not lost_id or not found_id:
        return "Invalid match details.", 400

    conn = get_db_connection()

    lost_item = conn.execute(
        "SELECT * FROM lost_items WHERE id = ?",
        (lost_id,)
    ).fetchone()

    found_item = conn.execute(
        "SELECT * FROM found_items WHERE id = ?",
        (found_id,)
    ).fetchone()

    if not lost_item or not found_item:

        conn.close()

        return "Match not found.", 404

    current_user = session["user_id"]

    lost_owner = lost_item["user_id"]
    finder = found_item["user_id"]

    score = calculate_similarity(
        item_text(lost_item),
        item_text(found_item)
    )

    if (
        lost_owner is None
        or finder is None
        or lost_owner == finder
        or current_user not in (lost_owner, finder)
        or score < 15
    ):

        conn.close()

        return "You are not allowed to access this chat.", 403

    other_user_id = (
        finder if current_user == lost_owner else lost_owner
    )

    other_user = conn.execute(
        "SELECT fullname FROM users WHERE id = ?",
        (other_user_id,)
    ).fetchone()

    if not other_user:

        conn.close()

        return "Other student account not found.", 404

    if request.method == "POST":

        message_text = request.form.get(
            "message", ""
        ).strip()

        if not message_text:

            conn.close()

            return redirect(url_for(
                "messages",
                lost_id=lost_id,
                found_id=found_id
            ))

        if len(message_text) > 1000:

            conn.close()

            return "Message is too long. Maximum 1000 characters.", 400

        conn.execute("""
            INSERT INTO messages
            (lost_item_id, found_item_id, sender_id, receiver_id, message)
            VALUES (?, ?, ?, ?, ?)
        """, (
            lost_id,
            found_id,
            current_user,
            other_user_id,
            message_text
        ))

        conn.commit()
        conn.close()

        return redirect(url_for(
            "messages",
            lost_id=lost_id,
            found_id=found_id
        ))

    chat_messages = conn.execute("""
        SELECT
            messages.*,
            users.fullname AS sender_name
        FROM messages
        JOIN users ON users.id = messages.sender_id
        WHERE messages.lost_item_id = ?
          AND messages.found_item_id = ?
        ORDER BY messages.created_at ASC, messages.id ASC
    """, (lost_id, found_id)).fetchall()

    conn.close()

    return render_template(
        "messages.html",
        chat_messages=chat_messages,
        other_user=other_user,
        current_user=current_user,
        lost_item=lost_item,
        found_item=found_item
    )


# ==================================================
# MATCH DETAILS
# ==================================================

@app.route("/match_details/<int:lost_id>/<int:found_id>")
@login_required
def match_details(lost_id, found_id):

    conn = get_db_connection()

    lost_item = conn.execute(
        "SELECT * FROM lost_items WHERE id = ?",
        (lost_id,)
    ).fetchone()

    found_item = conn.execute(
        "SELECT * FROM found_items WHERE id = ?",
        (found_id,)
    ).fetchone()

    if not lost_item or not found_item:

        conn.close()

        return "Match details not found.", 404

    current_user_id = session["user_id"]

    if (
        lost_item["user_id"] != current_user_id
        and found_item["user_id"] != current_user_id
    ):

        conn.close()

        return "You are not allowed to view this match.", 403

    score = calculate_similarity(
        item_text(lost_item),
        item_text(found_item)
    )

    if score < 15:

        conn.close()

        return "These items do not meet the AI matching threshold.", 404

    conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ? AND lost_item_id = ? AND found_item_id = ?
    """, (
        current_user_id,
        lost_id,
        found_id
    ))

    conn.commit()
    conn.close()

    return render_template(
        "match_details.html",
        lost_item=lost_item,
        found_item=found_item,
        score=round(score, 2)
    )


# ==================================================
# DISPLAY UPLOADED IMAGES
# ==================================================

@app.route("/uploads/<filename>")
def uploaded_file(filename):

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# ==================================================
# RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    create_table()

    app.run(
        port=5001,
        debug=True
    )