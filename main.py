import os, re, traceback
from fastapi import FastAPI
from supabase import create_client
from playwright.async_api import async_playwright

app = FastAPI()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BRASAPP_EMAIL = os.getenv("BRASAPP_EMAIL")
BRASAPP_SENHA = os.getenv("BRASAPP_SENHA")

URL_LOGIN = "https://bras.app/minha-conta/"
URL_LISTA = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def limpar(t):
    return re.sub(r"\s+", " ", t or "").strip()

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
    await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    await page.fill("#username", BRASAPP_EMAIL, timeout=15000)
    await page.fill("#password", BRASAPP_SENHA, timeout=15000)
    await page.locator("button:has-text('Entrar')").first.click(timeout=15000)

    await page.wait_for_timeout(8000)

    html = await page.content()
    return "Sair" in html or "logout" in html or "Minha conta" in await page.title()

async def carregar_lista(page):
    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(12000)

    for _ in range(8):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(2000)

async def pegar_links_fornecedores(page, limite):
    links = await page.locator("a").evaluate_all("""
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim(),
            cls: a.className || ""
        }))
    """)

    bloqueios = [
        "minha-conta", "contato", "produto", "category=", "region=",
        "sort=", "tab=categories", "login", "register", "lost-password",
        "#", "mailto:", "whatsapp", "instagram", "cliks.com.br"
    ]

    fornecedores = []
    vistos = set()

    for item in links:
        href = item.get("href", "")
        nome = limpar(item.get("text", ""))

        if not href.startswith("https://bras.app/"):
            continue

        if any(b in href for b in bloqueios):
            continue

        if href.rstrip("/") in ["https://bras.app", "https://bras.app/"]:
            continue

        if href in vistos:
            continue

        # aceita link interno com cara de perfil
        if nome or "listing" in item.get("cls", "").lower() or "/fornecedor" in href:
            vistos.add(href)
            fornecedores.append({"nome": nome, "link": href})

    return fornecedores[:limite], links[:80]

async def extrair_fornecedor(page, f):
    await page.goto(f["link"], wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(6000)

    nome = f.get("nome") or ""

    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            nome = await h1.inner_text()
    except:
        pass

    instagram = ""
    whatsapp = ""

    links = await page.locator("a").evaluate_all("""
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
    """)

    for a in links:
        href = a.get("href", "")
        if not instagram and "instagram.com" in href:
            instagram = href
        if not whatsapp and ("wa.me" in href or "api.whatsapp.com" in href or "whatsapp" in href.lower()):
            whatsapp = href

    return {
        "nome": limpar(nome),
        "instagram": instagram,
        "whatsapp": whatsapp,
        "categoria": "",
        "regiao": "",
        "link_perfil": f["link"],
        "status": "coletado"
    }

@app.get("/coletar")
async def coletar(limite: int = 3):
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1366, "height": 900})
            page = await context.new_page()

            login_ok = await fazer_login(page)
            if not login_ok:
                await browser.close()
                return {"status": "erro_login", "mensagem": "Login não confirmado"}

            await carregar_lista(page)

            fornecedores, amostra_links = await pegar_links_fornecedores(page, limite)

            if not fornecedores:
                html = (await page.content())[:3000]
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "mensagem": "Não achei links de perfil. Veja amostra_links para ajustar seletor.",
                    "url_atual": page.url,
                    "amostra_links": amostra_links,
                    "html_inicio": html
                }

            dados = []
            erros = []

            for f in fornecedores:
                try:
                    registro = await extrair_fornecedor(page, f)

                    supabase.table("fornecedores_brasapp").upsert(
                        registro,
                        on_conflict="link_perfil"
                    ).execute()

                    dados.append(registro)
                except Exception as e:
                    erros.append({"fornecedor": f, "erro": str(e)})

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
