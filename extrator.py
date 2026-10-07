import argparse
import logging
import random
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL_INICIAL = "http://quotes.toscrape.com/"
SELETOR_BLOCO = "div.quote"
SELETOR_TEXTO = "span.text"
SELETOR_AUTOR = "small.author"
SELETOR_TAGS = "div.tags a.tag"
SELETOR_PROXIMA = "li.next > a"

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

ASPAS = "\u201c\u201d\"'"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("citacoes")


def criar_sessao() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adaptador = HTTPAdapter(max_retries=retry)
    sessao = requests.Session()
    sessao.headers.update(CABECALHOS)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)
    return sessao


def texto_seguro(elemento) -> Optional[str]:
    if elemento is None:
        return None
    valor = elemento.get_text(strip=True)
    return valor or None


def extrair_citacao(bloco) -> Optional[dict]:
    texto = texto_seguro(bloco.select_one(SELETOR_TEXTO))
    if texto is None:
        return None

    tags = [t.get_text(strip=True) for t in bloco.select(SELETOR_TAGS)]

    return {
        "Citação": texto.strip(ASPAS),
        "Autor": texto_seguro(bloco.select_one(SELETOR_AUTOR)),
        "Tags": ", ".join(tags),
    }


def extrair_pagina(sessao: requests.Session, url: str) -> tuple[list[dict], Optional[str]]:
    resposta = sessao.get(url, timeout=(5, 20))
    resposta.raise_for_status()

    soup = BeautifulSoup(resposta.content, "html.parser")

    registros = [
        r for r in map(extrair_citacao, soup.select(SELETOR_BLOCO)) if r is not None
    ]

    link = soup.select_one(SELETOR_PROXIMA)
    proxima = urljoin(url, link["href"]) if link and link.get("href") else None

    return registros, proxima


def salvar(registros: list[dict], caminho: Path) -> None:
    if not registros:
        log.warning("Nenhum registro para salvar.")
        return

    tabela = pd.DataFrame(registros).drop_duplicates().reset_index(drop=True)

    if caminho.suffix.lower() == ".xlsx":
        tabela.to_excel(caminho, index=False)
    else:
        tabela.to_csv(caminho, index=False, sep=";", encoding="utf-8-sig")

    log.info("%d citações salvas em %s.", len(tabela), caminho)


def coletar(url_inicial: str, max_paginas: int, pausa: float, saida: Path) -> None:
    registros: list[dict] = []
    visitadas: set[str] = set()
    url: Optional[str] = url_inicial

    with criar_sessao() as sessao:
        try:
            while url and len(visitadas) < max_paginas:
                if url in visitadas:
                    log.warning("Loop de paginação detectado em %s.", url)
                    break
                visitadas.add(url)

                try:
                    dados, proxima = extrair_pagina(sessao, url)
                except requests.RequestException as erro:
                    log.error("Falha em %s: %s", url, erro)
                    break

                registros.extend(dados)
                log.info("Página %d: %d citações.", len(visitadas), len(dados))

                url = proxima
                if url:
                    time.sleep(pausa + random.uniform(0, 1))
        except KeyboardInterrupt:
            log.warning("Interrompido pelo usuário, salvando o que foi coletado.")
        finally:
            salvar(registros, saida)


def ler_argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coletor de citações do quotes.toscrape.com.")
    parser.add_argument("--url", default=URL_INICIAL)
    parser.add_argument("--paginas", type=int, default=10)
    parser.add_argument("--pausa", type=float, default=1.0)
    parser.add_argument("--saida", type=Path, default=Path("citacoes_capturadas.csv"))
    return parser.parse_args()


def main() -> int:
    args = ler_argumentos()
    coletar(args.url, args.paginas, args.pausa, args.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())