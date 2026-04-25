import os
import traceback
from fastapi import FastAPI
from playwright.async_api import async_playwright
from supabase import create_client

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BRASAPP_EMAIL = os.getenv("BRASAPP_EMAIL")
BRASAPP_SENHA = os.getenv("BRASAPP_SENHA")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


@app.get("/")
def home():
    return {"status": "online", "app": "robo-brasapp-fornecedores"}


@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
        "brasapp_email_ok": bool(BRASAPP_EMAIL),
        "brasapp_senha_ok": bool(BRASAPP_SENHA),
    }


@app.get("/inspecionar-login")
async def inspecionar_login():
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            urls = [
                "https://bras.app/login",
                "https://bras.app/wp-login.php",
                "https://bras.app/minha-conta",
                "https://bras.app/"
            ]

            resultados = []

            for url in urls:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(6000)

                inputs = await page.locator("input").evaluate_all("""
                    els => els.map(i => ({
                        type: i.type || "",
                        name: i.name || "",
                        id: i.id || "",
                        placeholder: i.placeholder || "",
                        value: i.value || ""
                    }))
                """)

                buttons = await page.locator("button, input[type='submit'], a").evaluate_all("""
                    els => els.slice(0, 80).map(b => ({
                        tag: b.tagName || "",
                        text: (b.innerText || b.value || b.textContent || "").trim(),
                        type: b.type || "",
                        href: b.href || "",
                        id: b.id || "",
                        class: b.className || ""
                    }))
                """)

                html_inicio = (await page.content())[:3000]

                resultados.append({
                    "url_testada": url,
                    "url_final": page.url,
                    "titulo": await page.title(),
                    "inputs": inputs,
                    "buttons_links": buttons,
                    "html_inicio": html_inicio
                })

            await browser.close()

            return {
                "status": "ok",
                "resultados": resultados
            }

    except Exception as e:
        return {
            "status": "erro",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
