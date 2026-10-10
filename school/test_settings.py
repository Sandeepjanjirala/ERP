"""Deterministic application tests; deployment settings are checked separately."""
from config.settings import *

DEBUG = False
SECURE_SSL_REDIRECT = False
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
# Test accounts use a fast hash. Runtime settings retain Django's default PBKDF2.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
