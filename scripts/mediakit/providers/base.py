"""Shared HTTP transport for provider adapters. Credentials never follow redirects."""
import json
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('拒绝携带凭据跟随接口重定向')

def request(url,headers,payload):
    data=json.dumps(payload,ensure_ascii=False).encode()
    req=urllib.request.Request(url,data=data,headers={**headers,'Content-Type':'application/json'},method='POST')
    try: return urllib.request.build_opener(NoRedirect).open(req,timeout=180)
    except Exception as e:
        code=getattr(e,'code',None)
        raise ValueError('生成请求未取得可验证结果'+('，HTTP '+str(code) if code else '')+'；先查状态，勿自动重复付费请求') from None
