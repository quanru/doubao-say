"""Match only public model identifiers; never print raw secrets or access an API key.
Provider account/balance cannot be inferred. No network or inference requests.
"""
import os,json,urllib.parse
catalog={
 'doubao-seed-2-1-turbo-260628':{'family':'Doubao Seed','generation':'2.1','variant':'Turbo','release':'2026-06-28'},
 'doubao-seed-2-1-pro-260628':{'family':'Doubao Seed','generation':'2.1','variant':'Pro','release':'2026-06-28'},
 'doubao-seed-2-0-lite-260428':{'family':'Doubao Seed','generation':'2.0','variant':'Lite','release':'2026-04-28'},
 'doubao-seed-2-0-mini-260428':{'family':'Doubao Seed','generation':'2.0','variant':'Mini','release':'2026-04-28'},
 'doubao-seed-2-0-pro-260215':{'family':'Doubao Seed','generation':'2.0','variant':'Pro','release':'2026-02-15'},
 'doubao-seed-2-0-lite-260215':{'family':'Doubao Seed','generation':'2.0','variant':'Lite','release':'2026-02-15'},
 'doubao-seed-2-0-mini-260215':{'family':'Doubao Seed','generation':'2.0','variant':'Mini','release':'2026-02-15'},
 'doubao-seed-1-8-251228':{'family':'Doubao Seed','generation':'1.8','release':'2025-12-28'},
 'doubao-seed-1-6-vision-250815':{'family':'Doubao Seed','generation':'1.6','variant':'Vision','release':'2025-08-15'},
 'doubao-seed-1-6-250615':{'family':'Doubao Seed','generation':'1.6','release':'2025-06-15'}
}
name=os.environ.get('CONFIG_MODEL_NAME','');host=(urllib.parse.urlsplit(os.environ.get('CONFIG_MODEL_BASE_URL','')).hostname or '').lower()
match=catalog.get(name)
print(json.dumps({'public_catalog_match':match,'provider_is_volcengine_ark':host.endswith('.volces.com') or host.endswith('.volcengineapi.com'),'deployment_alias':name.startswith('ep-'),'no_match_requires_user_model_info':match is None,'inference_calls':0,'api_key_accessed':False},ensure_ascii=False))
