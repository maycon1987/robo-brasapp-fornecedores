import os
import re
import traceback
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
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


# ============================================================
# FUNÇÕES GERAIS
# ============================================================

def limpar_texto(texto):
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def limpar_whatsapp(link):
    """
    Extrai apenas o telefone do link do WhatsApp.
    Ex:
    https://wa.me/5511963050794/?text=...
    vira:
    5511963050794
    """
    if not link:
        return ""

    match = re.search(r"(?:wa\.me/|phone=)(\d{10,15})", link)
    if match:
        return match.group(1)

    numeros = re.findall(r"\d{10,15}", link)
    return numeros[0] if numeros else ""


def detectar_plataforma(url: str):
    url_lower = (url or "").lower()

    if "tiktok.com" in url_lower:
        return "tiktok"

    if "instagram.com" in url_lower:
        if "/reel/" in url_lower or "/reels/" in url_lower:
            return "instagram_reels"
        return "instagram"

    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"

    return "outro"


def gerar_embed_html(url: str, plataforma: str):
    """
    Embed simples para exibir na home.
    Depois dá para evoluir para oEmbed oficial.
    """
    if not url:
        return ""

    if plataforma == "tiktok":
        return f'<blockquote class="tiktok-embed" cite="{url}" data-video-id=""><a href="{url}">Ver vídeo no TikTok</a></blockquote>'

    if plataforma in ["instagram", "instagram_reels"]:
        return f'<blockquote class="instagram-media" data-instgrm-permalink="{url}"><a href="{url}">Ver no Instagram</a></blockquote>'

    if plataforma == "youtube":
        return f'<a href="{url}" target="_blank">Ver vídeo no YouTube</a>'

    return f'<a href="{url}" target="_blank">Ver vídeo</a>'


# ============================================================
# ROTAS BÁSICAS
# ============================================================

@app.get("/")
def home():
    return {
        "status": "online",
        "app": "robo-brasapp-fornecedores",
        "modulos": [
            "brasapp",
            "videos_fornecedores"
        ]
    }


@app.get("/debug")
def debug():
    return {
        "supabase_url_ok": bool(SUPABASE_URL),
        "supabase_key_ok": bool(SUPABASE_KEY),
        "brasapp_email_ok": bool(BRASAPP_EMAIL),
        "brasapp_senha_ok": bool(BRASAPP_SENHA),
    }


# ============================================================
# MÓDULO VIDEOS DE FORNECEDORES
# ============================================================

class VideoFornecedorInput(BaseModel):
    url_video: str
    titulo: Optional[str] = None
    observacao: Optional[str] = None
    fornecedor_id: Optional[int] = None
    plataforma: Optional[str] = None


@app.post("/postar-video")
def postar_video(video: VideoFornecedorInput):
    """
    Salva um link de vídeo na tabela videos_fornecedores.
    Use para TikTok, Instagram Reels, YouTube Shorts etc.
    """
    if not supabase:
        return {
            "status": "erro",
            "erro": "Supabase não configurado"
        }

    url_video = limpar_texto(video.url_video)

    if not url_video:
        return {
            "status": "erro",
            "erro": "url_video é obrigatório"
        }

    plataforma = video.plataforma or detectar_plataforma(url_video)
    embed_html = gerar_embed_html(url_video, plataforma)

    registro = {
        "fornecedor_id": video.fornecedor_id,
        "plataforma": plataforma,
        "url_video": url_video,
        "embed_html": embed_html,
        "titulo": limpar_texto(video.titulo),
        "observacao": limpar_texto(video.observacao),
        "status": "pendente",
    }

    try:
        resultado = (
            supabase
            .table("videos_fornecedores")
            .insert(registro)
            .execute()
        )

        return {
            "status": "ok",
            "mensagem": "Vídeo salvo com sucesso",
            "video": resultado.data[0] if resultado.data else registro
        }

    except Exception as e:
        return {
            "status": "erro",
            "erro": str(e),
            "trace": traceback.format_exc()
        }


@app.get("/listar-videos")
def listar_videos(limite: int = 20, status: Optional[str] = None):
    """
    Lista vídeos salvos para aparecerem na home.
    Ex:
    /listar-videos?limite=20
    /listar-videos?status=pendente
    """
    if not supabase:
        return {
            "status": "erro",
            "erro": "Supabase não configurado"
        }

    try:
        query = (
            supabase
            .table("videos_fornecedores")
            .select("*")
            .order("criado_em", desc=True)
            .limit(limite)
        )

        if status:
            query = query.eq("status", status)

        resultado = query.execute()

        return {
            "status": "ok",
            "total": len(resultado.data or []),
            "videos": resultado.data or []
        }

    except Exception as e:
        return {
            "status": "erro",
            "erro": str(e),
            "trace": traceback.format_exc()
        }


# ============================================================
# MÓDULO BRASAPP
# ============================================================

async def fazer_login(page):
    await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    await page.fill("#username", BRASAPP_EMAIL, timeout=15000)
    await page.fill("#password", BRASAPP_SENHA, timeout=15000)

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
        print(f"📄 Página {pagina}")

        await page.wait_for_timeout(4000)

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
    site = ""

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

        if (
            not site
            and href.startswith("http")
            and "bras.app" not in href
            and "instagram.com" not in href
            and "wa.me" not in href
            and "whatsapp" not in href.lower()
            and "maps.google.com" not in href
            and "google.com/maps" not in href
            and "cliks.com.br" not in href
        ):
            site = href

    texto_pagina = ""
    try:
        texto_pagina = await page.locator("body").inner_text()
        texto_pagina = limpar_texto(texto_pagina)
    except Exception:
        pass

    endereco = ""
    produtos = ""

    padroes_endereco = [
        r"((?:R\.|Rua)\s+[^|]{5,140}?\d+[^|]{0,80}?(?:SP|RJ|PR|MG|SC|RS|BA|GO|PE|CE|ES|DF|MT|MS|PA|AM|PB|RN|AL|SE|MA|PI|TO|RO|AC|RR|AP))",
        r"((?:Av\.|Avenida)\s+[^|]{5,140}?\d+[^|]{0,80}?(?:SP|RJ|PR|MG|SC|RS|BA|GO|PE|CE|ES|DF|MT|MS|PA|AM|PB|RN|AL|SE|MA|PI|TO|RO|AC|RR|AP))",
        r"(Shopping\s+[^|]{5,140})",
    ]

    for padrao in padroes_endereco:
        achou = re.search(padrao, texto_pagina, re.IGNORECASE)
        if achou:
            endereco = limpar_texto(achou.group(1))
            endereco = endereco.replace("Obter instruções", "").strip()
            break

    produtos = texto_pagina[:1200]
    telefone_limpo = limpar_whatsapp(whatsapp)

    return {
        "nome": limpar_texto(nome),
        "instagram": instagram,
        "whatsapp": whatsapp,
        "telefone": telefone_limpo,
        "site": site,
        "endereco": endereco,
        "produtos": produtos,
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
async def coletar(limite: int = 300, paginas: int = 10, atualizar: bool = False):
    coletados = []
    atualizados = []
    pulados = []
    erros = []

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
                    existe = fornecedor_ja_existe(fornecedor["link"])

                    if existe and not atualizar:
                        pulados.append({
                            "nome": fornecedor["nome"],
                            "link_perfil": fornecedor["link"],
                            "motivo": "já existia no Supabase"
                        })
                        continue

                    registro = await extrair_fornecedor(page, fornecedor)

                    if existe and atualizar:
                        supabase.table("fornecedores_brasapp").update(registro).eq(
                            "link_perfil",
                            fornecedor["link"]
                        ).execute()
                        atualizados.append(registro)
                    else:
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
                "atualizar": atualizar,
                "total_encontrado": len(fornecedores),
                "total_coletado_novo": len(coletados),
                "total_atualizado": len(atualizados),
                "total_pulado_repetido": len(pulados),
                "total_erros": len(erros),
                "dados": coletados,
                "atualizados": atualizados,
                "pulados": pulados,
                "erros": erros
            }

    except Exception as e:
        return {
            "status": "erro_geral",
            "erro": str(e),
            "trace": traceback.format_exc()
        }
