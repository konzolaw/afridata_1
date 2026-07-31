# dataset/views.py
# pyrefly: ignore-all-errors  # Django ORM/request false positives — no django-stubs support in Pyrefly yet
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.utils import timezone
from datetime import timedelta, date
from .models import Dataset, Comment, TokenTransaction, Download, PremiumPurchase
from accounts.models import CustomUser, UserProfile
import pandas as pd
import numpy as np
import io
from django.views.decorators.csrf import csrf_exempt
from .forms import DatasetUploadForm, DatasetEditForm
import json
from django.http import JsonResponse
from django.urls import reverse
from django.contrib.auth import get_user_model
from typing import cast, Any

User = get_user_model() 

import threading
from metadata.models import PipelineRun, RunStatus, SourceType
from metadata.tasks import run_pipeline_task 

def _run_pipeline_task_with_db_cleanup(*args, **kwargs):
    from django.db import connections
    try:
        run_pipeline_task(*args, **kwargs)
    finally:
        connections.close_all()



def dataset_detail(request, slug):
    """View to display dataset details and bio with enhanced functionality"""
    dataset = get_object_or_404(Dataset, slug=slug)

   
    # Increment view count
    dataset.views += 1
    dataset.save(update_fields=['views'])
    
    # Check if user can download (for authenticated users)
    can_download = False
    insufficient_tokens = False
    monthly_limit_exceeded = False
    user_token_balance = 0
    
    if request.user.is_authenticated:
        user_profile = request.user.profile
        user_token_balance = user_profile.token_balance
        
        # Check if user has already downloaded this dataset
        already_downloaded = Download.objects.filter(
            user=request.user, 
            dataset=dataset
        ).exists()
        
        if already_downloaded:
            can_download = True
        else:
            # Check monthly download limit
            user_profile.reset_monthly_downloads_if_needed()
            if not user_profile.can_download_this_month():
                monthly_limit_exceeded = True
            elif dataset.is_premium:
                # Premium datasets don't require tokens but need separate purchase
                can_download = True
            elif user_profile.can_afford(dataset.token_cost):
                can_download = True
            else:
                insufficient_tokens = True
   
    # Get preview data
    preview_data = []
    columns = []
    graph_data = None
    error_message = None
    
    try:
        # Read dataset file for preview
        if dataset.file:
            # Reset file pointer to beginning
            dataset.file.seek(0)
            file_content = dataset.file.read()
            
            # Determine file type and read accordingly
            if dataset.dataset_type == 'unstructured':
                # Skip pandas parsing for unstructured data
                df = pd.DataFrame()
            elif dataset.dataset_type == 'csv':
                try:
                    df = pd.read_csv(io.BytesIO(file_content), encoding='utf-8')
                except Exception:
                    try:
                        df = pd.read_csv(io.BytesIO(file_content), encoding='latin-1')
                    except Exception:
                        df = pd.read_csv(io.BytesIO(file_content))
            elif dataset.dataset_type == 'excel':
                df = pd.read_excel(io.BytesIO(file_content))
            else:
                # Try CSV as fallback
                try:
                    df = pd.read_csv(io.BytesIO(file_content), encoding='utf-8')
                except Exception:
                    try:
                        df = pd.read_csv(io.BytesIO(file_content), encoding='latin-1')
                    except Exception:
                        df = pd.read_csv(io.BytesIO(file_content))
            
            if not df.empty:
                # Get columns
                columns = df.columns.tolist()
                
                # Get preview data (first 10 rows)
                preview_rows = df.head(10)
                preview_data = preview_rows.to_dict('records')
                
                # Improved Data Visualization Logic
                # ----------------------------------
                numeric_cols = df.select_dtypes(include=cast(Any, ['number'])).columns.tolist()
                object_cols = df.select_dtypes(include=cast(Any, ['object', 'category', 'datetime'])).columns.tolist()
                
                chart_type = 'bar'
                chart_labels = []
                chart_datasets = []
                insight_label = "General Preview"

                if numeric_cols and len(df) > 1:
                    # 1. Try to find a good categorical column for labeling
                    # look for specific names or low-cardinality columns
                    label_col = None
                    potential_labels = ['name', 'title', 'category', 'country', 'state', 'city', 'year', 'month', 'date', 'type', 'region', 'label']
                    for p_label in potential_labels:
                        matching = [c for c in object_cols if p_label in c.lower()]
                        if matching:
                            # Check cardinality - between 2 and 20 is ideal for visualization
                            if 2 <= df[matching[0]].nunique() <= 20:
                                label_col = matching[0]
                                break
                    
                    # If no named label column, find any categorical column with low cardinality
                    if not label_col:
                        for col in object_cols:
                            if 2 <= df[col].nunique() <= 15:
                                label_col = col
                                break
                    
                    # 2. Extract or Aggregate data
                    if label_col:
                        # Aggregate first 3 numeric columns by label_col
                        target_numerics = numeric_cols[:2] 
                        agg_df = df.groupby(label_col)[target_numerics].mean().reset_index()
                        
                        # Limit to top 12 categories for clarity
                        if len(agg_df) > 12:
                            agg_df = agg_df.head(12)
                        
                        chart_labels = agg_df[label_col].astype(str).tolist()
                        insight_label = f"Average by {label_col}"
                        
                        colors = [
                            'rgba(54, 162, 235, 0.8)', # Blue
                            'rgba(255, 99, 132, 0.8)', # Red
                            'rgba(75, 192, 192, 0.8)', # Teal
                            'rgba(255, 206, 86, 0.8)', # Yellow
                            'rgba(153, 102, 255, 0.8)' # Purple
                        ]
                        
                        for i, col in enumerate(target_numerics):
                            chart_datasets.append({
                                'label': col,
                                'data': agg_df[col].fillna(0).tolist(),
                                'backgroundColor': colors[i % len(colors)],
                                'borderColor': colors[i % len(colors)].replace('0.8', '1'),
                                'borderWidth': 1
                            })
                        
                        # Use Pie chart if it's a single column with few labels
                        if len(chart_labels) <= 6 and len(target_numerics) == 1:
                            chart_type = 'doughnut'
                        elif any('year' in str(label_col).lower() or 'date' in str(label_col).lower() for i in [1]):
                            chart_type = 'line'

                    else:
                        # Fallback: Just plot the first numeric column of the first 20 rows
                        # But with better labeling than just "Row X"
                        chart_data_rows = df.head(15)
                        target_numeric = numeric_cols[0]
                        
                        if 'name' in df.columns:
                            chart_labels = chart_data_rows['name'].astype(str).tolist()
                        else:
                            chart_labels = [f"Item {i+1}" for i in range(len(chart_data_rows))]
                            
                        chart_datasets.append({
                            'label': target_numeric,
                            'data': chart_data_rows[target_numeric].fillna(0).tolist(),
                            'backgroundColor': 'rgba(54, 162, 235, 0.6)',
                            'borderColor': 'rgba(54, 162, 235, 1)',
                            'borderWidth': 1,
                            'fill': True,
                            'tension': 0.3
                        })
                        chart_type = 'area' if chart_type == 'line' else 'bar'

                    graph_data = {
                        'chart_type': 'line' if chart_type == 'line' or chart_type == 'area' else chart_type,
                        'labels_json': json.dumps(chart_labels),
                        'datasets_json': json.dumps(chart_datasets),
                        'raw_labels': chart_labels,
                        'raw_datasets': chart_datasets,
                        'insight_label': insight_label
                    }
    
    except Exception as e:
        error_message = f"Error reading dataset file: {str(e)}"
        print(f"Error reading dataset file: {e}")
        # Handle file reading errors gracefully
        preview_data = []
        columns = []
        graph_data = None
    
    # Get comments (top 5 by upvotes)
    comments = Comment.objects.filter(
        dataset=dataset
    ).select_related('author').order_by('-upvotes', '-created_at')[:5]
    
    # Get related datasets (AI Curated Content-Based Filtering)
    try:
        from recommendations.domain.engines.content_based import ContentBasedEngine
        from django.db.models import Case, When
        cbf_engine = ContentBasedEngine()
        cbf_engine.load()
        similar_ids = cbf_engine.get_similar_items(dataset.id, limit=5)
        
        if similar_ids:
            preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(similar_ids)])
            related_datasets = Dataset.objects.filter(id__in=similar_ids).order_by(preserved_order)
        else:
            # Fallback
            related_datasets = Dataset.objects.filter(
                Q(topics__icontains=dataset.topics) | Q(author=dataset.author)  # pyrefly: ignore[unsupported-operation]
            ).exclude(id=dataset.id).distinct()[:5]
    except Exception as e:
        print(f"Error loading ContentBasedEngine: {e}")
        related_datasets = Dataset.objects.filter(
            Q(topics__icontains=dataset.topics) | Q(author=dataset.author)  # pyrefly: ignore[unsupported-operation]
        ).exclude(id=dataset.id).distinct()[:5]
    
    # Fetch latest pipeline run and metadata result if available
    pipeline_run = None
    metadata_result = None
    try:
        pipeline_run = PipelineRun.objects.filter(
            dataset=dataset
        ).order_by('-created_at').first()
        if pipeline_run and hasattr(pipeline_run, 'metadata_result'):
            metadata_result = pipeline_run.metadata_result
    except Exception:
        pass

    context = {
        'dataset': dataset,
        'author_name': dataset.author.get_full_name() or dataset.author.username,
        'topics': dataset.get_topics_list(),
        'preview_data': preview_data,
        'columns': columns,
        'graph_data': graph_data,
        'comments': comments,
        'related_datasets': related_datasets,
        'error_message': error_message,
        'can_download': can_download,
        'insufficient_tokens': insufficient_tokens,
        'monthly_limit_exceeded': monthly_limit_exceeded,
        'user_token_balance': user_token_balance,
        'pipeline_run': pipeline_run,
        'metadata_result': metadata_result,
    }
    
    return render(request, 'dataset/dataset_detail.html', context)


def dataset_preview(request, slug):
    """View to display full dataset preview with pagination"""
    dataset = get_object_or_404(Dataset, slug=slug)

    
    try:
        if dataset.file:
            # Reset file pointer to beginning
            dataset.file.seek(0)
            file_content = dataset.file.read()
            
            if dataset.dataset_type == 'unstructured':
                df = pd.DataFrame()
            elif dataset.dataset_type == 'csv':
                df = pd.read_csv(io.BytesIO(file_content))
            elif dataset.dataset_type == 'excel':
                df = pd.read_excel(io.BytesIO(file_content))
            else:
                df = pd.read_csv(io.BytesIO(file_content))
            
            columns = df.columns.tolist()
            
            # Paginate the data
            page_number = request.GET.get('page', 1)
            rows_per_page = 50
            
            total_rows = len(df)
            start_idx = (int(page_number) - 1) * rows_per_page
            end_idx = start_idx + rows_per_page
            
            preview_data = df.iloc[start_idx:end_idx].to_dict('records')
            
            # Calculate pagination info
            import math
            total_pages = math.ceil(total_rows / rows_per_page) if rows_per_page else 1
            has_previous = start_idx > 0
            has_next = end_idx < total_rows
            
            context = {
                'dataset': dataset,
                'columns': columns,
                'preview_data': preview_data,
                'current_page': int(page_number),
                'total_pages': total_pages,
                'has_previous': has_previous,
                'has_next': has_next,
                'total_rows': total_rows,
                'start_row': start_idx + 1,
                'end_row': min(end_idx, total_rows),
                'author_name': dataset.author.get_full_name() or dataset.author.username,
            }
            
            return render(request, 'dataset/dataset_preview.html', context)
            
    except Exception as e:
        print(f"Error reading dataset file: {e}")
        context = {
            'dataset': dataset,
            'error_message': 'Unable to load dataset preview',
            'author_name': dataset.author.get_full_name() or dataset.author.username,
        }
        return render(request, 'dataset/dataset_preview.html', context)


def dataset_comments(request, slug):
    """View to display comments with pagination"""
    dataset = get_object_or_404(Dataset, slug=slug)

    
    # Get comments ordered by upvotes then by creation date
    comments = Comment.objects.filter(
        dataset=dataset
    ).select_related('author').order_by('-upvotes', '-created_at')
    
    # Paginate comments
    paginator = Paginator(comments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'dataset': dataset,
        'comments': page_obj,
        'author_name': dataset.author.get_full_name() or dataset.author.username,
    }
    
    return render(request, 'dataset/dataset_comments.html', context)


@login_required
@require_POST
def post_comment(request, slug):
    """View to allow authenticated user to post a comment"""
    dataset = get_object_or_404(Dataset, slug=slug)

    
    content = request.POST.get('content', '').strip()
    
    if not content:
        messages.error(request, 'Comment content cannot be empty.')
        return redirect('dataset_detail', slug=slug)

    
    # Create new comment
    comment = Comment.objects.create(
        dataset=dataset,
        author=request.user,
        content=content
    )
    
    messages.success(request, 'Comment posted successfully!')
    return redirect('dataset_detail', slug=slug)



@login_required
@require_POST
def upvote_comment(request, comment_id):
    """View to upvote a comment"""
    comment = get_object_or_404(Comment, id=comment_id)
    
    # Increment upvote count
    comment.upvotes += 1
    comment.save(update_fields=['upvotes'])
    
    if request.headers.get('Content-Type') == 'application/json':
        return JsonResponse({'upvotes': comment.upvotes})
    
    return redirect('dataset_detail', slug=comment.dataset.slug)


@login_required
def download_dataset(request, slug):
    """Handle dataset download with token system"""
    dataset = get_object_or_404(Dataset, slug=slug)

    user_profile = request.user.profile
    
    # Check if user has already downloaded this dataset
    existing_download = Download.objects.filter(user=request.user, dataset=dataset).first()
    if existing_download:
        # User already downloaded, allow re-download
        return serve_file(dataset)
    
    # Check monthly download limits
    user_profile.reset_monthly_downloads_if_needed()
    if not user_profile.can_download_this_month():
        messages.error(request, f'You have reached your monthly download limit of {user_profile.monthly_download_limit} files.')
        return redirect('dataset_detail', slug=slug)

    
    # Handle premium datasets
    if dataset.is_premium:
        # Check if user has purchased this premium dataset
        premium_purchase = PremiumPurchase.objects.filter(
            user=request.user, 
            dataset=dataset, 
            payment_status='completed'
        ).first()
        
        if not premium_purchase:
            messages.error(request, 'This is a premium dataset. Please purchase it first.')
            return redirect('dataset_detail', slug=slug)

        
        # Create download record
        Download.objects.create(
            user=request.user,
            dataset=dataset,
            tokens_spent=0,
            is_premium_download=True,
            premium_purchase=premium_purchase
        )
    else:
        # Handle regular token-based downloads
        if not user_profile.can_afford(dataset.token_cost):
            messages.error(request, f'Insufficient tokens. You need {dataset.token_cost} tokens but have {user_profile.token_balance}.')
            return redirect('dataset_detail', slug=slug)

        
        # Deduct tokens
        if user_profile.spend_tokens(dataset.token_cost, f'Downloaded {dataset.title}'):
            # Create download record
            Download.objects.create(
                user=request.user,
                dataset=dataset,
                tokens_spent=dataset.token_cost,
                is_premium_download=False
            )
        else:
            messages.error(request, 'Failed to process token payment.')
            return redirect('dataset_detail', slug=slug)

    
    # Increment counters
    dataset.downloads += 1
    dataset.save(update_fields=['downloads'])
    user_profile.increment_monthly_downloads()
    
    messages.success(request, f'Successfully downloaded {dataset.title}!')
    return serve_file(dataset)


def serve_file(dataset):
    """Helper function to serve the dataset file"""
    if dataset.file:
        dataset.file.seek(0)
        response = HttpResponse(
            dataset.file.read(), 
            content_type='application/octet-stream'
        )
        response['Content-Disposition'] = f'attachment; filename="{dataset.file.name}"'
        return response
    else:
        raise Http404("File not found")


@login_required
def upload_dataset(request):
    """Handle dataset upload via regular form submission and AJAX with token rewards"""
    if request.method == 'POST':
        form = DatasetUploadForm(request.POST, request.FILES)
        if form.is_valid():
            dataset = form.save(commit=False)
            dataset.author = request.user

            # ==================== ADDED FOR HASHING ====================
            uploaded_file = form.cleaned_data.get('file')
            if uploaded_file and hasattr(uploaded_file, 'file_hash'):
                dataset.file_hash = uploaded_file.file_hash
            # ==========================================================

            # Calculate token cost based on file size
            # Calculate token cost based on file size
            dataset.token_cost = dataset.calculate_token_cost()
            dataset.save()
            
            # Trigger metadata AI engine asynchronously if supported
            if dataset.dataset_type in ['csv', 'excel', 'parquet', 'json']:
                try:
                    source = SourceType.EXCEL if dataset.dataset_type == 'excel' else SourceType.CSV
                    run = PipelineRun.objects.create(
                        dataset=dataset,
                        source=source,
                        source_path=dataset.file.name,
                        dataset_title=dataset.title,
                        dataset_description=dataset.bio,
                        status=RunStatus.PENDING,
                    )
                    threading.Thread(
                        target=_run_pipeline_task_with_db_cleanup,
                        kwargs={
                            "run_id": str(run.id),
                            "source": source,
                            "source_path": dataset.file.name,
                            "dataset_title": dataset.title,
                            "dataset_description": dataset.bio,
                        },
                        daemon=True
                    ).start()
                except Exception as e:
                    # Log error but don't fail upload
                    import logging
                    logging.getLogger(__name__).exception("Failed to trigger metadata pipeline: %s", e)
            
            # Award upload bonus tokens to the user
            upload_bonus = dataset.get_upload_bonus_tokens()
            request.user.profile.add_tokens(
                amount=upload_bonus,
                transaction_type='upload_bonus',
                description=f'Upload bonus for "{dataset.title}"',
                dataset=dataset
            )
            
            # Check if it's an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Dataset uploaded successfully! You earned {upload_bonus} tokens.',
                    'dataset_id': dataset.pk,
                    'tokens_earned': upload_bonus,
                    'redirect_url': reverse('dataset_detail', kwargs={'slug': dataset.slug})

                })
            else:
                # Regular form submission - redirect as usual
                messages.success(request, f'Dataset uploaded successfully! You earned {upload_bonus} tokens.')
                return redirect('dataset_detail', slug=dataset.slug)

        else:
            # Form has errors
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': form.errors,
                    'message': 'Please correct the errors below.'
                }, status=400)
            else:
                # Regular form submission with errors
                messages.error(request, 'Please correct the errors below.')
    else:
        form = DatasetUploadForm()
   
    return render(request, 'dataset/upload.html', {'form': form})

'''
@login_required
def home(request):
    """Render authenticated user's home page - Dynamic home page view with real data"""
    
    # Get user-specific data
    user_profile = request.user.profile
    user_downloads = Download.objects.filter(user=request.user).count()
    user_uploads = Dataset.objects.filter(author=request.user).count()
    
    # Reset monthly downloads if needed
    user_profile.reset_monthly_downloads_if_needed()
    
    # Get total statistics
    total_researchers = User.objects.count()
    total_datasets = Dataset.objects.count()
    total_downloads = Dataset.objects.aggregate(Sum('downloads'))['downloads__sum'] or 0
    total_views = Dataset.objects.aggregate(Sum('views'))['views__sum'] or 0
    
    # Get trending datasets (most downloaded in the last week)
    trending_datasets = Dataset.objects.select_related('author').annotate(
        recent_growth=Count('id')
    ).order_by('-downloads', '-views')[:3]
    
    # Get top categories with counts
    all_datasets = Dataset.objects.all()
    category_counts = {}
    
    for dataset in all_datasets:
        topics = dataset.get_topics_list()
        for topic in topics:
            topic_lower = topic.lower().strip()
            if topic_lower in category_counts:
                category_counts[topic_lower] += 1
            else:
                category_counts[topic_lower] = 1
    
    # Sort categories by count and get top 4
    top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:4]
    
    # Get popular search terms (based on topics)
    popular_terms = []
    if top_categories:
        popular_terms = [category[0].title() for category in top_categories[:6]]
    
    # Get featured datasets (highest rated or most downloaded)
    featured_datasets = Dataset.objects.select_related('author').order_by('-rating', '-downloads')[:4]
    
    # Get file format counts
    format_counts = {
        'csv': Dataset.objects.filter(dataset_type='csv').count(),
        'excel': Dataset.objects.filter(dataset_type='excel').count(),
        'pdf': Dataset.objects.filter(dataset_type='pdf').count(),
        'txt': Dataset.objects.filter(dataset_type='txt').count(),
        'json': Dataset.objects.filter(dataset_type='json').count(),
        'yaml': Dataset.objects.filter(dataset_type='yaml').count(),
        'xml': Dataset.objects.filter(dataset_type='xml').count(),
        'zip': Dataset.objects.filter(dataset_type='zip').count(),
        'parquet': Dataset.objects.filter(dataset_type='parquet').count(),
    }
    
    # Get recent transactions for the user
    recent_transactions = TokenTransaction.objects.filter(
        user=request.user
    ).order_by('-created_at')[:5]
    
    context = {
        'total_datasets': total_datasets,
        'total_downloads': total_downloads,
        'total_views': total_views,
        'total_countries': 54,  # Static for now
        'total_researchers': total_researchers, 
        'trending_datasets': trending_datasets,
        'top_categories': top_categories,
        'popular_terms': popular_terms,
        'featured_datasets': featured_datasets,
        'format_counts': format_counts,
        # User-specific data
        'user_token_balance': user_profile.token_balance,
        'user_downloads': user_downloads,
        'user_uploads': user_uploads,
        'downloads_remaining': user_profile.monthly_download_limit - user_profile.downloads_this_month,
        'recent_transactions': recent_transactions,
        'is_premium': user_profile.is_premium_subscriber,
    }

    return render(request, 'accounts/home.html', context)'''


def dataset_list(request):
    """View to return dataset title, author name, downloads, views with search and filtering"""
    datasets = Dataset.objects.select_related('author').all()
    
    # Handle search
    search_query = request.GET.get('search', '')
    if search_query:
        from django.db.models import Case, When, IntegerField, Value
        datasets = datasets.annotate(
            search_relevance=Case(
                When(title__iexact=search_query, then=Value(100)),
                When(title__icontains=search_query, then=Value(80)),
                When(topics__icontains=search_query, then=Value(60)),
                When(bio__icontains=search_query, then=Value(40)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).filter(
            Q(title__icontains=search_query) |  # type: ignore
            Q(bio__icontains=search_query) |  # type: ignore
            Q(topics__icontains=search_query) |  # type: ignore
            Q(author__username__icontains=search_query)
        ).order_by('-search_relevance')
    
    # Handle category filter
    category = request.GET.get('category', '')
    if category and category != 'all':
        datasets = datasets.filter(topics__icontains=category)
    
    # Handle format filter
    format_filter = request.GET.get('format', '')
    if format_filter:
        datasets = datasets.filter(dataset_type=format_filter)
    
    # Handle premium filter
    premium_filter = request.GET.get('premium', '')
    if premium_filter == 'true':
        datasets = datasets.filter(is_premium=True)
    elif premium_filter == 'false':
        datasets = datasets.filter(is_premium=False)
    
    # Handle quality tier filter
    quality_filter = request.GET.get('quality', '')
    if quality_filter:
        datasets = datasets.filter(quality_tier=quality_filter)
    
    # Handle sorting
    sort_by = request.GET.get('sort', 'relevance')
    if sort_by == 'downloads':
        datasets = datasets.order_by('-downloads')
    elif sort_by == 'recent':
        datasets = datasets.order_by('-created_at')
    elif sort_by == 'rating':
        datasets = datasets.order_by('-rating')
    elif sort_by == 'tokens_asc':
        datasets = datasets.order_by('token_cost')
    elif sort_by == 'tokens_desc':
        datasets = datasets.order_by('-token_cost')
    else:  # relevance (default)
        if search_query:
            datasets = datasets.order_by('-search_relevance', '-views', '-downloads')
        else:
            datasets = datasets.order_by('-views', '-downloads')
    
    # Pagination
    paginator = Paginator(datasets, 12)  # Show 12 datasets per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    dataset_data = []
    for dataset in page_obj:
        dataset_data.append({
            'id': dataset.id,
            'slug': dataset.slug,
            'title': dataset.title,
            'author_name': dataset.author.get_full_name() or dataset.author.username,
            'downloads': dataset.downloads,
            'views': dataset.views,
            'rating': dataset.rating,
            'bio': dataset.bio,
            'topics': dataset.get_topics_list(),
            'dataset_type': dataset.get_dataset_type_display(),
            'created_at': dataset.created_at,
            'token_cost': dataset.token_cost,
            'is_premium': dataset.is_premium,
            'premium_price_usd': dataset.premium_price_usd,
            'quality_tier': dataset.get_quality_tier_display(),
            'file_size_mb': round(dataset.file_size_mb, 2),
            'has_documentation': dataset.has_documentation,
            'cover_photo': dataset.get_cover_photo_url,
        })
    
    context = {
        'datasets': dataset_data,
        'page_obj': page_obj,
        'search_query': search_query,
        'current_category': category,
        'current_format': format_filter,
        'current_sort': sort_by,
        'current_premium': premium_filter,
        'current_quality': quality_filter,
    }
    return render(request, 'dataset/dataset_list.html', context)



@login_required
def token_history(request):
    """View showing user's complete token transaction history"""
    transactions = TokenTransaction.objects.filter(user=request.user).order_by('-created_at')
    
    # Pagination
    paginator = Paginator(transactions, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'transactions': page_obj,
        'user_profile': request.user.profile,
    }
    
    return render(request, 'accounts/token_history.html', context)


@login_required
def generate_metadata(request, slug):
    """AJAX endpoint to trigger async metadata extraction and inference for a dataset."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST request required.'}, status=405)
        
    dataset = get_object_or_404(Dataset, slug=slug)
    
    # Verify dataset type and presence of file
    if dataset.dataset_type not in ['csv', 'excel']:
        return JsonResponse({
            'success': False, 
            'error': 'Metadata generation is only supported for CSV and Excel datasets.'
        }, status=400)
        
    if not dataset.file or not dataset.file.name:
        return JsonResponse({
            'success': False, 
            'error': 'Dataset file is missing.'
        }, status=400)
        
    # Check if there is already a running/pending run
    active_run = PipelineRun.objects.filter(
        dataset=dataset,
        status__in=[RunStatus.PENDING, RunStatus.RUNNING]
    ).first()
    
    if active_run:
        return JsonResponse({
            'success': False, 
            'error': 'Metadata generation is already in progress.',
            'run_id': str(active_run.id)
        })
        
    # Start the async metadata run
    try:
        source = SourceType.EXCEL if dataset.dataset_type == 'excel' else SourceType.CSV
        run = PipelineRun.objects.create(
            dataset=dataset,
            source=source,
            source_path=dataset.file.path,
            dataset_title=dataset.title,
            dataset_description=dataset.bio,
            status=RunStatus.PENDING,
        )
        threading.Thread(
            target=_run_pipeline_task_with_db_cleanup,
            kwargs={
                "run_id": str(run.id),
                "source": source,
                "source_path": dataset.file.path,
                "dataset_title": dataset.title,
                "dataset_description": dataset.bio,
            },
            daemon=True
        ).start()
        return JsonResponse({
            'success': True, 
            'run_id': str(run.id),
            'message': 'Metadata generation started.'
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to trigger manual metadata pipeline: %s", e)
        return JsonResponse({
            'success': False, 
            'error': f'Failed to trigger metadata pipeline: {str(e)}'
        }, status=500)

@login_required
def edit_dataset(request, slug):
    """View to allow authors to edit their dataset"""
    dataset = get_object_or_404(Dataset, slug=slug)
    
    # Ensure only author or superuser can edit
    if request.user != dataset.author and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to edit this dataset.')
        return redirect('dataset_detail', slug=slug)
        
    if request.method == 'POST':
        form = DatasetEditForm(request.POST, request.FILES, instance=dataset)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dataset updated successfully!')
            return redirect('dataset_detail', slug=dataset.slug)
    else:
        form = DatasetEditForm(instance=dataset)
        
    context = {
        'form': form,
        'dataset': dataset,
    }
    return render(request, 'dataset/edit.html', context)

@login_required
@require_POST
def delete_dataset(request, slug):
    """View to allow authors to delete their dataset"""
    dataset = get_object_or_404(Dataset, slug=slug)
    
    # Ensure only author or superuser can delete
    if request.user != dataset.author and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to delete this dataset.')
        return redirect('dataset_detail', slug=slug)
        
    dataset.delete()
    messages.success(request, 'Dataset deleted successfully!')
    return redirect('workspace')