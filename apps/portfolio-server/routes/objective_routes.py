from __future__ import annotations

from fastapi import APIRouter, Depends, status
from prisma import Prisma

from controllers.objective_controller import ObjectiveController
from db import prisma_client
from schemas import (
    ObjectiveCreateRequest,
    ObjectiveCreateResponse,
    ObjectiveIntakeRequest,
    ObjectiveIntakeResponse,
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


