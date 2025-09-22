from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import json, io, os
from fpdf import FPDF
import google.generativeai as genai

# --- Vercel Specific Paths ---
# This tells Flask to look for the templates and static folders in the project's root directory,
# not in the 'api' folder where this file is located.
template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.secret_key = "supersecretkey"

# --- API Key Configuration and Validation ---
# Get API key from environment variable
api_key = os.getenv("GEN_API_KEY")
if not api_key:
    # If the environment variable is not set, a hardcoded key can be used for local testing.
    # Replace "YOUR_API_KEY_HERE" with your actual key.
    # WARNING: Do not use hardcoded keys in production.
    # api_key = "YOUR_API_KEY_HERE"
    print("Warning: GEN_API_KEY environment variable not set. API analysis will fail.")

# Configure Gemini API
genai.configure(api_key=api_key)

# In-memory storage
users = []
fir_reports = []

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
        users.append({"username": username, "password": password})
        flash("Registered successfully! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

# ---------------- Login ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        for user in users:
            if user["username"] == username and user["password"] == password:
                session["user"] = username
                flash(f"Welcome {username}!", "success")
                return redirect(url_for("dashboard"))
        flash("Invalid credentials", "error")
    return render_template("login.html")

# ---------------- Logout ----------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("home"))

# ---------------- Dashboard ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))
    return render_template("dashboard.html", reports=fir_reports)

# ---------------- FIR Analysis ----------------
def analyze_fir(description):
    # Check if API key is configured before making the call
    if not api_key:
        print("API key is missing. Skipping AI analysis.")
        return "Analysis failed: API key not configured.", "Try again later"
    
    try:
        # Use the correct, updated Gemini API model name
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(
            f"""You are a legal assistant. 
            Analyze this FIR description and provide a response that strictly adheres to the following format. Do not include any other text.
            
            Description: "{description}"
            
            Suggested Laws: [List relevant Indian laws, sections, and their descriptions]
            Recommended Actions: [Describe detailed, actionable steps to take]
            """
        )

        text = response.text  # This contains the AI's text output

        # Extract Suggested Laws and Recommended Actions from the text
        suggested_laws = "Analysis failed: Could not parse AI response."
        recommended_actions = "Try again later"

        if "Suggested Laws:" in text and "Recommended Actions:" in text:
            try:
                suggested_laws = text.split("Suggested Laws:")[1].split("Recommended Actions:")[0].strip()
                recommended_actions = text.split("Recommended Actions:")[1].strip()
            except IndexError:
                # Fallback for unexpected format
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
    if "user" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        description = request.form.get("description")
        suggested_laws, recommended_actions = analyze_fir(description)

        fir = {
            "name": request.form.get("full_name"),
            "company": request.form.get("company_name"),
            "description": description,
            "status": "Analyzed",
            "laws": suggested_laws,
            "actions": recommended_actions
        }
        fir_reports.append(fir)
        flash("FIR submitted successfully!", "success")
        return redirect(url_for("dashboard"))
    return render_template("report.html")

# ---------------- Generate PDF ----------------
@app.route("/download/<int:fir_id>")
def download_fir(fir_id):
    if "user" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    if fir_id >= len(fir_reports):
        flash("Invalid FIR ID", "error")
        return redirect(url_for("dashboard"))

    fir = fir_reports[fir_id]
    pdf_file = generate_fir_pdf(fir)
    return send_file(pdf_file, download_name=f"FIR_{fir_id+1}.pdf", as_attachment=True, mimetype='application/pdf')

def generate_fir_pdf(fir):
    pdf = FPDF()
    pdf.add_page()

    # Use built-in Arial font (no Unicode issues)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "FIR Report", ln=True, align="C")

    pdf.set_font("Arial", "", 12)
    pdf.ln(10)
    pdf.cell(0, 10, f"Name: {fir['name']}", ln=True)
    pdf.cell(0, 10, f"Company: {fir['company']}", ln=True)
    pdf.multi_cell(0, 10, f"Description: {fir['description']}")
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
