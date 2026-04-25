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

URL_LISTA = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&tab=categories"


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


async def preencher_primeiro(page, seletores, valor):
    for seletor in seletores:
        try:
            campo = page.locator(seletor).first
            if await campo.count() > 0:
                await campo.fill(valor, timeout=8000)
                return True
        except Exception:
            pass
    return False


@app.get("/coletar")
async def coletar(limite: int = 5):
    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            await page.goto("https://bras.app/login", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            email_ok = await preencher_primeiro(page, [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="username"]',
                'input[id*="email"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="e-mail" i]',
                'input[placeholder*="usuário" i]',
                'input'
            ], BRASAPP_EMAIL)

           senha_ok = await preencher_primeiro(page, [
    'input[type="password"]',
    'input[name="password"]',
    'input[name="senha"]',
    'input[id*="password"]',
    'input[id*="senha"]',
    'input[placeholder*="senha" i]',
    'input[placeholder*="password" i]',
    'input[type="text"]',
    'input'
], BRASAPP_SENHA)

            if not email_ok or not senha_ok:
                html_inicio = (await page.content())[:1000]
                await browser.close()
                return {
                    "status": "erro_login",
                    "email_ok": email_ok,
                    "senha_ok": senha_ok,
                    "url_atual": page.url,
                    "html_inicio": html_inicio
                }

            botoes = [
                'button[type="submit"]',
                'button:has-text("Entrar")',
                'button:has-text("Login")',
                'button:has-text("Acessar")',
                'input[type="submit"]'
            ]

            clicou = False
            for seletor in botoes:
                try:
                    botao = page.locator(seletor).first
                    if await botao.count() > 0:
                        await botao.click(timeout=8000)
                        clicou = True
                        break
                except Exception:
                    pass

            if not clicou:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(8000)

            await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(8000)

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
                nome = item.get("text", "").strip()

                if "/resultado/" in href and href not in vistos:
                    vistos.add(href)
                    fornecedores.append({"nome": nome, "link": href})

            fornecedores = fornecedores[:limite]
            dados = []

            for f in fornecedores:
                await page.goto(f["link"], wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(4000)

                nome = f["nome"]
                try:
                    h1 = page.locator("h1").first
                    if await h1.count() > 0:
                        nome = await h1.inner_text()
                except Exception:
                    pass

                instagram = ""
                whatsapp = ""

                all_links = await page.locator("a").evaluate_all("""
                    els => els.map(a => ({
                        href: a.href || "",
                        text: (a.innerText || a.textContent || "").trim()
                    }))
                """)

                for a in all_links:
                    href = a.get("href", "")
                    if not instagram and "instagram.com" in href:
                        instagram = href
                    if not whatsapp and ("wa.me" in href or "whatsapp" in href.lower()):
                        whatsapp = href

                registro = {
                    "nome": nome,
                    "instagram": instagram,
                    "whatsapp": whatsapp,
                    "link_perfil": f["link"],
                    "status": "coletado"
                }

                supabase.table("fornecedores_brasapp").upsert(
                    registro,
                    on_conflict="link_perfil"
                ).execute()

                dados.append(registro)

            await browser.close()

            return {
                "status": "finalizado",
                "total_fornecedores_encontrados": len(fornecedores),
                "total_coletado": len(dados),
                "dados": dados
            }

    except Exception as e:
        return {
            "status": "erro",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
