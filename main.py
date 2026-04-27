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
URL_BASE = "https://bras.app/lista-de-fornecedores-de-roupas-no-atacado-brasapp-explorar/?type=roupas&sort=a-z"

supabase = None
if SUPABASE_URL and SUPABASE_KEY:
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

    botao = page.locator("button:has-text('Entrar')").first
    if await botao.count() > 0:
        await botao.click(timeout=15000)
    else:
        await page.click("button[type='submit']", timeout=15000)

    await page.wait_for_timeout(8000)

    html = await page.content()
    titulo = await page.title()

    return "Sair" in html or "logout" in html or "Minha conta" in titulo


def montar_url_pagina(pagina: int):
    if pagina <= 1:
        return URL_BASE
    return f"{URL_BASE}&page={pagina}"


async def abrir_pagina_lista(page, pagina: int):
    url = montar_url_pagina(pagina)
    print(f"📄 Abrindo página {pagina}: {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(10000)

    for _ in range(5):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(1200)


async def pegar_links_fornecedores(page):
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

        if len(nome) < 2:
            slug = href.rstrip("/").split("/")[-1]
            nome = slug.replace("-", " ").title()

        if href in vistos:
            continue

        vistos.add(href)

        fornecedores.append({
            "nome": nome,
            "link": href
        })

    return fornecedores


async def coletar_links_com_paginacao(page, limite: int, paginas: int):
    todos = []
    vistos = set()

    for pagina in range(1, paginas + 1):
        if len(todos) >= limite:
            break

        await abrir_pagina_lista(page, pagina)
        encontrados = await pegar_links_fornecedores(page)

        print(f"✅ Página {pagina}: {len(encontrados)} fornecedores encontrados")

        novos_da_pagina = 0

        for f in encontrados:
            if f["link"] in vistos:
                continue

            vistos.add(f["link"])
            todos.append(f)
            novos_da_pagina += 1

            if len(todos) >= limite:
                break

        if novos_da_pagina == 0:
            print("⚠️ Página sem novos fornecedores. Parando.")
            break

    return todos[:limite]


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
async def coletar(limite: int = 100, paginas: int = 10):
    if not supabase:
        return {"status": "erro", "erro": "Supabase não configurado"}

    if not BRASAPP_EMAIL or not BRASAPP_SENHA:
        return {"status": "erro", "erro": "BRASAPP_EMAIL ou BRASAPP_SENHA não configurados"}

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

            fornecedores = await coletar_links_com_paginacao(page, limite, paginas)

            if not fornecedores:
                html = (await page.content())[:3000]
                await browser.close()
                return {
                    "status": "sem_fornecedores",
                    "mensagem": "Não encontrei links reais de fornecedores.",
                    "url_atual": page.url,
                    "html_inicio": html
                }

            for fornecedor in fornecedores:
                try:
                    link_perfil = fornecedor["link"]

                    if fornecedor_ja_existe(link_perfil):
                        pulados.append({
                            "nome": fornecedor["nome"],
                            "link_perfil": link_perfil,
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
