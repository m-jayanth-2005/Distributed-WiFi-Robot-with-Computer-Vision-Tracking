"""
Database Management Script for Patient Monitoring System
This script helps initialize, backup, and manage the database
"""

import sqlite3
import os
from datetime import datetime
import json

DB_PATH = "patients.db"

def init_database():
    """Initialize the database with all required tables"""
    print("Initializing database...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Patients table
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

    # Activities log table
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

    # Monitoring sessions table
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

    # Insert default settings
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

    # Gemini analysis logs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gemini_analysis_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        patient_name TEXT,
        analysis_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        risk_level TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients(id)
    )
    """)

    # Gemini raw logs table (Removed by request)
    # cursor.execute("""
    # CREATE TABLE IF NOT EXISTS gemini_raw_logs (
    #     id INTEGER PRIMARY KEY AUTOINCREMENT,
    #     patient_id INTEGER,
    #     raw_json TEXT,
    #     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    #     FOREIGN KEY (patient_id) REFERENCES patients(id)
    # )
    # """)

    conn.commit()
    conn.close()
    
    print("✓ Database initialized successfully!")
    print(f"✓ Database location: {os.path.abspath(DB_PATH)}")

def backup_database():
    """Create a backup of the database"""
    if not os.path.exists(DB_PATH):
        print("✗ Database not found!")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"patients_backup_{timestamp}.db"
    
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    
    print(f"✓ Database backed up to: {backup_path}")

def show_statistics():
    """Display database statistics"""
    if not os.path.exists(DB_PATH):
        print("✗ Database not found! Run init first.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("\n" + "="*50)
    print("DATABASE STATISTICS")
    print("="*50)
    
    # Patients
    cursor.execute("SELECT COUNT(*) FROM patients")
    patient_count = cursor.fetchone()[0]
    print(f"Total Patients: {patient_count}")
    
    # Activities
    cursor.execute("SELECT COUNT(*) FROM activities")
    activity_count = cursor.fetchone()[0]
    print(f"Total Activities: {activity_count}")
    
    # Sessions
    cursor.execute("SELECT COUNT(*) FROM monitoring_sessions")
    session_count = cursor.fetchone()[0]
    print(f"Total Sessions: {session_count}")
    
    # Alerts
    cursor.execute("SELECT COUNT(*) FROM emergency_alerts WHERE is_resolved = 0")
    active_alerts = cursor.fetchone()[0]
    print(f"Active Alerts: {active_alerts}")

    # Gemini Logs
    try:
        cursor.execute("SELECT COUNT(*) FROM gemini_analysis_logs")
        ai_logs = cursor.fetchone()[0]
        print(f"AI Analysis Logs: {ai_logs}")
    except:
        print("AI Analysis Logs: 0 (Table not found)")
    
    # Recent activities
    cursor.execute("""
        SELECT activity, COUNT(*) as count 
        FROM activities 
        GROUP BY activity 
        ORDER BY count DESC 
        LIMIT 5
    """)
    
    print("\nTop Activities:")
    for row in cursor.fetchall():
        print(f"  - {row[0]}: {row[1]} times")
    
    conn.close()
    print("="*50 + "\n")

def export_data():
    """Export database data to JSON"""
    if not os.path.exists(DB_PATH):
        print("✗ Database not found!")
        return
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    data = {
        'patients': [],
        'activities': [],
        'sessions': [],
        'alerts': []
    }
    
    # Export patients (without passwords)
    cursor.execute("SELECT id, name, age, gender, phone, email FROM patients")
    data['patients'] = [dict(row) for row in cursor.fetchall()]
    
    # Export activities
    cursor.execute("SELECT * FROM activities")
    data['activities'] = [dict(row) for row in cursor.fetchall()]
    
    # Export sessions
    cursor.execute("SELECT * FROM monitoring_sessions")
    data['sessions'] = [dict(row) for row in cursor.fetchall()]
    
    # Export alerts
    cursor.execute("SELECT * FROM emergency_alerts")
    data['alerts'] = [dict(row) for row in cursor.fetchall()]

    # Export Gemini Analysis
    try:
        cursor.execute("SELECT * FROM gemini_analysis_logs")
        data['gemini_analysis'] = [dict(row) for row in cursor.fetchall()]
    except: pass

    # Export Gemini Raw Logs (Removed)
    # try:
    #     cursor.execute("SELECT * FROM gemini_raw_logs")
    #     data['gemini_raw'] = [dict(row) for row in cursor.fetchall()]
    # except: pass
    
    conn.close()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = f"data_export_{timestamp}.json"
    
    with open(export_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Data exported to: {export_path}")

def reset_database():
    """Reset database (WARNING: Deletes all data)"""
    response = input("⚠️  WARNING: This will delete ALL data! Type 'YES' to confirm: ")
    
    if response == 'YES':
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print("✓ Database deleted")
        init_database()
        print("✓ Fresh database created")
    else:
        print("✗ Operation cancelled")

def main():
    """Main menu"""
    while True:
        print("\n" + "="*50)
        print("PATIENT MONITORING - DATABASE MANAGER")
        print("="*50)
        print("1. Initialize Database")
        print("2. Show Statistics")
        print("3. Backup Database")
        print("4. Export Data to JSON")
        print("5. Reset Database (⚠️  Deletes all data)")
        print("6. Exit")
        print("="*50)
        
        choice = input("\nEnter choice (1-6): ")
        
        if choice == '1':
            init_database()
        elif choice == '2':
            show_statistics()
        elif choice == '3':
            backup_database()
        elif choice == '4':
            export_data()
        elif choice == '5':
            reset_database()
        elif choice == '6':
            print("Goodbye!")
            break
        else:
            print("✗ Invalid choice!")

if __name__ == "__main__":
    main()
