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
try:
    from PySide6 import QtWidgets, QtCore, QtGui
except Exception:
    QtWidgets = None
from flask_cors import CORS
import config
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

def _get_mongo_client():
    uri = getattr(config, 'MONGO_URI', None)
    if uri:
        try:
            c = MongoClient(uri, serverSelectionTimeoutMS=3000)
            c.admin.command('ping')
            return c
        except Exception:
            pass
    local_uri = getattr(config, 'MONGO_LOCAL_URI', 'mongodb://localhost:27017')
    return MongoClient(local_uri)

app = Flask(__name__, static_folder=_static_base())
CORS(app)
client = _get_mongo_client()
db_name = getattr(config, 'MONGO_DB', 'tasklist')
mdb = client[db_name]
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
    pass

def qt_ui_main():
    if QtWidgets is None:
        return False
    class TaskWidget(QtWidgets.QWidget):
        toggled = QtCore.Signal(int)
        deleted = QtCore.Signal(int)
        def __init__(self, task, parent=None):
            super().__init__(parent)
            self.task = task
            hb = QtWidgets.QHBoxLayout(self)
            self.cb = QtWidgets.QCheckBox()
            self.cb.setChecked(bool(task.get('completed', False)))
            self.cb.stateChanged.connect(self.on_toggle)
            self.title = QtWidgets.QLabel(task.get('title',''))
            btn = QtWidgets.QPushButton('Xóa')
            btn.setStyleSheet('background:#f44336;color:#fff;border:none;padding:4px 8px;')
            btn.clicked.connect(self.on_delete)
            hb.addWidget(self.cb)
            hb.addWidget(self.title)
            hb.addStretch(1)
            hb.addWidget(btn)
        def on_toggle(self, _):
            self.toggled.emit(self.task['id'])
        def on_delete(self):
            self.deleted.emit(self.task['id'])
    class ColumnWidget(QtWidgets.QGroupBox):
        add_task = QtCore.Signal(int)
        delete_column = QtCore.Signal(int)
        refresh = QtCore.Signal()
        def __init__(self, column, tasks, parent=None):
            super().__init__(parent)
            self.column = column
            self.setTitle(column.get('title',''))
            v = QtWidgets.QVBoxLayout(self)
            hv = QtWidgets.QHBoxLayout()
            btn_add = QtWidgets.QPushButton('Thêm')
            btn_add.setStyleSheet('background:#4CAF50;color:#fff;border:none;padding:4px 8px;')
            btn_add.clicked.connect(lambda: self.add_task.emit(column['id']))
            btn_del = QtWidgets.QPushButton('Xóa cột')
            btn_del.setStyleSheet('background:#f44336;color:#fff;border:none;padding:4px 8px;')
            btn_del.clicked.connect(lambda: self.delete_column.emit(column['id']))
            hv.addWidget(btn_add)
            hv.addWidget(btn_del)
            hv.addStretch(1)
            v.addLayout(hv)
            comp = sum(1 for t in tasks if t.get('completed', False))
            total = len(tasks)
            percent = int(round((comp/total)*100)) if total else 0
            bar = QtWidgets.QProgressBar()
            bar.setRange(0,100)
            bar.setValue(percent)
            v.addWidget(bar)
            lbl = QtWidgets.QLabel(f"{comp}/{total}   {percent}%")
            lbl.setAlignment(QtCore.Qt.AlignRight)
            v.addWidget(lbl)
            for t in tasks:
                tw = TaskWidget(t)
                tw.toggled.connect(self.on_toggle)
                tw.deleted.connect(self.on_delete)
                v.addWidget(tw)
            v.addStretch(1)
        def on_toggle(self, tid):
            tasks_col.update_one({'id': tid}, {'$set': {'completed': not tasks_col.find_one({'id': tid}).get('completed', False), 'updated_at': datetime.utcnow()}})
            self.refresh.emit()
        def on_delete(self, tid):
            tasks_col.delete_one({'id': tid})
            self.refresh.emit()
    class Main(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('TaskList')
            self.resize(1200,800)
            try:
                import base64 as _b64
                icon_data = getattr(__import__('config'), 'APP_ICON', None)
                logo_data = getattr(__import__('config'), 'LOGO', None)
                if icon_data:
                    pix = QtGui.QPixmap()
                    if pix.loadFromData(_b64.b64decode(icon_data)):
                        ic = QtGui.QIcon(pix)
                        self.setWindowIcon(ic)
                elif logo_data:
                    pix = QtGui.QPixmap()
                    if pix.loadFromData(_b64.b64decode(logo_data)):
                        self.setWindowIcon(QtGui.QIcon(pix))
            except Exception:
                pass
            cen = QtWidgets.QWidget()
            self.setCentralWidget(cen)
            v = QtWidgets.QVBoxLayout(cen)
            self.banner = QtWidgets.QLabel('TaskList')
            self.banner.setAlignment(QtCore.Qt.AlignCenter)
            self.banner.setStyleSheet('background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #667eea, stop:1 #764ba2); color:#fff; font-size:24px; font-weight:bold; padding:18px;')
            v.addWidget(self.banner)
            h = QtWidgets.QHBoxLayout()
            v.addLayout(h,1)
            left = QtWidgets.QWidget()
            left.setStyleSheet('background:#1f2937; color:#e5e7eb;')
            left.setMinimumWidth(280)
            lv = QtWidgets.QVBoxLayout(left)
            lhdr = QtWidgets.QHBoxLayout()
            title = QtWidgets.QLabel('Danh sách')
            title.setStyleSheet('color:#fff; font-weight:700;')
            self.btn_add_list = QtWidgets.QPushButton('+')
            self.btn_add_list.setStyleSheet('background:#2563eb;color:#fff;')
            lhdr.addWidget(title)
            lhdr.addStretch(1)
            lhdr.addWidget(self.btn_add_list)
            lv.addLayout(lhdr)
            self.lists = QtWidgets.QListWidget()
            self.lists.setStyleSheet('background:#374151; color:#e5e7eb;')
            lv.addWidget(self.lists,1)
            la = QtWidgets.QHBoxLayout()
            self.btn_rename = QtWidgets.QPushButton('Sửa')
            self.btn_delete = QtWidgets.QPushButton('Xóa')
            self.btn_rename.setStyleSheet('background:#374151;color:#e5e7eb;')
            self.btn_delete.setStyleSheet('background:#f44336;color:#fff;')
            la.addWidget(self.btn_rename)
            la.addWidget(self.btn_delete)
            lv.addLayout(la)
            self.board_scroll = QtWidgets.QScrollArea()
            self.board_scroll.setWidgetResizable(True)
            board = QtWidgets.QWidget()
            self.board = board
            self.board_layout = QtWidgets.QHBoxLayout(board)
            self.board_layout.addStretch(1)
            self.board_scroll.setWidget(board)
            h.addWidget(left)
            h.addWidget(self.board_scroll,1)
            tb = QtWidgets.QHBoxLayout()
            self.btn_add_column = QtWidgets.QPushButton('Thêm cột')
            self.btn_add_column.setStyleSheet('background:#4CAF50;color:#fff;')
            tb.addStretch(1)
            tb.addWidget(self.btn_add_column)
            v.addLayout(tb)
            self.current_list_id = None
            self.btn_add_list.clicked.connect(self.add_list)
            self.btn_rename.clicked.connect(self.rename_list)
            self.btn_delete.clicked.connect(self.delete_list)
            self.btn_add_column.clicked.connect(self.add_column)
            self.lists.itemSelectionChanged.connect(self.on_select_list)
            self.reload_lists()
        def reload_lists(self):
            self.lists.clear()
            ls = list(tasklists_col.find({}).sort('created_at', 1))
            for l in ls:
                it = QtWidgets.QListWidgetItem(f"{l['id']}|{l.get('title','')}")
                self.lists.addItem(it)
            if ls:
                if self.current_list_id is None:
                    self.current_list_id = ls[0]['id']
                for i,l in enumerate(ls):
                    if l['id'] == self.current_list_id:
                        self.lists.setCurrentRow(i)
                        break
            self.reload_board()
        def on_select_list(self):
            it = self.lists.currentItem()
            if not it:
                return
            try:
                self.current_list_id = int(it.text().split('|',1)[0])
            except Exception:
                self.current_list_id = None
            self.reload_board()
        def reload_board(self):
            for i in reversed(range(self.board_layout.count()-1)):
                w = self.board_layout.itemAt(i).widget()
                if w:
                    w.setParent(None)
            if not self.current_list_id:
                return
            cols = list(columns_col.find({'task_list_id': self.current_list_id}).sort('position', 1))
            for c in cols:
                ts = list(tasks_col.find({'column_id': c['id']}).sort([('completed', 1), ('position', 1)]))
                cw = ColumnWidget(c, ts)
                cw.add_task.connect(self.add_task)
                cw.delete_column.connect(self.delete_column)
                cw.refresh.connect(self.reload_board)
                self.board_layout.insertWidget(self.board_layout.count()-1, cw)
        def add_list(self):
            title, ok = QtWidgets.QInputDialog.getText(self, 'Danh sách', 'Tên danh sách:')
            if not ok or not title:
                return
            new_id = next_id(tasklists_col)
            doc = {'id': new_id, 'title': title, 'created_at': datetime.utcnow()}
            tasklists_col.insert_one(doc)
            self.current_list_id = new_id
            self.reload_lists()
        def rename_list(self):
            it = self.lists.currentItem()
            if not it:
                return
            lid = int(it.text().split('|',1)[0])
            title, ok = QtWidgets.QInputDialog.getText(self, 'Sửa', 'Tên danh sách:')
            if not ok or not title:
                return
            tasklists_col.update_one({'id': lid}, {'$set': {'title': title}})
            self.reload_lists()
        def delete_list(self):
            it = self.lists.currentItem()
            if not it:
                return
            lid = int(it.text().split('|',1)[0])
            m = QtWidgets.QMessageBox.question(self, 'Xác nhận', 'Xóa danh sách này?')
            if m != QtWidgets.QMessageBox.Yes:
                return
            col_ids = [c['id'] for c in columns_col.find({'task_list_id': lid})]
            tasks_col.delete_many({'column_id': {'$in': col_ids}})
            columns_col.delete_many({'task_list_id': lid})
            tasklists_col.delete_one({'id': lid})
            self.current_list_id = None
            self.reload_lists()
        def add_column(self):
            if not self.current_list_id:
                return
            title, ok = QtWidgets.QInputDialog.getText(self, 'Cột', 'Tiêu đề cột:')
            if not ok or not title:
                return
            last = columns_col.find_one({'task_list_id': self.current_list_id}, sort=[('position', -1)])
            pos = (last['position'] + 1) if last else 1
            new_id = next_id(columns_col)
            doc = {'id': new_id, 'title': title, 'position': pos, 'created_at': datetime.utcnow(), 'task_list_id': self.current_list_id}
            columns_col.insert_one(doc)
            self.reload_board()
        def add_task(self, cid):
            title, ok = QtWidgets.QInputDialog.getText(self, 'Công việc', 'Tiêu đề công việc:')
            if not ok:
                return
            desc, ok2 = QtWidgets.QInputDialog.getText(self, 'Công việc', 'Mô tả:')
            if not ok2:
                return
            last = tasks_col.find_one({'column_id': cid}, sort=[('position', -1)])
            pos = (last['position'] + 1) if last else 1
            new_id = next_id(tasks_col)
            now = datetime.utcnow()
            doc = {'id': new_id, 'title': title or 'New Task', 'description': desc or '', 'completed': False, 'position': pos, 'column_id': cid, 'created_at': now, 'updated_at': now}
            tasks_col.insert_one(doc)
            self.reload_board()
        def delete_column(self, cid):
            m = QtWidgets.QMessageBox.question(self, 'Xác nhận', 'Xóa cột này?')
            if m != QtWidgets.QMessageBox.Yes:
                return
            tasks_col.delete_many({'column_id': cid})
            columns_col.delete_one({'id': cid})
            self.reload_board()
    appq = QtWidgets.QApplication(sys.argv)
    try:
        import base64 as _b64
        icon_data = getattr(__import__('config'), 'APP_ICON', None)
        if icon_data:
            p = QtGui.QPixmap()
            if p.loadFromData(_b64.b64decode(icon_data)):
                appq.setWindowIcon(QtGui.QIcon(p))
    except Exception:
        pass
    w = Main()
    w.show()
    appq.exec()
    return True

if __name__ == '__main__':
    ran = qt_ui_main()
    if not ran:
        try:
            import tkinter as tk
            def python_ui_main():
                root = tk.Tk()
                root.title('TaskList')
                try:
                    logo_img = tk.PhotoImage(data=getattr(__import__('config'), 'LOGO', ''))
                    root.iconphoto(True, logo_img)
                except Exception:
                    pass
                tk.Label(root, text='PySide6 chưa sẵn sàng, đang dùng UI cơ bản', font=('Segoe UI', 12)).pack(padx=20, pady=20)
                root.mainloop()
            python_ui_main()
        except Exception:
            pass
