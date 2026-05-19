import os
import re
import subprocess
from datetime import datetime
import requests
from xml.etree import ElementTree as ET
from xml.dom import minidom

URLS = {
    "L": "https://portalimoveis.casasoft.net.br/ftp/agendacafe/14570/casasoft14570l10.xml",
    "V": "https://portalimoveis.casasoft.net.br/ftp/agendacafe/14570/casasoft14570v10.xml",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "joharc_meta.xml")


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_text(element, tag, default=""):
    node = element.find(tag)
    if node is None or node.text is None:
        return default
    return node.text.strip()


def format_price(value):
    try:
        num = float(value.replace(",", "."))
        return f"{int(num)} BRL"
    except (ValueError, AttributeError):
        return "0 BRL"


def property_type(tipo):
    t = (tipo or "").lower()
    if "apart" in t:
        return "apartment"
    if "terreno" in t or "lote" in t:
        return "land"
    if "casa" in t or "resid" in t:
        return "house"
    return "other"


def sub(parent, tag, text=None, **attribs):
    el = ET.SubElement(parent, tag, **attribs)
    if text is not None:
        el.text = text
    return el


def convert(imovel_para, imovel_el):
    listing = ET.Element("listing")

    codigo = get_text(imovel_el, "codigo")
    sub(listing, "home_listing_id", f"14570-{codigo}")

    titulo = get_text(imovel_el, "titulodoimovel")
    sub(listing, "name", titulo)

    if imovel_para == "L":
        availability = "for_rent"
        listing_type = "for_rent_by_agent"
        price_raw = get_text(imovel_el, "valorlocacao")
    else:
        availability = "for_sale"
        listing_type = "for_sale_by_agent"
        price_raw = get_text(imovel_el, "valortotal")

    sub(listing, "availability", availability)
    sub(listing, "listing_type", listing_type)

    observacao = get_text(imovel_el, "observacao")
    descricao = strip_html(f"{titulo} {observacao}")
    sub(listing, "description", descricao)

    # endereço está dentro de <endereco>
    endereco_el = imovel_el.find("endereco")
    logradouro = get_text(endereco_el, "logradouro") if endereco_el is not None else ""
    numero = get_text(endereco_el, "numero") if endereco_el is not None else ""
    addr1 = " ".join(filter(None, [logradouro, numero]))
    city = get_text(imovel_el, "cidade")
    region = get_text(imovel_el, "uf")
    postal_code = get_text(imovel_el, "cep")

    address = sub(listing, "address", format="simple")
    sub(address, "component", addr1, name="addr1")
    sub(address, "component", city, name="city")
    sub(address, "component", region, name="region")
    sub(address, "component", "Brasil", name="country")
    sub(address, "component", postal_code, name="postal_code")

    lat = get_text(imovel_el, "latitude")
    lon = get_text(imovel_el, "longitude")
    if lat:
        sub(listing, "latitude", lat)
    if lon:
        sub(listing, "longitude", lon)

    bairro = get_text(imovel_el, "bairro")
    sub(listing, "neighborhood", bairro)

    # fotos dentro de <galeriaimagens><fotos><foto>
    # URL completa = urlarquivo + nomearquivo
    galeria_el = imovel_el.find("galeriaimagens")
    if galeria_el is not None:
        fotos_el = galeria_el.find("fotos")
        if fotos_el is not None:
            for foto in fotos_el.findall("foto"):
                url_foto = get_text(foto, "urlarquivo")
                if url_foto:
                    img = sub(listing, "image")
                    sub(img, "url", url_foto)

    # quartos e banheiros dentro de <caracteristicaspadrao>
    caract_el = imovel_el.find("caracteristicaspadrao")
    num_beds = get_text(caract_el, "quarto") if caract_el is not None else "0"
    num_baths = get_text(caract_el, "banheiro") if caract_el is not None else "0"
    sub(listing, "num_beds", num_beds or "0")
    sub(listing, "num_baths", num_baths or "0")
    sub(listing, "num_units", "1")
    sub(listing, "price", format_price(price_raw))

    tipo = get_text(imovel_el, "tipoimovel")
    sub(listing, "property_type", property_type(tipo))

    sub(listing, "url", "https://www.joharc.com.br")

    return listing


def prettify(root):
    raw = ET.tostring(root, encoding="unicode")
    parsed = minidom.parseString(raw)
    return parsed.toprettyxml(indent="  ", encoding="utf-8")


def fetch_listings(imovel_para, root_out):
    url = URLS[imovel_para]
    label = "locação" if imovel_para == "L" else "venda"
    print(f"Baixando {label}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    # corrige encoding: substitui declaração iso-8859-1 antes de parsear como utf-8
    content = resp.content.decode("iso-8859-1")
    content = content.replace('encoding="iso-8859-1"', 'encoding="utf-8"')
    content = content.replace("encoding='iso-8859-1'", "encoding='utf-8'")
    root_in = ET.fromstring(content.encode("utf-8"))

    count = 0
    for imovel_el in root_in.findall(".//imovel"):
        listing = convert(imovel_para, imovel_el)
        root_out.append(listing)
        count += 1

    print(f"  -> {count} imóveis de {label}")
    return count


if __name__ == "__main__":
    root_out = ET.Element("listings")

    total_loc = fetch_listings("L", root_out)
    total_venda = fetch_listings("V", root_out)

    xml_bytes = prettify(root_out)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(xml_bytes)

    total = total_loc + total_venda
    print(f"\nResumo:")
    print(f"  Locação : {total_loc} imóveis")
    print(f"  Venda   : {total_venda} imóveis")
    print(f"  Total   : {total} imóveis -> {OUTPUT_FILE}")

    # commit e push para GitHub
    data = datetime.now().strftime("%Y-%m-%d %H:%M")
    subprocess.run(["git", "-C", SCRIPT_DIR, "add", OUTPUT_FILE], check=True)
    result = subprocess.run(["git", "-C", SCRIPT_DIR, "commit", "-m", f"Atualiza feed Meta - {total} imóveis ({data})"])
    if result.returncode == 0:
        subprocess.run(["git", "-C", SCRIPT_DIR, "push"], check=True)
        print("Feed enviado ao GitHub com sucesso.")
    else:
        print("Feed sem alterações, push não necessário.")
