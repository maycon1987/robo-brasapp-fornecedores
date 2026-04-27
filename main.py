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

    # Botão correto do formulário de login
    botao = page.locator("form.login button[type='submit']").first

    if await botao.count() > 0:
        await botao.click(timeout=15000)
    else:
        await page.keyboard.press("Enter")

    await page.wait_for_timeout(8000)

    html = await page.content()
    titulo = await page.title()

    return "Sair" in html or "logout" in html or "Minha conta" in titulo


async def pegar_links(page):
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

        if not href:
            continue

        if not href.startswith("https://bras.app/"):
            continue

        if "lista-de-fornecedores-de-roupas-no-atacado-bras-resultado/" not in href:
            continue

        bloqueados = [
            "member-logout",
            "logout",
            "minha-conta",
            "lost-password",
            "register",
            "produto",
            "contato",
            "category=",
            "region=",
            "sort=",
            "tab=",
            "#",
        ]

        if any(b in href.lower() for b in bloqueados):
            continue

        if href in vistos:
            continue

        vistos.add(href)

        if len(nome) < 2:
            slug = href.rstrip("/").split("/")[-1]
            nome = slug.replace("-", " ").title()

        fornecedores.append({
            "nome": nome,
            "link": href
        })

    return fornecedores


async def navegar_paginas(page, limite=300, paginas=10):
    todos = []
    vistos = set()

    await page.goto(URL_LISTA, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(10000)

    for pagina in range(1, paginas + 1):
        print(f"Página {pagina}")

        await page.wait_for_timeout(5000)

        fornecedores = await pegar_links(page)

        for fornecedor in fornecedores:
            if fornecedor["link"] in vistos:
                continue

            vistos.add(fornecedor["link"])
            todos.append(fornecedor)

            if len(todos) >= limite:
                return todos

        proxima = pagina + 1

        try:
            botao_pagina = page.locator(f"a:has-text('{proxima}')").first

            if await botao_pagina.count() > 0:
                await botao_pagina.click(timeout=10000)
                await page.wait_for_timeout(8000)
            else:
                print("Fim das páginas")
                break

        except Exception as e:
            print("Erro ao clicar na próxima página:", e)
            break

    return todos


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


def fornecedor_ja_existe(link_perfil):
    consulta = (
        supabase
        .table("fornecedores_brasapp")
        .select("id, link_perfil")
        .eq("link_perfil", link_perfil)
        .limit(1)
        .execute()
    )

    return bool(consulta.data)


@app.get("/coletar")
async def coletar(limite: int = 300, paginas: int = 10):
    coletados = []
    pulados = []
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

            login_ok = await fazer_login(page)

            if not login_ok:
                await browser.close()
                return {
                    "status": "erro_login",
                    "mensagem": "Login não confirmado"
                }

            fornecedores = await navegar_paginas(page, limite=limite, paginas=paginas)

            for fornecedor in fornecedores:
                try:
                    if fornecedor_ja_existe(fornecedor["link"]):
                        pulados.append({
                            "nome": fornecedor["nome"],
                            "link_perfil": fornecedor["link"],
                            "motivo": "já existia no Supabase"
                        })
                        continue

                    registro = await extrair_fornecedor(page, fornecedor)

                    supabase.table("fornecedores_brasapp").insert(registro).execute()

                    coletados.append(registro)

                except Exception as e:
                    erros.append({
                        "fornecedor": fornecedor,
                        "erro": str(e)
                    })

            await browser.close()

            return {
                "status": "finalizado",
                "limite": limite,
                "paginas": paginas,
                "total_encontrado": len(fornecedores),
                "total_coletado_novo": len(coletados),
                "total_pulado_repetido": len(pulados),
                "total_erros": len(erros),
                "dados": coletados,
                "pulados": pulados,
                "erros": erros
            }

    except Exception as e:
        return {
            "status": "erro_geral",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
