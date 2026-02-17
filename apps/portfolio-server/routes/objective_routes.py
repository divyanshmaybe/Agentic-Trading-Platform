from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prisma import Prisma

from controllers.objective_controller import ObjectiveController
from db import prisma_client
from schemas import (
    ObjectiveCreateRequest,
    ObjectiveCreateResponse,
    ObjectiveIntakeRequest,
    ObjectiveIntakeResponse,
    ObjectiveResponse,
)
from services.pipeline_service import PipelineService
from services.objective_intake_service import ObjectiveIntakeService
from utils.auth import get_authenticated_user


def create_objective_routes(pipeline_service: PipelineService) -> APIRouter:
    """Factory that wires objective routes with the shared pipeline service."""

    router = APIRouter(prefix="/objectives", tags=["Objectives"])

    def get_controller(prisma: Prisma = Depends(prisma_client)) -> ObjectiveController:
        return ObjectiveController(prisma, pipeline_service, logger=pipeline_service.logger)

    def get_intake_service(prisma: Prisma = Depends(prisma_client)) -> ObjectiveIntakeService:
        return ObjectiveIntakeService(prisma, pipeline_service, logger=pipeline_service.logger)

    @router.get(
        "/",
        response_model=List[ObjectiveResponse],
        status_code=status.HTTP_200_OK,
        summary="Get objectives for authenticated user",
    )
    async def get_user_objectives(
        prisma: Prisma = Depends(prisma_client),
        user: dict = Depends(get_authenticated_user),
        status_filter: Optional[str] = Query(
            default=None,
            description="Filter by status (active, inactive, etc.)",
            alias="status",
        ),
        include_inactive: bool = Query(
            default=False,
            description="Include inactive/archived objectives",
        ),
    ) -> List[ObjectiveResponse]:
        """
        Retrieve all investment objectives for the authenticated user.
        By default, returns only active objectives.
        """
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user id is required.",
            )

        # Build where clause
        where_clause: dict = {"user_id": user_id}
        
        if status_filter:
            where_clause["status"] = status_filter
        elif not include_inactive:
            where_clause["status"] = "active"

        objectives = await prisma.objective.find_many(
            where=where_clause,
            order={"created_at": "desc"},
        )

        return [
            ObjectiveResponse.model_validate(obj.model_dump())
            for obj in objectives
        ]

    @router.get(
        "/{objective_id}",
        response_model=ObjectiveResponse,
        status_code=status.HTTP_200_OK,
        summary="Get a specific objective by ID",
    )
    async def get_objective_by_id(
        objective_id: str,
        prisma: Prisma = Depends(prisma_client),
        user: dict = Depends(get_authenticated_user),
    ) -> ObjectiveResponse:
        """
        Retrieve a specific investment objective by its ID.
        The objective must belong to the authenticated user.
        """
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user id is required.",
            )

        objective = await prisma.objective.find_unique(
            where={"id": objective_id}
        )

        if not objective:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Objective {objective_id} not found.",
            )

        if objective.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Objective does not belong to the authenticated user.",
            )

        return ObjectiveResponse.model_validate(objective.model_dump())

    @router.post(
        "/",
        response_model=ObjectiveCreateResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create objective and trigger allocation",
    )
    async def create_objective(
        payload: ObjectiveCreateRequest,
        controller: ObjectiveController = Depends(get_controller),
        user: dict = Depends(get_authenticated_user),
    ) -> ObjectiveCreateResponse:
        """
        Create an investment objective for the authenticated user and immediately
        rebalance their portfolio using the Pathway allocation pipeline.
        """

        return await controller.create_objective(user, payload)

    @router.post(
        "/intake",
        response_model=ObjectiveIntakeResponse,
        status_code=status.HTTP_200_OK,
        summary="Interactive objective intake (transcript or JSON)",
    )
    async def intake_objective(
        payload: ObjectiveIntakeRequest,
        intake_service: ObjectiveIntakeService = Depends(get_intake_service),
        user: dict = Depends(get_authenticated_user),
    ) -> ObjectiveIntakeResponse:
        """
        Accepts either a transcript or partial structured JSON and progressively
        builds an investment objective. Responds with missing fields until all
        mandatory attributes are captured, then finalises the objective and
        rebalances the user's portfolio.
        """

        return await intake_service.process_intake(user, payload)

    return router








