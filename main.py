from fastapi import FastAPI
from supabase import create_client
from playwright.async_api import async_playwright
import os
import re

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BRASAPP_EMAIL = os.getenv("BRASAPP_EMAIL")
BRASAPP_SENHA = os.getenv("BRASAPP_SENHA")

URL_LISTA = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
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


def limpar_whatsapp(link):
    if not link:
        return ""
    return link.strip()


def limpar_instagram(link):
    if not link:
        return ""
    return link.strip()


@app.get("/coletar")
async def coletar(limite: int = 10):
    if not supabase:
        return {"erro": "Supabase não configurado"}

    if not BRASAPP_EMAIL or not BRASAPP_SENHA:
        return {"erro": "BRASAPP_EMAIL ou BRASAPP_SENHA não configurados"}

    coletados = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        page = await browser.new_page()

        # Abre o site
        await page.goto(URL_LISTA, wait_until="networkidle", timeout=60000)

        # Se aparecer tela de login, tenta logar
        try:
            email_input = page.locator("input[type='email'], input[name='email']").first
            if await email_input.count() > 0:
                await email_input.fill(BRASAPP_EMAIL)

                senha_input = page.locator("input[type='password'], input[name='password']").first
                await senha_input.fill(BRASAPP_SENHA)

                botao_login = page.locator("button:has-text('Entrar'), button:has-text('Login'), button[type='submit']").first
                await botao_login.click()

                await page.wait_for_timeout(5000)
                await page.goto(URL_LISTA, wait_until="networkidle", timeout=60000)
        except Exception:
            pass

        await page.wait_for_timeout(5000)

        # Pega links internos dos fornecedores
        links = await page.locator("a[href*='/resultado/']").evaluate_all(
            """els => els.map(a => ({
                href: a.href,
                text: a.innerText
            }))"""
        )

        # Remove duplicados
        vistos = set()
        fornecedores = []
        for item in links:
            href = item.get("href")
            nome = item.get("text", "").strip()

            if href and href not in vistos:
                vistos.add(href)
                fornecedores.append({
                    "nome": nome,
                    "link": href
                })

        fornecedores = fornecedores[:limite]

        for fornecedor in fornecedores:
            try:
                await page.goto(fornecedor["link"], wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(3000)

                titulo = ""
                try:
                    titulo = await page.locator("h1, h2").first.inner_text()
                except Exception:
                    titulo = fornecedor["nome"]

                instagram = ""
                whatsapp = ""

                todos_links = await page.locator("a").evaluate_all(
                    """els => els.map(a => ({
                        href: a.href,
                        text: a.innerText
                    }))"""
                )

                for a in todos_links:
                    href = a.get("href", "")

                    if "instagram.com" in href and not instagram:
                        instagram = href

                    if ("wa.me" in href or "whatsapp" in href or "api.whatsapp.com" in href) and not whatsapp:
                        whatsapp = href

                registro = {
                    "nome": titulo.strip() if titulo else fornecedor["nome"],
                    "instagram": limpar_instagram(instagram),
                    "whatsapp": limpar_whatsapp(whatsapp),
                    "link_perfil": fornecedor["link"],
                    "status": "coletado"
                }

                supabase.table("fornecedores_brasapp").upsert(
                    registro,
                    on_conflict="link_perfil"
                ).execute()

                coletados.append(registro)

            except Exception as e:
                coletados.append({
                    "nome": fornecedor.get("nome"),
                    "link_perfil": fornecedor.get("link"),
                    "erro": str(e)
                })

        await browser.close()

    return {
        "status": "finalizado",
        "total_coletado": len(coletados),
        "dados": coletados
    }
