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
if not api_key:
    print("Warning: GEN_API_KEY environment variable not set. API analysis will fail.")
genai.configure(api_key=api_key)

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
@app.route("/download/<int:fir_id>")
def download_fir(fir_id):
    if "user_id" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    conn = get_db_connection()
    fir = conn.execute("SELECT * FROM fir_reports WHERE id = ? AND user_id = ?", (fir_id, session['user_id'])).fetchone()
    conn.close()

    if not fir:
        flash("Invalid FIR ID or you do not have permission to download this report.", "error")
        return redirect(url_for("dashboard"))

    pdf_file = generate_fir_pdf(fir)
    return send_file(pdf_file, download_name=f"FIR_{fir_id}.pdf", as_attachment=True, mimetype='application/pdf')

def generate_fir_pdf(fir):
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "FIR Report", ln=True, align="C")

    pdf.set_font("Arial", "", 12)
    pdf.ln(10)
    
    pdf.cell(0, 10, "Complainant Information", ln=True)
    pdf.cell(0, 10, f"Name: {fir['name']}", ln=True)
    pdf.cell(0, 10, f"Email: {fir['email']}", ln=True)
    pdf.cell(0, 10, f"Phone: {fir['phone']}", ln=True)
    pdf.ln(5)

    pdf.cell(0, 10, "Company Information", ln=True)
    pdf.cell(0, 10, f"Company: {fir['company']}", ln=True)
    pdf.multi_cell(0, 10, f"Company Address: {fir['company_address']}")
    pdf.cell(0, 10, f"Industry: {fir['industry']}", ln=True)
    pdf.ln(5)

    pdf.cell(0, 10, "Violation Details", ln=True)
    pdf.cell(0, 10, f"Violation Type: {fir['violation_type']}", ln=True)
    pdf.cell(0, 10, f"Incident Date: {fir['incident_date']}", ln=True)
    pdf.multi_cell(0, 10, f"Description: {fir['description']}")
    pdf.ln(5)

    pdf.cell(0, 10, "Accused Details", ln=True)
    pdf.cell(0, 10, f"Name: {fir['accused_name']}", ln=True)
    pdf.cell(0, 10, f"Role: {fir['accused_role']}", ln=True)
    pdf.ln(5)

    pdf.cell(0, 10, "Witness Details", ln=True)
    pdf.cell(0, 10, f"Name: {fir['witness_name']}", ln=True)
    pdf.cell(0, 10, f"Contact: {fir['witness_contact']}", ln=True)
    pdf.multi_cell(0, 10, f"Location Details: {fir['location_details']}")
    pdf.ln(5)

    pdf.cell(0, 10, "Legal Analysis", ln=True)
    pdf.multi_cell(0, 10, f"Suggested Laws: {fir['laws']}")
    pdf.multi_cell(0, 10, f"Recommended Actions: {fir['actions']}")
    
    pdf_output = pdf.output(dest='S').encode('latin-1')
    return io.BytesIO(pdf_output)

# ---------------- Privacy ----------------
@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

if __name__ == "__main__":
    app.run(debug=True)
