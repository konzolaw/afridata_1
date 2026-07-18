"""
Tests for recommendations/services.py — the orchestration entry point that
wires candidate generation and hybrid scoring together.

This suite exists to prove the fix for the crash chain traced through
domain/schemas.py, domain/engines/hybrid.py, and
domain/engines/candidate_generation.py:

  - CandidateSet previously had `item_ids` while candidate_generation.py
    built it with `candidate_ids` (TypeError on construction) and
    hybrid.py read `.candidate_ids` (AttributeError on read).
  - Two incompatible EngineConfig classes existed (schemas.py vs
    hybrid.py); candidate_generation.py's apply_popularity_filter /
    apply_recency_filter flags existed on neither.

CollaborativeEngine and ContentBasedEngine are mocked — this suite proves
the wiring/data-flow is correct, not ML scoring quality (which needs real
trained models and is a separate concern).
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from recommendations import services
from recommendations.domain.schemas import RankedList
from recommendations.models import DatasetProxy, InteractionType, UserInteraction

User = get_user_model()


class GetRecommendationsForUserTests(TestCase):
    def setUp(self):
        # Engines are cached as module-level singletons; make sure each
        # test starts from a clean slate regardless of test order.
        services._cf_engine = None
        services._cbf_engine = None
        services._hybrid_engine = None

        self.user = User.objects.create_user(
            username="svc_user", email="svc_user@example.com", password="x"
        )
        DatasetProxy.objects.create(
            id=1, dataset_id=1, title="Dataset One", is_active=True, interaction_count=50
        )
        DatasetProxy.objects.create(
            id=2, dataset_id=2, title="Dataset Two", is_active=True, interaction_count=30
        )

    def tearDown(self):
        services._cf_engine = None
        services._cbf_engine = None
        services._hybrid_engine = None

    @patch("recommendations.services.ContentBasedEngine")
    @patch("recommendations.services.CollaborativeEngine")
    def test_cold_start_user_does_not_crash_and_falls_back_to_cbf(self, MockCF, MockCBF):
        """
        A user with zero interactions is exactly the scenario that used to
        raise TypeError before the fix (CandidateSet/EngineConfig mismatch).
        """
        mock_cf = MockCF.return_value
        mock_cf.is_loaded = True
        mock_cf.score_for_user.return_value = {1: 0.0, 2: 0.0}
        mock_cf.is_cold_start.return_value = True

        mock_cbf = MockCBF.return_value
        mock_cbf.is_loaded = True
        mock_cbf.score_for_user.return_value = {1: 0.8, 2: 0.4}

        result = services.get_recommendations_for_user(user_id=self.user.pk)

        self.assertIsInstance(result, RankedList)
        self.assertFalse(result.is_empty)
        # auto_cold_start must have forced alpha to 0.0 (pure content-based).
        self.assertEqual(result.alpha, 0.0)
        # Highest CBF/popularity score ranked first.
        self.assertEqual(result.items[0].item_id, 1)

    @patch("recommendations.tasks.refresh_user_scores.delay")
    @patch("recommendations.services.ContentBasedEngine")
    @patch("recommendations.services.CollaborativeEngine")
    def test_warm_user_blends_cf_and_cbf(self, MockCF, MockCBF, mock_task_delay):
        # Saving a UserInteraction fires post_save -> signals.py, which
        # enqueues tasks.refresh_user_scores.delay(). That's unrelated to
        # what this test exercises, so it's mocked out rather than trying
        # to reach a real Celery broker.
        UserInteraction.objects.create(
            user=self.user, dataset_id=1, interaction_type=InteractionType.DOWNLOAD
        )

        mock_cf = MockCF.return_value
        mock_cf.is_loaded = True
        mock_cf.score_for_user.return_value = {2: 0.9}
        mock_cf.is_cold_start.return_value = False

        mock_cbf = MockCBF.return_value
        mock_cbf.is_loaded = True
        mock_cbf.score_for_user.return_value = {2: 0.1}

        result = services.get_recommendations_for_user(user_id=self.user.pk, alpha=0.5)

        self.assertEqual(result.alpha, 0.5)
        self.assertFalse(result.is_empty)

    @patch("recommendations.services.ContentBasedEngine")
    @patch("recommendations.services.CollaborativeEngine")
    def test_engines_are_loaded_once_and_reused(self, MockCF, MockCBF):
        MockCF.return_value.is_loaded = True
        MockCF.return_value.score_for_user.return_value = {}
        MockCF.return_value.is_cold_start.return_value = True
        MockCBF.return_value.is_loaded = True
        MockCBF.return_value.score_for_user.return_value = {}

        services.get_recommendations_for_user(user_id=self.user.pk)
        services.get_recommendations_for_user(user_id=self.user.pk)

        MockCF.return_value.load.assert_called_once()
        MockCBF.return_value.load.assert_called_once()
