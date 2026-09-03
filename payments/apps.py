from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self):
        # Import (not just define) the receiver here, not at module import
        # time in models.py/signals.py alone -- ready() is Django's
        # documented one-time hook for connecting signal handlers, called
        # exactly once after the app registry is fully populated. Connecting
        # from a plain module-level import risks running before every model
        # is loaded, or running twice under certain autoreload/test setups.
        from payments import signals  # noqa: F401
