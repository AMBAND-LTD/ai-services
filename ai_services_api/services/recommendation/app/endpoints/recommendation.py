from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, Request
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import logging
import json
from datetime import datetime
from ai_services_api.services.recommendation.services.expert_matching import ExpertMatchingService
from ai_services_api.services.recommendation.core.database import Neo4jDatabase
from ai_services_api.services.recommendation.core.postgres_database import get_db_connection

router = APIRouter()
logger = logging.getLogger(__name__)

# Base Models
class ExpertBase(BaseModel):
    expert_id: str = Field(..., description="Expert's unique identifier")

class ExpertResponse(ExpertBase):
    name: str = Field(..., description="Expert's full name")
    expertise_summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of expert's expertise categories"
    )
    similar_experts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of similar experts with similarity scores"
    )

# User ID dependencies
async def get_user_id(request: Request) -> str:
    """Get user ID from request header for production use"""
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header is required")
    return user_id

async def get_test_user_id(request: Request) -> str:
    """Get user ID from request header or use default for testing"""
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        user_id = "test_user_123"
    return user_id

async def process_expert_recommendation(
    expert_id: str,
    user_id: str
):
    """Common expert recommendation processing logic"""
    db_conn = get_db_connection()
    cursor = db_conn.cursor()
    start_time = datetime.utcnow()
    
    try:
        # Get expert matching service
        expert_matching = ExpertMatchingService()
        
        # Get recommendations with analytics tracking
        similar_experts = await expert_matching.find_similar_experts(expert_id)
        
        # Record matches in analytics
        for match in similar_experts:
            cursor.execute("""
                INSERT INTO expert_matching_logs (
                    expert_id,
                    matched_expert_id,
                    similarity_score,
                    shared_domains,
                    shared_fields,
                    shared_skills,
                    successful
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
            """, (
                expert_id,
                match['id'],
                match['similarity_score'],
                json.dumps(match['shared_domains']),
                len(match.get('shared_fields', [])),
                len(match.get('shared_skills', [])),
                True  # All matches are considered successful as we're taking top 10
            ))
            
            # Record domain analytics
            for domain in match.get('shared_domains', []):
                cursor.execute("""
                    INSERT INTO domain_expertise_analytics (
                        domain_name,
                        match_count
                    ) VALUES (%s, 1)
                    ON CONFLICT (domain_name) 
                    DO UPDATE SET match_count = domain_expertise_analytics.match_count + 1
                """, (domain,))
        
        db_conn.commit()
        
        return {
            "expert_id": expert_id,
            "recommendations": similar_experts,
            "user_id": user_id,  # Include user_id in response but not in DB
            "analytics": {
                "total_matches": len(similar_experts),
                "average_similarity": sum(e['similarity_score'] for e in similar_experts) / len(similar_experts) if similar_experts else 0,
                "timestamp": datetime.utcnow()
            }
        }
        
    except Exception as e:
        db_conn.rollback()
        logger.error(f"Error in recommendation: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        db_conn.close()

# Test endpoint
@router.post("/recommendation/test/recommend/{expert_id}")
async def test_expert_recommendation(
    expert_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_test_user_id)
):
    """Test endpoint for expert recommendations with analytics tracking."""
    return await process_expert_recommendation(expert_id, user_id)

# Production endpoint
@router.post("/recommendation/recommend/{expert_id}")
async def expert_recommendation(
    expert_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id)
):
    """Production endpoint for expert recommendations with analytics tracking."""
    return await process_expert_recommendation(expert_id, user_id)
