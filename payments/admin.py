from django.contrib import admin

from payments.models import ProcessedEvent, Wallet

admin.site.register(Wallet)
admin.site.register(ProcessedEvent)
