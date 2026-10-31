import os
import base64
import secrets
import sqlite3
from pathlib import Path
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session, flash,
    render_template, Response
)

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "rafin.db"

app = Flask(__name__)
app.secret_key = os.environ.get("RAFIN_SECRET_KEY", "rafin-txt-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

ADMIN_PASSWORD = os.environ.get("RAFIN_ADMIN_PASSWORD", "RAFIN_888")
TELEGRAM_LINK = "https://t.me/alien_boss_676"
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

# ডিফল্ট ছবি (খালি না দেখানোর জন্য)
DEFAULT_PROFILE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

# ---------- ডেটাবেস ----------
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price TEXT NOT NULL,
                category TEXT,
                description TEXT,
                image_mime TEXT,
                image_data BLOB,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()

init_db()

def list_products():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, name, price, category, description,
                   (image_data IS NOT NULL) AS has_image
            FROM products
            ORDER BY created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]

def get_product(pid):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    return dict(row) if row else None

def get_site_photo_key():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='site_photo'").fetchone()
    return row["value"] if row else None

# ---------- হেল্পার ----------
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            flash("এই অংশে ঢুকতে আগে প্রশাসক হিসেবে প্রবেশ করো।", "error")
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper

def ext_ok(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def file_to_base64(file):
    if not file or not file.filename or not ext_ok(file.filename, IMAGE_EXTENSIONS):
        return None, None
    data = file.read()
    if not data:
        return None, None
    ext = file.filename.rsplit(".", 1)[1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return mime, data

# ---------- রুট ----------
@app.route("/")
def home():
    return render_template(
        "index.html",
        products=list_products(),
        is_admin=bool(session.get("admin")),
        show_login=request.args.get("login") == "1",
        telegram_link=TELEGRAM_LINK,
    )

@app.post("/login")
def login():
    if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
        session["admin"] = True
        flash("প্রশাসক প্যানেলে প্রবেশ সফল হয়েছে।", "success")
    else:
        flash("গোপন সংকেত সঠিক নয়।", "error")
    return redirect(url_for("home"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.post("/add")
@admin_required
def add_item():
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    if not name or not price:
        flash("পণ্যের নাম ও দাম লিখতে হবে।", "error")
        return redirect(url_for("home"))

    mime, data = file_to_base64(request.files.get("photo"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO products (id,name,price,category,description,image_mime,image_data) VALUES (?,?,?,?,?,?,?)",
            (
                secrets.token_hex(6), name, price,
                request.form.get("category", "").strip(),
                request.form.get("description", "").strip(),
                mime, data,
            ),
        )
        conn.commit()
    flash("নতুন পণ্য যোগ হয়েছে।", "success")
    return redirect(url_for("home"))

@app.route("/edit/<pid>", methods=["GET", "POST"])
@admin_required
def edit_item(pid):
    item = get_product(pid)
    if not item:
        flash("পণ্যটি পাওয়া যায়নি।", "error")
        return redirect(url_for("home"))

    if request.method == "POST":
        mime, data = file_to_base64(request.files.get("photo"))
        with get_db() as conn:
            if data:
                conn.execute(
                    "UPDATE products SET name=?,price=?,category=?,description=?,image_mime=?,image_data=? WHERE id=?",
                    (request.form.get("name", "").strip(), request.form.get("price", "").strip(),
                     request.form.get("category", "").strip(), request.form.get("description", "").strip(),
                     mime, data, pid),
                )
            else:
                conn.execute(
                    "UPDATE products SET name=?,price=?,category=?,description=? WHERE id=?",
                    (request.form.get("name", "").strip(), request.form.get("price", "").strip(),
                     request.form.get("category", "").strip(), request.form.get("description", "").strip(), pid),
                )
            conn.commit()
        flash("পণ্যের তথ্য বদলানো হয়েছে।", "success")
        return redirect(url_for("home"))

    return render_template("edit.html", item=item)

@app.post("/delete/<pid>")
@admin_required
def delete_item(pid):
    with get_db() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
    flash("পণ্য মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("home"))

@app.get("/product-image/<pid>")
def product_image(pid):
    with get_db() as conn:
        row = conn.execute("SELECT image_mime, image_data FROM products WHERE id=?", (pid,)).fetchone()
    if not row or not row["image_data"]:
        return "", 404
    return Response(row["image_data"], mimetype=row["image_mime"] or "image/png")

@app.post("/site-photo/update")
@admin_required
def update_site_photo():
    mime, data = file_to_base64(request.files.get("site_photo"))
    if not data:
        flash("একটি JPG, PNG, WEBP বা GIF ছবি বেছে নাও।", "error")
        return redirect(url_for("home"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES ('site_photo',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"{mime}|{base64.b64encode(data).decode()}",),
        )
        conn.commit()
    flash("সাইটের ছবি পরিবর্তন হয়েছে।", "success")
    return redirect(url_for("home"))

@app.get("/site-photo")
def site_photo():
    key = get_site_photo_key()
    if key:
        mime, b64 = key.split("|", 1)
        return Response(base64.b64decode(b64), mimetype=mime)
    return Response(base64.b64decode(DEFAULT_PROFILE_B64), mimetype="image/png")

@app.errorhandler(413)
def too_large(_e):
    flash("ফাইলটি অনেক বড়। ২৫ এমবির মধ্যে রাখো।", "error")
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)