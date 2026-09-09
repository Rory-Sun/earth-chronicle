"""Decode base64 canvas captures saved by the browser tool into blender/output/shots/<prefix>_<key>.jpg"""
import json, base64, os, sys
p, prefix = sys.argv[1], sys.argv[2]
arr = json.load(open(p, encoding='utf-8'))
texts = [e.get('text', '') for e in arr]
t = next((x for x in texts if 'javascript_tool' in x), texts[0])
if t.startswith('['): t = t.split('] ', 1)[1].split('\n\n\nTab Context')[0].strip()
obj = json.loads(t)
if isinstance(obj, str): obj = json.loads(obj)
os.makedirs('blender/output/shots', exist_ok=True)
for k, v in obj.items():
    if k == 'meta': print('meta', v); continue
    out = f'blender/output/shots/{prefix}_{k}.jpg'; open(out, 'wb').write(base64.b64decode(v)); print(out, os.path.getsize(out))
