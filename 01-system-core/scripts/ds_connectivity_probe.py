# -*- coding: utf-8 -*-
"""探测 DeepSeek 连通(自动解密DB里的key,key只在内存,绝不写入/打印明文)。
结果(不含明文key)写 /tmp/ds_probe.json。"""
import os, sys, json, ssl, urllib.request
os.chdir('01-system-core')
sys.path.insert(0, '.')
out = {}

# 1) 读 DB schema + deepseek 行(不取 key 值,只看结构/标志位)
try:
    import sqlite3
    con = sqlite3.connect('data/tasks.db'); cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(llm_provider_setting)")]
    out['cols'] = cols
    rows = cur.execute("SELECT * FROM llm_provider_setting").fetchall()
    ds_rows = []
    for r in rows:
        d = dict(zip(cols, r))
        if 'deepseek' in json.dumps(d, default=str).lower():
            safe = {k: (('<len %d>' % len(str(v))) if ('key' in k.lower() or 'encrypt' in k.lower()) and v else v) for k, v in d.items()}
            ds_rows.append(safe)
    out['deepseek_rows'] = ds_rows
    con.close()
except Exception as e:
    out['db_err'] = f"{type(e).__name__}: {e}"

# 2) 用 app service 拿解密后的 settings 并测连通
def try_call(base, model, key):
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    url = base.rstrip('/')
    if not url.endswith('/v1'): url += '/v1'
    url += '/chat/completions'
    body = json.dumps({"model": model, "messages":[{"role":"user","content":"只回复两个字：通了"}], "max_tokens":10, "temperature":0}).encode()
    req = urllib.request.Request(url, body, {"Authorization":"Bearer "+key, "Content-Type":"application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=45, context=ctx); d = json.loads(r.read())
        return {"call":"OK", "reply": d['choices'][0]['message'].get('content','')[:40], "model": model}
    except Exception as e:
        b = e.read()[:200] if hasattr(e,'read') else b''
        return {"call":"FAIL", "model": model, "err": f"{type(e).__name__} {getattr(e,'code','')}: {b.decode('utf-8','ignore')}"}

settings = None
for fn in ['get_generation_settings', 'get_provider_settings', 'resolve_settings']:
    try:
        from app.services import text_generation_service as tg
        if hasattr(tg, fn):
            settings = getattr(tg, fn)(provider="deepseek")
            out['settings_via'] = fn
            break
    except Exception as e:
        out.setdefault('settings_errs', []).append(f"{fn}: {type(e).__name__}: {str(e)[:120]}")

if isinstance(settings, dict):
    base = settings.get('base_url'); model = settings.get('model') or settings.get('default_model'); key = settings.get('api_key')
    out['resolved'] = {"base_url": base, "model": model, "key_present": bool(key)}
    if base and key:
        out['connectivity'] = try_call(base, model or "deepseek-chat", key)
        # 多试几个 deepseek 型号
        out['model_tests'] = {}
        for m in ["deepseek-chat","deepseek-reasoner","deepseek-v4-pro","deepseek-v4-flash"]:
            out['model_tests'][m] = try_call(base, m, key)
else:
    out['resolved'] = "no settings dict from service"

json.dump(out, open('/tmp/ds_probe.json','w'), ensure_ascii=False, indent=1)
print("PROBE_DONE")
