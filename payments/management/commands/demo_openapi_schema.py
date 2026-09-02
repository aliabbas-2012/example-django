from django.core.management.base import BaseCommand
from drf_spectacular.generators import SchemaGenerator


class Command(BaseCommand):
    help = "Generates the real OpenAPI 3 schema and prints the parts drf-spectacular customizes beyond auto-introspection."

    def handle(self, *args, **options):
        schema = SchemaGenerator().get_schema(request=None, public=True)

        self.stdout.write(self.style.MIGRATE_HEADING("OpenAPI version"))
        self.stdout.write(f"  {schema['openapi']}  (drf-yasg tops out at 2.0 / Swagger)")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("balance_cents: typed via @extend_schema_field"))
        prop = schema["components"]["schemas"]["Wallet"]["properties"]["balance_cents"]
        self.stdout.write(f"  {prop}  (a bare SerializerMethodField would default to a generic string)")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("wallets_credit_create: documented via @extend_schema"))
        op = schema["paths"]["/api/wallets/{id}/credit/"]["post"]
        self.stdout.write(f"  summary: {op.get('summary')}")
        self.stdout.write(f"  requestBody schema ref: {op['requestBody']['content']['application/json']['schema']}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("gateway webhook: excluded from the public schema via @extend_schema(exclude=True)"))
        excluded = "/api/webhooks/gateway/" not in schema["paths"]
        self.stdout.write(f"  excluded: {excluded}")
        assert excluded

        self.stdout.write(self.style.SUCCESS("\nFull schema: python manage.py spectacular --file schema.yaml"))
