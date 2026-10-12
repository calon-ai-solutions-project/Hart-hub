from rest_framework import serializers

from ..models import SyncLog, SyncRun
from ..platforms import PLATFORMS


class StartRunSerializer(serializers.Serializer):
    session_ok = serializers.BooleanField()


class RunUrlSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    outcome = serializers.ChoiceField(choices=[
        SyncLog.Outcome.CAPTURED, SyncLog.Outcome.SKIPPED, SyncLog.Outcome.STOPPED, SyncLog.Outcome.FAILED])
    http_status = serializers.IntegerField(required=False, allow_null=True, min_value=100, max_value=599)
    detail = serializers.CharField(required=False, allow_blank=True, max_length=255)
    record = serializers.DictField(required=False)

    def validate(self, data):
        if data["outcome"] == SyncLog.Outcome.CAPTURED and not data.get("record"):
            raise serializers.ValidationError({"record": "A captured listing needs its record."})
        return data


class PhotoUploadSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    position = serializers.IntegerField(min_value=1, max_value=200)
    file = serializers.FileField()


class ScrapedListingSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=list(PLATFORMS))
    record = serializers.DictField(allow_empty=False)


class ScrapedPhotoSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=list(PLATFORMS))
    external_id = serializers.CharField(max_length=64)
    position = serializers.IntegerField(min_value=1, max_value=200)
    file = serializers.FileField()


class FinishRunSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[
        SyncRun.Status.COMPLETED, SyncRun.Status.STOPPED_BY_PLATFORM, SyncRun.Status.FAILED])
    stop_reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AlertInboundSerializer(serializers.Serializer):
    """Tolerant of the field names different inbound-email providers use."""

    platform = serializers.ChoiceField(choices=list(PLATFORMS), required=False)
    sender = serializers.CharField(required=False, allow_blank=True)
    subject = serializers.CharField(required=False, allow_blank=True)
    raw = serializers.CharField()

    SENDER_KEYS = ("sender", "from", "From")
    SUBJECT_KEYS = ("subject", "Subject")
    BODY_KEYS = ("raw", "html", "body-html", "HtmlBody", "text", "body-plain", "TextBody")

    def to_internal_value(self, data):
        def pick(keys):
            return next((data[k] for k in keys if data.get(k)), "")

        body = "\n".join(str(data[k]) for k in self.BODY_KEYS if data.get(k))
        mapped = {"sender": str(pick(self.SENDER_KEYS)), "subject": str(pick(self.SUBJECT_KEYS)), "raw": body}
        if data.get("platform"):
            mapped["platform"] = data["platform"]
        return super().to_internal_value(mapped)
