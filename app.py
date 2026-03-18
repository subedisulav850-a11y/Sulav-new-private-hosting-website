import os
import subprocess
import psutil
import json
import secrets
import shutil
import threading
import time
import hashlib
import zipfile
import sys
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, send_from_directory, render_template_string, send_file

# ==================== Auto Requirements Checker ====================
REQUIRED_PACKAGES = [
    'flask==2.3.3',
    'psutil==5.9.5',
    'gunicorn==21.2.0'
]

def check_and_install_requirements():
    """Check if all required packages are installed, install if missing"""
    print("="*60)
    print("🔍 CHECKING REQUIREMENTS")
    print("="*60)
    
    def check_package_installed(package_name):
        """Simple check if package is installed by trying to import it"""
        try:
            if package_name == 'psutil':
                import psutil
            elif package_name == 'flask':
                import flask
            elif package_name == 'gunicorn':
                try:
                    result = subprocess.run(['gunicorn', '--version'], 
                                          capture_output=True, 
                                          text=True, 
                                          timeout=2)
                    return result.returncode == 0
                except:
                    return False
            return True
        except ImportError:
            return False
        except:
            return False
    
    missing_packages = []
    
    for requirement in REQUIRED_PACKAGES:
        package_name = requirement.split('==')[0]
        if not check_package_installed(package_name):
            missing_packages.append(requirement)
            print(f"❌ {requirement} - MISSING")
        else:
            print(f"✅ {requirement} - OK")
    
    if missing_packages:
        print("\n" + "="*60)
        print("📦 INSTALLING MISSING PACKAGES")
        print("="*60)
        
        for package in missing_packages:
            try:
                print(f"Installing {package}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✅ Successfully installed {package}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to install {package}: {e}")
        
        print("\n" + "="*60)
        print("✅ ALL REQUIREMENTS INSTALLED")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("✅ ALL REQUIREMENTS SATISFIED")
        print("="*60)
    
    print("\n" + "="*60)
    print("🚀 STARTING APPLICATION")
    print("="*60 + "\n")

# Run requirements check before starting app
check_and_install_requirements()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)

# Directory structure
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "data/bots")
LOG_DIR = os.path.join(BASE_DIR, "data/logs")
CONFIG_DIR = os.path.join(BASE_DIR, "data/config")
BACKUP_DIR = os.path.join(BASE_DIR, "data/backups")
TEMP_DIR = os.path.join(BASE_DIR, "data/temp")

for dir_path in [UPLOAD_DIR, LOG_DIR, CONFIG_DIR, BACKUP_DIR, TEMP_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Config files
USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
UPLOADS_FILE = os.path.join(CONFIG_DIR, "uploads.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
ACTIVITY_FILE = os.path.join(CONFIG_DIR, "activity.json")

# Default settings
DEFAULT_SETTINGS = {
    "global_upload_limit": 10,
    "max_file_size": 100,
    "allowed_extensions": [".py", ".js", ".sh", ".txt", ".zip"],
    "maintenance_mode": False,
    "maintenance_message": "🚧 System under maintenance",
    "max_bots_per_user": 5
}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ==================== File Operations ====================

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def load_uploads():
    try:
        with open(UPLOADS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_uploads(uploads):
    with open(UPLOADS_FILE, 'w') as f:
        json.dump(uploads, f, indent=2)

def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except:
        return DEFAULT_SETTINGS

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def load_activity():
    try:
        with open(ACTIVITY_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_activity(activity):
    with open(ACTIVITY_FILE, 'w') as f:
        json.dump(activity[-100:], f, indent=2)

# Initialize default admin
def init_config():
    if not os.path.exists(USERS_FILE):
        default_users = {
            "admin": {
                "password": hash_password("Admin@123"),
                "is_admin": True,
                "upload_limit": 1000,
                "max_bots": 50,
                "created_at": datetime.now().isoformat(),
                "status": "active"
            },
            "sulav": {
                "password": hash_password("SulavPapa123"),
                "is_admin": True,
                "upload_limit": 500,
                "max_bots": 30,
                "created_at": datetime.now().isoformat(),
                "status": "active",
                "notes": "👑 Owner"
            }
        }
        save_users(default_users)

init_config()

# Running bots
running_bots = {}
bot_processes = {}

# ==================== Helper Functions ====================

def log_activity(username, action, details, ip=None):
    activity = load_activity()
    activity.append({
        'username': username,
        'action': action,
        'details': details,
        'ip': ip or 'Unknown',
        'timestamp': datetime.now().isoformat()
    })
    save_activity(activity)

def get_user_upload_count(username):
    uploads = load_uploads()
    return len(uploads.get(username, []))

def get_user_upload_limit(username):
    users = load_users()
    user = users.get(username, {})
    return user.get('upload_limit', load_settings()['global_upload_limit'])

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def start_bot(filename, username):
    user_dir = os.path.join(UPLOAD_DIR, username)
    filepath = os.path.join(user_dir, filename)
    
    if not os.path.exists(filepath):
        return None, "File not found"
    
    bot_log_dir = os.path.join(LOG_DIR, username)
    os.makedirs(bot_log_dir, exist_ok=True)
    
    log_path = os.path.join(bot_log_dir, f"{filename}.log")
    log_file = open(log_path, "a")
    
    log_file.write(f"\n{'='*50}\n")
    log_file.write(f"Bot started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"{'='*50}\n\n")
    log_file.flush()
    
    try:
        proc = subprocess.Popen(
            ["python", filepath],
            stdout=log_file,
            stderr=log_file,
            text=True
        )
        
        bot_id = f"{username}_{filename}_{int(time.time())}"
        running_bots[bot_id] = {
            "filename": filename,
            "username": username,
            "start_time": datetime.now().isoformat(),
            "log_path": log_path,
            "pid": proc.pid
        }
        bot_processes[bot_id] = proc
        
        log_activity(username, 'start_bot', f'Started bot: {filename}')
        return bot_id, "Bot started"
    except Exception as e:
        return None, str(e)

def stop_bot(bot_id):
    if bot_id not in running_bots:
        return False, "Bot not found"
    
    try:
        proc = bot_processes.get(bot_id)
        if proc:
            proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
        
        bot = running_bots[bot_id]
        with open(bot['log_path'], 'a') as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*50}\n\n")
        
        log_activity(bot['username'], 'stop_bot', f'Stopped bot: {bot["filename"]}')
        
        del running_bots[bot_id]
        if bot_id in bot_processes:
            del bot_processes[bot_id]
        
        return True, "Bot stopped"
    except Exception as e:
        return False, str(e)

# ==================== Decorators ====================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        users = load_users()
        if not users.get(session['user_id'], {}).get('is_admin'):
            return jsonify({"error": "Admin required"}), 403
        return f(*args, **kwargs)
    return decorated

# ==================== HTML Templates ====================

LOGIN_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sulav Hosting - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, sans-serif; }
        body { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-box { background: white; border-radius: 20px; padding: 40px; width: 90%; max-width: 400px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }
        h1 { text-align: center; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 30px; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 16px; }
        button { width: 100%; padding: 12px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }
        .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 8px; margin: 10px 0; display: none; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>Sulav Hosting</h1>
        <div id="error" class="error"></div>
        <input type="text" id="username" placeholder="Username">
        <input type="password" id="password" placeholder="Password">
        <button onclick="login()">Login</button>
    </div>
    <script>
        async function login() {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password})
            });
            
            const data = await res.json();
            if (res.ok) {
                window.location.href = data.redirect;
            } else {
                document.getElementById('error').style.display = 'block';
                document.getElementById('error').textContent = data.error;
            }
        }
    </script>
</body>
</html>
'''

DASHBOARD_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sulav Hosting - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: #f5f5f5; }
        
        /* Navbar */
        .navbar { background: white; padding: 1rem 2rem; box-shadow: 0 2px 10px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
        .logo { font-size: 1.5rem; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .nav-links { display: flex; gap: 20px; }
        .nav-link { cursor: pointer; padding: 8px 15px; border-radius: 8px; transition: all 0.3s; }
        .nav-link:hover { background: #f0f0f0; }
        .nav-link.active { background: #667eea; color: white; }
        .user-info { display: flex; align-items: center; gap: 20px; }
        .logout-btn { padding: 8px 20px; background: #f44336; color: white; border: none; border-radius: 8px; cursor: pointer; }
        
        /* Container */
        .container { max-width: 1400px; margin: 2rem auto; padding: 0 2rem; }
        
        /* Stats Grid */
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 15px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 20px; }
        .stat-icon { width: 60px; height: 60px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 2rem; }
        .stat-icon.blue { background: #e3f2fd; color: #1976d2; }
        .stat-icon.green { background: #e8f5e9; color: #388e3c; }
        .stat-icon.purple { background: #f3e5f5; color: #7b1fa2; }
        .stat-icon.orange { background: #fff3e0; color: #f57c00; }
        .stat-info h3 { color: #666; font-size: 0.9rem; margin-bottom: 5px; }
        .stat-info .value { font-size: 2rem; font-weight: bold; color: #333; }
        
        /* Sections */
        .section { background: white; border-radius: 15px; padding: 25px; margin-bottom: 30px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }
        .section-title { font-size: 1.3rem; color: #333; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
        
        /* Upload Area */
        .upload-area { border: 2px dashed #667eea; border-radius: 10px; padding: 40px; text-align: center; cursor: pointer; transition: all 0.3s; background: #f8f9ff; }
        .upload-area:hover { background: #e8eaff; }
        .upload-icon { font-size: 3rem; color: #667eea; margin-bottom: 15px; }
        
        /* File List */
        .file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; margin-top: 20px; }
        .file-card { background: #f8f9fa; border-radius: 10px; padding: 15px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #e0e0e0; }
        .file-name { font-weight: 600; color: #333; margin-bottom: 5px; word-break: break-all; }
        .file-meta { font-size: 0.8rem; color: #999; }
        .file-actions { display: flex; gap: 5px; }
        
        /* Buttons */
        .btn { padding: 8px 15px; border: none; border-radius: 5px; cursor: pointer; font-weight: 500; transition: all 0.3s; }
        .btn-sm { padding: 5px 10px; font-size: 0.8rem; }
        .btn-primary { background: #667eea; color: white; }
        .btn-primary:hover { background: #5a67d8; }
        .btn-success { background: #48bb78; color: white; }
        .btn-success:hover { background: #38a169; }
        .btn-danger { background: #f56565; color: white; }
        .btn-danger:hover { background: #e53e3e; }
        .btn-warning { background: #ed8936; color: white; }
        .btn-info { background: #4299e1; color: white; }
        
        /* Log Box */
        .log-box { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 10px; font-family: 'Courier New', monospace; height: 400px; overflow-y: auto; white-space: pre-wrap; margin: 20px 0; font-size: 0.9rem; }
        .log-controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .log-controls select { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 5px; min-width: 200px; }
        
        /* Bot List */
        .bot-list { margin-top: 20px; }
        .bot-item { background: #f8f9fa; border-radius: 10px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #e0e0e0; }
        .status-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; }
        .status-running { background: #e8f5e9; color: #388e3c; }
        .status-stopped { background: #ffebee; color: #d32f2f; }
        
        /* Alert */
        .alert { position: fixed; top: 20px; right: 20px; padding: 15px 25px; border-radius: 10px; display: none; animation: slideIn 0.3s; z-index: 1000; }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        .alert-success { background: #c6f6d5; color: #22543d; border-left: 4px solid #48bb78; }
        .alert-error { background: #fed7d7; color: #742a2a; border-left: 4px solid #f56565; }
        
        /* Modal */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); align-items: center; justify-content: center; z-index: 1000; }
        .modal-content { background: white; border-radius: 15px; padding: 25px; max-width: 500px; width: 90%; }
        .modal-title { font-size: 1.3rem; color: #333; margin-bottom: 15px; }
        .modal-body { margin-bottom: 20px; }
        .modal-footer { display: flex; gap: 10px; justify-content: flex-end; }
        
        /* Admin Table */
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 12px; background: #f8f9fa; font-weight: 600; }
        td { padding: 12px; border-bottom: 1px solid #e2e8f0; }
        tr:hover { background: #f8f9fa; }
        input[type="number"] { padding: 5px; border: 1px solid #ddd; border-radius: 4px; width: 70px; }
        
        /* Progress Bar */
        .progress-bar { width: 100%; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); transition: width 0.3s; }
        
        /* Maintenance Banner */
        .maintenance-banner { background: #fed7d7; color: #742a2a; padding: 10px 20px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        
        @media (max-width: 768px) {
            .navbar { flex-direction: column; gap: 10px; }
            .nav-links { flex-wrap: wrap; justify-content: center; }
            .stats-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div id="maintenanceBanner" class="maintenance-banner" style="display: none;">
        <span>🚧 <span id="maintenanceMessage">System under maintenance</span></span>
        <button class="btn btn-sm btn-danger" onclick="this.parentElement.style.display='none'">Dismiss</button>
    </div>

    <nav class="navbar">
        <div class="logo">Sulav Hosting</div>
        <div class="nav-links">
            <span class="nav-link active" onclick="showSection('dashboard')">Dashboard</span>
            <span class="nav-link" onclick="showSection('files')">Files</span>
            <span class="nav-link" onclick="showSection('bots')">Bots</span>
            <span class="nav-link" onclick="showSection('logs')">Logs</span>
            <span class="nav-link" id="adminLink" style="display:none;" onclick="showSection('admin')">Admin</span>
        </div>
        <div class="user-info">
            <span id="usernameDisplay"></span>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </div>
    </nav>

    <div class="container">
        <div id="alert" class="alert"></div>

        <!-- Dashboard Section -->
        <div id="dashboardSection">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon blue">📁</div>
                    <div class="stat-info">
                        <h3>Files Uploaded</h3>
                        <div class="value" id="uploadCount">0</div>
                        <div id="uploadLimit"></div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon green">🤖</div>
                    <div class="stat-info">
                        <h3>Running Bots</h3>
                        <div class="value" id="runningCount">0</div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon purple">💾</div>
                    <div class="stat-info">
                        <h3>Storage Used</h3>
                        <div class="value" id="storageUsed">0 MB</div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon orange">⚡</div>
                    <div class="stat-info">
                        <h3>System CPU</h3>
                        <div class="value" id="systemCpu">0%</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Files Section -->
        <div id="filesSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">📤 Upload Bot</h2>
                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">📁</div>
                    <p>Click to upload or drag and drop</p>
                    <p style="color: #999; font-size: 0.9rem;">Supported: .py, .js, .sh, .zip</p>
                    <input type="file" id="fileInput" style="display: none;" onchange="uploadFile()">
                </div>
                <div id="uploadProgress" class="progress-bar">
                    <div class="progress-fill" id="uploadProgressFill"></div>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">📁 My Files</h2>
                <div id="fileList" class="file-grid">Loading...</div>
            </div>
        </div>

        <!-- Bots Section -->
        <div id="botsSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">🤖 Running Bots</h2>
                <div id="botList" class="bot-list">Loading...</div>
            </div>
        </div>

        <!-- Logs Section -->
        <div id="logsSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">📋 View Logs</h2>
                <div class="log-controls">
                    <select id="logFileSelect">
                        <option value="">Select a file</option>
                    </select>
                    <button class="btn btn-primary" onclick="loadLogs()">View</button>
                    <button class="btn btn-warning" onclick="refreshLogs()">Refresh</button>
                </div>
                <div id="logBox" class="log-box">Select a file to view logs</div>
            </div>
        </div>

        <!-- Admin Section -->
        <div id="adminSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">👥 User Management</h2>
                <button class="btn btn-primary" onclick="addUser()" style="margin-bottom: 20px;">+ Add User</button>
                <div id="userList"></div>
            </div>
            
            <div class="section">
                <h2 class="section-title">📊 User Files</h2>
                <div id="userFilesList"></div>
            </div>
            
            <div class="section">
                <h2 class="section-title">⚙️ Settings</h2>
                <div style="margin-bottom: 15px;">
                    <label>Maintenance Mode:</label>
                    <select id="maintenanceMode" style="width:100%; padding:10px;">
                        <option value="false">Off</option>
                        <option value="true">On</option>
                    </select>
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Maintenance Message:</label>
                    <input type="text" id="maintenanceMessageInput" style="width:100%; padding:10px;">
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Global Upload Limit:</label>
                    <input type="number" id="globalUploadLimit" style="width:100%; padding:10px;">
                </div>
                <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
            </div>

            <div class="section">
                <h2 class="section-title">📝 Activity Log</h2>
                <div id="activityLog" style="max-height: 400px; overflow-y: auto;"></div>
            </div>
        </div>
    </div>

    <!-- Add User Modal -->
    <div id="userModal" class="modal">
        <div class="modal-content">
            <h3 class="modal-title">Add New User</h3>
            <div class="modal-body">
                <input type="text" id="newUsername" placeholder="Username" style="width:100%; padding:10px; margin-bottom:10px;">
                <input type="password" id="newPassword" placeholder="Password" style="width:100%; padding:10px; margin-bottom:10px;">
                <input type="number" id="newLimit" placeholder="Upload Limit" style="width:100%; padding:10px;">
            </div>
            <div class="modal-footer">
                <button class="btn btn-danger" onclick="hideModal()">Cancel</button>
                <button class="btn btn-primary" onclick="createUser()">Create</button>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;
        let isAdmin = false;
        let refreshInterval = null;
        let selectedFile = null;

        document.addEventListener('DOMContentLoaded', () => {
            loadUserData();
            startRefreshInterval();
            checkMaintenance();
        });

        function showSection(section) {
            document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            
            document.getElementById('dashboardSection').style.display = 'none';
            document.getElementById('filesSection').style.display = 'none';
            document.getElementById('botsSection').style.display = 'none';
            document.getElementById('logsSection').style.display = 'none';
            document.getElementById('adminSection').style.display = 'none';
            
            document.getElementById(section + 'Section').style.display = 'block';
            
            if (section === 'files') loadFiles();
            if (section === 'bots') loadBots();
            if (section === 'logs') loadLogFileList();
            if (section === 'admin' && isAdmin) loadAdminData();
        }

        async function checkMaintenance() {
            const res = await fetch('/api/settings');
            const data = await res.json();
            if (data.maintenance_mode) {
                document.getElementById('maintenanceBanner').style.display = 'flex';
                document.getElementById('maintenanceMessage').textContent = data.maintenance_message;
            }
        }

        async function loadUserData() {
            try {
                const res = await fetch('/api/user/stats');
                const data = await res.json();
                
                if (res.ok) {
                    currentUser = data;
                    isAdmin = data.is_admin;
                    document.getElementById('usernameDisplay').textContent = data.username;
                    document.getElementById('uploadCount').textContent = data.upload_count;
                    document.getElementById('uploadLimit').textContent = `Limit: ${data.upload_limit}`;
                    document.getElementById('runningCount').textContent = data.running_bots?.length || 0;
                    document.getElementById('storageUsed').textContent = formatSize(data.total_size || 0);
                    
                    if (isAdmin) {
                        document.getElementById('adminLink').style.display = 'inline';
                    }
                    
                    loadSystemStats();
                }
            } catch (error) {
                showAlert('Failed to load user data', 'error');
            }
        }

        async function loadSystemStats() {
            try {
                const res = await fetch('/api/system');
                const data = await res.json();
                document.getElementById('systemCpu').textContent = data.cpu + '%';
            } catch (error) {}
        }

        async function loadFiles() {
            try {
                const res = await fetch('/api/user/stats');
                const data = await res.json();
                
                if (!data.uploads || data.uploads.length === 0) {
                    document.getElementById('fileList').innerHTML = '<p style="color:#999;">No files uploaded yet.</p>';
                    return;
                }
                
                let html = '';
                data.uploads.forEach(file => {
                    html += `
                        <div class="file-card">
                            <div>
                                <div class="file-name">${file.filename}</div>
                                <div class="file-meta">${formatSize(file.size)} • ${new Date(file.uploaded_at).toLocaleString()}</div>
                            </div>
                            <div class="file-actions">
                                <button class="btn btn-sm btn-success" onclick="startBot('${file.filename}')">Start</button>
                                <button class="btn btn-sm btn-danger" onclick="deleteFile('${file.filename}')">Delete</button>
                            </div>
                        </div>
                    `;
                });
                
                document.getElementById('fileList').innerHTML = html;
            } catch (error) {
                document.getElementById('fileList').innerHTML = 'Failed to load files';
            }
        }

        async function loadBots() {
            try {
                const res = await fetch('/api/user/stats');
                const data = await res.json();
                
                if (!data.running_bots || data.running_bots.length === 0) {
                    document.getElementById('botList').innerHTML = '<p style="color:#999;">No bots running.</p>';
                    return;
                }
                
                let html = '';
                data.running_bots.forEach(bot => {
                    html += `
                        <div class="bot-item">
                            <div>
                                <strong>${bot.filename}</strong><br>
                                <small>Started: ${new Date(bot.start_time).toLocaleString()}</small>
                            </div>
                            <div>
                                <span class="status-badge status-running">● Running</span>
                                <button class="btn btn-sm btn-danger" onclick="stopBot('${bot.id}')">Stop</button>
                            </div>
                        </div>
                    `;
                });
                
                document.getElementById('botList').innerHTML = html;
            } catch (error) {
                document.getElementById('botList').innerHTML = 'Failed to load bots';
            }
        }

        function loadLogFileList() {
            if (!currentUser?.uploads) return;
            
            let options = '<option value="">Select a file</option>';
            currentUser.uploads.forEach(file => {
                options += `<option value="${file.filename}">${file.filename}</option>`;
            });
            document.getElementById('logFileSelect').innerHTML = options;
        }

        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            if (!file) return;
            
            const formData = new FormData();
            formData.append('file', file);
            
            document.getElementById('uploadProgress').style.display = 'block';
            
            try {
                const res = await fetch('/api/user/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    showAlert('File uploaded!', 'success');
                    fileInput.value = '';
                    loadUserData();
                    loadFiles();
                } else {
                    showAlert(data.error || 'Upload failed', 'error');
                }
            } catch (error) {
                showAlert('Upload failed', 'error');
            } finally {
                document.getElementById('uploadProgress').style.display = 'none';
            }
        }

        async function startBot(filename) {
            try {
                const res = await fetch('/api/user/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ filename })
                });
                
                if (res.ok) {
                    showAlert('Bot started!', 'success');
                    loadBots();
                    loadUserData();
                } else {
                    const data = await res.json();
                    showAlert(data.error || 'Failed to start', 'error');
                }
            } catch (error) {
                showAlert('Failed to start bot', 'error');
            }
        }

        async function stopBot(botId) {
            if (!confirm('Stop this bot?')) return;
            
            try {
                const res = await fetch('/api/user/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ bot_id: botId })
                });
                
                if (res.ok) {
                    showAlert('Bot stopped!', 'success');
                    loadBots();
                    loadUserData();
                }
            } catch (error) {
                showAlert('Failed to stop bot', 'error');
            }
        }

        async function deleteFile(filename) {
            if (!confirm(`Delete ${filename}?`)) return;
            
            try {
                const res = await fetch('/api/user/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ filename })
                });
                
                if (res.ok) {
                    showAlert('File deleted!', 'success');
                    loadUserData();
                    loadFiles();
                }
            } catch (error) {
                showAlert('Delete failed', 'error');
            }
        }

        async function loadLogs() {
            const filename = document.getElementById('logFileSelect').value;
            if (!filename) {
                showAlert('Select a file', 'error');
                return;
            }
            
            try {
                const res = await fetch(`/api/user/logs/${filename}`);
                const logs = await res.text();
                document.getElementById('logBox').textContent = logs || 'No logs available';
            } catch (error) {
                document.getElementById('logBox').textContent = 'Failed to load logs';
            }
        }

        function refreshLogs() {
            loadLogs();
        }

        async function loadAdminData() {
            try {
                const res = await fetch('/api/admin/stats');
                const data = await res.json();
                
                // User list
                let userHtml = '<table><tr><th>Username</th><th>Role</th><th>Files</th><th>Limit</th><th>Actions</th></tr>';
                data.users.forEach(user => {
                    userHtml += `
                        <tr>
                            <td>${user.username}</td>
                            <td>${user.is_admin ? 'Admin' : 'User'}</td>
                            <td>${user.upload_count}/${user.upload_limit}</td>
                            <td><input type="number" id="limit_${user.username}" value="${user.upload_limit}" style="width:70px;"></td>
                            <td>
                                <button class="btn btn-sm btn-primary" onclick="updateUserLimit('${user.username}')">Update</button>
                                ${!user.is_admin ? `<button class="btn btn-sm btn-danger" onclick="deleteUser('${user.username}')">Delete</button>` : ''}
                            </td>
                        </tr>
                    `;
                });
                userHtml += '</table>';
                document.getElementById('userList').innerHTML = userHtml;
                
                // User files
                let filesHtml = '<table><tr><th>Username</th><th>Files</th><th>Action</th></tr>';
                for (const [username, files] of Object.entries(data.user_uploads)) {
                    filesHtml += `
                        <tr>
                            <td>${username}</td>
                            <td>${files.length} files</td>
                            <td><button class="btn btn-sm btn-info" onclick="viewUserFiles('${username}')">View</button></td>
                        </tr>
                    `;
                }
                filesHtml += '</table>';
                document.getElementById('userFilesList').innerHTML = filesHtml;
                
                // Settings
                document.getElementById('maintenanceMode').value = data.settings.maintenance_mode ? 'true' : 'false';
                document.getElementById('maintenanceMessageInput').value = data.settings.maintenance_message || '';
                document.getElementById('globalUploadLimit').value = data.settings.global_upload_limit;
                
                // Activity log
                let activityHtml = '<table><tr><th>Time</th><th>User</th><th>Action</th><th>IP</th></tr>';
                data.activity.forEach(act => {
                    activityHtml += `
                        <tr>
                            <td>${new Date(act.timestamp).toLocaleString()}</td>
                            <td>${act.username}</td>
                            <td>${act.action} - ${act.details}</td>
                            <td>${act.ip}</td>
                        </tr>
                    `;
                });
                activityHtml += '</table>';
                document.getElementById('activityLog').innerHTML = activityHtml;
            } catch (error) {
                console.error('Failed to load admin data');
            }
        }

        async function updateUserLimit(username) {
            const limit = document.getElementById(`limit_${username}`).value;
            
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, upload_limit: parseInt(limit) })
                });
                
                if (res.ok) {
                    showAlert('User limit updated!', 'success');
                }
            } catch (error) {}
        }

        async function deleteUser(username) {
            if (!confirm(`Delete user ${username}?`)) return;
            
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username })
                });
                
                if (res.ok) {
                    showAlert('User deleted!', 'success');
                    loadAdminData();
                }
            } catch (error) {}
        }

        function viewUserFiles(username) {
            window.open(`/api/admin/user-files/${username}`, '_blank');
        }

        function addUser() {
            document.getElementById('userModal').style.display = 'flex';
        }

        async function createUser() {
            const username = document.getElementById('newUsername').value;
            const password = document.getElementById('newPassword').value;
            const limit = document.getElementById('newLimit').value || 10;
            
            if (!username || !password) {
                showAlert('Username and password required', 'error');
                return;
            }
            
            try {
                const res = await fetch('/api/admin/users', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password, upload_limit: parseInt(limit) })
                });
                
                if (res.ok) {
                    showAlert('User created!', 'success');
                    hideModal();
                    loadAdminData();
                } else {
                    const data = await res.json();
                    showAlert(data.error || 'Failed to create user', 'error');
                }
            } catch (error) {
                showAlert('Failed to create user', 'error');
            }
        }

        async function saveSettings() {
            const settings = {
                maintenance_mode: document.getElementById('maintenanceMode').value === 'true',
                maintenance_message: document.getElementById('maintenanceMessageInput').value,
                global_upload_limit: parseInt(document.getElementById('globalUploadLimit').value)
            };
            
            try {
                const res = await fetch('/api/admin/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings)
                });
                
                if (res.ok) {
                    showAlert('Settings saved!', 'success');
                    checkMaintenance();
                }
            } catch (error) {}
        }

        function hideModal() {
            document.getElementById('userModal').style.display = 'none';
            document.getElementById('newUsername').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('newLimit').value = '';
        }

        function formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
        }

        function showAlert(message, type) {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.className = `alert alert-${type}`;
            alert.style.display = 'block';
            setTimeout(() => alert.style.display = 'none', 3000);
        }

        function startRefreshInterval() {
            refreshInterval = setInterval(() => {
                if (document.getElementById('botsSection').style.display === 'block') loadBots();
                if (document.getElementById('dashboardSection').style.display === 'block') loadSystemStats();
            }, 5000);
        }

        function logout() {
            window.location.href = '/api/logout';
        }
    </script>
</body>
</html>
'''

# ==================== Routes ====================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/login')
def login_page():
    settings = load_settings()
    if settings.get('maintenance_mode'):
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Maintenance</title></head>
            <body style="font-family:sans-serif; text-align:center; padding:50px;">
                <h1>🚧 Maintenance Mode</h1>
                <p>{{ message }}</p>
            </body>
            </html>
        ''', message=settings.get('maintenance_message'))
    return LOGIN_PAGE

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    return DASHBOARD_PAGE

# ==================== API Routes ====================

@app.route('/api/settings')
def get_settings():
    settings = load_settings()
    return jsonify({
        'maintenance_mode': settings.get('maintenance_mode', False),
        'maintenance_message': settings.get('maintenance_message', '')
    })

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    users = load_users()
    user = users.get(username)
    
    if user and user['password'] == hash_password(password):
        session.permanent = True
        session['user_id'] = username
        user['last_login'] = datetime.now().isoformat()
        save_users(users)
        log_activity(username, 'login', 'Logged in', request.remote_addr)
        return jsonify({'success': True, 'redirect': '/dashboard'})
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout')
def api_logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'logout', 'Logged out', request.remote_addr)
    session.clear()
    return redirect('/login')

@app.route('/api/user/stats')
@login_required
def user_stats():
    username = session['user_id']
    users = load_users()
    uploads = load_uploads()
    user_uploads = uploads.get(username, [])
    
    total_size = 0
    for upload in user_uploads:
        filepath = os.path.join(UPLOAD_DIR, username, upload['filename'])
        if os.path.exists(filepath):
            upload['size'] = os.path.getsize(filepath)
            total_size += upload['size']
    
    user_bots = []
    for bot_id, bot in running_bots.items():
        if bot['username'] == username:
            bot['id'] = bot_id
            user_bots.append(bot)
    
    return jsonify({
        'username': username,
        'is_admin': users.get(username, {}).get('is_admin', False),
        'upload_count': len(user_uploads),
        'upload_limit': get_user_upload_limit(username),
        'total_size': total_size,
        'running_bots': user_bots,
        'uploads': user_uploads
    })

@app.route('/api/user/upload', methods=['POST'])
@login_required
def user_upload():
    username = session['user_id']
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    settings = load_settings()
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings['allowed_extensions']:
        return jsonify({'error': 'File type not allowed'}), 400
    
    upload_count = get_user_upload_count(username)
    upload_limit = get_user_upload_limit(username)
    
    if upload_count >= upload_limit:
        return jsonify({'error': 'Upload limit reached'}), 400
    
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    max_size = settings['max_file_size'] * 1024 * 1024
    if file_size > max_size:
        return jsonify({'error': f'Max size {settings["max_file_size"]}MB'}), 400
    
    user_dir = os.path.join(UPLOAD_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    
    filepath = os.path.join(user_dir, file.filename)
    file.save(filepath)
    
    uploads = load_uploads()
    if username not in uploads:
        uploads[username] = []
    
    uploads[username].append({
        'filename': file.filename,
        'uploaded_at': datetime.now().isoformat(),
        'size': file_size
    })
    save_uploads(uploads)
    
    log_activity(username, 'upload', f'Uploaded: {file.filename}', request.remote_addr)
    
    return jsonify({'success': True})

@app.route('/api/user/start', methods=['POST'])
@login_required
def user_start():
    username = session['user_id']
    data = request.json
    filename = data.get('filename')
    
    bot_id, message = start_bot(filename, username)
    
    if bot_id:
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/user/stop', methods=['POST'])
@login_required
def user_stop():
    username = session['user_id']
    data = request.json
    bot_id = data.get('bot_id')
    
    bot = running_bots.get(bot_id)
    if not bot or bot['username'] != username:
        return jsonify({'error': 'Bot not found'}), 404
    
    success, message = stop_bot(bot_id)
    
    if success:
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/user/logs/<filename>')
@login_required
def user_logs(filename):
    username = session['user_id']
    log_path = os.path.join(LOG_DIR, username, f"{filename}.log")
    
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return f.read()
    
    return 'No logs', 404

@app.route('/api/user/delete', methods=['POST'])
@login_required
def user_delete():
    username = session['user_id']
    data = request.json
    filename = data.get('filename')
    
    for bot_id, bot in list(running_bots.items()):
        if bot['username'] == username and bot['filename'] == filename:
            stop_bot(bot_id)
    
    filepath = os.path.join(UPLOAD_DIR, username, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    
    uploads = load_uploads()
    if username in uploads:
        uploads[username] = [u for u in uploads[username] if u['filename'] != filename]
        save_uploads(uploads)
    
    log_activity(username, 'delete', f'Deleted: {filename}', request.remote_addr)
    
    return jsonify({'success': True})

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    users = load_users()
    uploads = load_uploads()
    activity = load_activity()
    settings = load_settings()
    
    system_stats = {
        'cpu': psutil.cpu_percent() if hasattr(psutil, 'cpu_percent') else 0,
        'ram': psutil.virtual_memory().percent if hasattr(psutil, 'virtual_memory') else 0,
        'running_bots': len(running_bots)
    }
    
    user_details = []
    for username, user_data in users.items():
        user_uploads = uploads.get(username, [])
        user_details.append({
            'username': username,
            'is_admin': user_data.get('is_admin', False),
            'upload_limit': user_data.get('upload_limit', settings['global_upload_limit']),
            'upload_count': len(user_uploads)
        })
    
    return jsonify({
        'total_users': len(users),
        'system': system_stats,
        'users': user_details,
        'user_uploads': uploads,
        'activity': activity[-50:],
        'settings': settings
    })

@app.route('/api/admin/users', methods=['POST', 'PUT', 'DELETE'])
@admin_required
def admin_users():
    users = load_users()
    
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        upload_limit = data.get('upload_limit', 10)
        
        if username in users:
            return jsonify({'error': 'User exists'}), 400
        
        users[username] = {
            'password': hash_password(password),
            'is_admin': False,
            'upload_limit': upload_limit,
            'created_at': datetime.now().isoformat(),
            'status': 'active'
        }
        save_users(users)
        log_activity(session['user_id'], 'admin', f'Created user: {username}', request.remote_addr)
        return jsonify({'success': True})
    
    elif request.method == 'PUT':
        data = request.json
        username = data.get('username')
        
        if username not in users:
            return jsonify({'error': 'User not found'}), 404
        
        if 'upload_limit' in data:
            users[username]['upload_limit'] = data['upload_limit']
        save_users(users)
        return jsonify({'success': True})
    
    elif request.method == 'DELETE':
        data = request.json
        username = data.get('username')
        
        if username not in users:
            return jsonify({'error': 'User not found'}), 404
        
        if username == session['user_id']:
            return jsonify({'error': 'Cannot delete yourself'}), 400
        
        del users[username]
        save_users(users)
        log_activity(session['user_id'], 'admin', f'Deleted user: {username}', request.remote_addr)
        return jsonify({'success': True})

@app.route('/api/admin/settings', methods=['POST'])
@admin_required
def admin_settings():
    settings = load_settings()
    data = request.json
    
    if 'maintenance_mode' in data:
        settings['maintenance_mode'] = data['maintenance_mode']
    if 'maintenance_message' in data:
        settings['maintenance_message'] = data['maintenance_message']
    if 'global_upload_limit' in data:
        settings['global_upload_limit'] = int(data['global_upload_limit'])
    
    save_settings(settings)
    log_activity(session['user_id'], 'admin', 'Updated settings', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/admin/user-files/<username>')
@admin_required
def admin_user_files(username):
    user_dir = os.path.join(UPLOAD_DIR, username)
    if not os.path.exists(user_dir):
        return jsonify({'files': []})
    
    files = []
    for file in os.listdir(user_dir):
        filepath = os.path.join(user_dir, file)
        if os.path.isfile(filepath):
            files.append({
                'name': file,
                'size': os.path.getsize(filepath),
                'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
            })
    
    return jsonify(files)

@app.route('/api/system')
def system():
    try:
        cpu = psutil.cpu_percent() if hasattr(psutil, 'cpu_percent') else 0
        ram = psutil.virtual_memory().percent if hasattr(psutil, 'virtual_memory') else 0
    except:
        cpu = 0
        ram = 0
    
    return jsonify({
        'cpu': cpu,
        'ram': ram,
        'running_bots': len(running_bots)
    })

# ==================== Run ====================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)