# home/views.py
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db.models import Q, Sum, Avg, Count
from django.utils import timezone
from datetime import timedelta
from dataset.models import Dataset
from django.http import HttpResponse
import json
from django.contrib.auth.decorators import login_required
from collections import Counter
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib import messages
from .forms import ContactForm
from django.core.mail import send_mail
from django.conf import settings
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

def get_recommended_datasets(request):
    """
    Get recommended datasets for display on homepage.
    For logged-in users: personalized recommendations (with cold-start fallback)
    For anonymous users: public recommendations (Discover mode)
    """
    recommended = []
    recommended_source = "discover"  # For template context
    
    # "Discover" fallback for cold start or anonymous users
    # Focuses on high ratings and recency rather than pure downloads (which is Trending)
    def get_discover_datasets():
        return Dataset.objects.select_related('author').order_by(
            '-rating', '-created_at', '-views'
        )[:10]
    
    if request.user.is_authenticated:
        try:
            # Try to get recommendations for the user
            from recommendations.models import RecommendationResult
            from recommendations.infrastructure.cache import get_cached_recommendations
            
            # Try cache first
            recommendations = get_cached_recommendations(user_id=request.user.pk)
            
            if recommendations and len(recommendations.items) > 0:
                # User has recommendations
                dataset_ids = [item.item_id for item in recommendations.items][:10]
                from django.db.models import Case, When
                preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(dataset_ids)])
                recommended = Dataset.objects.filter(id__in=dataset_ids).select_related('author').order_by(preserved_order)
                recommended_source = "personalized"
                logger.info(f"Recommendations found for user {request.user.pk}")
            else:
                # Cold start: User is new or has no interactions
                # Fall back to Discover mode
                recommended = get_discover_datasets()
                recommended_source = "warm_start"
                logger.info(f"Cold start fallback for user {request.user.pk} - showing discover datasets")
                
        except ImportError:
            # Recommendations module not fully initialized
            logger.warning("Recommendations module not available, using discover datasets")
            recommended = get_discover_datasets()
            recommended_source = "discover"
        except Exception as e:
            # Any error in recommendations, fall back gracefully
            logger.error(f"Error fetching recommendations for user {request.user.pk}: {e}")
            recommended = get_discover_datasets()
            recommended_source = "discover"
    else:
        # Anonymous user: show public recommendations (Discover mode)
        recommended = get_discover_datasets()
        recommended_source = "public"
    
    return recommended, recommended_source

def default_home(request):
    """
    Enhanced default homepage view with dynamic data.
    Accessible to all users (no login required).
    For authenticated users: shows personalized recommendations.
    For anonymous users: shows popular/trending datasets.
    """
    if request.user.is_authenticated:
        return redirect('home')

    # Get overall statistics
    stats = Dataset.objects.aggregate(
        total_datasets=Count('id'),
        total_downloads=Sum('downloads'),
        total_views=Sum('views'),
        avg_rating=Avg('rating')
    )
    
    # Calculate total countries (assuming you store country info in topics or bio)
    # This is a simplified approach - you might want to add a country field to your model
    datasets_with_countries = Dataset.objects.filter(
        Q(topics__icontains='Nigeria') | Q(topics__icontains='Kenya') |  # type: ignore
        Q(topics__icontains='South Africa') | Q(topics__icontains='Ghana') |  # type: ignore
        Q(topics__icontains='Egypt') | Q(topics__icontains='Ethiopia') |  # type: ignore
        Q(topics__icontains='Uganda') | Q(topics__icontains='Tanzania') |  # type: ignore
        Q(bio__icontains='Nigeria') | Q(bio__icontains='Kenya') |  # type: ignore
        Q(bio__icontains='South Africa') | Q(bio__icontains='Ghana')  # type: ignore
    ).distinct()
    
    total_countries = 54  # Default African countries count
    total_researchers = User.objects.count()
    
    # Get trending datasets (most viewed/downloaded recently)
    one_week_ago = timezone.now() - timedelta(days=7)
    trending_datasets = Dataset.objects.select_related('author').annotate(
        popularity=Count('views') + Count('downloads')
    ).order_by('-views', '-downloads')[:3]
    
    # Get popular topics from all datasets
    all_datasets = Dataset.objects.all()
    topic_counter = Counter()
    
    for dataset in all_datasets:
        topics = dataset.get_topics_list()
        for topic in topics[:3]:  # Take first 3 topics from each dataset
            clean_topic = topic.strip().title()
            if len(clean_topic) > 3:  # Filter out very short topics
                topic_counter[clean_topic] += 1
    
    # Get top 5 topics
    top_topics = topic_counter.most_common(5)
    
    # If we don't have enough topics, add some defaults
    default_topics = [
        ('Climate Change', 150), ('Healthcare', 120), ('Economics', 98), 
        ('Agriculture', 87), ('Education', 76)
    ]
    
    if len(top_topics) < 4:
        top_topics.extend(default_topics)
    
    # Get recommended datasets with recommendations for logged-in users and discover for anonymous
    recommended_datasets, recommended_source = get_recommended_datasets(request)
    
    # Get popular search terms (simplified - you might want to track actual searches)
    popular_terms = []
    if all_datasets.exists():
        # Extract some terms from dataset titles and topics
        for dataset in all_datasets[:20]:
            words = dataset.title.split()
            topics = dataset.get_topics_list()
            
            # Add relevant words from titles
            for word in words:
                if len(word) > 4 and word.lower() not in ['data', 'dataset', 'analysis']:
                    popular_terms.append(word.title())
            
            # Add topics
            for topic in topics[:2]:
                if len(topic.strip()) > 3:
                    popular_terms.append(topic.strip().title())
    
    # Remove duplicates and get top 5
    popular_terms = list(set(popular_terms))[:5]
    
    # Default terms if not enough data
    if len(popular_terms) < 5:
        default_terms = ['Nigeria GDP', 'Kenya Agriculture', 'South Africa Mining', 
                        'Egypt Tourism', 'Ethiopia Demographics']
        popular_terms.extend(default_terms)
    
    context = {
        # Statistics
        'total_datasets': stats['total_datasets'] or 0,
        'total_countries': total_countries,
        'total_downloads': stats['total_downloads'] or 0,
        'total_researchers': total_researchers,
        
        # Trending datasets
        'trending_datasets': trending_datasets,
        
        # Popular topics with search counts (simulated)
        'topic_1': top_topics[0][0] if len(top_topics) > 0 else 'Climate Change',
        'topic_1_searches': f"{top_topics[0][1] * 100:.1f}K" if len(top_topics) > 0 else '15.2K',
        'topic_2': top_topics[1][0] if len(top_topics) > 1 else 'Healthcare',
        'topic_2_searches': f"{top_topics[1][1] * 80:.1f}K" if len(top_topics) > 1 else '12.8K',
        'topic_3': top_topics[2][0] if len(top_topics) > 2 else 'Economics',
        'topic_3_searches': f"{top_topics[2][1] * 60:.1f}K" if len(top_topics) > 2 else '9.4K',
        'topic_4': top_topics[3][0] if len(top_topics) > 3 else 'Agriculture',
        'topic_4_searches': f"{top_topics[3][1] * 40:.1f}K" if len(top_topics) > 3 else '7.9K',
        
        # Popular search terms
        'term_1': popular_terms[0] if len(popular_terms) > 0 else 'Nigeria GDP',
        'term_2': popular_terms[1] if len(popular_terms) > 1 else 'Kenya Agriculture',
        'term_3': popular_terms[2] if len(popular_terms) > 2 else 'South Africa Mining',
        'term_4': popular_terms[3] if len(popular_terms) > 3 else 'Egypt Tourism',
        'term_5': popular_terms[4] if len(popular_terms) > 4 else 'Ethiopia Demographics',
        
        # Recommended datasets
        'recommended_datasets': recommended_datasets,
        'recommended_source': recommended_source,
        
        # Category counts (you might want to add categories to your model)
        'category_counts': {
            'healthcare': Dataset.objects.filter(
                Q(topics__icontains='health') | Q(bio__icontains='health') |  # type: ignore
                Q(topics__icontains='medical') | Q(bio__icontains='medical')  # type: ignore
            ).count(),
            'climate': Dataset.objects.filter(
                Q(topics__icontains='climate') | Q(bio__icontains='climate') |  # type: ignore
                Q(topics__icontains='environment') | Q(bio__icontains='environment')  # type: ignore
            ).count(),
            'economics': Dataset.objects.filter(
                Q(topics__icontains='economic') | Q(bio__icontains='economic') |  # type: ignore
                Q(topics__icontains='finance') | Q(bio__icontains='finance') |  # type: ignore
                Q(topics__icontains='gdp') | Q(bio__icontains='gdp')  # type: ignore
            ).count(),
            'social': Dataset.objects.filter(
                Q(topics__icontains='social') | Q(bio__icontains='social') |  # type: ignore
                Q(topics__icontains='demographic') | Q(bio__icontains='demographic')  # type: ignore
            ).count(),
            'agriculture': Dataset.objects.filter(
                Q(topics__icontains='agriculture') | Q(bio__icontains='agriculture') |  # type: ignore
                Q(topics__icontains='farming') | Q(bio__icontains='farming')  # type: ignore
            ).count(),
            'education': Dataset.objects.filter(
                Q(topics__icontains='education') | Q(bio__icontains='education') |  # type: ignore
                Q(topics__icontains='school') | Q(bio__icontains='school')  # type: ignore
            ).count(),
            'technology': Dataset.objects.filter(
                Q(topics__icontains='technology') | Q(bio__icontains='technology') |  # type: ignore
                Q(topics__icontains='tech') | Q(bio__icontains='tech')  # type: ignore
            ).count(),
        },
        
        # File format counts
        'format_counts': {
            'csv': Dataset.objects.filter(dataset_type='csv').count(),
            'excel': Dataset.objects.filter(dataset_type='excel').count(),
        }
    }
    
    return render(request, 'home/index.html', context)


# Keep all your existing API functions as they are
def search_datasets(request):
    """
    Search datasets based on user query.
    Searches in title, bio, topics, and author username.
    """
    query = request.GET.get('q', '').strip()
    
    if not query:
        return JsonResponse({
            'success': False,
            'message': 'Search query is required',
            'datasets': []
        })
    
    # Search across multiple fields
    # Use select_related and limit results to prevent DB overwhelm during concurrent searches
    datasets = Dataset.objects.filter(
        Q(title__icontains=query) |  # type: ignore
        Q(bio__icontains=query) |  # type: ignore
        Q(topics__icontains=query) |  # type: ignore
        Q(author__username__icontains=query)
    ).select_related('author').order_by('-created_at')[:20]
    
    # Format results
    results = []
    for dataset in datasets:
        # Get first 30 words of bio
        bio_words = dataset.bio.split()[:30]
        short_bio = ' '.join(bio_words) + ('...' if len(dataset.bio.split()) > 30 else '')
        
        results.append({
            'id': dataset.id,
            'slug': dataset.slug,
            'title': dataset.title,

            'author': dataset.author.username,
            'short_bio': short_bio,
            'dataset_type': dataset.get_dataset_type_display(),
            'views': dataset.views,
            'downloads': dataset.downloads,
            'rating': dataset.rating,
            'created_at': dataset.created_at.strftime('%Y-%m-%d'),
            'topics': dataset.get_topics_list()
        })
    
    return JsonResponse({
        'success': True,
        'count': len(results),
        'datasets': results
    })


def global_search(request):
    """
    Global platform search API.
    Searches across Datasets and Organizations (Users).
    Returns grouped results for the global search dropdown.
    """
    query = request.GET.get('q', '').strip()
    
    if not query:
        return JsonResponse({
            'success': True,
            'results': {
                'datasets': [],
                'organizations': [],
                'resources': [],
                'standards': []
            }
        })
    
    # 1. Search Datasets (Relevance ordered: Exact title > partial title > keywords/bio)
    from django.db.models import Case, When, IntegerField, Value
    
    datasets = Dataset.objects.annotate(
        relevance=Case(
            When(title__iexact=query, then=Value(100)),
            When(title__icontains=query, then=Value(80)),
            When(topics__icontains=query, then=Value(60)),
            When(bio__icontains=query, then=Value(40)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).filter(
        Q(title__icontains=query) |  # type: ignore
        Q(bio__icontains=query) |  # type: ignore
        Q(topics__icontains=query) |  # type: ignore
        Q(author__username__icontains=query)
    ).select_related('author').order_by('-relevance', '-downloads')[:5]

    dataset_results = []
    for d in datasets:
        dataset_results.append({
            'id': d.id,
            'title': d.title,
            'url': f'/dataset/{d.slug}/',
            'type': d.get_dataset_type_display(),
            'subtitle': f"By {d.author.get_full_name() or d.author.username}"
        })

    # 2. Search Organizations (Users with organization field)
    User = get_user_model()
    org_users = User.objects.filter(
        Q(profile__organization__icontains=query) |  # type: ignore
        Q(username__icontains=query) |  # type: ignore
        Q(full_name__icontains=query)
    ).select_related('profile').distinct()[:3]
    
    org_results = []
    for u in org_users:
        org_name = u.profile.organization if hasattr(u, 'profile') and u.profile.organization else (u.get_full_name() or u.username)
        org_results.append({
            'id': u.id,
            'title': org_name,
            'url': f'/user/{u.username}/', # Or wherever user profiles are
            'subtitle': 'Organization / User'
        })

    # 3. Resources & Standards (Empty for now)
    resource_results = []
    standard_results = []

    return JsonResponse({
        'success': True,
        'results': {
            'datasets': dataset_results,
            'organizations': org_results,
            'resources': resource_results,
            'standards': standard_results
        }
    })


def trending_datasets(request):
    """
    Fetch most viewed or downloaded datasets in the past hour.
    Returns at least 7 datasets with their key attributes.
    """
    # Calculate time one hour ago
    one_hour_ago = timezone.now() - timedelta(hours=1)
    
    # Get datasets updated in the past hour, ordered by views + downloads
    trending = Dataset.objects.filter(
        updated_at__gte=one_hour_ago
    ).select_related('author').extra(
        select={'popularity': 'views + downloads'}
    ).order_by('-popularity', '-views', '-downloads')
    
    # If we don't have enough from the past hour, get top datasets overall
    if trending.count() < 7:
        trending = Dataset.objects.select_related('author').extra(
            select={'popularity': 'views + downloads'}
        ).order_by('-popularity', '-views', '-downloads')
    
    # Take at least 7 datasets
    trending = trending[:max(7, trending.count())]
    
    results = []
    for dataset in trending:
        # Get first 30 words of bio
        bio_words = dataset.bio.split()[:30]
        short_bio = ' '.join(bio_words) + ('...' if len(dataset.bio.split()) > 30 else '')
        
        results.append({
            'id': dataset.id,
            'slug': dataset.slug,
            'title': dataset.title,

            'author': dataset.author.username,
            'short_bio': short_bio,
            'dataset_type': dataset.get_dataset_type_display(),
            'views': dataset.views,
            'downloads': dataset.downloads,
            'rating': dataset.rating,
            'created_at': dataset.created_at.strftime('%Y-%m-%d'),
            'popularity_score': dataset.views + dataset.downloads
        })
    
    return JsonResponse({
        'success': True,
        'count': len(results),
        'datasets': results,
        'timeframe': 'past_hour_or_trending'
    })


def filter_datasets(request):
    """
    Filter datasets based on criteria: most_downloaded, most_recent, 
    highest_rating, or most_relevant.
    Returns at least 15 datasets with detailed attributes.
    """
    filter_type = request.GET.get('filter', 'most_recent').lower()
    limit = max(15, int(request.GET.get('limit', 15)))
    
    # Base queryset
    datasets = Dataset.objects.select_related('author')
    
    # Apply filtering based on type
    if filter_type == 'most_downloaded':
        datasets = datasets.order_by('-downloads', '-views')
    elif filter_type == 'most_recent':
        datasets = datasets.order_by('-created_at', '-updated_at')
    elif filter_type == 'highest_rating':
        datasets = datasets.order_by('-rating', '-views', '-downloads')
    elif filter_type == 'most_relevant':
        # Most relevant = combination of rating, views, downloads, and recency
        datasets = datasets.extra(
            select={
                'relevance_score': '''
                    (rating * 0.3) + 
                    (LEAST(views, 1000) * 0.0003) + 
                    (LEAST(downloads, 1000) * 0.0005) + 
                    (CASE 
                        WHEN created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 0.2
                        WHEN created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY) THEN 0.1
                        ELSE 0 
                    END)
                '''
            }
        ).order_by('-relevance_score', '-rating', '-views')
    else:
        # Default to most recent
        datasets = datasets.order_by('-created_at')
    
    # Limit results
    datasets = datasets[:limit]
    
    results = []
    for dataset in datasets:
        # Get first 60 words of bio
        bio_words = dataset.bio.split()[:60]
        bio_excerpt = ' '.join(bio_words) + ('...' if len(dataset.bio.split()) > 60 else '')
        
        result = {
            'id': dataset.id,
            'slug': dataset.slug,
            'title': dataset.title,

            'author': dataset.author.username,
            'bio': bio_excerpt,
            'dataset_type': dataset.get_dataset_type_display(),
            'type_code': dataset.dataset_type,
            'downloads': dataset.downloads,
            'views': dataset.views,
            'rating': dataset.rating,
            'created_at': dataset.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': dataset.updated_at.strftime('%Y-%m-%d %H:%M'),
            'topics': dataset.get_topics_list(),
            'file_url': dataset.file.url if dataset.file else None
        }
        
        # Add relevance score if it was calculated
        if filter_type == 'most_relevant' and hasattr(dataset, 'relevance_score'):
            result['relevance_score'] = round(dataset.relevance_score, 2)
        
        results.append(result)
    
    return JsonResponse({
        'success': True,
        'filter_type': filter_type,
        'count': len(results),
        'datasets': results
    })


def dataset_stats(request):
    """
    Get overall dataset statistics for the homepage.
    """
    from django.db.models import Sum, Avg, Count
    
    stats = Dataset.objects.aggregate(
        total_datasets=Count('id'),
        total_downloads=Sum('downloads'),
        total_views=Sum('views'),
        avg_rating=Avg('rating')
    )
    
    # Get recent activity (datasets created in last 7 days)
    week_ago = timezone.now() - timedelta(days=7)
    recent_count = Dataset.objects.filter(created_at__gte=week_ago).count()
    
    return JsonResponse({
        'success': True,
        'stats': {
            'total_datasets': stats['total_datasets'] or 0,
            'total_downloads': stats['total_downloads'] or 0,
            'total_views': stats['total_views'] or 0,
            'average_rating': round(stats['avg_rating'] or 0, 2),
            'recent_datasets': recent_count
        }
    })


def api_docs(request):
    """API documentation page"""
    return render(request, 'home/api_docs.html')


def quick_search_suggestions(request):
    """
    Get quick search suggestions based on popular topics and datasets
    """
    # Get top topics from datasets
    datasets = Dataset.objects.all()[:100]  # Limit for performance
    topic_counter = Counter()
    
    for dataset in datasets:
        topics = dataset.get_topics_list()
        for topic in topics:
            topic_counter[topic.strip().title()] += 1
    
    # Get most common topics
    suggestions = [topic for topic, count in topic_counter.most_common(10)]
    
    # Add some default suggestions if not enough data
    default_suggestions = [
        'Nigeria Economy', 'Kenya Healthcare', 'South Africa Mining',
        'Ghana Agriculture', 'Egypt Demographics', 'Ethiopia Climate'
    ]
    
    if len(suggestions) < 6:
        suggestions.extend(default_suggestions)
    
    return JsonResponse({
        'success': True,
        'suggestions': suggestions[:8]  # Return top 8 suggestions
    })


def contact_us(request):
    """
    Handle Contact Us page: form display and processing.
    """
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            # Save the message to the database
            contact_msg = form.save()
            
            # Send email notification if configured
            recipient_email = getattr(settings, 'CONTACT_EMAIL_RECIPIENT', '')
            if recipient_email:
                subject = f"New Contact Message: {contact_msg.subject}"
                message = f"You have received a new contact message from {contact_msg.name} ({contact_msg.email}):\n\n{contact_msg.message}"
                from_email = settings.DEFAULT_FROM_EMAIL
                
                try:
                    send_mail(
                        subject,
                        message,
                        from_email,
                        [recipient_email],
                        fail_silently=True
                    )
                except Exception as e:
                    logger.error(f"Failed to send contact notification email: {e}")
            
            messages.success(request, "Your message has been sent successfully! We'll get back to you soon.")
            return render(request, 'home/contact.html', {'form': ContactForm(), 'success': True})
    else:
        form = ContactForm()
    
    return render(request, 'home/contact.html', {'form': form})

from django.shortcuts import redirect
from .models import NewsletterSubscriber

def subscribe_newsletter(request):
    """
    Handle newsletter subscription requests.
    """
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if email:
            # Check if already subscribed
            subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email)
            if created:
                messages.success(request, "Thank you for subscribing to our newsletter!")
            else:
                if not subscriber.is_active:
                    subscriber.is_active = True
                    subscriber.save()
                    messages.success(request, "Welcome back! Your subscription has been reactivated.")
                else:
                    messages.info(request, "You are already subscribed to our newsletter.")
        else:
            messages.error(request, "Please provide a valid email address.")
            
        # Redirect back to where they came from
        next_url = request.META.get('HTTP_REFERER', '/')
        return redirect(next_url)
    
    return redirect('home')

def faq_page(request):
    """
    Render the Frequently Asked Questions (FAQ) page.
    """
    return render(request, 'home/faq.html')