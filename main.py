from fastapi import FastAPI
from supabase import create_client
import os
import requests
from bs4 import BeautifulSoup

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
def home():
    return {"status": "online"}

@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
    }

@app.get("/coletar")
def coletar():
    url = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "lxml")

    fornecedores = []

    cards = soup.find_all("a")

    for card in cards[:30]:
        nome = card.text.strip()

        if len(nome) > 2:
            fornecedores.append({
                "nome": nome
            })

            if supabase:
                supabase.table("contatos").insert({
                    "telefone": nome
                }).execute()

    return {
        "total_encontrados": len(fornecedores),
        "exemplo": fornecedores[:5]
    }
