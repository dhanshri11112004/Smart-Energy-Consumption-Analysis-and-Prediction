from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
# from google.genai import Client
import google.generativeai as genai
import os
import pickle
import numpy as np
import os
import json

import re
import sqlite3
from datetime import datetime


LAST_INPUT = None
LAST_PREDICTION = None


# ---------------- APP INIT ----------------
app = Flask(__name__)
CORS(app,resources={r"/*":{"origins":"*"}}) 

# ---------------- LOAD ML MODEL ----------------
MODEL_PATH = "model/energy_xgb_model.pkl"
ml_model = None

try:
    with open(MODEL_PATH, "rb") as f:
        ml_model = pickle.load(f)
    print("✅ ML Model loaded successfully")
except Exception as e:
    print(f"❌ ML Model Load Error: {e}")

# ---------------- GEMINI CONFIG ----------------
# CRITICAL: Replace 'YOUR_API_KEY_HERE' with your actual key if the environment variable isn't working
# API_KEY = os.getenv("GEMINI_API_KEY") 
# client = Client(api_key=API_KEY)
# print(f"DEBUG: API Key found: {bool(os.getenv('GEMINI_API_KEY'))}")
# MODEL_NAME = "gemini-2.0-flash-lite-preview-02-05" 

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model=genai.GenerativeModel("gemini-2.0-flash-lite-preview-02-05")
response=model.generate_content(prompt)
text=response.text
# ---------------- FEATURE ORDER ----------------
FEATURE_ORDER = ["HVACUsage", "Occupancy", "Temperature", "RenewableEnergy", "Hour", "IsWeekend"]

# ---------------- HELPERS ----------------

def init_feedback_db():
    conn = sqlite3.connect("feedback.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            category TEXT,
            message TEXT,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()


def extract_params_from_text(text):
    prompt = f"""
    You are a data extraction tool. 
    Analyze the text: "{text}"
    Extract these EXACT 6 keys:
    - HVACUsage: (1 if on/running, 0 if off)
    - Occupancy: (number of people)
    - Temperature: (the number in Celsius)
    - RenewableEnergy: (1 if using solar/wind, 0 if grid)
    - Hour: (0-23 format)
    - IsWeekend: (1 if Sat/Sun, 0 if Mon-Fri)
    
    Return ONLY raw JSON. Do not add any conversational text.
    """
    try:
        # Note: Using the correct method signature for the new Google GenAI SDK
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        # Clean the response to find JSON
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"Extraction Error: {e}")
    return None

def run_prediction(params):
    if ml_model is None: return 0.0
    features = np.array([[params.get(f, 0) for f in FEATURE_ORDER]])
    return round(float(ml_model.predict(features)[0]), 2)


def explain_prediction(inputs, prediction):
    reasons = []

    if inputs["HVACUsage"] == 1:
        reasons.append("HVAC is ON, which significantly increases energy use")

    if inputs["Temperature"] >= 30:
        reasons.append(f"High temperature ({inputs['Temperature']}°C) increases cooling load")

    if inputs["Occupancy"] > 50:
        reasons.append(f"High occupancy ({inputs['Occupancy']}) increases appliance and cooling demand")

    if inputs["RenewableEnergy"] < 30:
        reasons.append(f"Low renewable energy ({inputs['RenewableEnergy']}%) increases grid dependency")

    if inputs["IsWeekend"] == 1:
        reasons.append("Weekend usage patterns are typically less optimized")

    explanation = "Energy consumption is high mainly because:\n"
    explanation += "\n".join([f"- {r}" for r in reasons])

    return explanation




import re

def extract_inputs_rule_based(text: str):
    t = text.lower()

    def find_number(keyword, default=0):
        match = re.search(rf"{keyword}[^0-9]*(\d+)", t)
        return int(match.group(1)) if match else default

    return {
        "HVACUsage": 1 if ("hvac on" in t or "hvac is on" in t or "hvac running" in t) else 0,
        "Occupancy": find_number("occupancy", 50),
        "Temperature": find_number("temperature", 25),
        "RenewableEnergy": find_number("renewable", 20),
        "Hour": find_number("hour", 12),
        "IsWeekend": 1 if "weekend" in t else 0
    }

from PyPDF2 import PdfReader
from docx import Document

def extract_text_from_file(file):
    filename = file.filename.lower()

    if filename.endswith(".txt"):
        return file.read().decode("utf-8", errors="ignore")

    elif filename.endswith(".pdf"):
        reader = PdfReader(file)
        return " ".join(page.extract_text() or "" for page in reader.pages)

    elif filename.endswith(".docx"):
        doc = Document(file)
        return " ".join(p.text for p in doc.paragraphs)

    return ""


def build_audit_report(inputs, energy):
    score = 100

    if inputs["HVACUsage"] == 1:
        score -= 20
    if inputs["Temperature"] > 30:
        score -= 15
    if inputs["Occupancy"] > 100:
        score -= 20
    if inputs["RenewableEnergy"] < 30:
        score -= 15
    if inputs["IsWeekend"] == 1:
        score -= 10

    score = max(score, 30)

    if score >= 80:
        risk = "Low"
    elif score >= 60:
        risk = "Medium"
    else:
        risk = "High"

    inefficiencies = []
    if inputs["HVACUsage"] == 1:
        inefficiencies.append("HVAC running continuously")
    if inputs["Temperature"] >= 30:
        inefficiencies.append("High cooling demand")
    if inputs["RenewableEnergy"] < 30:
        inefficiencies.append("Low renewable energy usage")
    if inputs["IsWeekend"] == 1:
        inefficiencies.append("Weekend usage inefficiency")

    recommendations = []
    if inputs["HVACUsage"] == 1:
        recommendations.append("Optimize HVAC runtime")
    if inputs["Temperature"] >= 30:
        recommendations.append("Improve cooling efficiency")
    if inputs["RenewableEnergy"] < 30:
        recommendations.append("Increase renewable energy contribution")

    summary = (
        f"Predicted energy consumption is {energy} kWh. "
        f"Efficiency score indicates {risk.lower()} risk."
    )

    return {
        "energy": energy,
        "score": score,
        "risk": risk,
        "inefficiencies": inefficiencies,
        "recommendations": recommendations,
        "summary": summary
    }


import matplotlib.pyplot as plt
from io import BytesIO
def generate_feature_chart(inputs):
    features = [
        "HVAC",
        "Occupancy",
        "Temperature",
        "Renewable",
        "Hour",
        "Weekend"
    ]

    values = [
        1 if inputs["HVACUsage"] else 0.2,
        min(inputs["Occupancy"] / 100, 1),
        min(inputs["Temperature"] / 40, 1),
        1 - inputs["RenewableEnergy"] / 100,
        inputs["Hour"] / 24,
        inputs["IsWeekend"]
    ]

    fig, ax = plt.subplots(figsize=(5, 3))
    ax.bar(features, values)
    ax.set_ylabel("Relative Impact")
    ax.set_title("Energy Consumption Drivers")

    buffer = BytesIO()
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)

    return buffer

from reportlab.lib.utils import ImageReader





@app.route("/predict", methods=["POST"])
def predict():
    global LAST_INPUT, LAST_PREDICTION

    data = request.json
    prediction = run_prediction(data)

    LAST_INPUT = data
    LAST_PREDICTION = prediction

    return jsonify({
        "status": "success",
        "prediction": prediction,
        "unit": "kWh"
    })




@app.route("/offline-predict", methods=["POST"])
def offline_predict():
    try:
        print("🔵 offline-predict called")

        if "file" not in request.files:
            print("❌ No file in request")
            return jsonify({"status": "error", "message": "No file uploaded"}), 400

        file = request.files["file"]
        print("📄 File received:", file.filename)

        import pandas as pd
        df = pd.read_csv(file)
        print("📊 CSV loaded")
        print(df.head())

        print("📌 Expected columns:", FEATURE_ORDER)
        print("📌 CSV columns:", list(df.columns))

        features = df[FEATURE_ORDER]
        print("✅ Features selected")

        preds = ml_model.predict(features)
        print("🔮 Prediction done")

        df["PredictedEnergy"] = preds.round(2)

        return jsonify({
            "status": "success",
            "predictions": df.to_dict(orient="records")
        })

    except Exception as e:
        print("🔥 OFFLINE PREDICT ERROR:", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500




import re
import json

@app.route("/chat", methods=["POST"])
def chat():
    global LAST_INPUT, LAST_PREDICTION

    user_msg = request.json.get("message", "").strip()
    msg = user_msg.lower()

    print("🤖 User:", user_msg)

    # ---------------- MODEL CONTEXT (NO HARDCODING OF ANSWERS) ----------------
    MODEL_CONTEXT = """
This system predicts building energy consumption using an XGBoost regression model.

Model inputs:
HVACUsage (0 or 1)
Occupancy (number of people)
Temperature (Celsius)
RenewableEnergy (percentage)
Hour (0 to 23)
IsWeekend (0 or 1)

The model learns non-linear relationships from historical data
and outputs energy consumption in kilowatt-hours.
"""

    # ---------------- 1️⃣ CURRENT PREDICTION STATE ----------------
    if "current" in msg and "prediction" in msg:
        if LAST_PREDICTION is None:
            return jsonify({
                "type": "chat",
                "response": "No energy prediction has been generated yet. Please provide input values to run a prediction."
            })

        state_prompt = f"""
You are summarizing the current system state.

Last predicted energy: {LAST_PREDICTION} kWh
Last input values: {LAST_INPUT}

Explain the current prediction in 2 to 3 short sentences.
Plain text only.
"""
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=state_prompt
        )

        return jsonify({
            "type": "chat",
            "response": resp.text.strip()
        })

    # ---------------- 2️⃣ WHY ENERGY IS HIGH / EXPLANATION ----------------
    WHY_KEYWORDS = ["why", "reason", "explain", "high", "consumption"]

    if LAST_INPUT and any(k in msg for k in WHY_KEYWORDS):
        explain_prompt = f"""
You are explaining an energy prediction produced by an XGBoost model.

Prediction: {LAST_PREDICTION} kWh
Input values:
{LAST_INPUT}

Explain clearly why the energy consumption is high or low.
Use only the given inputs.
Maximum 4 lines.
Plain text only.
"""
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=explain_prompt
        )

        return jsonify({
            "type": "prediction",
            "prediction": LAST_PREDICTION,
            "unit": "kWh",
            "response": resp.text.strip()
        })

    # ---------------- 3️⃣ MODEL / FEATURE / ML QUESTIONS ----------------
    MODEL_QUESTIONS = [
        "how model works",
        "how does model work",
        "what is this model",
        "input feature",
        "input features",
        "why machine learning",
        "why ml",
        "why ai",
        "why xgboost"
    ]

    if any(k in msg for k in MODEL_QUESTIONS):
        model_prompt = f"""
{MODEL_CONTEXT}

Answer the following question clearly.

Rules:
Maximum 4 lines
Plain text only
No symbols or formatting

Question:
{user_msg}
"""
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=model_prompt
        )

        return jsonify({
            "type": "chat",
            "response": resp.text.strip()
        })

    # ---------------- 4️⃣ TRY PARAMETER EXTRACTION FOR NEW PREDICTION ----------------
    REQUIRED = FEATURE_ORDER
    params = None

    try:
        extract_prompt = f"""
Extract energy prediction parameters from the sentence below.

Return strict JSON with all fields or return null.

Format:
{{
 "HVACUsage": 0 or 1,
 "Occupancy": number,
 "Temperature": number,
 "RenewableEnergy": number,
 "Hour": number,
 "IsWeekend": 0 or 1
}}

Sentence:
{user_msg}
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=extract_prompt
        )

        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if match:
            params = json.loads(match.group())
            if not all(k in params for k in REQUIRED):
                params = None

    except Exception as e:
        print("⚠️ Extraction failed:", e)

    # Fallback numeric extraction
    if params is None:
        numbers = list(map(int, re.findall(r"\d+", msg)))
        if len(numbers) >= 6:
            params = dict(zip(REQUIRED, numbers[:6]))

    # ---------------- 5️⃣ RUN NEW PREDICTION ----------------
    if params:
        prediction = run_prediction(params)
        LAST_INPUT = params
        LAST_PREDICTION = prediction

        return jsonify({
            "type": "prediction",
            "prediction": prediction,
            "unit": "kWh",
            "response": "Energy prediction generated successfully."
        })

    # ---------------- 6️⃣ GENERAL ENERGY CHAT ----------------
    general_prompt = f"""
Answer the following question in simple plain text.

Rules:
Maximum 4 lines
No symbols, bullets, emojis, or formatting

Question:
{user_msg}
"""
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=general_prompt
    )

    return jsonify({
        "type": "chat",
        "response": resp.text.strip()
    })


@app.route("/extract-inputs", methods=["POST"])
def extract_inputs():
    file = request.files.get("file")
    if not file:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    text = extract_text_from_file(file)

    inputs = None
    used_mode = "rule-based"

    # ---------- TRY GEMINI (OPTIONAL) ----------
    try:
        inputs = extract_params_from_text(text)  # your existing Gemini function
        if inputs:
            used_mode = "gemini"
    except Exception as e:
        print("⚠️ Gemini unavailable, using fallback:", e)

    # ---------- FALLBACK ----------
    if not inputs:
        inputs = extract_inputs_rule_based(text)

    return jsonify({
        "status": "success",
        "mode": used_mode,
        "inputs": inputs
    })

@app.route("/audit", methods=["GET"])
def generate_audit():
    global LAST_INPUT, LAST_PREDICTION

    if LAST_INPUT is None or LAST_PREDICTION is None:
        return jsonify({
            "status": "error",
            "message": "No prediction available"
        })

    energy = LAST_PREDICTION
    inputs = LAST_INPUT

    # -------- SCORE CALCULATION --------
    score = 100

    if inputs["HVACUsage"] == 1:
        score -= 20
    if inputs["Temperature"] > 30:
        score -= 15
    if inputs["Occupancy"] > 100:
        score -= 20
    if inputs["RenewableEnergy"] < 30:
        score -= 15
    if inputs["IsWeekend"] == 1:
        score -= 10

    score = max(score, 30)

    if score >= 80:
        risk = "Low"
    elif score >= 60:
        risk = "Medium"
    else:
        risk = "High"

    # -------- INEFFICIENCIES --------
    inefficiencies = []
    if inputs["HVACUsage"] == 1:
        inefficiencies.append("HVAC running continuously")
    if inputs["Temperature"] > 30:
        inefficiencies.append("High cooling demand due to temperature")
    if inputs["Occupancy"] > 100:
        inefficiencies.append("High occupancy increasing load")
    if inputs["RenewableEnergy"] < 30:
        inefficiencies.append("Low renewable energy utilization")

    # -------- RECOMMENDATIONS --------
    recommendations = []
    if inputs["HVACUsage"] == 1:
        recommendations.append("Optimize HVAC runtime using occupancy control")
    if inputs["Temperature"] > 30:
        recommendations.append("Improve insulation or cooling efficiency")
    if inputs["RenewableEnergy"] < 30:
        recommendations.append("Increase renewable energy contribution")
    if inputs["Occupancy"] > 100:
        recommendations.append("Distribute load across time slots")

    summary = (
        f"Predicted energy consumption is {energy} kWh. "
        f"Efficiency score indicates {risk.lower()} risk."
    )

    return jsonify({
        "status": "success",
        "audit": {
            "energy": energy,
            "score": score,
            "risk": risk,
            "inputs": inputs,
            "inefficiencies": inefficiencies,
            "recommendations": recommendations,
            "summary": summary
        }
    })


from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from flask import send_file

@app.route("/audit-pdf", methods=["GET"])
def download_audit_pdf():
    global LAST_INPUT, LAST_PREDICTION
    print("Last input",LAST_INPUT)
    print("Last Prediction",LAST_PREDICTION)

    if LAST_INPUT is None or LAST_PREDICTION is None:
        return jsonify({"error": "No audit data available"}), 400

    audit = build_audit_report(LAST_INPUT, LAST_PREDICTION)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    # ---------- TITLE ----------
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(50, y, "Energy Audit Report")
    y -= 30

    # ---------- SUMMARY ----------
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, y, f"Predicted Energy Consumption: {audit['energy']} kWh")
    y -= 20
    pdf.drawString(50, y, f"Efficiency Score: {audit['score']}")
    y -= 20
    pdf.drawString(50, y, f"Risk Level: {audit['risk']}")
    y -= 30

    # ---------- SYSTEM OVERVIEW ----------
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "System Overview")
    y -= 20
    pdf.setFont("Helvetica", 12)

    for key, value in LAST_INPUT.items():
        pdf.drawString(60, y, f"{key}: {value}")
        y -= 18

    # ---------- FEATURE IMPACT CHART ----------
    y -= 20
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Feature Impact Analysis")
    y -= 10

    chart_img = generate_feature_chart(LAST_INPUT)
    chart = ImageReader(chart_img)

    pdf.drawImage(
        chart,
        50,
        y - 220,
        width=400,
        height=200
    )
    y -= 240

    # ---------- ANALYSIS SUMMARY ----------
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Analysis Summary")
    y -= 20
    pdf.setFont("Helvetica", 12)
    pdf.drawString(60, y, audit["summary"])
    y -= 30

    # ---------- INEFFICIENCIES ----------
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Identified Inefficiencies")
    y -= 20
    pdf.setFont("Helvetica", 12)

    for item in audit["inefficiencies"]:
        pdf.drawString(60, y, f"- {item}")
        y -= 16

    # ---------- RECOMMENDATIONS ----------
    y -= 10
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Optimization Recommendations")
    y -= 20
    pdf.setFont("Helvetica", 12)

    for rec in audit["recommendations"]:
        pdf.drawString(60, y, f"- {rec}")
        y -= 16

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Energy_Audit_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/submit-feedback", methods=["POST"])
def submit_feedback():
    data = request.json

    name = data.get("name")
    email = data.get("email")
    category = data.get("category")
    message = data.get("message")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect("feedback.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO feedback (name, email, category, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (name, email, category, message, timestamp))

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})









# if __name__ == "__main__":
#     init_feedback_db()
#     app.run(debug=True, use_reloader=False, port=5000)

if __name__ == "__main__":
    init_feedback_db()
    app.run()