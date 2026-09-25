import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { DeepReviewReport } from "@/lib/types";

interface DeepReviewPanelProps {
  review: DeepReviewReport;
}

export function DeepReviewPanel({ review }: DeepReviewPanelProps) {
  return (
    <Card className="overflow-hidden border-slate-300 bg-slate-950 text-slate-50 dark:border-slate-700">
      <CardHeader className="border-b border-white/10 bg-[radial-gradient(circle_at_top_right,rgba(245,158,11,0.18),transparent_44%)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">
              Deep review
            </p>
            <CardTitle className="mt-1 text-2xl text-white">
              What prevents correct implementation
            </CardTitle>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
              {review.summary}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge className="border-white/15 bg-white/5 text-slate-200" variant="outline">
              {review.claims.length} verified claims
            </Badge>
            <Badge className="border-white/15 bg-white/5 text-slate-200" variant="outline">
              {review.graph.nodes.length} graph nodes
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        {review.findings.length === 0 ? (
          <div className="flex gap-3 rounded-lg border border-emerald-400/20 bg-emerald-400/5 p-4">
            <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-300" />
            <div>
              <p className="font-medium text-emerald-100">No mechanical conflict found</p>
              <p className="mt-1 text-sm text-slate-300">
                Checks cover numeric ranges, named skip thresholds, timelines,
                event-based metric formulas, and classified precedence, scope, and
                supersession conflicts between paired statements.
              </p>
            </div>
          </div>
        ) : (
          review.findings.map((finding, index) => (
            <article
              key={finding.finding_id}
              className="rounded-lg border border-amber-300/20 bg-white/[0.035] p-4"
            >
              <div className="flex items-start gap-3">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-amber-300 font-mono text-xs font-bold text-slate-950">
                  {index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-semibold text-white">{finding.title}</h3>
                    <Badge className="border-amber-300/25 text-amber-200" variant="outline">
                      {finding.confidence === "classified"
                        ? "classified"
                        : "proved"}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm leading-6 text-slate-300">{finding.summary}</p>

                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <ReviewDetail
                      label="Implementation consequence"
                      value={finding.implementation_consequence}
                    />
                    <ReviewDetail label="Decision required" value={finding.required_decision} />
                  </div>

                  <div className="mt-3 space-y-2">
                    {finding.evidence.map((evidence) => (
                      <blockquote
                        key={evidence.claim_id}
                        className="border-l-2 border-amber-300/50 pl-3 text-sm italic leading-6 text-slate-200"
                      >
                        &ldquo;{evidence.quote}&rdquo;
                        <span className="ml-2 not-italic text-slate-500">
                          {evidence.page
                            ? `Page ${evidence.page}`
                            : evidence.section ?? evidence.source_block_id}
                        </span>
                      </blockquote>
                    ))}
                  </div>

                  {finding.affected_consumers.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      <AlertTriangle className="size-3.5 text-amber-300" />
                      {finding.affected_consumers.map((consumer) => (
                        <Badge
                          key={consumer}
                          className="border-white/10 text-[10px] uppercase text-slate-300"
                          variant="outline"
                        >
                          {consumer}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </article>
          ))
        )}
        <p className="text-xs text-slate-500">
          Advisory finding set. It does not change the deterministic readiness score.
        </p>
      </CardContent>
    </Card>
  );
}

function ReviewDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-black/20 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-sm leading-5 text-slate-200">{value}</p>
    </div>
  );
}
