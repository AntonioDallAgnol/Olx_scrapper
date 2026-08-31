import os
import re
import json
import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ================= CONFIGURAÇÕES =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")

URL_BUSCA = "https://www.olx.com.br/games/consoles-de-video-game/sony/playstation-5?ps=2000&pe=3000&opst=2"
PRECO_LIMITE = 3001.00
DB_FILE = "anuncios_vistos.json"

# Termos que você NÃO quer que apareçam no título
PALAVRAS_BLOQUEADAS = ["vr", "portal", "psvr", "playstation portal", "vr2", "psvr2"]
# =================================================

def carregar_historico():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def salvar_historico(historico):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(historico), f, indent=2)

def enviar_telegram(titulo, preco, link):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"[Telegram Mock] Alerta: {titulo} - R$ {preco:.2f}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    preco_formatado = f"R$ {preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    mensagem_html = (
        f"🚨 <b>Oportunidade Encontrada!</b>\n\n"
        f"📌 <b>Produto:</b> {titulo}\n"
        f"💰 <b>Preço:</b> {preco_formatado}\n\n"
        f"🔗 <a href='{link}'>Acessar Anúncio na OLX</a>"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": mensagem_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        res = r.json()
        if not res.get("ok"):
            print(f"[Erro Telegram] {res}")
        else:
            print(f" -> Alerta enviado no Telegram: {titulo[:35]}")
    except Exception as e:
        print(f"[Erro Telegram Conexão] {e}")

def extrair_preco(texto):
    if not texto:
        return None
    apenas_numeros = re.sub(r"[^\d,]", "", str(texto)).replace(".", "").replace(",", ".")
    try:
        return float(apenas_numeros)
    except ValueError:
        return None

def contem_palavra_bloqueada(titulo):
    """Verifica se o título contém qualquer termo da lista de bloqueio."""
    titulo_lower = titulo.lower()
    for termo in PALAVRAS_BLOQUEADAS:
        # Usa \b para casar palavras exatas
        padrao = rf"\b{re.escape(termo.lower())}\b"
        if re.search(padrao, titulo_lower):
            return True
    return False

def extrair_anuncios(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    anuncios = []

    # Abordagem 1: Next.js JSON (__NEXT_DATA__)
    script_next = soup.find("script", id="__NEXT_DATA__")
    if script_next and script_next.string:
        try:
            dados = json.loads(script_next.string)
            props = dados.get("props", {}).get("pageProps", {})
            ad_list = props.get("ads", []) or props.get("listingProps", {}).get("ads", [])
            for ad in ad_list:
                preco_raw = ad.get("price") or ad.get("rawPrice")
                preco_num = float(preco_raw) if preco_raw is not None else None
                anuncios.append({
                    "id": str(ad.get("listId") or ad.get("id")),
                    "titulo": ad.get("subject") or ad.get("title") or "Anúncio OLX",
                    "preco": preco_num,
                    "link": ad.get("url") or ad.get("friendlyUrl")
                })
            if anuncios:
                return anuncios
        except Exception:
            pass

    # Abordagem 2: Fallback por elementos do DOM
    links = soup.find_all("a", href=re.compile(r"olx\.com\.br/.*-\d+"))
    for link_tag in links:
        href = link_tag.get("href")
        match_id = re.search(r"-(\d+)(?:\?|$)", href)
        if not match_id:
            continue
        ad_id = match_id.group(1)
        card = link_tag.find_parent("section") or link_tag.find_parent("li") or link_tag
        titulo_tag = card.find(["h2", "h3"]) or link_tag.find(["h2", "h3"])
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else link_tag.get("title", "Anúncio OLX")

        preco_tag = card.find(string=re.compile(r"R\$\s*[\d\.,]+"))
        preco_num = extrair_preco(preco_tag) if preco_tag else None

        anuncios.append({
            "id": ad_id,
            "titulo": titulo,
            "preco": preco_num,
            "link": href
        })

    vistos = set()
    unicos = []
    for item in anuncios:
        if item["id"] not in vistos:
            vistos.add(item["id"])
            unicos.append(item)

    return unicos

def obter_html_com_playwright(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pt-BR",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        content = page.content()
        browser.close()
        return content

def checar_anuncios(historico):
    try:
        html = obter_html_com_playwright(URL_BUSCA)
        anuncios = extrair_anuncios(html)

        if not anuncios:
            print("[Aviso] Nenhum anúncio identificado na página.")
            return

        novos_anuncios = 0
        for item in anuncios:
            anuncio_id = item["id"]
            if anuncio_id in historico:
                continue

            historico.add(anuncio_id)
            novos_anuncios += 1

            titulo = item["titulo"]
            preco = item["preco"]
            link = item["link"]

            # Filtro de palavras bloqueadas
            if contem_palavra_bloqueada(titulo):
                print(f" [Ignorado - Filtro de Palavra] {titulo[:40]}")
                continue

            print(f" -> Encontrado: {titulo[:35]} | Preço: {preco}")

            if preco is not None and preco <= PRECO_LIMITE:
                enviar_telegram(titulo, preco, link)

        if novos_anuncios > 0:
            salvar_historico(historico)
            print(f"[Sucesso] {novos_anuncios} novos anúncios processados.")
        else:
            print("[Info] Varredura concluída. Nenhum novo anúncio.")

    except Exception as e:
        print(f"[Erro Scraping] {e}")

def main():
    historico = carregar_historico()
    print("Iniciando varredura única OLX...")
    checar_anuncios(historico)

if __name__ == "__main__":
    main()
