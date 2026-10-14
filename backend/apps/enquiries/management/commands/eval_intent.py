import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.enquiries.services import classify

EVAL_FILE = Path(classify.PROMPT_FILE).with_name("intent_v1_eval.json")


class Command(BaseCommand):
    help = ("Run the first-message classifier over its example set and report how many it gets right. "
            "Uses the real AI model when OPENROUTER_* is set (one small call per example).")

    def handle(self, *args, **options):
        examples = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
        right, risky = 0, []
        for example in examples:
            intent, confidence, how = classify.classify(example["text"])
            ok = intent == example["intent"]
            right += ok
            # the costly mistake: replying to someone the Hub should have left alone
            if intent in ("car_enquiry", "finance") and example["intent"] not in ("car_enquiry", "finance"):
                risky.append(example["text"])
            mark = "ok " if ok else "BAD"
            self.stdout.write(f"{mark} {example['intent']:15} -> {intent:15} {confidence:.2f} {how:5} {example['text'][:60]}")
        self.stdout.write(self.style.SUCCESS(f"{right}/{len(examples)} right ({classify.PROMPT_VERSION})"))
        if risky:
            self.stdout.write(self.style.ERROR(f"Would wrongly reply to {len(risky)}: {risky}"))
