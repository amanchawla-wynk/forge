import type { AssessmentResponse, EdgeCaseCoverageLedger, LLMConfig, SupplementalAnswer, UploadResponse } from "@/lib/types";

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
