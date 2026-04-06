from django.core.management.base import BaseCommand
from auditlog.models import LogEntry
from django.db.models import Count


class Command(BaseCommand):
    help = 'Inspects AuditLog for deleted entries and shows what can be restored'

    def handle(self, *args, **options):
        self.stdout.write(
            "Scanning AuditLog for deleted records (Action = DELETE)...")

        # Action 0=CREATE, 1=UPDATE, 2=DELETE
        deleted_stats = LogEntry.objects.filter(action=2).values(
            'content_type__app_label',
            'content_type__model'
        ).annotate(count=Count('id')).order_by('-count')

        if not deleted_stats:
            self.stdout.write(self.style.WARNING(
                "No deleted records found in AuditLog."))
            return

        self.stdout.write(f"{'APP':<15} {'MODEL':<25} {'DELETED COUNT':<15}")
        self.stdout.write("-" * 55)

        for stat in deleted_stats:
            app = stat['content_type__app_label']
            model = stat['content_type__model']
            count = stat['count']
            self.stdout.write(f"{app:<15} {model:<25} {count:<15}")

        self.stdout.write("-" * 55)
        self.stdout.write(
            "If a model is NOT listed above, it was not tracked by auditlog and cannot be restored.")
