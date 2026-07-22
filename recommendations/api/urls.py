"""
URL configuration for the recommendations API.

The recommendations API provides personalized dataset recommendations
for authenticated users. All routes are prefixed with /api/recommendations/
(as configured in the main afridata/urls.py).

Route map:
  GET  /api/recommendations/          → RecommendationListView
    Returns Top-N recommended datasets for the authenticated user.

  POST /api/recommendations/feedback/ → FeedbackView
    Records explicit user feedback (rating, thumbs up/down).

app_name = 'recommendations'  (for use with reverse())
"""

from django.urls import path
from .views import RecommendationListView, FeedbackView

app_name = 'recommendations'

urlpatterns = [
    path('', RecommendationListView.as_view(), name='list'),
    path('feedback/', FeedbackView.as_view(), name='feedback'),
]