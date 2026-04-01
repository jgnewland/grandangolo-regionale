import xml.etree.ElementTree as ET
import json
import re
import sys
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

# ── PAROLE CHIAVE PRIORITÀ ──
PRIORITA = ['palermo', 'catania', 'agrigento', 'sicilia', 'regione siciliana', 'ragusa']

# ── DUPLICATI: titoli già visti ──
titoli_visti = set()

def tag_text(el, tag, ns=None):
    found = el.find('{' + ns + '}' + tag) if ns else el.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ''

def first_img(text):
    if not text:
        return None
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text)
    return m.group(1) if m else None

def get_img(el):
    for ns in [NS_MEDIA]:
        for tag in ['content', 'thumbnail']:
            mc = el.find('{' + ns + '}' + tag)
            if mc is not None and mc.get('url'):
                return mc.get('url')
    enc = el.find('enclosure')
    if enc is not None and 'image' in enc.get('type', ''):
        return enc.get('url', '')
    content = tag_text(el, 'encoded', NS_CONTENT)
    return first_img(content) or first_img(tag_text(el, 'description'))

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

def is_prioritaria(item):
    testo = ' '.join([
        item.get('title', ''),
        item.get('category', ''),
        item.get('description', ''),
        item.get('fonte', ''),
    ]).lower()
    return any(c in testo for c in PRIORITA)

def is_duplicato(title):
    key = re.sub(r'\W+', '', title.lower())[:60]
    if key in titoli_visti:
        return True
    titoli_visti.add(key)
    return False

def scarica_feed(feed_info):
    import urllib.request
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

    channel = tree.find('channel')
    if channel is None:
        # Prova Atom
        channel = tree
    
    for item in channel.findall('item'):
        title = tag_text(item, 'title')
        if not title or is_duplicato(title):
            continue
        content     = tag_text(item, 'encoded', NS_CONTENT)
        description = tag_text(item, 'description')
        clean_desc  = re.sub('<[^>]+>', '', description).strip()
        pub_date    = tag_text(item, 'pubDate')
        items.append({
            'title':       title,
            'link':        tag_text(item, 'link'),
            'description': clean_desc,
            'content':     content,
            'pubDate':     pub_date,
            '_ts':         parse_date(pub_date).timestamp(),
            'category':    tag_text(item, 'category') or fonte,
            'author':      tag_text(item, 'creator', NS_DC),
            'image':       get_img(item),
            'fonte':       fonte,
        })
    print(f'OK {fonte}: {len(items)} articoli')
    return items

# ── SCARICA TUTTI I FEED ──
tutti = []
for feed in FEEDS:
    tutti.extend(scarica_feed(feed))

if not tutti:
    print('ERRORE: nessun articolo raccolto', file=sys.stderr)
    sys.exit(1)

# ── ORDINA PER DATA (più recenti prima) ──
tutti.sort(key=lambda x: x.get('_ts', 0), reverse=True)

# ── RIMUOVI CAMPO INTERNO _ts ──
for item in tutti:
    item.pop('_ts', None)

# ── SEPARA PRIORITARI E ALTRI ──
prioritari = [i for i in tutti if is_prioritaria(i)]
altri      = [i for i in tutti if not is_prioritaria(i)]

# ── MERGE: prioritari prima, poi altri ──
items_finali = prioritari + altri

# ── MAX 80 ARTICOLI ──
items_finali = items_finali[:80]

output = {
    'generated':   datetime.utcnow().isoformat() + 'Z',
    'fonti':       [f['fonte'] for f in FEEDS],
    'count':       len(items_finali),
    'prioritarie': len(prioritari),
    'items':       items_finali,
}

with open('feed.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'\nTOTALE: {len(items_finali)} articoli ({len(prioritari)} prioritari)')
print(f'Fonti: {", ".join(f["fonte"] for f in FEEDS)}')
