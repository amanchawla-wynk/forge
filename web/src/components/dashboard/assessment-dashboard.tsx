"use client";

import { useAppStore } from "@/lib/store";
import { WarningsBanner } from "@/components/dashboard/warnings-banner";
import { BandSummaryCard } from "@/components/dashboard/band-summary-card";
import { ConsumerGrid } from "@/components/dashboard/consumer-grid";
import { GapsPanel } from "@/components/dashboard/gaps-panel";
import { ConversationPanel } from "@/components/dashboard/conversation-panel";
import { DeepReviewPanel } from "@/components/dashboard/deep-review-panel";
import { Badge } from "@/components/ui/badge";

export function AssessmentDashboard() {
  const assessment = useAppStore((state) => state.assessment);
  if (!assessment) return null;

  const allWarnings = [
    ...assessment.warnings,
    ...(assessment.disputed_criteria.length > 0
      ? [
          `Extraction runs disagreed on: ${assessment.disputed_criteria.join(", ")}. ` +
            (assessment.recommended_additional_runs > 0
              ? `Consider ${assessment.recommended_additional_runs} more full run(s) for stability.`
              : "Confidence reflects that disagreement."),
        ]
      : []),
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        {assessment.deep_review && <DeepReviewPanel review={assessment.deep_review} />}
        <WarningsBanner warnings={allWarnings} />
        <BandSummaryCard response={assessment} />
        <ConsumerGrid consumers={assessment.assessment.consumers} />
        <GapsPanel criteria={assessment.assessment.criteria} />
        {assessment.client_models.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>Model(s) used:</span>
            {[...new Set(assessment.client_models)].map((model) => (
              <Badge key={model} variant="outline" className="text-[10px]">
                {model}
              </Badge>
            ))}
          </div>
        )}
      </div>
      <div className="lg:sticky lg:top-20 lg:col-span-1 lg:h-fit">
        <ConversationPanel />
      </div>
    </div>
  );
}
