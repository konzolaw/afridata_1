"""
API views for the recommendations app.

Provides RESTful endpoints to retrieve personalised recommendations
and submit explicit user feedback. Uses DRF GenericAPIView.

Endpoints (registered in api/urls.py):
  GET  /api/recommendations/
    Returns Top-N recommended datasets for the authenticated user.
    Reads from cache first; falls back to a live recommendation-service call.

  POST /api/recommendations/feedback/
    Records explicit user feedback (rating, thumbs up/down) as a
    UserInteraction, which triggers cache invalidation via signals.

Views contain no scoring or ranking logic.
All recommendation computation is delegated to the domain layer; this
module only translates the resulting RankedList into the API's JSON shape.
"""

from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from recommendations.infrastructure.cache import get_cached_recommendations
from recommendations.models import DatasetProxy
from recommendations.services import get_recommendations_for_user
from .serializers import RecommendationListSerializer, FeedbackSerializer


def _to_api_shape(ranked_list) -> dict:
    """
    Translate a domain RankedList into the dict shape RecommendationListSerializer
    expects: {recommendations: [{dataset_id, title, rank, s_hybrid}, ...], alpha, top_n, generated_at}.

    RankedList.items only carries item_id/s_cf/s_cbf/s_hybrid — titles are
    looked up here in a single bulk query keyed by DatasetProxy.id, which is
    the same id space candidate generation uses for item_id.
    """
    item_ids = [item.item_id for item in ranked_list.items]
    titles = dict(DatasetProxy.objects.filter(id__in=item_ids).values_list("id", "title"))

    return {
        "recommendations": [
            {
                "dataset_id": str(item.item_id),
                "title": titles.get(item.item_id, ""),
                "rank": rank,
                "s_hybrid": item.s_hybrid,
            }
            for rank, item in enumerate(ranked_list.items, start=1)
        ],
        "alpha": ranked_list.alpha,
        "top_n": ranked_list.top_n,
        "generated_at": ranked_list.generated_at,
    }


class RecommendationListView(ListAPIView):
    """
    GET /api/recommendations/

    Returns Top-N personalised recommended datasets for the authenticated user.

    Strategy:
      1. Check the cache for a pre-computed ranked list.
      2. On a cache miss, delegate to the recommendation service for a live
         computation. For large/expensive requests this should be enqueued
         as a Celery task; the synchronous fallback here is intentionally
         lightweight.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = RecommendationListSerializer

    def list(self, request, *args, **kwargs):
        user = request.user

        ranked_list = get_cached_recommendations(user_id=user.pk)

        if ranked_list is None:
            ranked_list = get_recommendations_for_user(user_id=user.pk)

        serializer = self.get_serializer(_to_api_shape(ranked_list))
        return Response(serializer.data, status=status.HTTP_200_OK)


class FeedbackView(CreateAPIView):
    """
    POST /api/recommendations/feedback/

    Records explicit user feedback (rating or thumbs up/down) as a
    UserInteraction. Saving the interaction triggers cache invalidation
    via Django signals — no manual invalidation is needed here.

    Returns 201 on success with the serialised interaction payload.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = FeedbackSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)