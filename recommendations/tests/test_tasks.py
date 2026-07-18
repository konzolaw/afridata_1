"""
Tests for recommendations/tasks.py::refresh_user_scores.

Proves the fix for two crashes that made this Celery task fail before it
ever wrote anything to cache:

  1. `HybridEngine()` called with zero constructor args (it actually
     requires collaborative_engine + content_based_engine) followed by
     `.recommend(user_id=user_id)` — a method signature that doesn't
     exist. Fixed by delegating to services.get_recommendations_for_user().
  2. `set_cached_recommendations(user_id=..., recommendations=...)` used a
     kwarg name (`recommendations`) that doesn't match the real signature
     (`ranked_list`). Fixed directly.

This task has zero prior test coverage — that's exactly why the bug
shipped unnoticed.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from recommendations import tasks
from recommendations.domain.schemas import RankedList, ScoredCandidate

User = get_user_model()


class RefreshUserScoresTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="task_user", email="task_user@example.com", password="x"
        )

    @patch("recommendations.tasks.set_cached_recommendations")
    @patch("recommendations.tasks.get_recommendations_for_user")
    def test_refresh_user_scores_computes_and_caches(self, mock_get_recs, mock_set_cache):
        ranked_list = RankedList(
            user_id=self.user.pk,
            items=[ScoredCandidate(item_id=1, s_cf=0.0, s_cbf=0.8, s_hybrid=0.8)],
            engine_used="content_based",
            alpha=0.0,
        )
        mock_get_recs.return_value = ranked_list

        # Direct call (no .delay()) — this is how the task actually runs
        # under a bound @shared_task; no exception should propagate.
        tasks.refresh_user_scores(user_id=self.user.pk)

        mock_get_recs.assert_called_once_with(user_id=self.user.pk)
        mock_set_cache.assert_called_once_with(user_id=self.user.pk, ranked_list=ranked_list)

    @patch("recommendations.tasks.set_cached_recommendations")
    @patch("recommendations.tasks.get_recommendations_for_user")
    def test_exception_from_service_propagates_for_celery_retry(
        self, mock_get_recs, mock_set_cache
    ):
        mock_get_recs.side_effect = RuntimeError("model not trained yet")

        with self.assertRaises(RuntimeError):
            tasks.refresh_user_scores(user_id=self.user.pk)

        mock_set_cache.assert_not_called()
