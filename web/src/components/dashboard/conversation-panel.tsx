"use client";

import { useState } from "react";
import { CheckCircle2, Download, FilePenLine, Loader2, MessageCircleQuestion, SendHorizontal, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  checkpointRemediation,
  createRevision,
  documentDownloadUrl,
  previewRevision,
  recordRemediationAnswer,
  resumeDocumentReview,
} from "@/lib/api";
import { useAppStore } from "@/lib/store";
import {
  BAND_STYLES,
  CONSUMER_LABELS,
  type AssessmentResponse,
  type Consumer,
  type RevisionAction,
  type RevisionPreview,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function ConversationPanel() {
  const llm = useAppStore((state) => state.llm);
  const document = useAppStore((state) => state.document);
  const assessment = useAppStore((state) => state.assessment);
  const history = useAppStore((state) => state.history);
  const setAssessment = useAppStore((state) => state.setAssessment);
  const setDocument = useAppStore((state) => state.setDocument);
  const appendHistory = useAppStore((state) => state.appendHistory);

  const [answer, setAnswer] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [checkpointOperationId, setCheckpointOperationId] = useState<string | null>(null);
  const [revisionPreview, setRevisionPreview] = useState<RevisionPreview | null>(null);
  const [revisionActions, setRevisionActions] = useState<Record<string, RevisionAction>>({});
  const [revisionDownload, setRevisionDownload] = useState<string | null>(null);

  if (!assessment || !llm || !document) return null;
  const question = assessment.next_question;
  const nextAction = assessment.next_action?.type;

  async function runCheckpoint(current: AssessmentResponse) {
    const sessionId = current.review_session_id;
    const sessionVersion = current.session_version;
    if (!sessionId || !sessionVersion || !llm) return;
    const operationId = checkpointOperationId ?? crypto.randomUUID();
    setCheckpointOperationId(operationId);
    const checkpoint = await checkpointRemediation(
      sessionId,
      sessionVersion,
      operationId,
      llm,
    );
    const state = checkpoint.result.state;
    setAssessment({
      ...current,
      assessment: state.assessment,
      report: state.report,
      next_question: checkpoint.result.next_question,
      supplemental_answers: state.verified_answers,
      framing: state.framing,
      edge_case_coverage: state.edge_case_coverage,
      review_session_id: checkpoint.review_session_id,
      session_version: checkpoint.session_version,
      workflow_state: checkpoint.workflow_state,
      next_action: checkpoint.next_action,
    });
    setPendingCount(0);
    setCheckpointOperationId(null);
    toast.success("Checkpoint scored", {
      description: `${checkpoint.result.previous_band} → ${checkpoint.result.current_band}`,
    });
  }

  async function handleRetryCheckpoint() {
    const current = assessment;
    if (!current) return;
    setIsSubmitting(true);
    try {
      await runCheckpoint(current);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not process the checkpoint.";
      toast.error("Checkpoint failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRefreshReview() {
    const reviewSessionId = assessment?.review_session_id;
    const documentId = document?.document_id;
    if (!reviewSessionId || !documentId) return;
    setIsSubmitting(true);
    try {
      const refreshed = await resumeDocumentReview(
        documentId,
        reviewSessionId,
      );
      setAssessment(refreshed);
      toast.success("Review state refreshed");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not refresh the review.";
      toast.error("Refresh failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSubmit() {
    if (!question || !answer.trim() || !assessment || !llm || !document) return;
    setIsSubmitting(true);
    const sessionId = assessment.review_session_id;
    const sessionVersion = assessment.session_version;
    if (!sessionId || !sessionVersion) {
      toast.error("Start a new assessment to use checkpointed remediation.");
      setIsSubmitting(false);
      return;
    }
    try {
      const recorded = await recordRemediationAnswer(
        sessionId,
        sessionVersion,
        crypto.randomUUID(),
        answer.trim(),
      );
      appendHistory({ question, answer: answer.trim() });
      setAnswer("");
      setPendingCount(recorded.turn.pending_answer_count);
      const recordedAssessment = {
        ...assessment,
        next_question: recorded.turn.next_question,
        review_session_id: recorded.review_session_id,
        session_version: recorded.session_version,
        workflow_state: recorded.workflow_state,
        next_action: recorded.next_action,
      };
      setAssessment(recordedAssessment);
      if (recorded.turn.checkpoint_due) {
        await runCheckpoint(recordedAssessment);
      } else {
        toast.success("Answer saved", {
          description: `${recorded.turn.pending_answer_count} of 5 answers collected`,
        });
      }
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not rescore the document.";
      toast.error("Rescoring failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handlePreviewRevision() {
    if (!assessment || !document || !assessment.review_session_id || !assessment.session_version || assessment.supplemental_answers.length === 0) return;
    setIsSubmitting(true);
    try {
      const preview = await previewRevision(
        document.document_id,
        assessment.review_session_id,
        assessment.session_version,
        crypto.randomUUID(),
        assessment.supplemental_answers,
      );
      setRevisionPreview(preview);
      setAssessment({
        ...assessment,
        review_session_id: preview.review_session_id,
        session_version: preview.session_version,
        workflow_state: preview.workflow_state,
        next_action: preview.next_action,
      });
      setRevisionActions(
        Object.fromEntries(
          preview.edits.map((edit) => [
            edit.edit_id,
            edit.target_section ? "integrate" : "audit_only",
          ]),
        ),
      );
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not preview the revision.";
      toast.error("Revision preview failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateRevision() {
    if (!revisionPreview || !assessment || !document || !llm || !assessment.review_session_id || !assessment.session_version) return;
    setIsSubmitting(true);
    try {
      const revised = await createRevision(
        document.document_id,
        assessment.review_session_id,
        assessment.session_version,
        crypto.randomUUID(),
        revisionPreview.plan_id,
        revisionActions,
        llm,
      );
      setDocument({
        document_id: revised.document_id,
        filename: revised.filename,
        source_type: revised.filename.split(".").pop() ?? "",
      });
      setAssessment(revised.assessment);
      setRevisionDownload(documentDownloadUrl(revised.document_id));
      setRevisionPreview(null);
      toast.success("Revised copy created and reassessed", {
        description: revised.assessment.report.headline,
      });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not create the revised copy.";
      toast.error("Revision failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageCircleQuestion className="h-4 w-4" />
          Remediation loop
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          One question at a time. Answers are processed together at a checkpoint,
          avoiding repeated full-document extraction.
        </p>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {history.length > 0 && (
          <ScrollArea className="max-h-56 rounded-md border p-3">
            <div className="space-y-3">
              {history.map((turn, index) => (
                <div key={index} className="space-y-1 text-sm">
                  <p className="font-medium text-foreground">{turn.question.question}</p>
                  <p className="rounded-md bg-muted px-2 py-1.5 text-muted-foreground">
                    {turn.answer}
                  </p>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}

        {question && (nextAction === "ask_question" || !nextAction) ? (
          <div className="space-y-3">
            {history.length > 0 && <Separator />}
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className="text-[10px]">
                  {question.criterion_name}
                </Badge>
                {question.is_gate && (
                  <Badge
                    variant="outline"
                    className="border-red-200 bg-red-50 text-[10px] text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
                  >
                    Blocking gate
                  </Badge>
                )}
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[10px]",
                    BAND_STYLES[question.band_if_answered]?.className,
                  )}
                >
                  Answering unlocks: {BAND_STYLES[question.band_if_answered]?.label}
                </Badge>
              </div>
              <p className="text-sm font-medium">{question.question}</p>
              {question.answer_requirements.map((requirement) => (
                <p key={requirement} className="text-xs text-muted-foreground">
                  {requirement}
                </p>
              ))}
              {question.unblocks_consumers.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {question.unblocks_consumers.map((consumer) => (
                    <Badge key={consumer} variant="secondary" className="text-[10px]">
                      Unblocks {CONSUMER_LABELS[consumer as Consumer] ?? consumer}
                    </Badge>
                  ))}
                </div>
              )}
              {pendingCount > 0 && (
                <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
                  {pendingCount} pending answer{pendingCount === 1 ? "" : "s"}; score updates at the next checkpoint.
                </p>
              )}
            </div>

            <Textarea
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="Type your answer..."
              rows={4}
              disabled={isSubmitting}
            />
            <Button
              className="w-full"
              onClick={handleSubmit}
              disabled={!answer.trim() || isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Saving&hellip;
                </>
              ) : (
                <>
                  <SendHorizontal className="h-4 w-4" />
                  Save answer
                </>
              )}
            </Button>
          </div>
        ) : nextAction === "prepare_checkpoint" || nextAction === "submit_delta" ? (
          <div className="space-y-4 rounded-md border border-amber-300 bg-amber-50/50 p-5 dark:border-amber-900 dark:bg-amber-950/20">
            <div className="space-y-1 text-center">
              <p className="text-sm font-medium">Checkpoint required</p>
              <p className="text-xs text-muted-foreground">
                Your answers are saved. Process the pending answer delta before continuing.
              </p>
            </div>
            <Button className="w-full" onClick={handleRetryCheckpoint} disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Process checkpoint
            </Button>
            <Button variant="outline" className="w-full" onClick={handleRefreshReview} disabled={isSubmitting}>
              Refresh saved state
            </Button>
          </div>
        ) : (
          <div className="space-y-4 rounded-md border border-dashed p-5">
            <div className="flex flex-col items-center gap-2 text-center">
              <CheckCircle2 className="h-6 w-6 text-emerald-600" />
              <p className="text-sm font-medium">No material question remains</p>
              <p className="text-xs text-muted-foreground">
                Create a new copy that integrates the approved clarifications,
                then reassess that artifact without conversational evidence.
              </p>
            </div>
            {assessment.supplemental_answers.length > 0 && !revisionPreview && (
              <Button className="w-full" onClick={handlePreviewRevision} disabled={isSubmitting}>
                <FilePenLine className="h-4 w-4" />
                Preview revised copy
              </Button>
            )}
            {revisionPreview && (
              <div className="space-y-3">
                {revisionPreview.edits.map((edit) => (
                  <div key={edit.edit_id} className="space-y-2 rounded-md border bg-muted/30 p-3 text-xs">
                    <p className="font-medium">{edit.target_section ?? "No matching section"}</p>
                    {edit.existing_excerpt && (
                      <p className="text-muted-foreground">Existing: {edit.existing_excerpt}</p>
                    )}
                    <p>Proposed: {edit.answer}</p>
                    {edit.conflicts.map((conflict) => (
                      <p key={conflict.conflict_id} className="text-amber-700 dark:text-amber-300">
                        {conflict.message}
                      </p>
                    ))}
                    <select
                      className="w-full rounded-md border bg-background px-2 py-1.5"
                      value={revisionActions[edit.edit_id]}
                      onChange={(event) =>
                        setRevisionActions((current) => ({
                          ...current,
                          [edit.edit_id]: event.target.value as RevisionAction,
                        }))
                      }
                    >
                      {edit.target_section && <option value="integrate">Integrate into section</option>}
                      <option value="audit_only">Audit appendix only</option>
                      <option value="skip">Skip</option>
                    </select>
                  </div>
                ))}
                <Button className="w-full" onClick={handleCreateRevision} disabled={isSubmitting}>
                  {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FilePenLine className="h-4 w-4" />}
                  Create copy and reassess
                </Button>
              </div>
            )}
            {revisionDownload && (
              <Button asChild variant="outline" className="w-full">
                <a href={revisionDownload}>
                  <Download className="h-4 w-4" />
                  Download revised PRD
                </a>
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
