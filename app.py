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
table = None
if CONN:
    service = TableServiceClient.from_connection_string(CONN)
    table = service.create_table_if_not_exists(TABLE_NAME)
 
# Fallback so the site still loads without a database (posts vanish on restart).
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
        "r": int(e.get("reads", 0)),
        "created": e.get("created", ""),
    }
 
 
def all_posts():
    entities = list(table.list_entities()) if table else memory_posts
    entities.sort(key=lambda e: e.get("created", ""), reverse=True)
    return [to_json(e) for e in entities]
 
 
@app.route("/")
def index():
    return render_template("index.html")
 
 
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
 
    # Validate on the server too (the browser checks can be bypassed).
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
        "verified": False,   # only the journalism club can set this (edit in Azure for now)
        "extra": False,      # same for 号外
        "reads": 0,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    if table:
        table.create_entity(entity)
    else:
        memory_posts.append(entity)
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
 
 
if __name__ == "__main__":
    app.run(debug=True)
 