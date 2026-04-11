import json, sys
sys.path.insert(0, '.')
from core.crypto import decrypt_dict_fields

with open('config/wholesalers.json', encoding='utf-8') as f:
    ws = json.load(f)

for wid, data in ws.items():
    name = data.get('name', '')
    if '아남' in wid or '아남' in name:
        cfg = decrypt_dict_fields(dict(data), ['id', 'pw'])
        print('WID:', wid)
        print('Name:', cfg.get('name'))
        print('URL:', cfg.get('url'))
        print('ID:', cfg.get('id'))
        print('PW:', cfg.get('pw'))
        break
