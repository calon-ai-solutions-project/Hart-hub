from celery import shared_task

from .services import engine


@shared_task(name="enquiries.prepare_options")
def prepare_options(enquiry_id):
    engine.prepare_options(enquiry_id)


@shared_task(name="enquiries.ask_purpose")
def ask_purpose(enquiry_id):
    engine.ask_purpose(enquiry_id)


@shared_task(name="enquiries.whatsapp_inbound")
def whatsapp_inbound(phone, text, external_id):
    from django.conf import settings

    engine.handle_inbound(phone, text, channel="whatsapp", business_number=settings.WHATSAPP_BUSINESS_NUMBER,
                          external_id=external_id)
