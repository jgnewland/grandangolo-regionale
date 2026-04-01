import xml.etree.ElementTree as ET
import json
import re
import sys
import os
import urllib.request
import urllib.error
import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

NS_CONTENT = 'http://purl.org/rss/1.0/modules/content/'
NS_MEDIA   = 'http://search.yahoo.com/mrss/'
NS_DC      = 'http://purl.org/dc/elements/1.1/'

# ── FONTI RSS ──
FEEDS = [
    {'url': 'https://www.grandangoloagrigento.it/feed',      'fonte': 'Grandangolo Agrigento'},
    {'url': 'https://www.palermotoday.it/rss/homepage.rss',  'fonte': 'PalermoToday'},
    {'url': 'https://www.cataniatoday.it/rss/homepage.rss',  'fonte': 'CataniaToday'},
    {'url': 'https://www.lasicilia.it/rss',                  'fonte': 'La Sicilia'},
    {'url': 'https://livesicilia.it/feed',                   'fonte': 'LiveSicilia'},
    {'url': 'https://www.blogsicilia.it/feed',               'fonte': 'BlogSicilia'},
    {'url': 'https://www.ragusanews.com/feed',               'fonte': 'RagusaNews'},
]

# ── PRIORITÀ ──
PRIORITA = ['palermo', 'catania', 'agrigento', 'sicilia', 'regione siciliana', 'ragusa', 'trapani', 'messina', 'enna', 'caltanissetta', 'siracusa']

# ── NORMALIZZAZIONE CATEGORIE ──
CATEGORIE_MAP = {
    # Cronaca
    'cronaca': 'Cronaca', 'crime': 'Cronaca', 'nera': 'Cronaca',
    # Politica
    'politica': 'Politica', 'politics': 'Politica', 'governo': 'Politica', 'comune': 'Politica',
    # Giudiziaria
    'giudiziaria': 'Giudiziaria', 'mafia': 'Giudiziaria', 'antimafia': 'Giudiziaria',
    'giustizia': 'Giudiziaria', 'tribunale': 'Giudiziaria', 'arresti': 'Giudiziaria',
    # Economia
    'economia': 'Economia', 'lavoro': 'Economia', 'finanza': 'Economia', 'business': 'Economia',
    # Cultura
    'cultura': 'Cultura', 'spettacoli': 'Cultura', 'arte': 'Cultura', 'cinema': 'Cultura',
    'musica': 'Cultura', 'teatro': 'Cultura', 'libri': 'Cultura',
    # Sport
    'sport': 'Sport', 'calcio': 'Sport', 'serie a': 'Sport', 'palermo calcio': 'Sport',
    # Inchieste
    'inchieste': 'Inchieste', 'inchiesta': 'Inchieste',
    # Ambiente
    'ambiente': 'Ambiente', 'natura': 'Ambiente', 'meteo': 'Ambiente',
    # Città siciliane
    'agrigento': 'Agrigento', 'palermo': 'Palermo', 'catania': 'Catania',
    'ragusa': 'Ragusa', 'messina': 'Messina', 'trapani': 'Trapani',
    'siracusa': 'Siracusa', 'enna': 'Enna', 'caltanissetta': 'Caltanissetta',
}

def normalizza_categoria(cat_raw, title='', description=''):
    if not cat_raw:
        # Prova a indovinare dalla città nel titolo
        testo = (title + ' ' + description).lower()
        for kw in ['palermo','catania','agrigento','ragusa','messina','trapani','siracusa','enna','caltanissetta']:
            if kw in testo:
                return kw.capitalize()
        return 'Sicilia'
    cat_lower = cat_raw.lower().strip()
    # Cerca corrispondenza diretta
    for k, v in CATEGORIE_MAP.items():
        if k in cat_lower:
            return v
    # Se è una categoria strana (contiene trattini, è lunga, tutto maiuscolo) → Sicilia
    if len(cat_raw) > 30 or '-' in cat_raw or cat_raw.isupper():
        return 'Sicilia'
    # Capitalizza e tronca se troppo lunga
    return cat_raw.strip().capitalize()[:20]

# ── DUPLICATI ──
titoli_visti = set()

def is_duplicato(title):
    key = re.sub(r'\W+', '', title.lower())[:60]
    if key in titoli_visti:
        return True
    titoli_visti.add(key)
    return False

# ── ESTRAI IMMAGINE ──
def tag_text(el, tag, ns=None):
    found = el.find('{' + ns + '}' + tag) if ns else el.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ''

def first_img(text):
    if not text:
        return None
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text)
    if m:
        src = m.group(1)
        # Escludi immagini piccole (icone, pixel tracker)
        if 'pixel' in src or '1x1' in src or 'tracker' in src:
            return None
        return src
    return None

def get_img(el):
    # 1. media:content / media:thumbnail
    for tag in ['content', 'thumbnail']:
        mc = el.find('{' + NS_MEDIA + '}' + tag)
        if mc is not None and mc.get('url'):
            url = mc.get('url')
            if not any(x in url for x in ['pixel','1x1','tracker','gif?']):
                return url
    # 2. enclosure
    enc = el.find('enclosure')
    if enc is not None and 'image' in enc.get('type', ''):
        return enc.get('url', '')
    # 3. prima img nel content
    content = tag_text(el, 'encoded', NS_CONTENT)
    img = first_img(content)
    if img:
        return img
    # 4. prima img nella description
    return first_img(tag_text(el, 'description'))

# ── SCARICA TESTO COMPLETO DALLA PAGINA ──
def scarica_testo_completo(url):
    """Scarica la pagina e estrae il testo dell'articolo."""
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'it-IT,it;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')

        # Selettori CSS per il corpo articolo nei vari siti
        # Usa regex per estrarre il contenuto principale
        selettori = [
            # Classi tipiche dei CMS italiani
            r'<article[^>]*>(.*?)</article>',
            r'<div[^>]*class="[^"]*(?:entry-content|post-content|article-body|article__body|content-article|news-body|article-text|single-content|the-content)[^"]*"[^>]*>(.*?)</div>\s*(?:<div|</article)',
        ]

        testo = None
        for pattern in selettori:
            m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                raw = m.group(1)
                # Pulisci elementi non necessari
                raw = re.sub(r'<(script|style|nav|header|footer|aside|form|button|iframe|noscript)[^>]*>.*?</\1>', '', raw, flags=re.DOTALL|re.IGNORECASE)
                raw = re.sub(r'<div[^>]*class="[^"]*(?:share|social|related|tag|comment|advertisement|pub|adv|banner|newsletter|sidebar)[^"]*"[^>]*>.*?</div>', '', raw, flags=re.DOTALL|re.IGNORECASE)
                # Conta le parole — deve essere un testo vero
                parole = len(re.sub('<[^>]+>', '', raw).split())
                if parole > 80:
                    testo = raw
                    break

        return testo
    except Exception as e:
        return None

# ── SCARICA IMMAGINE LOCALMENTE ──
IMG_DIR = 'imgs'
os.makedirs(IMG_DIR, exist_ok=True)

def scarica_immagine(url, idx):
    if not url:
        return None
    try:
        # Genera nome file unico
        ext = '.jpg'
        if '.png' in url.lower(): ext = '.png'
        elif '.webp' in url.lower(): ext = '.webp'
        nome = f'img_{idx:04d}{ext}'
        percorso = os.path.join(IMG_DIR, nome)

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': url.split('/')[0] + '//' + url.split('/')[2] + '/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
            # Verifica che sia un'immagine vera (min 5KB)
            if len(data) < 5000:
                return None
            with open(percorso, 'wb') as f:
                f.write(data)
        return percorso
    except Exception as e:
        return None

# ── PARSE DATA ──
def parse_date(s):
    if not s:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    try:
        return parsedate_to_datetime(s)
    except Exception:
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime(2000, 1, 1, tzinfo=timezone.utc)

# ── PRIORITÀ ──
def is_prioritaria(item):
    testo = ' '.join([item.get('title',''), item.get('category',''), item.get('description','')]).lower()
    return any(c in testo for c in PRIORITA)

# ── SCARICA FEED ──
def scarica_feed(feed_info):
    items = []
    url = feed_info['url']
    fonte = feed_info['fonte']
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; GrandangoloRegionale/2.0; +https://regionale.grandangolosettimanale.it)'
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_data = r.read()
        tree = ET.fromstring(xml_data)
    except Exception as e:
        print(f'SKIP {fonte}: {e}', file=sys.stderr)
        return []

    channel = tree.find('channel')
    if channel is None:
        channel = tree

    for item in channel.findall('item'):
        title = tag_text(item, 'title')
        if not title or is_duplicato(title):
            continue
        content     = tag_text(item, 'encoded', NS_CONTENT)
        description = tag_text(item, 'description')
        clean_desc  = re.sub('<[^>]+>', '', description).strip()
        # Rimuovi riferimenti al sito sorgente nel sommario
        clean_desc  = re.sub(r'\s*Articolo\s+[^\.]+su\s+[\w\.]+\.[a-z]+\.?\s*', ' ', clean_desc, flags=re.IGNORECASE)
        clean_desc  = re.sub(r'\s*su\s+\w[\w\-]*\.[a-z]{2,}\.?\s*$', '', clean_desc, flags=re.IGNORECASE)
        clean_desc  = re.sub(r'\s*Leggi (tutto|di più|l\'articolo).*$', '', clean_desc, flags=re.IGNORECASE)
        clean_desc  = re.sub(r'\s{2,}', ' ', clean_desc).strip()
        pub_date    = tag_text(item, 'pubDate')
        cat_raw     = tag_text(item, 'category')
        cat_norm    = normalizza_categoria(cat_raw, title, clean_desc)

        items.append({
            'title':       title,
            'link':        tag_text(item, 'link'),
            'description': clean_desc,
            'content':     content,
            'pubDate':     pub_date,
            '_ts':         parse_date(pub_date).timestamp(),
            'category':    cat_norm,
            'author':      tag_text(item, 'creator', NS_DC),
            'image_url':   get_img(item),  # URL originale
            'image':       None,            # verrà impostato dopo
            'fonte':       fonte,
        })
    print(f'OK {fonte}: {len(items)} articoli')
    return items

# ── RACCOLTA ──
tutti = []
for feed in FEEDS:
    tutti.extend(scarica_feed(feed))

if not tutti:
    print('ERRORE: nessun articolo raccolto', file=sys.stderr)
    sys.exit(1)

# ── ORDINA ──
tutti.sort(key=lambda x: x.get('_ts', 0), reverse=True)
for item in tutti:
    item.pop('_ts', None)

# ── PRIORITÀ ──
prioritari = [i for i in tutti if is_prioritaria(i)]
altri      = [i for i in tutti if not is_prioritaria(i)]
items_finali = (prioritari + altri)[:80]

# ── SCARICA IMMAGINI LOCALMENTE ──
print(f'\nScarico immagini per {len(items_finali)} articoli...')
scaricate = 0
for idx, item in enumerate(items_finali):
    url_img = item.get('image_url')
    if url_img:
        percorso = scarica_immagine(url_img, idx)
        if percorso:
            item['image'] = percorso
            scaricate += 1
        else:
            item['image'] = None
    else:
        item['image'] = None
    item.pop('image_url', None)
    item.pop('fonte', None)

print(f'Immagini scaricate: {scaricate}/{len(items_finali)}')

# ── SCARICA TESTO COMPLETO per articoli con contenuto insufficiente ──
print(f'\nControllo testo completo articoli...')
arricchiti = 0
for idx, item in enumerate(items_finali):
    content = item.get('content', '')
    # Conta parole nel content attuale
    parole = len(re.sub('<[^>]+>', '', content).split())
    if parole < 100 and item.get('link'):
        print(f'  [{idx+1}] Scarico testo completo: {item["link"][:60]}...')
        testo = scarica_testo_completo(item['link'])
        if testo:
            item['content'] = testo
            arricchiti += 1
            print(f'  OK: testo aggiunto ({len(re.sub("<[^>]+>","",testo).split())} parole)')
        else:
            print(f'  SKIP: impossibile scaricare')

print(f'Articoli arricchiti con testo completo: {arricchiti}/{len(items_finali)}')

# ── SALVA JSON ──
output = {
    'generated':   datetime.utcnow().isoformat() + 'Z',
    'count':       len(items_finali),
    'prioritarie': len(prioritari),
    'items':       items_finali,
}

with open('feed.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'TOTALE: {len(items_finali)} articoli salvati in feed.json')
print(f'Cartella immagini: {IMG_DIR}/ ({scaricate} files)')
