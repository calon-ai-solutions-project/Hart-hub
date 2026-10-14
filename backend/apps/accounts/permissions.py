"""Who may do what in the portal. Checked on the server: hiding a button in the page is never the protection.

| Role  | Stock chat | WhatsApp enquiries                                         | Home dashboard          |
| ----- | ---------- | ---------------------------------------------------------- | ----------------------- |
| owner | yes        | every enquiry; can approve, reply and send                 | whole team              |
| sales | yes        | unassigned ones and their own; can approve, reply and send | my day                  |
| admin | no         | every enquiry, read only                                   | won deals (chosen cars) |
"""

from rest_framework.permissions import BasePermission

OWNER, SALES, ADMIN = "owner", "sales", "admin"
SECTIONS = {
    OWNER: ["home", "chat", "whatsapp"],
    SALES: ["home", "chat", "whatsapp"],
    ADMIN: ["home", "whatsapp"],
}


def role_of(user):
    return getattr(user, "role", "") if user and user.is_authenticated else ""


class _Roles(BasePermission):
    roles = ()
    message = "Your role does not include this."

    def has_permission(self, request, view):
        return role_of(request.user) in self.roles


class CanSell(_Roles):
    """Owner and sales: talk to customers, search stock, get quotes."""

    roles = (OWNER, SALES)


class CanView(_Roles):
    """Every role: read enquiries (admin only reads)."""

    roles = (OWNER, SALES, ADMIN)


def enquiries_for(user, queryset):
    """The enquiries a person may see: a salesperson sees the unassigned ones and their own."""
    if role_of(user) == SALES:
        from django.db.models import Q

        return queryset.filter(Q(assigned_to__isnull=True) | Q(assigned_to=user))
    return queryset


def may_work_on(user, enquiry):
    """May this person approve, reply or send on this enquiry?"""
    role = role_of(user)
    if role == OWNER:
        return True
    return role == SALES and enquiry.assigned_to_id in (None, user.id)
