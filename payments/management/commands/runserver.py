from django.contrib.staticfiles.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    """
    Overrides Django's default dev server port (8000, hardcoded in
    django.core.management.commands.runserver) with 8011 -- 8000 is
    already taken by an unrelated PHP dev server on this machine.
    `python manage.py runserver` alone now binds 8011; an explicit
    `python manage.py runserver <port>` still overrides it either way.

    Subclasses staticfiles' runserver (not the bare core one) so DEBUG
    static-file serving -- which /api/docs/'s Swagger UI assets rely on
    -- keeps working exactly as before; only default_port changes.
    """

    default_port = "8011"
