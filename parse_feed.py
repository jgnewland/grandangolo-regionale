import xml.etree.ElementTree as ET
import json
import re
import sys
import os
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

NS_CONTENT = 'http://purl.org/rss/1.0/modules/content/'
NS_MEDIA   = 'http://search.yahoo.com/mrss/'
NS_DC      = 'http://purl.org/dc/elements/1.1/'

# ── FONTI RSS ──
FEEDS = [
    {'url': 'https://www.grandangoloagrigento.it/feed', 'fonte': 'Grandangolo Agrigento'},
]

PRIORITA = ['palermo','catania','agrigento','sicilia','regione siciliana',
            'ragusa','trapani','messina','enna','caltanissetta','siracusa']

FRASI_SORGENTE = [
    'proviene da','appeared first','the post','su livesicilia','su blogsicilia',
    'su palermotoday','su cataniatoday','su lasicilia','su ragusanews',
    'su grandangolo','leggi su','leggi tutto su','continua a leggere su',
    'pubblicato su','originally published'
]

CATEGORIE_MAP = {
    'cronaca':'Cronaca','crime':'Cronaca','nera':'Cronaca',
    'politica':'Politica','governo':'Politica','comune':'Politica',
    'giudiziaria':'Giudiziaria','mafia':'Giudiziaria','antimafia':'Giudiziaria',
    'giustizia':'Giudiziaria','tribunale':'Giudiziaria','arresti':'Giudiziaria',
    'economia':'Economia','lavoro':'Economia','finanza':'Economia',
    'cultura':'Cultura','spettacoli':'Cultura','arte':'Cultura','cinema':'Cultura',
    'musica':'Cultura','teatro':'Cultura',
    'sport':'Sport','calcio':'Sport',
    'inchieste':'Inchieste','inchiesta':'Inchieste',
    'ambiente':'Ambiente','meteo':'Ambiente',
    'agrigento':'Agrigento','palermo':'Palermo','catania':'Catania',
    'ragusa':'Ragusa','messina':'Messina','trapani':'Trapani',
    'siracusa':'Siracusa','enna':'Enna','caltanissetta':'Caltanissetta',
}

titoli_visti = set()

# ── UTILS ──
def tag_text(el, tag, ns=None):
    found = el.find('{'+ns+'}'+tag) if ns else el.find(tag)
    return found.text.strip() if found is not None and found.text else ''

def normalizza_categoria(cat, title='', desc=''):
    if not cat:
        testo = (title+' '+desc).lower()
        for kw in ['palermo','catania','agrigento','ragusa','messina','trapani','siracusa','enna','caltanissetta']:
            if kw in testo:
                return kw.capitalize()
        return 'Sicilia'
    cl = cat.lower().strip()
    for k,v in CATEGORIE_MAP.items():
        if k in cl:
            return v
    if len(cat)>25 or '-' in cat or cat.isupper():
        return 'Sicilia'
    return cat.strip().capitalize()[:20]

def is_duplicato(title):
    key = re.sub(r'\W+','',title.lower())[:60]
    if key in titoli_visti:
        return True
    titoli_visti.add(key)
    return False

def is_prioritaria(item):
    testo = ' '.join([item.get('title',''), item.get('category',''), item.get('description','')]).lower()
    return any(c in testo for c in PRIORITA)

def parse_date(s):
    if not s:
        return datetime(2000,1,1,tzinfo=timezone.utc)
    try:
        return parsedate_to_datetime(s)
    except:
        try:
            return datetime.fromisoformat(s)
        except:
            return datetime(2000,1,1,tzinfo=timezone.utc)

# ── PULIZIA HTML con BeautifulSoup ──
def pulisci_html(html):
    """Pulisce HTML con BeautifulSoup — nessun tag rotto possibile."""
    if not html or not html.strip():
        return ''
    try:
        soup = BeautifulSoup(html, 'lxml')
    except:
        soup = BeautifulSoup(html, 'html.parser')

    # Rimuovi tag inutili
    for tag in soup(['script','style','iframe','noscript','form','button','input',
                     'header','footer','nav','aside','figure > figcaption']):
        tag.decompose()

    # Rimuovi div/section con classi pubblicitarie o social
    classi_da_rimuovere = ['share','social','related','tag','comment','advertisement',
                           'adv','banner','newsletter','sidebar','widget','promo','pub',
                           'cookie','gdpr','popup','modal','ad-']
    for el in soup.find_all(True, class_=True):
        classi = ' '.join(el.get('class',[])).lower()
        if any(c in classi for c in classi_da_rimuovere):
            el.decompose()

    # Pulisci immagini
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or ''
        # Scarta immagini tracker o troppo piccole
        if not src or any(x in src for x in ['pixel','1x1','tracker','gif?','blank','spacer']):
            img.decompose()
            continue
        # Ricrea img pulita con solo src
        nuovo = BeautifulSoup(
            f'<img src="{src}" loading="lazy" style="max-width:100%;height:auto;display:block;margin:20px auto"/>',
            'html.parser'
        ).find('img')
        img.replace_with(nuovo)

    # Rimuovi paragrafi/div con riferimenti al sito sorgente
    for el in soup.find_all(['p','div','span','li']):
        testo = el.get_text().lower()
        if any(f in testo for f in FRASI_SORGENTE):
            el.decompose()

    # Rimuovi elementi vuoti
    for el in soup.find_all(['p','div','span']):
        if not el.get_text(strip=True) and not el.find('img'):
            el.decompose()

    # Tieni solo i tag editoriali puliti
    testo_html = ''
    for el in soup.find_all(['p','h2','h3','h4','ul','ol','li','blockquote','img']):
        if el.name == 'img':
            testo_html += str(el) + '\n'
        elif el.name in ['p','h2','h3','h4']:
            testo = el.get_text(strip=True)
            if testo and len(testo) > 10:
                # Pulisci attributi dal tag
                testo_html += f'<{el.name}>{el.decode_contents()}</{el.name}>\n'
        elif el.name in ['ul','ol']:
            testo_html += str(el) + '\n'

    return testo_html.strip()

def pulisci_sommario(testo):
    """Rimuove riferimenti ai siti sorgente dal sommario."""
    if not testo:
        return ''
    # Rimuovi frasi tipo "Articolo X su Sito.it"
    testo = re.sub(r'Articolo\s+[^\.]{0,100}su\s+[\w\-\.]+\.[a-z]{2,}\.?', '', testo, flags=re.IGNORECASE)
    testo = re.sub(r'su\s+[\w\-]+\.[a-z]{2,}\.?\s*$', '', testo, flags=re.IGNORECASE)
    testo = re.sub(r'Leggi\s+(tutto|di\s+più|l\'articolo).*$', '', testo, flags=re.IGNORECASE)
    testo = re.sub(r'\s{2,}', ' ', testo).strip(' .-')
    return testo

# ── ESTRAI IMMAGINE DAL FEED ──
def get_img(el):
    for tag in ['content','thumbnail']:
        mc = el.find('{'+NS_MEDIA+'}'+tag)
        if mc is not None and mc.get('url'):
            url = mc.get('url')
            if not any(x in url for x in ['pixel','1x1','tracker']):
                return url
    enc = el.find('enclosure')
    if enc is not None and 'image' in enc.get('type',''):
        return enc.get('url','')
    # Cerca prima img nel content HTML
    for field in [tag_text(el,'encoded',NS_CONTENT), tag_text(el,'description')]:
        if field:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', field)
            if m:
                src = m.group(1)
                if not any(x in src for x in ['pixel','1x1','tracker']):
                    return src
    return None

# ── SCARICA IMMAGINE ──
IMG_DIR = 'imgs'
os.makedirs(IMG_DIR, exist_ok=True)

def scarica_immagine(url, idx):
    if not url:
        return None
    try:
        ext = '.jpg'
        if '.png' in url.lower(): ext = '.png'
        elif '.webp' in url.lower(): ext = '.webp'
        nome = f'img_{idx:04d}{ext}'
        percorso = os.path.join(IMG_DIR, nome)
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': '/'.join(url.split('/')[:3])+'/',
            'Accept': 'image/*,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        if len(data) < 3000:
            return None
        with open(percorso,'wb') as f:
            f.write(data)
        return percorso
    except:
        return None

# ── SCARICA TESTO COMPLETO dalla pagina ──
def scarica_testo_completo(url):
    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'it-IT,it;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, 'lxml')

        # Rimuovi elementi non-contenuto
        for tag in soup(['script','style','nav','header','footer','aside',
                         'form','iframe','noscript','button']):
            tag.decompose()

        # Cerca il contenitore principale dell'articolo
        selettori = [
            {'class': re.compile(r'entry-content|post-content|article-body|article__body|'
                                 r'article__content|content-article|news-body|article-text|'
                                 r'single-content|the-content|articolo-testo|testo-articolo|'
                                 r'corpo-articolo|news__content|post__content', re.I)},
            {'itemprop': 'articleBody'},
            {'role': 'main'},
        ]

        contenuto = None
        for sel in selettori:
            el = soup.find(['div','section','article'], sel)
            if el:
                testo_grezzo = el.get_text(strip=True)
                if len(testo_grezzo.split()) > 80:
                    contenuto = el
                    break

        if not contenuto:
            # Fallback: prendi l'articolo più lungo
            candidati = soup.find_all(['article','main','div'], limit=20)
            for c in candidati:
                if len(c.get_text(strip=True).split()) > 100:
                    contenuto = c
                    break

        if not contenuto:
            return None

        return pulisci_html(str(contenuto))
    except Exception as e:
        return None

# ── SCARICA FEED ──
def scarica_feed(feed_info):
    items = []
    url = feed_info['url']
    fonte = feed_info['fonte']
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; GrandangoloRegionale/2.0)'
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            xml_data = r.read()
        tree = ET.fromstring(xml_data)
    except Exception as e:
        print(f'SKIP {fonte}: {e}', file=sys.stderr)
        return []

    channel = tree.find('channel') or tree

    for item in channel.findall('item'):
        title = tag_text(item,'title')
        if not title or is_duplicato(title):
            continue

        raw_content    = tag_text(item,'encoded',NS_CONTENT)
        raw_desc       = tag_text(item,'description')
        content_pulito = pulisci_html(raw_content or raw_desc)
        desc_pulita    = pulisci_sommario(
            BeautifulSoup(raw_desc,'html.parser').get_text(strip=True) if raw_desc else ''
        )
        pub_date = tag_text(item,'pubDate')
        cat_raw  = tag_text(item,'category')

        items.append({
            'title':       title,
            'link':        tag_text(item,'link'),
            'description': desc_pulita,
            'content':     content_pulito,
            'pubDate':     pub_date,
            '_ts':         parse_date(pub_date).timestamp(),
            'category':    normalizza_categoria(cat_raw, title, desc_pulita),
            'image_url':   get_img(item),
            'image':       None,
            'fonte':       fonte,
        })

    print(f'OK {fonte}: {len(items)} articoli')
    return items

# ═══════════════════════════════════
# MAIN
# ═══════════════════════════════════

tutti = []
for feed in FEEDS:
    tutti.extend(scarica_feed(feed))

if not tutti:
    print('ERRORE: nessun articolo raccolto', file=sys.stderr)
    sys.exit(1)

# Ordina per data
tutti.sort(key=lambda x: x.get('_ts',0), reverse=True)
for item in tutti:
    item.pop('_ts',None)

# Priorità
prioritari = [i for i in tutti if is_prioritaria(i)]
altri      = [i for i in tutti if not is_prioritaria(i)]
items_finali = (prioritari + altri)[:80]

# Scarica immagini
print(f'\nScarico immagini...')
scaricate = 0
for idx, item in enumerate(items_finali):
    url_img = item.pop('image_url', None)
    item.pop('fonte', None)
    if url_img:
        percorso = scarica_immagine(url_img, idx)
        if percorso:
            item['image'] = percorso
            scaricate += 1
print(f'Immagini: {scaricate}/{len(items_finali)}')

# Scarica testo completo per articoli con contenuto insufficiente
print(f'\nArricchimento testo...')
arricchiti = 0
for idx, item in enumerate(items_finali):
    parole = len(re.sub('<[^>]+>','',item.get('content','')).split())
    if parole < 80 and item.get('link'):
        testo = scarica_testo_completo(item['link'])
        if testo and len(re.sub('<[^>]+>','',testo).split()) > 80:
            item['content'] = testo
            arricchiti += 1
print(f'Arricchiti: {arricchiti}/{len(items_finali)}')

# Salva
output = {
    'generated':   datetime.utcnow().isoformat() + 'Z',
    'count':       len(items_finali),
    'prioritarie': len(prioritari),
    'items':       items_finali,
}
with open('feed.json','w',encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'\nTOTALE: {len(items_finali)} articoli in feed.json')
