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

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def limpar_texto(texto):
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


@app.get("/")
def home():
    return {"status": "online"}


@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
        "email_ok": bool(BRASAPP_EMAIL),
        "senha_ok": bool(BRASAPP_SENHA),
    }


async def fazer_login(page):
    await page.goto(URL_LOGIN)
    await page.wait_for_timeout(4000)

    await page.fill("#username", BRASAPP_EMAIL)
    await page.fill("#password", BRASAPP_SENHA)

    await page.click("button[type=submit]")
    await page.wait_for_timeout(8000)

    html = await page.content()
    return "Sair" in html


async def pegar_links(page):
    links = await page.locator("a").evaluate_all("""
        els => els.map(a => ({
            href: a.href || "",
            text: (a.innerText || "").trim()
        }))
    """)

    fornecedores = []
    vistos = set()

    for item in links:
        href = item["href"]

        if "resultado" not in href:
            continue

        if href in vistos:
            continue

        vistos.add(href)

        nome = item["text"]
        if len(nome) < 2:
            nome = href.split("/")[-2].replace("-", " ").title()

        fornecedores.append({
            "nome": nome,
            "link": href
        })

    return fornecedores


async def extrair(page, fornecedor):
    await page.goto(fornecedor["link"])
    await page.wait_for_timeout(5000)

    instagram = ""
    whatsapp = ""

    links = await page.locator("a").evaluate_all("""
        els => els.map(a => a.href)
    """)

    for l in links:
        if "instagram.com" in l:
            instagram = l
        if "wa.me" in l or "whatsapp" in l:
            whatsapp = l

    return {
        "nome": fornecedor["nome"],
        "instagram": instagram,
        "whatsapp": whatsapp,
        "link_perfil": fornecedor["link"]
    }


def ja_existe(link):
    r = supabase.table("fornecedores_brasapp").select("id").eq("link_perfil", link).execute()
    return len(r.data) > 0


# 🔥 PAGINAÇÃO REAL (CLIQUE)
async def navegar_paginas(page, max_paginas=10, limite=500):
    todos = []
    vistos = set()

    await page.goto(URL_LISTA)
    await page.wait_for_timeout(8000)

    for pagina in range(1, max_paginas + 1):
        print(f"📄 Página {pagina}")

        await page.wait_for_timeout(5000)

        fornecedores = await pegar_links(page)

        novos = 0

        for f in fornecedores:
            if f["link"] in vistos:
                continue

            vistos.add(f["link"])
            todos.append(f)
            novos += 1

            if len(todos) >= limite:
                return todos

        print(f"→ {novos} novos")

        # 👉 CLICA NA PRÓXIMA PÁGINA
        try:
            await page.click(f"text={pagina + 1}", timeout=5000)
            await page.wait_for_timeout(8000)
        except:
            print("Fim das páginas")
            break

    return todos


@app.get("/coletar")
async def coletar(limite: int = 200, paginas: int = 10):
    coletados = []
    pulados = []
    erros = []

    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            login_ok = await fazer_login(page)

            if not login_ok:
                return {"erro": "login falhou"}

            fornecedores = await navegar_paginas(page, paginas, limite)

            for f in fornecedores:
                try:
                    if ja_existe(f["link"]):
                        pulados.append(f)
                        continue

                    dados = await extrair(page, f)

                    supabase.table("fornecedores_brasapp").insert(dados).execute()

                    coletados.append(dados)

                except Exception as e:
                    erros.append(str(e))

            await browser.close()

            return {
                "status": "ok",
                "total_novos": len(coletados),
                "total_pulados": len(pulados),
                "total_erros": len(erros)
            }

    except Exception as e:
        return {
            "erro": str(e),
            "trace": traceback.format_exc()
        }
