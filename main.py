from fastapi import FastAPI
from supabase import create_client
import os

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

@app.get("/")
def home():
    return {"status": "online", "app": "robo-brasapp-fornecedores"}

@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
    }

@app.get("/rodar")
def rodar():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"erro": "SUPABASE_URL ou SUPABASE_KEY não configuradas"}

    return {
        "status": "ok",
        "mensagem": "Robô preparado. Próximo passo: adicionar coleta com Playwright."
    }
