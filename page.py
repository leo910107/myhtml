import hmac
import os
import time
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from storage import create_storage, is_safe_path_part

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


BASE_DIR = Path(__file__).resolve().parent
download_folder_from_env = os.environ.get("DOWNLOAD_FOLDER")
DOWNLOAD_FOLDER = (
    Path(download_folder_from_env)
    if download_folder_from_env
    else BASE_DIR / "downloads"
).resolve()

DEFAULT_CATEGORIES = (
    "數量方法",
    "個體經濟學",
    "總體經濟學",
    "計量經濟學",
    "學習筆記",
    "工作文件",
    "其他",
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config["DOWNLOAD_FOLDER"] = str(DOWNLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024))
storage = create_storage(DOWNLOAD_FOLDER, DEFAULT_CATEGORIES)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")
MAX_TOTAL_STORAGE_BYTES = int(os.environ.get("MAX_TOTAL_STORAGE_BYTES", 2 * 1024 * 1024 * 1024))
MAX_FILE_COUNT = int(os.environ.get("MAX_FILE_COUNT", 200))
MAX_DOWNLOADS_PER_HOUR_PER_IP = int(os.environ.get("MAX_DOWNLOADS_PER_HOUR_PER_IP", 120))
DOWNLOAD_RATE_WINDOW_SECONDS = 60 * 60
download_events_by_ip = {}

mock_data = [
    {"id": 1, "type": "note", "title": "Flask 學習筆記", "content": "Flask 是一個輕量的 Python Web 框架。"},
    {"id": 2, "type": "note", "title": "Python 資料結構", "content": "介紹串列 (List)、字典 (Dictionary) 的用法。"},
    {"id": 3, "type": "file", "title": "常用指令.txt", "content": "git clone, git push, pip install..."},
    {"id": 4, "type": "about", "title": "關於 Cheng-Ho Wang", "content": "這是 Cheng-Ho Wang 使用 Flask 製作的個人網站。"},
]


def is_logged_in():
    return bool(session.get("logged_in"))


def get_categorized_files():
    return storage.list_files()


def get_categories():
    return storage.list_categories()


def format_bytes(size):
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)

    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024


def get_uploaded_file_size(file_storage):
    current_position = file_storage.stream.tell()
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(current_position)
    return size


def get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.remote_addr or "unknown"


def is_download_rate_limited():
    if MAX_DOWNLOADS_PER_HOUR_PER_IP <= 0:
        return False

    now = time.time()
    cutoff = now - DOWNLOAD_RATE_WINDOW_SECONDS
    client_ip = get_client_ip()
    events = [event_time for event_time in download_events_by_ip.get(client_ip, []) if event_time >= cutoff]

    if len(events) >= MAX_DOWNLOADS_PER_HOUR_PER_IP:
        download_events_by_ip[client_ip] = events
        return True

    events.append(now)
    download_events_by_ip[client_ip] = events
    return False


def validate_upload_limits(file_storage):
    upload_size = get_uploaded_file_size(file_storage)
    file_storage.stream.seek(0)

    if MAX_TOTAL_STORAGE_BYTES > 0:
        stats = storage.usage_stats()
        if stats["total_bytes"] + upload_size > MAX_TOTAL_STORAGE_BYTES:
            return (
                "已超過網站總儲存上限。"
                f"目前已使用 {format_bytes(stats['total_bytes'])}，"
                f"上限是 {format_bytes(MAX_TOTAL_STORAGE_BYTES)}。"
            )

    if MAX_FILE_COUNT > 0:
        stats = storage.usage_stats()
        if stats["file_count"] >= MAX_FILE_COUNT:
            return f"已達到檔案數量上限：{MAX_FILE_COUNT} 個。"

    return None


@app.errorhandler(413)
def file_too_large(error):
    flash(f"檔案太大，單一檔案上限是 {format_bytes(app.config['MAX_CONTENT_LENGTH'])}。")
    return redirect(url_for("file_page"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/note")
def note():
    return render_template("note.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/learning_record")
def learning_record():
    return render_template("learning_record.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        username_matches = hmac.compare_digest(username, ADMIN_USERNAME)
        password_matches = hmac.compare_digest(password, ADMIN_PASSWORD)

        if username_matches and password_matches:
            session["logged_in"] = True
            return redirect(url_for("file_page"))

        error = "無效的使用者名稱或密碼"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("index"))


@app.route("/downloads/<path:filepath>")
def download_file(filepath):
    if "/" not in filepath:
        abort(404)

    category, filename = filepath.split("/", 1)
    if not is_safe_path_part(category) or not is_safe_path_part(filename):
        abort(404)

    if is_download_rate_limited():
        abort(429, description="下載次數太頻繁，請稍後再試。")

    return storage.download_response(category, filename)


@app.route("/delete_file", methods=["POST"])
def delete_file():
    if not is_logged_in():
        return redirect(url_for("index"))

    category = request.form.get("category", "")
    filename = request.form.get("filename", "")

    if is_safe_path_part(category) and is_safe_path_part(filename):
        storage.delete(category, filename)

    return redirect(url_for("file_page"))


@app.route("/add_category", methods=["POST"])
def add_category():
    if not is_logged_in():
        return redirect(url_for("login"))

    category = request.form.get("category", "").strip()
    if not is_safe_path_part(category):
        flash("分類名稱不能空白，也不能包含 /、\\ 或 ..")
        return redirect(url_for("file_page"))

    storage.add_category(category)
    flash(f"已新增分類：{category}")
    return redirect(url_for("file_page"))


@app.route("/delete_category", methods=["POST"])
def delete_category():
    if not is_logged_in():
        return redirect(url_for("login"))

    category = request.form.get("category", "").strip()
    if not is_safe_path_part(category):
        flash("分類名稱無效。")
        return redirect(url_for("file_page"))

    try:
        storage.delete_category(category)
        flash(f"已刪除分類：{category}")
    except ValueError as error:
        flash(str(error))

    return redirect(url_for("file_page"))


@app.route("/file", methods=["GET", "POST"])
def file_page():
    if request.method == "POST":
        if not is_logged_in():
            return redirect(url_for("login"))

        file = request.files.get("file_to_upload")
        category = request.form.get("category", "").strip()
        categories = get_categories()

        if category not in categories:
            flash("請先選擇或新增一個有效分類。")
            return redirect(request.url)

        if file and file.filename:
            filename = file.filename

            if not is_safe_path_part(filename):
                flash("檔名不能包含 /、\\ 或 ..")
                return redirect(request.url)

            limit_error = validate_upload_limits(file)
            if limit_error:
                flash(limit_error)
                return redirect(request.url)

            storage.save(file, category, filename)
            flash(f"已上傳檔案：{filename}")

            return redirect(url_for("file_page"))

        flash("請先選擇要上傳的檔案。")
        return redirect(request.url)

    return render_template(
        "file.html",
        categories=get_categories(),
        categorized_files=get_categorized_files(),
        storage_stats=storage.usage_stats(),
        storage_limits={
            "max_total_storage_bytes": MAX_TOTAL_STORAGE_BYTES,
            "max_file_count": MAX_FILE_COUNT,
            "max_downloads_per_hour_per_ip": MAX_DOWNLOADS_PER_HOUR_PER_IP,
        },
        format_bytes=format_bytes,
    )


@app.route("/search")
def search():
    query = request.args.get("query", "")
    search_results = []
    dynamic_search_index = list(mock_data)

    for category_name, filenames in get_categorized_files().items():
        for filename in filenames:
            dynamic_search_index.append(
                {
                    "id": f"file_{category_name}_{filename}",
                    "type": "file",
                    "title": filename,
                    "content": f"位於 {category_name} 分類下的檔案",
                }
            )

    if query:
        normalized_query = query.lower()
        for item in dynamic_search_index:
            if normalized_query in item["title"].lower() or normalized_query in item["content"].lower():
                search_results.append(item)

    return render_template("search_results.html", query=query, results=search_results)


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1")
