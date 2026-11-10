from django.core.management.base import BaseCommand, CommandError

from apps.demo.services import NotADemoDatabase, reset_demo


class Command(BaseCommand):
    help = (
        "Replace the demo's data with a fresh synthetic seed (demo mode and demo databases only)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--size", choices=["full", "small"], default=None)

    def handle(self, *args, size, **options):
        try:
            reset_demo(size, stdout=self.stdout)
        except NotADemoDatabase as refusal:
            raise CommandError(str(refusal)) from refusal
