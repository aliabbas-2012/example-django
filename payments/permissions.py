"""
Object-level permission for WalletViewSet.credit -- deliberately separate
from the view-level IsAuthenticated check that runs first.

Authentication answers "who is this?" (and 401s if it can't tell).
Permissions answer "is this specific person allowed to do this specific
thing?" (and 403s if the answer is no) -- two different questions,
answered at two different points in DRF's request handling, which is
exactly what demo_drf_internals.py proves by hitting the same endpoint
three ways: no token (401), someone else's wallet (403), your own wallet
(202).
"""

from rest_framework.permissions import BasePermission


class IsWalletOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner_id == request.user.username
