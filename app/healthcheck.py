"""
Docker HEALTHCHECK script'i.

/health endpoint'ine bağlanabiliyorsa konteyner "healthy" sayılır. Sunucu 503
(degraded/down) dönse bile süreç ayakta demektir → healthy. Yalnızca bağlantı
kurulamazsa (süreç çökmüş/port kapalı) unhealthy.
"""

import os
import sys
import urllib.error
import urllib.request

url = f"http://127.0.0.1:{os.getenv('WEB_PORT', '8080')}/health"

try:
    urllib.request.urlopen(url, timeout=4)
except urllib.error.HTTPError:
    pass  # sunucu yanıt verdi (örn. 503) → ayakta
except Exception:
    sys.exit(1)

sys.exit(0)
