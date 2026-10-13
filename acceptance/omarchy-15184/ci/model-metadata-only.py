"""No API key, no network, no inference. Only non-secret categories are emitted."""
import os,json,urllib.parse
name=os.environ.get('CONFIG_MODEL_NAME','');family=os.environ.get('CONFIG_MODEL_FAMILY','');url=os.environ.get('CONFIG_MODEL_BASE_URL','')
host=(urllib.parse.urlsplit(url).hostname or '').lower()
provider='unknown'
if host.endswith('.volces.com') or host.endswith('.volcengineapi.com'):provider='volcengine-ark-domain'
elif host=='api.openai.com':provider='openai-domain'
elif host.endswith('.dashscope.aliyuncs.com') or host=='dashscope.aliyuncs.com':provider='dashscope-domain'
name_kind='deployment-alias' if name.startswith('ep-') else 'literal-or-other' if name else 'missing'
known_family=next((x for x in ['doubao-seed','doubao-vision','gpt-6','gpt-5','qwen3-vl','gemini','kimi','glm'] if family==x),'other-or-missing')
# No raw name, endpoint, URL path/query, auth header or key is read or emitted.
print(json.dumps({'provider_category':provider,'model_name_kind':name_kind,'family_category':known_family,'model_name_configured':bool(name),'exact_model_verified':False,'pricing_verified':False,'inference_calls':0}))
