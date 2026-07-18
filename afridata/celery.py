"""
Celery application for the afridata project.

Without this file, @shared_task decorators in tasks.py (e.g.
recommendations/tasks.py) bind to Celery's bare default app instead of
this Django project's configuration, so CELERY_* settings in settings.py
are silently ignored and the broker URL can't be overridden.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "afridata.settings")

app = Celery("afridata")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
