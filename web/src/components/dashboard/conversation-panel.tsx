"use client";

import { useState } from "react";
import { CheckCircle2, Loader2, MessageCircleQuestion, SendHorizontal } from "lucide-react";
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
import { ApiError, createAssessment } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { BAND_STYLES, CONSUMER_LABELS, type Consumer } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ConversationPanel() {
  const llm = useAppStore((state) => state.llm);
  const document = useAppStore((state) => state.document);
  const assessment = useAppStore((state) => state.assessment);
  const history = useAppStore((state) => state.history);
  const setAssessment = useAppStore((state) => state.setAssessment);
  const appendHistory = useAppStore((state) => state.appendHistory);

  const [answer, setAnswer] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!assessment || !llm || !document) return null;
  const question = assessment.next_question;

  async function handleSubmit() {
    if (!question || !answer.trim() || !assessment || !llm || !document) return;
    setIsSubmitting(true);
    const nextAnswers = [
      ...assessment.supplemental_answers,
      {
        criterion_id: question.criterion_id,
        answer: answer.trim(),
        requirement_quote: question.requirement_quote,
        edge_case_id: question.edge_case_id,
        taxonomy_version: question.taxonomy_version,
      },
    ];
    try {
      const updated = await createAssessment({
        document_id: document.document_id,
        llm,
        supplemental_answers: nextAnswers,
        framing: assessment.framing,
        edge_case_coverage: assessment.edge_case_coverage,
      });
      appendHistory({ question, answer: answer.trim() });
      setAssessment(updated);
      setAnswer("");
      toast.success("Rescored", {
        description: `${updated.report.headline}`,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not rescore the document.";
      toast.error("Rescoring failed", { description: message });
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
          One highest-impact question at a time. Each answer is retained as
          supplemental evidence and the document is rescored.
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

        {question ? (
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
                  Rescoring&hellip;
                </>
              ) : (
                <>
                  <SendHorizontal className="h-4 w-4" />
                  Submit answer &amp; rescore
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-md border border-dashed p-6 text-center">
            <CheckCircle2 className="h-6 w-6 text-emerald-600" />
            <p className="text-sm font-medium">No material question remains</p>
            <p className="text-xs text-muted-foreground">
              Every applicable rubric criterion has been addressed for this
              document and its supplemental answers.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
