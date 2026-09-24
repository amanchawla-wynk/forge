"use client";

import { useState } from "react";
import { Loader2, PlugZap, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConnectModelDialog } from "@/components/connect-model-dialog";
import { DocumentUpload } from "@/components/setup/document-upload";
import { ApiError, createAssessment, uploadDocument } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { PROVIDER_LABELS } from "@/lib/types";

export function SetupPanel() {
  const llm = useAppStore((state) => state.llm);
  const setDocument = useAppStore((state) => state.setDocument);
  const setAssessment = useAppStore((state) => state.setAssessment);

  const [file, setFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const canSubmit = Boolean(llm && file);

  async function handleSubmit() {
    if (!file || !llm) return;
    setIsSubmitting(true);
    try {
      const uploaded = await uploadDocument(file);
      setDocument(uploaded);

      const assessment = await createAssessment({
        document_id: uploaded.document_id,
        llm,
        supplemental_answers: [],
      });
      setAssessment(assessment);
      toast.success("Assessment complete", {
        description: `${assessment.report.headline} · ${assessment.run_count} extraction run(s).`,
      });
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Could not reach the local Forge dashboard backend. Is it running on port 8000?";
      toast.error("Assessment failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center py-10">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          Assess a PRD
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Bring your own API key, upload a document, and get an evidence-based
          readiness assessment &mdash; entirely on your machine.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. Connect a model</CardTitle>
          <CardDescription>
            Forge extracts facts and quotes with your model; scoring itself
            stays deterministic and never sees your key.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {llm ? (
            <div className="flex items-center justify-between rounded-lg border bg-emerald-50 px-4 py-3 text-sm dark:bg-emerald-950/30">
              <div className="flex items-center gap-2">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="font-medium text-emerald-900 dark:text-emerald-300">
                  Connected to {PROVIDER_LABELS[llm.provider]}
                  {llm.model ? ` · ${llm.model}` : ""}
                </span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setDialogOpen(true)}>
                Change
              </Button>
            </div>
          ) : (
            <Button variant="outline" className="w-full" onClick={() => setDialogOpen(true)}>
              <PlugZap className="h-4 w-4" />
              Connect a model
            </Button>
          )}
        </CardContent>
      </Card>

      <div className="py-4" />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. Upload your PRD</CardTitle>
          <CardDescription>
            PDF, DOCX, Markdown, or plain text.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DocumentUpload file={file} onChange={setFile} />
        </CardContent>
      </Card>

      <Button
        size="lg"
        className="mt-6 w-full"
        disabled={!canSubmit || isSubmitting}
        onClick={handleSubmit}
      >
        {isSubmitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Running extraction &amp; scoring&hellip;
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4" />
            Assess PRD
          </>
        )}
      </Button>
      <p className="mt-3 text-center text-xs text-muted-foreground">
        Forge is a source-backed expert baseline, not an organization-validated
        rubric. Treat results as advisory, not an approval gate.
      </p>

      <ConnectModelDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
