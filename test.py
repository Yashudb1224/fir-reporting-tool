import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEN_API_KEY"))
print([m.name for m in genai.list_models()])
