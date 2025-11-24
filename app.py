from flask import Flask, jsonify, request, render_template_string, send_from_directory
import base64
import threading
try:
    import webview
except Exception:
    webview = None
try:
    import tkinter as tk
except Exception:
    tk = None
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
import os
import sys
import glob
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import json
import time
from urllib.request import urlopen

def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith('#'):
                        continue
                    k, _, v = s.partition('=')
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass

def _static_base():
    base = os.path.join(os.path.dirname(__file__), 'static')
    if hasattr(sys, '_MEIPASS'):
        base = os.path.join(sys._MEIPASS, 'static')
    return base

app = Flask(__name__, static_folder=_static_base())
CORS(app)
_load_env()
MONGO_URI = os.environ.get('MONGO_URI')
client = MongoClient(MONGO_URI) if MONGO_URI else MongoClient('mongodb://localhost:27017')
mdb = client['tasklist']
tasklists_col = mdb['tasklists']
columns_col = mdb['columns']
tasks_col = mdb['tasks']

def next_id(col):
    doc = col.find_one(sort=[('id', -1)])
    return (doc['id'] + 1) if doc else 1

def ensure_logo():
    src_static = os.path.join(os.path.dirname(__file__), 'static')
    os.makedirs(src_static, exist_ok=True)
    logo_path = os.path.join(src_static, 'logo.png')
    if os.path.exists(logo_path):
        return
    candidates = []
    for pat in ['favicon.png', 'favicon.jpg', 'favicon.jpeg', 'favicon.ico', 'logo.png', 'logo.jpg', 'logo.png']:
        candidates += glob.glob(os.path.join(src_static, pat))
    if candidates:
        src = candidates[0]
        try:
            img = Image.open(src)
            img = img.convert('RGB')
            img.thumbnail((256, 256))
            bg = Image.new('RGB', (256, 256), (255, 255, 255))
            x = (256 - img.width) // 2
            y = (256 - img.height) // 2
            bg.paste(img, (x, y))
            bg.save(logo_path, format='JPEG', quality=90)
            return
        except Exception:
            pass
    img = Image.new('RGB', (256, 256), color=(34, 197, 94))
    draw = ImageDraw.Draw(img)
    for i in range(256):
        draw.line([(0, i), (256, i)], fill=(34, 197 - i//4, 94 + i//8))
    font = ImageFont.load_default()
    text = 'TaskList'
    bbox = draw.textbbox((0,0), text, font=font)
    tw = bbox[2]-bbox[0]
    th = bbox[3]-bbox[1]
    draw.text(((256 - tw)//2, (256 - th)//2), text, fill=(255,255,255), font=font)
    img.save(logo_path, format='JPEG', quality=90)

def _current_logo_name():
    base = app.static_folder
    if os.path.exists(os.path.join(base, 'logo.png')):
        return 'logo.png'
    return 'logo.jpeg'

def ensure_ico():
    base = os.path.join(os.path.dirname(__file__), 'static')
    os.makedirs(base, exist_ok=True)
    ico_path = os.path.join(base, 'app.ico')
    if os.path.exists(ico_path):
        return
    src = None
    for name in ['logo.png', 'logo.jpeg', 'favicon.png', 'favicon.jpg', 'favicon.jpeg']:
        p = os.path.join(base, name)
        if os.path.exists(p):
            src = p
            break
    if not src:
        return
    img = Image.open(src).convert('RGBA')
    sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
    img.save(ico_path, format='ICO', sizes=sizes)

@app.route('/assets/logo')
def serve_logo():
    fn = _current_logo_name()
    return send_from_directory(app.static_folder, fn)

def get_logo_data_url():
    base = app.static_folder
    path = os.path.join(base, _current_logo_name())
    mime = 'image/png' if path.endswith('.png') else 'image/jpeg'
    try:
        with open(path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        return f'data:{mime};base64,{b64}'
    except Exception:
        # Fallback: small embedded pixel
        return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQYV2NgYGD4DwAB6gG9oPLw6wAAAABJRU5ErkJggg=='

# Database Models
if tasklists_col.count_documents({}) == 0:
    tasklists_col.insert_one({'id': 1, 'title': 'TaskList 1', 'created_at': datetime.utcnow()})
ensure_logo()
ensure_ico()

# API Routes for Columns
@app.route('/api/columns', methods=['GET'])
def get_columns():
    list_id = request.args.get('list_id', type=int)
    q = {'task_list_id': list_id} if list_id is not None else {}
    cols = list(columns_col.find(q).sort('position', 1))
    result = []
    for c in cols:
        ts = list(tasks_col.find({'column_id': c['id']}).sort('position', 1))
        result.append({
            'id': c['id'],
            'title': c.get('title', ''),
            'position': c.get('position', 0),
            'created_at': c.get('created_at', datetime.utcnow()).isoformat(),
            'tasks': [{
                'id': t['id'],
                'title': t.get('title', ''),
                'description': t.get('description', ''),
                'completed': t.get('completed', False),
                'position': t.get('position', 0),
                'column_id': t.get('column_id'),
                'created_at': t.get('created_at', datetime.utcnow()).isoformat(),
                'updated_at': t.get('updated_at', t.get('created_at', datetime.utcnow())).isoformat()
            } for t in ts]
        })
    return jsonify(result)

@app.route('/api/columns', methods=['POST'])
def create_column():
    data = request.get_json()
    title = data.get('title', 'New Column')
    list_id = data.get('task_list_id')
    filt = {'task_list_id': list_id} if list_id is not None else {}
    last = columns_col.find_one(filt, sort=[('position', -1)])
    pos = (last['position'] + 1) if last else 1
    new_id = next_id(columns_col)
    doc = {'id': new_id, 'title': title, 'position': pos, 'created_at': datetime.utcnow(), 'task_list_id': list_id}
    columns_col.insert_one(doc)
    return jsonify({'id': doc['id'], 'title': doc['title'], 'position': doc['position'], 'created_at': doc['created_at'].isoformat(), 'tasks': []}), 201

@app.route('/api/columns/<int:column_id>', methods=['PUT'])
def update_column(column_id):
    data = request.get_json()
    update = {}
    if 'title' in data: update['title'] = data['title']
    if 'position' in data: update['position'] = data['position']
    if 'task_list_id' in data: update['task_list_id'] = data['task_list_id']
    columns_col.update_one({'id': column_id}, {'$set': update})
    c = columns_col.find_one({'id': column_id})
    ts = list(tasks_col.find({'column_id': column_id}).sort('position', 1))
    return jsonify({'id': c['id'], 'title': c.get('title',''), 'position': c.get('position',0), 'created_at': c.get('created_at', datetime.utcnow()).isoformat(), 'tasks': [{
        'id': t['id'], 'title': t.get('title',''), 'description': t.get('description',''), 'completed': t.get('completed',False), 'position': t.get('position',0), 'column_id': t.get('column_id'), 'created_at': t.get('created_at', datetime.utcnow()).isoformat(), 'updated_at': t.get('updated_at', t.get('created_at', datetime.utcnow())).isoformat()
    } for t in ts]})

@app.route('/api/columns/<int:column_id>', methods=['DELETE'])
def delete_column(column_id):
    tasks_col.delete_many({'column_id': column_id})
    columns_col.delete_one({'id': column_id})
    return '', 204

# API Routes for Tasks
@app.route('/api/columns/<int:column_id>/tasks', methods=['GET'])
def get_tasks(column_id):
    ts = list(tasks_col.find({'column_id': column_id}).sort('position', 1))
    return jsonify([{
        'id': t['id'], 'title': t.get('title',''), 'description': t.get('description',''), 'completed': t.get('completed',False), 'position': t.get('position',0), 'column_id': t.get('column_id'), 'created_at': t.get('created_at', datetime.utcnow()).isoformat(), 'updated_at': t.get('updated_at', t.get('created_at', datetime.utcnow())).isoformat()
    } for t in ts])

@app.route('/api/columns/<int:column_id>/tasks', methods=['POST'])
def create_task(column_id):
    data = request.get_json()
    title = data.get('title', 'New Task')
    description = data.get('description', '')
    last = tasks_col.find_one({'column_id': column_id}, sort=[('position', -1)])
    pos = (last['position'] + 1) if last else 1
    new_id = next_id(tasks_col)
    now = datetime.utcnow()
    doc = {'id': new_id, 'title': title, 'description': description, 'completed': False, 'position': pos, 'column_id': column_id, 'created_at': now, 'updated_at': now}
    tasks_col.insert_one(doc)
    return jsonify({'id': doc['id'], 'title': doc['title'], 'description': doc['description'], 'completed': doc['completed'], 'position': doc['position'], 'column_id': doc['column_id'], 'created_at': doc['created_at'].isoformat(), 'updated_at': doc['updated_at'].isoformat()}), 201

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    data = request.get_json()
    update = {}
    for k in ['title','description','completed','position','column_id']:
        if k in data: update[k] = data[k]
    update['updated_at'] = datetime.utcnow()
    tasks_col.update_one({'id': task_id}, {'$set': update})
    t = tasks_col.find_one({'id': task_id})
    return jsonify({'id': t['id'], 'title': t.get('title',''), 'description': t.get('description',''), 'completed': t.get('completed',False), 'position': t.get('position',0), 'column_id': t.get('column_id'), 'created_at': t.get('created_at', datetime.utcnow()).isoformat(), 'updated_at': t.get('updated_at', datetime.utcnow()).isoformat()})

@app.route('/api/tasks/<int:task_id>/toggle', methods=['POST'])
def toggle_task(task_id):
    t = tasks_col.find_one({'id': task_id})
    if not t:
        return jsonify({'error':'not found'}), 404
    tasks_col.update_one({'id': task_id}, {'$set': {'completed': not t.get('completed', False), 'updated_at': datetime.utcnow()}})
    t = tasks_col.find_one({'id': task_id})
    return jsonify({'id': t['id'], 'title': t.get('title',''), 'description': t.get('description',''), 'completed': t.get('completed',False), 'position': t.get('position',0), 'column_id': t.get('column_id'), 'created_at': t.get('created_at', datetime.utcnow()).isoformat(), 'updated_at': t.get('updated_at', datetime.utcnow()).isoformat()})

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    tasks_col.delete_one({'id': task_id})
    return '', 204

@app.route('/api/columns/reorder', methods=['POST'])
def reorder_columns():
    data = request.get_json()
    ordered_ids = data.get('ordered_ids', [])
    for idx, col_id in enumerate(ordered_ids, start=1):
        columns_col.update_one({'id': col_id}, {'$set': {'position': idx}})
    return jsonify({'status': 'ok'})

@app.route('/api/tasks/reorder', methods=['POST'])
def reorder_tasks():
    data = request.get_json()
    changes = data.get('changes', [])
    for change in changes:
        column_id = change.get('column_id')
        ordered_ids = change.get('ordered_ids', [])
        for idx, task_id in enumerate(ordered_ids, start=1):
            tasks_col.update_one({'id': task_id}, {'$set': {'column_id': column_id, 'position': idx}})
    return jsonify({'status': 'ok'})

@app.route('/api/tasklists', methods=['GET'])
def get_tasklists():
    lists = list(tasklists_col.find({}).sort('created_at', 1))
    return jsonify([{'id': l['id'], 'title': l.get('title',''), 'created_at': l.get('created_at', datetime.utcnow()).isoformat()} for l in lists])

@app.route('/api/tasklists', methods=['POST'])
def create_tasklist():
    data = request.get_json()
    title = data.get('title', 'TaskList')
    new_id = next_id(tasklists_col)
    doc = {'id': new_id, 'title': title, 'created_at': datetime.utcnow()}
    tasklists_col.insert_one(doc)
    return jsonify({'id': doc['id'], 'title': doc['title'], 'created_at': doc['created_at'].isoformat()}), 201

@app.route('/api/tasklists/<int:list_id>', methods=['PUT'])
def update_tasklist(list_id):
    data = request.get_json()
    tasklists_col.update_one({'id': list_id}, {'$set': {'title': data.get('title')}})
    tl = tasklists_col.find_one({'id': list_id})
    return jsonify({'id': tl['id'], 'title': tl.get('title',''), 'created_at': tl.get('created_at', datetime.utcnow()).isoformat()})

@app.route('/api/tasklists/<int:list_id>', methods=['DELETE'])
def delete_tasklist(list_id):
    col_ids = [c['id'] for c in columns_col.find({'task_list_id': list_id})]
    tasks_col.delete_many({'column_id': {'$in': col_ids}})
    columns_col.delete_many({'task_list_id': list_id})
    tasklists_col.delete_one({'id': list_id})
    return '', 204

# Frontend HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TaskList - Quản lý công việc</title>
    <link rel="icon" href="__LOGO_URL__">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
            color: white;
            margin-left: 280px;
        }

        .header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }

        .board-container {
            display: flex;
            gap: 20px;
            overflow-x: auto;
            padding-bottom: 20px;
            margin-left: 280px;
        }

        .column {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 12px;
            padding: 16px;
            min-width: 300px;
            max-width: 350px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }

        .column-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 2px solid #e0e0e0;
        }

        .column-title {
            font-size: 1.2rem;
            font-weight: 600;
            color: #333;
        }

        .column-actions {
            display: flex;
            gap: 8px;
        }

        .btn {
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: all 0.3s ease;
        }

        .btn-primary {
            background: #4CAF50;
            color: white;
        }

        .btn-primary:hover {
            background: #45a049;
        }

        .btn-danger {
            background: #f44336;
            color: white;
        }

        .btn-danger:hover {
            background: #da190b;
        }

        .btn-small {
            padding: 4px 8px;
            font-size: 0.8rem;
        }

        .btn-icon { display: inline-flex; align-items: center; justify-content: center; }
        .icon { width: 16px; height: 16px; fill: currentColor; }

        .task-list {
            min-height: 100px;
            margin-bottom: 12px;
        }

        .task {
            background: white;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            cursor: pointer;
            transition: all 0.3s ease;
            border-left: 4px solid #2196F3;
        }

        .task:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        }

        .task.completed {
            opacity: 0.7;
            border-left-color: #4CAF50;
        }

        .task.completed .task-title {
            text-decoration: line-through;
            color: #666;
        }

        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .task-title {
            font-weight: 500;
            color: #333;
            flex: 1;
        }

        .task-checkbox {
            width: 18px;
            height: 18px;
            margin-right: 8px;
            cursor: pointer;
        }

        .task-description {
            color: #666;
            font-size: 0.9rem;
            margin-top: 8px;
        }

        .task-actions {
            display: flex;
            gap: 4px;
            margin-top: 8px;
        }

        .add-column {
            background: rgba(255, 255, 255, 0.2);
            border: 2px dashed rgba(255, 255, 255, 0.5);
            border-radius: 12px;
            padding: 20px;
            min-width: 300px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.3s ease;
            color: white;
            font-weight: 500;
        }

        .add-column:hover {
            background: rgba(255, 255, 255, 0.3);
            border-color: rgba(255, 255, 255, 0.7);
        }

        .dragging {
            opacity: 0.5;
        }

        .layout {
            display: grid;
            grid-template-columns: 260px 1fr;
            gap: 16px;
            display: block;
        }

        .leftbar {
            position: fixed;
            top: 0;
            left: 0;
            height: 100vh;
            width: 280px;
            background: #1f2937;
            color: #e5e7eb;
            padding: 16px 12px;
            box-shadow: 2px 0 12px rgba(0,0,0,0.2);
            overflow-y: auto;
        }

        .leftbar-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
            border-bottom: 1px solid #374151;
            padding-bottom: 10px;
        }

        .leftbar-title {
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 0.3px;
        }
        .logo-small { height:18px; width:auto; border-radius:4px; box-shadow:0 1px 4px rgba(0,0,0,0.2); }

        .list-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 12px;
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 6px;
            transition: background 0.2s ease;
            color: #e5e7eb;
        }

        .list-item:hover {
            background: #374151;
        }

        .list-item.active {
            background: #2563eb;
        }

        .list-actions { display: flex; gap: 6px; }
        .leftbar .btn { background: #374151; color: #e5e7eb; }
        .leftbar .btn:hover { background: #4b5563; }
        #addListBtn { background: #2563eb; }
        #addListBtn:hover { background: #1d4ed8; }

        .progress-wrap {
            margin-bottom: 12px;
        }

        .progress {
            width: 100%;
            height: 8px;
            background: #eeeeee;
            border-radius: 999px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            width: 0%;
            background: #2196F3;
            transition: width 0.25s ease;
        }

        .progress-text {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.8rem;
            color: #555;
            margin-top: 6px;
        }

        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
        }

        .modal-content {
            background-color: white;
            margin: 15% auto;
            padding: 20px;
            border-radius: 12px;
            width: 400px;
            max-width: 90%;
        }

        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e0e0e0;
        }

        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }

        .close:hover {
            color: #000;
        }

        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            margin-bottom: 6px;
            font-weight: 500;
            color: #333;
        }

        .form-group input,
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 6px;
            font-size: 1rem;
        }

        .form-group textarea {
            resize: vertical;
            min-height: 80px;
        }

        .splash { position: fixed; inset: 0; display:flex; align-items:center; justify-content:center; flex-direction:column; background: rgba(0,0,0,0.5); z-index: 2000; transition: opacity .3s ease; }
        .splash img { width: 96px; height: 96px; border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,0.35); }
        .splash .title { color: #fff; font-size: 1.4rem; margin-top: 12px; font-weight: 600; letter-spacing: 0.3px; }

        .error {
            background: #f44336;
            color: white;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
        }
        .header-inner { display:flex; align-items:center; gap:12px; justify-content:center; }
        .logo { height:40px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.2); }
        </style>
</head>
<body>
    <div class="header">
        <div class="header-inner">
            <img src="__LOGO_URL__" class="logo" alt="logo">
            <h1>TaskList</h1>
        </div>
        <p>Quản lý công việc của bạn một cách hiệu quả</p>
    </div>

    <div id="splash" class="splash">
        <img src="__LOGO_URL__" alt="logo">
        <div class="title">Đang khởi động…</div>
        <div style="width:320px; max-width:80vw; margin-top:14px;">
            <div class="progress"><div class="progress-fill" id="splashProgressFill"></div></div>
            <div class="progress-text" id="splashProgressText" style="color:#fff;">0%</div>
        </div>
    </div>
    <div id="error" class="error" style="display: none;"></div>

    <div class="layout">
        <aside class="leftbar" id="leftbar">
            <div class="leftbar-header">
                <div class="leftbar-title" style="display:flex;align-items:center;gap:8px;">
                    <img src="__LOGO_URL__" class="logo-small" alt="logo">
                    <span>Danh sách</span>
                </div>
                <button class="btn btn-primary btn-small btn-icon" id="addListBtn" title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
            </div>
            <div id="lists"></div>
        </aside>
        <div id="board" class="board-container" style="display: none;"></div>
    </div>

    <!-- Add Column Modal -->
    <div id="addColumnModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg> Cột Mới</h3>
                <span class="close" onclick="closeModal('addColumnModal')">&times;</span>
            </div>
            <form id="addColumnForm">
                <div class="form-group">
                    <label for="columnTitle">Tiêu đề cột:</label>
                    <input type="text" id="columnTitle" name="title" required>
                </div>
                <button type="submit" class="btn btn-primary btn-icon" title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
            </form>
        </div>
    </div>

    <!-- Add Task Modal -->
    <div id="addTaskModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg> Công Việc Mới</h3>
                <span class="close" onclick="closeModal('addTaskModal')">&times;</span>
            </div>
            <form id="addTaskForm">
                <input type="hidden" id="taskColumnId" name="column_id">
                <div class="form-group">
                    <label for="taskTitle">Tiêu đề công việc:</label>
                    <input type="text" id="taskTitle" name="title" required>
                </div>
                <div class="form-group">
                    <label for="taskDescription">Mô tả:</label>
                    <textarea id="taskDescription" name="description"></textarea>
                </div>
                <button type="submit" class="btn btn-primary btn-icon" title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
            </form>
        </div>
    </div>

    <div id="addListModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg> Danh Sách Mới</h3>
                <span class="close" onclick="closeModal('addListModal')">&times;</span>
            </div>
            <form id="addListForm">
                <div class="form-group">
                    <label for="listTitle">Tên danh sách:</label>
                    <input type="text" id="listTitle" name="title" required>
                </div>
                <button type="submit" class="btn btn-primary btn-icon" title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
            </form>
        </div>
    </div>

    <div id="editListModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3><svg class="icon" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg> Sửa Danh Sách</h3>
                <span class="close" onclick="closeModal('editListModal')">&times;</span>
            </div>
            <form id="editListForm">
                <input type="hidden" id="editListId" name="id">
                <div class="form-group">
                    <label for="editListTitle">Tên danh sách:</label>
                    <input type="text" id="editListTitle" name="title" required>
                </div>
                <button type="submit" class="btn btn-primary btn-icon" title="Lưu"><svg class="icon" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg></button>
            </form>
        </div>
    </div>

    <div id="confirmModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3><svg class="icon" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9z"/></svg> Xác Nhận</h3>
                <span class="close" onclick="closeModal('confirmModal')">&times;</span>
            </div>
            <div class="form-group">
                <div id="confirmMessage" style="color:#111827;"></div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">
                <button id="confirmCancelBtn" class="btn btn-secondary">Hủy</button>
                <button id="confirmOkBtn" class="btn btn-danger">Xác nhận</button>
            </div>
        </div>
    </div>

    <script>
        let currentColumnId = null;
        let currentListId = null;
        let splashStart = null;
        const minSplashMs = 1500;
        const nativeSplash = new URLSearchParams(location.search).has('nativeSplash');
        const splashFill = document.getElementById('splashProgressFill');
        const splashText = document.getElementById('splashProgressText');
        if (nativeSplash) {
            const s = document.getElementById('splash');
            if (s) s.style.display = 'none';
        }
        function setSplashProgress(p) {
            const v = Math.max(0, Math.min(100, Math.round(p)));
            if (splashFill) splashFill.style.width = v + '%';
            if (splashText) splashText.textContent = 'Đang tải… ' + v + '%';
        }

        // API functions
        async function fetchColumns() {
            try {
                const response = await fetch(`/api/columns?list_id=${currentListId ?? ''}`);
                if (!response.ok) throw new Error('Failed to fetch columns');
                return await response.json();
            } catch (error) {
                showError('Không thể tải dữ liệu: ' + error.message);
                return [];
            }
        }

        async function fetchLists() {
            try {
                const response = await fetch('/api/tasklists');
                if (!response.ok) throw new Error('Failed to fetch lists');
                return await response.json();
            } catch (error) {
                showError('Không thể tải danh sách: ' + error.message);
                return [];
            }
        }

        async function createList(title) {
            const res = await fetch('/api/tasklists', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) });
            if (!res.ok) return null;
            return await res.json();
        }

        async function updateList(id, title) {
            const res = await fetch(`/api/tasklists/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) });
            return res.ok;
        }

        async function deleteList(id) {
            const res = await fetch(`/api/tasklists/${id}`, { method: 'DELETE' });
            return res.ok;
        }

        async function createColumn(title) {
            try {
                const response = await fetch('/api/columns', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ title, task_list_id: currentListId }),
                });
                if (!response.ok) throw new Error('Failed to create column');
                return await response.json();
            } catch (error) {
                showError('Không thể tạo cột: ' + error.message);
                return null;
            }
        }

        async function deleteColumn(columnId) {
            try {
                const response = await fetch(`/api/columns/${columnId}`, {
                    method: 'DELETE',
                });
                if (!response.ok) throw new Error('Failed to delete column');
                return true;
            } catch (error) {
                showError('Không thể xóa cột: ' + error.message);
                return false;
            }
        }

        async function createTask(columnId, title, description) {
            try {
                const response = await fetch(`/api/columns/${columnId}/tasks`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ title, description }),
                });
                if (!response.ok) throw new Error('Failed to create task');
                return await response.json();
            } catch (error) {
                showError('Không thể tạo công việc: ' + error.message);
                return null;
            }
        }

        async function toggleTask(taskId) {
            try {
                const response = await fetch(`/api/tasks/${taskId}/toggle`, {
                    method: 'POST',
                });
                if (!response.ok) throw new Error('Failed to toggle task');
                return await response.json();
            } catch (error) {
                showError('Không thể cập nhật trạng thái: ' + error.message);
                return null;
            }
        }

        async function deleteTask(taskId) {
            try {
                const response = await fetch(`/api/tasks/${taskId}`, {
                    method: 'DELETE',
                });
                if (!response.ok) throw new Error('Failed to delete task');
                return true;
            } catch (error) {
                showError('Không thể xóa công việc: ' + error.message);
                return false;
            }
        }

        // UI functions
        function showError(message) {
            const errorDiv = document.getElementById('error');
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
            setTimeout(() => {
                errorDiv.style.display = 'none';
            }, 5000);
        }

        function openModal(modalId) {
            document.getElementById(modalId).style.display = 'block';
        }

        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
        }

        let confirmAction = null;
        function openConfirmModal(message, onConfirm) {
            confirmAction = onConfirm;
            const el = document.getElementById('confirmMessage');
            if (el) el.textContent = message || '';
            openModal('confirmModal');
        }

        function renderColumn(column) {
            const completed = column.tasks.filter(t => t.completed).length;
            const total = column.tasks.length;
            const percent = total ? Math.round((completed / total) * 100) : 0;
            const barColor = percent === 100 ? '#4CAF50' : '#2196F3';
            return `
                <div class="column" data-column-id="${column.id}" draggable="true">
                    <div class="column-header">
                        <div class="column-title">${column.title}</div>
                        <div class="column-actions">
                            <button class="btn btn-primary btn-small btn-icon" onclick="openAddTaskModal(${column.id})" title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
                            <button class="btn btn-danger btn-small btn-icon" onclick="deleteColumnHandler(${column.id})" title="Xóa"><svg class="icon" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9z"/></svg></button>
                        </div>
                    </div>
                    <div class="progress-wrap">
                        <div class="progress"><div class="progress-fill" style="width: ${percent}%; background: ${barColor}"></div></div>
                        <div class="progress-text"><span>${completed}/${total}</span><span>${percent}%</span></div>
                    </div>
                    <div class="task-list" data-column-id="${column.id}">
                        ${column.tasks.map(task => renderTask(task)).join('')}
                    </div>
                </div>
            `;
        }

        function renderTask(task) {
            return `
                <div class="task ${task.completed ? 'completed' : ''}" data-task-id="${task.id}" draggable="true">
                    <div class="task-header">
                        <div style="display: flex; align-items: center;">
                            <input type="checkbox" class="task-checkbox" ${task.completed ? 'checked' : ''} 
                                   onchange="toggleTaskHandler(${task.id})">
                            <div class="task-title">${task.title}</div>
                        </div>
                    </div>
                    ${task.description ? `<div class="task-description">${task.description}</div>` : ''}
                    <div class="task-actions">
                        <button class="btn btn-danger btn-small btn-icon" onclick="deleteTaskHandler(${task.id})" title="Xóa"><svg class="icon" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9z"/></svg></button>
                    </div>
                </div>
            `;
        }

        let hasLoaded = false;
        async function loadBoard() {
            if (!hasLoaded) {
                document.getElementById('board').style.display = 'none';
                splashStart = performance.now();
            }
            
            if (!hasLoaded) setSplashProgress(5);
            const lists = await fetchLists();
            if (!hasLoaded) setSplashProgress(40);
            const listsContainer = document.getElementById('lists');
            if (currentListId === null && lists.length > 0) {
                currentListId = lists[0].id;
            }

            const renderListItem = (l) => `
                <div class="list-item ${l.id === currentListId ? 'active' : ''}" data-id="${l.id}">
                    <div>${l.title}</div>
                    <div class="list-actions">
                        <button class="btn btn-small btn-icon" onclick="renameList(${l.id})" title="Sửa"><svg class="icon" viewBox="0 0 24 24"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg></button>
                        <button class="btn btn-danger btn-small btn-icon" onclick="deleteListHandler(${l.id})" title="Xóa"><svg class="icon" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v8h-2V9zm4 0h2v8h-2V9zM7 9h2v8H7V9z"/></svg></button>
                    </div>
                </div>
            `;

            listsContainer.innerHTML = lists.map(renderListItem).join('');

            listsContainer.querySelectorAll('.list-item').forEach(item => {
                item.addEventListener('click', () => {
                    currentListId = parseInt(item.dataset.id);
                    loadBoard();
                });
            });

            const columns = await fetchColumns();
            if (!hasLoaded) setSplashProgress(90);
            const board = document.getElementById('board');
            
            if (!currentListId) {
                board.innerHTML = `
                    <div class="board-toolbar" style="margin-bottom:12px; display:flex; justify-content:flex-end;">
                        <button class="btn btn-primary btn-icon" id="addColumnTop" disabled title="Thêm"><svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg></button>
                    </div>
                    <div style="color:white; font-weight:500;">Chọn hoặc tạo TaskList ở leftbar để thêm cột</div>
                `;
            } else {
                board.innerHTML = `` +
                columns.map(column => renderColumn(column)).join('') + `
                    <div class="add-column" onclick="openModal('addColumnModal')">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <svg class="icon" viewBox="0 0 24 24"><path d="M11 11V5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/></svg>
                            <span>Cột Mới</span>
                        </div>
                    </div>
                `;
                const addTop = document.getElementById('addColumnTop');
                if (addTop) addTop.addEventListener('click', () => openModal('addColumnModal'));
            }
            
            if (!hasLoaded && !nativeSplash) {
                setSplashProgress(100);
                const splash = document.getElementById('splash');
                const elapsed = performance.now() - splashStart;
                const wait = Math.max(0, minSplashMs - elapsed);
                setTimeout(() => {
                    if (splash) {
                        splash.style.opacity = '0';
                        setTimeout(() => { splash.style.display = 'none'; }, 300);
                    }
                }, wait);
                hasLoaded = true;
            }
            document.getElementById('board').style.display = 'flex';
            setupDragAndDrop();
        }

        // Event handlers
        async function deleteColumnHandler(columnId) {
            openConfirmModal('Bạn có chắc chắn muốn xóa cột này? Tất cả công việc trong cột sẽ bị xóa.', async () => {
                if (await deleteColumn(columnId)) {
                    loadBoard();
                }
            });
        }

        async function toggleTaskHandler(taskId) {
            const task = await toggleTask(taskId);
            if (task) {
                loadBoard();
            }
        }

        async function deleteTaskHandler(taskId) {
            openConfirmModal('Bạn có chắc chắn muốn xóa công việc này?', async () => {
                if (await deleteTask(taskId)) {
                    loadBoard();
                }
            });
        }

        function openAddTaskModal(columnId) {
            currentColumnId = columnId;
            document.getElementById('taskColumnId').value = columnId;
            openModal('addTaskModal');
        }

        // Form submissions
        document.getElementById('addColumnForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const title = document.getElementById('columnTitle').value;
            if (!currentListId) {
                showError('Hãy chọn TaskList trước khi thêm cột');
                return;
            }
            if (await createColumn(title)) {
                closeModal('addColumnModal');
                document.getElementById('addColumnForm').reset();
                loadBoard();
            }
        });

        document.getElementById('addTaskForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const title = document.getElementById('taskTitle').value;
            const description = document.getElementById('taskDescription').value;
            if (await createTask(currentColumnId, title, description)) {
                closeModal('addTaskModal');
                document.getElementById('addTaskForm').reset();
                loadBoard();
            }
        });

        // Close modals when clicking outside
        window.onclick = function(event) {
            if (event.target.classList.contains('modal')) {
                event.target.style.display = 'none';
            }
        }

        // Initialize: show splash first, then start loading after first paint
        if (nativeSplash) {
            loadBoard();
        } else {
            requestAnimationFrame(() => {
                setSplashProgress(1);
                setTimeout(() => loadBoard(), 150);
            });
        }
        document.getElementById('addListBtn').addEventListener('click', () => {
            openModal('addListModal');
        });

        window.renameList = (id) => {
            const item = document.querySelector(`.list-item[data-id="${id}"]`);
            const currentTitle = item ? item.querySelector('div').textContent : '';
            document.getElementById('editListId').value = id;
            document.getElementById('editListTitle').value = currentTitle || '';
            openModal('editListModal');
        };

        window.deleteListHandler = async (id) => {
            openConfirmModal('Xóa danh sách này?', async () => {
                if (await deleteList(id)) {
                    currentListId = null;
                    loadBoard();
                }
            });
        };

        document.getElementById('addListForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const title = document.getElementById('listTitle').value;
            const created = await createList(title);
            if (created) {
                currentListId = created.id;
                closeModal('addListModal');
                document.getElementById('addListForm').reset();
                loadBoard();
            }
        });

        document.getElementById('editListForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = parseInt(document.getElementById('editListId').value);
            const title = document.getElementById('editListTitle').value;
            if (await updateList(id, title)) {
                closeModal('editListModal');
                document.getElementById('editListForm').reset();
                loadBoard();
            }
        });

        document.getElementById('confirmCancelBtn').addEventListener('click', (e) => {
            e.preventDefault();
            closeModal('confirmModal');
            confirmAction = null;
        });

        document.getElementById('confirmOkBtn').addEventListener('click', async (e) => {
            e.preventDefault();
            const fn = confirmAction;
            confirmAction = null;
            closeModal('confirmModal');
            if (typeof fn === 'function') {
                await fn();
            }
        });

        function getTaskAfterElement(container, y) {
            const elements = [...container.querySelectorAll('.task:not(.dragging)')];
            return elements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offset = y - box.top - box.height / 2;
                if (offset < 0 && offset > closest.offset) {
                    return { offset: offset, element: child };
                } else {
                    return closest;
                }
            }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
        }

        function getColumnAfterElement(container, x) {
            const elements = [...container.querySelectorAll('.column:not(.dragging)')];
            return elements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offset = x - box.left - box.width / 2;
                if (offset < 0 && offset > closest.offset) {
                    return { offset: offset, element: child };
                } else {
                    return closest;
                }
            }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
        }

        async function reorderColumns(orderedIds) {
            await fetch('/api/columns/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ordered_ids: orderedIds })
            });
        }

        async function reorderTasks(changes) {
            await fetch('/api/tasks/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ changes })
            });
        }

        function setupDragAndDrop() {
            document.querySelectorAll('.task').forEach(task => {
                task.addEventListener('dragstart', e => {
                    task.classList.add('dragging');
                    const sourceColumn = task.closest('.column').dataset.columnId;
                    e.dataTransfer.setData('text/plain', JSON.stringify({ type: 'task', taskId: task.dataset.taskId, sourceColumnId: sourceColumn }));
                });
                task.addEventListener('dragend', () => {
                    task.classList.remove('dragging');
                });
            });

            document.querySelectorAll('.task-list').forEach(list => {
                list.addEventListener('dragover', e => {
                    e.preventDefault();
                    const afterElement = getTaskAfterElement(list, e.clientY);
                    const dragging = document.querySelector('.task.dragging');
                    if (!dragging) return;
                    if (afterElement == null) {
                        list.appendChild(dragging);
                    } else {
                        list.insertBefore(dragging, afterElement);
                    }
                });
                list.addEventListener('drop', async e => {
                    e.preventDefault();
                    const data = JSON.parse(e.dataTransfer.getData('text/plain') || '{}');
                    if (data.type !== 'task') return;
                    const destColumnId = parseInt(list.dataset.columnId);
                    const destTasks = Array.from(list.querySelectorAll('.task')).map(el => parseInt(el.dataset.taskId));
                    const changes = [{ column_id: destColumnId, ordered_ids: destTasks }];
                    const sourceList = document.querySelector(`.task-list[data-column-id="${data.sourceColumnId}"]`);
                    if (sourceList && sourceList !== list) {
                        const sourceTasks = Array.from(sourceList.querySelectorAll('.task')).map(el => parseInt(el.dataset.taskId));
                        changes.push({ column_id: parseInt(data.sourceColumnId), ordered_ids: sourceTasks });
                    }
                    await reorderTasks(changes);
                    loadBoard();
                });
            });

            const board = document.getElementById('board');
            document.querySelectorAll('.column').forEach(column => {
                column.addEventListener('dragstart', () => {
                    column.classList.add('dragging');
                });
                column.addEventListener('dragend', async () => {
                    column.classList.remove('dragging');
                    const orderedIds = Array.from(board.querySelectorAll('.column')).map(el => parseInt(el.dataset.columnId));
                    await reorderColumns(orderedIds);
                    loadBoard();
                });
            });

            board.addEventListener('dragover', e => {
                e.preventDefault();
                const afterElement = getColumnAfterElement(board, e.clientX);
                const dragging = document.querySelector('.column.dragging');
                const addTile = board.querySelector('.add-column');
                if (!dragging) return;
                if (afterElement == null) {
                    board.insertBefore(dragging, addTile);
                } else {
                    board.insertBefore(dragging, afterElement);
                }
            });
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    logo_url = get_logo_data_url()
    return HTML_TEMPLATE.replace('__LOGO_URL__', logo_url)

def _run_server():
    app.run(debug=False, host='127.0.0.1', port=5000, use_reloader=False)

if __name__ == '__main__':
    if webview is None:
        app.run(debug=True, host='0.0.0.0', port=5000)
    else:
        t = threading.Thread(target=_run_server, daemon=True)
        t.start()
        if tk is not None:
            root = tk.Tk()
            root.withdraw()
            splash = tk.Toplevel(root)
            splash.overrideredirect(True)
            cv = tk.Canvas(splash, highlightthickness=0)
            cv.pack(fill=tk.BOTH, expand=True)
            sw, sh = 420, 220
            x = (splash.winfo_screenwidth() - sw) // 2
            y = (splash.winfo_screenheight() - sh) // 3
            splash.geometry(f"{sw}x{sh}+{x}+{y}")
            def hex_to_rgb(h):
                return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
            def rgb_to_hex(rgb):
                return "#%02x%02x%02x" % rgb
            def draw_gradient(canvas, w, h, colors):
                canvas.delete("gradient")
                step = 2
                seg = max(len(colors) - 1, 1)
                for y0 in range(0, h, step):
                    pos = y0 / h
                    idx = min(int(pos * seg), seg - 1)
                    s0 = idx / seg
                    s1 = (idx + 1) / seg
                    t2 = (pos - s0) / (s1 - s0) if s1 > s0 else 0
                    c0 = hex_to_rgb(colors[idx])
                    c1 = hex_to_rgb(colors[idx + 1])
                    r = int(c0[0] * (1 - t2) + c1[0] * t2)
                    g = int(c0[1] * (1 - t2) + c1[1] * t2)
                    b = int(c0[2] * (1 - t2) + c1[2] * t2)
                    canvas.create_rectangle(0, y0, w, y0 + step, outline="", fill=rgb_to_hex((r, g, b)), tags="gradient")
            draw_gradient(cv, sw, sh, ["#0f2027", "#203a43", "#2c5364"]) 
            logo_img = None
            lp = os.path.join(app.static_folder, 'logo.png')
            if os.path.exists(lp):
                try:
                    raw = tk.PhotoImage(file=lp)
                    f = max(1, raw.height() // 96)
                    logo_img = raw.subsample(f, f)
                    cv.create_image(sw // 2, sh // 2 - 20, image=logo_img)
                except Exception:
                    pass
            cv.create_text(sw // 2, sh // 2 + 60, text="Đang tải dữ liệu...", font=("Segoe UI", 12), fill="#ffffff")
            ready = {"ok": False}
            def worker():
                start = time.time()
                min_ms = 1.5
                while time.time() - start < 10:
                    try:
                        with urlopen('http://127.0.0.1:5000/api/tasklists', timeout=2) as r:
                            if r.status == 200:
                                break
                    except Exception:
                        time.sleep(0.2)
                elapsed = time.time() - start
                if elapsed < min_ms:
                    time.sleep(min_ms - elapsed)
                ready["ok"] = True
                try:
                    splash.destroy()
                except Exception:
                    pass
                root.quit()
            threading.Thread(target=worker, daemon=True).start()
            root.mainloop()
        icon_path = os.path.join(app.static_folder, 'app.ico')
        try:
            webview.create_window('TaskList', 'http://127.0.0.1:5000/?nativeSplash=1', width=1200, height=800, icon=icon_path)
        except Exception:
            webview.create_window('TaskList', 'http://127.0.0.1:5000/?nativeSplash=1', width=1200, height=800)
        webview.start()
