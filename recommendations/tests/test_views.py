"""
Tests for RecommendationListView (GET /api/recommendations/).

Proves the fix for the crash chain confirmed live against a running dev
server (curl -> HTTP 500, TypeError: WeightedHybridEngine.__init__() got
an unexpected keyword argument 'user'):

  - The view used to call `HybridEngine(user=user)` (TypeError — no such
    kwarg on the real WeightedHybridEngine.__init__) followed by a
    `.get_recommendations()` method that doesn't exist at all. Fixed by
    delegating to services.get_recommendations_for_user().
  - The serializer expects {recommendations: [...], alpha, top_n,
    generated_at} but RankedList only exposes `.items` (ScoredCandidate,
    no title/rank). Fixed with the _to_api_shape() adapter in views.py.

Also proves the URL routing fix: /api/recommendations/ previously 404'd
because the include()'d urls.py declared its own redundant
'recommendations/' path segment on top of the outer include prefix.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from recommendations.domain.schemas import RankedList, ScoredCandidate
from recommendations.models import DatasetProxy

User = get_user_model()

RECOMMENDATIONS_URL = "/api/recommendations/"


class RecommendationListViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="view_user", email="view_user@example.com", password="x"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        DatasetProxy.objects.create(
            id=1, dataset_id=1, title="Dataset One", is_active=True
        )

    def test_url_resolves_at_the_documented_path(self):
        """
        Regression test for the routing bug: this used to 404 because the
        view's own urls.py duplicated the 'recommendations/' segment
        already applied by the outer include() prefix.
        """
        anon_client = APIClient()
        response = anon_client.get(RECOMMENDATIONS_URL)
        # 403 (permission denied), not 404 (route doesn't exist) — proves
        # the URL is wired up; auth is a separate, expected concern.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("recommendations.api.views.get_cached_recommendations", return_value=None)
    @patch("recommendations.api.views.get_recommendations_for_user")
    def test_cache_miss_computes_live_and_returns_200(self, mock_get_recs, mock_get_cache):
        mock_get_recs.return_value = RankedList(
            user_id=self.user.pk,
            items=[ScoredCandidate(item_id=1, s_cf=0.0, s_cbf=0.8, s_hybrid=0.8)],
            engine_used="content_based",
            alpha=0.0,
        )

        response = self.client.get(RECOMMENDATIONS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["recommendations"]), 1)
        rec = response.data["recommendations"][0]
        self.assertEqual(rec["dataset_id"], "1")
        self.assertEqual(rec["title"], "Dataset One")
        self.assertEqual(rec["rank"], 1)
        self.assertEqual(rec["s_hybrid"], 0.8)
        mock_get_recs.assert_called_once_with(user_id=self.user.pk)

    @patch("recommendations.api.views.get_recommendations_for_user")
    @patch("recommendations.api.views.get_cached_recommendations")
    def test_cache_hit_skips_live_computation(self, mock_get_cache, mock_get_recs):
        mock_get_cache.return_value = RankedList(
            user_id=self.user.pk,
            items=[ScoredCandidate(item_id=1, s_cf=0.5, s_cbf=0.5, s_hybrid=0.5)],
        )

        response = self.client.get(RECOMMENDATIONS_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_recs.assert_not_called()
