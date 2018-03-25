"""Celery application.

Workers are started with ``celery -A config worker`` and the beat scheduler with
``celery -A config beat``. All task configuration lives in Django settings under
the ``CELERY_`` namespace.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("eventhub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
