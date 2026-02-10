from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
import sqlite3
import os
import subprocess
import sys
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import cv2
import numpy as np
from collections import deque
import threading
import json
import time
import mediapipe as mp
from dotenv import load_dotenv
from dotenv import load_dotenv
# from gemini_analyzer import GeminiActivityAnalyzer # Removed in favor of ai_manager
from medical_rag import MedicalChatbot

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret_key")

@app.template_filter('from_json')
def from_json_filter(s):
    try:
        if not s: return {}
        # s can be a dict if coming from memory or a string if from DB
        if isinstance(s, dict): return s
        
        # Clean up common AI markdown artifacts
        if isinstance(s, str):
            import re
            # Extract content between first { and last }
            json_match = re.search(r'(\{.*\})', s, re.DOTALL)
            if json_match:
                s = json_match.group(1)
            else:
                s = s.replace('```json', '').replace('```', '').strip()
                
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except:
        return {}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "patients.db")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Global video capture object
video_capture = None
monitoring_active = False
monitoring_lock = threading.Lock()

# ---------------- DATABASE MANAGEMENT ----------------
class Database:
    @staticmethod
    def get_connection():
        """Get database connection with row factory"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    @staticmethod
    def init_db():
        """Initialize all database tables"""
        conn = Database.get_connection()
        cursor = conn.cursor()

        # Patients table - Enhanced with more fields
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            password_hash TEXT NOT NULL,
            address TEXT,
            emergency_contact TEXT,
            emergency_phone TEXT,
            medical_conditions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """)
        
        # Ensure Default Patient 1 exists for Guest access
        try:
             cursor.execute("SELECT id FROM patients WHERE id = 1")
             if not cursor.fetchone():
                 cursor.execute("INSERT INTO patients (id, name, age, gender, phone, password_hash) VALUES (1, 'Guest', 0, 'Unknown', '000000', 'hashed')")
                 conn.commit()
        except: pass

        # Activities log table - Enhanced
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            patient_name TEXT,
            activity TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            duration_seconds INTEGER DEFAULT 0,
            notes TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
        """)

        # Activity sessions table - Track monitoring sessions
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitoring_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            patient_name TEXT,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            duration_minutes INTEGER,
            total_activities INTEGER DEFAULT 0,
            camera_url TEXT,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
        """)

        # Emergency alerts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS emergency_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            patient_name TEXT,
            alert_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            description TEXT,
            is_resolved INTEGER DEFAULT 0,
            resolved_by TEXT,
            resolved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
        """)

        # System settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,
            setting_value TEXT NOT NULL,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Insert default camera settings if not exists
        cursor.execute("""
        INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description)
        VALUES ('camera_url', '0', 'Camera source URL or device index')
        """)

        cursor.execute("""
        INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description)
        VALUES ('detection_confidence', '0.5', 'Minimum confidence threshold for activity detection')
        """)

        cursor.execute("""
        INSERT OR IGNORE INTO system_settings (setting_key, setting_value, description)
        VALUES ('alert_enabled', '1', 'Enable/disable emergency alerts')
        """)

        conn.commit()
        
        # Gemini analysis logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS gemini_analysis_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            patient_name TEXT,
            analysis_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
        """)

        # Gemini raw logs table (Removed by request)
        # Gemini raw logs table (Enabled)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS gemini_raw_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        )
        """)
        
        conn.commit()
        conn.close()

    @staticmethod
    def log_gemini_analysis(patient_id, patient_name, analysis_text):
        """Log Gemini analysis results"""
        try:
            query = """
            INSERT INTO gemini_analysis_logs (patient_id, patient_name, analysis_text)
            VALUES (?, ?, ?)
            """
            Database.execute_query(query, (patient_id, patient_name, analysis_text))
            return True
        except Exception as e:
            print(f"Error logging Gemini analysis: {e}")
            return False

    @staticmethod
    def execute_query(query, params=(), fetch_one=False, fetch_all=False):
        """Execute a database query with error handling"""
        try:
            conn = Database.get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                conn.commit()
                result = cursor.lastrowid
            
            conn.close()
            return result
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return None

    @staticmethod
    def get_setting(key, default=None):
        """Get a system setting value"""
        result = Database.execute_query(
            "SELECT setting_value FROM system_settings WHERE setting_key = ?",
            (key,),
            fetch_one=True
        )
        return result['setting_value'] if result else default

    @staticmethod
    def update_setting(key, value):
        """Update a system setting"""
        return Database.execute_query(
            """UPDATE system_settings 
               SET setting_value = ?, updated_at = CURRENT_TIMESTAMP 
               WHERE setting_key = ?""",
            (value, key)
        )

# Initialize database on startup
Database.init_db()

# ---------------- HELPER FUNCTIONS ----------------
def login_required(f):
    """Decorator to require login for routes"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get current logged in user details"""
    if 'user_id' in session:
        return Database.execute_query(
            "SELECT * FROM patients WHERE id = ?",
            (session['user_id'],),
            fetch_one=True
        )
    return None

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return redirect(url_for('login'))

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        phone = request.form.get("phone")
        email = request.form.get("email", "")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        address = request.form.get("address", "")
        emergency_contact = request.form.get("emergency_contact", "")
        emergency_phone = request.form.get("emergency_phone", "")
        medical_conditions = request.form.get("medical_conditions", "")

        # Validation
        if not all([name, age, gender, phone, password]):
            flash("Please fill all required fields", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("register.html")

        # Check if phone already exists
        existing = Database.execute_query(
            "SELECT id FROM patients WHERE phone = ?",
            (phone,),
            fetch_one=True
        )
        
        if existing:
            flash("Phone number already registered", "error")
            return render_template("register.html")

        # Hash password
        password_hash = generate_password_hash(password)

        # Insert new patient
        patient_id = Database.execute_query(
            """INSERT INTO patients 
               (name, age, gender, phone, email, password_hash, address, 
                emergency_contact, emergency_phone, medical_conditions)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, age, gender, phone, email, password_hash, address,
             emergency_contact, emergency_phone, medical_conditions)
        )

        if patient_id:
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Registration failed. Please try again.", "error")

    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone")
        password = request.form.get("password")

        patient = Database.execute_query(
            "SELECT * FROM patients WHERE phone = ? AND is_active = 1",
            (phone,),
            fetch_one=True
        )

        if patient and check_password_hash(patient['password_hash'], password):
            session['user_id'] = patient['id']
            session['user_name'] = patient['name']
            flash(f"Welcome back, {patient['name']}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid phone or password", "error")

    return render_template("login.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    
    # Get statistics
    total_activities = Database.execute_query(
        "SELECT COUNT(*) as count FROM activities WHERE patient_id = ?",
        (session['user_id'],),
        fetch_one=True
    )['count']
    
    total_sessions = Database.execute_query(
        "SELECT COUNT(*) as count FROM monitoring_sessions WHERE patient_id = ?",
        (session['user_id'],),
        fetch_one=True
    )['count']
    
    recent_activities = Database.execute_query(
        """SELECT * FROM activities 
           WHERE patient_id = ? 
           ORDER BY timestamp DESC 
           LIMIT 5""",
        (session['user_id'],),
        fetch_all=True
    )
    
    # Get camera URL
    camera_url = Database.get_setting('camera_url', '0')
    
    return render_template(
        "dashboard.html",
        user=user,
        total_activities=total_activities,
        total_sessions=total_sessions,
        recent_activities=recent_activities,
        monitoring=monitoring_active,
        camera_url=camera_url
    )

# ---------------- PROFILE ----------------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        email = request.form.get("email")
        address = request.form.get("address")
        emergency_contact = request.form.get("emergency_contact")
        emergency_phone = request.form.get("emergency_phone")
        medical_conditions = request.form.get("medical_conditions")

        Database.execute_query(
            """UPDATE patients 
               SET name = ?, age = ?, email = ?, address = ?,
                   emergency_contact = ?, emergency_phone = ?, 
                   medical_conditions = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (name, age, email, address, emergency_contact, 
             emergency_phone, medical_conditions, session['user_id'])
        )

        flash("Profile updated successfully!", "success")
        return redirect(url_for("profile"))

    user = get_current_user()
    return render_template("profile.html", user=user)

# ---------------- CAMERA SETTINGS ----------------
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        camera_url = request.form.get("camera_url")
        detection_confidence = request.form.get("detection_confidence")
        alert_enabled = request.form.get("alert_enabled", "0")

        Database.update_setting("camera_url", camera_url)
        Database.update_setting("detection_confidence", detection_confidence)
        Database.update_setting("alert_enabled", alert_enabled)

        flash("Settings updated successfully!", "success")
        return redirect(url_for("settings"))

    camera_url = Database.get_setting('camera_url', '0')
    detection_confidence = Database.get_setting('detection_confidence', '0.5')
    alert_enabled = Database.get_setting('alert_enabled', '1')

    return render_template(
        "settings.html",
        camera_url=camera_url,
        detection_confidence=detection_confidence,
        alert_enabled=alert_enabled
    )

# ---------------- START MONITORING ----------------
@app.route("/start_monitoring")
@login_required
def start_monitoring():
    global monitoring_active
    
    camera_url = Database.get_setting('camera_url', '0')
    
    # Start monitoring session
    session_id = Database.execute_query(
        """INSERT INTO monitoring_sessions 
           (patient_id, patient_name, camera_url)
           VALUES (?, ?, ?)""",
        (session['user_id'], session['user_name'], camera_url)
    )
    
    # Store session ID
    session['monitoring_session_id'] = session_id
    monitoring_active = True
    
    flash("Monitoring started successfully!", "success")
    return redirect(url_for("dashboard"))

# ---------------- STOP MONITORING ----------------
@app.route("/stop_monitoring")
@login_required
def stop_monitoring():
    global monitoring_active, video_capture
    
    monitoring_active = False
    
    if video_capture is not None:
        video_capture.release()
        video_capture = None
    
    # Update monitoring session
    if 'monitoring_session_id' in session:
        Database.execute_query(
            """UPDATE monitoring_sessions 
               SET end_time = CURRENT_TIMESTAMP,
                   status = 'completed'
               WHERE id = ?""",
            (session['monitoring_session_id'],)
        )
    
    flash("Monitoring stopped", "info")
    return redirect(url_for("dashboard"))

# ---------------- VIEW ACTIVITIES ----------------
@app.route("/view_activities")
@login_required
def view_activities():
    activities = Database.execute_query(
        """SELECT * FROM activities 
           WHERE patient_id = ? 
           ORDER BY timestamp DESC""",
        (session['user_id'],),
        fetch_all=True
    )
    
    
    
    # Fetch Combined Gemini Analysis & Raw Data
    # JOINing on created_at since they are inserted with the same timestamp
    gemini_logs = Database.execute_query(
        """SELECT a.id, a.created_at, a.analysis_text, r.raw_json 
           FROM gemini_analysis_logs a 
           LEFT JOIN gemini_raw_logs r ON a.created_at = r.created_at AND a.patient_id = r.patient_id
           WHERE a.patient_id = ? 
           ORDER BY a.created_at DESC""",
        (session['user_id'],),
        fetch_all=True
    )
    
    return render_template("activities.html", activities=activities, gemini_logs=gemini_logs)

# ---------------- DELETE LOGS ----------------
@app.route("/delete_logs", methods=['POST'])
@login_required
def delete_logs():
    time_range = request.form.get('time_range')
    
    conn = Database.get_connection()
    c = conn.cursor()
    
    try:
        if time_range == 'all':
            c.execute("DELETE FROM activities WHERE patient_id = ?", (session['user_id'],))
            c.execute("DELETE FROM gemini_analysis_logs WHERE patient_id = ?", (session['user_id'],))
            c.execute("DELETE FROM gemini_raw_logs WHERE patient_id = ?", (session['user_id'],))
            c.execute("DELETE FROM emergency_alerts WHERE patient_id = ?", (session['user_id'],))
            flash("All logs have been permanently deleted.", "success")
            
        elif time_range:
            # Calculate cutoff time
            import datetime
            hours = int(time_range)
            cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
            
            c.execute("DELETE FROM activities WHERE patient_id = ? AND timestamp < ?", (session['user_id'], cutoff))
            c.execute("DELETE FROM gemini_analysis_logs WHERE patient_id = ? AND created_at < ?", (session['user_id'], cutoff))
            c.execute("DELETE FROM gemini_raw_logs WHERE patient_id = ? AND created_at < ?", (session['user_id'], cutoff))
            c.execute("DELETE FROM emergency_alerts WHERE patient_id = ? AND created_at < ?", (session['user_id'], cutoff))
            
            flash(f"Logs older than {hours} hours have been deleted.", "success")
            
        conn.commit()
    except Exception as e:
        flash(f"Error deleting logs: {e}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('view_activities'))

# ---------------- API STATUS ----------------
@app.route("/api/status")
def api_status():
    """Health check endpoint"""
    return jsonify({
        "status": "online",
        "monitoring": monitoring_active,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })

# ---------------- VIEW SESSIONS ----------------
@app.route("/view_sessions")
@login_required
def view_sessions():
    sessions_list = Database.execute_query(
        """SELECT * FROM monitoring_sessions 
           WHERE patient_id = ? 
           ORDER BY start_time DESC""",
        (session['user_id'],),
        fetch_all=True
    )
    
    return render_template("sessions.html", sessions=sessions_list)

# ---------------- ALERTS ----------------
@app.route("/alerts")
@login_required
def alerts():
    alerts_list = Database.execute_query(
        """SELECT * FROM emergency_alerts 
           WHERE patient_id = ? 
           ORDER BY created_at DESC""",
        (session['user_id'],),
            fetch_all=True
        )
    
    return render_template("alerts.html", alerts=alerts_list)

@app.route("/resolve_alert/<int:alert_id>", methods=["POST"])
@login_required
def resolve_alert(alert_id):
    """Resolve an emergency alert"""
    try:
        Database.execute_query(
            """UPDATE emergency_alerts 
               SET is_resolved = 1, 
                   resolved_at = CURRENT_TIMESTAMP,
                   resolved_by = ?
               WHERE id = ?""",
            (session['user_name'], alert_id)
        )
        flash("Alert resolved successfully!", "success")
    except Exception as e:
        flash(f"Error resolving alert: {str(e)}", "error")
    
    return redirect(url_for("alerts"))

# ---------------- API ENDPOINTS ----------------
@app.route("/api/log_activity", methods=["POST"])
def api_log_activity():
    """API endpoint for logging activities from monitoring script"""
    data = request.json
    
    activity_id = Database.execute_query(
        """INSERT INTO activities 
           (patient_id, patient_name, activity, confidence, notes)
           VALUES (?, ?, ?, ?, ?)""",
        (data.get('patient_id'), data.get('patient_name'), 
         data.get('activity'), data.get('confidence', 1.0),
         data.get('notes', ''))
    )
    
    return jsonify({'status': 'success', 'activity_id': activity_id})

@app.route("/api/create_alert", methods=["POST"])
def api_create_alert():
    """API endpoint for creating emergency alerts"""
    data = request.json
    
    alert_id = Database.execute_query(
        """INSERT INTO emergency_alerts 
           (patient_id, patient_name, alert_type, severity, description)
           VALUES (?, ?, ?, ?, ?)""",
        (data.get('patient_id'), data.get('patient_name'),
         data.get('alert_type'), data.get('severity', 'medium'),
         data.get('description', ''))
    )
    
    return jsonify({'status': 'success', 'alert_id': alert_id})

@app.route("/api/get_settings")
def api_get_settings():
    """API endpoint to get system settings"""
    return jsonify({
        'camera_url': Database.get_setting('camera_url', '0'),
        'detection_confidence': float(Database.get_setting('detection_confidence', '0.5')),
        'alert_enabled': int(Database.get_setting('alert_enabled', '1'))
    })

# ---------------- ACTIVITY DETECTION ----------------

class ActivityDetector:
    """Real-time activity detection using MediaPipe + ML Classifier"""
    
    def __init__(self):
        # Determine detection mode - Try Tasks API with multiple landmarkers
        self.mode = "HOLISTIC"
        self.frame_timestamp_ms = 0
        
        try:
            # Use MediaPipe Tasks API for pose + hands + face
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            import mediapipe as mp
            
            # Initialize Pose Landmarker
            pose_model_path = os.path.join(BASE_DIR, "pose_landmarker.task")
            if not os.path.exists(pose_model_path):
                print(f"⚠️ Downloading pose model...")
                import urllib.request
                url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task"
                urllib.request.urlretrieve(url, pose_model_path)
            
            pose_options = vision.PoseLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=pose_model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
            
            # Initialize Hand Landmarker
            hand_model_path = os.path.join(BASE_DIR, "hand_landmarker.task")
            if not os.path.exists(hand_model_path):
                print(f"⚠️ Downloading hand model...")
                import urllib.request
                url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
                urllib.request.urlretrieve(url, hand_model_path)
                
            hand_options = vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=hand_model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.hand_landmarker = vision.HandLandmarker.create_from_options(hand_options)
            
            # Store MediaPipe utilities
            self.mp_Image = mp.Image
            self.mp_ImageFormat = mp.ImageFormat
            
            print("✅ Using MediaPipe Tasks API - Holistic Mode (Image)")
            print("   - Pose Landmarker: 33 landmarks")
            print("   - Hand Landmarker: 21 landmarks per hand")
            print("   - Combined tracking for comprehensive activity detection")
            
        except Exception as e:
            print(f"⚠️ MediaPipe Tasks failed ({e}). Using MOG2 fallback.")
            self.mode = "MOG2"
            self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=500, varThreshold=16, detectShadows=True
            )
            self.motion_history = deque(maxlen=10)
            self.prev_center_y = None
        
        # Activity tracking
        self.activity_buffer = deque(maxlen=20)
        self.current_activity = "None"
        self.last_logged_activity = None
        self.last_log_time = 0
        
        # Emergency detection
        self.fall_detection_frames = 0
        self.lying_start_time = None
        self.last_alert_time = 0
        
        # Advanced movement tracking
        self.prev_lk_y = None
        self.prev_landmarks = None
        self.hand_movement_history = deque(maxlen=30)
        self.head_movement_history = deque(maxlen=30)
        self.limb_velocity_history = deque(maxlen=30)
        
        # Specific activity buffers
        self.eating_frames = 0
        self.drinking_frames = 0
        self.waving_frames = 0
        self.clapping_frames = 0
        self.reading_frames = 0
        self.writing_frames = 0
        self.phone_frames = 0
        self.distress_frames = 0
        self.seizure_frames = 0
        self.exercise_frames = 0
        self.reaching_frames = 0
        self.bending_frames = 0
        
        # Initialize Gemini Analysis
        # Use Gemini API key from environment variable
        # gemini_key = os.getenv("GEMINI_API_KEY")  
        # self.gemini_analyzer = GeminiActivityAnalyzer(gemini_key, analysis_interval=60) # REPLACED BY AI MANAGER
        
        # --- ULTIMATE MONITOR BUFFERS (User Request) ---
        self.nose_speed_buffer = deque(maxlen=5)
        self.hand_jitter_buffer = deque(maxlen=15)
        self.prev_nose_y = None
        
        print(f"🎯 Activity Detector initialized in {self.mode} mode")
        
    def warmup(self, cap):
        """Warmup phase for background models"""
        if self.mode == "MOG2":
            print("Warming up background model...")
            for _ in range(30):
                ret, frame = cap.read()
                if ret:
                    self.bg_subtractor.apply(cv2.flip(frame, 1))
            print("Warmup done")

    def calculate_angle(self, a, b, c):
        """Calculate angle between three points"""
        a = np.array([a.x, a.y])
        b = np.array([b.x, b.y])
        c = np.array([c.x, c.y])
        ba = a - b
        bc = c - b
        cos = np.dot(ba, bc) / (np.linalg.norm(ba)*np.linalg.norm(bc) + 1e-6)
        return np.degrees(np.arccos(np.clip(cos, -1, 1)))
        
    def calculate_distance(self, p1, p2):
        """Calculate 2D distance between two landmarks"""
        return np.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2)
    
    def calculate_3d_distance(self, p1, p2):
        """Calculate 3D distance including depth"""
        return np.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2 + (p1.z - p2.z)**2)

    def detect_activity_holistic(self, results, frame_shape, patient_info=None):
        """Detect activity and extract raw kinematics for Gemini analysis"""
        detected = "None"
        confidence = 0.0
        status = "Monitoring: Normal"
        kinematics = {}
        
        if not results.pose_landmarks:
            return detected, confidence, status, kinematics

        plm = results.pose_landmarks
        
        # Coordinates
        nose = plm[0]
        l_wrist, r_wrist = plm[15], plm[16]
        l_ankle, r_ankle = plm[27], plm[28]
        l_hip, r_hip = plm[23], plm[24]
        l_shoulder, r_shoulder = plm[11], plm[12]
        l_ear, r_ear = plm[7], plm[8]
        hip_y = (l_hip.y + r_hip.y) / 2
        
        frame_activity = "Normal"
        confidence = 0.5
        
        # --- KINEMATICS EXTRACTION ---
        # 1. Torso Angle (Posture)
        # Calculate angle of torso relative to vertical (0 deg = vertical)
        neck_x = (l_shoulder.x + r_shoulder.x) / 2
        neck_y = (l_shoulder.y + r_shoulder.y) / 2
        torso_angle = np.degrees(np.arctan2(abs(neck_x - l_hip.x), abs(neck_y - l_hip.y)))
        
        # 2. Nose Velocity (Sudden drops)
        nose_speed = 0.0
        if self.prev_nose_y is not None:
            nose_speed = (nose.y - self.prev_nose_y)
            self.nose_speed_buffer.append(nose_speed)
        self.prev_nose_y = nose.y
        
        # 3. Hand Jitter (Tremors)
        hand_jitter = 0.0
        
        kinematics = {
            "nose_y": round(nose.y, 3),
            "nose_velocity": round(nose_speed, 4),
            "torso_angle": round(torso_angle, 1),
            "hands_above_head": l_wrist.y < l_ear.y or r_wrist.y < r_ear.y,
            "feet_spread": round(abs(l_ankle.x - r_ankle.x), 3),
            "on_floor": nose.y > hip_y and hip_y > 0.2
        }

        # B. Positional Filters
        if "CRITICAL" not in frame_activity:
            if nose.y > hip_y and hip_y > 0.2:
                frame_activity = "EMERGENCY: Patient on Floor"
                detected = "Fallen/Lying"
                status = "⚠️ Patient on Floor"
                confidence = 0.95
            elif l_wrist.y < l_ear.y and r_wrist.y < r_ear.y:
                frame_activity = "ALERT: Surrender/Both Hands Up"
                detected = "Hands Up"
                status = "Both Hands Raised"
                confidence = 0.90
            elif l_wrist.y < l_ear.y or r_wrist.y < r_ear.y:
                frame_activity = "ALERT: Hand Raised for Help"
                detected = "Help Signal"
                status = "One Hand Raised"
                confidence = 0.85
            elif abs(l_shoulder.y - l_hip.y) < 0.12:
                frame_activity = "Status: Resting/Lying"
                detected = "Resting"
                status = "Horizontal Posture"
                confidence = 0.80
        
        # C. Proximity Filter (Wandering/Leaving Bed)
        if "CRITICAL" not in frame_activity and "ALERT" not in frame_activity:
            if nose.x < 0.1 or nose.x > 0.9:
                frame_activity = "WARNING: Patient Exiting View"
                detected = "Leaving View"
                status = "Near Edge of Frame"
                confidence = 0.75

        # D. Hand-to-Body Multi-Filters
        # Check both hands (Tasks API separates them, user code iterated simple list)
        # We'll check presence of either hand
        hands_list = []
        if results.left_hand_landmarks: hands_list.append(results.left_hand_landmarks)
        if results.right_hand_landmarks: hands_list.append(results.right_hand_landmarks)
        
        if hands_list:
            for h_lms in hands_list:
                # MediaPipe Hand Landmarks: 8 is index tip, 4 is thumb tip
                idx_tip = h_lms[8]
                
                dist_to_nose = np.sqrt((idx_tip.x-nose.x)**2 + (idx_tip.y-nose.y)**2)
                dist_to_ears = min(np.sqrt((idx_tip.x-l_ear.x)**2 + (idx_tip.y-l_ear.y)**2),
                                   np.sqrt((idx_tip.x-r_ear.x)**2 + (idx_tip.y-r_ear.y)**2))
                
                if dist_to_nose < 0.07:
                    frame_activity = "Patient: Hydrating/Eating"
                    detected = "Eating/Drinking"
                    status = "Hand near mouth"
                    confidence = 0.85
                elif dist_to_nose < 0.12 and idx_tip.y < nose.y:
                    frame_activity = "Status: Coughing/Sneezing"
                    detected = "Coughing"
                    status = "Hand covering mouth"
                    confidence = 0.80
                elif dist_to_ears < 0.08:
                    frame_activity = "Status: Possible Headache/Ear Pain"
                    detected = "Headache/Pain"
                    status = "Hand near ear"
                    confidence = 0.80
                elif idx_tip.y > nose.y and idx_tip.y < hip_y and dist_to_nose < 0.15:
                     frame_activity = "CRITICAL: Chest Pain/Distress"
                     detected = "Chest Pain"
                     status = "⚠️ Hand clutching chest"
                     confidence = 0.92
                     
                # E. Agitation/Seizure Filter (Hand Jitter)
                # Wrist is index 0 in hand model
                wrist = h_lms[0]
                self.hand_jitter_buffer.append((wrist.x, wrist.y))

        if len(self.hand_jitter_buffer) == 15:
            jitter = np.var(self.hand_jitter_buffer, axis=0).sum()
            kinematics["hand_jitter"] = round(jitter, 5)
            if jitter > 0.008:
                frame_activity = "WARNING: Patient Agitated/Shaking"
                detected = "Agitated/Seizure"
                status = "⚠️ High tremor detected"
                confidence = 0.88

        # --- DYNAMIC FILTERS (Sudden Fall re-check) ---
        if kinematics["nose_velocity"] > 0.05:
            frame_activity = "CRITICAL: SUDDEN FALL!"
            detected = "Sudden Fall"
            status = "⚠️ Rapid Downward Velocity"
            confidence = 0.95
                
        # Handle "Normal" case explicitly with Basic Pose Classification
        if detected == "None" and frame_activity == "Normal":
            try:
                # Check Thigh Orientation for Sitting vs Standing
                l_knee_y, r_knee_y = plm[25].y, plm[26].y
                l_ankle_y, r_ankle_y = plm[27].y, plm[28].y
                
                # Check if legs are visible
                if l_knee_y > 0 and r_knee_y > 0:
                     l_thigh_y_span = abs(l_hip.y - l_knee_y)
                     l_thigh_x_span = abs(l_hip.x - plm[25].x)
                     
                     # If thigh is more horizontal -> Sitting
                     if l_thigh_y_span < l_thigh_x_span * 1.5: # Generous threshold for sitting
                         detected = "Sitting"
                         status = "Posture: Seated"
                         confidence = 0.75
                     else:
                         detected = "Standing"
                         status = "Posture: Standing" 
                         confidence = 0.70
                         
                         # Simple Walking Check (Oscillation or Feet spread)
                         if abs(plm[27].x - plm[28].x) > 0.15 and abs(plm[27].y - plm[28].y) > 0.05:
                              detected = "Walking"
                              status = "Action: Walking"
                else:
                     detected = "Standing" # Default
                     status = "Monitoring"
            except:
                detected = "Standing" # Fallback
                status = "Monitoring"
        
        # If user code set frame_activity but didn't set 'detected' (custom parsing fallback)
        if detected == "None" and frame_activity != "Normal":
            detected = frame_activity.split(":")[-1].strip()
        
        # Add frame activity to kinematics for context
        kinematics["rule_based_hint"] = frame_activity
            
        return detected, confidence, status, kinematics
        
    def _has_rapid_limb_movement(self, landmarks):
        """Detect rapid chaotic limb movement (seizure indicator) - VERY STRICT to prevent false positives"""
        if self.prev_landmarks is None:
            self.prev_landmarks = landmarks
            return False
        
        # Track wrists and ankles
        current_limbs = [landmarks[15], landmarks[16], landmarks[27], landmarks[28]]
        prev_limbs = [self.prev_landmarks[15], self.prev_landmarks[16], 
                     self.prev_landmarks[27], self.prev_landmarks[28]]
        
        # Calculate velocities for each limb
        velocities = []
        for curr, prev in zip(current_limbs, prev_limbs):
            velocity = np.sqrt((curr.x - prev.x)**2 + (curr.y - prev.y)**2)
            velocities.append(velocity)
            self.limb_velocity_history.append(velocity)
        
        self.prev_landmarks = landmarks
        
        # Need enough history
        if len(self.limb_velocity_history) < 20:
            return False
        
        # Calculate statistics
        recent_velocities = list(self.limb_velocity_history)[-20:]
        velocity_mean = np.mean(recent_velocities)
        velocity_variance = np.var(recent_velocities)
        
        # MUCH STRICTER THRESHOLDS to prevent false positives
        # - High variance indicates chaotic movement
        # - High mean indicates rapid movement
        # - Both must be present for seizure
        is_chaotic = velocity_variance > 0.20  # Increased from 0.10
        is_rapid = velocity_mean > 0.25  # Increased from 0.15
        
        return is_chaotic and is_rapid      

    def draw_holistic_landmarks(self, frame, results):
        """Draw all holistic landmarks (pose, hands) from Tasks API"""
        h, w = frame.shape[:2]
        
        # Define connections for pose (same as MediaPipe Pose)
        POSE_CONNECTIONS = [
            (11, 12), (11, 23), (12, 24), (23, 24),  # Torso
            (23, 25), (24, 26), (25, 27), (26, 28),  # Legs
            (27, 29), (28, 30), (29, 31), (30, 32),  # Feet
            (11, 13), (13, 15), (12, 14), (14, 16),  # Arms
            (15, 17), (15, 19), (15, 21), (17, 19),  # Left hand
            (16, 18), (16, 20), (16, 22), (18, 20)   # Right hand
        ]
        
        HAND_CONNECTIONS = [
            (0, 1), (1, 2), (2, 3), (3, 4),  # Thumb
            (0, 5), (5, 6), (6, 7), (7, 8),  # Index
            (0, 9), (9, 10), (10, 11), (11, 12),  # Middle
            (0, 13), (13, 14), (14, 15), (15, 16),  # Ring
            (0, 17), (17, 18), (18, 19), (19, 20),  # Pinky
            (5, 9), (9, 13), (13, 17)  # Palm
        ]
        
        # Draw pose landmarks
        if results.pose_landmarks:
            landmarks = results.pose_landmarks
            # Draw connections
            for connection in POSE_CONNECTIONS:
                start_idx, end_idx = connection
                if start_idx < len(landmarks) and end_idx < len(landmarks):
                    start = landmarks[start_idx]
                    end = landmarks[end_idx]
                    
                    start_point = (int(start.x * w), int(start.y * h))
                    end_point = (int(end.x * w), int(end.y * h))
                    
                    cv2.line(frame, start_point, end_point, (255, 255, 255), 2)
            
            # Draw points
            for idx, landmark in enumerate(landmarks):
                if hasattr(landmark, 'visibility') and landmark.visibility < 0.5:
                    continue
                point = (int(landmark.x * w), int(landmark.y * h))
                cv2.circle(frame, point, 4, (0, 0, 255), -1)
        
        # Draw left hand landmarks
        if results.left_hand_landmarks:
            landmarks = results.left_hand_landmarks
            # Draw connections
            for connection in HAND_CONNECTIONS:
                start_idx, end_idx = connection
                if start_idx < len(landmarks) and end_idx < len(landmarks):
                    start = landmarks[start_idx]
                    end = landmarks[end_idx]
                    
                    start_point = (int(start.x * w), int(start.y * h))
                    end_point = (int(end.x * w), int(end.y * h))
                    
                    cv2.line(frame, start_point, end_point, (0, 255, 255), 3)
            
            # Draw points
            for landmark in landmarks:
                point = (int(landmark.x * w), int(landmark.y * h))
                cv2.circle(frame, point, 5, (0, 255, 0), -1)
        
        # Draw right hand landmarks
        if results.right_hand_landmarks:
            landmarks = results.right_hand_landmarks
            # Draw connections
            for connection in HAND_CONNECTIONS:
                start_idx, end_idx = connection
                if start_idx < len(landmarks) and end_idx < len(landmarks):
                    start = landmarks[start_idx]
                    end = landmarks[end_idx]
                    
                    start_point = (int(start.x * w), int(start.y * h))
                    end_point = (int(end.x * w), int(end.y * h))
                    
                    cv2.line(frame, start_point, end_point, (0, 255, 255), 3)
            
            # Draw points
            for landmark in landmarks:
                point = (int(landmark.x * w), int(landmark.y * h))
                cv2.circle(frame, point, 5, (0, 255, 0), -1)


    def detect_activity(self, frame, patient_info=None):
        """Detect activity using MediaPipe Tasks API or MOG2 fallback"""
        
        # ================== HOLISTIC MODE (Tasks API with Pose + Hands) ==================
        if self.mode == "HOLISTIC":
            # Convert to RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = self.mp_Image(image_format=self.mp_ImageFormat.SRGB, data=rgb)
            
            # Timestamp must be monotonic
            # self.frame_timestamp_ms += 33  # assume ~30fps
            
            try:
                # Run pose detection
                pose_result = self.pose_landmarker.detect(mp_image)
                
                # Run hand detection
                hand_result = self.hand_landmarker.detect(mp_image)
                
                # Combine results into a holistic-like structure
                class HolisticResults:
                    def __init__(self):
                        self.pose_landmarks = None
                        self.left_hand_landmarks = None
                        self.right_hand_landmarks = None
                        self.face_landmarks = None
                
                results = HolisticResults()
                
                # Set pose landmarks
                if pose_result.pose_landmarks:
                    results.pose_landmarks = pose_result.pose_landmarks[0]
                
                # Set hand landmarks (Tasks API uses handedness to determine left/right)
                if hand_result.hand_landmarks:
                    for idx, landmarks in enumerate(hand_result.hand_landmarks):
                        if idx < len(hand_result.handedness):
                            handedness = hand_result.handedness[idx][0].category_name
                            if handedness == "Left":
                                results.left_hand_landmarks = landmarks
                            else:  # "Right"
                                results.right_hand_landmarks = landmarks
                
                # Use the holistic detection logic
                detected, confidence, status, kinematics = self.detect_activity_holistic(results, frame.shape, patient_info)
                
                # Prepare info dict for drawing
                info = {
                    'holistic_results': results,
                    'pose_result': pose_result,
                    'hand_result': hand_result,
                    'kinematics': kinematics
                }
                
                # === GEMINI ANALYSIS INTEGRATION ===
                # (Replaced by global ai_manager in generate_frames loop)
                pass
                
                return detected, confidence, info, status
                
            except Exception as e:
                print(f"Holistic detection error: {e}")
                return "None", 0.0, None, "Detection Error"

        # ================== MOG2 FALLBACK LOGIC ==================
        elif self.mode == "MOG2":
            fg_mask = self.bg_subtractor.apply(frame)
            _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return "None", 0.0, None, "No Motion"
                
            largest_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest_contour)
            
            if area < 3000:
                return "None", 0.0, None, "Area too small"
                
            x, y, w, h = cv2.boundingRect(largest_contour)
            aspect_ratio = float(w) / h if h > 0 else 0
            center_x = x + w // 2
            center_y = y + h // 2
            
            frame_height = frame.shape[0]
            relative_height = h / frame_height
            
            vertical_movement = 0
            if self.prev_center_y is not None:
                vertical_movement = abs(center_y - self.prev_center_y)
                
            self.motion_history.append(vertical_movement)
            avg_motion = np.mean(self.motion_history) if len(self.motion_history) > 0 else 0
            self.prev_center_y = center_y
            
            activity = "None"
            confidence = 0.5
            status = f"Legacy Mode (AR:{aspect_ratio:.2f})"
            
            if aspect_ratio > 1.3:
                activity = "Lying"
                confidence = 0.8
            elif avg_motion > 5:
                activity = "Walking"
                confidence = 0.7
            elif relative_height < 0.6:
                activity = "Sitting"
                confidence = 0.6
            else:
                activity = "Standing"
                confidence = 0.6
                
            info = {
                'bbox': (x, y, w, h),
                'aspect_ratio': aspect_ratio,
                'relative_height': relative_height,
                'motion': avg_motion,
                'area': area,
                'center': (center_x, center_y)
            }
            
            return activity, confidence, info, status
        
        # Should not reach here
        return "None", 0.0, None, "Unknown Mode"
    
    
    def detect_fall(self, activity, info, confidence):
        """Detect potential falls"""
        if activity == "Lying" and confidence > 0.8:
            self.fall_detection_frames += 1
            
            # If lying detected for 3+ consecutive frames, might be a fall
            if self.fall_detection_frames >= 3:
                return True
        else:
            self.fall_detection_frames = 0
        
        return False
    
    def check_prolonged_lying(self, activity):
        """Check if person has been lying for too long"""
        if activity == "Lying":
            if self.lying_start_time is None:
                self.lying_start_time = time.time()
            else:
                lying_duration = time.time() - self.lying_start_time
                # Alert if lying for more than 5 minutes
                if lying_duration > 300:  # 5 minutes
                    return True, lying_duration
        else:
            self.lying_start_time = None
        
        return False, 0
    
    def update_activity(self, detected_activity, confidence):
        """Update activity with stability buffer"""
        self.activity_buffer.append(detected_activity)
        
        # Activity is stable if detected in 8 frames 
        # OR if it is high-confidence persistent event (like Seizure/Distress which already have internal buffers)
        is_stable = self.activity_buffer.count(detected_activity) >= 8
        is_critical = confidence >= 0.99
        
        if is_stable or is_critical:
            if self.current_activity != detected_activity:
                self.current_activity = detected_activity
                return True  # Activity changed
        
        return False  # No change
    
    def log_activity_to_db(self, patient_id, patient_name, activity, confidence):
        """Log activity to database"""
        now = time.time()
        
        # Don't log too frequently (minimum 3 seconds between logs)
        if now - self.last_log_time < 3:
            return
        
        # Don't log if same activity
        if activity == self.last_logged_activity:
            return
        
        try:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            Database.execute_query(
                """INSERT INTO activities 
                   (patient_id, patient_name, activity, confidence, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (patient_id, patient_name, activity, confidence, local_time)
            )
            
            self.last_logged_activity = activity
            self.last_log_time = now
            
        except Exception as e:
            print(f"Error logging activity: {e}")
    
    def create_fall_alert(self, patient_id, patient_name):
        """Create emergency alert for fall detection"""
        now = time.time()
        
        # Don't create alerts too frequently (minimum 30 seconds between alerts)
        if now - self.last_alert_time < 30:
            return
        
        try:
            local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            Database.execute_query(
                """INSERT INTO emergency_alerts 
                   (patient_id, patient_name, alert_type, severity, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (patient_id, patient_name, "Fall Detected", "critical",
                 "Potential fall detected - Patient found lying down suddenly", local_time)
            )
            
            self.last_alert_time = now
            print(f"🚨 EMERGENCY ALERT: Fall detected for {patient_name}")
            
        except Exception as e:
            print(f"Error creating alert: {e}")
    
    def draw_overlay(self, frame, activity, confidence, info, status):
        """Draw info overlay on frame"""
        
        # Draw Holistic Landmarks (pose + hands from Tasks API)
        if self.mode == "HOLISTIC" and info and info.get('holistic_results'):
            self.draw_holistic_landmarks(frame, info['holistic_results'])
        
        # Draw BBox (MOG2 fallback)
        elif self.mode == "MOG2" and info and info.get('bbox'):
            x, y, w, h = info['bbox']
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            if 'center' in info:
                cx, cy = info['center']
                cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)

        # Draw status text box with transparent background
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (500, 150), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        
        # Determine color based on activity
        color = (0, 255, 0)  # Default green
        if "Lying" in activity or "Fall" in activity:
            color = (0, 0, 255)  # Red for lying/fall
        elif "Seizure" in activity or "Help" in activity or "Distress" in activity:
            color = (0, 0, 255)  # Red for critical
        elif "Sitting" in activity:
            color = (0, 255, 255)  # Yellow
        elif "Walking" in activity:
            color = (255, 165, 0)  # Orange
        elif "Eating" in activity or "Drinking" in activity:
            color = (255, 0, 255)  # Magenta
        elif "Standing" in activity:
            color = (0, 255, 0)  # Green
        
        # Draw activity text
        cv2.putText(frame, f"Activity: {activity}", (20, 50),
                   cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
        
        # Draw confidence
        cv2.putText(frame, f"Confidence: {confidence:.0%}", (20, 90),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                   
        # Draw status
        cv2.putText(frame, f"Status: {status}", (20, 120),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        # Show mode indicator
        mode_text = f"Mode: {self.mode}"
        cv2.putText(frame, mode_text, (frame.shape[1] - 250, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                   
        # Fall Warning
        if "Lying" in activity and self.fall_detection_frames > 0:
             cv2.putText(frame, "⚠️ FALL DETECTED!", (20, frame.shape[0] - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        
        # Critical Warning
        if "CRITICAL" in status:
            cv2.putText(frame, "🚨 EMERGENCY!", (20, frame.shape[0] - 80),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)

# Global detector instance
activity_detector = ActivityDetector()


import atexit
def cleanup():
    global activity_detector
    try:
        if activity_detector:
            if hasattr(activity_detector, 'pose_landmarker') and activity_detector.pose_landmarker:
                activity_detector.pose_landmarker.close()
                activity_detector.pose_landmarker = None
            if hasattr(activity_detector, 'hand_landmarker') and activity_detector.hand_landmarker:
                activity_detector.hand_landmarker.close()
                activity_detector.hand_landmarker = None
    except:
        pass
atexit.register(cleanup)

# ---------------- VIDEO FEED ----------------
def generate_frames(user_id=1, user_name="Guest"):
    """Generator function to stream video frames with activity detection"""
    global video_capture, activity_detector
    
    camera_url = Database.get_setting('camera_url', '0')
    
    # Try to parse camera_url as integer for local camera
    try:
        camera_source = int(camera_url)
    except ValueError:
        # It's a URL string (like WiFi camera)
        camera_source = camera_url
    
    # Initialize video capture
    if video_capture is None:
        video_capture = cv2.VideoCapture(camera_source)
        video_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        # Warmup if needed
        activity_detector.warmup(video_capture)
    
    # Frame counter for processing optimization
    frame_count = 0
    
    # Get user info from session before entering loop
    from flask import copy_current_request_context
    

                             
    # Stream continuously (don't check monitoring_active)
    while True:
        success, frame = video_capture.read()
        
        if not success:
            # If reading fails, try to reconnect
            if video_capture is not None:
                video_capture.release()
            video_capture = cv2.VideoCapture(camera_source)
            continue
        
        # Flip frame for mirror effect (optional)
        frame = cv2.flip(frame, 1)
        
        # Process every frame for activity detection
        frame_count += 1
        
        # Only process detection if monitoring is active
        if monitoring_active:
            # Detect activity - Pass patient info
            patient_info = {'id': user_id, 'name': user_name}
            detected_activity, confidence, info, status = activity_detector.detect_activity(frame, patient_info)
            
            # Update activity buffer
            activity_changed = activity_detector.update_activity(detected_activity, confidence)
            
            # ================== LOGGING LOGIC ==================
            # Use passed identity
            p_id = user_id
            p_name = user_name

            # ================== AI MANAGER INTEGRATION ==================
            # Feed data to the background thread
            # Pass ONLY the kinematics dict to ensure clean data
            ai_manager.set_patient(user_id, user_name)
            ai_manager.add_frame(
                detected_activity, 
                confidence, 
                (info or {}).get('kinematics', {})
            )
            # ============================================================

            # Check for Critical Status
            is_critical = status.startswith("CRITICAL")
                
            # 1. Log Activity Change
            if (activity_changed and detected_activity != "None") or is_critical:
                # print(f"Logging: {detected_activity}")
                activity_detector.log_activity_to_db(
                    p_id, p_name, 
                    activity_detector.current_activity, confidence
                )
                
                if is_critical and activity_detector.last_alert_time < time.time() - 5:
                    # Log alert 
                    msg = f"{status}: {detected_activity}"
                    try:
                       Database.execute_query(
                           "INSERT INTO emergency_alerts (patient_id, patient_name, alert_type, severity, description) VALUES (?, ?, ?, ?, ?)",
                           (p_id, p_name, detected_activity, "critical", msg)
                       )
                       activity_detector.last_alert_time = time.time()
                    except: pass

            # 2. Existing Fall Check
            if activity_detector.detect_fall(detected_activity, info, confidence):
                 activity_detector.create_fall_alert(p_id, p_name)

            # 3. Prolonged Lying
            is_prolonged, duration = activity_detector.check_prolonged_lying(activity_detector.current_activity)
            if is_prolonged:
                    # Create alert for prolonged lying
                    try:
                        Database.execute_query(
                            """INSERT INTO emergency_alerts 
                               (patient_id, patient_name, alert_type, severity, description)
                               VALUES (?, ?, ?, ?, ?)""",
                            (p_id, p_name, "Prolonged Lying", "medium",
                             f"Patient has been lying down for {int(duration/60)} minutes")
                        )
                        activity_detector.lying_start_time = time.time()  # Reset timer
                    except:
                        pass
            
            # Draw overlay on frame
            activity_detector.draw_overlay(frame, activity_detector.current_activity,
                                          confidence, info, status)
        
        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', frame)
        
        if not ret:
            continue
        
        # Convert to bytes
        frame_bytes = buffer.tobytes()
        
        # Yield frame in multipart format
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route("/video_feed")
@login_required
def video_feed():
    """Video streaming route. Returns multipart response"""
    user_id = session.get('user_id', 1)
    user_name = session.get('user_name', 'Guest')
    
    return Response(
        generate_frames(user_id, user_name),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "info")
    return redirect(url_for("login"))

# ---------------- ADMIN ROUTES (Optional) ----------------
@app.route("/admin/patients")
@login_required
def admin_patients():
    """View all patients (admin only)"""
    patients = Database.execute_query(
        "SELECT * FROM patients ORDER BY created_at DESC",
        fetch_all=True
    )
    return render_template("admin_patients.html", patients=patients)

# ---------------- ERROR HANDLERS ----------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500



# ---------------- MEDICAL RAG CHATBOT ----------------
# Initialize Chatbot using Gemini API key from environment
chatbot = MedicalChatbot(os.getenv("GEMINI_API_KEY"), DB_PATH)

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat requests"""
    try:
        data = request.json
        question = data.get('question')
        if not question:
            return jsonify({"error": "No question provided"}), 400
            
        answer = chatbot.ask(question, patient_name="Current Patient")
        return jsonify({"answer": answer})
    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({"error": str(e)}), 500

from ai_manager import ai_manager

# Note: ActivityDetector NO LONGER initializes gemini_analyzer internally.
# It is now fully decoupled and handled by the global ai_manager via app.py loop.

if __name__ == "__main__":
    try:
        # Ensure AI Manager uses same DB as App
        ai_manager.db_path = DB_PATH
        # Start the background AI thread
        ai_manager.start()
        app.run(debug=True, host='0.0.0.0', port=5000)
    finally:
        # Ensure clean shutdown
        ai_manager.stop()