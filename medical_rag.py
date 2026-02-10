
import google.generativeai as genai
import sqlite3
import os
import datetime
import json

class MedicalChatbot:
    def __init__(self, api_key, db_path):
        self.api_key = api_key
        self.db_path = db_path
        
        try:
            # Initialize Client (Old Style)
            genai.configure(api_key=api_key)
            self.model_name = "gemini-2.5-flash"
            self.client = True # Marker
            print("✅ Medical Chatbot initialized with Gemini 2.5 Flash")
        except Exception as e:
            print(f"❌ Gemini Chatbot init failed: {e}")
            self.client = None

    def get_patient_context(self, patient_id=1, hours=24):
        """Fetch recent activities and analysis logs for context"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Time filter
            time_threshold = (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            
            # 1. Fetch raw activities (summary of counts/types)
            cursor.execute("""
                SELECT activity, COUNT(*) as count, MAX(timestamp) as last_seen
                FROM activities 
                WHERE timestamp > ? 
                GROUP BY activity
            """, (time_threshold,))
            
            activity_summary = [dict(row) for row in cursor.fetchall()]
            
            # 2. Fetch specific critical events
            cursor.execute("""
                SELECT activity, timestamp 
                FROM activities 
                WHERE timestamp > ? AND (activity LIKE '%CRITICAL%' OR activity LIKE '%FALL%' OR activity LIKE '%HELP%')
                ORDER BY timestamp DESC
            """, (time_threshold,))
            critical_events = [dict(row) for row in cursor.fetchall()]
            
            # 3. Fetch Gemini Analysis Logs (The deep insights)
            cursor.execute("""
                SELECT analysis_text, created_at
                FROM gemini_analysis_logs 
                WHERE created_at > ?
                ORDER BY created_at DESC 
                LIMIT 5
            """, (time_threshold,))
            analysis_logs = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            
            return {
                "summary": activity_summary,
                "critical": critical_events,
                "analysis_history": analysis_logs,
                "period": f"Last {hours} hours"
            }
            
        except Exception as e:
            print(f"Context fetch error: {e}")
            return {}

    def ask(self, question, patient_name="Patient"):
        """Generate answer using RAG"""
        if not self.client:
            return "I am currently offline (API Error)."
            
        # 1. Retrieve Context
        context = self.get_patient_context()
        
        # 2. Build Prompt
        prompt = f"""
        You are a Medical AI Assistant monitoring {patient_name}. 
        User Question: "{question}"
        
        Here is the recorded data for the {context.get('period', 'recent period')}:
        
        [ACTIVITY SUMMARY]
        {json.dumps(context.get('summary', []), indent=2)}
        
        [CRITICAL ALERTS]
        {json.dumps(context.get('critical', []), indent=2)}
        
        [AI ANALYSIS LOGS (From previous periodic checks)]
        {json.dumps(context.get('analysis_history', []), indent=2)}
        
        INSTRUCTIONS:
        - Answer the question based ONLY on the provided data.
        - Be empathetic but professional.
        - If critical events (Falls, Seizures) are present, highlight them immediately.
        - If no data supports the answer, say "I don't have records for that specific event."
        - Keep answers concise.
        """
        
        try:
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error generating response: {e}"
