import hmac
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify
from azure.data.tables import TableServiceClient, UpdateMode
from azure.core.exceptions import ResourceNotFoundError

app = Flask(__name__)

CATEGORIES = ["部活", "行事", "落とし物", "相談"]
TABLE_NAME = "posts"
PARTITION = "post"

CONN = os.environ.get("STORAGE_CONNECTION_STRING")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

table = None
if CONN:
    service = TableServiceClient.from_connection_string(CONN)
    table = service.create_table_if_not_exists(TABLE_NAME)

memory_posts = []


def to_json(e):
    return {
        "id": e["RowKey"],
        "t": e["title"],
        "b": e["body"],
        "c": e["category"],
        "n": e["nickname"],
        "ok": bool(e.get("verified", False)),
        "extra": bool(e.get("extra", False)),
        "hidden": bool(e.get("hidden", False)),
        "r": int(e.get("reads", 0)),
        "created": e.get("created", ""),
    }


def all_posts(include_hidden=False):
    entities = list(table.list_entities()) if table else list(memory_posts)
    entities.sort(key=lambda e: e.get("created", ""), reverse=True)
    posts = [to_json(e) for e in entities]
    return posts if include_hidden else [p for p in posts if not p["hidden"]]


def is_admin():
    # Admin disabled until ADMIN_PASSWORD is set in Azure.
    given = request.headers.get("X-Admin-Password", "")
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(given.encode(), ADMIN_PASSWORD.encode())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.get("/api/posts")
def get_posts():
    return jsonify(all_posts())


@app.post("/api/posts")
def create_post():
    data = request.get_json(silent=True) or {}
    title = str(data.get("t", "")).strip()
    body = str(data.get("b", "")).strip()
    category = str(data.get("c", "")).strip()
    nickname = str(data.get("n", "")).strip()

    # validate
    if not (title and body and nickname):
        return jsonify(error="required"), 400
    if len(title) > 30 or len(body) > 100 or len(nickname) > 12:
        return jsonify(error="too long"), 400
    if category not in CATEGORIES:
        return jsonify(error="bad category"), 400

    entity = {
        "PartitionKey": PARTITION,
        "RowKey": uuid.uuid4().hex,
        "title": title,
        "body": body,
        "category": category,
        "nickname": nickname,
        "verified": False,   # admin only
        "extra": False,
        "hidden": False,
        "reads": 0,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if table:
            table.create_entity(entity)
        else:
            memory_posts.append(entity)
    except Exception as e:
        app.logger.exception("save failed")
        return jsonify(error=str(e)), 500
    return jsonify(to_json(entity)), 201


@app.post("/api/posts/<post_id>/read")
def read_post(post_id):
    delta = 1 if (request.get_json(silent=True) or {}).get("delta", 1) >= 0 else -1
    if table:
        try:
            e = table.get_entity(PARTITION, post_id)
        except ResourceNotFoundError:
            return jsonify(error="not found"), 404
        e["reads"] = max(0, int(e.get("reads", 0)) + delta)
        table.update_entity(e, mode=UpdateMode.MERGE)
    else:
        e = next((x for x in memory_posts if x["RowKey"] == post_id), None)
        if not e:
            return jsonify(error="not found"), 404
        e["reads"] = max(0, e["reads"] + delta)
    return jsonify(r=int(e["reads"]))


# ---------- admin ----------

@app.get("/api/admin/posts")
def admin_list():
    if not is_admin():
        return jsonify(error="unauthorized"), 401
    return jsonify(all_posts(include_hidden=True))


@app.post("/api/admin/posts/<post_id>")
def admin_update(post_id):
    if not is_admin():
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    changes = {k: bool(data[k]) for k in ("verified", "extra", "hidden") if k in data}
    if table:
        try:
            e = table.get_entity(PARTITION, post_id)
        except ResourceNotFoundError:
            return jsonify(error="not found"), 404
        e.update(changes)
        table.update_entity(e, mode=UpdateMode.MERGE)
    else:
        e = next((x for x in memory_posts if x["RowKey"] == post_id), None)
        if not e:
            return jsonify(error="not found"), 404
        e.update(changes)
    return jsonify(to_json(e))


if __name__ == "__main__":
    app.run(debug=True)