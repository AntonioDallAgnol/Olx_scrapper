import time
import re
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# ================= CONFIGURAÇÕES =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8659592937:AAEji1h1XuriKcyEWrVP10RlVyy0bLCcqVs")
CHAT_ID = os.getenv("CHAT_ID", "7186926895")

URL_BUSCA = "https://www.olx.com.br/games/consoles-de-video-game/sony/playstation-5?ps=2000&pe=3000&opst=2"
PRECO_LIMITE = 3001.00
CHECK_INTERVAL_SECONDS = 60
DB_FILE = "anuncios_vistos.json"
# =================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self.send_response(204)
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        self.send_response(204)
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, format, *args):
        pass

def start_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

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

def buscar_anuncios_html(soup):
    anuncios = []
    links = soup.find_all("a", href=re.compile(r"olx\.com\.br/.*-\d+"))

    for link_tag in links:
        href = link_tag.get("href")
        match_id = re.search(r"-(\d+)(?:\?|$)", href)
        if not match_id:
            continue
        ad_id = match_id.group(1)

        card = link_tag.find_parent("section") or link_tag.find_parent("li") or link_tag

        titulo_tag = card.find(["h2", "h3"]) or link_tag.find(["h2", "h3"])
        titulo = titulo_tag.get_text(strip=True) if titulo_tag else None

        if not titulo:
            titulo = link_tag.get("title") or link_tag.get("aria-label") or "Anúncio OLX"

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

def checar_anuncios(historico):
    try:
        scraper_key = os.getenv("SCRAPERAPI_KEY")
        
        # Se houver chave, usa o proxy anti-bloqueio; caso contrário, faz request direta
        if scraper_key:
            url_alvo = f"http://api.scraperapi.com?api_key={scraper_key}&url={requests.utils.quote(URL_BUSCA)}&country_code=br"
            resposta = requests.get(url_alvo, timeout=60)
        else:
            session = cffi_requests.Session(impersonate="chrome124")
            resposta = session.get(URL_BUSCA, timeout=25)

        if resposta.status_code != 200:
            print(f"[Aviso] Status {resposta.status_code} ao acessar OLX.")
            return

        soup = BeautifulSoup(resposta.text, "html.parser")
        anuncios = buscar_anuncios_html(soup)

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
