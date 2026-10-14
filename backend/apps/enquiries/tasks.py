from celery import shared_task

from .services import engine


@shared_task(name="enquiries.prepare_options")
def prepare_options(enquiry_id):
    engine.prepare_options(enquiry_id)
