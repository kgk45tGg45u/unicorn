import secrets

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Print a new master key (Fernet) and a new HMAC key for the operator to copy into .env. "
        "Nothing is written to a file or a log."
    )

    def handle(self, *args, **options):
        self.stdout.write("UNICORN_MASTER_KEY=" + Fernet.generate_key().decode())
        self.stdout.write("UNICORN_HMAC_KEY=" + secrets.token_hex(32))
