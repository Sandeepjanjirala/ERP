"""Run inside your virtual environment; prepare an isolated local development setup."""
import secrets
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
env = root / '.env'
if not env.exists():
    env.write_text('DEBUG=1\nDJANGO_SECRET_KEY='+secrets.token_urlsafe(60)+'\nPOSTGRES_PASSWORD='+secrets.token_urlsafe(36)+'\nALLOWED_HOSTS=localhost,127.0.0.1,[::1]\n', encoding='utf-8')
    print('Local settings created.')
else:
    print('Using your existing .env file.')
subprocess.run([sys.executable,'manage.py','migrate'],cwd=root,check=True)
print('\nNext: python manage.py seed_demo  (synthetic data only)')
print('Or:   python manage.py createsuperuser  (empty real pilot)')
print('Then: python manage.py runserver')
