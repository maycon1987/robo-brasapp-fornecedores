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

URL_LOGIN = "https://bras.app/minha-conta/"
URL_LISTA = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def limpar_texto(texto):
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


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


async def fazer_login(page):
    print("🔐 Abrindo página de login correta...")

    await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(5000)

    try:
        await page.fill("#username", BRASAPP_EMAIL, timeout=15000)
        await page.fill("#password", BRASAPP_SENHA, timeout=15000)

        botao = page.locator("button:has-text('Entrar')").first

        if await botao.count() > 0:
            await botao.click(timeout=15000)
        else:
            await page.click("button[type='submit']", timeout=15000)

        await page.wait_for_timeout(8000)

        url_atual = page.url
        html = await page.content()

        if "Sair" in html or "logout" in html or "Minha conta" in await page.title():
            print("✅ Login realizado")
            return {
                "ok": True,
                "url_atual": url_atual
            }

        return {
            "ok": False,
            "url_atual": url_atual,
            "mensagem": "Login enviado, mas não consegui confirmar se entrou."
        }

    except Exception as e:
        return {
            "ok": False,
            "erro": str(e),
            "url_atual": page.url,
            "html_inicio": (await page.content())[:2500]
        }


async def carregar_lista(page):
    print("🌐 Abrindo lista de fornecedores...")

    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(10000)

    for i in range(6):
        print(f"📜 Scroll {i + 1}/6")
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2000)


async def pegar_fornecedores(page, limite):
    print("🔎 Procurando fornecedores...")

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )

    fornecedores = []
    vistos = set()

    for item in links:
        href = item.get("href", "")
        nome = limpar_texto(item.get("text", ""))

        if not href:
            continue

        if "/resultado/" not in href:
            continue

        if href in vistos:
            continue

        vistos.add(href)

        fornecedores.append({
            "nome": nome,
            "link": href
        })

    print(f"✅ Fornecedores encontrados: {len(fornecedores)}")

    return fornecedores[:limite]


async def extrair_fornecedor(page, fornecedor):
    print(f"➡️ Abrindo fornecedor: {fornecedor['link']}")

    await page.goto(fornecedor["link"], wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(6000)

    nome = fornecedor.get("nome") or ""

    try:
        h1 = page.locator("h1").first
        if await h1.count() > 0:
            nome = await h1.inner_text()
    except Exception:
        pass

    instagram = ""
    whatsapp = ""

    links = await page.locator("a").evaluate_all(
        """
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )

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

    registro = {
        "nome": limpar_texto(nome),
        "instagram": instagram,
        "whatsapp": whatsapp,
        "categoria": "",
        "regiao": "",
        "link_perfil": fornecedor["link"],
        "status": "coletado"
    }

    print("✅ Registro:", registro)

    return registro


@app.get("/coletar")
async def coletar(limite: int = 3):
    if not supabase:
        return {
            "status": "erro",
            "erro": "Supabase não configurado"
        }

    if not BRASAPP_EMAIL or not BRASAPP_SENHA:
        return {
            "status": "erro",
            "erro": "BRASAPP_EMAIL ou BRASAPP_SENHA não configurados"
        }

    coletados = []
    erros = []

    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)

            context = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )

            page = await context.new_page()

            login = await fazer_login(page)

            if not login.get("ok"):
                await browser.close()
                return {
                    "status": "erro_login",
                    "login": login
                }

            await carregar_lista(page)

            fornecedores = await pegar_fornecedores(page, limite)

            if not fornecedores:
                html = (await page.content())[:3000]
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "mensagem": "Não encontrei links /resultado/. Pode ter bloqueio, login não aplicado ou seletor diferente.",
                    "url_atual": page.url,
                    "html_inicio": html
                }

            for fornecedor in fornecedores:
                try:
                    registro = await extrair_fornecedor(page, fornecedor)

                    supabase.table("fornecedores_brasapp").upsert(
                        registro,
                        on_conflict="link_perfil"
                    ).execute()

                    coletados.append(registro)

                except Exception as e:
                    erros.append({
                        "fornecedor": fornecedor,
                        "erro": str(e)
                    })

            await browser.close()

            return {
                "status": "finalizado",
                "total_coletado": len(coletados),
                "total_erros": len(erros),
                "dados": coletados,
                "erros": erros
            }

    except Exception as e:
        return {
            "status": "erro_geral",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
