from fastapi import FastAPI
from supabase import create_client
from playwright.async_api import async_playwright
import os
import re
import traceback

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
    return {
        "status": "online",
        "app": "robo-brasapp-fornecedores"
    }


@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
        "brasapp_email_ok": bool(BRASAPP_EMAIL),
        "brasapp_senha_ok": bool(BRASAPP_SENHA),
    }


def limpar_texto(txt):
    if not txt:
        return ""
    return re.sub(r"\s+", " ", txt).strip()


async def tentar_login(page):
    print("🔐 Verificando se precisa login...")

    await page.goto("https://bras.app/login", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    email_selectors = [
        "input[type='email']",
        "input[name='email']",
        "input[placeholder*='email' i]",
        "input[placeholder*='e-mail' i]",
    ]

    senha_selectors = [
        "input[type='password']",
        "input[name='password']",
        "input[placeholder*='senha' i]",
    ]

    email_input = None
    senha_input = None

    for selector in email_selectors:
        loc = page.locator(selector).first
        if await loc.count() > 0:
            email_input = loc
            break

    for selector in senha_selectors:
        loc = page.locator(selector).first
        if await loc.count() > 0:
            senha_input = loc
            break

    if not email_input or not senha_input:
        print("ℹ️ Campos de login não encontrados. Talvez já esteja logado ou rota diferente.")
        return False

    print("✅ Campos de login encontrados. Fazendo login...")

    await email_input.fill(BRASAPP_EMAIL)
    await senha_input.fill(BRASAPP_SENHA)

    botoes = [
        "button:has-text('Entrar')",
        "button:has-text('Login')",
        "button:has-text('Acessar')",
        "button[type='submit']",
    ]

    clicou = False

    for selector in botoes:
        botao = page.locator(selector).first
        if await botao.count() > 0:
            await botao.click()
            clicou = True
            break

    if not clicou:
        print("⚠️ Botão de login não encontrado. Tentando apertar Enter.")
        await senha_input.press("Enter")

    await page.wait_for_timeout(8000)
    print("✅ Login tentado.")
    return True


async def carregar_lista(page):
    print("🌐 Abrindo lista de fornecedores...")

    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(8000)

    # tenta aceitar/fechar coisas que atrapalham
    for texto in ["Aceitar", "Entendi", "Fechar", "Agora não", "Não agora"]:
        try:
            botao = page.locator(f"button:has-text('{texto}')").first
            if await botao.count() > 0:
                await botao.click(timeout=3000)
                await page.wait_for_timeout(1000)
        except Exception:
            pass

    # scroll para carregar mais fornecedores
    for i in range(5):
        print(f"📜 Scroll carregando lista {i+1}/5...")
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2000)

    print("✅ Lista carregada.")


async def pegar_links_fornecedores(page, limite):
    print("🔎 Procurando links de fornecedores...")

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            href: a.href || '',
            text: (a.innerText || a.textContent || '').trim()
        }))
        """
    )

    fornecedores = []
    vistos = set()

    for item in links:
        href = item.get("href", "")
        text = limpar_texto(item.get("text", ""))

        if not href:
            continue

        # perfis do BrasApp geralmente têm /resultado/
        if "/resultado/" not in href:
            continue

        if href in vistos:
            continue

        vistos.add(href)

        fornecedores.append({
            "nome": text,
            "link": href
        })

    print(f"✅ Links encontrados: {len(fornecedores)}")

    return fornecedores[:limite]


async def extrair_dados_fornecedor(page, fornecedor):
    link = fornecedor["link"]

    print(f"➡️ Abrindo fornecedor: {link}")

    await page.goto(link, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(6000)

    titulo = fornecedor.get("nome") or ""

    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            titulo = await h1.inner_text()
    except Exception:
        pass

    if not titulo:
        try:
            h2 = page.locator("h2").first
            if await h2.count() > 0:
                titulo = await h2.inner_text()
        except Exception:
            pass

    instagram = ""
    whatsapp = ""

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            href: a.href || '',
            text: (a.innerText || a.textContent || '').trim()
        }))
        """
    )

    for a in links:
        href = a.get("href", "")

        if not instagram and "instagram.com" in href:
            instagram = href

        if not whatsapp and (
            "wa.me" in href
            or "api.whatsapp.com" in href
            or "web.whatsapp.com" in href
            or "whatsapp" in href.lower()
        ):
            whatsapp = href

    # tenta pegar categorias/região por texto visível
    texto_pagina = ""
    try:
        texto_pagina = await page.locator("body").inner_text()
    except Exception:
        pass

    registro = {
        "nome": limpar_texto(titulo),
        "instagram": instagram,
        "whatsapp": whatsapp,
        "categoria": "",
        "regiao": "",
        "link_perfil": link,
        "status": "coletado"
    }

    print("✅ Coletado:", registro)

    return registro


@app.get("/coletar")
async def coletar(limite: int = 5):
    if not supabase:
        return {"erro": "Supabase não configurado"}

    if not BRASAPP_EMAIL or not BRASAPP_SENHA:
        return {"erro": "BRASAPP_EMAIL ou BRASAPP_SENHA não configurados"}

    coletados = []
    erros = []

    try:
        async with async_playwright() as p:
            print("🚀 Iniciando navegador...")

            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                    "--disable-extensions",
                ]
            )

            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )

            page = await context.new_page()

            await tentar_login(page)
            await carregar_lista(page)

            fornecedores = await pegar_links_fornecedores(page, limite)

            if not fornecedores:
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "mensagem": "Não encontrei links de fornecedores. Pode ser login não concluído ou seletor diferente.",
                    "total_coletado": 0,
                    "dados": []
                }

            for fornecedor in fornecedores:
                try:
                    registro = await extrair_dados_fornecedor(page, fornecedor)

                    supabase.table("fornecedores_brasapp").upsert(
                        registro,
                        on_conflict="link_perfil"
                    ).execute()

                    coletados.append(registro)

                except Exception as e:
                    erro = {
                        "fornecedor": fornecedor,
                        "erro": str(e)
                    }
                    print("❌ Erro fornecedor:", erro)
                    erros.append(erro)

            await browser.close()

    except Exception as e:
        print("💥 ERRO GERAL:")
        print(traceback.format_exc())

        return {
            "status": "erro",
            "erro": str(e),
            "trace": traceback.format_exc()
        }

    return {
        "status": "finalizado",
        "total_coletado": len(coletados),
        "total_erros": len(erros),
        "dados": coletados,
        "erros": erros
    }
