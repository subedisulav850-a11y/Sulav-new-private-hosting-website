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
import pkg_resources
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
    
    installed_packages = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
    missing_packages = []
    
    for requirement in REQUIRED_PACKAGES:
        package_name, required_version = requirement.split('==')
        if package_name not in installed_packages:
            missing_packages.append(requirement)
            print(f"❌ {package_name} {required_version} - MISSING")
        elif installed_packages[package_name] != required_version:
            print(f"⚠️ {package_name} - installed: {installed_packages[package_name]}, required: {required_version}")
            missing_packages.append(requirement)
        else:
            print(f"✅ {package_name} {required_version} - OK")
    
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

# Directory structure for Render (persistent storage)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "data/bots")
LOG_DIR = os.path.join(BASE_DIR, "data/logs")
CONFIG_DIR = os.path.join(BASE_DIR, "data/config")
BACKUP_DIR = os.path.join(BASE_DIR, "data/backups")
TEMP_DIR = os.path.join(BASE_DIR, "data/temp")
REQUIREMENTS_DIR = os.path.join(BASE_DIR, "data/requirements")

for dir_path in [UPLOAD_DIR, LOG_DIR, CONFIG_DIR, BACKUP_DIR, TEMP_DIR, REQUIREMENTS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# Config files
USERS_FILE = os.path.join(CONFIG_DIR, "users.json")
UPLOADS_FILE = os.path.join(CONFIG_DIR, "uploads.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
ACTIVITY_FILE = os.path.join(CONFIG_DIR, "activity.json")
ANNOUNCEMENTS_FILE = os.path.join(CONFIG_DIR, "announcements.json")
REQUIREMENTS_FILE = os.path.join(REQUIREMENTS_DIR, "installed.json")

# Default settings
DEFAULT_SETTINGS = {
    "global_upload_limit": 10,
    "max_file_size": 100,
    "allowed_extensions": [".py", ".js", ".sh", ".txt", ".bat", ".ps1", ".zip"],
    "session_timeout": 30,
    "maintenance_mode": False,
    "maintenance_message": "🚧 System is under maintenance. Please check back later. - Sulav",
    "allow_registration": False,
    "max_bots_per_user": 5,
    "enable_activity_logging": True,
    "backup_interval_hours": 24,
    "theme": "dark",
    "site_name": "Sulav Hosting",
    "contact_email": "admin@sulavhosting.com",
    "version": "2.0.0",
    "auto_install_requirements": True,
    "check_requirements_on_start": True
}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Initialize config files
def init_config():
    if not os.path.exists(USERS_FILE):
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'Admin@123')
        default_users = {
            "admin": {
                "password": hash_password(admin_pass),
                "is_admin": True,
                "upload_limit": 1000,
                "max_bots": 50,
                "created_at": datetime.now().isoformat(),
                "last_login": None,
                "last_ip": None,
                "status": "active",
                "notes": "System Administrator",
                "total_uploads": 0,
                "total_bot_starts": 0
            },
            "sulav": {
                "password": hash_password("SulavPapa123"),
                "is_admin": True,
                "upload_limit": 500,
                "max_bots": 30,
                "created_at": datetime.now().isoformat(),
                "last_login": None,
                "last_ip": None,
                "status": "active",
                "notes": "👑 Owner - Sulav",
                "total_uploads": 0,
                "total_bot_starts": 0
            }
        }
        with open(USERS_FILE, 'w') as f:
            json.dump(default_users, f, indent=2)
    
    if not os.path.exists(UPLOADS_FILE):
        with open(UPLOADS_FILE, 'w') as f:
            json.dump({}, f, indent=2)
    
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
    
    if not os.path.exists(ACTIVITY_FILE):
        with open(ACTIVITY_FILE, 'w') as f:
            json.dump([], f, indent=2)
    
    if not os.path.exists(ANNOUNCEMENTS_FILE):
        with open(ANNOUNCEMENTS_FILE, 'w') as f:
            json.dump([], f, indent=2)
    
    if not os.path.exists(REQUIREMENTS_FILE):
        with open(REQUIREMENTS_FILE, 'w') as f:
            json.dump({
                "last_check": None,
                "installed": [],
                "missing": [],
                "auto_install": True
            }, f, indent=2)

init_config()

# Running bots tracking
running_bots = {}
bot_processes = {}

# ==================== Requirements Management Functions ====================

def save_requirements_status(status):
    """Save requirements check status"""
    with open(REQUIREMENTS_FILE, 'w') as f:
        json.dump(status, f, indent=2)

def load_requirements_status():
    """Load requirements check status"""
    with open(REQUIREMENTS_FILE, 'r') as f:
        return json.load(f)

def get_installed_packages():
    """Get list of installed packages with versions"""
    return {pkg.key: pkg.version for pkg in pkg_resources.working_set}

def check_package_installed(package_name, required_version=None):
    """Check if a specific package is installed with correct version"""
    installed = get_installed_packages()
    if package_name not in installed:
        return False, f"{package_name} not installed"
    
    if required_version and installed[package_name] != required_version:
        return False, f"{package_name} version mismatch: installed {installed[package_name]}, required {required_version}"
    
    return True, f"{package_name} {installed[package_name]}"

def install_package(package_spec):
    """Install a specific package"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec])
        return True, f"Successfully installed {package_spec}"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to install {package_spec}: {str(e)}"

def check_all_requirements():
    """Check all required packages and install missing ones"""
    settings = load_settings()
    status = load_requirements_status()
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "total": len(REQUIRED_PACKAGES),
        "installed": [],
        "missing": [],
        "errors": []
    }
    
    print("\n" + "="*60)
    print("📋 CHECKING REQUIREMENTS")
    print("="*60)
    
    for requirement in REQUIRED_PACKAGES:
        if '==' in requirement:
            package, version = requirement.split('==')
        else:
            package = requirement
            version = None
        
        installed, message = check_package_installed(package, version)
        
        if installed:
            results["installed"].append(requirement)
            print(f"✅ {message}")
        else:
            results["missing"].append(requirement)
            print(f"❌ {message}")
            
            if settings.get("auto_install_requirements", True):
                print(f"   Attempting to install {requirement}...")
                success, install_msg = install_package(requirement)
                if success:
                    results["installed"].append(requirement)
                    results["missing"].remove(requirement)
                    print(f"   ✅ {install_msg}")
                else:
                    results["errors"].append(install_msg)
                    print(f"   ❌ {install_msg}")
    
    results["installed_count"] = len(results["installed"])
    results["missing_count"] = len(results["missing"])
    results["success"] = len(results["missing"]) == 0
    
    save_requirements_status(results)
    
    print("="*60)
    print(f"📊 SUMMARY: {results['installed_count']}/{results['total']} packages installed")
    if results["missing_count"] > 0:
        print(f"⚠️  {results['missing_count']} packages still missing")
    else:
        print("✅ All requirements satisfied!")
    print("="*60 + "\n")
    
    return results

def generate_requirements_file():
    """Generate requirements.txt file from installed packages"""
    installed = get_installed_packages()
    requirements = []
    
    for package in REQUIRED_PACKAGES:
        if '==' in package:
            pkg_name = package.split('==')[0]
            if pkg_name in installed:
                requirements.append(f"{pkg_name}=={installed[pkg_name]}")
            else:
                requirements.append(package)
    
    req_path = os.path.join(BASE_DIR, "requirements.txt")
    with open(req_path, 'w') as f:
        f.write('\n'.join(requirements))
    
    return req_path

# Run initial requirements check
if load_settings().get("check_requirements_on_start", True):
    check_all_requirements()

# ==================== Helper Functions ====================

def load_users():
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def load_uploads():
    with open(UPLOADS_FILE, 'r') as f:
        return json.load(f)

def save_uploads(uploads):
    with open(UPLOADS_FILE, 'w') as f:
        json.dump(uploads, f, indent=2)

def load_settings():
    with open(SETTINGS_FILE, 'r') as f:
        return json.load(f)

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def load_activity():
    with open(ACTIVITY_FILE, 'r') as f:
        return json.load(f)

def save_activity(activity):
    with open(ACTIVITY_FILE, 'w') as f:
        json.dump(activity[-100:], f, indent=2)  # Keep last 100 entries

def load_announcements():
    with open(ANNOUNCEMENTS_FILE, 'r') as f:
        return json.load(f)

def save_announcements(announcements):
    with open(ANNOUNCEMENTS_FILE, 'w') as f:
        json.dump(announcements, f, indent=2)

def log_activity(username, action, details, ip=None):
    settings = load_settings()
    if settings.get('enable_activity_logging', True):
        activity = load_activity()
        activity.append({
            'username': username,
            'action': action,
            'details': details,
            'ip': ip or request.remote_addr,
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

def get_user_max_bots(username):
    users = load_users()
    user = users.get(username, {})
    return user.get('max_bots', load_settings()['max_bots_per_user'])

def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def extract_zip(zip_path, extract_to, main_file=None):
    """Extract zip file and return the main file to run"""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    
    if main_file:
        main_path = os.path.join(extract_to, main_file)
        if os.path.exists(main_path):
            return main_file
    
    python_files = []
    for root, dirs, files in os.walk(extract_to):
        for file in files:
            if file.endswith('.py'):
                rel_path = os.path.relpath(os.path.join(root, file), extract_to)
                python_files.append(rel_path)
    
    if python_files:
        return python_files[0]
    
    return None

# ==================== Bot Management ====================

def start_bot(filename, username, main_file=None):
    user_dir = os.path.join(UPLOAD_DIR, username)
    
    if filename.endswith('.zip'):
        extract_dir = os.path.join(user_dir, filename.replace('.zip', ''))
        os.makedirs(extract_dir, exist_ok=True)
        zip_path = os.path.join(user_dir, filename)
        
        main_file = extract_zip(zip_path, extract_dir, main_file)
        if not main_file:
            return None, "No Python file found in zip"
        
        filepath = os.path.join(extract_dir, main_file)
        bot_name = f"{filename.replace('.zip', '')}/{main_file}"
    else:
        filepath = os.path.join(user_dir, filename)
        bot_name = filename
    
    if not os.path.exists(filepath):
        return None, "File not found"
    
    users = load_users()
    user_bots = len([b for b in running_bots.values() if b['username'] == username])
    max_bots = get_user_max_bots(username)
    
    if user_bots >= max_bots:
        return None, f"Maximum bot limit reached ({max_bots})"
    
    bot_log_dir = os.path.join(LOG_DIR, username)
    os.makedirs(bot_log_dir, exist_ok=True)
    
    log_path = os.path.join(bot_log_dir, f"{bot_name.replace('/', '_')}.log")
    log_file = open(log_path, "a")
    
    log_file.write(f"\n{'='*50}\n")
    log_file.write(f"Bot started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log_file.write(f"Bot: {bot_name}\n")
    log_file.write(f"{'='*50}\n\n")
    log_file.flush()
    
    try:
        proc = subprocess.Popen(
            ["python", filepath],
            stdout=log_file,
            stderr=log_file,
            text=True,
            cwd=os.path.dirname(filepath)
        )
        
        bot_id = f"{username}_{bot_name}_{int(time.time())}"
        running_bots[bot_id] = {
            "filename": bot_name,
            "original_file": filename,
            "username": username,
            "start_time": datetime.now().isoformat(),
            "log_path": log_path,
            "pid": proc.pid,
            "status": "running"
        }
        bot_processes[bot_id] = proc
        
        users = load_users()
        if username in users:
            users[username]['total_bot_starts'] = users[username].get('total_bot_starts', 0) + 1
            save_users(users)
        
        log_activity(username, 'start_bot', f'Started bot: {bot_name}')
        
        return bot_id, "Bot started successfully"
    except Exception as e:
        return None, f"Failed to start bot: {str(e)}"

def stop_bot(bot_id):
    if bot_id not in running_bots or bot_id not in bot_processes:
        return False, "Bot not found"
    
    try:
        proc = bot_processes[bot_id]
        proc.terminate()
        
        for _ in range(10):
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        
        if proc.poll() is None:
            proc.kill()
        
        bot = running_bots[bot_id]
        with open(bot['log_path'], 'a') as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*50}\n\n")
        
        bot['status'] = 'stopped'
        log_activity(bot['username'], 'stop_bot', f'Stopped bot: {bot["filename"]}')
        
        del running_bots[bot_id]
        del bot_processes[bot_id]
        
        return True, "Bot stopped successfully"
    except Exception as e:
        return False, f"Failed to stop bot: {str(e)}"

# ==================== Authentication Decorators ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect('/login')
        
        users = load_users()
        user = users.get(session['user_id'], {})
        if user.get('status') != 'active':
            session.clear()
            return redirect('/login?message=Account+disabled')
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        
        users = load_users()
        user = users.get(session['user_id'], {})
        
        if not user.get('is_admin', False):
            return jsonify({"error": "Admin access required"}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def check_maintenance(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        settings = load_settings()
        if settings.get('maintenance_mode', False):
            if 'user_id' in session:
                users = load_users()
                if users.get(session['user_id'], {}).get('is_admin', False):
                    return f(*args, **kwargs)
            
            if request.path.startswith('/api/'):
                return jsonify({
                    "error": "maintenance",
                    "message": settings.get('maintenance_message', 'System under maintenance')
                }), 503
            
            return render_template_string(MAINTENANCE_PAGE, message=settings.get('maintenance_message'))
        
        return f(*args, **kwargs)
    return decorated_function

# ==================== HTML Templates ====================

MAINTENANCE_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maintenance Mode - Sulav Hosting</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .maintenance-container { background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 90%; max-width: 500px; padding: 40px; text-align: center; }
        .icon { font-size: 5rem; margin-bottom: 20px; }
        h1 { font-size: 2rem; color: #333; margin-bottom: 20px; }
        p { color: #666; line-height: 1.6; margin-bottom: 30px; }
        .btn { display: inline-block; padding: 12px 30px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; text-decoration: none; border-radius: 8px; font-weight: 600; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(102,126,234,0.4); }
    </style>
</head>
<body>
    <div class="maintenance-container">
        <div class="icon">🚧</div>
        <h1>Maintenance Mode</h1>
        <p>{{ message }}</p>
        <a href="/logout" class="btn">Back to Login</a>
    </div>
</body>
</html>
'''

LOGIN_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sulav Hosting - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .login-container { background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 90%; max-width: 400px; padding: 40px; }
        .logo { text-align: center; margin-bottom: 30px; }
        .logo h1 { font-size: 2rem; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .logo p { color: #666; font-size: 0.9rem; margin-top: 5px; }
        .form-group { margin-bottom: 20px; }
        .form-group input { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 1rem; transition: border-color 0.3s; }
        .form-group input:focus { outline: none; border-color: #667eea; }
        .login-btn { width: 100%; padding: 12px; background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; border-radius: 10px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: transform 0.3s; }
        .login-btn:hover { transform: translateY(-2px); }
        .error-message { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 8px; margin-bottom: 20px; display: none; }
        .footer { text-align: center; margin-top: 20px; color: #666; font-size: 0.8rem; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>Sulav Hosting</h1>
            <p>Professional Bot Management Panel</p>
        </div>
        <div id="errorMessage" class="error-message"></div>
        <form id="loginForm">
            <div class="form-group">
                <input type="text" id="username" placeholder="Username" required>
            </div>
            <div class="form-group">
                <input type="password" id="password" placeholder="Password" required>
            </div>
            <button type="submit" class="login-btn">Login</button>
        </form>
        <div class="footer">
            &copy; 2024 Sulav Hosting. All rights reserved.
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            try {
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password })
                });
                const data = await response.json();
                
                if (response.ok) {
                    window.location.href = data.redirect;
                } else {
                    document.getElementById('errorMessage').style.display = 'block';
                    document.getElementById('errorMessage').textContent = data.error;
                }
            } catch (error) {
                document.getElementById('errorMessage').style.display = 'block';
                document.getElementById('errorMessage').textContent = 'Login failed';
            }
        });
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
        .navbar { background: white; padding: 1rem 2rem; box-shadow: 0 2px 10px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 1.5rem; font-weight: bold; background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .user-info { display: flex; align-items: center; gap: 20px; }
        .user-badge { background: #667eea; color: white; padding: 5px 10px; border-radius: 20px; font-size: 0.8rem; }
        .logout-btn { padding: 8px 15px; background: #f44336; color: white; border: none; border-radius: 8px; cursor: pointer; }
        .container { max-width: 1400px; margin: 2rem auto; padding: 0 2rem; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: white; border-radius: 15px; padding: 20px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 15px; }
        .stat-icon { width: 50px; height: 50px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; }
        .stat-icon.blue { background: #e3f2fd; color: #1976d2; }
        .stat-icon.green { background: #e8f5e9; color: #388e3c; }
        .stat-icon.purple { background: #f3e5f5; color: #7b1fa2; }
        .stat-icon.orange { background: #fff3e0; color: #f57c00; }
        .stat-info h3 { color: #666; font-size: 0.9rem; margin-bottom: 5px; }
        .stat-info .value { font-size: 1.8rem; font-weight: bold; color: #333; }
        .section { background: white; border-radius: 15px; padding: 25px; margin-bottom: 30px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); }
        .section-title { font-size: 1.3rem; color: #333; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
        .upload-area { border: 2px dashed #667eea; border-radius: 10px; padding: 40px; text-align: center; cursor: pointer; margin-bottom: 20px; transition: all 0.3s; }
        .upload-area:hover { background: #f8f9ff; }
        .upload-area i { font-size: 3rem; color: #667eea; margin-bottom: 15px; }
        .file-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 15px; }
        .file-item { background: #f8f9fa; border-radius: 10px; padding: 15px; display: flex; justify-content: space-between; align-items: center; }
        .file-info { flex: 1; }
        .file-name { font-weight: 600; color: #333; margin-bottom: 3px; }
        .file-meta { font-size: 0.7rem; color: #999; }
        .file-actions { display: flex; gap: 5px; }
        .btn { padding: 8px 15px; border: none; border-radius: 5px; cursor: pointer; font-weight: 500; transition: all 0.3s; }
        .btn-sm { padding: 5px 10px; font-size: 0.8rem; }
        .btn-primary { background: #667eea; color: white; }
        .btn-primary:hover { background: #5a67d8; transform: translateY(-2px); }
        .btn-success { background: #48bb78; color: white; }
        .btn-success:hover { background: #38a169; }
        .btn-danger { background: #f56565; color: white; }
        .btn-danger:hover { background: #e53e3e; }
        .btn-warning { background: #ed8936; color: white; }
        .btn-info { background: #4299e1; color: white; }
        .log-box { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 10px; font-family: monospace; height: 400px; overflow-y: auto; white-space: pre-wrap; margin: 20px 0; font-size: 0.9rem; }
        .log-controls { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .log-controls select { flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 5px; min-width: 200px; }
        .bot-list { margin-top: 20px; }
        .bot-item { background: #f8f9fa; border-radius: 10px; padding: 15px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
        .bot-status { padding: 4px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 600; }
        .status-running { background: #e8f5e9; color: #388e3c; }
        .status-stopped { background: #ffebee; color: #d32f2f; }
        .alert { padding: 15px; border-radius: 10px; margin-bottom: 20px; display: none; position: fixed; top: 20px; right: 20px; z-index: 9999; animation: slideIn 0.3s; max-width: 400px; }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
        .alert-success { background: #c6f6d5; color: #22543d; border-left: 4px solid #48bb78; }
        .alert-error { background: #fed7d7; color: #742a2a; border-left: 4px solid #f56565; }
        .nav-links { display: flex; gap: 20px; }
        .nav-link { cursor: pointer; padding: 5px 10px; border-radius: 5px; transition: all 0.3s; }
        .nav-link:hover { background: #f0f0f0; }
        .nav-link.active { background: #667eea; color: white; }
        .progress-bar { width: 100%; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; margin: 10px 0; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); transition: width 0.3s; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 12px; background: #f8f9fa; font-weight: 600; }
        td { padding: 12px; border-bottom: 1px solid #e2e8f0; }
        tr:hover { background: #f8f9fa; }
        input[type="number"], input[type="text"], textarea { padding: 8px; border: 1px solid #ddd; border-radius: 4px; width: 100%; }
        .maintenance-banner { background: #fed7d7; color: #742a2a; padding: 10px 20px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
        .maintenance-banner.warning { background: #fff3e0; color: #f57c00; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 10000; align-items: center; justify-content: center; }
        .modal-content { background: white; border-radius: 15px; padding: 25px; max-width: 500px; width: 90%; animation: modalSlideIn 0.3s; }
        @keyframes modalSlideIn { from { transform: translateY(-50px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .modal-title { font-size: 1.3rem; color: #333; margin-bottom: 15px; }
        .modal-body { margin-bottom: 20px; }
        .modal-footer { display: flex; gap: 10px; justify-content: flex-end; }
        .badge { background: #667eea; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.7rem; }
        .requirements-banner { background: #e3f2fd; color: #1976d2; padding: 10px 20px; border-radius: 8px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; border-left: 4px solid #1976d2; }
        .requirements-banner.success { background: #e8f5e9; color: #388e3c; border-left-color: #388e3c; }
        .requirements-banner.warning { background: #fff3e0; color: #f57c00; border-left-color: #f57c00; }
        @media (max-width: 768px) { .stats-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="logo">Sulav Hosting</div>
        <div class="nav-links">
            <span class="nav-link active" onclick="showSection('dashboard')">Dashboard</span>
            <span class="nav-link" onclick="showSection('files')">Files</span>
            <span class="nav-link" onclick="showSection('bots')">Bots</span>
            <span class="nav-link" onclick="showSection('logs')">Logs</span>
            <span class="nav-link" onclick="showSection('requirements')">Requirements</span>
            <span class="nav-link" id="adminLink" style="display:none;" onclick="showSection('admin')">Admin</span>
        </div>
        <div class="user-info">
            <span class="user-badge" id="userRole">User</span>
            <span id="username"></span>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </div>
    </nav>

    <div class="container">
        <div id="maintenanceBanner" class="maintenance-banner" style="display: none;">
            <span>🚧 <span id="maintenanceMessage">System is under maintenance</span></span>
            <button class="btn btn-sm btn-danger" onclick="dismissMaintenance()">Dismiss</button>
        </div>

        <div id="requirementsBanner" class="requirements-banner" style="display: none;">
            <span id="requirementsMessage">Checking requirements...</span>
            <button class="btn btn-sm btn-primary" onclick="checkRequirements()">Check Now</button>
        </div>

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
                        <div id="botLimit"></div>
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

            <div class="section">
                <h2 class="section-title">📢 Announcements</h2>
                <div id="announcements"></div>
            </div>
        </div>

        <!-- Files Section -->
        <div id="filesSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">📤 Upload Bot (ZIP or Python)</h2>
                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div>📁</div>
                    <p>Click to upload or drag and drop</p>
                    <p class="small">Supported: .py, .js, .sh, .zip (Max: <span id="maxFileSize">100</span>MB)</p>
                    <p class="small">For ZIP files, you'll specify the main file after upload</p>
                    <input type="file" id="fileInput" style="display: none;" onchange="handleFileSelect()">
                </div>
                <div id="zipMainFileInput" style="display: none; margin-top: 20px;">
                    <h3>ZIP File Detected</h3>
                    <p>Enter the main Python file to run (e.g., main.py or bot.py):</p>
                    <input type="text" id="mainFileInput" placeholder="main.py" style="width: 300px; padding: 10px;">
                    <button class="btn btn-primary" onclick="uploadWithMainFile()">Upload & Extract</button>
                    <button class="btn btn-warning" onclick="cancelZipUpload()">Cancel</button>
                </div>
                <div id="uploadProgress" class="progress-bar" style="display: none;">
                    <div class="progress-fill" id="uploadProgressFill" style="width: 0%;"></div>
                </div>
            </div>

            <div class="section">
                <h2 class="section-title">📁 My Files</h2>
                <div id="fileList" class="file-list">Loading files...</div>
            </div>
        </div>

        <!-- Bots Section -->
        <div id="botsSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">🤖 Running Bots</h2>
                <div id="botList" class="bot-list">Loading bots...</div>
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
                    <button class="btn btn-primary" onclick="loadLogs()">View Logs</button>
                    <button class="btn btn-warning" onclick="refreshLogs()">Refresh</button>
                    <button class="btn btn-info" onclick="downloadLogs()">Download</button>
                </div>
                <div id="logBox" class="log-box">Select a file to view logs</div>
            </div>
        </div>

        <!-- Requirements Section -->
        <div id="requirementsSection" style="display:none;">
            <div class="section">
                <h2 class="section-title">📦 Requirements Manager</h2>
                
                <div style="margin-bottom: 20px;">
                    <button class="btn btn-primary" onclick="checkRequirements()">Check Requirements</button>
                    <button class="btn btn-success" onclick="installAllRequirements()">Install All Missing</button>
                    <button class="btn btn-info" onclick="downloadRequirements()">Download requirements.txt</button>
                </div>

                <div id="requirementsStatus" style="margin-bottom: 20px;">
                    <h3>Current Status</h3>
                    <div id="requirementsSummary"></div>
                </div>

                <div id="requirementsList" style="margin-top: 20px;">
                    <h3>Required Packages</h3>
                    <table>
                        <thead>
                            <tr>
                                <th>Package</th>
                                <th>Status</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="requirementsTableBody">
                            <tr><td colspan="3">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Admin Section -->
        <div id="adminSection" style="display:none;">
            <div class="maintenance-banner warning" id="maintenanceModeBanner" style="display: none;">
                ⚠️ Maintenance mode is ON - Users cannot access the panel
            </div>

            <div class="section">
                <h2 class="section-title">👥 User Management</h2>
                <button class="btn btn-primary" onclick="showAddUserModal()" style="margin-bottom: 20px;">+ Add User</button>
                <div id="userList"></div>
            </div>
            
            <div class="section">
                <h2 class="section-title">📊 User Uploads Overview</h2>
                <div id="userUploadsList"></div>
            </div>
            
            <div class="section">
                <h2 class="section-title">⚙️ System Settings</h2>
                <div style="margin-bottom: 15px;">
                    <label>Maintenance Mode:</label>
                    <select id="maintenanceMode" style="width:100%; padding:10px; margin-top:5px;">
                        <option value="false">Off</option>
                        <option value="true">On</option>
                    </select>
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Maintenance Message:</label>
                    <textarea id="maintenanceMessageInput" rows="3" style="width:100%; padding:10px; margin-top:5px;"></textarea>
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Auto Install Requirements:</label>
                    <select id="autoInstallRequirements" style="width:100%; padding:10px; margin-top:5px;">
                        <option value="true">Enabled</option>
                        <option value="false">Disabled</option>
                    </select>
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Check Requirements on Start:</label>
                    <select id="checkRequirementsOnStart" style="width:100%; padding:10px; margin-top:5px;">
                        <option value="true">Enabled</option>
                        <option value="false">Disabled</option>
                    </select>
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Global Upload Limit:</label>
                    <input type="number" id="globalUploadLimit" style="width:100%; padding:10px; margin-top:5px;">
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Max File Size (MB):</label>
                    <input type="number" id="maxFileSizeSetting" style="width:100%; padding:10px; margin-top:5px;">
                </div>
                <div style="margin-bottom: 15px;">
                    <label>Max Bots Per User:</label>
                    <input type="number" id="maxBotsPerUser" style="width:100%; padding:10px; margin-top:5px;">
                </div>
                <button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
            </div>

            <div class="section">
                <h2 class="section-title">📢 Announcements</h2>
                <div style="margin-bottom: 15px;">
                    <textarea id="newAnnouncement" rows="3" placeholder="Enter new announcement..." style="width:100%; padding:10px;"></textarea>
                    <button class="btn btn-primary" onclick="addAnnouncement()" style="margin-top:10px;">Add Announcement</button>
                </div>
                <div id="announcementsList"></div>
            </div>

            <div class="section">
                <h2 class="section-title">📝 Activity Log</h2>
                <div id="activityLog" style="max-height: 400px; overflow-y: auto;"></div>
            </div>

            <div class="section">
                <h2 class="section-title">💾 Backup & Restore</h2>
                <button class="btn btn-primary" onclick="createBackup()">Create Backup</button>
                <button class="btn btn-warning" onclick="restoreBackup()">Restore from Backup</button>
                <div id="backupList" style="margin-top:20px;"></div>
            </div>

            <div class="section">
                <h2 class="section-title">📊 System Monitor</h2>
                <div id="systemMonitor">Loading system stats...</div>
            </div>
        </div>
    </div>

    <!-- Modal for file download -->
    <div id="downloadModal" class="modal">
        <div class="modal-content">
            <h3 class="modal-title">Download File</h3>
            <div class="modal-body" id="downloadModalBody">
                Are you sure you want to download this file?
            </div>
            <div class="modal-footer">
                <button class="btn btn-danger" onclick="hideModal()">Cancel</button>
                <button class="btn btn-primary" id="confirmDownloadBtn">Download</button>
            </div>
        </div>
    </div>

    <script>
        let currentUser = null;
        let isAdmin = false;
        let refreshInterval = null;
        let selectedFile = null;
        let currentBotId = null;

        document.addEventListener('DOMContentLoaded', () => {
            loadUserData();
            startRefreshInterval();
            checkMaintenanceStatus();
            loadRequirementsStatus();
        });

        function showSection(section) {
            document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            
            document.getElementById('dashboardSection').style.display = 'none';
            document.getElementById('filesSection').style.display = 'none';
            document.getElementById('botsSection').style.display = 'none';
            document.getElementById('logsSection').style.display = 'none';
            document.getElementById('requirementsSection').style.display = 'none';
            document.getElementById('adminSection').style.display = 'none';
            
            document.getElementById(section + 'Section').style.display = 'block';
            
            if (section === 'files') loadFiles();
            if (section === 'bots') loadBots();
            if (section === 'logs') loadLogFileList();
            if (section === 'requirements') loadRequirementsStatus();
            if (section === 'admin' && isAdmin) loadAdminData();
        }

        function checkMaintenanceStatus() {
            fetch('/api/settings')
                .then(res => res.json())
                .then(data => {
                    if (data.maintenance_mode) {
                        document.getElementById('maintenanceBanner').style.display = 'flex';
                        document.getElementById('maintenanceMessage').textContent = data.maintenance_message;
                    }
                });
        }

        function dismissMaintenance() {
            document.getElementById('maintenanceBanner').style.display = 'none';
        }

        async function loadUserData() {
            try {
                const response = await fetch('/api/user/stats');
                const data = await response.json();
                
                if (response.ok) {
                    currentUser = data;
                    isAdmin = data.is_admin;
                    document.getElementById('username').textContent = data.username;
                    document.getElementById('userRole').textContent = isAdmin ? 'Admin' : 'User';
                    document.getElementById('uploadCount').textContent = data.upload_count;
                    document.getElementById('uploadLimit').textContent = `Limit: ${data.upload_limit}`;
                    document.getElementById('runningCount').textContent = data.running_bots?.length || 0;
                    document.getElementById('botLimit').textContent = `Max: ${data.max_bots || 5}`;
                    document.getElementById('storageUsed').textContent = formatSize(data.total_size || 0);
                    
                    if (isAdmin) {
                        document.getElementById('adminLink').style.display = 'inline';
                    }
                    
                    loadSystemStats();
                    loadAnnouncements();
                }
            } catch (error) {
                showAlert('Failed to load user data', 'error');
            }
        }

        async function loadAnnouncements() {
            try {
                const response = await fetch('/api/announcements');
                const data = await response.json();
                
                let html = '';
                data.forEach(ann => {
                    html += `
                        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #667eea;">
                            <p>${ann.message}</p>
                            <small>${new Date(ann.created_at).toLocaleString()} by ${ann.created_by}</small>
                        </div>
                    `;
                });
                
                if (html === '') html = '<p>No announcements</p>';
                document.getElementById('announcements').innerHTML = html;
            } catch (error) {}
        }

        async function loadSystemStats() {
            try {
                const response = await fetch('/api/system');
                const data = await response.json();
                document.getElementById('systemCpu').textContent = data.cpu + '%';
            } catch (error) {}
        }

        async function loadRequirementsStatus() {
            try {
                const response = await fetch('/api/requirements/status');
                const data = await response.json();
                
                let summaryHtml = `
                    <div class="requirements-banner ${data.success ? 'success' : 'warning'}">
                        <span>📦 ${data.installed_count}/${data.total} packages installed</span>
                        <span>Last checked: ${data.timestamp ? new Date(data.timestamp).toLocaleString() : 'Never'}</span>
                    </div>
                `;
                document.getElementById('requirementsSummary').innerHTML = summaryHtml;
                
                let tableHtml = '';
                const requiredPackages = [
                    'flask==2.3.3',
                    'psutil==5.9.5',
                    'gunicorn==21.2.0'
                ];
                
                for (const pkg of requiredPackages) {
                    const isInstalled = data.installed.includes(pkg);
                    tableHtml += `
                        <tr>
                            <td>${pkg}</td>
                            <td>
                                <span class="badge" style="background: ${isInstalled ? '#48bb78' : '#f56565'}">
                                    ${isInstalled ? '✅ Installed' : '❌ Missing'}
                                </span>
                            </td>
                            <td>
                                ${!isInstalled ? `<button class="btn btn-sm btn-primary" onclick="installPackage('${pkg}')">Install</button>` : '✓'}
                            </td>
                        </tr>
                    `;
                }
                
                document.getElementById('requirementsTableBody').innerHTML = tableHtml;
                
                if (data.missing_count > 0) {
                    document.getElementById('requirementsBanner').style.display = 'flex';
                    document.getElementById('requirementsMessage').textContent = 
                        `⚠️ ${data.missing_count} requirements missing. Click to install.`;
                } else {
                    document.getElementById('requirementsBanner').style.display = 'flex';
                    document.getElementById('requirementsBanner').className = 'requirements-banner success';
                    document.getElementById('requirementsMessage').textContent = 
                        '✅ All requirements satisfied!';
                }
            } catch (error) {
                console.error('Failed to load requirements', error);
            }
        }

        async function checkRequirements() {
            showAlert('Checking requirements...', 'info');
            try {
                const response = await fetch('/api/requirements/check', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showAlert('Requirements check complete!', 'success');
                    loadRequirementsStatus();
                }
            } catch (error) {
                showAlert('Failed to check requirements', 'error');
            }
        }

        async function installPackage(packageSpec) {
            showAlert(`Installing ${packageSpec}...`, 'info');
            try {
                const response = await fetch('/api/requirements/install', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ package: packageSpec })
                });
                const data = await response.json();
                if (data.success) {
                    showAlert(`✅ ${packageSpec} installed!`, 'success');
                    loadRequirementsStatus();
                } else {
                    showAlert(`❌ Failed to install: ${data.error}`, 'error');
                }
            } catch (error) {
                showAlert('Installation failed', 'error');
            }
        }

        async function installAllRequirements() {
            showAlert('Installing all missing requirements...', 'info');
            try {
                const response = await fetch('/api/requirements/install-all', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showAlert('✅ All requirements installed!', 'success');
                    loadRequirementsStatus();
                } else {
                    showAlert(`❌ Some installations failed`, 'warning');
                }
            } catch (error) {
                showAlert('Installation failed', 'error');
            }
        }

        function downloadRequirements() {
            window.location.href = '/api/requirements/download';
        }

        async function loadFiles() {
            try {
                const response = await fetch('/api/user/stats');
                const data = await response.json();
                
                if (!data.uploads || data.uploads.length === 0) {
                    document.getElementById('fileList').innerHTML = '<p>No files uploaded yet.</p>';
                    return;
                }
                
                let html = '';
                data.uploads.forEach(file => {
                    const isZip = file.filename.endsWith('.zip');
                    html += `
                        <div class="file-item">
                            <div class="file-info">
                                <div class="file-name">${file.filename} ${isZip ? '📦' : '📄'}</div>
                                <div class="file-meta">${formatSize(file.size)} • ${new Date(file.uploaded_at).toLocaleString()}</div>
                                ${file.main_file ? `<div class="file-meta">Main: ${file.main_file}</div>` : ''}
                            </div>
                            <div class="file-actions">
                                <button class="btn btn-sm btn-info" onclick="downloadFile('${file.filename}')">Download</button>
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
                const response = await fetch('/api/user/stats');
                const data = await response.json();
                
                if (!data.running_bots || data.running_bots.length === 0) {
                    document.getElementById('botList').innerHTML = '<p>No bots running.</p>';
                    return;
                }
                
                let html = '';
                data.running_bots.forEach(bot => {
                    html += `
                        <div class="bot-item">
                            <div>
                                <strong>${bot.filename}</strong><br>
                                <small>Started: ${new Date(bot.start_time).toLocaleString()}</small><br>
                                <small>PID: ${bot.pid}</small>
                            </div>
                            <div>
                                <span class="bot-status status-running">● Running</span>
                                <button class="btn btn-sm btn-info" onclick="viewBotLogs('${bot.id}')">Logs</button>
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

        function handleFileSelect() {
            const fileInput = document.getElementById('fileInput');
            selectedFile = fileInput.files[0];
            
            if (selectedFile.name.endsWith('.zip')) {
                document.getElementById('zipMainFileInput').style.display = 'block';
            } else {
                uploadFile();
            }
        }

        function cancelZipUpload() {
            document.getElementById('zipMainFileInput').style.display = 'none';
            document.getElementById('fileInput').value = '';
            selectedFile = null;
        }

        async function uploadWithMainFile() {
            const mainFile = document.getElementById('mainFileInput').value;
            if (!mainFile) {
                showAlert('Please enter the main file name', 'error');
                return;
            }
            
            await uploadFile(mainFile);
            document.getElementById('zipMainFileInput').style.display = 'none';
            document.getElementById('mainFileInput').value = '';
        }

        async function uploadFile(mainFile = null) {
            if (!selectedFile) return;
            
            const formData = new FormData();
            formData.append('file', selectedFile);
            if (mainFile) {
                formData.append('main_file', mainFile);
            }
            
            document.getElementById('uploadProgress').style.display = 'block';
            
            try {
                const response = await fetch('/api/user/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showAlert('File uploaded successfully!', 'success');
                    document.getElementById('fileInput').value = '';
                    selectedFile = null;
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
            let mainFile = null;
            if (filename.endsWith('.zip')) {
                mainFile = prompt('Enter the main Python file to run (e.g., main.py):');
                if (!mainFile) return;
            }
            
            try {
                const response = await fetch('/api/user/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ filename, main_file: mainFile })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    showAlert(`Bot started!`, 'success');
                    loadBots();
                    loadUserData();
                } else {
                    showAlert(data.error || 'Failed to start bot', 'error');
                }
            } catch (error) {
                showAlert('Failed to start bot', 'error');
            }
        }

        async function stopBot(botId) {
            if (!confirm('Stop this bot?')) return;
            
            try {
                const response = await fetch('/api/user/stop', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ bot_id: botId })
                });
                
                if (response.ok) {
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
                const response = await fetch('/api/user/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ filename })
                });
                
                if (response.ok) {
                    showAlert('File deleted!', 'success');
                    loadUserData();
                    loadFiles();
                }
            } catch (error) {
                showAlert('Delete failed', 'error');
            }
        }

        function downloadFile(filename) {
            window.location.href = `/api/user/download/${filename}`;
        }

        async function loadLogs() {
            const filename = document.getElementById('logFileSelect').value;
            if (!filename) {
                showAlert('Select a file', 'error');
                return;
            }
            
            try {
                const response = await fetch(`/api/user/logs/${filename}`);
                const logs = await response.text();
                document.getElementById('logBox').textContent = logs || 'No logs available';
            } catch (error) {
                document.getElementById('logBox').textContent = 'Failed to load logs';
            }
        }

        function refreshLogs() {
            loadLogs();
        }

        function downloadLogs() {
            const filename = document.getElementById('logFileSelect').value;
            if (filename) {
                window.location.href = `/api/user/logs/${filename}?download=true`;
            }
        }

        function viewBotLogs(botId) {
            currentBotId = botId;
            showSection('logs');
        }

        async function loadAdminData() {
            try {
                const response = await fetch('/api/admin/stats');
                const data = await response.json();
                
                let userHtml = '<table><tr><th>Username</th><th>Role</th><th>Files</th><th>Bots</th><th>Limit</th><th>Status</th><th>Actions</th></tr>';
                
                data.users.forEach(user => {
                    userHtml += `
                        <tr>
                            <td>${user.username} ${user.notes ? '👑' : ''}</td>
                            <td><span class="badge">${user.is_admin ? 'Admin' : 'User'}</span></td>
                            <td>${user.upload_count}/${user.upload_limit}</td>
                            <td>${user.running_bots}/${user.max_bots || 5}</td>
                            <td><input type="number" id="limit_${user.username}" value="${user.upload_limit}" style="width:70px;"></td>
                            <td><span class="badge" style="background: ${user.status === 'active' ? '#48bb78' : '#f56565'}">${user.status || 'active'}</span></td>
                            <td>
                                <button class="btn btn-sm btn-primary" onclick="updateUserLimit('${user.username}')">Update</button>
                                ${!user.is_admin ? `<button class="btn btn-sm btn-danger" onclick="deleteUser('${user.username}')">Delete</button>` : ''}
                                <button class="btn btn-sm btn-info" onclick="viewUserFiles('${user.username}')">Files</button>
                            </td>
                        </tr>
                    `;
                });
                
                userHtml += '</table>';
                document.getElementById('userList').innerHTML = userHtml;
                
                let uploadsHtml = '<table><tr><th>Username</th><th>Files</th><th>Actions</th></tr>';
                for (const [username, files] of Object.entries(data.user_uploads || {})) {
                    uploadsHtml += `
                        <tr>
                            <td>${username}</td>
                            <td>${files.length} files</td>
                            <td>
                                <button class="btn btn-sm btn-info" onclick="viewUserFiles('${username}')">View Files</button>
                                <button class="btn btn-sm btn-warning" onclick="downloadAllUserFiles('${username}')">Download All</button>
                            </td>
                        </tr>
                    `;
                }
                uploadsHtml += '</table>';
                document.getElementById('userUploadsList').innerHTML = uploadsHtml;
                
                document.getElementById('maintenanceMode').value = data.settings.maintenance_mode ? 'true' : 'false';
                document.getElementById('maintenanceMessageInput').value = data.settings.maintenance_message || '';
                document.getElementById('autoInstallRequirements').value = data.settings.auto_install_requirements ? 'true' : 'false';
                document.getElementById('checkRequirementsOnStart').value = data.settings.check_requirements_on_start ? 'true' : 'false';
                document.getElementById('globalUploadLimit').value = data.settings.global_upload_limit;
                document.getElementById('maxFileSizeSetting').value = data.settings.max_file_size;
                document.getElementById('maxBotsPerUser').value = data.settings.max_bots_per_user || 5;
                
                if (data.settings.maintenance_mode) {
                    document.getElementById('maintenanceModeBanner').style.display = 'block';
                } else {
                    document.getElementById('maintenanceModeBanner').style.display = 'none';
                }
                
                let activityHtml = '<table><tr><th>Time</th><th>User</th><th>Action</th><th>Details</th><th>IP</th></tr>';
                (data.activity || []).forEach(act => {
                    activityHtml += `
                        <tr>
                            <td>${new Date(act.timestamp).toLocaleString()}</td>
                            <td>${act.username}</td>
                            <td>${act.action}</td>
                            <td>${act.details}</td>
                            <td>${act.ip}</td>
                        </tr>
                    `;
                });
                activityHtml += '</table>';
                document.getElementById('activityLog').innerHTML = activityHtml;
                
                let annHtml = '';
                (data.announcements || []).forEach((ann, index) => {
                    annHtml += `
                        <div style="background: #f8f9fa; padding: 10px; margin-bottom: 10px; border-radius: 5px;">
                            <p>${ann.message}</p>
                            <small>${new Date(ann.created_at).toLocaleString()}</small>
                            <button class="btn btn-sm btn-danger" onclick="deleteAnnouncement(${index})">Delete</button>
                        </div>
                    `;
                });
                document.getElementById('announcementsList').innerHTML = annHtml || '<p>No announcements</p>';
                
                document.getElementById('systemMonitor').innerHTML = `
                    <p>CPU: ${data.system.cpu}%</p>
                    <p>RAM: ${data.system.ram}%</p>
                    <p>Disk: ${data.system.disk}%</p>
                    <p>Total Users: ${data.total_users}</p>
                    <p>Total Uploads: ${data.total_uploads}</p>
                    <p>Running Bots: ${data.system.running_bots}</p>
                    <p>Total Bot Starts: ${data.total_bot_starts || 0}</p>
                `;
            } catch (error) {
                console.error('Failed to load admin data', error);
            }
        }

        async function updateUserLimit(username) {
            const limit = document.getElementById(`limit_${username}`).value;
            
            try {
                const response = await fetch('/api/admin/users', {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, upload_limit: parseInt(limit) })
                });
                
                if (response.ok) {
                    showAlert('User limit updated!', 'success');
                }
            } catch (error) {}
        }

        async function deleteUser(username) {
            if (!confirm(`Delete user ${username}?`)) return;
            
            try {
                const response = await fetch('/api/admin/users', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username })
                });
                
                if (response.ok) {
                    showAlert('User deleted!', 'success');
                    loadAdminData();
                }
            } catch (error) {}
        }

        function viewUserFiles(username) {
            window.open(`/api/admin/user-files/${username}`, '_blank');
        }

        function downloadAllUserFiles(username) {
            window.location.href = `/api/admin/download-all/${username}`;
        }

        async function saveSettings() {
            const settings = {
                maintenance_mode: document.getElementById('maintenanceMode').value === 'true',
                maintenance_message: document.getElementById('maintenanceMessageInput').value,
                auto_install_requirements: document.getElementById('autoInstallRequirements').value === 'true',
                check_requirements_on_start: document.getElementById('checkRequirementsOnStart').value === 'true',
                global_upload_limit: parseInt(document.getElementById('globalUploadLimit').value),
                max_file_size: parseInt(document.getElementById('maxFileSizeSetting').value),
                max_bots_per_user: parseInt(document.getElementById('maxBotsPerUser').value)
            };
            
            try {
                const response = await fetch('/api/admin/settings', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(settings)
                });
                
                if (response.ok) {
                    showAlert('Settings saved!', 'success');
                    checkMaintenanceStatus();
                }
            } catch (error) {}
        }

        async function addAnnouncement() {
            const message = document.getElementById('newAnnouncement').value;
            if (!message) return;
            
            try {
                const response = await fetch('/api/admin/announcements', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ message })
                });
                
                if (response.ok) {
                    showAlert('Announcement added!', 'success');
                    document.getElementById('newAnnouncement').value = '';
                    loadAdminData();
                    loadAnnouncements();
                }
            } catch (error) {}
        }

        function deleteAnnouncement(index) {
            if (!confirm('Delete this announcement?')) return;
            
            fetch('/api/admin/announcements', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ index })
            }).then(() => {
                loadAdminData();
                loadAnnouncements();
            });
        }

        function createBackup() {
            if (!confirm('Create a system backup?')) return;
            
            fetch('/api/admin/backup', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        showAlert('Backup created!', 'success');
                    }
                });
        }

        function restoreBackup() {
            if (!confirm('Restore from backup? This will overwrite current data.')) return;
            
            fetch('/api/admin/restore', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        showAlert('Backup restored!', 'success');
                        location.reload();
                    }
                });
        }

        function showAddUserModal() {
            const username = prompt('Enter username:');
            if (!username) return;
            
            const password = prompt('Enter password:');
            if (!password) return;
            
            const limit = prompt('Enter upload limit:', '10');
            
            fetch('/api/admin/users', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    username,
                    password,
                    upload_limit: parseInt(limit)
                })
            }).then(response => {
                if (response.ok) {
                    showAlert('User created!', 'success');
                    loadAdminData();
                }
            });
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
            setTimeout(() => alert.style.display = 'none', 5000);
        }

        function hideModal() {
            document.getElementById('downloadModal').style.display = 'none';
        }

        function startRefreshInterval() {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(() => {
                if (document.getElementById('botsSection').style.display === 'block') loadBots();
                if (document.getElementById('dashboardSection').style.display === 'block') {
                    loadSystemStats();
                    loadAnnouncements();
                }
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
@check_maintenance
def index():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/login')
def login_page():
    settings = load_settings()
    if settings.get('maintenance_mode'):
        return render_template_string(MAINTENANCE_PAGE, message=settings.get('maintenance_message'))
    return LOGIN_PAGE

@app.route('/dashboard')
@login_required
@check_maintenance
def dashboard():
    return DASHBOARD_PAGE

# ==================== API Routes ====================

@app.route('/api/settings', methods=['GET'])
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
        if user.get('status') != 'active':
            return jsonify({'error': 'Account is disabled'}), 403
        
        session.permanent = True
        session['user_id'] = username
        user['last_login'] = datetime.now().isoformat()
        user['last_ip'] = request.remote_addr
        save_users(users)
        
        log_activity(username, 'login', 'User logged in', request.remote_addr)
        
        return jsonify({'success': True, 'redirect': '/dashboard'})
    
    log_activity(username, 'login_failed', f'Failed login attempt for {username}', request.remote_addr)
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/logout')
def api_logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'logout', 'User logged out', request.remote_addr)
    session.clear()
    return redirect('/login')

@app.route('/api/announcements')
def get_announcements():
    announcements = load_announcements()
    return jsonify(announcements)

# ==================== Requirements API Routes ====================

@app.route('/api/requirements/status', methods=['GET'])
def requirements_status():
    status = load_requirements_status()
    return jsonify(status)

@app.route('/api/requirements/check', methods=['POST'])
def requirements_check():
    results = check_all_requirements()
    return jsonify(results)

@app.route('/api/requirements/install', methods=['POST'])
def requirements_install():
    data = request.json
    package = data.get('package')
    
    success, message = install_package(package)
    
    if success:
        check_all_requirements()  # Refresh status
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'error': message}), 400

@app.route('/api/requirements/install-all', methods=['POST'])
def requirements_install_all():
    results = check_all_requirements()
    return jsonify(results)

@app.route('/api/requirements/download', methods=['GET'])
def requirements_download():
    req_path = generate_requirements_file()
    return send_file(req_path, as_attachment=True, download_name='requirements.txt')

# ==================== User API Routes ====================

@app.route('/api/user/stats')
@login_required
@check_maintenance
def user_stats():
    username = session['user_id']
    users = load_users()
    uploads = load_uploads()
    user_uploads = uploads.get(username, [])
    
    total_size = 0
    for upload in user_uploads:
        if upload.get('is_zip'):
            extract_dir = os.path.join(UPLOAD_DIR, username, upload['filename'].replace('.zip', ''))
            if os.path.exists(extract_dir):
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        total_size += os.path.getsize(filepath)
        else:
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
        'upload_count': get_user_upload_count(username),
        'upload_limit': get_user_upload_limit(username),
        'max_bots': get_user_max_bots(username),
        'total_size': total_size,
        'running_bots': user_bots,
        'uploads': user_uploads
    })

@app.route('/api/user/upload', methods=['POST'])
@login_required
@check_maintenance
def user_upload():
    username = session['user_id']
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    settings = load_settings()
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings['allowed_extensions']:
        return jsonify({'error': f'File type not allowed. Allowed: {", ".join(settings["allowed_extensions"])}'}), 400
    
    upload_count = get_user_upload_count(username)
    upload_limit = get_user_upload_limit(username)
    
    if upload_count >= upload_limit:
        return jsonify({'error': f'Upload limit reached ({upload_limit} files)'}), 400
    
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    max_size = settings['max_file_size'] * 1024 * 1024
    if file_size > max_size:
        return jsonify({'error': f'File too large (max {settings["max_file_size"]}MB)'}), 400
    
    user_dir = os.path.join(UPLOAD_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    
    filepath = os.path.join(user_dir, file.filename)
    
    if os.path.exists(filepath):
        return jsonify({'error': 'File already exists'}), 400
    
    file.save(filepath)
    
    main_file = request.form.get('main_file')
    is_zip = file.filename.endswith('.zip')
    
    uploads = load_uploads()
    if username not in uploads:
        uploads[username] = []
    
    upload_info = {
        'filename': file.filename,
        'uploaded_at': datetime.now().isoformat(),
        'size': file_size,
        'is_zip': is_zip
    }
    
    if is_zip and main_file:
        extract_dir = os.path.join(user_dir, file.filename.replace('.zip', ''))
        os.makedirs(extract_dir, exist_ok=True)
        
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        upload_info['main_file'] = main_file
        upload_info['extracted'] = True
    
    uploads[username].append(upload_info)
    save_uploads(uploads)
    
    users = load_users()
    if username in users:
        users[username]['total_uploads'] = users[username].get('total_uploads', 0) + 1
        save_users(users)
    
    log_path = os.path.join(LOG_DIR, username, f"{file.filename}.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, 'a') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"File uploaded at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Filename: {file.filename}\n")
        f.write(f"Size: {format_size(file_size)}\n")
        if is_zip:
            f.write(f"Type: ZIP Archive\n")
            if main_file:
                f.write(f"Main file: {main_file}\n")
        f.write(f"{'='*50}\n\n")
    
    log_activity(username, 'upload', f'Uploaded file: {file.filename}', request.remote_addr)
    
    return jsonify({'success': True, 'message': 'File uploaded successfully'})

@app.route('/api/user/download/<filename>')
@login_required
@check_maintenance
def user_download(filename):
    username = session['user_id']
    filepath = os.path.join(UPLOAD_DIR, username, filename)
    
    if os.path.exists(filepath):
        log_activity(username, 'download', f'Downloaded file: {filename}', request.remote_addr)
        return send_file(filepath, as_attachment=True)
    
    return jsonify({'error': 'File not found'}), 404

@app.route('/api/user/start', methods=['POST'])
@login_required
@check_maintenance
def user_start():
    username = session['user_id']
    data = request.json
    filename = data.get('filename')
    main_file = data.get('main_file')
    
    bot_id, message = start_bot(filename, username, main_file)
    
    if bot_id:
        log_activity(username, 'start_bot', f'Started bot: {filename}', request.remote_addr)
        return jsonify({'success': True, 'bot_id': bot_id})
    return jsonify({'error': message}), 400

@app.route('/api/user/stop', methods=['POST'])
@login_required
@check_maintenance
def user_stop():
    username = session['user_id']
    data = request.json
    bot_id = data.get('bot_id')
    
    bot = running_bots.get(bot_id)
    if not bot or bot['username'] != username:
        return jsonify({'error': 'Bot not found'}), 404
    
    success, message = stop_bot(bot_id)
    
    if success:
        log_activity(username, 'stop_bot', f'Stopped bot: {bot["filename"]}', request.remote_addr)
        return jsonify({'success': True})
    return jsonify({'error': message}), 400

@app.route('/api/user/logs/<filename>')
@login_required
@check_maintenance
def user_logs(filename):
    username = session['user_id']
    
    log_path = os.path.join(LOG_DIR, username, f"{filename}.log")
    
    if request.args.get('download'):
        if os.path.exists(log_path):
            return send_file(log_path, as_attachment=True)
        return jsonify({'error': 'Log not found'}), 404
    
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            return f.read()
    
    return 'No logs available', 404

@app.route('/api/user/delete', methods=['POST'])
@login_required
@check_maintenance
def user_delete():
    username = session['user_id']
    data = request.json
    filename = data.get('filename')
    
    for bot_id, bot in list(running_bots.items()):
        if bot['username'] == username and (bot['filename'] == filename or bot['original_file'] == filename):
            stop_bot(bot_id)
    
    filepath = os.path.join(UPLOAD_DIR, username, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    
    if filename.endswith('.zip'):
        extract_dir = os.path.join(UPLOAD_DIR, username, filename.replace('.zip', ''))
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
    
    log_path = os.path.join(LOG_DIR, username, f"{filename}.log")
    if os.path.exists(log_path):
        os.remove(log_path)
    
    uploads = load_uploads()
    if username in uploads:
        uploads[username] = [u for u in uploads[username] if u['filename'] != filename]
        save_uploads(uploads)
    
    log_activity(username, 'delete', f'Deleted file: {filename}', request.remote_addr)
    
    return jsonify({'success': True})

# ==================== Admin API Routes ====================

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    users = load_users()
    uploads = load_uploads()
    activity = load_activity()
    announcements = load_announcements()
    settings = load_settings()
    
    total_users = len(users)
    total_uploads = sum(len(uploads.get(u, [])) for u in users)
    total_bots = len(running_bots)
    total_bot_starts = sum(u.get('total_bot_starts', 0) for u in users.values())
    
    system_stats = {
        'cpu': psutil.cpu_percent(interval=1),
        'ram': psutil.virtual_memory().percent,
        'disk': psutil.disk_usage('/').percent,
        'running_bots': total_bots
    }
    
    user_details = []
    for username, user_data in users.items():
        user_uploads = uploads.get(username, [])
        user_bots = len([b for b in running_bots.values() if b['username'] == username])
        
        user_details.append({
            'username': username,
            'is_admin': user_data.get('is_admin', False),
            'upload_limit': user_data.get('upload_limit', settings['global_upload_limit']),
            'max_bots': user_data.get('max_bots', settings['max_bots_per_user']),
            'upload_count': len(user_uploads),
            'running_bots': user_bots,
            'created_at': user_data.get('created_at', 'Unknown'),
            'last_login': user_data.get('last_login', 'Never'),
            'last_ip': user_data.get('last_ip', 'Unknown'),
            'status': user_data.get('status', 'active'),
            'notes': user_data.get('notes', ''),
            'total_uploads': user_data.get('total_uploads', 0),
            'total_bot_starts': user_data.get('total_bot_starts', 0)
        })
    
    return jsonify({
        'total_users': total_users,
        'total_uploads': total_uploads,
        'total_bot_starts': total_bot_starts,
        'system': system_stats,
        'users': user_details,
        'user_uploads': uploads,
        'activity': activity[-50:],
        'announcements': announcements,
        'settings': settings
    })

@app.route('/api/admin/users', methods=['POST', 'PUT', 'DELETE'])
@admin_required
def admin_users():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        upload_limit = data.get('upload_limit', load_settings()['global_upload_limit'])
        
        users = load_users()
        if username in users:
            return jsonify({'error': 'User exists'}), 400
        
        users[username] = {
            'password': hash_password(password),
            'is_admin': False,
            'upload_limit': upload_limit,
            'max_bots': load_settings()['max_bots_per_user'],
            'created_at': datetime.now().isoformat(),
            'last_login': None,
            'last_ip': None,
            'status': 'active',
            'notes': '',
            'total_uploads': 0,
            'total_bot_starts': 0
        }
        save_users(users)
        log_activity(session['user_id'], 'admin_create_user', f'Created user: {username}', request.remote_addr)
        return jsonify({'success': True})
    
    elif request.method == 'PUT':
        data = request.json
        username = data.get('username')
        
        users = load_users()
        if username not in users:
            return jsonify({'error': 'User not found'}), 404
        
        if 'upload_limit' in data:
            users[username]['upload_limit'] = data['upload_limit']
        if 'password' in data and data['password']:
            users[username]['password'] = hash_password(data['password'])
        if 'status' in data:
            users[username]['status'] = data['status']
        if 'notes' in data:
            users[username]['notes'] = data['notes']
        
        save_users(users)
        log_activity(session['user_id'], 'admin_update_user', f'Updated user: {username}', request.remote_addr)
        return jsonify({'success': True})
    
    elif request.method == 'DELETE':
        data = request.json
        username = data.get('username')
        
        users = load_users()
        if username not in users:
            return jsonify({'error': 'User not found'}), 404
        
        if username == session['user_id']:
            return jsonify({'error': 'Cannot delete yourself'}), 400
        
        if username == 'sulav':
            return jsonify({'error': 'Cannot delete owner account'}), 400
        
        for bot_id, bot in list(running_bots.items()):
            if bot['username'] == username:
                stop_bot(bot_id)
        
        user_dir = os.path.join(UPLOAD_DIR, username)
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
        
        user_log_dir = os.path.join(LOG_DIR, username)
        if os.path.exists(user_log_dir):
            shutil.rmtree(user_log_dir)
        
        del users[username]
        save_users(users)
        
        uploads = load_uploads()
        if username in uploads:
            del uploads[username]
            save_uploads(uploads)
        
        log_activity(session['user_id'], 'admin_delete_user', f'Deleted user: {username}', request.remote_addr)
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
    if 'auto_install_requirements' in data:
        settings['auto_install_requirements'] = data['auto_install_requirements']
    if 'check_requirements_on_start' in data:
        settings['check_requirements_on_start'] = data['check_requirements_on_start']
    if 'global_upload_limit' in data:
        settings['global_upload_limit'] = int(data['global_upload_limit'])
    if 'max_file_size' in data:
        settings['max_file_size'] = int(data['max_file_size'])
    if 'max_bots_per_user' in data:
        settings['max_bots_per_user'] = int(data['max_bots_per_user'])
    
    save_settings(settings)
    log_activity(session['user_id'], 'admin_settings', 'Updated system settings', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/admin/announcements', methods=['GET', 'POST', 'DELETE'])
@admin_required
def admin_announcements():
    if request.method == 'GET':
        return jsonify(load_announcements())
    
    elif request.method == 'POST':
        data = request.json
        announcements = load_announcements()
        announcements.append({
            'message': data.get('message'),
            'created_by': session['user_id'],
            'created_at': datetime.now().isoformat()
        })
        save_announcements(announcements)
        log_activity(session['user_id'], 'admin_announcement', 'Added announcement', request.remote_addr)
        return jsonify({'success': True})
    
    elif request.method == 'DELETE':
        data = request.json
        index = data.get('index')
        announcements = load_announcements()
        if 0 <= index < len(announcements):
            announcements.pop(index)
            save_announcements(announcements)
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
    
    return jsonify({'username': username, 'files': files})

@app.route('/api/admin/download-all/<username>')
@admin_required
def admin_download_all(username):
    user_dir = os.path.join(UPLOAD_DIR, username)
    if not os.path.exists(user_dir):
        return jsonify({'error': 'No files found'}), 404
    
    zip_path = os.path.join(TEMP_DIR, f"{username}_files_{int(time.time())}.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, dirs, files in os.walk(user_dir):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, user_dir)
                zipf.write(filepath, arcname)
    
    log_activity(session['user_id'], 'admin_download_all', f'Downloaded all files for: {username}', request.remote_addr)
    return send_file(zip_path, as_attachment=True, download_name=f"{username}_files.zip")

@app.route('/api/admin/backup', methods=['POST'])
@admin_required
def admin_backup():
    backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    os.makedirs(backup_path, exist_ok=True)
    
    shutil.copytree(CONFIG_DIR, os.path.join(backup_path, 'config'))
    
    uploads = load_uploads()
    with open(os.path.join(backup_path, 'uploads.json'), 'w') as f:
        json.dump(uploads, f, indent=2)
    
    log_activity(session['user_id'], 'admin_backup', f'Created backup: {backup_name}', request.remote_addr)
    return jsonify({'success': True, 'backup': backup_name})

@app.route('/api/admin/restore', methods=['POST'])
@admin_required
def admin_restore():
    data = request.json
    backup_name = data.get('backup')
    
    if not backup_name:
        backups = os.listdir(BACKUP_DIR)
        return jsonify({'backups': backups})
    
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    if not os.path.exists(backup_path):
        return jsonify({'error': 'Backup not found'}), 404
    
    shutil.rmtree(CONFIG_DIR)
    shutil.copytree(os.path.join(backup_path, 'config'), CONFIG_DIR)
    
    log_activity(session['user_id'], 'admin_restore', f'Restored from backup: {backup_name}', request.remote_addr)
    return jsonify({'success': True})

@app.route('/api/system')
def system():
    try:
        return jsonify({
            'cpu': psutil.cpu_percent(),
            'ram': psutil.virtual_memory().percent,
            'disk': psutil.disk_usage('/').percent,
            'running_bots': len(running_bots),
            'uptime': time.time() - psutil.boot_time()
        })
    except:
        return jsonify({'cpu': 0, 'ram': 0, 'disk': 0, 'running_bots': 0, 'uptime': 0})

# ==================== Run Application ====================

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)