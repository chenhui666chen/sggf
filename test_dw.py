import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'backend')
from app.api.v1.dreamweaver_api import router
print(f'Dreamweaver Router OK: {len(router.routes)} routes')
for r in router.routes:
    if hasattr(r, 'path') and hasattr(r, 'methods'):
        print(f'  {r.methods} {r.path}')
