import xml.etree.ElementTree as ET
import json
import re
import sys
from datetime import datetime

NS_CONTENT = 'http://purl.org/rss/1.0/modules/content/'
NS_MEDIA   = 'http://search.yahoo.com/mrss/'
NS_DC      = 'http://purl.org/dc/elements/1.1/'

def tag_text(el, tag, ns=None):
    if ns:
        found = el.find('{' + ns + '}' + tag)
    else:
        found = el.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ''

def first_img(text):
    if not text:
        return None
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text)
    return m.group(1) if m else None

def get_img(el):
    mc = el.find('{' + NS_MEDIA + '}content')
    if mc is not None and mc.get('url'):
        return mc.get('url')
    mt = el.find('{' + NS_MEDIA + '}thumbnail')
    if mt is not None and mt.get('url'):
        return mt.get('url')
    enc = el.find('enclosure')
    if enc is not None:
        tipo = enc.get('type', '')
        if 'image' in tipo:
            return enc.get('url', '')
    content = tag_text(el, 'encoded', NS_CONTENT)
    result = first_img(content)
    if result:
        return result
    return first_img(tag_text(el, 'description'))

try:
    tree = ET.parse('feed_raw.xml')
except ET.ParseError as e:
    print('Errore parsing XML: ' + str(e))
    sys.exit(1)

channel = tree.getroot().find('channel')
if channel is None:
    print('Nessun elemento channel trovato')
    sys.exit(1)

items = []
for item in channel.findall('item'):
    content     = tag_text(item, 'encoded', NS_CONTENT)
    description = tag_text(item, 'description')
    clean_desc  = re.sub('<[^>]+>', '', description).strip()
    items.append({
        'title':       tag_text(item, 'title'),
        'link':        tag_text(item, 'link'),
        'description': clean_desc,
        'content':     content,
        'pubDate':     tag_text(item, 'pubDate'),
        'category':    tag_text(item, 'category'),
        'author':      tag_text(item, 'creator', NS_DC),
        'image':       get_img(item),
    })

output = {
    'generated': datetime.utcnow().isoformat() + 'Z',
    'source':    'https://www.grandangoloagrigento.it/feed',
    'count':     len(items),
    'items':     items,
}

with open('feed.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print('OK: ' + str(len(items)) + ' articoli salvati in feed.json')
