from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash
import json, io, os, sqlite3, re, textwrap
from fpdf import FPDF
import google.generativeai as genai

app = Flask(__name__)
app.secret_key = "supersecretkey"

# --- Database Setup ---
DATABASE = 'fir_portal.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def create_db_tables():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS fir_reports (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            company TEXT,
            company_address TEXT,
            industry TEXT,
            email TEXT,
            phone TEXT,
            accused_name TEXT,
            accused_role TEXT,
            witness_name TEXT,
            witness_contact TEXT,
            location_details TEXT,
            violation_type TEXT,
            incident_date TEXT,
            description TEXT,
            status TEXT,
            laws TEXT,
            actions TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

create_db_tables()

# --- API Key Configuration ---
api_key = os.getenv("GEN_API_KEY")
DEFAULT_MODEL = os.getenv("GEN_MODEL", "gemini-1.5-flash")
FALLBACK_MODELS = [
    DEFAULT_MODEL,
    "gemini-1.5",
    "gemini-1.5-pro",
    "gemini-1.5-preview",
    "gemini-1.0",
]

if api_key:
    print("API key found. Configuring Gemini.")
    genai.configure(api_key=api_key)
else:
    print("API key not found. Gemini will not be configured.")

# ---------------- Home ----------------
@app.route("/")
def home():
    return render_template("index.html")

# ---------------- Register ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        password_hash = generate_password_hash(password)

        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            flash("Registered successfully! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "error")
            conn.close()
            return render_template("register.html")
        finally:
            conn.close()

    return render_template("register.html")

# ---------------- Login ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session["user_id"] = user['id']
            session["user"] = user['username']
            flash(f"Welcome {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials", "error")

    return render_template("login.html")

# ---------------- Logout ----------------
@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("home"))

# ---------------- Dashboard ----------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    reports = conn.execute("SELECT * FROM fir_reports WHERE user_id = ?", (session['user_id'],)).fetchall()
    conn.close()

    return render_template("dashboard.html", reports=reports)

# ---------------- FIR Analysis ----------------
def analyze_fir(description):
    if not api_key:
        print("API key is missing. Skipping AI analysis.")
        return "Analysis failed: API key not configured.", "Try again later"

    prompt = f"""You are a legal assistant.
Analyze this FIR description and provide a response that strictly adheres to the following format. Do not include any other text.

Description: "{description}"

Suggested Laws: [List relevant Indian laws, sections, and short descriptions]
Recommended Actions: [Describe detailed, actionable steps to take]
"""
    last_exception = None
    tried = []
    for candidate in FALLBACK_MODELS:
        if not candidate:
            continue
        try:
            tried.append(candidate)
            model = genai.GenerativeModel(candidate)
            response = model.generate_content(prompt)
            text = getattr(response, "text", None)
            if not text:
                text = str(response)

            suggested_laws = "Analysis failed: Could not parse AI response."
            recommended_actions = "Try again later"

            if text and "Suggested Laws:" in text and "Recommended Actions:" in text:
                suggested_laws = text.split("Suggested Laws:")[1].split("Recommended Actions:")[0].strip()
                recommended_actions = text.split("Recommended Actions:")[1].strip()
            elif text:
                parts = text.split("Recommended Actions:")
                if len(parts) == 2:
                    suggested_laws = parts[0].replace("Suggested Laws:", "").strip()
                    recommended_actions = parts[1].strip()
                else:
                    suggested_laws = "See AI analysis below."
                    recommended_actions = text.strip()

            return suggested_laws, recommended_actions

        except Exception as e:
            last_exception = e
            print(f"AI attempt with model '{candidate}' failed: {e}")
            continue

    guidance = (
        "Analysis failed: Could not reach a supported model. "
        "Make sure your API key is correct and the model name is available."
    )
    print(f"AI analysis error after trying models {tried}: {last_exception}")
    return guidance, "Try again later"

# ---------------- File FIR ----------------
@app.route("/report", methods=["GET", "POST"])
def report():
    if "user_id" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        description = request.form.get("description")
        suggested_laws, recommended_actions = analyze_fir(description)

        conn = get_db_connection()
        conn.execute('''
            INSERT INTO fir_reports (
                user_id, name, company, company_address, industry, email, phone, 
                accused_name, accused_role, witness_name, witness_contact, location_details, 
                violation_type, incident_date, description, status, laws, actions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session['user_id'],
            request.form.get("full_name"),
            request.form.get("company_name"),
            request.form.get("company_address"),
            request.form.get("industry"),
            request.form.get("email"),
            request.form.get("phone"),
            request.form.get("accused_name"),
            request.form.get("accused_role"),
            request.form.get("witness_name"),
            request.form.get("witness_contact"),
            request.form.get("location_details"),
            request.form.get("violation_type"),
            request.form.get("incident_date"),
            description,
            "Analyzed",
            suggested_laws,
            recommended_actions
        ))
        conn.commit()
        conn.close()

        flash("FIR submitted successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("report.html")

# ---------------- Generate PDF ----------------
def safe_text(text, width=100):
    if not text:
        return "N/A"
    text = re.sub(r"(\S{%d,})" % width,
                  lambda m: " ".join(textwrap.wrap(m.group(0), width)),
                  text)
    return "\n".join(textwrap.wrap(text, width))

def generate_fir_pdf(fir_dict):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)

    try:
        if os.path.exists("fonts/DejaVuSans.ttf") and os.path.exists("fonts/DejaVuSans-Bold.ttf"):
            pdf.add_font("DejaVu", "", "fonts/DejaVuSans.ttf", uni=True)
            pdf.add_font("DejaVu", "B", "fonts/DejaVuSans-Bold.ttf", uni=True)
            regular_font = ("DejaVu", "")
            bold_font = ("DejaVu", "B")
        else:
            raise FileNotFoundError("DejaVu fonts not found.")
    except Exception as e:
        print(f"Font fallback: {e}")
        regular_font = ("Arial", "")
        bold_font = ("Arial", "B")

    pdf.set_font(bold_font[0], bold_font[1], 16)
    pdf.cell(0, 10, "First Information Report (FIR)", ln=True, align="C")
    pdf.ln(8)

    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font(regular_font[0], regular_font[1], 12)

    fields = [
        ("Complainant", "name"),
        ("Email", "email"),
        ("Phone", "phone"),
        ("Accused", "accused_name"),
        ("Role", "accused_role"),
        ("Incident Date", "incident_date"),
        ("Location", "location_details"),
        ("Violation Type", "violation_type"),
        ("Description", "description"),
        ("Company", "company"),
        ("Company Address", "company_address"),
        ("Industry", "industry"),
        ("Suggested Laws", "laws"),
        ("Recommended Actions", "actions")
    ]

    for label, key in fields:
        text = safe_text(fir_dict.get(key, "N/A"))
        pdf.set_font(bold_font[0], bold_font[1], 12)
        pdf.cell(0, 8, f"{label}:", ln=True)
        pdf.set_font(regular_font[0], regular_font[1], 12)
        pdf.multi_cell(width, 6, text)
        pdf.ln(2)

    # ✅ FIXED — remove encode, handle bytearray directly
    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode("latin-1")
    return io.BytesIO(bytes(pdf_bytes))

# --- Download route ---
@app.route("/download/<int:fir_id>")
def download_fir(fir_id):
    if "user_id" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    fir_row = conn.execute(
        "SELECT * FROM fir_reports WHERE id = ? AND user_id = ?",
        (fir_id, session['user_id'])
    ).fetchone()
    conn.close()

    if not fir_row:
        flash("Invalid FIR ID or you do not have permission to download this report.", "error")
        return redirect(url_for("dashboard"))

    fir_dict = dict(fir_row)
    pdf_file = generate_fir_pdf(fir_dict)
    pdf_file.seek(0)
    return send_file(pdf_file, download_name=f"FIR_{fir_id}.pdf", as_attachment=True, mimetype="application/pdf")

# ---------------- Privacy ----------------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

if __name__ == "__main__":
    app.run(debug=True)
