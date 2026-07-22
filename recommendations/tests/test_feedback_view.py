"""
Tests for FeedbackView (POST /api/recommendations/feedback/).

Proves the fix for a real bug surfaced via live Postman testing:
FeedbackSerializer declared a `rating` field with no `source=`, so
ModelSerializer.create() tried UserInteraction.objects.create(rating=...)
— but the model field is `explicit_rating`, not `rating`. Every POST with
a rating crashed with TypeError before ever reaching this fix.

tasks.refresh_user_scores.delay() (fired via signals.py on UserInteraction
save) is mocked out: dispatching it for real requires a running Celery
broker, which is an infrastructure dependency unrelated to what this test
verifies.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from recommendations.models import UserInteraction

User = get_user_model()

FEEDBACK_URL = "/api/recommendations/feedback/"


class FeedbackViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="feedback_user", email="feedback_user@example.com", password="x"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("recommendations.tasks.refresh_user_scores.delay")
    def test_feedback_with_rating_is_saved(self, mock_task_delay):
        response = self.client.post(
            FEEDBACK_URL,
            {"dataset_id": "1", "interaction_type": "download", "rating": 4},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        interaction = UserInteraction.objects.get(user=self.user, dataset_id=1)
        self.assertEqual(interaction.explicit_rating, 4)
        self.assertEqual(interaction.interaction_type, "download")

    @patch("recommendations.tasks.refresh_user_scores.delay")
    def test_feedback_without_rating_is_saved(self, mock_task_delay):
        response = self.client.post(
            FEEDBACK_URL,
            {"dataset_id": "2", "interaction_type": "view"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        interaction = UserInteraction.objects.get(user=self.user, dataset_id=2)
        self.assertIsNone(interaction.explicit_rating)

    @patch("recommendations.tasks.refresh_user_scores.delay")
    def test_rating_out_of_range_is_rejected(self, mock_task_delay):
        response = self.client.post(
            FEEDBACK_URL,
            {"dataset_id": "3", "interaction_type": "download", "rating": 9},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonymous_request_is_rejected(self):
        anon_client = APIClient()
        response = anon_client.post(
            FEEDBACK_URL,
            {"dataset_id": "1", "interaction_type": "download"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
