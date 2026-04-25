from fastapi import FastAPI
from playwright.async_api import async_playwright
import os
import traceback
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


@app.get("/coletar")
async def coletar(limite: int = 5):
    try:
        async with async_playwright() as p:

            # 🔥 FIREFOX (resolve crash)
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            # =========================
            # LOGIN
            # =========================
            await page.goto("https://bras.app/login", timeout=60000)

            await page.fill('input[type="email"]', BRASAPP_EMAIL)
            await page.fill('input[type="password"]', BRASAPP_SENHA)

            await page.click('button[type="submit"]')

            await page.wait_for_timeout(5000)

            # =========================
            # IR PARA LISTA
            # =========================
            await page.goto("https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories")

            await page.wait_for_timeout(5000)

            fornecedores = await page.query_selector_all("a")

            dados = []

            for i, fornecedor in enumerate(fornecedores[:limite]):
                try:
                    nome = await fornecedor.inner_text()

                    # abrir perfil
                    await fornecedor.click()
                    await page.wait_for_timeout(3000)

                    # pegar instagram
                    instagram = ""
                    insta = await page.query_selector('a[href*="instagram"]')
                    if insta:
                        instagram = await insta.get_attribute("href")

                    # pegar whatsapp
                    whatsapp = ""
                    zap = await page.query_selector('a[href*="wa.me"], a[href*="whatsapp"]')
                    if zap:
                        whatsapp = await zap.get_attribute("href")

                    registro = {
                        "nome": nome,
                        "instagram": instagram,
                        "whatsapp": whatsapp,
                    }

                    dados.append(registro)

                    # salvar no supabase
                    supabase.table("fornecedores").insert(registro).execute()

                    # voltar
                    await page.go_back()
                    await page.wait_for_timeout(3000)

                except Exception as e:
                    print("Erro fornecedor:", e)

            await browser.close()

            return {
                "status": "finalizado",
                "total": len(dados),
                "dados": dados
            }

    except Exception as e:
        print("ERRO GERAL:")
        print(traceback.format_exc())

        return {
            "status": "erro",
            "erro": str(e)
        }
