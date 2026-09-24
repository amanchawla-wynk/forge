import type {
  AssessmentResponse,
  EdgeCaseCoverageLedger,
  LLMConfig,
  RemediationCheckpointResponse,
  RemediationTurnResponse,
  ReviewDiscovery,
  RevisionAction,
  RevisionPreview,
  RevisionResponse,
  SupplementalAnswer,
  UploadResponse,
} from "@/lib/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // fall through to generic message
  }
  return `Request failed with status ${response.status}`;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/documents`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export interface CreateAssessmentPayload {
  document_id: string;
  llm: LLMConfig;
  rubric_name?: string;
  supplemental_answers?: SupplementalAnswer[];
  product_context?: { term: string; meaning: string; source_ref?: string | null }[];
  framing?: string | null;
  edge_case_coverage?: EdgeCaseCoverageLedger | null;
  start_new?: boolean;
}

export async function createAssessment(
  payload: CreateAssessmentPayload,
): Promise<AssessmentResponse> {
  const response = await fetch(`${API_BASE_URL}/api/assessments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function recordRemediationAnswer(
  sessionId: string,
  sessionVersion: number,
  operationId: string,
  answer: string,
  forceCheckpoint = false,
): Promise<RemediationTurnResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/remediation/${sessionId}/answers`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_version: sessionVersion,
        operation_id: operationId,
        answer,
        force_checkpoint: forceCheckpoint,
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function checkpointRemediation(
  sessionId: string,
  sessionVersion: number,
  operationId: string,
  llm: LLMConfig,
): Promise<RemediationCheckpointResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/remediation/${sessionId}/checkpoint`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        llm,
        session_version: sessionVersion,
        operation_id: operationId,
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function findDocumentReviews(
  documentId: string,
): Promise<ReviewDiscovery> {
  const response = await fetch(
    `${API_BASE_URL}/api/documents/${documentId}/reviews`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function resumeDocumentReview(
  documentId: string,
  reviewSessionId: string,
  confirmClientChange = false,
): Promise<AssessmentResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/documents/${documentId}/reviews/${reviewSessionId}/resume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operation_id: crypto.randomUUID(),
        confirm_client_change: confirmClientChange,
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function previewRevision(
  documentId: string,
  reviewSessionId: string,
  sessionVersion: number,
  operationId: string,
  supplementalAnswers: SupplementalAnswer[],
): Promise<RevisionPreview> {
  const response = await fetch(
    `${API_BASE_URL}/api/documents/${documentId}/revisions/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review_session_id: reviewSessionId,
        session_version: sessionVersion,
        operation_id: operationId,
        supplemental_answers: supplementalAnswers,
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function createRevision(
  documentId: string,
  reviewSessionId: string,
  sessionVersion: number,
  operationId: string,
  planId: string,
  actions: Record<string, RevisionAction>,
  llm: LLMConfig,
): Promise<RevisionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/documents/${documentId}/revisions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review_session_id: reviewSessionId,
        session_version: sessionVersion,
        operation_id: operationId,
        plan_id: planId,
        actions,
        llm,
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export function documentDownloadUrl(documentId: string): string {
  return `${API_BASE_URL}/api/documents/${documentId}/download`;
}

export interface VerifyLLMResponse {
  ok: boolean;
  model: string;
}

export async function verifyLLM(llm: LLMConfig): Promise<VerifyLLMResponse> {
  const response = await fetch(`${API_BASE_URL}/api/llm/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(llm),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}
