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


async def preencher_campo(page, seletores, valor, nome_campo):
    for seletor in seletores:
        try:
            campo = page.locator(seletor).first
            if await campo.count() > 0:
                await campo.fill(valor, timeout=8000)
                print(f"✅ Campo preenchido: {nome_campo} usando {seletor}")
                return True
        except Exception as e:
            print(f"⚠️ Falhou seletor {seletor}: {e}")

    print(f"❌ Não achei campo: {nome_campo}")
    return False


async def clicar_botao_login(page):
    seletores = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Entrar")',
        'button:has-text("Login")',
        'button:has-text("Acessar")',
        'a:has-text("Entrar")',
        'a:has-text("Login")',
    ]

    for seletor in seletores:
        try:
            botao = page.locator(seletor).first
            if await botao.count() > 0:
                await botao.click(timeout=8000)
                print(f"✅ Cliquei no botão login: {seletor}")
                return True
        except Exception as e:
            print(f"⚠️ Falhou botão {seletor}: {e}")

    try:
        await page.keyboard.press("Enter")
        print("✅ Apertei Enter para tentar login")
        return True
    except Exception:
        return False


async def fazer_login(page):
    print("🔐 Abrindo tela de login...")
    await page.goto("https://bras.app/login", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(7000)

    email_ok = await preencher_campo(
        page,
        [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[name="user_login"]',
            'input[id*="email"]',
            'input[id*="user"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="e-mail" i]',
            'input[placeholder*="usuário" i]',
            'input[placeholder*="usuario" i]',
            'input[type="text"]',
            'input'
        ],
        BRASAPP_EMAIL,
        "email"
    )

    senha_ok = await preencher_campo(
        page,
        [
            'input[type="password"]',
            'input[name="password"]',
            'input[name="senha"]',
            'input[name="user_pass"]',
            'input[id*="password"]',
            'input[id*="senha"]',
            'input[id*="pass"]',
            'input[placeholder*="senha" i]',
            'input[placeholder*="password" i]'
        ],
        BRASAPP_SENHA,
        "senha"
    )

    if not email_ok or not senha_ok:
        html = (await page.content())[:2500]
        return {
            "ok": False,
            "email_ok": email_ok,
            "senha_ok": senha_ok,
            "url_atual": page.url,
            "html_inicio": html
        }

    await clicar_botao_login(page)
    await page.wait_for_timeout(10000)

    return {
        "ok": True,
        "url_atual": page.url
    }


async def carregar_lista(page):
    print("🌐 Abrindo lista...")
    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(10000)

    for i in range(6):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2000)

    print("✅ Lista carregada")


async def pegar_fornecedores(page, limite):
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

    return fornecedores[:limite]


async def extrair_fornecedor(page, fornecedor):
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
    if not supabase:
        return {"status": "erro", "erro": "Supabase não configurado"}

    if not BRASAPP_EMAIL or not BRASAPP_SENHA:
        return {"status": "erro", "erro": "BRASAPP_EMAIL ou BRASAPP_SENHA não configurados"}

    coletados = []
    erros = []

    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)

            context = await browser.new_context(
                viewport={"width": 1366, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
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
                html = (await page.content())[:2500]
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "mensagem": "Login pode ter falhado ou os links mudaram.",
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
