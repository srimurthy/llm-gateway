"""Async jobs: submit a completion now, fetch the result later."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, status

from llm_gateway.api.dependencies import JobServiceDep, TenantDep
from llm_gateway.api.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    JobAcceptedOut,
    JobErrorOut,
    JobOut,
)
from llm_gateway.core.errors import InvalidRequestError
from llm_gateway.jobs.models import JOB_ID_PATTERN

router = APIRouter(prefix="/v1/async", tags=["jobs"])


@router.post(
    "/chat/completions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a chat completion to run when capacity allows.",
)
async def submit_job(
    body: ChatCompletionRequest, tenant: TenantDep, jobs: JobServiceDep
) -> JobAcceptedOut:
    if body.stream:
        raise InvalidRequestError("Async jobs cannot stream. Remove 'stream' from the request.")
    job = await jobs.submit(tenant=tenant, alias=body.model, prompt=body.to_prompt())
    return JobAcceptedOut(
        id=job.job_id, status=job.status.value, status_url=f"/v1/async/jobs/{job.job_id}"
    )


@router.get("/jobs/{job_id}", summary="Get a job's status and, once finished, its result.")
async def get_job(
    job_id: Annotated[str, Path(pattern=JOB_ID_PATTERN)], tenant: TenantDep, jobs: JobServiceDep
) -> JobOut:
    job = await jobs.get(tenant=tenant, job_id=job_id)
    return JobOut(
        id=job.job_id,
        status=job.status.value,
        model=job.alias,
        created_at=job.created_at.isoformat(),
        result=ChatCompletionResponse.model_validate(job.result) if job.result else None,
        error=JobErrorOut(code=job.error.code, message=job.error.message) if job.error else None,
    )
