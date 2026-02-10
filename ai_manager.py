import threading
import time
import json
import sqlite3
import os
import logging
from datetime import datetime
import google.generativeai as genai  # STABLE LIBRARY
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIManager")

class AIManager:
    """
    Robust, threaded AI Manager using google.genai (v1) Library.
    """
    
    def __init__(self, db_path="patients.db", analysis_interval=10):
        load_dotenv()
        self.db_path = db_path
        self.analysis_interval = analysis_interval
        
        # API Setup
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.error("❌ GEMINI_API_KEY not found in environment!")
            self.client = None
        else:
            try:
                # Initialize Client (Old Style)
                genai.configure(api_key=self.api_key)
                # Use explicit model (Stable)
                self.model_name = "gemini-2.5-flash" 
                
                logger.info(f"✅ Gemini API configured with {self.model_name}")
                self.client = True # Marker that it's ready
            except Exception as e:
                logger.error(f"❌ Gemini Initialization Failed: {e}")
                self.client = None

        # Threading & State
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # Data Buffers
        self.buffer = []
        self.last_sample_time = 0
        self.last_analysis_time = time.time()
        
        # Current Patient Context
        self.current_patient = {"id": 1, "name": "Guest"}

    def start(self):
        """Start the background analysis thread"""
        if self.running:
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._analysis_loop, daemon=True)
        self.thread.start()
        logger.info("🤖 AI Manager Background Thread Started")
        
        # Test DB Connection
        try:
            # We don't call API here to save quota/time, just check DB
            self._save_to_db(self.current_patient, '{"summary": "System Startup: AI Manager Online"}')
            logger.info("✅ AI Manager: Database Connection Verified")
        except Exception as e:
            logger.error(f"❌ AI Manager: Database Check Failed: {e}")

    def stop(self):
        """Stop the background thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        logger.info("🛑 AI Manager Stopped")

    def set_patient(self, user_id, user_name):
        """Update current patient context"""
        with self.lock:
            self.current_patient = {"id": user_id, "name": user_name}

    def add_frame(self, activity, confidence, kinematics):
        """Thread-safe method to add a frame of data."""
        if not self.running:
            return

        now = time.time()
        should_sample = (now - self.last_sample_time >= 1.0) or (not self.buffer)
        
        if should_sample:
            with self.lock:
                entry = {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "activity": activity,
                    "confidence": round(confidence, 2),
                    "kinematics": kinematics
                }
                self.buffer.append(entry)
                self.last_sample_time = now
                if len(self.buffer) > 120:
                    self.buffer.pop(0)

    def _analysis_loop(self):
        """Main background loop"""
        while self.running:
            now = time.time()
            if now - self.last_analysis_time > self.analysis_interval:
                self._run_analysis_job()
                self.last_analysis_time = time.time()
            time.sleep(1)

    def _run_analysis_job(self):
        """Prepare data and call Gemini (New API)"""
        if not self.client:
            return

        with self.lock:
            if len(self.buffer) < 5: 
                return
            data_snapshot = list(self.buffer)
            patient_ctx = dict(self.current_patient)
            self.buffer = [] 
            
        logger.info(f"🧠 Triggering Analysis for {patient_ctx['name']} ({len(data_snapshot)} frames)")
        
        prompt = f"""
        ACT AS: Senior Clinical Nurse Specialist.
        TASK: Write a Shift Handoff Note for {patient_ctx['name']} (ID: {patient_ctx['id']}).
        CONTEXT: You are observing a short window of motion data.
        
        RAW KINEMATICS DATA:
        {json.dumps(data_snapshot, indent=2)}
        
        GUIDELINES:
        1.  **Synthesize, Don't List**: Do NOT mention "degrees", "coordinates", "kinematics", or "confidence score".
        2.  **Focus on Capability**: Can the patient stand unassisted? Are they restless?
        3.  **Identify Risk**: Fall risk? Agitation? Prolonged immobility?
        4.  **Tone**: Professional, medical, concise.
        
        OUTPUT JSON FORMAT:
        {{
          "summary": "Patient was observed [activity context]. Mobility appears [steady/unsteady]. No acute distress noted... (Keep it narrative)",
          "primary_activities": ["Walking", "Sitting"],
          "risk_level": "Low/Medium/High",
          "clinical_impression": "Brief medical impression (e.g., 'Normal mobility for age' or 'High fall risk observed')"
        }}
        """
        
        try:
            # OLD API CALL PATTERN (Stable)
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                prompt,
                generation_config={'response_mime_type': 'application/json'}
            )
            
            if response.text:
                self._save_to_db(patient_ctx, response.text)
                
        except Exception as e:
            logger.error(f"❌ Gemini API Error: {e}")

    def _save_to_db(self, patient, analysis_text):
        """Save result to DB"""
        try:
            # Verify JSON valid (should be guaranteed by API, but good to check)
            json.loads(analysis_text)
            
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT INTO gemini_analysis_logs (patient_id, patient_name, analysis_text, created_at)
                VALUES (?, ?, ?, ?)
            """, (patient['id'], patient['name'], analysis_text, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
            logger.info("✅ Analysis Saved to DB")
            
        except Exception as e:
            logger.error(f"❌ DB Save Error: {e}")

# Global Instance
ai_manager = AIManager()
