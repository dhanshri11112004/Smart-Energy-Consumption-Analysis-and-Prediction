from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import google.generativeai as genai
from ai.groq_api import ask_groq
import pickle
import numpy as np
import os
import json
import tempfile
import pyttsx3
import re
import sqlite3
from datetime import datetime
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import os
import sqlite3
import smtplib

from email.message import EmailMessage
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")


LAST_INPUT = None
LAST_PREDICTION = None
TOTAL_PREDICTIONS = 0

# ---------------- APP INIT ----------------

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "..", "frontend"),
    static_folder=os.path.join(BASE_DIR, "..", "frontend"),
    static_url_path=""
)
CORS(app)
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")

jwt = JWTManager(app)



@app.route("/")
def home():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login_user():

    data = request.json

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({
            "status": "error",
            "message": "Email and password are required"
        }), 400

    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, email, password FROM users WHERE email=?",
        (email,)
    )

    user = cur.fetchone()

    if not user:
        conn.close()

        return jsonify({
            "status": "error",
            "message": "Invalid email or password"
        }), 401

    user_id, name, user_email, stored_password = user

    password_valid = False

    # New hashed passwords
    if stored_password.startswith(("scrypt:", "pbkdf2:")):

        try:
            password_valid = check_password_hash(
                stored_password,
                password
            )

        except Exception:
            password_valid = False

    else:
        # Old users whose passwords are still plain text
        password_valid = (stored_password == password)

        # Upgrade old password to a secure hash
        if password_valid:

            hashed_password = generate_password_hash(password)

            cur.execute(
                "UPDATE users SET password=? WHERE id=?",
                (hashed_password, user_id)
            )

            conn.commit()

    if not password_valid:

        conn.close()

        return jsonify({
            "status": "error",
            "message": "Invalid email or password"
        }), 401

    access_token = create_access_token(
        identity=user_email
    )

    conn.close()

    return jsonify({
        "status": "success",
        "token": access_token,
        "user": {
            "id": user_id,
            "name": name,
            "email": user_email
        }
    })

@app.route("/register", methods=["POST"])
def register_user():

    data = request.json

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:

        return jsonify({
            "status": "error",
            "message": "All fields are required"
        }), 400

    if len(password) < 6:

        return jsonify({
            "status": "error",
            "message": "Password must contain at least 6 characters"
        }), 400

    hashed_password = generate_password_hash(password)

    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    try:

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT UNIQUE,
                password TEXT
            )
        """)

        cur.execute(
            """
            INSERT INTO users(name, email, password)
            VALUES(?,?,?)
            """,
            (
                name,
                email,
                hashed_password
            )
        )

        conn.commit()

        return jsonify({
            "status": "success",
            "message": "Registration successful"
        })

    except sqlite3.IntegrityError:

        return jsonify({
            "status": "error",
            "message": "Email already registered"
        }), 400

    finally:

        conn.close()


@app.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():

    current_email = get_jwt_identity()

    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, email FROM users WHERE email=?",
        (current_email,)
    )

    user = cur.fetchone()

    conn.close()

    if not user:

        return jsonify({
            "status": "error",
            "message": "User not found"
        }), 404

    return jsonify({
        "status": "success",
        "user": {
            "id": user[0],
            "name": user[1],
            "email": user[2]
        }
    })



@app.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():

    current_email = get_jwt_identity()

    data = request.json

    name = data.get("name", "").strip()
    new_email = data.get("email", "").strip().lower()

    if not name or not new_email:

        return jsonify({
            "status": "error",
            "message": "Name and email are required"
        }), 400

    conn = sqlite3.connect("users.db")
    cur = conn.cursor()

    try:

        cur.execute(
            """
            UPDATE users
            SET name=?, email=?
            WHERE email=?
            """,
            (
                name,
                new_email,
                current_email
            )
        )

        if cur.rowcount == 0:

            conn.close()

            return jsonify({
                "status": "error",
                "message": "User not found"
            }), 404

        conn.commit()

        # New JWT because email may have changed
        new_token = create_access_token(
            identity=new_email
        )

        cur.execute(
            "SELECT id, name, email FROM users WHERE email=?",
            (new_email,)
        )

        user = cur.fetchone()

        conn.close()

        return jsonify({
            "status": "success",
            "message": "Profile updated successfully",
            "token": new_token,
            "user": {
                "id": user[0],
                "name": user[1],
                "email": user[2]
            }
        })

    except sqlite3.IntegrityError:

        conn.close()

        return jsonify({
            "status": "error",
            "message": "Email already registered"
        }), 400


@app.route("/change-password", methods=["PUT"])
@jwt_required()
def change_password():

    current_email = get_jwt_identity()

    print("========== CHANGE PASSWORD DEBUG ==========")
    print("Raw request data:", request.data)
    print("Request content type:", request.content_type)
    print("Request JSON:", request.get_json(silent=True))
    print("==========================================")

    data = request.get_json(silent=True) or {}

    current_password = (
        data.get("current_password")
        or data.get("currentPassword")
        or ""
    ).strip()

    new_password = (
        data.get("new_password")
        or data.get("newPassword")
        or ""
    ).strip()


    # Check required fields

    if not current_password or not new_password:

        print("❌ Password fields missing")

        return jsonify({
            "status": "error",
            "message": "Current and new passwords are required"
        }), 400


    # Password length

    if len(new_password) < 6:

        return jsonify({
            "status": "error",
            "message": "New password must be at least 6 characters"
        }), 400


    # Current and new password should not be same

    if current_password == new_password:

        return jsonify({
            "status": "error",
            "message": "New password must be different from current password"
        }), 400


    # Connect database

    conn = sqlite3.connect("users.db")

    cur = conn.cursor()


    # Find user

    cur.execute(
        "SELECT password FROM users WHERE email=?",
        (current_email,)
    )

    row = cur.fetchone()


    if not row:

        conn.close()

        return jsonify({
            "status": "error",
            "message": "User not found"
        }), 404


    stored_password = row[0]


    # Check current password
    #
    # Supports both:
    # 1. Old plain-text passwords
    # 2. New hashed passwords

    try:

        if stored_password.startswith(("scrypt:", "pbkdf2:")):

            valid_password = check_password_hash(
                stored_password,
                current_password
            )

        else:

            valid_password = (
                stored_password == current_password
            )

    except Exception:

        valid_password = (
            stored_password == current_password
        )


    if not valid_password:

        conn.close()

        return jsonify({
            "status": "error",
            "message": "Current password is incorrect"
        }), 401


    # Save new password

    hashed_password = generate_password_hash(new_password)

    cur.execute(
        """
        UPDATE users
        SET password=?
        WHERE email=?
        """,
        (hashed_password, current_email)
    )

    conn.commit()

    conn.close()


    print("✅ Password changed for:", current_email)


    return jsonify({
        "status": "success",
        "message": "Password changed successfully"
    })



# ---------------- LOAD ML MODEL ----------------
MODEL_PATH = "model/energy_xgb_model.pkl"

try:
    with open(MODEL_PATH, "rb") as f:
        ml_model = pickle.load(f)
    print("✅ ML Model loaded successfully")
except Exception as e:
    print(f"❌ ML Model Load Error: {e}")



genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model=genai.GenerativeModel("gemini-2.0-flash-lite-preview-02-05")

# ---------------- FEATURE ORDER ----------------
FEATURE_ORDER = ["HVACUsage", "Occupancy", "Temperature", "RenewableEnergy", "Hour", "IsWeekend"]

# ---------------- HELPERS ----------------


def ask_ai(prompt):
    try:
        print("Using Gemini...")

        response = model.generate_content(prompt)

        return response.text

    except Exception as e:
        print("Gemini Error:", e)
        print("Switching to Groq...")

        return ask_groq(prompt)

def init_users_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT
        )
    """)

    conn.commit()
    conn.close()


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
        response_text = ask_ai(prompt)

        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if match:
            return json.loads(match.group())
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
@jwt_required()
def predict():
    global LAST_INPUT, LAST_PREDICTION

    data = request.json
    prediction = run_prediction(data)
    global TOTAL_PREDICTIONS
    TOTAL_PREDICTIONS += 1

    LAST_INPUT = data
    LAST_PREDICTION = prediction

    return jsonify({
        "status": "success",
        "prediction": prediction,
        "unit": "kWh"
    })




@app.route("/offline-predict", methods=["POST"])
@jwt_required()
def offline_predict():
    global TOTAL_PREDICTIONS
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
        TOTAL_PREDICTIONS += len(preds)
        print("TOTAL =", TOTAL_PREDICTIONS)
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
@jwt_required()
def chat():
    global LAST_INPUT, LAST_PREDICTION,TOTAL_PREDICTIONS

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

    # ---------------- 1️ CURRENT PREDICTION STATE ----------------
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
        answer = ask_ai(state_prompt)

        return jsonify({
    "   response": answer.strip()
})

   
    # ---------------- 3️⃣ MODEL / FEATURE / ML QUESTIONS ----------------
    MODEL_QUESTIONS = [
    "xgboost",
    "model",
    "machine learning",
    "ml",
    "ai",
    "feature",
    "features",
    "input",
    "prediction model",
    "how does xgboost",
    "how does the model",
    "how model works",
    "how prediction works"
]

    if any(k in msg for k in MODEL_QUESTIONS):
        model_prompt = f"""
You are an AI assistant for a Building Energy Consumption Prediction System.

System Information:
{MODEL_CONTEXT}

Answer ONLY the user's question.

Rules:
- If the user asks about XGBoost, explain how XGBoost works.
- If the user asks about features, explain the input features.
- If the user asks about machine learning, explain why ML is used.
- Do NOT explain the latest prediction.
- Do NOT mention prediction values unless the user explicitly asks about them.
- Maximum 6 lines.
- Plain English.

Question:
{user_msg}
"""
        answer = ask_ai(model_prompt)

        return jsonify({
            "type":"chat",
            "response":answer.strip()
})


     # ---------------- 2️⃣ WHY ENERGY IS HIGH / EXPLANATION ----------------
    # ---------------- 2️⃣ WHY ENERGY IS HIGH / EXPLANATION ----------------
    
    is_why_question = (
    ("why" in msg or "reason" in msg or "explain" in msg)
    and (
        "energy" in msg
        or "consumption" in msg
        or "usage" in msg
        or "prediction" in msg
    )
)
    print("WHY CHECK:", is_why_question, "LAST_INPUT:", LAST_INPUT)

    if LAST_INPUT and is_why_question:

        explain_prompt = f"""
You are an AI assistant for an energy consumption prediction system.

The system has already generated a prediction using an XGBoost machine learning model.

Latest predicted energy consumption:
{LAST_PREDICTION} kWh

Latest input values:
{LAST_INPUT}

Input feature meanings:

HVACUsage:
0 = OFF
1 = ON

Occupancy:
Number of people

Temperature:
Temperature in Celsius

RenewableEnergy:
Renewable energy percentage

Hour:
Hour of the day from 0 to 23

IsWeekend:
0 = Weekday
1 = Weekend

Explain why the predicted energy consumption may be high based ONLY on these provided values.

Rules:
- Do not say you need personal information.
- Do not ask for personal details.
- Do not invent any values.
- Do not change the prediction value.
- Do not calculate a new prediction.
- Explain the possible contribution of the provided input features.
- Keep the answer simple.
- Maximum 5 lines.

User question:
{user_msg}
"""

        answer = ask_ai(explain_prompt)

        return jsonify({
        "type": "prediction",
        "prediction": LAST_PREDICTION,
        "unit": "kWh",
        "response": answer.strip()
        })



        # ---------------- CURRENT ENERGY CONSUMPTION ----------------

    if LAST_PREDICTION is not None and (
    "what is my energy consumption" in msg
    or "what is my energy usage" in msg
    or "what is my consumption" in msg
    or ("what" in msg and "energy consumption" in msg)
    or "energy consumption value" in msg
    or "predicted value" in msg
    or "prediction value" in msg
    or "what is the energy value" in msg
    ):

        return jsonify({
        "type": "chat",
        "response": f"Your predicted energy consumption is {LAST_PREDICTION} kWh."
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
        response_text = ask_ai(extract_prompt)

        match = re.search(r"\{.*\}", response_text, re.DOTALL)
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
        TOTAL_PREDICTIONS += 1
        LAST_INPUT = params
        LAST_PREDICTION = prediction

        return jsonify({
    "type": "prediction",
    "prediction": prediction,
    "unit": "kWh",
    "response": f"The predicted building energy consumption is {prediction} kWh."
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
    answer = ask_ai(general_prompt)

    return jsonify({
    "type":"chat",
    "response":answer.strip()
})

@app.route("/extract-inputs", methods=["POST"])
@jwt_required()
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
@jwt_required()
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
@jwt_required()

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


def send_feedback_email(name, email, category, message, timestamp):

    msg = EmailMessage()

    msg["Subject"] = f"[Smart Energy] New {category}"
    msg["From"] = MAIL_USERNAME
    msg["To"] = ADMIN_EMAIL
    msg["Reply-To"] = email

    msg.set_content(f"""
New feedback has been submitted on the Smart Energy Platform.

-----------------------------------
USER DETAILS
-----------------------------------

Name: {name}
Email: {email}

-----------------------------------
FEEDBACK
-----------------------------------

Category: {category}

Message:
{message}

-----------------------------------
SUBMISSION DETAILS
-----------------------------------

Submitted At: {timestamp}
""")

    with smtplib.SMTP("smtp.gmail.com", 587) as server:

        server.starttls()

        server.login(
            MAIL_USERNAME,
            MAIL_PASSWORD
        )

        server.send_message(msg)


def send_user_confirmation_email(name, email, category):

    msg = EmailMessage()

    msg["Subject"] = "Thank You for Your Feedback - Smart Energy"
    msg["From"] = MAIL_USERNAME
    msg["To"] = email

    msg.set_content(f"""
Hi {name},

Thank you for submitting your feedback to the
Smart Energy Consumption Analysis & Prediction Platform.

Your feedback has been successfully received.

Category: {category}

We appreciate your time and contribution.

Regards,
Smart Energy Team
""")

    with smtplib.SMTP("smtp.gmail.com", 587) as server:

        server.starttls()

        server.login(
            MAIL_USERNAME,
            MAIL_PASSWORD
        )

        server.send_message(msg)

@app.route("/submit-feedback", methods=["POST"])
def submit_feedback():

    data = request.json

    name = data.get("name")
    email = data.get("email")
    category = data.get("category")
    message = data.get("message")

    # Basic validation
    if not name or not email or not category or not message:
        return jsonify({
            "status": "error",
            "message": "All fields are required."
        }), 400

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------
    # 1. SAVE FEEDBACK TO SQLITE
    # ------------------------------------

    conn = sqlite3.connect("feedback.db")
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO feedback
        (name, email, category, message, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        email,
        category,
        message,
        timestamp
    ))

    conn.commit()
    conn.close()

    # ------------------------------------
    # 2. SEND EMAIL TO ADMIN
    # ------------------------------------

    admin_email_status = "failed"

    try:

        send_feedback_email(
            name,
            email,
            category,
            message,
            timestamp
        )

        admin_email_status = "sent"

    except Exception as e:

        print("Admin email error:", e)

    # ------------------------------------
    # 3. SEND CONFIRMATION TO USER
    # ------------------------------------

    user_email_status = "failed"

    try:

        send_user_confirmation_email(
            name,
            email,
            category
        )

        user_email_status = "sent"

    except Exception as e:

        print("User confirmation email error:", e)

    # ------------------------------------
    # 4. RESPONSE TO FRONTEND
    # ------------------------------------

    return jsonify({
        "status": "success",
        "message": "Feedback submitted successfully.",
        "admin_email": admin_email_status,
        "user_email": user_email_status
    })

@app.route("/dashboard")
@jwt_required()
def dashboard():
    return jsonify({
        "total_predictions": TOTAL_PREDICTIONS
    })


init_users_db()
init_feedback_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
