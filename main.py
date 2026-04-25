import os
import re
import traceback
from fastapi import FastAPI
from supabase import create_client
from playwright.async_api import async_playwright

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BRASAPP_EMAIL = os.getenv("BRASAPP_EMAIL")
BRASAPP_SENHA = os.getenv("BRASAPP_SENHA")

URL_LOGIN = "https://bras.app/wp-login.php"
URL_LISTA = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def limpar_texto(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


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


async def fazer_login(page):
    print("🔐 Abrindo wp-login...")
    await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)

    # WordPress usa user_login e user_pass
    await page.fill("#user_login", BRASAPP_EMAIL, timeout=15000)
    await page.fill("#user_pass", BRASAPP_SENHA, timeout=15000)
    await page.click("#wp-submit", timeout=15000)

    await page.wait_for_timeout(8000)

    return {
        "url_atual": page.url,
        "login_ok": "wp-login.php" not in page.url
    }


async def carregar_lista(page):
    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(10000)

    for _ in range(6):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2000)


async def pegar_fornecedores(page, limite):
    links = await page.locator("a").evaluate_all("""
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
    """)

    fornecedores = []
    vistos = set()

    for item in links:
        href = item.get("href", "")
        nome = limpar_texto(item.get("text", ""))

        if "/resultado/" in href and href not in vistos:
            vistos.add(href)
            fornecedores.append({"nome": nome, "link": href})

    return fornecedores[:limite]


async def extrair_fornecedor(page, fornecedor):
    await page.goto(fornecedor["link"], wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)

    nome = fornecedor["nome"]

    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            nome = await h1.inner_text()
    except Exception:
        pass

    instagram = ""
    whatsapp = ""

    links = await page.locator("a").evaluate_all("""
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
    """)

    for item in links:
        href = item.get("href", "")

        if not instagram and "instagram.com" in href:
            instagram = href

        if not whatsapp and (
            "wa.me" in href
            or "api.whatsapp.com" in href
            or "web.whatsapp.com" in href
            or "whatsapp" in href.lower()
        ):
            whatsapp = href

    return {
        "nome": limpar_texto(nome),
        "instagram": instagram,
        "whatsapp": whatsapp,
        "categoria": "",
        "regiao": "",
        "link_perfil": fornecedor["link"],
        "status": "coletado"
    }


@app.get("/coletar")
async def coletar(limite: int = 3):
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)

            context = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )

            page = await context.new_page()

            login = await fazer_login(page)

            if not login["login_ok"]:
                html = (await page.content())[:2500]
                await browser.close()
                return {
                    "status": "erro_login",
                    "login": login,
                    "html_inicio": html
                }

            await carregar_lista(page)
            fornecedores = await pegar_fornecedores(page, limite)

            if not fornecedores:
                html = (await page.content())[:2500]
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "url_atual": page.url,
                    "html_inicio": html
                }

            dados = []
            erros = []

            for fornecedor in fornecedores:
                try:
                    registro = await extrair_fornecedor(page, fornecedor)

                    supabase.table("fornecedores_brasapp").upsert(
                        registro,
                        on_conflict="link_perfil"
                    ).execute()

                    dados.append(registro)

                except Exception as e:
                    erros.append({
                        "fornecedor": fornecedor,
                        "erro": str(e)
                    })

            await browser.close()

            return {
                "status": "finalizado",
                "total_coletado": len(dados),
                "total_erros": len(erros),
                "dados": dados,
                "erros": erros
            }

    except Exception as e:
        return {
            "status": "erro_geral",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
