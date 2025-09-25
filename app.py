from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash
import json, io, os, sqlite3
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

# Create the tables on startup
create_db_tables()

# --- API Key Configuration and Validation ---
api_key = os.getenv("GEN_API_KEY")
if api_key:
    print("API key found. Configuring Gemini.")
    genai.configure(api_key=api_key)
else:
    print("API key not found. Gemini will not be configured.")
    # You might want to consider raising an error here in a production environment
    # to prevent the app from running without the key.

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
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            f"""You are a legal assistant. 
            Analyze this FIR description and provide a response that strictly adheres to the following format. Do not include any other text.
            
            Description: "{description}"
            
            Suggested Laws: [List relevant Indian laws, sections, and their descriptions]
            Recommended Actions: [Describe detailed, actionable steps to take]
            """
        )

        text = response.text
        suggested_laws = "Analysis failed: Could not parse AI response."
        recommended_actions = "Try again later"

        if "Suggested Laws:" in text and "Recommended Actions:" in text:
            try:
                suggested_laws = text.split("Suggested Laws:")[1].split("Recommended Actions:")[0].strip()
                recommended_actions = text.split("Recommended Actions:")[1].strip()
            except IndexError:
                suggested_laws = "Analysis failed: Unexpected response format from AI."
                recommended_actions = "Try again later"
        
        if not text:
            suggested_laws = "Analysis failed: AI response was blocked by safety filters or an internal error occurred."
            recommended_actions = "Try again later"

        return suggested_laws, recommended_actions

    except Exception as e:
        print(f"AI analysis error: {type(e).__name__}: {e}")
        return "Analysis failed: An API or network error occurred. Check the server console for details.", "Try again later"

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
from flask import send_file
import io
from fpdf import FPDF
import re
import textwrap

# --- Safe text wrapper ---
def safe_text(text, width=100):
    """Wrap long text and break unbreakable words."""
    if not text:
        return "N/A"
    text = re.sub(r"(\S{%d,})" % width,
                  lambda m: " ".join(textwrap.wrap(m.group(0), width)),
                  text)
    return "\n".join(textwrap.wrap(text, width))

# --- PDF generator ---
# --- PDF generator ---
def generate_fir_pdf(fir_dict):
    pdf = FPDF()
    pdf.add_page()

    # Set page margins
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)

    # Add fonts
    pdf.add_font("DejaVu", "", "fonts/DejaVuSans.ttf", uni=True)
    pdf.add_font("DejaVu", "B", "fonts/DejaVuSans-Bold.ttf", uni=True)

    # Title
    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, "First Information Report (FIR)", ln=True, align="C")
    pdf.ln(10)

    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("DejaVu", "", 12)

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
        pdf.set_font("DejaVu", "B", 12)
        pdf.multi_cell(width, 8, f"{label}:", ln=True)
        pdf.set_font("DejaVu", "", 12)
        pdf.multi_cell(width, 8, text)
        pdf.ln(2)  # small spacing after each field

    pdf_bytes = pdf.output(dest="S")
    return io.BytesIO(pdf_bytes)




# --- Fixed download route ---
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

    # Convert sqlite3.Row to dict
    fir_dict = dict(fir_row)

    pdf_file = generate_fir_pdf(fir_dict)
    return send_file(pdf_file, download_name=f"FIR_{fir_id}.pdf", as_attachment=True, mimetype="application/pdf")



# ---------------- Privacy ----------------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

if __name__ == "__main__":
    app.run(debug=True)
